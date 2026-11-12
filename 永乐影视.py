# -*- coding: utf-8 -*-
"""
永乐影视  TVBox Python Spider（修复版）
原文件：桌面/永乐影视.py —— 保持原样不动，本文件为修复后的独立副本。

【修复依据】
1. 结构规范参照桌面的《猎手影视.py》(by嗷呜) 与本地 TVBox Spider 规范：
   - 必须是 class Spider(Spider)，方法集齐备，禁止调用 base 的 log（子类自带 log）
   - pg / extend 参数防御，所有公开方法 try/except 兜底，绝不抛异常到 runtime
   - vod_play_url 规则：集名$地址，同线路集之间用 #，线路之间用 $$$，
     且 vod_play_url.split('$$$') 段数必须等于 vod_play_from.split('$$$') 段数
2. 站点真实结构来自一份针对同一域名 www.ylys.tv 的历史可用源（MacCMS v10 / module 模板）：
   - 分类：/vodtype/{id}/        翻页：/vodtype/{id}/page/{pg}/
   - 搜索：/vodsearch/{关键词}-------------/   翻页加 /page/{pg}/
   - 详情：/voddetail/{数字id}/  播放页：/play/{id}-{线路}-{集}/
   - 列表项：<a href="/voddetail/(\\d+)/" title="名"> ... module-item-note ... data-original="海报"
   - 线路 tab：module-tab-item > span；剧集：a.module-play-list-link href="/play/{id}-{sid}-{nid}/"
   - 详情元数据：og:title / og:image / og:description
   - 播放：var player_aaaa = {...JSON...}，取 url 字段，解密后 parse=0
   桌面旧版用的是 /list/{id}-{pg}.html、/index.php/vod/search.html?wd= 等猜测路由，
   且剧集正则里残留了别站的 /sanyipy/ 路径，站点恢复后也拿不到数据 —— 这是本次主要修复点。

【站点现状（2026-11-12 实测）】
   https://www.ylys.tv/ 返回 Cloudflare 523 origin is unreachable；
   www.59v.net、www.ylsp.lv、ylsp.tv 等候选域名同样 523 / 超时。
   ⇒ 源站整体下线，脚本本身无法凭空变出影片。修复版已做到：
     ① 站点恢复后按真实路由直接可用；② 换域名时无需改代码。
   ★ 换域名方法：在 TVBox 源配置的 extend 里写 {"host":"https://新域名"}
     （也可让 init 接收一个 URL 字符串）。脚本会自动把该域名作为首选，
     并在主域名连续不可用时惰性探测内置备用域名。

【部署提醒】app 加载的是服务器副本，改完必须重新上传覆盖 AList 上的同名 .py，
并刷新配置/清缓存。
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
                method = 'POST'   # 带 data 时自动升级为 POST
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
        return '永乐影视'

    def log(self, *args):
        # 子类自带日志，绝不依赖 base Spider 的 log
        try:
            print('[永乐影视]', *args)
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
        """有些 app 实例化后直接调 homeContent，未调 init —— 兜底初始化一次"""
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

        self.host = custom or 'https://www.ylys.tv'
        # 备用域名（站点换域名时优先自动切换；也可由 extend 覆盖）
        self.host_candidates = []
        for h in (self.host, 'https://www.ylys.tv', 'https://www.59v.net',
                  'https://www.ylsp.lv', 'https://ylys.tv'):
            if h and h not in self.host_candidates:
                self.host_candidates.append(h)

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.host + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        # 只保留历史可用源里验证过的 4 个一级分类，避免"幽灵分类"
        self.categories = {
            '电影': '1',
            '电视剧': '2',
            '综艺': '3',
            '动漫': '4',
        }
        # 真实站点 filters（子分类在 MacCMS 中同样是 type id）
        self.filters = {
            '1': [{'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''}, {'n': '动作片', 'v': '6'}, {'n': '喜剧片', 'v': '7'},
                {'n': '爱情片', 'v': '8'}, {'n': '科幻片', 'v': '9'}, {'n': '恐怖片', 'v': '11'}]}],
            '2': [{'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''}, {'n': '国产剧', 'v': '13'}, {'n': '港台剧', 'v': '14'},
                {'n': '日剧', 'v': '15'}, {'n': '韩剧', 'v': '33'}, {'n': '欧美剧', 'v': '16'}]}],
            '3': [{'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''}, {'n': '内地综艺', 'v': '27'}, {'n': '港台综艺', 'v': '28'},
                {'n': '日本综艺', 'v': '29'}, {'n': '韩国综艺', 'v': '36'}]}],
            '4': [{'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''}, {'n': '国产动漫', 'v': '31'}, {'n': '日本动漫', 'v': '32'},
                {'n': '欧美动漫', 'v': '42'}, {'n': '其他动漫', 'v': '43'}]}],
        }
        # 分类页兜底路由（真实路由永远排在最前面）
        self.list_tpls = [
            '/vodtype/{id}-{pg}.html',
            '/list/{id}-{pg}.html',
            '/vodshow/{id}--------{pg}---.html',
            '/vodshow/{id}-----------{pg}---.html',
            '/index.php/vod/type/id/{id}/page/{pg}.html',
            '/vod/{id}-{pg}.html',
            '/type/{id}-{pg}.html',
        ]
        self.search_tpls = [
            '/index.php/vod/search.html?wd=',
            '/vodsearch/-------------.html?wd=',
            '/search/-------------.html?wd=',
            '/vodsearch.html?wd=',
        ]
        self._ok_cat = {}          # tid -> 已验证可用的第 1 页路径
        self._fail = 0             # 连续失败计数
        self._fail_at = 0
        self._max_fail = 3
        self._max_try = 6
        self._host_checked = False
        self._img_holder = re.compile(r'load(?:ing)?\.(?:gif|png)|blank\.gif|placeholder|lazy', re.I)
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

    def _is_bad_html(self, html):
        if not html:
            return True
        low = html[:600].lower()
        return ('origin is unreachable' in low or 'error 523' in low or
                'cloudflare' in low and len(html) < 3000)

    def _switch_host(self):
        """主域名连续失败时，惰性探测一次备用域名；成功后全局换 host"""
        if self._host_checked:
            return
        self._host_checked = True
        for h in self.host_candidates:
            if h == self.host:
                continue
            try:
                r = self.fetch(h + '/', headers=dict(self.headers))
                t = self._text(r)
                code = self._status(r)
                if (not code or 200 <= code < 300) and len(t) > 1000 and not self._is_bad_html(t):
                    self.log('备用域名可用，已切换:', h)
                    self.host = h
                    self.headers['Referer'] = h + '/'
                    self._fail = 0
                    return
            except Exception:
                continue

    def _http(self, url, extra=None):
        """统一请求：检查 HTTP 状态码（523/404 不当正常页面），失败重试，
        连续失败达阈值则短路 + 探测备用域名，60s 冷却后自动恢复。"""
        try:
            import time
            now = time.time()
            if self._fail >= self._max_fail:
                if now - self._fail_at > 60:
                    self._fail = 0
                    self._host_checked = False
                else:
                    return ''
        except Exception:
            now = 0
        hd = dict(self.headers)
        if extra:
            hd.update(extra)
        for attempt in range(2):
            try:
                resp = self.fetch(url, headers=hd)
                html = self._text(resp)
                code = self._status(resp)
                if (code and not (200 <= code < 300)) or self._is_bad_html(html):
                    raise RuntimeError('bad response %s' % code)
                self._fail = 0
                return html
            except Exception as e:
                self._fail += 1
                try:
                    import time
                    self._fail_at = time.time()
                except Exception:
                    pass
                if self._fail >= self._max_fail:
                    self.log('源站连续不可达（%s），暂停请求；正在探测备用域名' % e)
                    self._switch_host()
                    return ''
        return ''

    # ------------------------------------------------------------ URL 工具
    def _full(self, u):
        """把相对路径 / 纯数字 id / 播放 id 补成完整 URL"""
        if not u:
            return ''
        u = str(u).strip().strip('"\'')
        if u.startswith('http'):
            return u
        if u.startswith('//'):
            return 'https:' + u
        if re.fullmatch(r'\d+', u):
            return self.host + '/voddetail/' + u + '/'
        if re.fullmatch(r'\d+(?:-\d+){2}', u):
            return self.host + '/play/' + u + '/'
        return self.host + (u if u.startswith('/') else '/' + u)

    def _norm_id(self, href):
        """从详情链接里归一出 vod_id（真实站点是纯数字），无效返回 ''"""
        if not href:
            return ''
        h = str(href).strip()
        if h.lower().startswith(('javascript:', '#', 'mailto:')):
            return ''
        if re.search(r'/(?:play|vodplay|player)/', h, re.I):
            return ''
        m = re.search(r'/voddetail/(\d+)(?:/|\.html|$)', h, re.I)
        if not m:
            m = re.search(r'/detail/(\d+)(?:/|\.html|$)', h, re.I)
        if m:
            return m.group(1)
        if h.startswith('http') and re.search(r'/(?:voddetail|detail)/\d+', h, re.I):
            return h
        if re.search(r'/(?:voddetail|detail|movie|vod)/\d+(?:\.html|/)', h, re.I):
            return h
        return ''

    def _clean(self, s):
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s or '')).strip()

    # ------------------------------------------------------------ 列表解析
    def _extract_list(self, html):
        """通用列表提取：以详情锚点为块，属性顺序无关，返回 [(id, name, pic, remark)]"""
        items, seen = [], set()
        if not html:
            return items
        anchors = list(re.finditer(
            r'<a\b[^>]*href="([^"]+)"[^>]*>', html, re.I))
        for i, m in enumerate(anchors):
            vid = self._norm_id(m.group(1))
            if not vid or vid in seen:
                continue
            end = anchors[i + 1].start() if i + 1 < len(anchors) else len(html)
            seg = html[m.start():min(end, m.start() + 2200)]
            pm = re.search(r'(?:data-original|data-src|src)="([^"]+)"', seg, re.I)
            if not pm:                     # 必须是带海报的影片卡片，排除文字导航
                continue
            tm = re.search(r'title="([^"]*)"', m.group(0))
            if not tm:
                tm = re.search(r'title="([^"]*)"', seg)
            if not tm:
                tm = re.search(r'<(?:strong|h\d)[^>]*>\s*([^<]*?)\s*<', seg)
            nm = re.search(r'(?:module-item-note|pic-text|poster-item-note)[^>]*>\s*([^<]*?)\s*<', seg)
            name = self._clean(tm.group(1) if tm else '')
            if not name:
                continue
            pic = pm.group(1).strip()
            if self._img_holder.search(pic) or pic.startswith('data:'):
                pic = ''
            seen.add(vid)
            items.append((vid, name, self._full(pic),
                          self._clean(nm.group(1) if nm else '')))
        return items

    def _to_videos(self, items, limit=0):
        out = [{'vod_id': i[0], 'vod_name': i[1], 'vod_pic': i[2],
                'vod_remarks': i[3]} for i in items]
        return out[:limit] if limit else out

    # ------------------------------------------------------------ 首页 / 分类
    def homeContent(self, filter):
        self._ensure()
        try:
            classes = [{'type_name': n, 'type_id': t} for n, t in self.categories.items()]
            home = self._http(self.host + '/')
            return {'class': classes, 'filters': self.filters,
                    'list': self._to_videos(self._extract_list(home), 20) if home else []}
        except Exception as e:
            self.log('homeContent error:', e)
            return {'class': [], 'filters': {}}

    def homeVideoContent(self):
        self._ensure()
        try:
            home = self._http(self.host + '/')
            return {'list': self._to_videos(self._extract_list(home), 30) if home else []}
        except Exception as e:
            self.log('homeVideoContent error:', e)
            return {'list': []}

    def _cat_urls(self, tid, pg):
        urls = []
        if pg <= 1:
            cached = self._ok_cat.get(str(tid))
            if cached:
                urls.append(self.host + cached)
            urls += [self.host + '/vodtype/%s/' % tid,
                     self.host + '/vodtype/%s.html' % tid,
                     self.host + '/list/%s.html' % tid]
        else:
            urls += [self.host + '/vodtype/%s/page/%d/' % (tid, pg),
                     self.host + '/vodshow/%s-----------%d---.html' % (tid, pg),
                     self.host + '/vodtype/%s-%d.html' % (tid, pg),
                     self.host + '/list/%s-%d.html' % (tid, pg)]
        urls += [self.host + t.format(id=tid, pg=pg) for t in self.list_tpls]
        out, seen = [], set()
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _load_category(self, tid, pg):
        """按优先级试候选路由，取第一个解析出影片的"""
        for url in self._cat_urls(tid, pg)[:self._max_try]:
            if self._fail >= self._max_fail:
                return []
            html = self._http(url)
            if not html or len(html) < 500:
                continue
            items = self._extract_list(html)
            if items:
                if pg <= 1:
                    self._ok_cat[str(tid)] = url[len(self.host):]
                return self._to_videos(items)
        return []

    def categoryContent(self, tid, pg, filter, extend):
        self._ensure()
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        extend = self._parse_extend(extend)
        try:
            key = str(tid or '')
            # 子分类筛选：MacCMS 里子分类也是 type id
            cls = str(extend.get('class') or '').strip()
            if cls.isdigit() and cls != '0':
                key = cls
            if key in self.categories:
                key = self.categories[key]
            key = re.sub(r'\D', '', key) or '1'
            videos = self._load_category(key, pg)
            return {'list': videos, 'page': pg,
                    'pagecount': 9999 if videos else max(1, pg - 1),
                    'limit': 20, 'total': 999999 if videos else 0}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0}

    # ------------------------------------------------------------ 详情
    def _meta(self, html, prop):
        m = re.search(r'<meta[^>]*property="og:%s"[^>]*content="([^"]*)"' % prop, html, re.I)
        if not m:
            m = re.search(r'<meta[^>]*content="([^"]*)"[^>]*property="og:%s"' % prop, html, re.I)
        return self._clean(m.group(1)) if m else ''

    def _parse_plays(self, html, vid):
        """返回 (线路名列表, 每线路的 '集名$播放id' 用 # 连接的列表)。
        真实结构：module-tab-item 给线路名，a.module-play-list-link 给集链接。"""
        play_from, play_url = [], []
        vid = str(vid or '')
        vid_ok = bool(re.fullmatch(r'\d+', vid))

        # 线路名（tab 顺序 = 页面显示顺序）
        tabs = []
        for m in re.finditer(
                r'<(?:div|a|li|span)[^>]*class="[^"]*module-tab-item[^"]*"[^>]*>(.*?)</(?:div|a|li|span)>',
                html, re.S | re.I):
            sm = re.search(r'<span[^>]*>\s*([^<]*?)\s*</span>', m.group(1))
            nm = self._clean(sm.group(1) if sm else m.group(1))
            if nm and nm not in tabs:
                tabs.append(nm)

        # 剧集链接：不依赖 class 与 href 的先后顺序，按 sid 分组
        groups, order = {}, []
        ep_pat = (r'<a\b[^>]*href="([^"]*?/play/(\d+)-(\d+)-(\d+)'
                  r'(?:\.html)?/?)"[^>]*>(.*?)</a>')
        for m in re.finditer(ep_pat, html, re.S | re.I):
            if vid_ok and m.group(2) != vid:
                continue
            sid, nid, body = m.group(3), m.group(4), m.group(5)
            sm = re.search(r'<span[^>]*>\s*([^<]*?)\s*</span>', body)
            nm = self._clean(sm.group(1) if sm else body) or ('第%s集' % nid)
            pid = '%s-%s-%s' % (m.group(2), sid, nid)
            if sid not in groups:
                groups[sid] = []
                order.append(sid)
            if not any(x.startswith(nm + '$') or x.endswith('$' + pid) for x in groups[sid]):
                groups[sid].append('%s$%s' % (nm, pid))

        if groups:
            for idx, sid in enumerate(order):
                play_from.append(tabs[idx] if idx < len(tabs) else '线路' + sid)
                play_url.append('#'.join(groups[sid]))
            return play_from, play_url

        # 兜底 ① myui 模板：div#playlistN 分块
        names = {}
        for sid, nm in re.findall(r'href="#playlist(\d+)"[^>]*>\s*([^<]*?)\s*</a>', html):
            names[sid] = self._clean(nm) or ('线路' + sid)
        parts = re.split(r'<div id="playlist(\d+)"', html)
        for i in range(1, len(parts) - 1, 2):
            sid, body = parts[i], parts[i + 1]
            eps = []
            for m in re.finditer(
                    r'<a\b[^>]*href="([^"]*(?:/play/|/vodplay/)[^"]*)"[^>]*>(.*?)</a>',
                    body, re.S | re.I):
                nm = self._clean(m.group(2)) or ('第%d集' % (len(eps) + 1))
                eps.append('%s$%s' % (nm, self._full(m.group(1))))
            if eps:
                play_from.append(names.get(sid, '线路' + sid))
                play_url.append('#'.join(eps))
        if play_url:
            return play_from, play_url

        # 兜底 ② 整页任何播放链接，按 sid 分组
        groups, order = {}, []
        for m in re.finditer(r'href="([^"]*?/play/(\d+)-(\d+)-(\d+)[^"]*)"[^>]*>(.*?)</a>',
                             html, re.S | re.I):
            sid = m.group(3)
            nm = self._clean(m.group(5)) or ('第%d集' % (len(groups.get(sid, [])) + 1))
            if sid not in groups:
                groups[sid] = []
                order.append(sid)
            groups[sid].append('%s$%s' % (nm, self._full(m.group(1))))
        for idx, sid in enumerate(order):
            play_from.append(tabs[idx] if idx < len(tabs) else '线路' + sid)
            play_url.append('#'.join(groups[sid]))
        return play_from, play_url

    def detailContent(self, ids):
        self._ensure()
        try:
            one = ids[0] if isinstance(ids, (list, tuple)) else ids
            one = str(one or '').strip()
            url = self._full(one)
            html = self._http(url)
            if not html:
                return {'list': []}

            vid = ''
            vm = re.search(r'/voddetail/(\d+)', url)
            if vm:
                vid = vm.group(1)
            elif re.fullmatch(r'\d+', one):
                vid = one

            title = self._meta(html, 'title')
            if title:
                title = re.split(r'\s*[-_|]\s*', title)[0].strip()
            if not title:
                for pat in (r'<h1[^>]*>\s*([^<]*?)\s*</h1>',
                            r'<title>\s*《?(.*?)》?\s*[-_|]'):
                    m = re.search(pat, html, re.S)
                    if m and self._clean(m.group(1)):
                        title = self._clean(m.group(1))
                        break
            pic = self._meta(html, 'image')
            content = self._meta(html, 'description')
            if not content:
                m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html, re.I)
                content = self._clean(m.group(1)) if m else ''

            year, area = '', ''
            ym = re.search(r'<a[^>]*title="(\d{4})"[^>]*href="/vodshow/', html)
            if ym:
                year = ym.group(1)
            am = re.search(r'<a[^>]*title="([^"]{1,10})"[^>]*href="/vodshow/\d+-%', html)
            if am:
                area = self._clean(am.group(1))
            remark = ' | '.join(x for x in (year, area) if x)

            play_from, play_url = self._parse_plays(html, vid or one)
            # ★ 线路数必须与 $$$ 段数严格相等
            if len(play_from) != len(play_url):
                n = min(len(play_from), len(play_url))
                play_from, play_url = play_from[:n], play_url[:n]
            if not play_from:
                play_from, play_url = ['永乐影视'], ['#']

            video = {
                'vod_id': one,
                'vod_name': title,
                'vod_pic': self._full(pic),
                'vod_year': year,
                'vod_area': area,
                'vod_remarks': remark,
                'vod_content': content,
                'vod_play_from': '$$$'.join(play_from),
                'vod_play_url': '$$$'.join(play_url),
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    # ------------------------------------------------------------ 搜索
    def _search_post(self, url, params):
        """app 兼容的 POST：data 传 str、显式 Content-Type、手动跟随 302"""
        headers = dict(self.headers)
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        data = urllib.parse.urlencode(params)   # str，不转 bytes
        html = ''
        try:
            resp = self.fetch(url, headers=headers, data=data, allow_redirects=False)
            html = self._text(resp)
            try:
                loc = resp.headers.get('Location') or resp.headers.get('location') or ''
            except Exception:
                loc = ''
            if loc:
                target = loc if loc.startswith('http') else self._full(loc)
                html = self._text(self.fetch(target, headers=headers))
        except Exception:
            html = ''
        if not html or self._is_bad_html(html):
            try:
                html = self._text(self.fetch(url, headers=headers, data=data))
            except Exception:
                html = ''
        return html

    def searchContent(self, key, quick, pg=1):
        self._ensure()
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        try:
            kw = urllib.parse.quote(str(key or '').strip())
            if not kw:
                return {'list': [], 'page': pg}
            # 真实路由：/vodsearch/{关键词}-------------/，翻页加 /page/{pg}/
            tail = '-------------/'
            if pg > 1:
                tail = '-------------/page/%d/' % pg
            urls = [self.host + '/vodsearch/' + kw + tail]
            for tpl in self.search_tpls:
                u = self.host + tpl + kw
                if pg > 1:
                    u += '&page=%d' % pg
                urls.append(u)
            for u in urls:
                html = self._http(u)
                items = self._extract_list(html) if html else []
                if items:
                    return {'list': self._to_videos(items), 'page': pg,
                            'pagecount': 9999, 'total': 999999}
            # POST 兜底
            for u in urls[:3]:
                html = self._search_post(u.split('?')[0], {'wd': str(key).strip()})
                items = self._extract_list(html) if html else []
                if items:
                    return {'list': self._to_videos(items), 'page': pg,
                            'pagecount': 1, 'total': len(items)}
            return {'list': [], 'page': pg, 'pagecount': max(1, pg - 1), 'total': 0}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg}

    # ------------------------------------------------------------ 播放
    def playerContent(self, flag, id, vipFlags):
        self._ensure()
        try:
            raw = str(id or '').strip()
            hd = dict(self.headers)
            if not raw:
                return {'parse': 1, 'url': '', 'header': hd}
            if raw.startswith('magnet:') or self.isVideoFormat(raw):
                return {'parse': 0, 'url': raw, 'header': hd}

            url = self._full(raw)
            html = self._http(url)
            play_url = ''
            if html:
                idx = html.find('player_aaaa')
                if idx < 0:
                    idx = html.find('player_')
                if idx >= 0:
                    s = html.find('{', idx)
                    if s >= 0:
                        # 用 JSONDecoder 精确取出配平的 JSON 对象，不受后续 JS 干扰
                        try:
                            data, _ = json.JSONDecoder().raw_decode(html[s:])
                            play_url = str(data.get('url') or data.get('play_url') or '')
                            enc = str(data.get('encrypt') or '')
                            if enc in ('1', '2') and play_url:
                                try:
                                    play_url = base64.b64decode(
                                        play_url + '=' * (-len(play_url) % 4)
                                    ).decode('utf-8', 'replace')
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    if not play_url:
                        m = re.search(r'["\']?url["\']?\s*:\s*["\']([^"\']+)["\']', html[idx:idx + 3000])
                        if m:
                            play_url = m.group(1)
                if not play_url:
                    m = re.search(r'["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', html)
                    play_url = m.group(1) if m else ''

            if not play_url:
                # 解析不出直链时把播放页交给 app 的官方解析
                return {'parse': 1, 'url': url, 'header': hd}
            play_url = (play_url.replace('\\/', '/').replace('\\u002F', '/')
                        .replace('&amp;', '&').strip())
            if not play_url.startswith(('http', 'magnet:')):
                play_url = self._full(play_url)
            parse = 0 if self.isVideoFormat(play_url) else 1
            return {'parse': parse, 'url': play_url, 'header': hd}
        except Exception as e:
            self.log('playerContent error:', e)
            return {'parse': 1, 'url': id, 'header': dict(self.headers)}


# ==================================================================== 本地测试
def _offline_selftest(sp):
    """源站 523 时用贴近真实结构的离线 HTML 验证全部解析逻辑（不改网络行为）"""
    CARD = ('<a href="/voddetail/{id}/" title="{name}">'
            '<img data-original="/upload/{id}.jpg">'
            '<div class="module-item-note">{note}</div></a>')
    list_p1 = ('<html><body>' + ''.join(
        CARD.format(id=86027 + i, name='测试影片%d' % i, note='HD高清') for i in range(6))
        + '</body></html>')
    list_p2 = ('<html><body>' + ''.join(
        CARD.format(id=96027 + i, name='第二页影片%d' % i, note='更新至12集') for i in range(6))
        + '</body></html>')
    detail = '''<html><head>
<meta property="og:title" content="测试影片0-永乐影视">
<meta property="og:image" content="/upload/86027.jpg">
<meta property="og:description" content="这是一段剧情简介。">
</head><body>
<a title="2024" href="/vodshow/1-----------2024/">2024</a>
<a title="中国大陆" href="/vodshow/1-%E4%B8%AD%E5%9B%BD%E5%A4%A7%E9%99%86----------/">中国大陆</a>
<div class="module-tab-item"><span>全球3线</span><small>2</small></div>
<div class="module-tab-item"><span>大陆0线</span><small>2</small></div>
<a class="module-play-list-link" href="/play/86027-3-1/"><span>第1集</span></a>
<a class="module-play-list-link" href="/play/86027-3-2/"><span>第2集</span></a>
<a class="module-play-list-link" href="/play/86027-1-1/"><span>第1集</span></a>
<a class="module-play-list-link" href="/play/86027-1-2/"><span>第2集</span></a>
</body></html>'''
    player = ('<html><script>var player_aaaa={"flag":"play","encrypt":0,'
              '"url":"https:\\/\\/cdn.test.com\\/86027.m3u8","from":"yl"};'
              '</script></html>')
    search = '<html><body>' + ''.join(
        CARD.format(id=77001 + i, name='庆余年%d' % i, note='全46集') for i in range(3)) + '</body></html>'

    class R:
        def __init__(self, t):
            self.text = t
            self.content = t.encode('utf-8')
            self.status_code = 200
            self.headers = {}

        def json(self):
            return json.loads(self.text)

    def fake(url, headers=None, data=None, method='GET', timeout=10, **kwargs):
        u = str(url)
        if '/play/' in u:
            return R(player)
        if '/voddetail/' in u:
            return R(detail)
        if '/vodsearch/' in u or 'wd=' in u or 'search' in u:
            return R(search)
        if '/page/2/' in u or u.endswith('-2.html'):
            return R(list_p2)
        return R(list_p1)

    sp.fetch = fake
    sp._fail = 0
    sp._host_checked = True
    ok = []

    def chk(name, cond, extra=''):
        ok.append(bool(cond))
        print('  [%s] %s %s' % ('PASS' if cond else 'FAIL', name, extra))

    print('=== 离线自测（站点 523，使用真实结构样本）===')
    h = sp.homeContent({})
    chk('homeContent 分类=4 且 filter 齐备',
        len(h['class']) == 4 and len(h['filters']) == 4,
        str([c['type_name'] for c in h['class']]))
    chk('homeContent 首页推荐', len(h['list']) > 0, '%d 项' % len(h['list']))
    hv = sp.homeVideoContent()
    chk('homeVideoContent', len(hv['list']) > 0, '%d 项' % len(hv['list']))
    for c in h['class']:
        r = sp.categoryContent(c['type_id'], 1, {}, {})
        chk('分类 %s' % c['type_name'], len(r['list']) > 0,
            '%d 项 首项=%s' % (len(r['list']), r['list'][0]['vod_name'] if r['list'] else ''))
    p1 = sp.categoryContent('1', 1, {}, {})
    p2 = sp.categoryContent('1', 2, {}, {})
    chk('翻页第1页≠第2页',
        bool(p1['list'] and p2['list'] and p1['list'][0]['vod_id'] != p2['list'][0]['vod_id']),
        '%s -> %s' % (p1['list'][0]['vod_id'] if p1['list'] else '-',
                      p2['list'][0]['vod_id'] if p2['list'] else '-'))
    chk('字符串 pg 兼容', len(sp.categoryContent('1', '1', {}, {})['list']) > 0)
    chk('字符串 extend 兼容', len(sp.categoryContent('1', 1, {}, '{}')['list']) > 0)
    chk('子分类筛选不报错', len(sp.categoryContent('1', 1, {}, '{"class":"6"}')['list']) > 0)

    d = sp.detailContent([p1['list'][0]['vod_id']])['list']
    chk('detailContent 返回详情', len(d) == 1)
    if d:
        v = d[0]
        fs, us = v['vod_play_from'].split('$$$'), v['vod_play_url'].split('$$$')
        chk('线路数 == $$$段数', len(fs) == len(us), '%d 线路' % len(fs))
        chk('线路名正确', fs[:2] == ['全球3线', '大陆0线'], str(fs))
        chk('每线路2集且格式 集名$播放id',
            all(len(u.split('#')) == 2 and '$' in u.split('#')[0] for u in us),
            str(us[0]) if us else '')
        chk('详情元数据', v['vod_name'] == '测试影片0' and v['vod_year'] == '2024',
            '%s / %s / %s' % (v['vod_name'], v['vod_year'], v['vod_area']))
        pid = us[0].split('#')[0].split('$', 1)[1]
        r4 = sp.playerContent(fs[0], pid, None)
        chk('playerContent 直出 m3u8',
            r4['parse'] == 0 and r4['url'] == 'https://cdn.test.com/86027.m3u8',
            r4['url'])
        chk('playerContent 带 header', isinstance(r4.get('header'), dict) and
            'Referer' in r4['header'])
    sr = sp.searchContent('庆余年', False, 1)
    chk('searchContent 有结果', len(sr['list']) > 0,
        str([x['vod_name'] for x in sr['list'][:3]]))

    # 源站不可达时必须返回合法空结构，不抛异常
    def dead(url, headers=None, **kwargs):
        raise RuntimeError('523')

    sp.fetch = dead
    sp._fail, sp._host_checked = 0, True
    r5 = sp.categoryContent('1', 1, {}, {})
    chk('站点不可达时降级为空且不抛异常', isinstance(r5, dict) and r5['list'] == [])
    print('=== 离线自测：%d/%d 通过 ===' % (sum(ok), len(ok)))
    return all(ok)


def main():
    sp = Spider()
    sp.init('')
    print('=== 站点可达性 ===')
    probe = sp._http(sp.host + '/')
    if not probe:
        print('  当前源站不可达（Cloudflare 523 / 超时），跳过在线测试。')
        print('  这是站点下线，不是脚本问题；站点恢复或换域名后脚本可直接工作。\n')
        _offline_selftest(sp)
        return
    print('  首页可访问，%d 字节\n' % len(probe))
    print('=== homeContent ===')
    r = sp.homeContent({})
    print('  classes:', [(c['type_name'], c['type_id']) for c in r['class']])
    print('  首页推荐:', len(r.get('list', [])), '项\n')
    print('=== 分类列表 ===')
    for c in r['class']:
        r2 = sp.categoryContent(c['type_id'], 1, {}, {})
        print('  %-6s id=%s -> %d 项 %s' % (
            c['type_name'], c['type_id'], len(r2['list']),
            (r2['list'][0]['vod_name'] + ' | ' + r2['list'][0]['vod_id']) if r2['list'] else ''))
    first_tid = r['class'][0]['type_id'] if r['class'] else '1'
    print('\n=== 翻页 ===')
    p1 = sp.categoryContent(first_tid, 1, {}, {})
    p2 = sp.categoryContent(first_tid, 2, {}, {})
    print('  p1 first:', p1['list'][0]['vod_id'] if p1['list'] else None)
    print('  p2 first:', p2['list'][0]['vod_id'] if p2['list'] else None)
    print('\n=== 兼容性：字符串 pg / 字符串 extend ===')
    print('  str pg:', len(sp.categoryContent(first_tid, '1', {}, {})['list']), '项')
    print('  str extend:', len(sp.categoryContent(first_tid, 1, {}, '{}')['list']), '项')
    print('\n=== detailContent ===')
    if p1['list']:
        vs = sp.detailContent([p1['list'][0]['vod_id']])['list']
        if vs:
            v = vs[0]
            fs, us = v['vod_play_from'].split('$$$'), v['vod_play_url'].split('$$$')
            print('  name=%s 线路数=%d $$$段数=%d' % (v['vod_name'], len(fs), len(us)))
            for f, u in zip(fs, us):
                print('   %s -> %d 集, 首集: %s' % (f, len(u.split('#')), u.split('#')[0][:70]))
            print('\n=== playerContent ===')
            if us and us[0] and us[0] != '#':
                pid = us[0].split('#')[0].split('$', 1)[1]
                r4 = sp.playerContent(fs[0], pid, None)
                print('  parse=%s url=%s' % (r4['parse'], str(r4['url'])[:120]))
    print('\n=== searchContent ===')
    rs = sp.searchContent('庆余年', False, 1)
    print('  结果数:', len(rs['list']), [x['vod_name'] for x in rs['list'][:5]])


if __name__ == '__main__':
    main()
