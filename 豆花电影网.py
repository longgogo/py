# -*- coding: utf-8 -*-
# TVBox / 影视仓 / OK影视 Python Spider —— 豆花电影网 (dhvideo.cc)
# 结构实测：douhua/wzzycc 主题。列表 /dianying.html?page=N；卡片首 a 含图、次 a 含标题；
# 详情剧集按线路 div#list-{origin}；真实播放地址 = box.dyrs.com.de/api/super 的 m3u8
import sys, os, re, json, time, urllib.parse
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
        return '豆花电影网'

    def log(self, *args):
        print('[豆花电影网]', *args)

    def init(self, extend=''):
        self.host = 'https://dhvideo.cc'
        self.box = 'https://box.dyrs.com.de'
        self.group = 'douhua'  # box 分组，实测 dhvideo 用 douhua
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
        # 标题锚点：<a href="/movie/ID-NUM.html">片名</a>
        titles = re.findall(r'<a href="(/(?:movie|tv)/[0-9a-f]{24}-[0-9]+\.html)">([^<]{1,80})</a>', html)
        # 图片锚点：<a href="同" class="relative..."><img ... data-src="封面">
        pics = dict(re.findall(
            r'<a href="(/(?:movie|tv)/[0-9a-f]{24}-[0-9]+\.html)" class="relative[^"]*"[^>]*>\s*'
            r'<img[^>]*?data-src="([^"]+)"', html, re.S))
        out = []
        seen = set()
        for vid, name in titles:
            if vid in seen:
                continue
            seen.add(vid)
            out.append((vid, pics.get(vid, ''), name.strip()))
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
            # 剧集：<a href="/movie/ID/NUM.html?origin=xx&amp;p=n" ... data-origin="xx" ...
            items = re.findall(
                r'<a href="([^"]*?origin=([^"&]+)(?:&amp;|&)p=(\d+))"[^>]*?data-origin="([^"]+)"',
                html, re.S)
            groups = {}
            order = []
            for full, ocode, pnum, dorigin in items:
                key = dorigin
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                leaf = full.replace('&amp;', '&')
                if not leaf.startswith('http'):
                    leaf = self.host + (leaf if leaf.startswith('/') else '/' + leaf)
                groups[key].append('第%d集$%s' % (int(pnum) + 1, leaf))
            froms, plays = [], []
            for k in order:
                froms.append(k)
                plays.append('#'.join(groups[k]))
            video = {
                'vod_id': ids[0], 'vod_name': title, 'vod_pic': pic,
                'vod_year': '', 'vod_area': '', 'vod_remarks': '', 'vod_content': '',
                'vod_play_from': '$$$'.join(froms) if froms else '豆花',
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
                box = '%s/api/super?g=%s&id=%s&origin=%s' % (self.box, self.group, pid, origin_enc)
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
        p2 = sp.categoryContent(tid, 2, {}, {})
        print('  第2页首项:', p2['list'][0]['vod_id'] if p2['list'] else '空')
    # 电影详情
    d = sp.detailContent(['/movie/6ab1f52fc9f266a6e900c993-84931.html'])
    v = d['list'][0]
    print('详情(电影):', v['vod_name'], '| 线路:', v['vod_play_from'])
    seg0 = v['vod_play_url'].split('$$$')[0].split('#')[0]
    leaf = seg0.split('$', 1)[-1]
    print('首集 leaf:', leaf)
    pl = sp.playerContent(v['vod_play_from'], leaf, None)
    print('播放:', pl['parse'], str(pl['url'])[:120])


if __name__ == '__main__':
    main()
