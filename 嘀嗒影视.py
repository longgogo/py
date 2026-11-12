# -*- coding: utf-8 -*-
"""
嘀嗒影视（www.didahd.xyz）TVBox 蜘蛛源 —— 修复版
按「电影猎手」规范骨架整理，原文件保持不变。

=== 2026-11-12 站点实测 ===
苹果CMS mytheme。首页/分类/分页/搜索/详情/播放页均 200（Cloudflare，偶发
TLS 握手超时，必须重试）。
- 列表卡片 a.myui-vodlist__thumb[href][title][data-original]，实测 48 条/页
- 分类分页 /type/{n}-{pg}.html 有效（第 1、2 页首项不同）
- 搜索 /search/-------------.html?wd={kw}&page={pg} **分页有效**
- 详情按 <div id="playlist{N}"> 分块；tab 名 <a href="#playlist{N}">名</a>；
  /play/{id}-{sid}-{nid}.html 里的 sid 与 tab 序号**不相同**（tab0 超清G → sid=2）
- 播放页 var player_aaaa={...}，在线线路 encrypt=3，url 是 hex→base64→AES 密文；
  网盘线路 url 是明文 https://pan.baidu.com/...
  /static/js/player.js 只解 encrypt 1/2；真正解密在高度混淆且动态密钥的
  artplayer 页（CryptoJS.MD5(timestamp/vidHash)），本地复现脆弱 → 保持 parse:1

=== 修复清单 ===
1. 搜索忽略 pg：app 翻页永远重复第 1 页 → 支持 ?page=N 且空页收敛 pagecount。
2. 封面 URL 含 &amp; 实体未解码 → 图片加载失败。统一 HTML 实体还原。
3. _f() 只重试不校验：523/404 错误页会被当正常 HTML 解析 → 加状态码与错误页
   校验 + 连续失败短路冷却。
4. detailContent 混入「夸克网盘 / 百度网盘」线路，点进去无法播放 → 存在在线
   线路时剔除网盘线路；并强制 $$$ 段数 = 线路数。
5. playerContent 用全文正则抓 m3u8，容易误抓页面无关链接 → 改为 JSONDecoder
   精确解析 player_aaaa，按 encrypt 等级决定 parse:0 / parse:1。
6. 通用加固：_ensure() 防 app 未调 init、属性顺序无关的列表兜底、空列表收敛
   pagecount、extend={"host":...} 换域名、所有方法 try/except、Referer 随播放头。
"""
import sys, os, re, json, time, base64, html as html_mod
import urllib.parse

try:
    from base.spider import Spider
except Exception:
    class Spider:
        def __init__(self):
            self.headers = {}

        def fetch(self, url, headers=None, data=None, method='GET',
                  timeout=8, **kwargs):
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


class Spider(Spider):

    def getName(self):
        return '嘀嗒影视'

    def log(self, *args):
        # 子类自带，绝不调用 base Spider 的 log
        print('[嘀嗒影视]', *args)

    def init(self, extend=''):
        self.host = 'https://www.didahd.xyz'
        ex = self._parse_extend(extend)
        h = ex.get('host') or ex.get('site') or ''
        if isinstance(h, str) and h.strip().startswith('http'):
            self.host = h.strip().rstrip('/')
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        self.categories = {
            '电影': '/type/1.html', '电视剧': '/type/2.html', '纪录片': '/type/3.html',
            '动漫': '/type/4.html', '综艺': '/type/5.html',
        }
        self._fail = 0
        self._blocked_until = 0

    def _ensure(self):
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
        return html_mod.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()

    @staticmethod
    def _bad_page(h):
        if not h:
            return True
        low = h.lower()
        return ('origin is unreachable' in low or 'error 523' in low
                or '页面未找到' in h or '404错误' in h
                or ('cloudflare' in low and 'error' in low and len(h) < 20000))

    def _f(self, url):
        """带重试 + 状态码校验的 GET；错误页绝不当正常 HTML 返回。
        注意：本站走 Cloudflare，TLS 握手超时是常态，网络异常只重试、
        不触发冷却；只有明确拿到 523/5xx/404 错误页才计入失败并短冷却。"""
        self._ensure()
        if self._blocked_until > time.time():
            return ''
        last = None
        for i in range(7):
            try:
                r = self.fetch(url, headers=dict(self.headers))
                st = getattr(r, 'status_code', 200) or 200
                t = getattr(r, 'text', '') or ''
                if st >= 400 or self._bad_page(t):
                    last = 'HTTP %s / bad page' % st
                    self._fail += 1
                    if self._fail >= 3:
                        self._blocked_until = time.time() + 30
                    time.sleep(0.4)
                    continue
                self._fail = 0
                return t
            except Exception as e:
                last = e
                if i < 6:
                    time.sleep(0.4)
        self.log('fetch fail:', last)
        return ''

    # ------------------------------------------------------------------
    # 列表：主正则 + 属性顺序无关的锚点分块兜底
    # ------------------------------------------------------------------
    def _extract_list(self, html):
        out, seen = [], set()
        for m in re.finditer(r'<a\b[^>]*href="(/detail/\d+\.html)"[^>]*>', html, re.I):
            href = m.group(1)
            if href in seen:
                continue
            tag = m.group(0)
            t = re.search(r'title="([^"]+)"', tag, re.I)
            p = re.search(r'data-original="([^"]+)"', tag, re.I)
            if not t or not p:
                seg = html[m.start():m.start() + 800]
                t = t or re.search(r'title="([^"]+)"', seg, re.I)
                p = p or re.search(r'data-original="([^"]+)"', seg, re.I)
            name = self._txt(t.group(1)) if t else ''
            if not name:
                continue
            seen.add(href)
            pic = html_mod.unescape(p.group(1)) if p else ''   # &amp; → &
            out.append((href, pic, name))
        return out

    def _vod(self, url, pic, name):
        return {'vod_id': url, 'vod_name': (name or '').strip(),
                'vod_pic': pic, 'vod_remarks': ''}

    def homeContent(self, filter):
        try:
            self._ensure()
            return {'class': [{'type_name': n, 'type_id': p}
                              for n, p in self.categories.items()], 'filters': {}}
        except Exception as e:
            self.log('homeContent error:', e)
            return {'class': [], 'filters': {}}

    def homeVideoContent(self):
        try:
            self._ensure()
            items = self._extract_list(self._f(self.host + '/'))
            return {'list': [self._vod(*it) for it in items[:24]]}
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
            m = re.search(r'/type/(\d+)\.html', str(tid))
            n = m.group(1) if m else (re.sub(r'\D', '', str(tid)) or '1')
            url = ('%s/type/%s.html' % (self.host, n) if pg <= 1
                   else '%s/type/%s-%d.html' % (self.host, n, pg))
            videos = [self._vod(*it) for it in self._extract_list(self._f(url))]
            # 空列表收敛，避免 app 无限翻页
            return {'list': videos, 'page': pg,
                    'pagecount': 9999 if videos else pg,
                    'limit': max(len(videos), 24),
                    'total': 999999 if videos else 0}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 24, 'total': 0}

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------
    def _parse_plays(self, html):
        """按 <div id="playlist{N}"> 分块，tab 名按 N 对应；返回 (线路名, 剧集)"""
        tabs = {}
        for m in re.finditer(r'<a\b[^>]*href="#playlist(\d+)"[^>]*>(.*?)</a>',
                             html, re.S | re.I):
            tabs[m.group(1)] = self._txt(m.group(2))
        marks = list(re.finditer(r'<div id="playlist(\d+)"[^>]*>', html, re.I))
        names, groups = [], []
        for i, mk in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(html)
            eps = re.findall(r'href="(/play/[^"]+)"[^>]*>\s*([^<]+?)\s*<',
                             html[mk.end():end], re.S)
            if eps:
                names.append(tabs.get(mk.group(1)) or '线路%s' % mk.group(1))
                groups.append(eps)
        if not groups:
            eps = re.findall(r'href="(/play/[^"]+)"[^>]*>\s*([^<]+?)\s*<',
                             html, re.S)
            if eps:
                names, groups = ['嘀嗒影视'], [eps]
        # 存在在线线路时剔除网盘线路（TVBox 无法播放网盘页）
        online = [(n, g) for n, g in zip(names, groups)
                  if not re.search(r'网盘|百度|夸克|阿里|迅雷|pan\.', n, re.I)]
        if online:
            names = [n for n, _ in online]
            groups = [g for _, g in online]
        # 线路名去重
        seen = set()
        uniq_n, uniq_g = [], []
        for n, g in zip(names, groups):
            nn = n
            k = 1
            while nn in seen:
                k += 1
                nn = '%s%d' % (n, k)
            seen.add(nn)
            uniq_n.append(nn)
            uniq_g.append(g)
        return uniq_n, uniq_g

    def detailContent(self, ids):
        try:
            self._ensure()
            if not ids:
                return {'list': []}
            raw = str(ids[0] or '')
            url = raw if raw.startswith('http') else (
                self.host + (raw if raw.startswith('/') else '/' + raw))
            h = self._f(url)
            if not h:
                return {'list': []}
            m = (re.search(r'<meta property="og:title" content="([^"]*)"', h)
                 or re.search(r'<title>([^<]*)</title>', h))
            title = re.split(r'[\s|｜_\-–]+', self._txt(m.group(1)))[0] if m else ''
            pm = re.search(r'<meta property="og:image" content="([^"]*)"', h)
            pic = html_mod.unescape(pm.group(1)) if pm else ''

            names, groups = self._parse_plays(h)
            play_from = '$$$'.join(names) if names else ''
            play_url = '$$$'.join(
                '#'.join('%s$%s' % (self._txt(t),
                                    self.host + u if u.startswith('/') else u)
                         for u, t in eps)
                for eps in groups)
            return {'list': [{
                'vod_id': raw, 'vod_name': title, 'vod_pic': pic,
                'vod_year': '', 'vod_area': '', 'vod_remarks': '', 'vod_content': '',
                'vod_play_from': play_from, 'vod_play_url': play_url,
            }]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        try:
            self._ensure()
            key = str(key or '').strip()
            if not key:
                return {'list': [], 'page': pg, 'pagecount': 1, 'total': 0}
            url = ('%s/search/-------------.html?wd=%s&page=%d'
                   % (self.host, urllib.parse.quote(key), pg))
            videos = [self._vod(*it) for it in self._extract_list(self._f(url))]
            if not videos:
                # Cloudflare 偶发握手失败时再试一次，避免把网络抖动误判为无结果
                videos = [self._vod(*it) for it in self._extract_list(self._f(url))]
            return {'list': videos, 'page': pg,
                    'pagecount': 9999 if videos else pg,
                    'limit': max(len(videos), 24),
                    'total': 999999 if videos else 0}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 24, 'total': 0}

    # ------------------------------------------------------------------
    # 播放：精确解析 player_aaaa，按 encrypt 等级决定策略
    # ------------------------------------------------------------------
    @staticmethod
    def _js_unescape(s):
        s = re.sub(r'%u([0-9a-fA-F]{4})',
                   lambda m: chr(int(m.group(1), 16)), s)
        return urllib.parse.unquote(s)

    @staticmethod
    def _is_video(u):
        return bool(re.search(r'\.(m3u8|mp4|mkv|flv)(\?|$)', u, re.I)) or \
            ('.m3u8' in u.lower() and u.startswith('http'))

    def _player_obj(self, html):
        i = html.find('player_aaaa')
        if i < 0:
            return {}
        j = html.find('=', i)
        if j < 0:
            return {}
        try:
            obj, _ = json.JSONDecoder().raw_decode(html[j + 1:].strip())
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def playerContent(self, flag, id, vipFlags):
        result = {'parse': 1, 'url': str(id or ''),
                  'header': dict(getattr(self, 'headers', {}))}
        try:
            self._ensure()
            page = str(id or '').strip()
            result['url'] = page
            result['header'] = dict(self.headers)
            if not page.startswith('http'):
                return result
            h = self._f(page)
            if not h:
                return result
            obj = self._player_obj(h)
            u = str(obj.get('url') or '')
            enc = str(obj.get('encrypt') or '')
            if enc == '1':
                u = self._js_unescape(u)
            elif enc == '2':
                try:
                    u = self._js_unescape(base64.b64decode(u).decode('utf-8', 'replace'))
                except Exception:
                    u = ''
            # encrypt=3：在线线路是 hex→base64→AES 密文，站点解密脚本为
            # 动态密钥+混淆，本地不复现；网盘线路是明文网页，都不直出。
            if self._is_video(u):
                result['parse'] = 0
                result['url'] = u.replace('\\/', '/')
                return result
            # 兜底：只在 player_aaaa 对象范围内找明文 m3u8，避免误抓全页链接
            seg = json.dumps(obj, ensure_ascii=False)
            mm = re.search(r'https?:[^"\'<>\s\\]*\.m3u8[^"\'<>\s\\]*', seg)
            if mm:
                result['parse'] = 0
                result['url'] = mm.group(0).replace('\\/', '/')
        except Exception as e:
            self.log('playerContent error:', e)
        return result

    def isVideoFormat(self, url):
        return self._is_video(str(url or ''))

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

    print('=== 0. 规范检查 ===')
    need = ['getName', 'init', 'isVideoFormat', 'manualVideoCheck', 'action',
            'homeContent', 'homeVideoContent', 'categoryContent',
            'detailContent', 'searchContent', 'playerContent', 'localProxy', 'destroy']
    check('方法齐备', all(hasattr(sp, n) for n in need))
    check('类名为 Spider', type(sp).__name__ == 'Spider')

    print('=== 1. 首页 / 分类 ===')
    h = sp.homeContent({})
    check('5 个分类', len(h['class']) == 5, [c['type_name'] for c in h['class']])
    hv = sp.homeVideoContent()
    check('首页推荐', len(hv['list']) > 0, '%d 条' % len(hv['list']))
    first = []
    for c in h['class']:
        r = sp.categoryContent(c['type_id'], 1, {}, {})
        check('分类 %s' % c['type_name'], len(r['list']) > 0, '%d 条' % len(r['list']))
        if c['type_name'] == '电影':
            first = [v['vod_id'] for v in r['list'][:3]]
    p2 = sp.categoryContent('1', 2, {}, {})
    check('分类翻页不同', p2['list'] and
          [v['vod_id'] for v in p2['list'][:3]] != first,
          'p2=%d 条' % len(p2['list']))
    ps = sp.categoryContent('1', '2', {}, '{}')
    check('字符串 pg / extend', len(ps['list']) > 0)

    print('=== 2. 搜索（含分页）===')
    s1 = sp.searchContent('爱', False, 1)
    s2 = sp.searchContent('爱', False, 2)
    check('搜索有结果', len(s1['list']) > 0, '%d 条' % len(s1['list']))
    check('搜索翻页不同', len(s2['list']) > 0 and
          [v['vod_id'] for v in s2['list'][:3]] != [v['vod_id'] for v in s1['list'][:3]],
          'p2=%d 条' % len(s2['list']))
    check('字符串 pg', len(sp.searchContent('爱', False, '1')['list']) > 0)
    check('空关键词', sp.searchContent('', False, 1)['list'] == [])
    if s1['list']:
        check('封面实体已还原', '&amp;' not in s1['list'][0]['vod_pic'],
              s1['list'][0]['vod_pic'][:80])

    print('=== 3. 详情 / 线路 ===')
    d = sp.detailContent(['/detail/3843.html'])
    check('详情返回 1 项', len(d['list']) == 1)
    v = d['list'][0] if d['list'] else {}
    pf = v.get('vod_play_from', '').split('$$$') if v.get('vod_play_from') else []
    pu = v.get('vod_play_url', '').split('$$$') if v.get('vod_play_url') else []
    eps = pu[0].split('#') if pu and pu[0] else []
    check('线路数 = $$$ 段数', len(pf) == len(pu) and len(pf) >= 1,
          'from=%d url=%d names=%s' % (len(pf), len(pu), pf[:5]))
    check('网盘线路已剔除', all('网盘' not in n for n in pf))
    check('剧集用 # 连接', len(eps) >= 2, '%d 集' % len(eps))

    print('=== 4. 播放 ===')
    if eps:
        pr = sp.playerContent(pf[0] if pf else '', eps[0].split('$', 1)[-1], None)
        check('返回合法 parse', pr['parse'] in (0, 1), 'parse=%s' % pr['parse'])
        check('url 非空', bool(pr['url']), str(pr['url'])[:100])
        check('header 带 Referer', 'Referer' in pr.get('header', {}))
    check('isVideoFormat 带 query', sp.isVideoFormat('http://a.com/x.m3u8?t=1'))

    print()
    print('========== %d PASS / %d FAIL ==========' % (passed, failed))
    return failed == 0


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
