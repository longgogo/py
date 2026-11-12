# -*- coding: utf-8 -*-
"""
面包网 TVBox Python 源（修复版）  —— 影视仓 / OK影视
站点：https://v.aiwule.com/   苹果CMS(MacCMS) v10 + ewave 模板

【2026-11-12 修复说明】
本版在原脚本基础上做规范加固，原文件保持不变。站点实测结构（独立抓取通道
逐页核对，含带随机参数绕过缓存）：
  首页/分类 : /vodtype/{tid}.html、/vodshow/{tid}-----------.html
  翻页      : /vodshow/{tid}--------{pg}---.html   （实测第 2 页内容不同，格式有效）
  详情      : /voddetail/{vid}.html                （线路名已变为「播放接口6 / 播放接口2」）
  播放      : /vodplay/{vid}-{sid}-{eid}.html
  搜索      : /vodsearch/{wd}-------------.html

【本次实测发现的两个站点级情况（脚本无法根治，只能正确应对）】
  1) /vodsearch/ 全部路径（含路径式、?wd= 式、站内演员搜索链接）当前都会
     返回「系统安全验证」验证码页。该页内含 10 条「热门搜索」/voddetail/
     链接，旧脚本会把它当搜索结果返回 —— 表面"有结果"，实则与关键词无关。
     本版识别验证页后一律视为失败，并多路径兜底（app 端带正常 Cookie/UA
     时可能不触发验证）。
  2) 本机网络到该域名的 TLS 握手被阻断（curl/urllib 均 000；多个公共代理
     返回 Cloudflare 522），但站点本身在线且内容实时更新。这是网络可达性
     问题，不是脚本问题。为此 init() 支持 extend={"host":"https://新域名"}
     换域名，且 main() 内置离线结构自测，网络不通时也能完整验证解析逻辑。

【规范要点】class Spider(Spider)、不调用 base 的 log、方法集齐备、
pg/extend 类型防御、全集方法 try/except、集名$地址 + 集间 # + 线路间 $$$、
线路数与 $$$ 段数严格相等、Referer 随播放头返回。
"""
import re
import json
import time
import base64
import html as html_mod
import urllib.parse

UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1')

try:
    from base.spider import Spider
except Exception:
    class Spider:
        """本地测试用 fallback（app 内由 base.spider 提供真实实现）"""
        def __init__(self):
            self.headers = {}

        def fetch(self, url, headers=None, data=None, method='GET',
                  timeout=12, **kwargs):
            import urllib.request, ssl, gzip
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
                req.data = data.encode('utf-8') if isinstance(data, str) else data
            resp = urllib.request.urlopen(req, timeout=timeout)
            body = resp.read()
            if body[:2] == b'\x1f\x8b':
                body = gzip.decompress(body)

            class R:
                pass
            r = R()
            r.text = body.decode('utf-8', 'replace')
            r.content = body
            r.status_code = getattr(resp, 'status', 200) or 200
            try:
                r.headers = dict(resp.headers)
            except Exception:
                r.headers = {}

            def to_json():
                return json.loads(r.text)
            r.json = to_json
            return r


class Spider(Spider):

    # ------------------------------------------------------------------ 基础
    def getName(self):
        return '面包网'

    def log(self, *args):
        print('[面包网]', *args)

    def init(self, extend=''):
        """支持 extend={"host":"https://新域名"} 换域名，无需改代码"""
        d = self._parse_extend(extend)
        host = str(d.get('host') or 'https://v.aiwule.com').strip().rstrip('/')
        if not re.match(r'^https?://', host, re.I):
            host = 'https://' + host.lstrip('/')
        self.host = host
        self.detail_re = r'/voddetail/\d+\.html'
        self.headers = {
            'User-Agent': UA,
            'Referer': self.host + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        self.categories = {
            '电影': '20', '电视剧': '21', '综艺': '22', '动漫': '23', '短剧': '47',
            '动作片': '24', '喜剧片': '25', '爱情片': '26', '科幻片': '27',
            '恐怖片': '28', '剧情片': '29', '战争片': '30', '动画片': '49',
            '国产剧': '31', '港剧': '32', '韩剧': '33', '欧美剧': '34',
            '台剧': '36', '日剧': '37', '泰剧': '38',
            '大陆综艺': '39', '港台综艺': '40', '日韩综艺': '41', '欧美综艺': '42',
            '国产动漫': '43', '日韩动漫': '44',
        }
        self._fail = 0
        self._blocked_until = 0.0
        self._inited = True

    def _ensure(self):
        """app 可能不调用 init 就直接使用，这里兜底，避免 AttributeError"""
        if not getattr(self, '_inited', False):
            try:
                self.init('')
            except Exception:
                self.host = 'https://v.aiwule.com'
                self.headers = {'User-Agent': UA, 'Referer': self.host + '/'}
                self.detail_re = r'/voddetail/\d+\.html'
                self.categories = {'电影': '20'}
                self._fail = 0
                self._blocked_until = 0.0
                self._inited = True

    def isVideoFormat(self, url):
        try:
            return bool(re.match(r'(?i)^https?://.+\.(m3u8|mp4)(\?|$)', url or ''))
        except Exception:
            return False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        return ''

    def destroy(self):
        return ''

    def localProxy(self, param):
        return None

    # ------------------------------------------------------------------ 工具
    def _parse_extend(self, extend):
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend.strip() else {}
            except Exception:
                extend = {}
        return extend if isinstance(extend, dict) else {}

    def _attr(self, tag, name):
        m = re.search(r'(?i)\b' + re.escape(name) + r'\s*=\s*"([^"]*)"', tag or '')
        if not m:
            m = re.search(r"(?i)\b" + re.escape(name) + r"\s*=\s*'([^']*)'", tag or '')
        return m.group(1).strip() if m else ''

    def _clean_text(self, s):
        s = re.sub(r'(?is)<[^>]+>', '', s or '')
        try:
            s = html_mod.unescape(s)
        except Exception:
            s = (s.replace('&nbsp;', ' ').replace('&amp;', '&')
                  .replace('&quot;', '"').replace('&#39;', "'"))
        return re.sub(r'\s+', ' ', s).strip()

    def _clean_url(self, u):
        """封面/播放地址统一还原 HTML 实体与常见转义"""
        u = (u or '').strip()
        u = html_mod.unescape(u)
        return u.strip()

    def _abs(self, url):
        url = (url or '').strip()
        if not url:
            return ''
        if url.startswith('//'):
            return 'https:' + url
        if re.match(r'(?i)^https?://', url):
            return url
        self._ensure()
        return self.host + ('' if url.startswith('/') else '/') + url

    def _verify_page(self, t):
        """站点反爬「系统安全验证」页 —— 内含热门搜索链接，绝不能当结果"""
        if not t:
            return False
        head = t[:8000]
        return ('系统安全验证' in head or 'verify/index.html' in head
                or '安全验证...' in head or '安全验证…' in head)

    def _bad_page(self, t):
        if not t:
            return True
        if self._verify_page(t):
            return True
        head = t[:8000].lower()
        for s in ('origin is unreachable', 'error 521', 'error 522',
                  'error 523', 'error 524', 'cloudflare ray id',
                  'connection timed out'):
            if s in head:
                return True
        m = re.search(r'(?is)<title>(.*?)</title>', t)
        if m and re.search(r'(?i)(52[1-4]|50\d|not found|安全验证|error)', m.group(1)):
            return True
        return False

    def _get(self, url, headers=None, retries=3):
        """带状态码/错误页校验的 GET。
        网络超时只重试不冷却（站点偶发 TLS 握手失败）；
        仅明确的 5xx / 验证页才累计失败并短冷却。"""
        self._ensure()
        self._verify_hit = False
        if time.time() < self._blocked_until:
            return ''
        h = dict(self.headers)
        if headers:
            h.update(headers)
        last, bad = None, False
        for i in range(retries):
            try:
                r = self.fetch(url, headers=h)
                if isinstance(r, (str, bytes)):
                    # 部分 app runtime 的 fetch 直接返回字符串
                    t = r.decode('utf-8', 'replace') if isinstance(r, bytes) else r
                    st = 200
                else:
                    t = getattr(r, 'text', '') or ''
                    st = getattr(r, 'status_code', 200) or 200
                if self._verify_page(t):
                    self._verify_hit = True   # 站点级拦截：调用方据此短路
                    return ''
                if st >= 400 or self._bad_page(t):
                    bad = True
                    raise ValueError('HTTP %s / bad page' % st)
                self._fail = 0
                return t
            except Exception as e:
                last = e
                if i < retries - 1:
                    time.sleep(0.35)
        if bad:
            self._fail += 1
            if self._fail >= 3:
                self._blocked_until = time.time() + 30
                self.log('连续错误页，冷却 30s')
        self.log('_get fail:', last)
        return ''

    def _meta(self, html, label):
        """提取「标签：值」。主演等字段包含多个 <a>，全部收集。"""
        m = re.search(label + r'\s*[:：]', html or '')
        if not m:
            return ''
        seg = html[m.end():m.end() + 3000]
        end = seg.find('</span>')
        e2 = seg.find('</p>')
        if end < 0 or (0 <= e2 < end):
            end = e2
        seg = seg[:end] if end >= 0 else re.sub(r'<[^>]*$', '', seg)
        parts = [t.strip() for t in re.split(r'<[^>]+>', seg) if t.strip()]
        return self._clean_text('、'.join(parts)).strip('、 ')

    # -------------------------------------------------------------- 列表解析
    def _extract_list(self, html):
        """从列表页/搜索页提取条目。

        实测 ewave 主列表：封面是 div.img-wrapper 的 data-original（无 <img>），
        备注在 li 内 p.item-status；侧栏「热门排行」纯文字链接必须排除。
        """
        if not html or self._verify_page(html) or self._bad_page(html):
            return []
        self._ensure()
        data, order = {}, []
        pat = r'(?is)<a\b[^>]*href="([^"]*' + self.detail_re + r')"[^>]*>'
        for m in re.finditer(pat, html):
            vid, tag = m.group(1), m.group(0)
            seg = html[m.start():m.start() + 1200]
            li_end = seg.find('</li>')
            if li_end > 0:
                seg = seg[:li_end]
            # 只认带封面的条目，排除排行榜 / 侧栏 / 验证页热门搜索
            if ('img-wrapper' not in seg) and ('<img' not in seg.lower()):
                continue
            title = self._attr(tag, 'title')
            pic = (self._attr(tag, 'data-original') or self._attr(tag, 'data-src')
                   or self._attr(tag, 'data-echo'))
            it = re.search(
                r'(?is)<(?:img|div)\b[^>]*(?:data-original|data-src|data-echo|alt)="[^"]*"[^>]*>',
                seg)
            if it:
                itag = it.group(0)
                src = (self._attr(itag, 'data-original') or self._attr(itag, 'data-src')
                       or self._attr(itag, 'data-echo'))
                if not src:
                    src = self._attr(itag, 'src')
                if src and 'load.gif' not in src:
                    pic = pic or src
                if not title:
                    title = self._attr(itag, 'alt')
            if not title:
                t = re.search(r'(?is)<h[234][^>]*>\s*<a[^>]*>([^<]{1,80})<', seg)
                title = t.group(1) if t else ''
            remark = ''
            rm = re.search(
                r'(?is)class="[^"]*(?:item-status|pic-text|module-item-note|note|remarks)[^"]*"[^>]*>([^<]{1,40})<',
                seg)
            if rm:
                remark = self._clean_text(rm.group(1))
            if vid not in data:
                data[vid] = {'vod_id': vid, 'vod_name': '', 'vod_pic': '',
                             'vod_remarks': ''}
                order.append(vid)
            rec = data[vid]
            if not rec['vod_name'] and title:
                rec['vod_name'] = self._clean_text(title)
            if not rec['vod_pic'] and pic:
                rec['vod_pic'] = self._clean_url(pic)
            if not rec['vod_remarks'] and remark:
                rec['vod_remarks'] = remark
        out = []
        for vid in order:
            rec = data[vid]
            if not rec['vod_name'] or not rec['vod_pic']:
                continue
            out.append(rec)
        return out

    def _list_url(self, tid, pg):
        t = str(tid)
        if '/' in t or t.startswith('http'):
            return self._abs(t)
        try:
            p = int(pg)
        except Exception:
            p = 1
        if p > 1:
            return '%s/vodshow/%s--------%d---.html' % (self.host, t, p)
        return '%s/vodshow/%s-----------.html' % (self.host, t)

    # ------------------------------------------------------------------ 接口
    def homeContent(self, filter):
        try:
            self._ensure()
            classes = [{'type_name': n, 'type_id': t}
                       for n, t in self.categories.items()]
            return {'class': classes, 'filters': {}}
        except Exception as e:
            self.log('homeContent error:', e)
            return {'class': [], 'filters': {}}

    def homeVideoContent(self):
        """首页推荐取「最近更新」，失败时返回合法空结构"""
        try:
            self._ensure()
            h = self._get(self.host + '/label/new.html')
            if not h:
                h = self._get(self.host + '/')
            v = self._extract_list(h)[:24]
            return {'list': v}
        except Exception as e:
            self.log('homeVideoContent error:', e)
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        self._parse_extend(extend)
        try:
            self._ensure()
            html = self._get(self._list_url(tid, pg))
            videos = self._extract_list(html)
            # 空列表时收敛 pagecount，避免 app 无限翻页
            pagecount = (pg + 1) if len(videos) >= 12 else max(1, pg)
            return {'list': videos, 'page': pg, 'pagecount': pagecount,
                    'limit': len(videos) or 36,
                    'total': (pg * 36) if videos else 0}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': max(1, pg - 1),
                    'limit': 36, 'total': 0}

    # -------------------------------------------------------------- 选集解析
    _JUNK_TEXT = ('立即播放', '收藏', '正序', '倒序', '在线播放',
                  '上一集', '下一集', '举报', '分享')

    def _eps(self, block):
        eps, seen = [], set()
        for m in re.finditer(
                r'(?is)<a\b[^>]*href="([^"]*?/(?:vodplay|play)/[^"]+?\.html)"[^>]*>(.*?)</a>',
                block or ''):
            href, text = m.group(1), self._clean_text(m.group(2))
            if text in self._JUNK_TEXT:
                continue
            if not text:
                eid = re.search(r'-(\d+)\.html$', href)
                text = '第%s集' % (eid.group(1) if eid else len(eps) + 1)
            url = self._abs(href)
            if url in seen:
                continue
            seen.add(url)
            eps.append((text, url))
        return eps

    def _play_lists(self, html):
        """返回 (线路名列表, 每条线路的 [(集名, 地址)] 列表)

        1) ewave 模板：tab 的 data-target 与 ul 的 id 精确配对（属性顺序无关）；
        2) MacCMS 默认模板：<a href="#playlistN"> 名 + 对应容器；
        3) 兜底：全文扫 /vodplay/{vid}-{sid}-{eid}.html 按 sid 分组。
        站点线路名已由「无尽资源」改为「播放接口6 / 播放接口2」，
        因此 tab 名一律从页面实时读取，绝不硬编码。
        """
        tabmap = {}
        # li 标签内 class / data-target 顺序无关
        for m in re.finditer(r'(?is)<li\b([^>]*)>(.*?)</li>', html or ''):
            attrs, inner = m.group(1), m.group(2)
            cls = self._attr(attrs, 'class')
            if 'ewave-tab' not in cls and 'playlist-tab' not in cls:
                continue
            dt = self._attr(attrs, 'data-target')
            if not dt:
                continue
            t = self._clean_text(re.sub(r'(?is)<em\b.*?</em>', '', inner))
            if t and len(t) <= 24:
                tabmap[dt.lstrip('#')] = t
        # 补充 <a href="#playlistN"> 形式
        for m in re.finditer(r'(?is)<a\b[^>]*href="#([^"]+)"[^>]*>(.*?)</a>', html or ''):
            key, t = m.group(1).lstrip('#'), self._clean_text(m.group(2))
            if t and len(t) <= 24 and key not in tabmap:
                tabmap[key] = t

        def name_for(uid, idx):
            for k in (uid, uid.replace('ewave-playlist-', 'playlist'),
                      'playlist%s' % uid.split('-')[-1]):
                if k in tabmap:
                    return tabmap[k]
            return '线路%d' % idx

        froms, groups = [], []
        for m in re.finditer(r'(?is)<ul\b([^>]*)>(.*?)</ul>', html or ''):
            attrs = m.group(1)
            uid = self._attr(attrs, 'id')
            cls = self._attr(attrs, 'class')
            if not (uid.startswith('ewave-playlist-') or uid.startswith('playlist')
                    or 'ewave-playlist-content' in cls
                    or 'module-play-list-content' in cls
                    or 'stui-content__playlist' in cls):
                continue
            eps = self._eps(m.group(2))
            if not eps:
                continue
            # 正序 / 倒序两个容器内容相同（仅顺序相反）时只保留一个
            if groups and sorted(u for _, u in groups[-1]) == sorted(u for _, u in eps):
                continue
            froms.append(name_for(uid, len(froms) + 1))
            groups.append(eps)
        if froms:
            return froms, groups

        # 兜底：按 sid 分组
        buckets, order = {}, []
        for m in re.finditer(
                r'(?is)<a\b[^>]*href="([^"]*?/(?:vodplay|play)/\d+-(\d+)-(\d+)\.html)"[^>]*>(.*?)</a>',
                html or ''):
            href, sid, eid, text = (m.group(1), m.group(2), m.group(3),
                                    self._clean_text(m.group(4)))
            if text in self._JUNK_TEXT:
                continue
            if sid not in buckets:
                buckets[sid] = []
                order.append(sid)
            url = self._abs(href)
            if not any(u == url for _, u in buckets[sid]):
                buckets[sid].append((text or ('第%s集' % eid), url))
        froms, groups = [], []
        for i, sid in enumerate(order, 1):
            froms.append(tabmap.get('ewave-playlist-%s' % sid)
                         or tabmap.get('playlist%s' % sid)
                         or ('线路%s' % sid))
            groups.append(buckets[sid])
        return froms, groups

    def detailContent(self, ids):
        try:
            self._ensure()
            vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
            html = self._get(self._abs(str(vid)))
            if not html or self._verify_page(html):
                return {'list': []}

            name = ''
            nm = re.search(r'(?is)<h1[^>]*>(.*?)</h1>', html)
            if nm:
                name = self._clean_text(nm.group(1))
            if not name:
                tm = re.search(r'(?is)<title>(.*?)</title>', html)
                name = self._clean_text(tm.group(1)) if tm else ''

            pic = ''
            for pat in (
                    r'(?is)<(?:a|div)[^>]*class="[^"]*\bpic\b[^"]*"[^>]*>.*?<img\b[^>]*>',
                    r'(?is)<img\b[^>]*>'):
                im = re.search(pat, html)
                if im:
                    itag = re.search(r'(?is)<img\b[^>]*>', im.group(0))
                    if itag:
                        pic = (self._attr(itag.group(0), 'data-original')
                               or self._attr(itag.group(0), 'data-src')
                               or self._attr(itag.group(0), 'src'))
                        if pic:
                            break
            pic = self._clean_url(self._abs(pic))

            desc = ''
            for pat in (
                    r'(?is)<div[^>]*class="[^"]*more-box[^"]*"[^>]*>\s*<p[^>]*>(.*?)</p>',
                    r'(?is)<div[^>]*class="[^"]*module-info-introduction-content[^"]*"[^>]*>(.*?)</div>',
                    r'(?is)<span[^>]*class="[^"]*detail-content[^"]*"[^>]*>(.*?)</span>'):
                dm = re.search(pat, html)
                if dm:
                    desc = self._clean_text(dm.group(1))
                    if desc:
                        break
            if not desc:
                dm = re.search(r'(?is)<meta[^>]*name="description"[^>]*content="([^"]*)"', html)
                desc = self._clean_text(dm.group(1)) if dm else ''

            froms, groups = self._play_lists(html)
            # 无有效选集时不返回空白记录（会让 app 显示一个点不动的影片）
            if not froms or not any(groups):
                return {'list': []}
            play_from = '$$$'.join(froms)
            play_url = '$$$'.join(
                ['#'.join(['%s$%s' % (n, u) for n, u in eps]) for eps in groups])
            if play_from.count('$$$') != play_url.count('$$$'):
                return {'list': []}

            video = {
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic,
                'vod_year': self._meta(html, '年份'),
                'vod_area': self._meta(html, '地区'),
                'vod_actor': self._meta(html, '主演'),
                'vod_director': self._meta(html, '导演'),
                'vod_remarks': self._meta(html, '状态') or self._meta(html, '更新'),
                'vod_content': desc,
                'vod_play_from': play_from,
                'vod_play_url': play_url,
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    # -------------------------------------------------------------- 搜索
    def _search_post(self, path, params, marker):
        """POST 搜索；Location 用 urljoin（相对路径必须相对 /vodsearch/）"""
        headers = dict(self.headers)
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        data = urllib.parse.urlencode(params)
        base = self.host + path
        for payload in (data, data.encode('utf-8')):
            try:
                r = self.fetch(base, headers=headers, data=payload)
                if isinstance(r, (str, bytes)):
                    t = r.decode('utf-8', 'replace') if isinstance(r, bytes) else r
                    st = 200
                else:
                    t = getattr(r, 'text', '') or ''
                    st = getattr(r, 'status_code', 200) or 200
                if st < 400 and marker in t and not self._verify_page(t):
                    return t
                loc = ''
                try:
                    hd = getattr(r, 'headers', {}) or {}
                    loc = hd.get('Location') or hd.get('location') or ''
                except Exception:
                    pass
                if loc:
                    t2 = self._get(urllib.parse.urljoin(base + '/', loc), headers=headers)
                    if t2 and marker in t2:
                        return t2
            except Exception:
                continue
        return ''

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        key = (key or '').strip()
        try:
            self._ensure()
            if not key:
                return {'list': [], 'page': pg, 'pagecount': 1, 'total': 0}
            q = urllib.parse.quote(key)
            # 站点对 /vodsearch/ 全路径加了「系统安全验证」；多路径兜底，
            # 任一路径返回验证页都直接跳过，绝不把热门搜索当成结果。
            urls = [
                '%s/vodsearch/%s-------------.html' % (self.host, q),
                '%s/vodsearch/-------------.html?wd=%s' % (self.host, q),
                '%s/index.php/vod/search.html?wd=%s' % (self.host, q),
            ]
            if pg > 1:
                paged = [
                    '%s/vodsearch/%s--------%d---.html' % (self.host, q, pg),
                    '%s/vodsearch/%s-------------.html?page=%d' % (self.host, q, pg),
                ]
                urls = paged + urls
            verify_seen = 0
            for u in urls:
                h = self._get(u)
                if self._verify_hit:
                    # 站点对 /vodsearch/ 整体加了验证码，再试其它路径没有意义
                    verify_seen += 1
                    if verify_seen >= 2:
                        break
                    continue
                if not h:
                    continue
                v = self._extract_list(h)
                if v:
                    return {'list': v, 'page': pg, 'pagecount': pg + 1,
                            'total': len(v)}
            h = self._search_post('/vodsearch/',
                                  {'wd': key, 'submit': 'search'}, self.detail_re)
            v = self._extract_list(h)
            if v:
                return {'list': v, 'page': pg, 'pagecount': pg + 1, 'total': len(v)}
            return {'list': [], 'page': pg, 'pagecount': max(1, pg - 1),
                    'total': 0}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': max(1, pg - 1),
                    'total': 0}

    # -------------------------------------------------------------- 播放
    def _player_obj(self, html, key):
        """用 JSONDecoder 精确取配平对象（手写括号配对会被 URL 里的 {} 打断）"""
        i = (html or '').find(key)
        if i < 0:
            return None
        j = html.find('{', i)
        if j < 0:
            return None
        try:
            obj, _ = json.JSONDecoder().raw_decode(html[j:])
            return obj if isinstance(obj, dict) else None
        except Exception:
            try:
                obj, _ = json.JSONDecoder().raw_decode(
                    html[j:].replace("\\'", "'"))
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None

    def _clean_play_url(self, u):
        u = (u or '').strip()
        u = (u.replace('\\/', '/').replace('\\u0026', '&')
              .replace('\\u003d', '=').replace('&amp;', '&'))
        u = html_mod.unescape(u)
        if u.startswith('//'):
            u = 'https:' + u
        return u

    def _decode_play_url(self, raw):
        """兼容 encrypt=1 明文 / encrypt=2 base64 或 urlencode / 转义直链"""
        s = str(raw or '').strip()
        if not s:
            return ''
        cands = [self._clean_play_url(s)]
        try:
            cands.append(urllib.parse.unquote(self._clean_play_url(s)))
        except Exception:
            pass
        try:
            d = base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', 'replace')
            cands.append(self._clean_play_url(d))
        except Exception:
            pass
        for c in cands:
            if re.match(r'(?i)^https?://', c or ''):
                return c
            if c.startswith('magnet:'):
                return c
        return ''

    def _parse_player_url(self, html):
        if not html or self._verify_page(html):
            return ''
        for key in ('player_aaaa', 'player_data', 'player_'):
            obj = self._player_obj(html, key)
            if not isinstance(obj, dict):
                continue
            for k in ('url', 'url_next', 'link', 'vod_url'):
                u = self._decode_play_url(obj.get(k))
                if u:
                    return u
        m = re.search(r'''(?is)["'](https?:[^"']*?\.(?:m3u8|mp4)[^"']*)["']''', html)
        if m:
            return self._decode_play_url(m.group(1))
        m = re.search(r'''(?is)(?:url|src|source)\s*[:=]\s*["']([^"']+?)["']''', html)
        if m:
            return self._decode_play_url(m.group(1))
        return ''

    def playerContent(self, flag, id, vipFlags):
        try:
            self._ensure()
            url = self._abs(str(id))
            if not re.search(r'/(?:vodplay|play)/', url):
                return {'parse': 0, 'url': url, 'header': dict(self.headers)}
            html = self._get(url)
            real = self._parse_player_url(html)
            if real:
                return {'parse': 0, 'url': real, 'header': dict(self.headers)}
            # 本地解不出直链（加密/验证/JS 渲染）：交给 app 嗅探，
            # 不能把播放页 HTML 当视频地址直出（旧版 parse:0 会直接播不了）
            return {'parse': 1, 'url': url, 'header': dict(self.headers)}
        except Exception as e:
            self.log('playerContent error:', e)
            return {'parse': 1, 'url': self._abs(str(id)),
                    'header': dict(self.headers)}


# ==================================================================== 本地测试
def _selftest():
    """离线结构自测：网络可达与否都能跑，覆盖解析 / 规范 / 降级全链路"""
    PASS, FAIL = [0], [0]

    def ck(name, cond, extra=''):
        if cond:
            PASS[0] += 1
            print('  PASS  %s' % name)
        else:
            FAIL[0] += 1
            print('  FAIL  %s  %s' % (name, extra))

    class Resp:
        def __init__(self, text='', status=200, headers=None):
            self.text, self.status_code = text, status
            self.headers = headers or {}
            self.content = text.encode('utf-8')

        def json(self):
            return json.loads(self.text)

    LIST = '''
    <div class="module"><ul>
      <li><div class="pic"><a href="/voddetail/160740.html" title="另一个妈妈">
        <div class="img-wrapper lazyload" data-original="https://img.example/a.jpg?x=1&amp;y=2"></div>
        </a></div><div class="name"><h3><a>另一个妈妈</a></h3>
        <p class="item-status">HD中字</p></div></li>
      <li><div class="pic"><a href="/voddetail/160741.html" title="谜尸">
        <div class="img-wrapper lazyload" data-original="https://img.example/b.jpg"></div>
        </a></div><div class="name"><h3><a>谜尸</a></h3>
        <p class="item-status">HD中字</p></div></li>
      <li><a href="/voddetail/999999.html">热门排行纯文字链接（应丢弃）</a></li>
    </ul></div>'''

    DETAIL = '''<html><head><title>另一个妈妈 - 面包网</title>
    <meta name="description" content="截断版简介"></head><body>
    <h1>另一个妈妈</h1>
    <div class="pic"><img data-original="https://img.example/p.jpg"></div>
    <span>年份：2026</span><span>地区：美国、爱尔兰</span>
    <span>导演：<a>罗布·萨维奇</a></span>
    <span>主演：<a>杰西卡·查斯坦</a><a>杰伊·杜普拉斯</a></span>
    <span>状态：HD中字</span>
    <div class="more-box"><p>这是完整简介全文，比 meta description 更长更完整。</p></div>
    <div class="btn-box"><a href="/vodplay/160740-1-1.html">立即播放</a></div>
    <li data-target="#ewave-playlist-2" class="swiper-slide ewave-tab">播放接口6<em></em></li>
    <li class="swiper-slide ewave-tab" data-target="#ewave-playlist-3">播放接口2<em></em></li>
    <ul id="ewave-playlist-2" class="ewave-playlist-content">
      <li class="ewave-playlist-item"><a href="/vodplay/160740-2-1.html">第1集</a></li>
      <li class="ewave-playlist-item"><a href="/vodplay/160740-2-2.html">第2集</a></li>
    </ul>
    <ul id="ewave-playlist-3" class="ewave-playlist-content">
      <li class="ewave-playlist-item"><a href="/vodplay/160740-3-1.html">HD</a></li>
      <li class="ewave-playlist-item"><a href="/vodplay/160740-3-2.html">HD中字</a></li>
    </ul>
    </body></html>'''

    PLAY = ('<script>var player_aaaa={"flag":"","encrypt":1,"from":"m3u8",'
            '"url":"https:\\/\\/cdn.example.com\\/2026\\/index.m3u8?t=abc",'
            '"url_next":""};</script>')
    PLAY_B64 = ('<script>var player_aaaa={"encrypt":2,"url":"%s"};</script>'
                % base64.b64encode(b'https://cdn.example.com/b64/index.m3u8').decode())
    VERIFY = '''<html><head><title>系统安全验证</title></head><body>
    <div class="hot"><a href="/voddetail/160775.html">锁柜日志：僵尸</a>
    <a href="/voddetail/160774.html">时尚战争</a></div>
    <img src="/verify/index.html"><h3>安全验证...</h3></body></html>'''
    CF523 = '<html><head><title>Origin is unreachable</title></head>error 523</html>'

    page = {
        'vodshow/20-----------.html': LIST,
        'vodshow/20--------2---.html': LIST.replace('160740', '160631')
                                            .replace('另一个妈妈', '龙在天涯1989粤语'),
        'label/new.html': LIST,
        'voddetail/160740.html': DETAIL,
        'vodplay/160740-2-1.html': PLAY,
        'vodplay/160740-2-2.html': PLAY_B64,
        'vodsearch/': VERIFY,
        'vodsearch/%E5%BA%86%E4%BD%99%E5%B9%B4-------------.html': VERIFY,
        'index.php/vod/search.html': VERIFY,
    }
    empty = {'vodsearch/': VERIFY}

    def mock_fetch(url, headers=None, data=None, **kw):
        for k, v in page.items():
            if k in url:
                return Resp(v)
        return Resp(CF523, 523)

    def mock_down(url, headers=None, data=None, **kw):
        raise OSError('network unreachable (simulated)')

    print('=== 1. 规范骨架 / 参数防御 ===')
    sp = Spider()
    ck('getName', sp.getName() == '面包网')
    hc = sp.homeContent({})                       # 故意不调 init
    ck('未调 init 时 homeContent 不崩', len(hc['class']) == 26,
       str(len(hc.get('class', []))))
    ck('分类含 type_id', all('type_id' in c for c in hc['class']))
    ck('isVideoFormat 带参数', sp.isVideoFormat('https://x.com/a.m3u8?t=1'))
    ck('isVideoFormat 拒绝网页', not sp.isVideoFormat('https://x.com/a.html'))
    ck('manualVideoCheck 返回 bool', sp.manualVideoCheck() is False)
    ck('action 非 None', sp.action('x') is not None)
    ck('destroy 非 None', sp.destroy() is not None)
    ck('localProxy 合法', sp.localProxy({}) is None)
    ck('extend 字符串可解析', sp._parse_extend('{"host":"https://a.com"}')['host'] == 'https://a.com')
    sp.init('{"host": "https://new.example.com"}')
    ck('init 支持换域名', sp.host == 'https://new.example.com', sp.host)

    print('=== 2. 列表 / 封面 / 验证页 ===')
    sp.init('')
    sp.fetch = mock_fetch
    v = sp._extract_list(LIST)
    ck('列表提取 2 条（侧栏纯文字被排除）', len(v) == 2, str(len(v)))
    ck('vod_id 正确', bool(v) and v[0]['vod_id'] == '/voddetail/160740.html')
    ck('封面 &amp; 实体已还原', bool(v) and '&amp;' not in v[0]['vod_pic']
       and 'y=2' in v[0]['vod_pic'])
    ck('备注提取', bool(v) and v[0]['vod_remarks'] == 'HD中字')
    ck('验证页返回 0 条（不误报热门搜索）', sp._extract_list(VERIFY) == [])
    ck('523 错误页返回 0 条', sp._extract_list(CF523) == [])
    ck('翻页 URL 格式', sp._list_url('20', 2).endswith('/vodshow/20--------2---.html'))
    ck('第 1 页 URL 格式', sp._list_url('20', 1).endswith('/vodshow/20-----------.html'))

    print('=== 3. 分类 / 分页 / pagecount ===')
    r1 = sp.categoryContent('20', 1, {}, {})
    r2 = sp.categoryContent('20', 2, {}, {})
    ck('第 1 页有数据', len(r1['list']) == 2)
    ck('第 2 页与第 1 页不同', r1['list'][0]['vod_name'] != r2['list'][0]['vod_name'])
    ck('字符串 pg 兼容', len(sp.categoryContent('20', '1', {}, {})['list']) == 2)
    ck('字符串 extend 兼容', len(sp.categoryContent('20', 1, {}, '{}')['list']) == 2)
    ck('pagecount 不恒为 9999', r1['pagecount'] < 9999)

    print('=== 4. 详情 / 选集格式 ===')
    d = sp.detailContent(['/voddetail/160740.html'])
    ck('详情返回 1 条', len(d['list']) == 1)
    if d['list']:
        vd = d['list'][0]
        ck('片名', vd['vod_name'] == '另一个妈妈', vd['vod_name'])
        ck('简介取完整版', '完整简介全文' in vd['vod_content'])
        ck('主演收集全部 a', '杰西卡' in vd['vod_actor'] and '杰伊' in vd['vod_actor'])
        ck('导演', vd['vod_director'] == '罗布·萨维奇', vd['vod_director'])
        ck('线路数 2（tab 名实时读取）', len(vd['vod_play_from'].split('$$$')) == 2,
           vd['vod_play_from'])
        ck('线路名来自页面', '播放接口' in vd['vod_play_from'])
        segs = vd['vod_play_url'].split('$$$')
        ck('$$$ 段数 = 线路数', len(segs) == len(vd['vod_play_from'].split('$$$')))
        ck('每条线路 2 集且用 # 连接', all(len(s.split('#')) == 2 for s in segs),
           str([len(s.split('#')) for s in segs]))
        ck('集名$地址格式', all('$' in x and x.split('$', 1)[1].startswith('http')
                              for s in segs for x in s.split('#')))
        ck('立即播放按钮未混入', '立即播放' not in vd['vod_play_url'])

    print('=== 5. 播放直出 / 降级 ===')
    p1 = sp.playerContent('', '/vodplay/160740-2-1.html', None)
    ck('encrypt=1 直出 m3u8', p1['parse'] == 0 and 'index.m3u8' in p1['url'], p1['url'][:90])
    ck('播放头带 Referer', 'Referer' in p1.get('header', {}))
    p2 = sp.playerContent('', '/vodplay/160740-2-2.html', None)
    ck('encrypt=2 base64 解码', p2['parse'] == 0 and 'b64/index.m3u8' in p2['url'],
       p2['url'][:90])
    p3 = sp.playerContent('', 'https://cdn.example.com/direct.m3u8', None)
    ck('已是直链直接返回', p3['parse'] == 0 and p3['url'].endswith('direct.m3u8'))

    print('=== 6. 搜索 / 安全验证 ===')
    s1 = sp.searchContent('庆余年', False, 1)
    ck('验证页时搜索返回合法空结构', s1['list'] == [] and s1['page'] == 1)
    ck('搜索不误报热门搜索影片', not any('160775' in x.get('vod_id', '') for x in s1['list']))
    s2 = sp.searchContent('庆余年', False, '2')
    ck('字符串 pg / 无结果时 pagecount 收敛', s2['page'] == 2 and s2['pagecount'] <= 2)

    def mock_search_ok(url, headers=None, data=None, **kw):
        if 'vodsearch/' in url and 'wd=' not in url:
            return Resp(LIST)
        return Resp(VERIFY)
    sp.fetch = mock_search_ok
    s3 = sp.searchContent('另一个妈妈', False, 1)
    ck('搜索正常时返回结果', len(s3['list']) == 2, str(len(s3['list'])))
    sp.fetch = mock_fetch

    print('=== 7. 源站不可用时的降级 ===')
    sp.init('')
    sp.fetch = mock_down
    ck('homeContent 不抛异常', len(sp.homeContent({})['class']) == 26)
    ck('homeVideoContent 返回空 list', sp.homeVideoContent()['list'] == [])
    ck('categoryContent 返回合法空结构',
       sp.categoryContent('20', 1, {}, {})['list'] == [])
    ck('detailContent 不返回空白记录', sp.detailContent(['/voddetail/1.html'])['list'] == [])
    ck('searchContent 不抛异常', sp.searchContent('x', False)['list'] == [])
    pc = sp.playerContent('', '/vodplay/1-1-1.html', None)
    ck('playerContent 降级为 parse:1', pc['parse'] == 1 and 'vodplay' in pc['url'])

    print()
    total = PASS[0] + FAIL[0]
    print('=== 结果：%d/%d PASS ===' % (PASS[0], total))
    return FAIL[0] == 0


def main():
    import sys
    sp = Spider()
    sp.init('')
    print('=== 在线可达性（不计入离线自测成绩）===')
    try:
        h = sp._get(sp.host + '/', retries=1)
        if h:
            print('  在线：可达，首页 %d 字节' % len(h))
            r = sp.homeContent({})
            print('  分类数：%d' % len(r['class']))
            c = sp.categoryContent('20', 1, {}, {})
            print('  电影第 1 页：%d 项' % len(c['list']))
        else:
            print('  在线：不可达（本机网络/代理层阻断），跳过在线项')
    except Exception as e:
        print('  在线：异常 %s，跳过在线项' % e)
    print()
    print('=== 离线结构自测 ===')
    ok = _selftest()
    print()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
