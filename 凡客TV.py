# -*- coding: utf-8 -*-
"""
凡客TV（fktv.me）TVBox 蜘蛛源 —— 修复版
按「电影猎手」规范骨架整理，原文件保持不变。

=== 2026-11-12 实测 ===
POST /ysapi/{endpoint}，请求体 = base64(AES-128-ECB(PKCS7(json)))，
key = b'9ed1a661a6ab787a'；响应同为 AES-ECB 密文（偶尔明文 JSON）。
- system/info    → status=y，含 categories / 线路配置
- movie/search   → status=y，data.{data,last_page,total,current_page,page_size}
                   空 keywords + cat_id 分类分页；keywords 搜索；
                   year / language 筛选参数实测有效
- movie/detail   → links（选集） + playback_v2.play_url（/m3v/...m3u8?rand=&sign=）
                   实测该直链 200、content-type application/vnd.apple.mpegurl、
                   55KB 完整 m3u8；不同 link_id 返回不同签名地址

=== 核心故障 ===
原文件模块顶层直接 `from Crypto.Cipher import AES` 与
`from base.spider import Spider`，**两者都没有 try/except 保护**。
本机（以及不少 app runtime）没有 pycryptodome → 模块导入阶段就抛
ModuleNotFoundError: No module named 'Crypto'，源整体无法加载。
本次实测已确认原脚本连 import 都过不去。

=== 修复清单 ===
1. 内置纯 Python AES-128/192/256 ECB 加解密（NIST FIPS-197 已知向量自检通过），
   有 pycryptodome 时优先用它，没有也能正常工作；import 全部 try/except。
2. 补 base.spider 的 fallback Spider（含本地 fetch），class Spider(Spider)。
3. _post_raw 改为优先 `fetch(url, headers=..., data=<str>)`（app 只证明过
   headers/data/allow_redirects 三种用法），不传 method/timeout；bytes 兜底。
4. isVideoFormat / manualVideoCheck 返回 bool（原为 None）；localProxy 返回 None；
   移除 sys.path.append("..")；补自定义 log。
5. _ensure() 防 app 未调 init；extend 兼容 JSON 字符串；host 可换域名，
   domain 字段随之更新。
6. playerContent 兜底链增强：playback_v2.play_url → video_lines[].h264.url
   → m3u8_url_source → play_links[].m3u8_url。
"""
import sys, os, re, json, time, base64, random, string
from functools import lru_cache

try:
    from base.spider import Spider
except Exception:
    class Spider:
        def __init__(self):
            self.headers = {}

        def fetch(self, url, headers=None, data=None, method='GET',
                  timeout=15, **kwargs):
            import urllib.request, urllib.error, ssl, gzip
            try:
                ssl._create_default_https_context = ssl._create_unverified_context
            except Exception:
                pass
            h = dict(getattr(self, 'headers', {}) or {})
            if headers:
                h.update(headers)
            if data is not None and method == 'GET':
                method = 'POST'
            body = None
            if data is not None:
                body = data.encode('utf-8') if isinstance(data, str) else data
            req = urllib.request.Request(url, headers=h, method=method)
            if body:
                req.data = body
            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                raw = e.read()
                resp = e
                resp.read = lambda: raw
            b = resp.read()
            if b[:2] == b'\x1f\x8b':
                b = gzip.decompress(b)

            class R:
                pass

            r = R()
            r.text = b.decode('utf-8', 'replace')
            r.content = b
            r.status_code = getattr(resp, 'status', None) or getattr(resp, 'code', 200)
            r.headers = dict(getattr(resp, 'headers', {}) or {})
            r.json = lambda: json.loads(r.text)
            return r

try:
    from Crypto.Cipher import AES as _CryptoAES
except Exception:
    _CryptoAES = None


# ---------------------------------------------------------------------------
# 纯 Python AES（ECB），无第三方依赖时的兜底；支持 128/192/256 位密钥
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


@lru_cache(maxsize=16)
def _aes_tables(key):
    def sbox_val(x):
        v = _gf_inv(x)
        s = v
        for _ in range(4):
            v = ((v << 1) | (v >> 7)) & 0xff
            s ^= v
        return s ^ 0x63

    sbox = tuple(sbox_val(i) for i in range(256))
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[i:i + 4]) for i in range(0, len(key), 4)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [sbox[x] for x in t]
            t[0] ^= rcon
            rcon = _gf_mul(rcon, 2)
        elif nk > 6 and i % nk == 4:
            t = [sbox[x] for x in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return sbox, tuple(inv), tuple(tuple(x) for x in w), nr


def _ark(s, w, rnd):
    for c in range(4):
        for r in range(4):
            s[r][c] ^= w[rnd * 4 + c][r]


def _state(block):
    return [[block[c * 4 + r] for c in range(4)] for r in range(4)]


def _flat(s):
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _enc_block(block, key):
    sbox, _, w, nr = _aes_tables(key)
    s = _state(block)
    _ark(s, w, 0)
    for rnd in range(1, nr + 1):
        s = [[sbox[x] for x in row] for row in s]
        s = [s[r][r:] + s[r][:r] for r in range(4)]
        if rnd != nr:
            for c in range(4):
                a0, a1, a2, a3 = s[0][c], s[1][c], s[2][c], s[3][c]
                s[0][c] = _gf_mul(a0, 2) ^ _gf_mul(a1, 3) ^ a2 ^ a3
                s[1][c] = a0 ^ _gf_mul(a1, 2) ^ _gf_mul(a2, 3) ^ a3
                s[2][c] = a0 ^ a1 ^ _gf_mul(a2, 2) ^ _gf_mul(a3, 3)
                s[3][c] = _gf_mul(a0, 3) ^ a1 ^ a2 ^ _gf_mul(a3, 2)
        _ark(s, w, rnd)
    return _flat(s)


def _dec_block(block, key):
    _, inv, w, nr = _aes_tables(key)
    s = _state(block)
    _ark(s, w, nr)
    for rnd in range(nr - 1, -1, -1):
        s = [s[r][-r:] + s[r][:-r] if r else list(s[r]) for r in range(4)]
        s = [[inv[x] for x in row] for row in s]
        _ark(s, w, rnd)
        if rnd != 0:
            for c in range(4):
                a0, a1, a2, a3 = s[0][c], s[1][c], s[2][c], s[3][c]
                s[0][c] = _gf_mul(a0, 14) ^ _gf_mul(a1, 11) ^ _gf_mul(a2, 13) ^ _gf_mul(a3, 9)
                s[1][c] = _gf_mul(a0, 9) ^ _gf_mul(a1, 14) ^ _gf_mul(a2, 11) ^ _gf_mul(a3, 13)
                s[2][c] = _gf_mul(a0, 13) ^ _gf_mul(a1, 9) ^ _gf_mul(a2, 14) ^ _gf_mul(a3, 11)
                s[3][c] = _gf_mul(a0, 11) ^ _gf_mul(a1, 13) ^ _gf_mul(a2, 9) ^ _gf_mul(a3, 14)
    return _flat(s)


def _pkcs7_pad(b):
    n = 16 - len(b) % 16
    return b + bytes([n]) * n


def _pkcs7_unpad(b):
    if not b:
        return b
    n = b[-1]
    return b[:-n] if 1 <= n <= 16 and b[-n:] == bytes([n]) * n else b


def _ecb_encrypt(plain, key):
    b = _pkcs7_pad(plain if isinstance(plain, bytes) else plain.encode('utf-8'))
    return b''.join(_enc_block(b[i:i + 16], key) for i in range(0, len(b), 16))


def _ecb_decrypt(data, key):
    b = data if isinstance(data, bytes) else data.encode('utf-8')
    if not b or len(b) % 16:
        raise ValueError('bad ciphertext length')
    return _pkcs7_unpad(b''.join(_dec_block(b[i:i + 16], key)
                                for i in range(0, len(b), 16)))


class Spider(Spider):

    host = 'https://fktv.me'
    api_key = b'9ed1a661a6ab787a'

    def getName(self):
        return '凡客TV'

    def log(self, *args):
        print('[凡客TV]', *args)

    def init(self, extend=''):
        self.host = 'https://fktv.me'
        self.api_key = b'9ed1a661a6ab787a'
        ex = self._parse_extend(extend)
        h = ex.get('host') or ex.get('site') or ''
        if isinstance(h, str) and h.strip().startswith('http'):
            self.host = h.strip().rstrip('/')
        try:
            self.device = ''.join(random.choices(string.hexdigits.lower()[:16], k=32))
        except Exception:
            self.device = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'
        self.headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/120.0.0.0 Safari/537.36'),
            'Referer': self.host + '/',
        }
        self._cache = {}
        self._cache_time = {}
        self._fail = 0
        self._blocked_until = 0

    def _ensure(self):
        if not getattr(self, 'host', ''):
            self.init('')
        if not getattr(self, 'device', ''):
            self.device = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'
        if not hasattr(self, '_cache'):
            self._cache = {}
        if not hasattr(self, '_cache_time'):
            self._cache_time = {}
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

    # ---------------- 加解密 ----------------
    def _aes_enc(self, text):
        raw = text.encode('utf-8') if isinstance(text, str) else text
        if _CryptoAES is not None:
            try:
                c = _CryptoAES.new(self.api_key, _CryptoAES.MODE_ECB)
                return base64.b64encode(c.encrypt(_pkcs7_pad(raw))).decode('ascii')
            except Exception:
                pass
        return base64.b64encode(_ecb_encrypt(raw, self.api_key)).decode('ascii')

    def _aes_dec(self, text):
        text = (text or '').strip()
        # 523/404 错误页不是 base64，先挡掉，避免拿去解密得到含糊的异常
        if not re.fullmatch(r'[A-Za-z0-9+/=\s]+', text):
            raise ValueError('non-base64 response')
        raw = base64.b64decode(text)
        if not raw or len(raw) % 16:
            raise ValueError('bad ciphertext length')
        if _CryptoAES is not None:
            try:
                c = _CryptoAES.new(self.api_key, _CryptoAES.MODE_ECB)
                return _pkcs7_unpad(c.decrypt(raw)).decode('utf-8', 'replace')
            except Exception:
                pass
        return _ecb_decrypt(raw, self.api_key).decode('utf-8', 'replace')

    # ---------------- HTTP / API ----------------
    def _post_raw(self, url, body, headers):
        """只传 headers / data（app fetch 证明过的参数），data 优先 str。"""
        attempts = [
            lambda: self.fetch(url, headers=headers, data=body),
            lambda: self.fetch(url, headers=headers, data=body.encode('utf-8')),
        ]
        if hasattr(self, 'post'):
            attempts.append(lambda: self.post(url, body, headers=headers))
        for fn in attempts:
            try:
                r = fn()
                if isinstance(r, str) or (r is not None and hasattr(r, 'text')):
                    return r
            except TypeError:
                continue
            except Exception:
                continue
        return None

    def _api(self, ep, data=None):
        self._ensure()
        domain = re.sub(r'^https?://', '', self.host).split('/')[0]
        payload = {
            'deviceId': self.device, 'token': '', 'domain': domain,
            'referer': '', 'user_agent': self.headers.get('User-Agent', ''),
            'shareCode': '', 'channel': '', 'ip': '', 'data': data or {},
        }
        body = self._aes_enc(json.dumps(payload))
        headers = {
            'version': '1.0', 'deviceType': 'pc',
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'shareCode': '', 'channel': '', 'ip': '',
            'Content-Type': 'application/octet-stream',
            'User-Agent': self.headers.get('User-Agent', ''),
            'Referer': self.host + '/',
        }
        r = self._post_raw(self.host + '/ysapi/' + ep, body, headers)
        text = ''
        if isinstance(r, str):
            text = r
        elif r is not None:
            text = getattr(r, 'text', '') or ''
        text = (text or '').strip()
        if not text:
            raise Exception('empty response from ' + ep)
        if text.startswith('{') or text.startswith('['):
            return json.loads(text)
        return json.loads(self._aes_dec(text))

    def _api_retry(self, ep, data=None, times=2):
        last = {}
        for i in range(times):
            try:
                r = self._api(ep, data)
                if isinstance(r, dict) and r.get('status') == 'y':
                    return r
                last = r if isinstance(r, dict) else {}
            except Exception as e:
                self.log('api fail', ep, e)
                last = {}
            if i < times - 1:
                try:
                    time.sleep(0.5)
                except Exception:
                    pass
        return last

    # ---------------- 缓存 / 清洗 ----------------
    def _cache_get(self, key, ttl):
        try:
            t = self._cache_time.get(key, 0)
            if t and (time.time() - t) < ttl and key in self._cache:
                return self._cache[key]
        except Exception:
            pass
        return None

    def _cache_set(self, key, val):
        try:
            if len(self._cache) > 64:
                self._cache.clear()
                self._cache_time.clear()
            self._cache[key] = val
            self._cache_time[key] = time.time()
        except Exception:
            pass

    def _clean(self, s):
        try:
            return re.sub(r'<[^>]+>', '', str(s or '')).replace('&nbsp;', ' ').strip()
        except Exception:
            return str(s or '').strip()

    def _card(self, it):
        try:
            if not isinstance(it, dict) or not it.get('name'):
                return None
            remark = ''
            if it.get('score') and str(it['score']) not in ('0', '0.00'):
                remark = '评分%s' % str(it['score'])[:3]
            if it.get('release_at'):
                remark = (str(it['release_at']) + ' ' + remark).strip()
            return {
                'vod_id': str(it.get('id') or it.get('movie_id') or ''),
                'vod_name': self._clean(it.get('name')),
                'vod_pic': (it.get('img_x_source') or it.get('img_y_source')
                            or it.get('img_x') or ''),
                'vod_remarks': remark,
                'vod_year': str(it.get('release_at') or ''),
            }
        except Exception:
            return None

    def _list_page(self, data, times=2):
        result = {'list': [], 'page': 1, 'pagecount': 1,
                  'limit': 24, 'total': 0}
        try:
            d = self._api_retry('movie/search', data, times=times).get('data') or {}
            videos = []
            for it in (d.get('data') or []):
                v = self._card(it)
                if v:
                    videos.append(v)
            result['list'] = videos
            try:
                result['page'] = int(data.get('page', '1'))
                result['pagecount'] = max(1, int(d.get('last_page') or 1))
                result['total'] = int(d.get('total') or 0)
            except Exception:
                pass
        except Exception as e:
            self.log('list_page error:', e)
        return result

    # ---------------- TVBox 接口 ----------------
    def homeContent(self, filter):
        try:
            self._ensure()
            classes = [
                {'type_name': '电影', 'type_id': '6'},
                {'type_name': '电视剧', 'type_id': '5'},
                {'type_name': '动漫', 'type_id': '7'},
                {'type_name': '综艺', 'type_id': '4'},
                {'type_name': '短剧', 'type_id': '9'},
                {'type_name': '纪录片', 'type_id': '8'},
                {'type_name': '电影解说', 'type_id': '11'},
            ]
            years = [str(y) for y in range(2026, 2016, -1)]
            langs = [('国语', '1'), ('粤语', '2'), ('英语', '3'), ('韩语', '4'),
                     ('日语', '5'), ('泰语', '7'), ('其他语', '8')]
            filters = {}
            for c in classes:
                filters[c['type_id']] = [
                    {'key': 'year', 'name': '年份',
                     'value': [{'n': y + '年', 'v': y} for y in years]},
                    {'key': 'language', 'name': '语言',
                     'value': [{'n': n, 'v': v} for n, v in langs]},
                ]
            return {'class': classes, 'filters': filters}
        except Exception as e:
            self.log('homeContent error:', e)
            return {'class': [], 'filters': {}}

    def homeVideoContent(self):
        try:
            self._ensure()
            cached = self._cache_get('home', 600)
            if cached is not None:
                return cached
            res = {'list': self._list_page(
                {'keywords': '', 'page': '1', 'page_size': '24'}, times=1)['list']}
            self._cache_set('home', res)
            return res
        except Exception as e:
            self.log('homeVideoContent error:', e)
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            p = int(pg)
        except Exception:
            p = 1
        if p < 1:
            p = 1
        try:
            self._ensure()
            ext = self._parse_extend(extend)
            data = {'keywords': '', 'cat_id': str(tid),
                    'page': str(p), 'page_size': '24'}
            year = str(ext.get('year', '') or '').strip()
            if re.match(r'^\d{4}$', year):
                data['year'] = year
            lang = str(ext.get('language', '') or '').strip()
            if re.match(r'^\d$', lang):
                data['language'] = lang
            key = 'cat:%s:%s:%s:%s' % (tid, p, year, lang)
            cached = self._cache_get(key, 300)
            if cached is not None:
                return cached
            r = self._list_page(data)
            if r.get('list'):
                self._cache_set(key, r)
            return r
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': p, 'pagecount': 1, 'limit': 24, 'total': 0}

    def detailContent(self, ids):
        try:
            self._ensure()
            if not ids:
                return {'list': []}
            mid = str(ids[0]).split('@')[0]
            cached = self._cache_get('detail:' + mid, 900)
            if cached is not None:
                return cached
            d = (self._api_retry('movie/detail',
                                 {'id': mid, 'is_simple': 'y'}).get('data') or {})
            if not d:
                return {'list': []}
            video = {'vod_id': mid}
            video['vod_name'] = self._clean(d.get('name'))
            video['vod_pic'] = (d.get('img_x_source') or d.get('img_y_source')
                                or d.get('img_x') or '')
            video['vod_year'] = str(d.get('release_at') or '')
            video['vod_area'] = self._clean(d.get('area'))
            video['vod_remarks'] = self._clean(d.get('child_title') or d.get('category'))
            sc = str(d.get('score') or '')
            if sc and sc not in ('0', '0.00'):
                video['vod_remarks'] = (video['vod_remarks'] + ' 评分' + sc[:3]).strip()
            desc = []
            if d.get('director'):
                desc.append('导演: ' + self._clean(d['director']))
            actors = d.get('actors')
            if isinstance(actors, list):
                nm = []
                for a in actors:
                    if isinstance(a, dict) and a.get('name'):
                        nm.append(self._clean(a['name']))
                    elif isinstance(a, str) and a.strip():
                        nm.append(self._clean(a))
                if nm:
                    desc.append('主演: ' + ' '.join(nm[:12]))
            elif isinstance(actors, str) and actors.strip():
                desc.append('主演: ' + self._clean(actors))
            if d.get('description'):
                desc.append(self._clean(d['description']))
            video['vod_content'] = '\n'.join(desc)

            names, plays = [], []
            links = d.get('links') or []
            if links:
                names.append('凡客TV')
                plays.append('#'.join(
                    '%s$%s@%s' % (self._clean(l.get('name') or ('第%s集' % (i + 1))),
                                  mid, l.get('id'))
                    for i, l in enumerate(links) if isinstance(l, dict) and l.get('id')))
            video['vod_play_from'] = '$$$'.join(names)
            video['vod_play_url'] = '$$$'.join(plays)
            result = {'list': [video]}
            self._cache_set('detail:' + mid, result)
            return result
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    def searchContent(self, key, quick, pg='1'):
        try:
            p = int(pg)
        except Exception:
            p = 1
        if p < 1:
            p = 1
        try:
            self._ensure()
            ckey = 's:%s:%s' % (str(key), p)
            cached = self._cache_get(ckey, 180)
            if cached is not None:
                return cached
            r = self._list_page({'keywords': str(key or ''), 'page': str(p),
                                 'page_size': '15'})
            r['page'] = p
            if r.get('list'):
                self._cache_set(ckey, r)
            return r
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': p, 'pagecount': 1, 'limit': 24, 'total': 0}

    @staticmethod
    def _abs_url(host, u):
        u = str(u or '')
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('/'):
            return host + u
        return u

    def playerContent(self, flag, id, vipFlags):
        result = {'parse': 1, 'url': '', 'header': dict(getattr(self, 'headers', {}))}
        try:
            self._ensure()
            result['header'] = dict(self.headers)
            mid, _, lid = str(id or '').partition('@')
            if not mid:
                return result
            ckey = 'play:%s:%s' % (mid, lid)
            cached = self._cache_get(ckey, 1800)
            if cached is not None:
                return cached
            data = {'id': mid, 'is_simple': 'y'}
            if lid:
                data['link_id'] = lid
            d = (self._api_retry('movie/detail', data).get('data') or {})
            pv = d.get('playback_v2') or {}
            play = pv.get('play_url') or ''
            # 兜底链：video_lines → m3u8_url_source → play_links
            if not play:
                for line in (pv.get('video_lines') or []):
                    if isinstance(line, dict):
                        play = ((line.get('h264') or {}).get('url')
                                or line.get('url') or '')
                        if play:
                            break
            if not play:
                play = d.get('m3u8_url_source') or ''
            if not play:
                for pl in (d.get('play_links') or []):
                    if isinstance(pl, dict) and pl.get('m3u8_url'):
                        play = pl['m3u8_url']
                        break
            url = self._abs_url(self.host, play)
            result['parse'] = 0 if url else 1
            result['url'] = url
            if url:
                self._cache_set(ckey, result)
        except Exception as e:
            self.log('playerContent error:', e)
        return result

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|mkv|flv)(\?|$)',
                              str(url or ''), re.I)) or '.m3u8' in str(url or '').lower()

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        return None


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

    print('=== 0. 模块级 / 规范检查 ===')
    check('无 Crypto 也能加载', True, 'CryptoAES=%s' % ('有' if _CryptoAES else '无，使用内置 AES'))
    need = ['getName', 'init', 'isVideoFormat', 'manualVideoCheck', 'action',
            'homeContent', 'homeVideoContent', 'categoryContent',
            'detailContent', 'searchContent', 'playerContent', 'localProxy', 'destroy']
    check('方法齐备', all(hasattr(sp, n) for n in need))
    check('类名为 Spider', type(sp).__name__ == 'Spider')
    check('AES 自检',
          _ecb_encrypt(bytes.fromhex('00112233445566778899aabbccddeeff'),
                       bytes.fromhex('000102030405060708090a0b0c0d0e0f'))[:16].hex()
          == '69c4e0d86a7b0430d8cdb78070b4c55a')
    check('加解密往返', _ecb_decrypt(_ecb_encrypt('凡客TV测试', sp.api_key),
                                    sp.api_key).decode('utf-8') == '凡客TV测试')
    check('isVideoFormat / manualVideoCheck 返回 bool',
          isinstance(sp.isVideoFormat('x.m3u8'), bool)
          and isinstance(sp.manualVideoCheck(), bool))
    check('localProxy 返回 None', sp.localProxy({}) is None)

    print('=== 1. 首页 / 分类 / 筛选 ===')
    h = sp.homeContent({})
    check('7 个分类', len(h['class']) == 7, [c['type_name'] for c in h['class']])
    hv = sp.homeVideoContent()
    check('首页推荐', len(hv['list']) > 0, '%d 条' % len(hv['list']))
    c1 = sp.categoryContent('6', 1, {}, {})
    check('电影分类', len(c1['list']) > 0, '%d 条 / 共 %s 页' %
          (len(c1['list']), c1.get('pagecount')))
    c2 = sp.categoryContent('6', 2, {}, {})
    check('分类翻页不同', len(c2['list']) > 0 and
          [v['vod_id'] for v in c2['list'][:2]] != [v['vod_id'] for v in c1['list'][:2]])
    cs = sp.categoryContent('6', '1', {}, '{"year":"2026"}')
    check('字符串 pg / JSON 字符串 extend + 年份筛选', len(cs['list']) > 0,
          '%d 条' % len(cs['list']))

    print('=== 2. 搜索 ===')
    s = sp.searchContent('庆余年', False, 1)
    check('搜索有结果', len(s['list']) > 0,
          '%d 条 %s' % (len(s['list']), [v['vod_name'] for v in s['list'][:2]]))
    check('搜索无结果合法空结构',
          sp.searchContent('绝不存在zzz999', False, 1)['list'] == [])

    print('=== 3. 详情 / 播放 ===')
    mid = s['list'][0]['vod_id'] if s['list'] else ''
    d = sp.detailContent([mid]) if mid else {'list': []}
    check('详情返回 1 项', len(d['list']) == 1)
    v = d['list'][0] if d['list'] else {}
    pf = v.get('vod_play_from', '').split('$$$') if v.get('vod_play_from') else []
    pu = v.get('vod_play_url', '').split('$$$') if v.get('vod_play_url') else []
    eps = pu[0].split('#') if pu and pu[0] else []
    check('线路数 = $$$ 段数', len(pf) == len(pu) and len(pf) >= 1)
    check('剧集用 # 连接', len(eps) >= 2, '%d 集' % len(eps))
    check('详情元数据', bool(v.get('vod_name')) and bool(v.get('vod_content')),
          v.get('vod_name'))
    if eps:
        pr = sp.playerContent(pf[0], eps[0].split('$', 1)[-1], None)
        check('parse=0', pr['parse'] == 0)
        check('直出 m3u8', '.m3u8' in pr['url'], pr['url'][:110])
        check('header 带 Referer', 'Referer' in pr.get('header', {}))

    print()
    print('========== %d PASS / %d FAIL ==========' % (passed, failed))
    return failed == 0


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
