# -*- coding: utf-8 -*-
# TVBox / 影视仓 / OK影视 Python Spider —— 嘀嗒影视 (didahd.xyz)
# 结构实测：苹果CMS(mytheme)。分类 /type/N.html；分页 /type/N-p.html；
# 卡片 a.myui-vodlist__thumb；详情剧集 div#playlist* 内 /play/{id}-{sid}-{nid}.html；
# 播放页 encrypt=3（该主题 player.js 不解此级），故回退 parse=1 交给 app 解析
#
# 2026-09-28 修复：详情页补齐 元信息 字段（此前全部硬编码空值，
# 导致影视仓详情页不显示 演员/导演/年份/地区/播放地址/内容简介 等行）。
#   · 标题   <h1 class="title">（og:title 该主题不输出）
#   · 封面   myui-content__thumb 内 data-original（og:image 同样不输出）
#   · 元信息 <p class="data"><span class="text-muted">主演：</span><a>..</a>..</p>
#   · 简介   「剧情简介：</span>」后至 </p>，内含嵌套 strong/span/a，剥标签取文本
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

    # ------------------------------------------------------- 详情页元信息
    def _strip(self, frag):
        """剥标签 + 压空白，&nbsp; 转空格"""
        frag = re.sub(r'&nbsp;', ' ', frag)
        frag = re.sub(r'<[^>]+>', '', frag)
        return re.sub(r'\s+', ' ', frag).strip()

    def _meta(self, html, label):
        """取 <p class="data"> 里 label 后的内容。
        单值字段（地区/年份等与语言同行）只取到下一个 split-line 前；
        多值字段（主演/导演）取该 <p> 内全部 <a> 用「、」连接。"""
        m = re.search(label + r'[：:]\s*</span>(.*?)(?=<span class="split-line"|<span class="text-muted|</p>)',
                      html, re.S)
        if not m:
            return ''
        frag = m.group(1)
        links = re.findall(r'<a[^>]*>\s*([^<]*?)\s*</a>', frag)
        if links:
            vals = [self._strip(x) for x in links]
            vals = [x for x in vals if x]
            if vals:
                return '、'.join(vals)
        return self._strip(frag)

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
            # 标题：优先 h1（该主题不输出 og:title）
            title = ''
            m = re.search(r'<h1 class="title[^"]*">\s*([^<]*?)\s*</h1>', html)
            if m:
                title = m.group(1).strip()
            if not title:
                m = re.search(r'<meta property="og:title" content="([^"]*)"', html) \
                    or re.search(r'<title>([^<]*)</title>', html)
                if m:
                    title = re.split(r'\s*[-|｜_]\s*', m.group(1).strip())[0].strip()
            # 封面：og:image 不输出，改取详情页大图 data-original
            pic = ''
            m = re.search(r'<meta property="og:image" content="([^"]*)"', html)
            if m:
                pic = m.group(1)
            if not pic:
                m = re.search(r'myui-content__thumb.*?data-original="([^"]+)"', html, re.S)
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
            # 简介：「剧情简介：</span>」后至 </p>，剥掉嵌套的豆瓣评分链接等标签
            content = ''
            m = re.search(r'剧情简介[：:]\s*</span>(.*?)</p>', html, re.S)
            if m:
                frag = m.group(1)
                # 去掉开头嵌着豆瓣评分链接的 <span class="text-highlight">…</span>
                frag = re.sub(r'<span class="text-highlight">.*?</span>', '', frag, count=1, flags=re.S)
                content = self._strip(frag)
                content = re.sub(r'^《[^》]*》\s*', '', content)   # 去掉开头的《片名》
                content = re.sub(r'^[，,、\s]+', '', content)       # 去掉残留的「豆瓣 8.3 分，」
                content = re.sub(r'短评[：:].*$', '', content).strip()
            if not content:
                m = re.search(r'<meta name="description" content="([^"]*)"', html)
                if m:
                    content = self._strip(m.group(1))
            remarks = self._meta(html, '集数') or ''
            video = {
                'vod_id': ids[0], 'vod_name': title, 'vod_pic': pic,
                'vod_year': self._meta(html, '年份'),
                'vod_area': self._meta(html, '地区'),
                'vod_actor': self._meta(html, '主演'),
                'vod_director': self._meta(html, '导演'),
                'vod_remarks': remarks,
                'vod_content': content,
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
    tid = r['class'][0]['type_id']
    p1 = sp.categoryContent(tid, 1, {}, {})
    print('  %s 第1页: %d 项' % (tid, len(p1['list'])))
    if p1['list']:
        print('  样例:', p1['list'][0])
    d = sp.detailContent(['/detail/2795.html'])
    v = d['list'][0]
    print('详情:', v['vod_name'], '| pic:', v['vod_pic'][:60])
    print('  年份:', v['vod_year'], '| 地区:', v['vod_area'])
    print('  演员:', v['vod_actor'])
    print('  导演:', v['vod_director'])
    print('  集数:', v['vod_remarks'])
    print('  简介:', v['vod_content'][:120])
    print('  线路:', v['vod_play_from'], '| 段数:', len(v['vod_play_url'].split('$$$')))
    seg0 = v['vod_play_url'].split('$$$')[0].split('#')[0]
    print('首集:', seg0)
    pl = sp.playerContent(v['vod_play_from'], seg0.split('$', 1)[-1], None)
    print('播放:', pl['parse'], str(pl['url'])[:100])


if __name__ == '__main__':
    main()
