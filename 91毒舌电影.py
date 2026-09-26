# -*- coding: utf-8 -*-
# TVBox / 影视仓 / OK影视 Python Spider —— 91毒舌电影 (duse0.com)
# 结构实测：苹果CMS。分类 /channel/N.html；分页 /channel/N-p.html；
# 卡片 a.v-item（封面 data-original、标题 div.v-item-title）；
# 播放页 /play/{id}-{sid}-{nid}.html 内含直链 m3u8。
# 注意：站点前置 cdndefend JS 挑战（设 cookie 后放行），本脚本已内置求解。
import sys, os, re, json, time, hashlib, urllib.parse
try:
    from base.spider import Spider
except Exception:
    class Spider(object):
        def __init__(self):
            self.headers = {}
            self._cookie = ''

        def fetch(self, url, headers=None, data=None, method='GET', allow_redirects=True, **kwargs):
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
            try:
                resp = urllib.request.urlopen(req, timeout=20)
            except urllib.error.HTTPError as e:
                body = e.read()
                resp = e
                resp.read = lambda: body
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


class Spider(Spider):

    def getName(self):
        return '91毒舌电影'

    def log(self, *args):
        print('[91毒舌电影]', *args)

    def init(self, extend=''):
        self.host = 'https://www.duse0.com'
        self._cookie = ''
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': self.host + '/',
        }
        self.categories = {
            '电影': '/channel/1.html', '电视剧': '/channel/2.html', '动漫': '/channel/3.html',
            '综艺': '/channel/4.html', '短剧': '/channel/6.html',
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

    # ---- cdndefend JS 挑战求解：cookie = 常量 + i，使 sha1(常量+i) 的第 n1、n1+1 字节为 0xB0、0x0B ----
    def _solve_challenge(self, html):
        m = re.search(r"'([0-9A-Fa-f]{36,48})'", html)
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

    def _get(self, url):
        """带挑战自动求解的 GET"""
        r = self.fetch(url, headers=self.headers)
        text = r.text or ''
        if 'cdndefend' in text or 'verifying your browser' in text:
            ck = self._solve_challenge(text)
            if ck:
                self._cookie = ck
                self.headers['Cookie'] = ck
                r = self.fetch(url, headers=self.headers)
        return r

    def _extract_list(self, html):
        # <a href="/detail/123.html" class="v-item"> ... data-original="/vod1/..." ... <div class="v-item-title">片名</div>
        items = re.findall(
            r'<a href="(/detail/[0-9]+\.html)" class="v-item">.*?'
            r'data-original="(/vod1/[^"]+)".*?'
            r'<div class="v-item-title">([^<]+)</div>',
            html, re.S)
        out = [(u, pic, name.strip()) for u, pic, name in items]
        if out:
            return out
        return [(u, '', n.strip()) for u, n in re.findall(
            r'<a href="(/detail/[0-9]+\.html)" class="v-item">.*?<div class="v-item-title">([^<]+)</div>',
            html, re.S)]

    def _vod(self, url, pic, name):
        return {'vod_id': url, 'vod_name': (name or '').strip(), 'vod_pic': pic, 'vod_remarks': ''}

    def homeContent(self, filter):
        return {'class': [{'type_name': n, 'type_id': p} for n, p in self.categories.items()], 'filters': {}}

    def homeVideoContent(self):
        try:
            items = self._extract_list(self._get(self.host + '/').text)
            return {'list': [self._vod(*it) for it in items]}
        except Exception as e:
            self.log('home err', e)
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        try:
            m = re.search(r'/channel/(\d+)\.html', tid)
            n = m.group(1) if m else re.sub(r'\D', '', tid) or '1'
            if pg <= 1:
                url = '%s/channel/%s.html' % (self.host, n)
            else:
                url = '%s/channel/%s-%d.html' % (self.host, n, pg)
            html = self._get(url).text
            vids = [self._vod(*it) for it in self._extract_list(html)]
            return {'list': vids, 'page': pg, 'pagecount': 1 if pg == 1 else 0, 'limit': 24, 'total': 999999}
        except Exception as e:
            self.log('category err', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 24, 'total': 0}

    def detailContent(self, ids):
        try:
            url = ids[0]
            if not url.startswith('http'):
                url = self.host + (url if url.startswith('/') else '/' + url)
            html = self._get(url).text
            title = ''
            m = re.search(r'<meta property="og:title" content="([^"]*)"', html) or re.search(r'<title>([^<]*)</title>', html)
            if m:
                title = re.split(r'[\s|｜_\-–]+', m.group(1).strip())[0].strip()
            pic = ''
            m = re.search(r'<meta property="og:image" content="([^"]*)"', html)
            if m:
                pic = m.group(1)
            labels = re.findall(r'class="source-item-label">([^<]+)</span>', html)
            blocks = re.findall(r'<div class="episode-list"[^>]*>(.*?)</div>', html, re.S)
            froms, plays = [], []
            for i, blk in enumerate(blocks):
                eps = re.findall(r'href="(/play/[^"]+)"[^>]*>\s*<span>([^<]+)</span>', blk)
                if not eps:
                    continue
                name = labels[i] if i < len(labels) else '线路%d' % (i + 1)
                froms.append(name if name not in froms else '%s%s' % (name, i))
                plays.append('#'.join('%s$%s' % (t.strip(), self.host + u) for u, t in eps))
            if not froms:
                eps = re.findall(r'href="(/play/[^"]+)"[^>]*>\s*<span>([^<]+)</span>', html)
                if eps:
                    froms = ['91毒舌']
                    plays = ['#'.join('%s$%s' % (t.strip(), self.host + u) for u, t in eps)]
            video = {
                'vod_id': ids[0], 'vod_name': title, 'vod_pic': pic,
                'vod_year': '', 'vod_area': '', 'vod_remarks': '', 'vod_content': '',
                'vod_play_from': '$$$'.join(froms) if froms else '91毒舌',
                'vod_play_url': '$$$'.join(plays) if plays else '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detail err', e)
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        # 站点搜索需带首页 token（t=），非稳定，返回空
        return {'list': [], 'page': 1}

    def playerContent(self, flag, id, vipFlags):
        page = id
        try:
            html = self._get(page).text
            m = re.search(r'https?:[^"\'<>\s\\]*\.m3u8[^"\'<>\s\\]*', html)
            if m:
                return {'parse': 0, 'url': m.group(0), 'header': dict(self.headers)}
        except Exception as e:
            self.log('player err', e)
        return {'parse': 1, 'url': page, 'header': dict(self.headers)}

    def localProxy(self, param):
        return None


def main():
    sp = Spider(); sp.init('')
    r = sp.homeContent({})
    print('分类:', [c['type_name'] for c in r['class']])
    for c in r['class']:
        r2 = sp.categoryContent(c['type_id'], 1, {}, {})
        print('  %s 第1页: %d 项' % (c['type_name'], len(r2['list'])))
    tid = r['class'][0]['type_id']
    p1 = sp.categoryContent(tid, 1, {}, {})
    if p1['list']:
        print('  样例:', p1['list'][0])
    d = sp.detailContent(['/detail/382373.html'])
    v = d['list'][0]
    print('详情:', v['vod_name'], '| 线路:', v['vod_play_from'][:80], '| 段数:', len(v['vod_play_url'].split('$$$')))
    seg0 = v['vod_play_url'].split('$$$')[0].split('#')[0]
    print('首集:', seg0)
    pl = sp.playerContent(v['vod_play_from'], seg0.split('$', 1)[-1], None)
    print('播放:', pl['parse'], str(pl['url'])[:120])


if __name__ == '__main__':
    main()
