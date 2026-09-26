# -*- coding: utf-8 -*-
"""
九韩剧（9hanju.com）TVBox 蜘蛛源
结构参照嗷呜《电影猎手》规范：class Spider(Spider)，不依赖 base 的 log 方法
"""
import sys, os, re, json, base64, urllib.parse, time

try:
    from base.spider import Spider
except Exception:
    class Spider:
        def __init__(self):
            self.headers = {}

        def fetch(self, url, headers=None, data=None, method='GET', timeout=10, **kwargs):
            import urllib.request, ssl, gzip
            try:
                ssl._create_default_https_context = ssl._create_unverified_context
            except Exception:
                pass
            h = dict(self.headers)
            if headers:
                h.update(headers)
            if data is not None and method == 'GET':
                method = 'POST'  # 带 data 时自动升级为 POST
            req = urllib.request.Request(url, headers=h, method=method)
            if data:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                req.data = data
            resp = urllib.request.urlopen(req, timeout=timeout)
            body = resp.read()
            if body[:2] == b'\x1f\x8b':
                body = gzip.decompress(body)
            class R:
                pass
            r = R()
            r.text = body.decode('utf-8', 'replace')
            r.content = body
            r.status_code = 200

            def to_json():
                return json.loads(r.text)
            r.json = to_json
            return r

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except Exception:
    AES = None
    unpad = None


class Spider(Spider):

    def getName(self):
        return '九韩剧'

    def log(self, *args):
        # 安全日志：子类自带实现，不依赖 base Spider 的 log
        print('[jiuhanju]', *args)

    def init(self, extend=''):
        self.host = 'https://www.9hanju.com'
        self.aes_key = b'my-to-newhan-2025'.ljust(32, b'\0')
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
        }

    def isVideoFormat(self, url):
        return bool(re.match(r'https?://.+\.(m3u8|mp4)', url))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    def _parse_extend(self, extend):
        """兼容 app 传 dict 或 JSON 字符串两种情况"""
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend.strip() else {}
            except Exception:
                extend = {}
        return extend if isinstance(extend, dict) else {}

    def _extract_list(self, html):
        """列表项提取：主正则 + 顺序无关的兜底正则"""
        # 主正则：<a class="tu lazyload" title="..." href="/detail/x.html" data-original="...">
        items = re.findall(
            r'<a[^>]+class="[^"]*tu[^"]*"[^>]*title="([^"]+)"[^>]*href="(/detail/\d+\.html)"[^>]*data-original="([^"]+)"',
            html
        )
        if items:
            return items
        # 兜底：逐个 a 标签内属性顺序无关提取
        items = []
        for m in re.finditer(r'<a\s[^>]*>', html):
            tag = m.group(0)
            if '/detail/' not in tag and 'data-original' not in tag:
                # 属性可能分布在标签与后续 img 之间，取标签前后片段
                seg = html[m.start():m.start() + 600]
            else:
                seg = tag
            t = re.search(r'title="([^"]+)"', seg)
            h = re.search(r'href="(/detail/\d+\.html)"', seg)
            p = re.search(r'data-original="([^"]+)"', seg)
            if t and h:
                items.append((t.group(1), h.group(1), p.group(1) if p else ''))
        return items

    def homeContent(self, filter):
        classes = [
            {'type_name': '韩剧', 'type_id': '1'},
            {'type_name': '韩国电影', 'type_id': '3'},
            {'type_name': '韩国综艺', 'type_id': '4'},
        ]
        years = [{'n': '全部', 'v': ''}] + [
            {'n': str(y), 'v': str(y)} for y in range(2026, 2019, -1)]
        sort = [{'n': '默认', 'v': ''}, {'n': '最新', 'v': 'newstime'}, {'n': '最热', 'v': 'onclick'}]
        year_f = [{'key': 'year', 'name': '年份', 'value': years}]
        sort_f = [{'key': 'by', 'name': '排序', 'value': sort}]
        filters = {
            '1': year_f + sort_f,
            '3': year_f + sort_f,
            '4': year_f + sort_f,
        }
        return {'class': classes, 'filters': filters}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        extend = self._parse_extend(extend)
        try:
            area = extend.get('area', '')
            year = extend.get('year', '')
            by = extend.get('by', '')
            # 网站真实URL格式: /list/{tid}-{年份}-{排序}-{页码}.html，留空表示不过滤
            if area and not year:
                # 站点地区筛选用法未验证，退化为不过滤
                area = ''
            path = '/list/%s-%s-%s-%s.html' % (tid, year, by, pg)
            url = self.host + path
            html = self.fetch(url, headers=self.headers).text
            videos = []
            for title, href, pic in self._extract_list(html):
                videos.append({
                    'vod_id': href,
                    'vod_name': title.strip(),
                    'vod_pic': pic,
                    'vod_remarks': '',
                })
            return {'list': videos, 'page': pg, 'pagecount': 9999,
                    'limit': 20, 'total': 999999}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 20, 'total': 0}

    def detailContent(self, ids):
        try:
            url = self.host + ids[0] if ids[0].startswith('/') else ids[0]
            html = self.fetch(url, headers=self.headers).text
            title_m = re.search(r'id="m">(.*?)</dd>', html)
            pic_m = re.search(r'data-original="([^"]+)"', html)
            actor_m = re.search(r'主演：</dt><dd>([^<]+)</dd>', html)
            director_m = re.search(r'导演：</dt><dd>([^<]+)</dd>', html)
            year_m = re.search(r'上映：</dt><dd>([^<]+)</dd>', html)
            remark_m = re.search(r'状态：</dt><dd>([^<]+)</dd>', html)
            content_m = re.search(r'剧情：</dt><dd>(.+?)<a\s+href="#jq">详细</a>', html, re.DOTALL)
            content = ''
            if content_m:
                content = content_m.group(1).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').strip()

            video = {
                'vod_id': ids[0],
                'vod_name': title_m.group(1).strip() if title_m else '',
                'vod_pic': pic_m.group(1) if pic_m else '',
                'vod_year': year_m.group(1).split('-')[0] if year_m else '',
                'vod_area': '韩国',
                'vod_actor': actor_m.group(1).strip() if actor_m else '',
                'vod_director': director_m.group(1).strip() if director_m else '',
                'vod_remarks': remark_m.group(1).strip() if remark_m else '',
                'vod_content': content,
            }

            # bb_a('id','标题',event) 格式
            ep_matches = re.findall(r"bb_a\('([^']+)'\s*,\s*'([^']+)'.*?\)", html)
            play_list = []
            for ep_id, ep_title in ep_matches:
                play_list.append('%s$%s' % (ep_title.strip(), ep_id))
            video['vod_play_from'] = '在线云播'
            video['vod_play_url'] = '$$$'.join(play_list) if play_list else '#'
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    def _search_post(self, path, params, marker):
        """POST 搜索并兼容 app 的 fetch：data 传 str、显式 Content-Type、手动跟随 302。
        marker 用于识别结果页（结果页才有的特征串）。"""
        headers = dict(self.headers)
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        # 关键：data 传 str 而非 bytes（app 的 fetch 走 Java 桥接，bytes 可能异常）；
        # 不传 method= 参数（参考源仅证明过 headers=/allow_redirects= 两种用法）
        data = urllib.parse.urlencode(params)
        html = ''
        try:
            resp = self.fetch(self.host + path, headers=headers, data=data,
                              allow_redirects=False)
            html = resp.text
            if marker not in html:
                loc = ''
                try:
                    loc = resp.headers.get('Location') or resp.headers.get('location') or ''
                except Exception:
                    loc = ''
                if loc:
                    if loc.startswith('http'):
                        html = self.fetch(loc, headers=headers).text
                    elif loc.startswith('/'):
                        html = self.fetch(self.host + loc, headers=headers).text
                    else:
                        html = self.fetch(self.host + '/' + loc, headers=headers).text
        except Exception:
            html = ''
        if marker not in html:
            # 兜底：让 fetch 自动跟随重定向
            try:
                html = self.fetch(self.host + path, headers=headers,
                                  data=data).text
            except Exception:
                html = ''
        return html

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        # 站点结果页无分页，仅返回第 1 页
        if pg > 1:
            return {'list': [], 'page': pg}
        try:
            # 搜索表单: POST /search/ (show=searchkey, keyboard=关键词)
            # 302 跳转到 /search/code.php?id=xxx 结果页
            html = self._search_post('/search/',
                                     {'show': 'searchkey', 'keyboard': key},
                                     marker='/detail/')
            videos = []
            # 结果结构: <li><i>1.</i><p id="name"><a href="/detail/x.html" title="名">名(年)</a></p>
            #           <p id="time">..</p><p id="actor">演员</p></li>
            for m in re.finditer(
                    r'<p id="name">\s*<a href="(/detail/\d+\.html)" title="([^"]+)">.*?'
                    r'<p id="actor">([^<]*)</p>', html, re.DOTALL):
                videos.append({
                    'vod_id': m.group(1),
                    'vod_name': m.group(2).strip(),
                    'vod_pic': '',
                    'vod_remarks': m.group(3).strip(),
                })
            return {'list': videos, 'page': pg}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg}

    def playerContent(self, flag, id, vipFlags):
        result = {'parse': 0, 'url': '', 'header': dict(self.headers)}
        try:
            ep_id = id.split('$')[-1].strip() if '$' in id else id.strip()
            if AES is None:
                self.log('pycryptodome not available')
                return result
            api_url = self.host + '/u/u1.php?ud=' + ep_id
            enc_text = self.fetch(api_url, headers=self.headers).text.strip()
            enc_bytes = base64.b64decode(enc_text)
            iv = enc_bytes[:16]
            ct = enc_bytes[16:]
            cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
            decrypted = unpad(cipher.decrypt(ct), AES.block_size).decode('utf-8')
            result['url'] = self.host + '/m3/edit-down.php?url=' + urllib.parse.quote(decrypted)
        except Exception as e:
            self.log('playerContent error:', e)
        return result

    def localProxy(self, param):
        return None


def main():
    sp = Spider()
    sp.init('')
    print('=== homeContent ===')
    r = sp.homeContent({})
    print('classes:', [c['type_name'] for c in r['class']])
    print()
    print('=== categoryContent ===')
    r = sp.categoryContent('1', 1, {}, {})
    print('items:', len(r['list']))
    if r['list']:
        v = r['list'][0]
        print('  first:', v['vod_name'], '|', v['vod_id'])
    print()
    print('=== detailContent ===')
    r = sp.detailContent(['/detail/3752.html'])
    v = r['list'][0]
    print('  name:', v['vod_name'])
    print('  play_from:', v['vod_play_from'])
    plays = v['vod_play_url'].split('$$$')
    print('  episodes:', len(plays))
    print()
    print('=== playerContent ===')
    if plays and plays[0] != '#':
        r = sp.playerContent('在线云播', plays[0], None)
        print('  parse:', r['parse'])
        print('  url:', r['url'][:100])


if __name__ == '__main__':
    main()
