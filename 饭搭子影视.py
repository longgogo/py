# -*- coding: utf-8 -*-
# TVBox / 影视仓 / OK影视 Python Spider —— 饭搭子影视 (fdzys.com)
# 结构实测：mizhiady 主题。列表 div.myui-vodbox-content；分页 ?page=N；
# 详情剧集锚点 div.listitem；播放 url 在 player_aaaa.url（dytt 解析页）
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
        return '饭搭子影视'

    def log(self, *args):
        print('[饭搭子影视]', *args)

    def init(self, extend=''):
        self.host = 'https://fdzys.com'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
        }
        # 仅 /movie/all 与 /tv/all 存在，其余 404（已实测）
        self.categories = {'电影': '/movie/all', '电视剧': '/tv/all'}

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
        # 卡片：<a href="https://fdzys.com/movie/slug"><div class="content-card"><div class="card-img"><img ... data-src="URL" ... alt="标题"
        pat = re.compile(
            r'<a href="(https://fdzys\.com/(?:movie|tv)/[a-z0-9\-]+)">\s*'
            r'<div class="content-card">\s*<div class="card-img">\s*'
            r'<img[^>]*?data-src="([^"]+)"[^>]*?alt="([^"]*)"', re.S)
        items = pat.findall(html)
        if items:
            return items
        # 兜底：逐块顺序无关
        out = []
        for m in re.finditer(r'<div class="myui-vodbox-content">', html):
            seg = html[m.start():m.start() + 2000]
            a = re.search(r'<a href="(https://fdzys\.com/(?:movie|tv)/[a-z0-9\-]+)"', seg)
            p = re.search(r'data-src="([^"]+)"', seg)
            t = re.search(r'alt="([^"]*)"', seg)
            if a:
                out.append((a.group(1), p.group(1) if p else '', t.group(1) if t else ''))
        return out

    def homeContent(self, filter):
        classes = [{'type_name': n, 'type_id': p} for n, p in self.categories.items()]
        return {'class': classes, 'filters': {}}

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
            return {'list': vids, 'page': pg, 'pagecount': 9999, 'limit': 24, 'total': 999999}
        except Exception as e:
            self.log('category err', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 24, 'total': 0}

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
            # 剧集：class="listitem ..."><a href="...">
            items = re.findall(r'class="listitem[^"]*"><a href="([^"]+)"[^>]*>([^<]+)</a>', html)
            groups = {}
            order = []
            for u, name in items:
                ms = re.search(r'sid=(\d+)', u)
                sid = ms.group(1) if ms else '1'
                if sid not in groups:
                    groups[sid] = []
                    order.append(sid)
                groups[sid].append('%s$%s' % (name.strip(), u))
            froms = []
            plays = []
            for i, sid in enumerate(order):
                froms.append('线路%d' % (i + 1))
                plays.append('#'.join(groups[sid]))
            video = {
                'vod_id': ids[0], 'vod_name': title, 'vod_pic': pic,
                'vod_year': '', 'vod_area': '', 'vod_remarks': '', 'vod_content': '',
                'vod_play_from': '$$$'.join(froms) if froms else '饭搭子',
                'vod_play_url': '$$$'.join(plays) if plays else '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detail err', e)
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        try:
            html = self.fetch('%s/search?wd=%s' % (self.host, urllib.parse.quote(key)), headers=self.headers).text
            vids = [self._vod(*it) for it in self._extract_list(html)]
            return {'list': vids, 'page': 1}
        except Exception as e:
            self.log('search err', e)
            return {'list': [], 'page': 1}

    def playerContent(self, flag, id, vipFlags):
        url = id
        try:
            if 'm3u8' not in url and 'mp4' not in url:
                html = self.fetch(url, headers=self.headers).text
                i = html.find('player_aaaa=')
                seg = html[i:i + 2000] if i >= 0 else html
                m = re.search(r'"url":"(https?[^"]+)"', seg) or re.search(r'"url":"([^"]+)"', seg)
                if m:
                    u = m.group(1).replace('\\/', '/')
                    if 'm3u8' in u or 'mp4' in u:
                        return {'parse': 0, 'url': u, 'header': dict(self.headers)}
                    url = u
        except Exception as e:
            self.log('player err', e)
        return {'parse': 1, 'url': url, 'header': dict(self.headers)}

    def localProxy(self, param):
        return None


def main():
    sp = Spider(); sp.init('')
    r = sp.homeContent({})
    print('分类:', [c['type_name'] for c in r['class']])
    for c in r['class']:
        r2 = sp.categoryContent(c['type_id'], 1, {}, {})
        print('  %s 第1页: %d 项' % (c['type_name'], len(r2['list'])))
        if r2['list']:
            print('    样例:', r2['list'][0])
            p2 = sp.categoryContent(c['type_id'], 2, {}, {})
            print('    第2页首项:', p2['list'][0]['vod_id'] if p2['list'] else '空')
    tid = r['class'][0]['type_id']
    p1 = sp.categoryContent(tid, 1, {}, {})
    if p1['list']:
        d = sp.detailContent([p1['list'][0]['vod_id']])
        v = d['list'][0]
        print('详情:', v['vod_name'], '| 线路:', v['vod_play_from'], '| 剧集段数:', len(v['vod_play_url'].split('$$$')))
        ep = v['vod_play_url'].split('$$$')[0].split('#')[0].split('$', 1)[-1]
        print('首集:', ep)
        pl = sp.playerContent(v['vod_play_from'], ep, None)
        print('播放:', pl['parse'], str(pl['url'])[:100])


if __name__ == '__main__':
    main()
