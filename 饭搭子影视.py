# -*- coding: utf-8 -*-
# TVBox / 影视仓 / OK影视 Python Spider —— 饭搭子影视 (fdzys.com)
# 结构实测：mizhiady 主题。列表 div.myui-vodbox-content；分页 ?page=N（子分类页同构）；
# 详情剧集锚点 div.listitem；播放 url 在 player_aaaa.url（dytt 解析页，本地解不出直链，
# 返回体为空，只能 parse=1 交给 app 嗅探）
#
# 2026-09-28 修复：
#   1) 详情页补齐 元信息 字段（此前硬编码空值，影视仓详情不显示 演员/导演/简介 等行）：
#      · 导演/主演  class="detail-meta"（主演为逗号分隔，转「、」）
#      · 简介       <div class="intro"> 内 <p> 正文
#      · 备注       <h1 class="title_name"> 里的 <span class="title_ep">（如 HD国语）
#      · 标题       h1.title_name（og:title 带 "_免费在线观看_" 后缀，仅兜底）
#   2) 搜索接口修复：/search?wd= 返回的是前端 JS 空页（无结果）。
#      站方真实搜索 URL（页面内 buildSearchUrl）：/yu-{wd}-xianguan-de-yingpian-shippin-zhibo
#   3) 分类扩充：类型/地区/年份子分类页与列表页同构、翻页一致（?page=N）。
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
                resp = urllib.request.urlopen(req, timeout=25)
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
        # /movie/all 与 /tv/all 及其类型/地区/年份子分类页均存在（已实测，结构同构）
        self.categories = {
            '电影': '/movie/all',
            '电视剧': '/tv/all',
            '动作': '/movie/dongzuo', '喜剧': '/movie/xiju', '爱情': '/movie/aiqing',
            '科幻': '/movie/kehuan', '恐怖': '/movie/kongbupian', '剧情': '/movie/juqing',
            '战争': '/movie/zhanzheng',
            '国产剧': '/tv/guochan', '欧美剧': '/tv/oumei', '日剧': '/tv/riben', '韩剧': '/tv/hanguo',
            '电影2026': '/movie/all-2026', '电影2025': '/movie/all-2025', '电影2024': '/movie/all-2024',
            '剧集2026': '/tv/all-2026', '剧集2025': '/tv/all-2025', '剧集2024': '/tv/all-2024',
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
        """带重试的 GET（站点走 Cloudflare，偶发 TLS 握手超时/连接重置）"""
        last = None
        for i in range(5):
            try:
                r = self.fetch(url, headers=self.headers)
                if getattr(r, 'text', ''):
                    return r
            except Exception as e:
                last = e
            time.sleep(min(1.0 + i * 0.6, 3.0))
        if last:
            raise last
        class _R(object):
            text = ''
        return _R()

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
            items = self._extract_list(self._f(self.host + '/').text)
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
            html = self._f(url).text
            vids = [self._vod(*it) for it in self._extract_list(html)]
            return {'list': vids, 'page': pg, 'pagecount': 9999, 'limit': 24, 'total': 999999}
        except Exception as e:
            self.log('category err', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 24, 'total': 0}

    # ------------------------------------------------------- 详情页元信息
    def _meta(self, html, label):
        """取「导演：xxx」「主演：a,b,c」。兼容两种布局：
        电影页 class="detail-meta"（导演：xxx）；剧集页 <div class="director ..."><div class="name">导演:</div> xxx</div>
        逗号统一转「、」。"""
        m = re.search(r'class="detail-meta"[^>]*>\s*' + label + r'[：:]\s*([^<]*)<', html)
        if not m:
            m = re.search(r'<div class="name">\s*' + label + r'\s*[：:]\s*</div>\s*([^<]*)', html)
        if not m:
            return ''
        vals = [x.strip() for x in m.group(1).replace('，', ',').split(',') if x.strip()]
        vals = list(dict.fromkeys(vals))   # 去重（源页面偶有重复如「王连平,王连平」）
        return '、'.join(vals)

    def detailContent(self, ids):
        try:
            url = ids[0]
            if not url.startswith('http'):
                url = self.host + (url if url.startswith('/') else '/' + url)
            html = self._f(url).text
            # 标题：电影页 h1.title_name（内含 title_ep 备注要剥掉）；剧集页 h1.title；
            # og:title 带 "_免费在线观看_" 后缀，仅兜底
            title = ''
            m = re.search(r'<h1 class="title_name[^"]*"[^>]*>(.*?)</h1>', html, re.S)
            if m:
                title = re.sub(r'<span class="title_ep">[^<]*</span>', '', m.group(1))
                title = re.sub(r'<[^>]+>', '', title).strip()
            if not title:
                m = re.search(r'<h1 class="title"[^>]*>\s*([^<]*?)\s*</h1>', html)
                if m:
                    title = m.group(1).strip()
            if not title:
                m = re.search(r'<meta property="og:title" content="([^"]*)"', html)
                if m:
                    title = m.group(1).split('_')[0].strip()
            title = re.sub(r'(免费在线观看|高清播放|在线观看).*$', '', title).strip()
            # 备注：h1 里的 <span class="title_ep">（如 HD国语）
            remarks = ''
            m = re.search(r'<span class="title_ep">([^<]*)</span>', html)
            if m:
                remarks = m.group(1).strip()
            pic = ''
            m = re.search(r'<meta property="og:image" content="([^"]*)"', html)
            if m:
                pic = m.group(1)
            director = self._meta(html, '导演')
            actor = self._meta(html, '主演')
            # 简介：<div class="intro"> 内第一个 <p>
            content = ''
            m = re.search(r'<div class="intro">.*?<p>(.*?)</p>', html, re.S)
            if m:
                content = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(1))).strip()
            if not content:
                m = re.search(r'<meta name="description" content="([^"]*)"', html)
                if m:
                    content = m.group(1).strip()
            # 剧集：class="listitem ..."><a href="..."（剧集页为相对路径，统一补全域名）
            items = re.findall(r'class="listitem[^"]*"><a href="([^"]+)"[^>]*>([^<]+)</a>', html)

            def _abs(u):
                if u.startswith('http'):
                    return u
                return self.host + (u if u.startswith('/') else '/' + u)

            groups = {}
            order = []
            for u, name in items:
                ms = re.search(r'sid=(\d+)', u)
                sid = ms.group(1) if ms else '1'
                if sid not in groups:
                    groups[sid] = []
                    order.append(sid)
                groups[sid].append('%s$%s' % (name.strip(), _abs(u)))
            froms = []
            plays = []
            for i, sid in enumerate(order):
                froms.append('线路%d' % (i + 1))
                plays.append('#'.join(groups[sid]))
            video = {
                'vod_id': ids[0], 'vod_name': title, 'vod_pic': pic,
                'vod_year': '', 'vod_area': '',
                'vod_actor': actor, 'vod_director': director,
                'vod_remarks': remarks, 'vod_content': content,
                'vod_play_from': '$$$'.join(froms) if froms else '饭搭子',
                'vod_play_url': '$$$'.join(plays) if plays else '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detail err', e)
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        try:
            # 站方真实搜索 URL（页面 buildSearchUrl 生成）：/yu-{wd}-xianguan-de-yingpian-shippin-zhibo
            # 旧 /search?wd= 是前端 JS 空页，抓不到结果
            kw = urllib.parse.quote(key)
            html = self.fetch('%s/yu-%s-xianguan-de-yingpian-shippin-zhibo' % (self.host, kw),
                              headers=self.headers).text
            vids = [self._vod(*it) for it in self._extract_list(html)]
            return {'list': vids, 'page': 1}
        except Exception as e:
            self.log('search err', e)
            return {'list': [], 'page': 1}

    def playerContent(self, flag, id, vipFlags):
        url = id
        try:
            if 'm3u8' not in url and 'mp4' not in url:
                html = self._f(url).text
                i = html.find('player_aaaa=')
                if i >= 0:
                    m = re.search(r'player_aaaa\s*=\s*(\{.*?\})\s*[;<]', html[i:i + 4000], re.S)
                    if m:
                        try:
                            data = json.loads(m.group(1))
                            u = (data.get('url') or '').replace('\\/', '/').strip()
                        except Exception:
                            m2 = re.search(r'"url":"([^"]+)"', m.group(1))
                            u = m2.group(1).replace('\\/', '/') if m2 else ''
                        if u:
                            if 'm3u8' in u or 'mp4' in u:
                                return {'parse': 0, 'url': u, 'header': dict(self.headers)}
                            url = u   # dytt 解析页：本地解不出直链，交 app 嗅探
        except Exception as e:
            self.log('player err', e)
        return {'parse': 1, 'url': url, 'header': dict(self.headers)}

    def localProxy(self, param):
        return None


def main():
    sp = Spider(); sp.init('')
    r = sp.homeContent({})
    print('分类:', [c['type_name'] for c in r['class']])
    for c in r['class'][:4]:
        r2 = sp.categoryContent(c['type_id'], 1, {}, {})
        print('  %s 第1页: %d 项' % (c['type_name'], len(r2['list'])))
        if r2['list']:
            p2 = sp.categoryContent(c['type_id'], 2, {}, {})
            print('    第2页首项:', p2['list'][0]['vod_id'] if p2['list'] else '空')
    tid = r['class'][0]['type_id']
    p1 = sp.categoryContent(tid, 1, {}, {})
    if p1['list']:
        d = sp.detailContent([p1['list'][0]['vod_id']])
        v = d['list'][0]
        print('详情:', v['vod_name'], '| 备注:', v['vod_remarks'], '| pic:', v['vod_pic'][:50])
        print('  导演:', v['vod_director'])
        print('  演员:', v['vod_actor'][:80])
        print('  简介:', v['vod_content'][:80])
        print('  线路:', v['vod_play_from'], '| 剧集段数:', len(v['vod_play_url'].split('$$$')))
        ep = v['vod_play_url'].split('$$$')[0].split('#')[0].split('$', 1)[-1]
        pl = sp.playerContent(v['vod_play_from'], ep, None)
        print('播放:', pl['parse'], str(pl['url'])[:100])
    print('搜索「沈腾」:')
    rs = sp.searchContent('沈腾', False, 1)
    print('  结果数:', len(rs['list']), [x['vod_name'] for x in rs['list'][:5]])


if __name__ == '__main__':
    main()
