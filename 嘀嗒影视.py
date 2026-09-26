# -*- coding: utf-8 -*-
# TVBox / 影视仓 / OK影视 Python Spider —— 嘀嗒影视 (didahd.xyz)
# 结构实测：苹果CMS(mytheme)。分类 /type/N.html；分页 /type/N-p.html；
# 卡片 a.myui-vodlist__thumb；详情剧集 div#playlist* 内 /play/{id}-{sid}-{nid}.html；
# 播放页 encrypt=3（该主题 player.js 不解此级），故回退 parse=1 交给 app 解析
import sys, os, re, json, time, urllib.parse
try:
    from base.spider import Spider
except Exception:
    class Spider(object):
        def __init__(self):
            self.headers = {}

        def fetch(self, url, headers=None, data=None, method='GET', allow_redirects=True, **kwargs):
            import urllib.request, urllib.error, ssl, gzip
            try:
                ssl._create_default_https_context = ssl._create_unverified_context
            except Exception:
                pass
            h = dict(self.headers)
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
        return '嘀嗒影视'

    def log(self, *args):
        print('[嘀嗒影视]', *args)

    def init(self, extend=''):
        self.host = 'https://www.didahd.xyz'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
        }
        self.categories = {
            '电影': '/type/1.html', '电视剧': '/type/2.html', '纪录片': '/type/3.html',
            '动漫': '/type/4.html', '综艺': '/type/5.html',
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

    def _f(self, url):
        """带重试的 GET（站点走 Cloudflare，偶发 TLS 握手超时）"""
        last = None
        for _ in range(3):
            try:
                return self.fetch(url, headers=self.headers)
            except Exception as e:
                last = e
                time.sleep(0.4)
        raise last

    def _extract_list(self, html):
        # <a class="myui-vodlist__thumb lazyload" href="/detail/123.html" title="片名" data-original="封面">
        items = re.findall(
            r'<a[^>]*class="myui-vodlist__thumb[^"]*"[^>]*href="(/detail/[0-9]+\.html)"[^>]*'
            r'title="([^"]+)"[^>]*?data-original="([^"]+)"', html, re.S)
        if not items:
            items = re.findall(
                r'<a[^>]*href="(/detail/[0-9]+\.html)"[^>]*title="([^"]+)"[^>]*?data-original="([^"]+)"', html, re.S)
        return [(u, pic, name.strip()) for u, name, pic in items]

    def _vod(self, url, pic, name):
        return {'vod_id': url, 'vod_name': (name or '').strip(), 'vod_pic': pic, 'vod_remarks': ''}

    def homeContent(self, filter):
        return {'class': [{'type_name': n, 'type_id': p} for n, p in self.categories.items()], 'filters': {}}

    def homeVideoContent(self):
        try:
            items = self._extract_list(self._f(self.host + '/').text)
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
            m = re.search(r'/type/(\d+)\.html', tid)
            n = m.group(1) if m else re.sub(r'\D', '', tid) or '1'
            if pg <= 1:
                url = '%s/type/%s.html' % (self.host, n)
            else:
                url = '%s/type/%s-%d.html' % (self.host, n, pg)
            html = self._f(url).text
            vids = [self._vod(*it) for it in self._extract_list(html)]
            return {'list': vids, 'page': pg, 'pagecount': 9999, 'limit': 24, 'total': 999999}
        except Exception as e:
            self.log('category err', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 24, 'total': 0}

    def detailContent(self, ids):
        try:
            url = ids[0]
            if not url.startswith('http'):
                url = self.host + (url if url.startswith('/') else '/' + url)
            html = self._f(url).text
            title = ''
            m = re.search(r'<meta property="og:title" content="([^"]*)"', html) or re.search(r'<title>([^<]*)</title>', html)
            if m:
                title = re.split(r'[\s|｜_\-–]+', m.group(1).strip())[0].strip()
            pic = ''
            m = re.search(r'<meta property="og:image" content="([^"]*)"', html)
            if m:
                pic = m.group(1)
            # tab 名：<a href="#playlist0" data-toggle="tab">超清G</a>
            tabs = dict(re.findall(r'#playlist(\d+)"[^>]*>\s*([^<]{1,12})', html))
            # 播放块
            blocks = re.findall(
                r'<div id="playlist(\d+)"[^>]*>(.*?)(?=<div id="playlist|<div class="myui-panel|<div class="myui-player|</body>|$)',
                html, re.S)
            froms, plays = [], []
            for idx, content in blocks:
                eps = re.findall(r'href="(/play/[^"]+)"[^>]*>\s*([^<]+?)\s*<', content)
                if not eps:
                    continue
                name = tabs.get(idx, '线路%s' % idx)
                froms.append(name if name not in froms else name + idx)
                plays.append('#'.join('%s$%s' % (t.strip(), self.host + u) for u, t in eps))
            if not froms:
                # 兜底：全文抓 /play/ 锚点
                eps = re.findall(r'href="(/play/[^"]+)"[^>]*>\s*([^<]+?)\s*<', html)
                if eps:
                    froms = ['嘀嗒影视']
                    plays = ['#'.join('%s$%s' % (t.strip(), self.host + u) for u, t in eps)]
            video = {
                'vod_id': ids[0], 'vod_name': title, 'vod_pic': pic,
                'vod_year': '', 'vod_area': '', 'vod_remarks': '', 'vod_content': '',
                'vod_play_from': '$$$'.join(froms) if froms else '嘀嗒影视',
                'vod_play_url': '$$$'.join(plays) if plays else '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detail err', e)
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        try:
            url = '%s/search/-------------.html?wd=%s' % (self.host, urllib.parse.quote(key))
            html = self._f(url).text
            vids = [self._vod(*it) for it in self._extract_list(html)]
            return {'list': vids, 'page': 1}
        except Exception as e:
            self.log('search err', e)
            return {'list': [], 'page': 1}

    def playerContent(self, flag, id, vipFlags):
        page = id
        try:
            html = self._f(page).text
            m = re.search(r'https?:[^"\'<>\s\\]*\.m3u8[^"\'<>\s\\]*', html)
            if m:
                return {'parse': 0, 'url': m.group(0), 'header': dict(self.headers)}
            m = re.search(r'"encrypt":0[^}]*?"url":"([^"]+)"', html)
            if m:
                u = m.group(1).replace('\\/', '/')
                if u.startswith('http'):
                    return {'parse': 0, 'url': u, 'header': dict(self.headers)}
        except Exception as e:
            self.log('player err', e)
        # encrypt=3 无法本地解密，交由 app 内置解析
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
        p2 = sp.categoryContent(tid, 2, {}, {})
        print('  第2页首项:', p2['list'][0]['vod_id'] if p2['list'] else '空')
    d = sp.detailContent(['/detail/2795.html'])
    v = d['list'][0]
    print('详情:', v['vod_name'], '| 线路:', v['vod_play_from'], '| 段数:', len(v['vod_play_url'].split('$$$')))
    seg0 = v['vod_play_url'].split('$$$')[0].split('#')[0]
    print('首集:', seg0)
    pl = sp.playerContent(v['vod_play_from'], seg0.split('$', 1)[-1], None)
    print('播放:', pl['parse'], str(pl['url'])[:100])


if __name__ == '__main__':
    main()
