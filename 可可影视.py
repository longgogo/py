# -*- coding: utf-8 -*-
"""
可可影视（www.kkys19.com）TVBox Python Spider —— 影视仓 / OK影视（修复版）
原文件：桌面/可可影视.py —— 保持原样不动，本文件为修复后的独立副本。

【2026-11-12 实测站点结构（全部 200 可用）】
  首页      /
  分类页    /show/{tid}-{类型}-{地区}-{语言}-{年份}-{排序}-{页码}.html   18 条/页
  频道 id   1=电影 2=连续剧 3=动漫 4=综艺纪录 6=短剧
  今日更新  /label/new.html                                            24 条
  详情页    /detail/{id}.html
  播放页    /play/{id}-{线路sid}-{剧集eid}.html   内嵌 src: "https://…/index.m3u8"
  搜索      /search?k={关键词}&page={页码}&t={token}
            token 来自任意页面 <input type="hidden" name="t" value="…">
  筛选行    /show 页 <div class="filter-row-side"><strong>标签</strong> + a.filter-item

【本次修复的问题（按实测逐条核对）】
  1. ★核心故障：详情页剧集链接真实写法是
         <a href="/play/380666-35-5774282.html"\n        class="episode-item" ... ><span>1080P</span></a>
     href 与 class 之间夹着换行+缩进，旧正则写成 '<a href="..." class="episode-item"'
     （单空格）→ 18 个线路块全部匹配 0 集 → vod_play_url 退化成 '#'
     → app 里能进详情但点播无反应，旧脚本本地运行更是直接 IndexError 崩溃。
     改为「按 <a> 标签分块 + 属性顺序/空白无关」提取。
  2. 播放页第一条"4K"线路是 APP 专属（弹窗"当前线路仅供APP端观看"，src: ""），
     其余线路（sid=2/4/9/27…）直出 m3u8。playerContent 遇到空 src 时自动
     从该播放页的其它线路链接里探测可用地址（最多 3 条），不再返回空地址。
  3. 网络层：旧 _get 不检查 HTTP 状态码，523/错误页会被当正常 HTML 解析。
     现在校验状态码 + 错误页特征，连续失败短路并 60s 冷却；支持备用域名切换。
  4. categoryContent 空列表时仍返回 pagecount=9999，app 会无限翻页 → 列表空时收敛。
  5. 搜索解析兜底：旧兜底用的 v-item 正则对 search-result-item 模板无效
     （实测命中 0）→ 增加通用详情锚点分块提取；token 提取改为属性顺序无关。
  6. 按《猎手影视.py》规范加固：_ensure() 防止 app 未调 init、isVideoFormat
     支持带 ? 参数的地址、线路数与 $$$ 段数强制相等、所有公开方法 try/except。
  7. 换域名不用改代码：init 支持 extend={"host":"https://新域名"} 或 URL 字符串。

【部署提醒】app 加载的是服务器副本，改完需重新上传覆盖服务器同名 .py，
并刷新配置/清缓存。
"""
import sys
import os
import re
import json
import time
import urllib.parse

# ---- base Spider 导入：app 内有 base.spider，本地测试走 fallback ----
try:
    from base.spider import Spider
except Exception:
    class Spider:
        """本地测试用最小实现（支持 headers / data / allow_redirects / status_code）"""

        def __init__(self):
            self.headers = {}

        def fetch(self, url, headers=None, data=None, method='GET', timeout=10, **kwargs):
            import urllib.request
            import urllib.error
            import ssl
            import gzip
            try:
                ssl._create_default_https_context = ssl._create_unverified_context
            except Exception:
                pass
            h = dict(self.headers)
            if headers:
                h.update(headers)
            if data is not None and method == 'GET':
                method = 'POST'
            req = urllib.request.Request(url, headers=h, method=method)
            if data is not None:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                req.data = data
            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                resp = e
            try:
                body = resp.read()
            except Exception:
                body = b''
            if body[:2] == b'\x1f\x8b':
                try:
                    body = gzip.decompress(body)
                except Exception:
                    pass

            class R:
                pass

            r = R()
            r.text = body.decode('utf-8', 'replace')
            r.content = body
            try:
                r.status_code = resp.getcode()
            except Exception:
                r.status_code = 200
            try:
                r.headers = dict(resp.headers)
            except Exception:
                r.headers = {}

            def to_json():
                return json.loads(r.text)

            r.json = to_json
            return r


class Spider(Spider):

    # ------------------------------------------------------------ 初始化
    def getName(self):
        return '可可影视'

    def log(self, *args):
        # 子类自带日志，绝不依赖 base Spider 的 log
        try:
            print('[kkys]', *args)
        except Exception:
            pass

    def _parse_extend(self, extend):
        """兼容 app 传 dict / JSON 字符串 / 空值"""
        if isinstance(extend, str):
            try:
                return json.loads(extend) if extend.strip() else {}
            except Exception:
                return {}
        return extend if isinstance(extend, dict) else {}

    def _ensure(self):
        """有些 app 实例化后直接调 homeContent 而未调 init —— 兜底初始化一次"""
        if not getattr(self, '_ready', False):
            try:
                self.init('')
            except Exception as e:
                self.log('init fallback error:', e)
            self._ready = True

    def init(self, extend=''):
        ext = self._parse_extend(extend)
        custom = ''
        if isinstance(extend, str) and extend.strip().lower().startswith('http'):
            custom = extend.strip().rstrip('/')
        else:
            custom = str(ext.get('host') or ext.get('domain') or ext.get('域名') or '').strip().rstrip('/')
        if custom and not custom.lower().startswith('http'):
            custom = 'https://' + custom

        self.host = custom or 'https://www.kkys19.com'
        self.host_candidates = []
        for h in (self.host, 'https://www.kkys19.com', 'https://kkys19.com'):
            if h and h not in self.host_candidates:
                self.host_candidates.append(h)

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        # 频道 id（2026-11-12 逐个实测 /show/{id}------1.html 均 200 且有 18 条）
        self.categories = {
            '电影': '1',
            '连续剧': '2',
            '动漫': '3',
            '综艺纪录': '4',
            '短剧': '6',
        }
        # 筛选行 -> URL 字段下标（/show/{tid}-类型-地区-语言-年份-排序-页码.html）
        self.filter_map = {'类型': 'class', '地区': 'area', '语言': 'lang',
                           '年份': 'year', '排序': 'order'}
        self._filter_cache = {}
        self._token_cache = ''
        self._fail = 0
        self._fail_at = 0
        self._max_fail = 3
        self._host_checked = False
        self._ready = True

    # ------------------------------------------------------------ 规定方法集
    def isVideoFormat(self, url):
        return bool(re.search(r'https?://.+\.(?:m3u8|mp4|flv)(?:\?|$)', url or ''))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        return None

    # ------------------------------------------------------------ 网络层
    def _text(self, resp):
        try:
            t = resp.text
        except Exception:
            t = ''
        if isinstance(t, bytes):
            t = t.decode('utf-8', 'replace')
        return t or ''

    def _status(self, resp):
        try:
            return int(getattr(resp, 'status_code', 0) or 0)
        except Exception:
            return 0

    def _is_bad(self, html):
        if not html:
            return True
        low = html[:600].lower()
        return ('origin is unreachable' in low or 'error 523' in low or
                ('cloudflare' in low and len(html) < 3000))

    def _switch_host(self):
        """主域名连续失败时惰性探测一次备用域名"""
        if self._host_checked:
            return
        self._host_checked = True
        for h in self.host_candidates:
            if h == self.host:
                continue
            try:
                r = self.fetch(h + '/', headers=dict(self.headers))
                html = self._text(r)
                code = self._status(r)
                if (not code or 200 <= code < 300) and len(html) > 1000 and not self._is_bad(html):
                    self.log('备用域名可用，已切换:', h)
                    self.host = h
                    self.headers['Referer'] = h + '/'
                    self._fail = 0
                    return
            except Exception:
                continue

    def _get(self, url, extra=None):
        """带一次重试的 GET；校验状态码与错误页；连续失败短路 + 60s 冷却"""
        try:
            now = time.time()
            if self._fail >= self._max_fail:
                if now - self._fail_at > 60:
                    self._fail = 0
                    self._host_checked = False
                else:
                    return ''
        except Exception:
            pass
        hd = dict(self.headers)
        if extra:
            hd.update(extra)
        for i in range(2):
            try:
                resp = self.fetch(url, headers=hd)
                html = self._text(resp)
                code = self._status(resp)
                if (code and not (200 <= code < 300)) or self._is_bad(html):
                    raise RuntimeError('bad response %s' % code)
                self._fail = 0
                return html
            except Exception as e:
                self._fail += 1
                try:
                    self._fail_at = time.time()
                except Exception:
                    pass
                self.log('fetch error(%d):' % i, url, e)
                if self._fail >= self._max_fail:
                    self._switch_host()
                    return ''
        return ''

    # ------------------------------------------------------------ 通用工具
    def _abs(self, url):
        if not url:
            return ''
        url = str(url).strip()
        if url.startswith('http'):
            return url
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.host + url
        return url

    def _clean(self, s):
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s or '')).strip()

    # ------------------------------------------------------------ 列表解析
    def _extract_list(self, html):
        """列表项提取。返回 (vod_id, vod_name, vod_pic, vod_remarks)。
        主路径：本站 v-item 卡片（实测 18/页）；
        兜底：按详情锚点分块、属性顺序无关（搜索结果模板同样适用）。"""
        out = []
        if not html:
            return out
        for m in re.finditer(
                r'<a\s+href="(/detail/\d+\.html)"\s+class="v-item">([\s\S]{0,3000}?)</a>', html):
            href, blk = m.group(1), m.group(2)
            cov = re.search(r'<div class="v-item-cover"[\s\S]*?</div>', blk)
            seg = cov.group(0) if cov else blk
            pic = ''
            for p in re.findall(r'data-original="([^"]+)"', seg):
                if 'logo_placeholder' not in p:
                    pic = self._abs(p)
                    break
            vis = re.findall(r'<div class="v-item-title">([^<]*)</div>', blk)
            if not vis:
                vis = [t for t in re.findall(r'<div class="v-item-title"[^>]*>([^<]*)</div>', blk)
                       if 'kekys' not in t and 'kkys' not in t]
            name = self._clean(vis[0]) if vis else ''
            rem = re.search(r'<div class="v-item-bottom">\s*<span>\s*([^<]*?)\s*</span>', blk)
            out.append((href, name, pic, self._clean(rem.group(1)) if rem else ''))
        if out:
            return out

        # 兜底：任一 /detail/{id}.html 锚点分块（属性顺序、换行、模板均无关）
        anchors = list(re.finditer(
            r'<a\b[^>]*href="([^"]*?/detail/\d+\.html)"[^>]*>', html, re.I))
        for i, m in enumerate(anchors):
            end = anchors[i + 1].start() if i + 1 < len(anchors) else len(html)
            seg = html[m.start():min(end, m.start() + 2500)]
            pm = re.search(r'(?:data-original|data-src|src)="([^"]+)"', seg, re.I)
            if not pm:
                continue
            tm = re.search(r'title="([^"]*)"', seg)
            if not tm:
                tm = re.search(r'class="(?:title|v-item-title)"[^>]*>\s*([^<]*?)\s*<', seg)
            name = self._clean(tm.group(1) if tm else '')
            if not name:
                continue
            pic = pm.group(1).strip()
            if 'logo_placeholder' in pic or pic.startswith('data:'):
                pic = ''
            rm = re.search(r'<span[^>]*>\s*([^<]*?)\s*</span>', seg)
            out.append((m.group(1), name, self._abs(pic),
                        self._clean(rm.group(1)) if rm else ''))
        return out

    def _to_videos(self, items):
        return [{'vod_id': i[0], 'vod_name': i[1], 'vod_pic': i[2],
                 'vod_remarks': i[3]} for i in items]

    # ------------------------------------------------------------ 筛选项
    def _get_filters(self, tid):
        if tid in self._filter_cache:
            return self._filter_cache[tid]
        filters = []
        try:
            html = self._get('%s/show/%s------1.html' % (self.host, tid))
            for row in re.finditer(r'<div class="filter-row-side">\s*<strong>([^<:：]*)', html):
                label = row.group(1).strip()
                key = self.filter_map.get(label)
                if not key:
                    continue
                tail = html[row.end():row.end() + 6000]
                end = tail.find('<div class="filter-row-side">')
                seg = tail[:end] if end > 0 else tail
                opts = []
                for a in re.finditer(r'href="(/show/[^"]+)"\s*\n?\s*class="filter-item[^"]*">([^<]*)</a>', seg):
                    href, name = a.group(1), self._clean(a.group(2))
                    path = urllib.parse.unquote(href.replace('/show/', '').replace('.html', ''))
                    parts = path.split('-')
                    keys = ['class', 'area', 'lang', 'year', 'order']
                    val = parts[1] if len(parts) == 2 else (
                        parts[1 + keys.index(key)] if len(parts) >= 6 else '')
                    opts.append({'n': name, 'v': val})
                if opts:
                    filters.append({'key': key, 'name': label, 'value': opts})
        except Exception as e:
            self.log('filters error:', tid, e)
        self._filter_cache[tid] = filters
        return filters

    # ------------------------------------------------------------ 标准方法
    def homeContent(self, filter):
        self._ensure()
        try:
            classes = [{'type_name': n, 'type_id': t} for n, t in self.categories.items()]
            filters = {}
            fail = 0
            for name, tid in self.categories.items():
                try:
                    f = self._get_filters(tid)
                    if f:
                        filters[tid] = f
                        fail = 0
                    else:
                        fail += 1
                except Exception as e:
                    self.log('homeContent filters error:', tid, e)
                    fail += 1
                if fail >= 2:
                    break
            return {'class': classes, 'filters': filters}
        except Exception as e:
            self.log('homeContent error:', e)
            return {'class': [], 'filters': {}}

    def homeVideoContent(self):
        self._ensure()
        try:
            html = self._get(self.host + '/label/new.html')
            return {'list': self._to_videos(self._extract_list(html)) if html else []}
        except Exception as e:
            self.log('homeVideoContent error:', e)
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        self._ensure()
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        extend = self._parse_extend(extend)
        try:
            path = str(tid)
            if path in self.categories:
                path = self.categories[path]
            else:
                path = path.strip('/').split('/')[-1].replace('.html', '')

            def val(k):
                v = extend.get(k, '')
                v = v if isinstance(v, str) else ''
                return urllib.parse.quote(v) if v else ''

            url = '%s/show/%s-%s-%s-%s-%s-%s-%d.html' % (
                self.host, path, val('class'), val('area'), val('lang'),
                val('year'), val('order'), pg)
            html = self._get(url)
            if not html:
                html = self._get('%s/show/%s------%d.html' % (self.host, path, pg))
            videos = self._to_videos(self._extract_list(html)) if html else []
            return {'list': videos, 'page': pg,
                    'pagecount': 9999 if videos else max(1, pg - 1),
                    'limit': 18, 'total': 999999 if videos else 0}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 18, 'total': 0}

    # ------------------------------------------------------------ 播放列表解析
    def _eps_from_block(self, blk):
        """★ 核心修复：按 <a> 标签分块提取，属性顺序 / 换行 / 缩进全部无关。
        真实 HTML：<a href="/play/380666-35-5774282.html"\n   class="episode-item" ...
                    ><span>1080P</span></a>"""
        eps = []
        for a in re.finditer(r'<a\b([^>]*)>(.*?)</a>', blk, re.S | re.I):
            attrs, body = a.group(1), a.group(2)
            hm = re.search(r'href\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
            if not hm or '/play/' not in hm.group(1):
                continue
            sm = re.search(r'<span[^>]*>\s*([^<]*?)\s*</span>', body, re.S)
            nm = self._clean(sm.group(1) if sm else body) or ('第%d集' % (len(eps) + 1))
            ep = (nm, self._abs(hm.group(1)))
            if ep not in eps:
                eps.append(ep)
        return eps

    def _parse_plays(self, html):
        """返回 (线路名列表, 每线路 '集名$地址' 用 # 连接的列表)，两者长度严格相等"""
        labels = re.findall(r'class="source-item-label">([^<]+)<', html)
        if not labels:
            labels = [self._clean(x) for x in re.findall(
                r'<span[^>]*class="source-item-label"[^>]*>([^<]+)</span>', html)]
        blocks = re.findall(
            r'<div class="episode-list"(?:\s+style="[^"]*")?>(.*?)</div>', html, re.S)
        if not blocks:
            parts = re.split(r'<div[^>]*class="episode-list[^"]*"[^>]*>', html)
            blocks = []
            for p in parts[1:]:
                e = p.find('</div>')
                blocks.append(p[:e] if e > 0 else p[:4000])
        play_from, play_url = [], []
        for i, blk in enumerate(blocks):
            eps = self._eps_from_block(blk)
            if not eps:
                continue
            lab = self._clean(labels[i]) if i < len(labels) else ('线路%d' % (i + 1))
            play_from.append(lab or ('线路%d' % (i + 1)))
            play_url.append('#'.join(['%s$%s' % (n, u) for n, u in eps]))
        n = min(len(play_from), len(play_url))
        play_from, play_url = play_from[:n], play_url[:n]
        if not play_from:
            return ['可可影视'], ['#']
        return play_from, play_url

    # ------------------------------------------------------------ 详情
    def detailContent(self, ids):
        self._ensure()
        try:
            raw = ids[0] if isinstance(ids, (list, tuple)) else ids
            raw = str(raw or '').strip()
            url = self._abs(raw)
            if not url.startswith('http'):
                url = self.host + '/detail/%s.html' % raw.replace('.html', '')
            html = self._get(url)
            if not html:
                return {'list': []}

            strongs = re.findall(r'<div class="detail-title">([\s\S]*?)</div>', html)
            name = ''
            if strongs:
                ss = [self._clean(s) for s in re.findall(r'<strong>([^<]*)</strong>', strongs[0])
                      if self._clean(s)]
                if len(ss) >= 2:
                    name = ss[1]
                elif ss:
                    name = ss[0]
            if not name or 'kkys' in name.lower() or 'kekys' in name.lower():
                t = re.search(r'<title>(.*?)</title>', html, re.S)
                if t:
                    name = re.split(r'[-_|]', t.group(1))[0].strip()

            pic_m = re.search(r'class="detail-pic"[\s\S]{0,800}?data-original="([^"]+)"', html)
            pic = self._abs(pic_m.group(1)) if pic_m else ''
            tags = re.findall(r'class="detail-tags-item">([^<]*)</a>', html)
            year = self._clean(tags[0]) if tags else ''
            area = self._clean(tags[1]) if len(tags) > 1 else ''

            desc_m = re.search(r'<div class="detail-desc">\s*<p>\s*([\s\S]*?)\s*</p>', html)
            content = self._clean(desc_m.group(1)) if desc_m else ''
            if not content:
                d = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html, re.I)
                content = self._clean(d.group(1)) if d else ''

            def info(label):
                m = re.search(r'class="detail-info-row-side">%s:?</div>\s*'
                              r'<div class="detail-info-row-main">([\s\S]*?)</div>' % label, html)
                return self._clean(m.group(1)) if m else ''

            play_from, play_url = self._parse_plays(html)
            # 首线路若为「仅供 APP 端观看」的空 src 线路（实测"4K"线路会弹此提示），
            # 直接剔除，避免 app 默认选中后点播无反应 / 自动换线路时落到别的集。
            if play_url and play_url[0] and play_url[0] != '#':
                first_ep = play_url[0].split('#')[0].split('$', 1)
                if len(first_ep) == 2:
                    ph = self._get(self._abs(first_ep[1]))
                    if ph and re.search(r'src:\s*["\']\s*["\']', ph) and '仅供APP' in ph:
                        self.log('首线路为 APP 专属，已剔除:', play_from[0])
                        play_from = play_from[1:] or ['可可影视']
                        play_url = play_url[1:] or ['#']
            video = {
                'vod_id': raw,
                'vod_name': name,
                'vod_pic': pic,
                'vod_year': year,
                'vod_area': area,
                'vod_actor': info('演员'),
                'vod_director': info('导演'),
                'vod_remarks': '',
                'vod_content': content,
                'vod_play_from': '$$$'.join(play_from),
                'vod_play_url': '$$$'.join(play_url),
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    # ------------------------------------------------------------ 搜索
    def _get_search_token(self):
        if self._token_cache:
            return self._token_cache
        try:
            html = self._get(self.host + '/')
            for inp in re.findall(r'<input\b[^>]*>', html, re.I):
                if re.search(r'name\s*=\s*["\']t["\']', inp, re.I):
                    vm = re.search(r'value\s*=\s*["\']([^"\']*)["\']', inp, re.I)
                    if vm:
                        self._token_cache = vm.group(1)
                        break
        except Exception as e:
            self.log('token error:', e)
        return self._token_cache

    def _search_url(self, key, pg, token):
        return '%s/search?k=%s&page=%d&t=%s' % (
            self.host, urllib.parse.quote(str(key)), pg,
            urllib.parse.quote(token or '', safe=''))

    def searchContent(self, key, quick, pg=1):
        self._ensure()
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        try:
            kw = str(key or '').strip()
            if not kw:
                return {'list': [], 'page': pg}
            token = self._get_search_token()
            html = self._get(self._search_url(kw, pg, token))
            videos = []
            for m in re.finditer(
                    r'<a\s+href="(/detail/\d+\.html)"\s+class="search-result-item">'
                    r'([\s\S]{0,2500}?)</a>', html):
                blk = m.group(2)
                title = re.search(r'class="title"[^>]*>([^<]*)<', blk)
                if not title:
                    title = re.search(r'title="([^"]*)"', blk)
                if not title:
                    continue
                pic = ''
                for p in re.findall(r'data-original="([^"]+)"', blk):
                    if 'logo_placeholder' not in p:
                        pic = self._abs(p)
                        break
                tag = re.findall(r'class="tags">([\s\S]*?)</div>', blk)
                rem = ' '.join(re.findall(r'<span>([^<]*)</span>', tag[0])[:2]) if tag else ''
                videos.append({'vod_id': m.group(1), 'vod_name': self._clean(title.group(1)),
                               'vod_pic': pic, 'vod_remarks': self._clean(rem)})
            if not videos:
                videos = self._to_videos(self._extract_list(html))
            if not videos:
                # token 可能过期：清空缓存后重取一次
                self._token_cache = ''
                html = self._get(self._search_url(kw, pg, self._get_search_token()))
                for m in re.finditer(
                        r'<a\s+href="(/detail/\d+\.html)"\s+class="search-result-item">'
                        r'([\s\S]{0,2500}?)</a>', html):
                    t = re.search(r'class="title"[^>]*>([^<]*)<', m.group(2))
                    if t:
                        videos.append({'vod_id': m.group(1),
                                       'vod_name': self._clean(t.group(1)),
                                       'vod_pic': '', 'vod_remarks': ''})
                if not videos:
                    videos = self._to_videos(self._extract_list(html))
            return {'list': videos, 'page': pg,
                    'pagecount': 9999 if videos else max(1, pg - 1)}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg}

    # ------------------------------------------------------------ 播放
    def _src_from_play_html(self, html):
        """从播放页取真实地址：src: "https://…/index.m3u8" 或任意 m3u8/mp4 字面量"""
        if not html:
            return ''
        m = re.search(r'src:\s*["\']([^"\']*\.(?:m3u8|mp4)[^"\']*)["\']', html, re.I)
        if not m:
            m = re.search(r'["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', html, re.I)
        if not m:
            return ''
        return m.group(1).replace('\\/', '/').replace('\\u002F', '/').replace('&amp;', '&').strip()

    def playerContent(self, flag, id, vipFlags):
        """播放页直出 m3u8；若命中 APP 专属线路（src 为空），自动探测同播放页
        里的其它线路链接，取第一个可用的直链，避免点了没反应。"""
        self._ensure()
        try:
            raw = str(id or '').strip()
            hd = dict(self.headers)
            if not raw:
                return {'parse': 1, 'url': '', 'header': hd}
            if raw.startswith('magnet:') or self.isVideoFormat(raw):
                return {'parse': 0, 'url': raw, 'header': hd}

            url = self._abs(raw)
            html = self._get(url) if not self.isVideoFormat(url) else ''
            play_url = self._src_from_play_html(html)

            if not play_url and html:
                cands = list(dict.fromkeys(
                    re.findall(r'href="(/play/\d+-\d+-\d+\.html)"', html)))
                for c in cands:
                    if c in url:
                        continue
                    if self._fail >= self._max_fail:
                        break
                    h2 = self._get(self._abs(c))
                    u2 = self._src_from_play_html(h2)
                    if u2:
                        self.log('APP 专属线路，已自动切换到可用线路:', c)
                        play_url = u2
                        break
            if play_url:
                return {'parse': 0, 'url': play_url, 'header': hd}
            # 解析不出直链时把播放页交给 app 的嗅探/官方解析，而不是返回空地址
            return {'parse': 1, 'url': url, 'header': hd}
        except Exception as e:
            self.log('playerContent error:', e)
            return {'parse': 1, 'url': id, 'header': dict(self.headers)}


# ==================================================================== 本地测试
def main():
    sp = Spider()
    sp.init('')
    print('=== homeContent ===')
    r = sp.homeContent(True)
    print('classes:', [(c['type_name'], c['type_id']) for c in r['class']])
    for tid, f in (r.get('filters') or {}).items():
        print('  filter tid=%s -> %s' % (
            tid, ', '.join('%s(%d项)' % (x['name'], len(x['value'])) for x in f)))
    print()
    print('=== homeVideoContent（今日更新）===')
    hv = sp.homeVideoContent()
    print('  %d 项' % len(hv['list']), hv['list'][0] if hv['list'] else None)
    print()
    print('=== categoryContent（全部分类）===')
    for c in r['class']:
        r2 = sp.categoryContent(c['type_id'], 1, {}, {})
        print('  %-6s: %d 项 | 例: %s' % (
            c['type_name'], len(r2['list']),
            r2['list'][0]['vod_name'] if r2['list'] else '-'))
    first_tid = r['class'][0]['type_id'] if r['class'] else '1'
    print()
    print('=== 翻页（第2页必须与第1页不同）===')
    p1 = sp.categoryContent(first_tid, 1, {}, {})
    p2 = sp.categoryContent(first_tid, 2, {}, {})
    print('  p1 first:', p1['list'][0]['vod_id'] if p1['list'] else None)
    print('  p2 first:', p2['list'][0]['vod_id'] if p2['list'] else None)
    print('  分页不同:', bool(p1['list'] and p2['list'] and
                            p1['list'][0]['vod_id'] != p2['list'][0]['vod_id']))
    print()
    print('=== 兼容性：字符串 pg / 字符串 extend ===')
    print('  str pg:', len(sp.categoryContent(first_tid, '1', {}, {})['list']), '项')
    print('  str extend:', len(sp.categoryContent(first_tid, 1, {}, '{}')['list']), '项')
    print()
    print('=== 筛选（类型=喜剧）===')
    f1 = sp.categoryContent(first_tid, 1, {}, {'class': '喜剧'})
    print('  喜剧: %d 项 | 例: %s' % (
        len(f1['list']), f1['list'][0]['vod_name'] if f1['list'] else '-'))
    print()
    print('=== searchContent ===')
    s = sp.searchContent('庆余年', False, 1)
    print('  p1: %d 项' % len(s['list']), s['list'][0] if s['list'] else None)
    s2 = sp.searchContent('庆余年', False, 2)
    print('  p2: %d 项' % len(s2['list']), s2['list'][0] if s2['list'] else None)
    print('  str pg:', len(sp.searchContent('庆余年', False, '1')['list']), '项')
    print()
    print('=== detailContent（电影：核心修复项）===')
    if p1['list']:
        r3 = sp.detailContent([p1['list'][0]['vod_id']])
        if r3['list']:
            v = r3['list'][0]
            froms = v['vod_play_from'].split('$$$')
            urls = v['vod_play_url'].split('$$$')
            print('  name:', v['vod_name'], '| year:', v['vod_year'], '| area:', v['vod_area'])
            print('  线路数:', len(froms), '| $$$段数:', len(urls),
                  '| 一致:', len(froms) == len(urls))
            print('  线路:', froms[:6])
            for f, pu in list(zip(froms, urls))[:3]:
                print('    %-10s %2d 集 | 首集: %s' % (f, len(pu.split('#')),
                                                       pu.split('#')[0][:70]))
            print()
            print('=== playerContent ===')
            ep = urls[0].split('#')[0]
            if '$' in ep:
                r4 = sp.playerContent(froms[0], ep.split('$', 1)[1], None)
                print('  parse:', r4['parse'], '| url:', str(r4['url'])[:130])
            else:
                print('  [FAIL] 播放串缺少 $ 分隔:', ep[:80])
    print()
    print('=== detailContent（连续剧：验多线路多集）===')
    tv = sp.categoryContent('2', 1, {}, {})
    if tv['list']:
        r5 = sp.detailContent([tv['list'][0]['vod_id']])
        if r5['list']:
            v = r5['list'][0]
            froms = v['vod_play_from'].split('$$$')
            urls = v['vod_play_url'].split('$$$')
            print('  name:', v['vod_name'], '| 线路数:', len(froms),
                  '| 段数一致:', len(froms) == len(urls))
            for i, (f, pu) in enumerate(zip(froms, urls)):
                eps = pu.split('#')
                print('    %-10s %2d 集 | 首集: %s' % (f, len(eps), eps[0][:70]))
                if i >= 2:
                    break


if __name__ == '__main__':
    main()
