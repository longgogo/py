# -*- coding: utf-8 -*-
"""
永乐影视  TVBox Python Spider（影视仓 / OK影视）
站点：https://www.ylys.tv/

⚠️ 站点状态（2026-09-26 实测）：
    www.ylys.tv / ylys.tv 均在 Cloudflare 后面（104.21.31.174、172.67.178.236）。
    http:// 返回 301 跳 https；https:// 返回 523（Cloudflare 报 "origin is unreachable"），
    curl、WebFetch、wayback 快照均拿不到任何页面 —— 源站当前宕机，页面结构无法探测。
    ⇒ 本源按 **最常见的 MacCMS v10 结构** 编写，并内置"多候选路由自适应"：
       分类页依次尝试 /list/{id}-{pg}.html、/vodshow/{id}--------{pg}---.html、
       /vodtype/{id}-{pg}.html、/index.php/vod/type/id/{id}/page/{pg}.html 等，
       谁先返回带海报的列表就用谁；详情/播放入口全部从列表页真实 href 推导，
       所以站点恢复后**无需改代码**即可大概率直接可用，但仍需人工验证一次。
    已按通用 MacCMS 结构假定的路径：
       detail : /detail/{id}.html  或  /voddetail/{id}.html
       list   : /list/{id}-{pg}.html
       cat    : /list/{id}.html
       search : /index.php/vod/search.html?wd=  或  /vodsearch/-------------.html?wd=
       play   : player_aaaa = {...} JSON（真实 m3u8 / mp4）

兼容两套主流模板的列表与播放列表结构：
   · myui 模板： div.myui-vodlist__box / ul.myui-content__list / div#playlistN
   · MacCMS v10 默认模板： a.module-poster-item / div.module-play-list-content / module-tab-item
"""
import sys
import os
import re
import json
import base64
import urllib.parse

# ---- base Spider 导入：app 内有 base.spider，本地测试走 fallback ----
try:
    from base.spider import Spider
except Exception:
    class Spider:
        """本地测试用最小实现"""

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
                method = 'POST'     # 带 data 时自动升级为 POST
            req = urllib.request.Request(url, headers=h, method=method)
            if data:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                req.data = data
            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                resp = e
            body = resp.read()
            if body[:2] == b'\x1f\x8b':
                body = gzip.decompress(body)

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

    def getName(self):
        return '永乐影视'

    def log(self, *args):
        # 子类自带日志实现，绝不依赖 base Spider 的 log
        print('[永乐影视]', *args)

    def init(self, extend=''):
        self.host = 'https://www.ylys.tv'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        # 通用 MacCMS 主分类 id（1 电影 2 连续剧 3 综艺 4 动漫 5 短剧 6 纪录片）
        self.categories = {
            '电影': '1',
            '电视剧': '2',
            '综艺': '3',
            '动漫': '4',
            '短剧': '5',
            '纪录片': '6',
        }
        # 分类页候选路由（{id} {pg} 占位）
        self.list_tpls = [
            '/list/{id}-{pg}.html',
            '/vodshow/{id}--------{pg}---.html',
            '/vodtype/{id}-{pg}.html',
            '/index.php/vod/type/id/{id}/page/{pg}.html',
            '/vod/{id}-{pg}.html',
            '/type/{id}-{pg}.html',
            '/vodlist/{id}-{pg}.html',
            '/vodshow/{id}-----------{pg}.html',
        ]
        # 分类首页候选（第 1 页可能不带 -1）
        self.list_tpls_p1 = [
            '/list/{id}.html',
            '/vodshow/{id}-----------.html',
            '/vodtype/{id}.html',
            '/index.php/vod/type/id/{id}.html',
            '/vod/{id}.html',
        ]
        self.search_tpls = [
            '/index.php/vod/search.html?wd=',
            '/vodsearch/-------------.html?wd=',
            '/search/-------------.html?wd=',
            '/vodsearch.html?wd=',
        ]
        self._list_tpl = None      # 探测到可用的分类路由后缓存
        self._fail = 0             # 连续网络失败计数：源站宕机时快速短路，避免逐个候选路由硬等
        self._fail_at = 0
        self._max_fail = 4
        self._max_try = 6          # 每次分类最多试多少个候选路由
        self._img_holder = re.compile(r'load(?:ing)?\.(?:gif|png)|blank\.gif|placeholder', re.I)

    # ------------------------------------------------------------------ 基础
    def isVideoFormat(self, url):
        return bool(re.match(r'https?://.+\.(m3u8|mp4|flv)', url or ''))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        return None

    def _parse_extend(self, extend):
        """兼容 app 传 dict 或 JSON 字符串两种情况"""
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend.strip() else {}
            except Exception:
                extend = {}
        return extend if isinstance(extend, dict) else {}

    def _text(self, resp):
        try:
            t = resp.text
        except Exception:
            t = ''
        if isinstance(t, bytes):
            t = t.decode('utf-8', 'replace')
        return t or ''

    def _http(self, url, extra=None):
        """统一请求入口：失败重试 1 次；连续失败达阈值则短路（源站宕机场景），
        冷却 60s 后自动重新探测，避免站点恢复后仍被判死。"""
        try:
            import time
            if self._fail >= self._max_fail and time.time() - self._fail_at > 60:
                self._fail = 0
        except Exception:
            pass
        if self._fail >= self._max_fail:
            return ''
        hd = dict(self.headers)
        if extra:
            hd.update(extra)
        for attempt in range(2):
            try:
                html = self._text(self.fetch(url, headers=hd))
                self._fail = 0
                return html
            except Exception as e:
                self.log('fetch error(第%d次):' % (attempt + 1), url, e)
                self._fail += 1
                try:
                    import time
                    self._fail_at = time.time()
                except Exception:
                    pass
                if self._fail >= self._max_fail:
                    self.log('连续 %d 次网络失败，判定源站不可达，暂停重试（60s 后再试）'
                             % self._fail)
                    return ''
        return ''

    def _full(self, u):
        if not u:
            return ''
        if u.startswith('http'):
            return u
        if u.startswith('//'):
            return 'https:' + u
        return self.host + (u if u.startswith('/') else '/' + u)

    # ------------------------------------------------------------ 列表项解析
    def _looks_like_detail(self, href):
        if not href or href.startswith(('javascript:', '#', 'mailto:')):
            return False
        if not re.search(r'\d', href):
            return False
        # 排除栏目/排行/专题等非详情页
        if re.search(r'/(?:list|vodtype|vodshow|type|vodsearch|search|topic|top|label|'
                     r'actor|map|art|gbook|user|index\.php/vod/(?:search|show|type|map))'
                     r'(?:/|\.|-|$)', href, re.I):
            return False
        return href.endswith('.html') or '/vod/detail' in href or '/detail/' in href

    def _extract_list(self, html):
        """通用列表提取，返回 [(href, name, pic, remark)]，按 href 去重保序"""
        items = []
        seen = set()

        def push(href, title, pic, remark):
            href = (href or '').strip()
            if not self._looks_like_detail(href) or href in seen:
                return
            seen.add(href)
            pic = (pic or '').strip()
            if self._img_holder.search(pic) or pic.startswith('data:'):
                pic = ''
            items.append((href, re.sub(r'<[^>]+>', '', title or '').strip(),
                          self._full(pic), (remark or '').strip()))

        # ① myui 模板：列表项 data-original 挂在 <a> 上
        for m in re.finditer(
                r'<a class="myui-vodlist__thumb[^"]*"[^>]*?href="([^"]+)"'
                r'[^>]*?title="([^"]*)"[^>]*?data-original="([^"]*)"[^>]*?>(.*?)</a>',
                html, re.S):
            rk = re.search(r'pic-text[^>]*>\s*([^<]*?)\s*<', m.group(4))
            push(m.group(1), m.group(2), m.group(3), rk.group(1) if rk else '')

        # ② MacCMS v10 默认模板：a.module-poster-item
        if not items:
            for m in re.finditer(
                    r'<a[^>]*class="[^"]*module-poster-item[^"]*"[^>]*?href="([^"]+)"'
                    r'[^>]*?(?:title="([^"]*)")?[^>]*>(.*?)</a>', html, re.S):
                seg = m.group(3)
                t = m.group(2) or ''
                if not t:
                    tm = re.search(r'poster-item-title[^>]*>\s*([^<]*?)\s*<', seg)
                    t = tm.group(1) if tm else ''
                p = re.search(r'(?:data-original|data-src|src)="([^"]+)"', seg)
                rk = re.search(r'(?:poster-item-note|module-item-note|module-poster-item-note)'
                               r'[^>]*>\s*([^<]*?)\s*<', seg)
                push(m.group(1), t, p.group(1) if p else '', rk.group(1) if rk else '')

        # ③ 通用兜底：任一含海报图的详情锚点（属性顺序无关）
        if not items:
            for m in re.finditer(r'<a\s[^>]*href="([^"]+)"[^>]*>', html):
                href = m.group(1)
                if not self._looks_like_detail(href):
                    continue
                seg = html[m.start():m.start() + 1500]
                end = seg.find('</a>')
                if end > 0:
                    seg = seg[:end]
                p = re.search(r'(?:data-original|data-src|src)="(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
                              seg, re.I)
                if not p:
                    continue
                t = re.search(r'title="([^"]*)"', seg)
                if not t:
                    tm = re.search(r'>(?!<)([^<>]{2,40})<', seg)
                    t = tm if tm else None
                rk = re.search(r'(?:pic-text|poster-item-note|module-item-note)[^>]*>\s*([^<]*?)\s*<', seg)
                push(href, t.group(1) if t else '', p.group(1),
                     rk.group(1) if rk else '')
        return items

    def _to_videos(self, items):
        return [{'vod_id': i[0], 'vod_name': i[1], 'vod_pic': i[2],
                 'vod_remarks': i[3]} for i in items]

    # ------------------------------------------------------ 分类页（多路由自适应）
    def _cat_urls(self, tid, pg):
        urls = []
        if self._list_tpl:
            urls.append(self.host + self._list_tpl.format(id=tid, pg=pg))
        if pg <= 1:
            for t in self.list_tpls_p1:
                urls.append(self.host + t.format(id=tid, pg=pg))
        for t in self.list_tpls:
            urls.append(self.host + t.format(id=tid, pg=pg))
        out, seen = [], set()
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def homeContent(self, filter):
        classes = [{'type_name': name, 'type_id': tid}
                   for name, tid in self.categories.items()]
        return {'class': classes, 'filters': {}}

    def homeVideoContent(self):
        try:
            videos = self._load_category(self.categories['电影'], 1)
            return {'list': videos[:30]}
        except Exception as e:
            self.log('homeVideoContent error:', e)
            return {'list': []}

    def _load_category(self, tid, pg):
        """逐个候选路由试，取第一个解析出条目的（最多试 self._max_try 个）"""
        for url in self._cat_urls(tid, pg)[:self._max_try]:
            if self._fail >= self._max_fail:
                return []
            try:
                html = self._http(url)
            except Exception:
                html = ''
            if not html or len(html) < 500:
                continue
            items = self._extract_list(html)
            if items:
                if not self._list_tpl:
                    tpl = url.replace(self.host, '')
                    # 反推模板：把 tid / pg 还原成占位符
                    tpl = tpl.replace('/%s-' % tid, '/{id}-').replace('/%s.' % tid, '/{id}.')
                    if '-{id}-' in tpl or '/{id}.' in tpl:
                        if str(pg) != '1':
                            tpl = re.sub(r'-%d\.html$' % pg, '-{pg}.html', tpl)
                        if '{pg}' in tpl or pg == 1:
                            self._list_tpl = tpl if '{pg}' in tpl else \
                                tpl.replace('/{id}.html', '/{id}-{pg}.html')
                    self.log('分类路由探测成功:', url, '-> 模板', self._list_tpl)
                return self._to_videos(items)
        return []

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)          # app 可能传字符串
        except Exception:
            pg = 1
        extend = self._parse_extend(extend)
        try:
            key = str(tid or '')
            if key in self.categories:
                key = self.categories[key]
            key = re.sub(r'\D', '', key) or '1'
            videos = self._load_category(key, pg)
            return {'list': videos, 'page': pg, 'pagecount': 9999,
                    'limit': 20, 'total': 999999}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 20, 'total': 0}

    # ------------------------------------------------------------------ 详情
    def detailContent(self, ids):
        try:
            one = ids[0] if isinstance(ids, (list, tuple)) else ids
            url = self._full(one)
            html = self._http(url)
            if not html:
                return {'list': []}

            title = ''
            for pat in (r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>\s*([^<]*?)\s*</h1>',
                        r'<h1[^>]*>\s*([^<]*?)\s*</h1>',
                        r'<title>\s*《?(.*?)》?\s*[-_|]'):
                m = re.search(pat, html)
                if m and m.group(1).strip():
                    title = m.group(1).strip()
                    break

            pic = ''
            for pat in (r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"',
                        r'myui-content__thumb.*?data-original="([^"]+)"',
                        r'class="[^"]*(?:module-item-pic|vodlist_thumb)[^"]*".*?'
                        r'(?:data-original|data-src|src)="([^"]+)"'):
                m = re.search(pat, html, re.S)
                if m and m.group(1).strip():
                    pic = m.group(1).strip()
                    break

            def field(label):
                """元数据取值：兼容 myui（</span><a>值</a> / </span>值</p>）
                与 MacCMS v10 默认模板（module-info-item-title + module-info-item-content）"""
                pats = (
                    label + r'[：:]\s*</span>\s*<a[^>]*>\s*([^<]*?)\s*</a>',
                    label + r'[：:]\s*</span>\s*<div[^>]*>\s*([^<]*?)\s*</div>',
                    label + r'[：:]\s*</span>\s*([^<>]{1,60}?)\s*<',
                    r'<span class="[^"]*module-info-item-title[^"]*">\s*' + label +
                    r'[：:]\s*</span>\s*(?:<div[^>]*>)?\s*([^<]*?)\s*<',
                )
                for p in pats:
                    m = re.search(p, html, re.S)
                    if m and m.group(1).strip():
                        return m.group(1).strip()
                return ''

            content = ''
            m = re.search(r"Layer\.Text\('剧情简介','(.*?)'", html, re.S)
            if not m:
                m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html)
            if m:
                content = re.sub(r'&nbsp;', ' ', m.group(1)).replace('&amp;', '&')
                content = re.sub(r'\s+', ' ', content).strip()

            play_from, play_url = self._parse_plays(html)
            video = {
                'vod_id': one,
                'vod_name': title,
                'vod_pic': self._full(pic),
                'vod_year': field('年份'),
                'vod_area': field('地区'),
                'vod_actor': field('主演'),
                'vod_director': field('导演'),
                'vod_remarks': field('更新') or field('备注'),
                'vod_content': content,
                'vod_play_from': '$$$'.join(play_from) if play_from else '永乐影视',
                'vod_play_url': '$$$'.join(play_url) if play_url else '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    def _eps_of(self, body, source=None):
        """从一个播放面板 HTML 里抽 集名$地址（source 为空则用全集链接）"""
        eps = []
        if source is not None:
            found = re.findall(
                r'href="(%s)"[^>]*>\s*(?:<span[^>]*>)?\s*([^<]*?)\s*(?:</span>)?\s*</a>' % source,
                body)
            if not found:
                found = [(h, '') for h in re.findall(r'href="(%s)"' % source, body)]
        else:
            found = re.findall(
                r'<a[^>]*href="([^"]*(?:/vod)?play[^"]*\.html)"[^>]*>\s*(?:<span[^>]*>)?'
                r'\s*([^<]*?)\s*(?:</span>)?\s*</a>', body, re.I)
        for href, nm in found:
            if not href or href.startswith(('javascript:', '#')):
                continue
            nm = (nm or '').strip() or '第%d集' % (len(eps) + 1)
            eps.append('%s$%s' % (nm, self._full(href)))
        return eps

    def _parse_plays(self, html):
        """返回 (play_from 列表, play_url 列表)，兼容 myui 与 MacCMS v10 默认模板"""
        play_from, play_url = [], []

        # ① myui：div#playlistN + ul.myui-content__list
        names = {}
        for sid, nm in re.findall(r'href="#playlist(\d+)"[^>]*>\s*([^<]*?)\s*</a>', html):
            names[sid] = nm or ('线路' + sid)
        parts = re.split(r'<div id="playlist(\d+)"', html)
        for i in range(1, len(parts) - 1, 2):
            sid, body = parts[i], parts[i + 1]
            eps = self._eps_of(body, r'/sanyipy/\d+-\d+-\d+\.html')
            if not eps:
                eps = self._eps_of(body, None)
            if eps:
                play_from.append(names.get(sid, '线路' + sid))
                play_url.append('#'.join(eps))

        # ② MacCMS v10 默认模板：module-play-list-content + module-tab-item
        if not play_url:
            tabs = re.findall(r'<div[^>]*class="[^"]*module-tab-item[^"]*"[^>]*>\s*'
                              r'(?:<span[^>]*>)?\s*([^<]*?)\s*(?:</span>)?\s*</div>', html)
            blocks = re.split(r'<div[^>]*class="[^"]*module-play-list-content[^"]*"', html)
            for i, body in enumerate(blocks[1:]):
                eps = self._eps_of(body, None)
                if eps:
                    play_from.append(tabs[i].strip() if i < len(tabs) and tabs[i].strip()
                                     else '线路%d' % (i + 1))
                    play_url.append('#'.join(eps))

        # ③ 兜底：整页扫播放链接，按 sid 分组；分不出就单线路
        if not play_url:
            pairs = re.findall(
                r'<a[^>]*href="([^"]+)"[^>]*>\s*(?:<span[^>]*>)?\s*([^<]*?)\s*(?:</span>)?\s*</a>',
                html)
            groups, order = {}, []
            for href, nm in pairs:
                if not re.search(r'(\d+)-(\d+)(?:-\d+)?\.html$', href or ''):
                    continue
                if '/vodsearch/' in href or '/search' in href:
                    continue
                m = re.search(r'-(\d+)-\d+(?:-\d+)?\.html$', href)
                sid = m.group(1) if m else '1'
                if sid not in groups:
                    groups[sid] = []
                    order.append(sid)
                nm = (nm or '').strip()
                if nm:
                    groups[sid].append('%s$%s' % (nm, self._full(href)))
                else:
                    groups[sid].append('第%d集$%s' % (len(groups[sid]) + 1, self._full(href)))
            for sid in order:
                if groups[sid]:
                    play_from.append('线路' + sid)
                    play_url.append('#'.join(groups[sid]))
        return play_from, play_url

    # ------------------------------------------------------------------ 搜索
    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg > 1:
            return {'list': [], 'page': pg}
        try:
            kw = urllib.parse.quote(key)
            videos = []
            # GET 各候选端点
            for tpl in self.search_tpls:
                html = self._http(self.host + tpl + kw)
                items = self._extract_list(html) if html else []
                if items:
                    return {'list': self._to_videos(items), 'page': pg}
            # POST 兜底（MacCMS 搜索有时只认 POST）
            headers = dict(self.headers)
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            data = urllib.parse.urlencode({'wd': key})
            for tpl in self.search_tpls:
                path = tpl.split('?')[0]
                try:
                    html = self._text(self.fetch(self.host + path, headers=headers, data=data))
                except Exception:
                    html = ''
                items = self._extract_list(html) if html else []
                if items:
                    return {'list': self._to_videos(items), 'page': pg}
            return {'list': [], 'page': pg}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg}

    # ------------------------------------------------------------------ 播放
    def playerContent(self, flag, id, vipFlags):
        try:
            url = self._full(id)
            play_url = ''
            html = self._http(url)
            m = re.search(r'player_aaaa\s*=\s*(\{.*?\})\s*</script>', html, re.S)
            if not m:
                m = re.search(r'player_aaaa\s*=\s*(\{.*\})', html, re.S)
            if m:
                try:
                    data = json.loads(m.group(1))
                except Exception:
                    data = {}
                play_url = (data.get('url') or '').strip()
                if play_url and str(data.get('encrypt')) == '1':
                    try:
                        play_url = base64.b64decode(
                            play_url + '=' * (-len(play_url) % 4)).decode('utf-8', 'replace')
                    except Exception:
                        pass
            if not play_url:
                # 兜底：页面直接给出 m3u8/mp4
                m = re.search(r'["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', html)
                play_url = m.group(1) if m else url
            parse = 0 if re.search(r'\.(m3u8|mp4|flv)(\?|$)', play_url) else 1
            return {'parse': parse, 'url': play_url,
                    'header': dict(self.headers), 'flag': flag}
        except Exception as e:
            self.log('playerContent error:', e)
            return {'parse': 1, 'url': id, 'header': dict(self.headers)}


def main():
    """本地测试块：python 永乐影视.py 直接运行"""
    sp = Spider()
    sp.init('')
    print('=== homeContent ===')
    r = sp.homeContent({})
    print('classes:', [(c['type_name'], c['type_id']) for c in r['class']])
    print()
    print('=== 分类列表 ===')
    for c in r['class']:
        r2 = sp.categoryContent(c['type_id'], 1, {}, {})
        print('  %-6s id=%s -> %d 项 %s' % (
            c['type_name'], c['type_id'], len(r2['list']),
            (r2['list'][0]['vod_name'] + ' | ' + r2['list'][0]['vod_id']) if r2['list'] else ''))
    print()
    first_tid = r['class'][0]['type_id']
    print('=== 翻页（第1页 vs 第2页）===')
    p1 = sp.categoryContent(first_tid, 1, {}, {})
    p2 = sp.categoryContent(first_tid, 2, {}, {})
    print('  p1 first:', p1['list'][0]['vod_id'] if p1['list'] else None)
    print('  p2 first:', p2['list'][0]['vod_id'] if p2['list'] else None)
    print()
    print('=== 兼容性：字符串 pg / 字符串 extend ===')
    print('  str pg:', len(sp.categoryContent(first_tid, '1', {}, {})['list']), '项')
    print('  str extend:', len(sp.categoryContent(first_tid, 1, {}, '{}')['list']), '项')
    print()
    print('=== detailContent ===')
    if p1['list']:
        v = sp.detailContent([p1['list'][0]['vod_id']])['list']
        if v:
            v = v[0]
            froms = v['vod_play_from'].split('$$$')
            urls = v['vod_play_url'].split('$$$')
            print('  name=%s | year=%s | area=%s' % (v['vod_name'], v['vod_year'], v['vod_area']))
            print('  来源:', froms)
            for f, u in zip(froms, urls):
                print('   %s -> %d 集, 首集: %s' % (f, len(u.split('#')), u.split('#')[0][:70]))
            print()
            print('=== playerContent ===')
            if urls and urls[0] and urls[0] != '#':
                pid = urls[0].split('#')[0].split('$', 1)[1]
                r4 = sp.playerContent(froms[0], pid, None)
                print('  parse=%s' % r4['parse'])
                print('  url=%s' % r4['url'][:120])
    print()
    print('=== searchContent ===')
    rs = sp.searchContent('庆余年', False, 1)
    print('  结果数:', len(rs['list']), [x['vod_name'] for x in rs['list'][:5]])


if __name__ == '__main__':
    main()
