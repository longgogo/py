# -*- coding: utf-8 -*-
# TVBox / 影视仓 / OK影视 Python Spider —— 电影人生 (dyrs360.cc)
# 结构实测：wzzycc/douhua 主题，与 dhvideo 同后端 box.dyrs.com.de（无 g 分组参数）
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
        return '电影人生'

    def log(self, *args):
        print('[电影人生]', *args)

    def init(self, extend=''):
        self.host = 'https://dyrs360.cc'
        self.box = 'https://box.dyrs.com.de'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
        }
        self.categories = {
            '电影': '/dianying.html', '电视剧': '/dianshiju.html',
            '动漫': '/dongman.html', '综艺': '/zongyi.html', '短剧': '/duanju.html',
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

    def _extract_list(self, html):
        # 卡片：<a href="/movie/ID-NUM.html" class="block w-full aspect-[2/3]..." title="片名" ...><img data-src="封面">
        items = re.findall(
            r'<a href="(/(?:movie|tv)/[0-9a-f]{24}-[0-9]+\.html)" class="block w-full aspect[^"]*"[^>]*?'
            r'title="([^"]+)"[^>]*?>\s*<img[^>]*?data-src="([^"]+)"', html, re.S)
        out = [(u, pic, name.strip()) for u, name, pic in items]
        if out:
            return out
        out, seen = [], set()
        for m in re.finditer(r'<a href="(/(?:movie|tv)/[0-9a-f]{24}-[0-9]+\.html)"[^>]*?title="([^"]+)"', html):
            u, name = m.group(1), m.group(2)
            if u in seen:
                continue
            seen.add(u)
            out.append((u, '', name.strip()))
        return out

    def homeContent(self, filter):
        return {'class': [{'type_name': n, 'type_id': p} for n, p in self.categories.items()], 'filters': {}}

    def homeVideoContent(self):
        try:
            items = self._extract_list(self.fetch(self.host + '/', headers=self.headers).text)
            return {'list': [self._vod(*it) for it in items]}
        except Exception as e:
            self.log('home err', e)
            return {'list': []}

    def _vod(self, url, pic, name):
        return {'vod_id': url, 'vod_name': (name or '').strip(), 'vod_pic': pic, 'vod_remarks': ''}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        try:
            path = tid if tid.startswith('/') else '/' + tid
            url = self.host + path
            if pg > 1:
                url = '%s?page=%d' % (url, pg)
            html = self.fetch(url, headers=self.headers).text
            vids = [self._vod(*it) for it in self._extract_list(html)]
            return {'list': vids, 'page': pg, 'pagecount': 1 if pg == 1 else 0, 'limit': 30, 'total': 999999}
        except Exception as e:
            self.log('category err', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 30, 'total': 0}

    def detailContent(self, ids):
        try:
            url = ids[0]
            if not url.startswith('http'):
                url = self.host + (url if url.startswith('/') else '/' + url)
            html = self.fetch(url, headers=self.headers).text
            title = ''
            m = re.search(r'<meta property="og:title" content="([^"]*)"', html) or re.search(r'<title>([^<]*)</title>', html)
            if m:
                title = re.split(r'[\s|｜_\-–]+', m.group(1).strip())[0].strip()
            pic = ''
            m = re.search(r'<meta property="og:image" content="([^"]*)"', html)
            if m:
                pic = m.group(1)
            items = re.findall(
                r'<a href="([^"]*?origin=([^"&]+)(?:&amp;|&)p=(\d+))"[^>]*?data-origin="([^"]+)"',
                html, re.S)
            groups, order = {}, []
            for full, ocode, pnum, dorigin in items:
                if dorigin not in groups:
                    groups[dorigin] = []
                    order.append(dorigin)
                leaf = full.replace('&amp;', '&')
                if not leaf.startswith('http'):
                    leaf = self.host + (leaf if leaf.startswith('/') else '/' + leaf)
                groups[dorigin].append('第%d集$%s' % (int(pnum) + 1, leaf))
            froms = order
            plays = ['#'.join(groups[k]) for k in order]
            video = {
                'vod_id': ids[0], 'vod_name': title, 'vod_pic': pic,
                'vod_year': '', 'vod_area': '', 'vod_remarks': '', 'vod_content': '',
                'vod_play_from': '$$$'.join(froms) if froms else '电影人生',
                'vod_play_url': '$$$'.join(plays) if plays else '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detail err', e)
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        try:
            html = self.fetch('%s/s?name=%s' % (self.host, urllib.parse.quote(key)), headers=self.headers).text
            vids = [self._vod(*it) for it in self._extract_list(html)]
            return {'list': vids, 'page': 1}
        except Exception as e:
            self.log('search err', e)
            return {'list': [], 'page': 1}

    def playerContent(self, flag, id, vipFlags):
        leaf = id
        try:
            html = self.fetch(leaf, headers=self.headers).text
            m = re.search(r'origin=([^"\\&]+)(?:\\u0026|&amp;|&)url=([0-9a-f]{24})', html)
            if m:
                origin_enc, pid = m.group(1), m.group(2)
                box = '%s/api/super?id=%s&origin=%s' % (self.box, pid, origin_enc)
                return {'parse': 0, 'url': box, 'header': dict(self.headers)}
        except Exception as e:
            self.log('player err', e)
        return {'parse': 1, 'url': leaf, 'header': dict(self.headers)}

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
    d = sp.detailContent(['/movie/6ab1f52fc9f266a6e900c993-35509.html'])
    v = d['list'][0]
    print('详情:', v['vod_name'], '| 线路:', v['vod_play_from'])
    seg0 = v['vod_play_url'].split('$$$')[0].split('#')[0]
    leaf = seg0.split('$', 1)[-1]
    print('首集 leaf:', leaf)
    pl = sp.playerContent(v['vod_play_from'], leaf, None)
    print('播放:', pl['parse'], str(pl['url'])[:120])


if __name__ == '__main__':
    main()
