# -*- coding: utf-8 -*-
# TVBox / 影视仓 / OK影视 Python Spider —— 91毒舌电影 (duse0.com)
#
# ── 2026-09-28 全网实测修复（原始 HTML 抓包逐条核对）──────────────────────────
# 站点：苹果CMS 系自研模板；前置 cdndefend JS 挑战（HTTP 850，脚本已内置求解）。
#
# 【修复 1｜详情页字段全空（原版只认 og 标签，而本站没有 og 标签）】
#   实测 `<meta property="og:title">` / `og:image` 出现次数 = 0 → 原版片名/封面全取不到。
#   真实位置：
#     片名   div.detail-title 内 <strong>（3 个：水印 / 真名 / 水印，挑含中文的那个）
#     封面   div.detail-pic > img[data-original="/vod1/..."]        ← 相对路径
#     简介   div.detail-desc > p                                    （meta description 是截断版）
#     导演   div.detail-info-row：side「导演:」→ main 内 <a> 文本
#     演员   同结构「演员:」，多个 <a> 用「、」连接
#     备注   「备注:」行（如 HD国语）；年份「首映:」行（2026-09-26）
#     年份/地区/类型  a.detail-tags-item（2026 / 中国大陆 / 剧情片）
#
# 【修复 2｜封面是相对路径 /vod1/...，本站域名直连 403】
#   本站图片走多 CDN 域名（前端 rdul.js + JS 测速选优）。rdul.js 实测内容：
#     window.RDUL = ["https://vres.cyscyy.com", "https://vres.enbymae.com",
#                    "https://vres.zyxpedu.com", "https://103.39.111.180:51050",
#                    "https://103.39.111.184:51050"];
#   实测 103.39.111.180:51050 / 103.39.111.184:51050 取图 200 image/jpeg（且不需要 cookie）。
#   本源：运行时抓 rdul.js 刷新候选（失败用内置兜底），逐个验证首个可用者并缓存。
#
# 【修复 3｜搜索原本直接返回空（其实完全可用！）】
#   实测：/search?k={词} 不带 token → 页面「找到 0 部影片」；
#         带任意页面里隐藏的 name="t" token → 「找到 24 部影片」，18 条/页，&page=2 再出 6 条。
#        token 与关键词无关、同一页面重复请求稳定（首页两次都是同一枚）→ 可复用。
#   本源：搜索前先抓首页取 t（隐藏 input name="t"），再 /search?k={wd}&t={t}&page={pg}。
#   搜索结果卡片：a.search-result-item（div.title / div.tags / div.actors / div.desc /
#                 div.search-result-item-header=分类名），卡内无嵌套 <a>。
#
# 【修复 4｜分类页没有真分页】
#   /channel/1-2.html、?page=2、?p=2 与第 1 页交集 37~39/48（真分页应为 0），
#   页面也无「下一页」UI → pagecount 固定 1、pg>1 直接返回空表，TVBox 不会去翻假页。
#
# 【修复 5｜_abs() 拼相对路径丢路径（致命）】
#   原写 `self.host + ('' if u.startswith('/') else '/' + u)` —— 三元里漏了 u，
#   凡是以 '/' 开头的相对路径（详情 /detail/xxx.html、播放 /play/xxx.html）一律被拼成
#   光秃秃的域名，于是详情页抓到的是首页：片名成站名、字段全空、线路只有 1 条。
#   已改 `self.host + (u if u.startswith('/') else '/' + u)`。
#
# 【修复 6｜站点间歇性 RST / 850 挑战 → 统一重试】
#   本站连续请求会偶发 `WinError 10054 远程主机强迫关闭`。_get() 现内置 3 次重试
#   （指数退避），并把「挑战求解后仍为空/异常」也纳入重试，避免搜索/详情偶发空。
#
# 【修复 7｜无封面条目返回站方占位图】
#   站方对无封面影片下发 vf.esadj.com/.../logo_placeholder_vertical.png，已识别并当空处理。
#
# 【播放】/play/{id}-{sid}-{nid}.html 内联 `const playSource = { src: "https://.../index.m3u8?appId=..&sign=.." }`
#   → 明文直链，实测直接 200 且返回真 m3u8（parse=0，无需嗅探）。签名带 timestamp，故取链必须在播放时现抓。
#
# 【已核对无误】列表卡片 a.v-item（封面 data-original、标题 div.v-item-title 无 style 属性的那个；
#   前后各有一个 style="display:none" 的水印同名 div，严格正则天然过滤）；备注 div.v-item-bottom>span；
#   详情页 source-item-label ↔ div.episode-list 数量一一对应（电影 17↔17、剧集 15↔15）。
import sys, os, re, json, time, hashlib, urllib.parse

try:
    from base.spider import Spider
except Exception:
    class Spider(object):
        def __init__(self):
            self.headers = {}
            self._cookie = ''

        def fetch(self, url, headers=None, data=None, method='GET', allow_redirects=True, timeout=20, **kwargs):
            import urllib.request, urllib.error, ssl, gzip
            try:
                ssl._create_default_https_context = ssl._create_unverified_context
            except Exception:
                pass
            h = dict(self.headers)
            if getattr(self, '_cookie', ''):
                h['Cookie'] = self._cookie
            if headers:
                h.update(headers)
            if data is not None and method == 'GET':
                method = 'POST'
            if isinstance(data, str):
                data = data.encode('utf-8')
            req = urllib.request.Request(url, headers=h, method=method)
            if data:
                req.data = data
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 必须清代理
            try:
                resp = op.open(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                resp = e
            body = resp.read() if hasattr(resp, 'read') else b''
            if body[:2] == b'\x1f\x8b':
                body = gzip.decompress(body)

            class R(object):
                pass
            r = R()
            r.text = body.decode('utf-8', 'replace')
            r.content = body
            r.status_code = getattr(resp, 'status', getattr(resp, 'code', 200))
            r.headers = dict(getattr(resp, 'headers', {}) or {})

            def to_json():
                return json.loads(r.text)
            r.json = to_json
            return r


UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1')

# 图片 CDN：rdul.js 实测值，取不到时用这份兜底
IMG_FALLBACK = ['https://vres.cyscyy.com', 'https://vres.enbymae.com', 'https://vres.zyxpedu.com',
                'https://103.39.111.180:51050', 'https://103.39.111.184:51050']
RDUL_URL = 'https://vf.esadj.com/vod_pc_static_ds91/js/rdul.js'

REGIONS = ('中国大陆', '大陆', '中国香港', '香港', '中国台湾', '台湾', '美国', '日本', '韩国', '泰国',
           '英国', '法国', '德国', '意大利', '西班牙', '印度', '俄罗斯', '加拿大', '澳大利亚',
           '新加坡', '马来西亚', '其他')


class Spider(Spider):

    def getName(self):
        return '91毒舌电影'

    def log(self, *args):
        print('[91毒舌电影]', *args)

    def init(self, extend=''):
        self.host = 'https://www.duse0.com'
        self._cookie = ''
        self._token = ''          # 搜索 token（每页都有，可复用）
        self._img_bases = []      # 图片 CDN 候选
        self._img_base = ''       # 已验证可用的图片 CDN
        if isinstance(extend, str) and extend.startswith('http'):
            self.host = extend.rstrip('/')
        self.headers = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': self.host + '/',
        }
        self.categories = {
            '电影': '/channel/1.html',
            '连续剧': '/channel/2.html',
            '动漫': '/channel/3.html',
            '综艺': '/channel/4.html',
            '短剧': '/channel/6.html',
        }

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4)(\?|$)', url or ''))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    def _parse_extend(self, extend):
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend.strip() else {}
            except Exception:
                extend = {}
        return extend if isinstance(extend, dict) else {}

    # ---------------------------------------------------------------- 基础请求
    def _fetch(self, url, headers=None, timeout=20):
        h = dict(self.headers)
        if headers:
            h.update(headers)
        try:
            r = self.fetch(url, headers=h)
            if r is not None and getattr(r, 'text', None) is not None:
                return r
        except Exception as e:
            self.log('宿主 fetch 失败，走本地兜底:', e)
        # 兜底：宿主 fetch 不可用时自己发（必须清代理，否则 502 假阴性）
        import urllib.request, urllib.error, ssl, gzip
        try:
            ssl._create_default_https_context = ssl._create_unverified_context
        except Exception:
            pass
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            resp = op.open(urllib.request.Request(url, headers=h), timeout=timeout)
            code, body, hd = resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            code, body, hd = e.code, e.read(), dict(e.headers or {})
        if body[:2] == b'\x1f\x8b':
            body = gzip.decompress(body)

        class R(object):
            pass
        r = R()
        r.text = body.decode('utf-8', 'replace')
        r.content = body
        r.status_code = code
        r.headers = hd
        return r

    # ---- cdndefend JS 挑战：cookie = 常量 + i，使 sha1(常量+i) 的第 n1、n1+1 字节为 0xB0、0x0B ----
    def _solve_challenge(self, html):
        m = (re.search(r"'([0-9A-Fa-f]{32,64})'", html)
             or re.search(r'"([0-9A-Fa-f]{32,64})"', html))
        if not m:
            return ''
        c = m.group(1)
        try:
            n1 = int(c[0], 16)
        except Exception:
            return ''
        for i in range(3000000):
            d = hashlib.sha1((c + str(i)).encode()).digest()
            if d[n1] == 0xB0 and d[n1 + 1] == 0x0B:
                return 'cdndefend_js_cookie=%s%d' % (c, i)
        return ''

    def _get(self, url, referer=None, tries=3):
        """带挑战自动求解 + 断连重试的 GET（本站连续请求会间歇性 RST）"""
        h = {'Referer': referer} if referer else None

        class _E(object):
            text = ''
            content = b''
            status_code = 0
            headers = {}
        last = _E()
        for i in range(max(1, tries)):
            try:
                r = self._fetch(url, headers=h)
                txt = (r.text or '')
            except Exception as e:
                self.log('get err(%d/%d): %s' % (i + 1, tries, e))
                time.sleep(0.8 + 0.7 * i)
                continue
            if r.status_code == 850 or 'cdndefend' in txt[:5000] or 'verifying your browser' in txt[:5000]:
                ck = self._solve_challenge(txt)
                if ck:
                    self._cookie = ck
                    self.headers['Cookie'] = ck
                    try:
                        r = self._fetch(url, headers=h)
                        txt = (r.text or '')
                    except Exception as e:
                        self.log('get err after challenge: %s', e)
            if txt and (r.status_code < 400 or len(txt) > 2000):
                return r
            last = r
            self.log('get retry(%d/%d): code=%s len=%d %s' % (i + 1, tries, r.status_code, len(txt), url[:60]))
            time.sleep(0.8 + 0.7 * i)
        return last

    # ---------------------------------------------------------------- 图片 CDN
    def _load_img_bases(self):
        bases = []
        try:
            js = self._fetch(RDUL_URL).text or ''
            bases = re.findall(r'https://[a-zA-Z0-9\.\-:]+', js)
            bases = [b for b in bases if 'esadj' not in b]
        except Exception:
            bases = []
        self._img_bases = bases or list(IMG_FALLBACK)
        return self._img_bases

    def _img(self, path):
        """把 /vod1/... 这类相对图片路径挂到可用的图片 CDN 上（结果缓存）"""
        path = (path or '').strip()
        if not path:
            return ''
        if 'logo_placeholder' in path or '/vod_pc_static' in path:
            return ''            # 站方占位图（无封面条目），当无封面处理
        if path.startswith('//'):
            return 'https:' + path
        if path.startswith('http'):
            return path
        if not path.startswith('/'):
            path = '/' + path
        if self._img_base:
            return self._img_base + path
        for b in (self._img_bases or self._load_img_bases()):
            try:
                r = self._fetch(b + path, headers={'Accept': 'image/*'}, timeout=8)
                if getattr(r, 'status_code', 0) == 200 and len(getattr(r, 'content', b'') or b'') > 100:
                    self._img_base = b
                    return b + path
            except Exception:
                continue
        self._img_base = (self._img_bases or IMG_FALLBACK)[0]
        return self._img_base + path

    # ---------------------------------------------------------------- 文本工具
    def _clean(self, s):
        s = re.sub(r'(?is)<[^>]+>', '', s or '')
        for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&quot;', '"'), ('&#39;', "'"),
                     ('&lt;', '<'), ('&gt;', '>'), ('&ldquo;', '“'), ('&rdquo;', '”')):
            s = s.replace(a, b)
        return s.strip()

    def _texts(self, seg):
        """取片段里的文本：优先 <a> 文本（多人名），否则取去标签后的纯文本"""
        a = [self._clean(t) for t in re.findall(r'(?is)<a\b[^>]*>(.*?)</a>', seg)]
        a = [t for t in a if t]
        if a:
            return a
        t = self._clean(seg)
        return [t] if t else []

    def _abs(self, u):
        u = (u or '').strip()
        if not u:
            return ''
        if u.startswith('http'):
            return u
        return self.host + (u if u.startswith('/') else '/' + u)

    # ---------------------------------------------------------------- 列表解析
    def _extract_list(self, html):
        """频道页/首页卡片：a.v-item（封面 data-original、标题无 style 的 div.v-item-title）"""
        out = []
        for m in re.finditer(r'(?is)<a\b([^>]*\bclass="[^"]*\bv-item\b[^"]*"[^>]*)>(.*?)</a>', html):
            tag, blk = m.group(1), m.group(2)
            hm = re.search(r'href="([^"]*?/detail/\d+\.html)"', tag)
            if not hm:
                continue
            vid = hm.group(1)
            # 标题：优先无 style 属性的（有水印同名 div 带 style="display:none"）
            titles = [self._clean(t) for t in
                      re.findall(r'(?is)<div class="v-item-title"(?![^>]*style)[^>]*>(.*?)</div>', blk)]
            titles = [t for t in titles if t and re.search(r'[\u4e00-\u9fffA-Za-z0-9]', t)]
            name = titles[0] if titles else ''
            if not name:  # 兜底：任意 v-item-title，排除广告水印
                for t in re.findall(r'(?is)<div class="v-item-title"[^>]*>(.*?)</div>', blk):
                    t = self._clean(t)
                    if t and not re.search(r'(?i)kekys|\.com|影视', t):
                        name = t
                        break
            # 封面
            pic = ''
            pm = re.search(r'(?is)<img\b[^>]*data-original="([^"]*?/vod1/[^"]*)"', blk)
            if pm:
                pic = self._img(pm.group(1))
            # 备注
            remark = ''
            rm = re.search(r'(?is)<div class="v-item-bottom"[^>]*>\s*<span[^>]*>(.*?)</span>', blk)
            if rm:
                remark = self._clean(rm.group(1))
            if not vid or not name:
                continue
            out.append({'vod_id': vid, 'vod_name': name, 'vod_pic': pic, 'vod_remarks': remark})
        return out

    def _extract_search(self, html):
        """搜索结果卡片：a.search-result-item（自带标题/年份/地区/类别/演员/简介）"""
        out = []
        for m in re.finditer(r'(?is)<a\b[^>]*href="([^"]*?/detail/\d+\.html)"[^>]*class="[^"]*search-result-item[^"]*"[^>]*>(.*?)</a>', html):
            vid, blk = m.group(1), m.group(2)
            nm = re.search(r'(?is)<div class="title">(.*?)</div>', blk)
            name = self._clean(nm.group(1)) if nm else ''
            if not name:
                continue
            pic = ''
            pm = re.search(r'(?is)<img\b[^>]*data-original="([^"]*?/vod1/[^"]*)"', blk)
            if pm:
                pic = self._img(pm.group(1))
            remark = ''
            rm = re.search(r'(?is)<div class="search-result-item-header">\s*<div>(.*?)</div>', blk)
            if rm:
                remark = self._clean(rm.group(1))
            year = area = ''
            tm = re.search(r'(?is)<div class="tags">(.*?)</div>', blk)
            if tm:
                for t in [self._clean(x) for x in re.findall(r'(?is)<span>(.*?)</span>', tm.group(1))]:
                    if re.match(r'^\d{4}$', t) and not year:
                        year = t
                    elif t in REGIONS and not area:
                        area = t
            actor = ''
            am = re.search(r'(?is)<div class="actors">(.*?)</div>', blk)
            if am:
                actor = self._clean(am.group(1))
            desc = ''
            dm = re.search(r'(?is)<div class="desc">(.*?)</div>', blk)
            if dm:
                desc = self._clean(dm.group(1))
            out.append({'vod_id': vid, 'vod_name': name, 'vod_pic': pic, 'vod_remarks': remark,
                        'vod_year': year, 'vod_area': area, 'vod_actor': actor, 'vod_content': desc})
        return out

    # ---------------------------------------------------------------- 接口
    def homeContent(self, filter):
        try:
            classes = [{'type_name': n, 'type_id': p} for n, p in self.categories.items()]
            return {'class': classes, 'filters': {}}
        except Exception as e:
            self.log('homeContent err', e)
            return {'class': [], 'filters': {}}

    def homeVideoContent(self):
        try:
            html = self._get(self.host + '/').text
            self._harvest_token(html)
            return {'list': self._extract_list(html)}
        except Exception as e:
            self.log('home err', e)
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        self._parse_extend(extend)
        try:
            m = re.search(r'/channel/(\d+)\.html', str(tid))
            n = m.group(1) if m else (re.sub(r'\D', '', str(tid)) or '1')
            if pg > 1:
                # 本站分类页无真分页（-2/-3/-10 与第 1 页交集 37~39/48，页面也无「下一页」）
                return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 0, 'total': 0}
            html = self._get('%s/channel/%s.html' % (self.host, n)).text
            vids = self._extract_list(html)
            return {'list': vids, 'page': pg, 'pagecount': 1,
                    'limit': len(vids) or 48, 'total': len(vids)}
        except Exception as e:
            self.log('category err', e)
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 48, 'total': 0}

    # -------------------------------------------------------------- 详情解析
    def _title_of(self, html):
        m = re.search(r'(?is)<div class="detail-title">(.*?)</div>', html)
        if m:
            cands = [self._clean(t) for t in re.findall(r'(?is)<strong[^>]*>(.*?)</strong>', m.group(1))]
            cands = [c for c in cands if c and re.search(r'[\u4e00-\u9fff]', c)]  # 水印无中文
            if cands:
                return cands[0]
        tm = re.search(r'(?is)<title>(.*?)</title>', html)
        if tm:
            return re.split(r'\s*[-–—|｜_]\s*', self._clean(tm.group(1)))[0].strip()
        return ''

    def _info_rows(self, html):
        """详情信息行：side「导演:/演员:/首映:/备注:」→ 值（多人名「、」连接）"""
        rows = {}
        parts = re.split(r'<div class="detail-info-row">', html)[1:]
        for p in parts:
            sm = re.search(r'detail-info-row-side">\s*([^<]{1,12}?)\s*<', p)
            if not sm:
                continue
            label = sm.group(1).strip().rstrip(':：')
            main = p[sm.end():]
            cut = re.search(r'(?is)(<div class="detail-info-row">|<div class="episode-list|<div class="source-list|<div class="detail-reviews)', main)
            if cut:
                main = main[:cut.start()]
            rows[label] = '、'.join(self._texts(main))
        return rows

    def detailContent(self, ids):
        try:
            if isinstance(ids, (list, tuple)):
                vid = ids[0] if ids else ''
            else:
                vid = ids
            url = self._abs(str(vid))
            html = self._get(url).text

            name = self._title_of(html)

            pic = ''
            pm = re.search(r'(?is)<div class="detail-pic">.*?<img\b[^>]*data-original="([^"]+)"', html)
            if not pm:
                pm = re.search(r'(?is)<img\b[^>]*data-original="([^"]*?/vod1/[^"]*)"', html)
            if pm:
                pic = self._img(pm.group(1))

            desc = ''
            dm = re.search(r'(?is)<div class="detail-desc">\s*<p[^>]*>(.*?)</p>', html)
            if dm:
                desc = self._clean(dm.group(1))
            if not desc:
                dm = re.search(r'(?is)<meta\s+name="description"\s+content="([^"]*)"', html)
                if dm:
                    desc = self._clean(dm.group(1))
                    desc = re.sub(r'^%s\s*[:：]\s*' % re.escape(name), '', desc) if name else desc

            rows = self._info_rows(html)
            year = ''
            ym = re.search(r'\d{4}', rows.get('首映', '') or rows.get('上映', '') or '')
            if ym:
                year = ym.group(0)
            area = ''
            vod_type = ''
            tm = re.search(r'(?is)<div class="detail-tags[^"]*">(.*?)</div>', html)
            if tm:
                tags = [self._clean(t) for t in re.findall(r'(?is)<a\b[^>]*class="detail-tags-item"[^>]*>(.*?)</a>', tm.group(1))]
                for t in tags:
                    if not year and re.match(r'^\d{4}$', t):
                        year = t
                    if not area and t in REGIONS:
                        area = t
                    if not vod_type and t and not re.match(r'^\d{4}$', t) and t not in REGIONS:
                        vod_type = t

            # 线路 ↔ 剧集：labels 与 .episode-list 块按文档顺序一一对应（实测 15↔15、17↔17）
            labels = [self._clean(t) for t in re.findall(r'class="source-item-label">([^<]*)</span>', html)]
            blocks = re.findall(r'(?is)<div class="episode-list"[^>]*>(.*?)</div>', html)
            froms, plays = [], []
            for i, blk in enumerate(blocks):
                eps = re.findall(r'href="(/play/[^"]+)"[^>]*>\s*<span>([^<]*)</span>', blk)
                if not eps:
                    continue
                if len(labels) == len(blocks):
                    nm = labels[i]
                else:
                    nm = labels[i] if i < len(labels) else '线路%d' % (i + 1)
                if nm in froms:  # 同名线路加序号区分
                    nm = '%s%d' % (nm, i + 1)
                froms.append(nm or ('线路%d' % (i + 1)))
                plays.append('#'.join('%s$%s' % (self._clean(t) or ('第%d集' % (k + 1)), self._abs(u))
                                      for k, (u, t) in enumerate(eps)))
            if not froms:
                eps = re.findall(r'href="(/play/[^"]+)"[^>]*>\s*<span>([^<]*)</span>', html)
                if eps:
                    froms = ['91毒舌']
                    plays = ['#'.join('%s$%s' % (self._clean(t), self._abs(u)) for u, t in eps)]

            video = {
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic,
                'vod_year': year,
                'vod_area': area,
                'vod_type': vod_type,
                'vod_remarks': rows.get('备注', ''),
                'vod_actor': rows.get('演员', '') or rows.get('主演', ''),
                'vod_director': rows.get('导演', ''),
                'vod_content': desc,
                'vod_play_from': '$$$'.join(froms) if froms else '91毒舌',
                'vod_play_url': '$$$'.join(plays) if plays else '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detail err', e)
            return {'list': []}

    # ---------------------------------------------------------------- 搜索
    def _harvest_token(self, html=''):
        """搜索 token：任意页面里搜索表单的隐藏 input name="t"（同页稳定，可跨关键词复用）"""
        if not html:
            try:
                html = self._get(self.host + '/').text
            except Exception:
                html = ''
        m = (re.search(r'name="t"\s+value="([^"]+)"', html)
             or re.search(r'[?&]t=([A-Za-z0-9+/=%]+)', html))
        if m:
            self._token = m.group(1)
        return self._token

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        for attempt in (0, 1):
            t = self._token or self._harvest_token()
            if not t:
                break
            url = '%s/search?k=%s&t=%s&page=%d' % (
                self.host, urllib.parse.quote(key), urllib.parse.quote(t, safe=''), pg)
            try:
                html = self._get(url, referer=self.host + '/').text
            except Exception as e:
                self.log('search err', e)
                break
            total = re.search(r'找到<span[^>]*>\s*(\d+)\s*</span>', html)
            items = self._extract_search(html)
            if items:
                return {'list': items, 'page': pg}
            if total and total.group(1) != '0':   # 有结果却没解析出来 → 换 token 再试
                self._token = ''
                continue
            if attempt == 0 and (not total):
                self._token = ''                  # 无「找到 N 部」标记，多半是 token 失效
                continue
            break
        return {'list': [], 'page': pg}

    # ---------------------------------------------------------------- 播放
    def playerContent(self, flag, id, vipFlags):
        page = self._abs(str(id))
        try:
            html = self._get(page, referer=self.host + '/').text
            m = (re.search(r'''(?is)src\s*:\s*["'](https?://[^"']+?\.m3u8[^"']*)["']''', html)
                 or re.search(r'''(?is)(https?://[^"'\s<>\\]+?\.m3u8[^"'\s<>\\]*)''', html))
            if not m:
                m = (re.search(r'''(?is)src\s*:\s*["'](https?://[^"']+?\.mp4[^"']*)["']''', html)
                     or re.search(r'''(?is)(https?://[^"'\s<>\\]+?\.mp4[^"'\s<>\\]*)''', html))
            if m:
                u = m.group(1).replace('&amp;', '&').replace('\\/', '/')
                return {'parse': 0, 'url': u, 'header': {'User-Agent': UA, 'Referer': self.host + '/'}}
        except Exception as e:
            self.log('player err', e)
        return {'parse': 1, 'url': page, 'header': {'User-Agent': UA, 'Referer': self.host + '/'}}

    def localProxy(self, param):
        return None


def main():
    sp = Spider()
    sp.init('')
    print('=== homeContent ===')
    r = sp.homeContent({})
    print('分类:', [c['type_name'] for c in r['class']])
    print()
    print('=== homeVideoContent ===')
    hv = sp.homeVideoContent()
    print('首页 %d 部; 例:' % len(hv['list']), hv['list'][0] if hv['list'] else None)
    print()
    print('=== categoryContent ===')
    for c in r['class']:
        rr = sp.categoryContent(c['type_id'], 1, {}, {})
        it = rr['list']
        print('  %-4s %2d 项 | 三字段完整 %d/%d | 例 %s' % (
            c['type_name'], len(it),
            sum(1 for v in it if v['vod_id'] and v['vod_name'] and v['vod_pic']), len(it),
            (it[0]['vod_name'], it[0]['vod_remarks']) if it else None))
    print()
    print('=== detailContent（电影 / 剧集）===')
    for vid in ['/detail/382388.html', '/detail/382702.html']:
        d = sp.detailContent([vid])
        if not d['list']:
            print('  %s -> 空!' % vid)
            continue
        v = d['list'][0]
        plays = v['vod_play_url'].split('$$$')
        print('  %s | 片名:%s' % (vid, v['vod_name']))
        print('     封面:%s' % v['vod_pic'])
        print('     年份:%s 地区:%s 备注:%s' % (v['vod_year'], v['vod_area'], v['vod_remarks']))
        print('     导演:%s' % v['vod_director'])
        print('     演员:%s' % v['vod_actor'][:60])
        print('     简介:%s...(%d字)' % (v['vod_content'][:40], len(v['vod_content'])))
        print('     线路数:%d 组数:%d 首线路:%s 集数:%d' % (
            len(v['vod_play_from'].split('$$$')), len(plays),
            v['vod_play_from'].split('$$$')[0], len(plays[0].split('#'))))
        print('     首集地址:%s' % plays[0].split('#')[0])
    print()
    print('=== playerContent ===')
    d = sp.detailContent(['/detail/382388.html'])
    v = d['list'][0]
    first = v['vod_play_url'].split('$$$')[0].split('#')[0].split('$', 1)[1]
    pl = sp.playerContent(v['vod_play_from'], first, None)
    print('  parse=%s url=%s' % (pl['parse'], pl['url'][:120]))
    print()
    print('=== searchContent ===')
    for kw in ['暴徒', '长生契']:
        s = sp.searchContent(kw, False, 1)
        print('  搜「%s」: %d 条 | 例: %s' % (kw, len(s['list']), s['list'][0] if s['list'] else None))
    s2 = sp.searchContent('暴徒', False, 2)
    print('  第2页: %d 条' % len(s2['list']))


if __name__ == '__main__':
    main()
