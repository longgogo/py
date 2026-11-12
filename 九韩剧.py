# -*- coding: utf-8 -*-
"""
九韩剧（9hanju.com）TVBox 蜘蛛源 —— 修复版
依据「电影猎手」规范骨架重写，原文件保持不变。

=== 本次实测（2026-11-12，站点在线）===
站点结构：EmpireCMS，/list/{tid}-{year}-{by}-{pg}.html 路径式分页；
          /detail/{id}.html 详情；剧集 bb_a('3752_1_1','第01集',event)；
          /u/u1.php?ud={集id} → base64(IV+密文) → AES-256-CBC → 原始 m3u8。

=== 修复清单 ===
1.【无法搜索·核心】POST /search/ 返回 302，Location 是**相对路径**
   `code.php?id=126`。旧版用 self.host + '/' + loc 拼成
   /code.php?id=126 → 实测 404「页面未找到」。
   本地 fallback 的 urllib 会自动跟随 302 所以「碰巧能搜」，
   app 的 fetch 不自动跟随就拿到 404，表现为搜索永远无结果。
   改用 urllib.parse.urljoin(base='/search/', loc) 正确解析，
   并加「禁止跟随 / 自动跟随 / bytes data」三条路径兜底，
   同时兼容 Location 大小写、Set-Cookie、无结果的「信息提示」页。
2.【点播错乱】detailContent 把 12 集用 $$$ 连接，而 vod_play_from
   只有 1 条线路，违反 TVBox 规范（集间用 #、线路间用 $$$）。
   改为按 playlist 分组，强制 $$$ 段数 = 线路数。
3.【播放失效】playerContent 依赖 pycryptodome，本环境（及不少 app
   runtime）没有 Crypto → 直接返回空 url。内置纯 Python AES-256-CBC
   兜底解密。另外旧版把地址套进 /m3/edit-down.php 代理，而该代理
   原样返回 m3u8 主列表，其中的相对分片 3000k/hls/mixed.m3u8 会
   被播放器解析到 www.9hanju.com/m3/ 下 → 实测 404。
   改为直接返回解密出的原始 m3u8 直链（实测无需 Referer 亦 200）。
4.【其它加固】网络层校验状态码 / 523 错误页 + 失败冷却；空列表收敛
   pagecount；搜索结果补封面（封面 URL 有稳定规律）并加解析兜底；
   元数据清洗 HTML 标签（状态字段是 <em> 包裹，旧版取到空字符串）；
   init 支持 extend={"host": "https://新域名"}；_ensure() 防 app 未调 init。
"""
import sys, os, re, json, base64, time, gzip
import urllib.parse, urllib.request, urllib.error, ssl
from functools import lru_cache

try:
    from base.spider import Spider
except Exception:
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        """本地测试用：让 allow_redirects=False 真正生效，以便覆盖 302 分支"""

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    class Spider:
        def __init__(self):
            self.headers = {}

        def fetch(self, url, headers=None, data=None, method='GET', timeout=10, **kwargs):
            """本地 fallback：模拟 app 的 fetch（text / status_code / headers）"""
            try:
                ssl._create_default_https_context = ssl._create_unverified_context
            except Exception:
                pass
            h = dict(getattr(self, 'headers', {}) or {})
            if headers:
                h.update(headers)
            body = None
            if data is not None:
                method = 'POST'  # 带 data 隐式 POST，不要求调用方传 method=
                body = data.encode('utf-8') if isinstance(data, str) else data
            req = urllib.request.Request(url, data=body, headers=h, method=method)

            opener = None
            if kwargs.get('allow_redirects', True) is False:
                ctx = ssl._create_unverified_context()
                opener = urllib.request.build_opener(
                    urllib.request.HTTPSHandler(context=ctx), _NoRedirect())
            try:
                resp = opener.open(req, timeout=timeout) if opener \
                    else urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                if opener and 300 <= e.code < 400:
                    resp = e          # 302 也作为可读取的响应对象返回
                else:
                    raise
            raw = resp.read()
            if raw[:2] == b'\x1f\x8b':
                raw = gzip.decompress(raw)

            class R:
                pass

            r = R()
            r.text = raw.decode('utf-8', 'replace')
            r.content = raw
            r.status_code = getattr(resp, 'status', None) or getattr(resp, 'code', 200)
            try:
                r.headers = dict(resp.headers.items())
            except Exception:
                r.headers = {}
            r.json = lambda: json.loads(r.text)
            return r

try:
    from Crypto.Cipher import AES
except Exception:
    AES = None


# ---------------------------------------------------------------------------
# 纯 Python AES-256-CBC 解密（app runtime 没有 pycryptodome 时的兜底）
# ---------------------------------------------------------------------------
def _gf_mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = ((a << 1) ^ 0x1b) & 0xff if a & 0x80 else (a << 1) & 0xff
        b >>= 1
    return r & 0xff


def _gf_inv(a):
    if a == 0:
        return 0
    r = 1
    for _ in range(254):
        r = _gf_mul(r, a)
    return r


@lru_cache(maxsize=8)
def _aes_tables(key):
    def sbox_val(x):
        v = _gf_inv(x)
        s = v
        for _ in range(4):
            v = ((v << 1) | (v >> 7)) & 0xff
            s ^= v
        return s ^ 0x63

    sbox = [sbox_val(i) for i in range(256)]
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    w = [list(key[i:i + 4]) for i in range(0, 32, 4)]
    rcon = 1
    for i in range(8, 60):
        t = list(w[i - 1])
        if i % 8 == 0:
            t = t[1:] + t[:1]
            t = [sbox[x] for x in t]
            t[0] ^= rcon
            rcon = _gf_mul(rcon, 2)
        elif i % 8 == 4:
            t = [sbox[x] for x in t]
        w.append([w[i - 8][j] ^ t[j] for j in range(4)])
    return tuple(inv), tuple(tuple(x) for x in w)


def _aes_cbc_decrypt(data, key):
    inv, w = _aes_tables(key)
    iv, ct = data[:16], data[16:]
    if len(ct) % 16:
        raise ValueError('bad ciphertext length')

    def add_round_key(s, rnd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rnd * 4 + c][r]

    def dec_block(block):
        s = [[block[c * 4 + r] for c in range(4)] for r in range(4)]
        add_round_key(s, 14)
        for rnd in range(13, 0, -1):
            s = [s[r][-r:] + s[r][:-r] if r else list(s[r]) for r in range(4)]
            s = [[inv[x] for x in row] for row in s]
            add_round_key(s, rnd)
            for c in range(4):
                a0, a1, a2, a3 = s[0][c], s[1][c], s[2][c], s[3][c]
                s[0][c] = _gf_mul(a0, 14) ^ _gf_mul(a1, 11) ^ _gf_mul(a2, 13) ^ _gf_mul(a3, 9)
                s[1][c] = _gf_mul(a0, 9) ^ _gf_mul(a1, 14) ^ _gf_mul(a2, 11) ^ _gf_mul(a3, 13)
                s[2][c] = _gf_mul(a0, 13) ^ _gf_mul(a1, 9) ^ _gf_mul(a2, 14) ^ _gf_mul(a3, 11)
                s[3][c] = _gf_mul(a0, 11) ^ _gf_mul(a1, 13) ^ _gf_mul(a2, 9) ^ _gf_mul(a3, 14)
        s = [s[r][-r:] + s[r][:-r] if r else list(s[r]) for r in range(4)]
        s = [[inv[x] for x in row] for row in s]
        add_round_key(s, 0)
        return bytes(s[r][c] for c in range(4) for r in range(4))

    out, prev = b'', iv
    for i in range(0, len(ct), 16):
        blk = ct[i:i + 16]
        out += bytes(a ^ b for a, b in zip(dec_block(blk), prev))
        prev = blk
    pad = out[-1] if out else 0
    if 1 <= pad <= 16 and out[-pad:] == bytes([pad]) * pad:
        out = out[:-pad]
    return out


class Spider(Spider):

    PIC_TPL = 'https://gimg1.baidu.com/gimg/app=2028&src=pics.9hanju.com/pics/%s.jpg'

    def getName(self):
        return '九韩剧'

    def log(self, *args):
        # 子类自带，绝不调用 base Spider 的 log（app 里没有该方法）
        print('[jiuhanju]', *args)

    # ------------------------------------------------------------------
    # 初始化 / 通用工具
    # ------------------------------------------------------------------
    def init(self, extend=''):
        self.host = 'https://www.9hanju.com'
        ex = self._parse_extend(extend)
        h = ex.get('host') or ex.get('site') or ''
        if isinstance(h, str) and h.strip().startswith('http'):
            self.host = h.strip().rstrip('/')
        self.aes_key = b'my-to-newhan-2025'.ljust(32, b'\0')
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        self._fail = 0
        self._blocked_until = 0

    def _ensure(self):
        """app 可能未调用 init 就直接请求；保证必需属性存在"""
        if not getattr(self, 'host', ''):
            self.init('')
        if not hasattr(self, '_fail'):
            self._fail = 0
        if not hasattr(self, '_blocked_until'):
            self._blocked_until = 0
        if not hasattr(self, 'headers'):
            self.headers = {'User-Agent': 'Mozilla/5.0', 'Referer': self.host + '/'}

    @staticmethod
    def _parse_extend(extend):
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend.strip() else {}
            except Exception:
                return {}
        return extend if isinstance(extend, dict) else {}

    @staticmethod
    def _txt(s):
        """去标签 + 常见实体还原"""
        s = re.sub(r'<[^>]+>', '', s or '')
        for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'),
                     ('&gt;', '>'), ('&quot;', '"'), ('&#39;', "'"), ('&apos;', "'")):
            s = s.replace(a, b)
        return re.sub(r'\s+', ' ', s).strip()

    @staticmethod
    def _bad_page(html):
        if not html:
            return True
        low = html.lower()
        return ('origin is unreachable' in low or 'error 523' in low
                or '页面未找到' in html or '404错误' in html
                or ('cloudflare' in low and 'error' in low and len(html) < 20000))

    def _get(self, url, headers=None):
        """统一 GET：校验状态码/错误页，连续失败短路 60s"""
        self._ensure()
        if self._blocked_until > time.time():
            return ''
        for attempt in range(2):
            try:
                # 只传 headers（app 的 fetch 只证明过 headers / data /
                # allow_redirects 三种参数，不传 method / timeout）
                resp = self.fetch(url, headers=headers or dict(self.headers))
                status = getattr(resp, 'status_code', 200) or 200
                html = getattr(resp, 'text', '') or ''
                if status >= 400 or self._bad_page(html):
                    raise ValueError('HTTP %s / bad page' % status)
                self._fail = 0
                return html
            except Exception as e:
                if attempt == 0:
                    time.sleep(0.3)
                    continue
                self._fail += 1
                if self._fail >= 3:
                    self._blocked_until = time.time() + 60
                self.log('fetch fail:', e)
        return ''

    def _pic(self, vid):
        m = re.search(r'/detail/(\d+)\.html', str(vid or ''))
        return self.PIC_TPL % m.group(1) if m else ''

    # ------------------------------------------------------------------
    # 列表提取（主正则 + 属性顺序无关的兜底）
    # ------------------------------------------------------------------
    def _extract_list(self, html):
        items, seen = [], set()
        for m in re.finditer(r'<a\b[^>]*href="(/detail/\d+\.html)"[^>]*>', html, re.I):
            href = m.group(1)
            if href in seen:
                continue
            tag = m.group(0)
            t = re.search(r'title="([^"]*)"', tag, re.I)
            p = re.search(r'data-original="([^"]*)"', tag, re.I)
            if not t or not p:
                seg = html[m.start():m.start() + 800]
                t = t or re.search(r'title="([^"]*)"', seg, re.I)
                p = p or re.search(r'data-original="([^"]*)"', seg, re.I)
            if not t:
                tail = re.match(r'\s*([^<]{2,60})</a>', html[m.end():m.end() + 120])
                if tail:
                    t = tail
            name = self._txt(t.group(1)) if t else ''
            if not name:
                continue
            seen.add(href)
            items.append((name, href, p.group(1) if p else self._pic(href)))
        return items

    # ------------------------------------------------------------------
    # 首页 / 分类
    # ------------------------------------------------------------------
    def homeContent(self, filter):
        try:
            classes = [
                {'type_name': '韩剧', 'type_id': '1'},
                {'type_name': '韩国电影', 'type_id': '3'},
                {'type_name': '韩国综艺', 'type_id': '4'},
            ]
            # 实测站点的 year/by 参数会被忽略（各组合均返回同 16 条），
            # 保留筛选入口仅为兼容原有配置，不做无效承诺。
            years = [{'n': '全部', 'v': ''}] + [
                {'n': str(y), 'v': str(y)} for y in range(2026, 2019, -1)]
            sort = [{'n': '默认', 'v': ''}, {'n': '最新', 'v': 'newstime'},
                    {'n': '最热', 'v': 'onclick'}]
            f = [{'key': 'year', 'name': '年份', 'value': years},
                 {'key': 'by', 'name': '排序', 'value': sort}]
            return {'class': classes, 'filters': {'1': f, '3': f, '4': f}}
        except Exception as e:
            self.log('homeContent error:', e)
            return {'class': [], 'filters': {}}

    def homeVideoContent(self):
        try:
            self._ensure()
            html = self._get(self.host + '/')
            videos = []
            for title, href, pic in self._extract_list(html)[:24]:
                videos.append({'vod_id': href, 'vod_name': title,
                               'vod_pic': pic, 'vod_remarks': ''})
            return {'list': videos}
        except Exception as e:
            self.log('homeVideoContent error:', e)
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        try:
            self._ensure()
            ex = self._parse_extend(extend)
            year = str(ex.get('year', '') or '')
            by = str(ex.get('by', '') or '')
            url = '%s/list/%s-%s-%s-%s.html' % (self.host, tid, year, by, pg)
            html = self._get(url)
            videos = []
            for title, href, pic in self._extract_list(html):
                videos.append({'vod_id': href, 'vod_name': title,
                               'vod_pic': pic, 'vod_remarks': ''})
            # 空列表时收敛 pagecount，避免 app 无限翻页
            pagecount = 9999 if videos else pg
            return {'list': videos, 'page': pg, 'pagecount': pagecount,
                    'limit': 20, 'total': len(videos) if not videos else 999999}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 20, 'total': 0}

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------
    def _parse_plays(self, html):
        """按 <dd id="playlist">线路名</dd> 分组，返回 (线路名列表, 剧集列表)"""
        marks = list(re.finditer(r'<dd\b[^>]*id="playlist"[^>]*>(.*?)</dd>',
                                 html, re.S | re.I))
        ep_pat = re.compile(r"bb_a\(\s*'([^']+)'\s*,\s*'([^']+)'", re.I)
        names, groups = [], []
        if marks:
            for i, mk in enumerate(marks):
                end = marks[i + 1].start() if i + 1 < len(marks) else len(html)
                eps = ep_pat.findall(html[mk.end():end])
                if eps:
                    names.append(self._txt(mk.group(1)) or '在线云播')
                    groups.append(eps)
        if not groups:
            eps = ep_pat.findall(html)
            if eps:
                names, groups = ['在线云播'], [eps]
        return names, groups

    def detailContent(self, ids):
        try:
            self._ensure()
            if not ids:
                return {'list': []}
            raw = str(ids[0] or '')
            url = self.host + raw if raw.startswith('/') else raw
            html = self._get(url)
            if not html:
                return {'list': []}

            def field(label):
                m = re.search(r'<dt>\s*%s\s*：</dt>\s*<dd>(.*?)</dd>' % label,
                              html, re.S)
                return self._txt(m.group(1)) if m else ''

            title_m = re.search(r'id="m"[^>]*>(.*?)</dd>', html, re.S)
            pic_m = re.search(r'data-original="([^"]+)"', html)
            content_m = re.search(r'剧情：</dt><dd>(.*?)<a\s+href="#jq">详细</a>',
                                  html, re.S)
            director_m = re.search(
                r'<div class="cast-name">([^<]+)</div>\s*'
                r'<div class="cast-role">导演</div>', html)
            year = field('上映')[:4]
            content = self._txt(content_m.group(1)) if content_m else ''

            names, groups = self._parse_plays(html)
            play_from = '$$$'.join(names) if names else ''
            # 关键：集间用 #，线路间用 $$$，段数必须等于线路数
            play_url = '$$$'.join(
                '#'.join('%s$%s' % (self._txt(ep[1]) or '第%d集' % (n + 1), ep[0])
                         for n, ep in enumerate(eps))
                for eps in groups)

            video = {
                'vod_id': raw,
                'vod_name': self._txt(title_m.group(1)) if title_m else field('片名'),
                'vod_pic': pic_m.group(1) if pic_m else self._pic(raw),
                'vod_year': year,
                'vod_area': '韩国',
                'vod_actor': field('主演'),
                'vod_director': self._txt(director_m.group(1)) if director_m else '',
                'vod_remarks': field('状态') or field('集数'),
                'vod_content': content,
                'vod_play_from': play_from,
                'vod_play_url': play_url,
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    # ------------------------------------------------------------------
    # 搜索（本次核心修复）
    # ------------------------------------------------------------------
    @staticmethod
    def _header_of(resp, name):
        """大小写不敏感地取响应头（app 返回的 headers 可能是 dict/Map）"""
        try:
            hs = resp.headers
            pairs = hs.items() if hasattr(hs, 'items') else hs
            for k, v in pairs:
                if str(k).lower() == name.lower():
                    return str(v)
        except Exception:
            pass
        return ''

    def _search_html(self, key):
        """POST /search/ → 302 code.php?id=xxx → 结果页 HTML"""
        self._ensure()
        base = self.host + '/search/'
        data = urllib.parse.urlencode({'show': 'searchkey', 'keyboard': key})  # str
        headers = dict(self.headers)
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        headers['Referer'] = base
        marker = '/detail/'

        def ok(h):
            return bool(h) and marker in h and not self._bad_page(h)

        def no_result(h):
            """站点「无匹配」时直接返回 200 信息提示页，不要重复 POST"""
            if not h:
                return False
            if '信息提示' in h:
                return True
            t = re.search(r'<title>(.*?)</title>', h, re.S | re.I)
            return bool(t and '搜索结果' in t.group(1) and marker not in h)

        def follow(resp, cur):
            """任何一条路径只要拿到 302 响应头，都按相对路径手动跟随一次"""
            if ok(cur):
                return cur
            loc = self._header_of(resp, 'Location')
            if not loc:
                return cur
            gh = dict(self.headers)
            ck = self._header_of(resp, 'Set-Cookie').split(';')[0]
            if ck:
                gh['Cookie'] = ck
            return self._get(urllib.parse.urljoin(base, loc), headers=gh) or cur

        html = ''
        # 路径 1：禁止自动跟随，手动解析 Location（相对路径必须基于 /search/）
        try:
            resp = self.fetch(base, headers=headers, data=data,
                              allow_redirects=False)
            html = follow(resp, getattr(resp, 'text', '') or '')
        except Exception as e:
            self.log('search path1:', e)
            html = ''

        # 路径 2：不传 allow_redirects，交给 fetch 自动跟随
        #         （兼容不接受该 kwarg 的 app runtime）
        if not ok(html) and not no_result(html):
            try:
                resp2 = self.fetch(base, headers=headers, data=data)
                html = follow(resp2, getattr(resp2, 'text', '') or '')
            except Exception as e:
                self.log('search path2:', e)

        # 路径 3：个别 app 只接受 bytes data
        if not ok(html) and not no_result(html):
            try:
                resp3 = self.fetch(base, headers=headers,
                                   data=data.encode('utf-8'))
                html = follow(resp3, getattr(resp3, 'text', '') or '')
            except Exception as e:
                self.log('search path3:', e)

        return html if ok(html) else ''

    def _parse_search(self, html):
        videos, seen = [], set()
        # 主正则：结果页 <p id="name"><a href=... title=...> ... <p id="actor">
        main = re.finditer(
            r'<p id="name">\s*<a\b[^>]*href="(/detail/\d+\.html)"[^>]*>.*?'
            r'<p id="actor"[^>]*>(.*?)</p>', html, re.S | re.I)
        for m in main:
            seg = m.group(0)
            a = re.search(r'<a\b[^>]*>', seg, re.I)
            t = re.search(r'title="([^"]*)"', a.group(0), re.I) if a else None
            if not t:
                continue
            href = m.group(1)
            name = self._txt(t.group(1))
            if not name or href in seen:
                continue
            seen.add(href)
            videos.append({'vod_id': href, 'vod_name': name,
                           'vod_pic': self._pic(href),
                           'vod_remarks': self._txt(m.group(2))})
        if videos:
            return videos
        # 兜底：按 <li> 分块，属性顺序/空白无关
        for block in re.findall(r'<li[^>]*>(.*?)</li>', html, re.S | re.I):
            a = re.search(r'<a\b[^>]*href="(/detail/\d+\.html)"[^>]*>', block, re.I)
            if not a:
                continue
            href = a.group(1)
            t = re.search(r'title="([^"]*)"', a.group(0), re.I)
            if not t:
                t = re.search(r'<a\b[^>]*>\s*([^<]+)</a>', block, re.I)
            name = self._txt(t.group(1)) if t else ''
            if not name or href in seen:
                continue
            seen.add(href)
            ac = re.search(r'<p id="actor"[^>]*>(.*?)</p>', block, re.S | re.I)
            videos.append({'vod_id': href, 'vod_name': name,
                           'vod_pic': self._pic(href),
                           'vod_remarks': self._txt(ac.group(1)) if ac else ''})
        return videos

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        # 站点搜索结果无分页（实测上限 30 条），第 2 页起直接返回空
        if pg > 1:
            return {'list': [], 'page': pg, 'pagecount': 1, 'total': 0}
        try:
            key = str(key or '').strip()
            if not key:
                return {'list': [], 'page': pg, 'pagecount': 1, 'total': 0}
            html = self._search_html(key)
            videos = self._parse_search(html) if html else []
            return {'list': videos, 'page': pg, 'pagecount': 1,
                    'total': len(videos)}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 1, 'total': 0}

    # ------------------------------------------------------------------
    # 播放
    # ------------------------------------------------------------------
    def _decrypt(self, data):
        iv, ct = data[:16], data[16:]
        if AES is not None:
            try:
                out = AES.new(self.aes_key, AES.MODE_CBC, iv).decrypt(ct)
                pad = out[-1] if out else 0
                if 1 <= pad <= 16 and out[-pad:] == bytes([pad]) * pad:
                    out = out[:-pad]
                return out
            except Exception:
                pass
        return _aes_cbc_decrypt(data, self.aes_key)

    def playerContent(self, flag, id, vipFlags):
        result = {'parse': 0, 'url': '', 'header': {}}
        try:
            self._ensure()
            result['header'] = dict(self.headers)
            ep = str(id or '').split('$')[-1].strip()
            if not ep:
                return result
            api = self.host + '/u/u1.php?ud=' + urllib.parse.quote(ep)
            enc = self._get(api)
            if not enc:
                return result
            raw = base64.b64decode(enc.strip())
            plain = self._decrypt(raw).decode('utf-8', 'replace').strip()
            if plain.startswith('http'):
                # 直出原始 m3u8：实测无需 Referer 亦 200；
                # 旧版的 /m3/edit-down.php 代理会让列表内相对分片 404。
                result['url'] = plain
            elif plain:
                result['url'] = (self.host + '/m3/edit-down.php?url='
                                 + urllib.parse.quote(plain))
        except Exception as e:
            self.log('playerContent error:', e)
        return result

    # ------------------------------------------------------------------
    # 规范要求的其余方法
    # ------------------------------------------------------------------
    def isVideoFormat(self, url):
        u = str(url or '').lower()
        return bool(re.search(r'\.(m3u8|mp4|mkv|flv)(\?|$)', u)) or 'm3u8' in u

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        return None


# ---------------------------------------------------------------------------
# 本地完整测试
# ---------------------------------------------------------------------------
def main():
    sp = Spider()
    sp.init('')
    passed = failed = 0

    def check(name, cond, extra=''):
        nonlocal passed, failed
        if cond:
            passed += 1
            print('  PASS  %s %s' % (name, extra))
        else:
            failed += 1
            print('  FAIL  %s %s' % (name, extra))

    print('=== 0. 方法集 / 类名 ===')
    need = ['getName', 'init', 'isVideoFormat', 'manualVideoCheck', 'action',
            'homeContent', 'homeVideoContent', 'categoryContent',
            'detailContent', 'searchContent', 'playerContent', 'localProxy', 'destroy']
    check('方法齐备', all(hasattr(sp, n) for n in need))
    check('类名为 Spider', type(sp).__name__ == 'Spider')

    print('=== 1. homeContent / homeVideoContent ===')
    h = sp.homeContent({})
    check('分类 3 个', len(h['class']) == 3, [c['type_name'] for c in h['class']])
    hv = sp.homeVideoContent()
    check('首页推荐', len(hv['list']) > 0, '%d 条' % len(hv['list']))

    print('=== 2. categoryContent ===')
    first_ids = []
    for tid in ['1', '3', '4']:
        r = sp.categoryContent(tid, 1, {}, {})
        check('分类 %s 有数据' % tid, len(r['list']) > 0, '%d 条' % len(r['list']))
        if tid == '1':
            first_ids = [v['vod_id'] for v in r['list'][:3]]
    r2 = sp.categoryContent('1', 2, {}, {})
    check('翻页内容不同', r2['list'] and
          [v['vod_id'] for v in r2['list'][:3]] != first_ids,
          'p2=%d 条' % len(r2['list']))
    rs = sp.categoryContent('1', '2', {}, '{"year":"2026","by":"newstime"}')
    check('字符串 pg / 字符串 extend', len(rs['list']) > 0)

    print('=== 3. detailContent ===')
    d = sp.detailContent(['/detail/3752.html'])
    check('详情返回 1 项', len(d['list']) == 1)
    v = d['list'][0] if d['list'] else {}
    pf = v.get('vod_play_from', '').split('$$$') if v.get('vod_play_from') else []
    pu = v.get('vod_play_url', '').split('$$$') if v.get('vod_play_url') else []
    eps = pu[0].split('#') if pu and pu[0] else []
    check('线路数 = $$$ 段数', len(pf) == len(pu) and len(pf) >= 1,
          'from=%d url=%d' % (len(pf), len(pu)))
    check('剧集用 # 连接', len(eps) >= 2, '%d 集, 首集=%s' % (len(eps), eps[:1]))
    check('元数据清洗', bool(v.get('vod_name')) and bool(v.get('vod_actor')),
          '%s / %s / %s' % (v.get('vod_name'), v.get('vod_remarks'), v.get('vod_director')))

    print('=== 4. playerContent（AES 直出 m3u8）===')
    if eps:
        p = sp.playerContent('在线云播', eps[0], None)
        check('parse=0', p['parse'] == 0)
        check('直出 m3u8 直链', '.m3u8' in p['url'] and 'edit-down.php' not in p['url'],
              p['url'][:100])
        check('header 带 Referer', 'Referer' in p.get('header', {}))

    print('=== 5. searchContent（核心）===')
    for k in ['黑暗荣耀', '请回答1988', '医生']:
        r = sp.searchContent(k, False, 1)
        check('搜索「%s」' % k, len(r['list']) > 0,
              '%d 条, 首条=%s' % (len(r['list']),
                                  r['list'][0]['vod_name'] if r['list'] else '-'))
        if r['list']:
            check('  结果带封面', bool(r['list'][0]['vod_pic']))
    r = sp.searchContent('不存在的片子zzz999', False, 1)
    check('无结果返回合法空结构', r['list'] == [] and r['page'] == 1)
    r = sp.searchContent('黑暗荣耀', False, '1')
    check('字符串 pg', len(r['list']) > 0)
    r = sp.searchContent('黑暗荣耀', False, 2)
    check('pg>1 返回空', r['list'] == [])
    check('isVideoFormat 带 query', sp.isVideoFormat('http://a.com/x.m3u8?token=1'))

    print()
    print('========== %d PASS / %d FAIL ==========' % (passed, failed))
    return failed == 0


if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
