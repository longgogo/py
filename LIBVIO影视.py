# -*- coding: utf-8 -*-
"""
LIBVIO影视 TVBox Python 源（影视仓 / OK影视）
站点：https://www.libvio.to/  —— MacCMS(苹果CMS) v10 + stui 模板

探测到的事实（来源：真实 TVBox 配置的 XPath / 站点结构）
  列表  : /show/{tid}-----------.html        （11 连字符占位，第 9 字段为页码）
  翻页  : /show/{tid}--------{pg}---.html    （页码位于第 9 字段）
  详情  : /detail/{vid}.html
  播放  : /play/{vid}-{sid}-{eid}.html       （播放页内联 player_aaaa JSON 含真实 m3u8）
  搜索  : GET /search/-------------.html?wd={wd}&submit=   （13 连字符）
          备用 POST /vodsearch/ (wd)  /  /index.php/ajax/suggest?mid=1&wd=
  列表项: div.stui-vodlist__box > a[href][title][data-original]
  选集  : ul.stui-content__playlist > li > a[href="/play/..."]

注：本机与国内出口均被该站 CDN 挑战拦截（HTTP 403 x-cdn-challenge: required），
    本地无法实测；结构按上述真实配置与 MacCMS v10 规范编写。
"""
import sys, os, re, json, base64, urllib.parse

UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1')

try:
    from base.spider import Spider
except Exception:
    class Spider:
        def __init__(self):
            self.headers = {}

        def fetch(self, url, headers=None, data=None, method='GET', timeout=10, **kwargs):
            # **kwargs 用于接收 app 专用参数（allow_redirects 等），urllib 自动跟随可忽略
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
            if data is not None:
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
            r.status_code = getattr(resp, 'status', 200) or 200
            try:
                r.headers = resp.headers
            except Exception:
                r.headers = {}

            def to_json():
                return json.loads(r.text)
            r.json = to_json
            return r


class Spider(Spider):

    def getName(self):
        return 'LIBVIO影视'

    def log(self, *args):
        print('[LIBVIO]', *args)

    def init(self, extend=''):
        self.host = 'https://www.libvio.to'
        self.detail_re = r'/detail/\d+\.html'
        self.headers = {
            'User-Agent': UA,
            # 反盗链：播放与详情都必须带本站 Referer
            'Referer': self.host + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        # 分类（type_id 为站点真实分类 id，子分类同样可独立访问）
        self.categories = {
            '最近更新': '19',
            '电影': '1', '电视剧': '2', '综艺': '3', '动漫': '4',
            '动作片': '6', '喜剧片': '7', '爱情片': '8', '科幻片': '9',
            '恐怖片': '10', '剧情片': '11', '战争片': '12', '动画片': '23',
            '国产剧': '13', '港台剧': '14', '日韩剧': '15', '欧美剧': '16',
            '纪录片': '21', '泰国剧': '24',
        }

    def isVideoFormat(self, url):
        return bool(re.match(r'https?://.+\.(m3u8|mp4)', url or ''))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ------------------------------------------------------------------ 工具
    def _parse_extend(self, extend):
        """兼容 app 传 dict 或 JSON 字符串两种情况"""
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend.strip() else {}
            except Exception:
                extend = {}
        return extend if isinstance(extend, dict) else {}

    def _attr(self, tag, name):
        m = re.search(r'(?i)\b' + name + r'\s*=\s*"([^"]*)"', tag or '')
        return m.group(1).strip() if m else ''

    def _clean_text(self, s):
        s = re.sub(r'(?is)<[^>]+>', '', s or '')
        s = (s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
              .replace('&#39;', "'").replace('&lt;', '<').replace('&gt;', '>'))
        return s.strip()

    def _abs(self, url):
        url = (url or '').strip()
        if not url:
            return ''
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('http'):
            return url
        return self.host + ('' if url.startswith('/') else '/') + url

    def _meta(self, html, label):
        m = re.search(label + r'\s*[:：]\s*(?:</?[^>]+>\s*)*([^<\n]{1,60})', html)
        return self._clean_text(m.group(1)) if m else ''

    # -------------------------------------------------------------- 列表解析
    def _extract_list(self, html):
        """从列表页/搜索页提取条目；对属性顺序与模板差异免疫。"""
        data, order = {}, []
        for m in re.finditer(r'(?is)<a\b[^>]*href="([^"]*' + self.detail_re + r')"[^>]*>', html):
            vid = m.group(1)
            tag = m.group(0)
            seg = html[m.start():m.start() + 1500]
            title = self._attr(tag, 'title')
            pic = (self._attr(tag, 'data-original') or self._attr(tag, 'data-src')
                   or self._attr(tag, 'data-echo'))
            img = re.search(r'(?is)<img\b[^>]*>', seg)
            if img:
                it = img.group(0)
                if not pic:
                    pic = (self._attr(it, 'data-original') or self._attr(it, 'data-src')
                           or self._attr(it, 'data-echo') or self._attr(it, 'src'))
                if not title:
                    title = self._attr(it, 'alt')
            if not title:
                t = re.search(r'(?i)title="([^"]+)"', seg)
                title = t.group(1) if t else ''
            remark = ''
            rm = re.search(r'(?is)class="[^"]*(?:pic-text|module-item-note)[^"]*"[^>]*>([^<]{1,20})<', seg)
            if rm:
                remark = self._clean_text(rm.group(1))
            if vid not in data:
                data[vid] = {'vod_id': vid, 'vod_name': '', 'vod_pic': '', 'vod_remarks': ''}
                order.append(vid)
            rec = data[vid]
            if not rec['vod_name'] and title:
                rec['vod_name'] = self._clean_text(title)
            if not rec['vod_pic'] and pic:
                rec['vod_pic'] = pic
            if not rec['vod_remarks'] and remark:
                rec['vod_remarks'] = remark
        out = []
        for vid in order:
            rec = data[vid]
            if not rec['vod_name']:
                rec['vod_name'] = vid
            out.append(rec)
        return out

    def _list_url(self, tid, pg):
        t = str(tid)
        if '/' in t or t.startswith('http'):
            return self._abs(t)
        if pg > 1:
            # 页码为第 9 字段：/show/{id}--------2---.html
            return '%s/show/%s--------%d---.html' % (self.host, t, pg)
        return '%s/show/%s-----------.html' % (self.host, t)

    # ------------------------------------------------------------------ 接口
    def homeContent(self, filter):
        try:
            classes = [{'type_name': n, 'type_id': t} for n, t in self.categories.items()]
            return {'class': classes, 'filters': {}}
        except Exception as e:
            self.log('homeContent error:', e)
            return {'class': [], 'filters': {}}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)  # app 可能传字符串
        except Exception:
            pg = 1
        extend = self._parse_extend(extend)
        try:
            html = self.fetch(self._list_url(tid, pg), headers=self.headers).text
            videos = self._extract_list(html)
            return {'list': videos, 'page': pg, 'pagecount': 9999,
                    'limit': len(videos) or 24, 'total': 999999}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 24, 'total': 0}

    # -------------------------------------------------------------- 选集解析
    def _eps(self, block):
        eps = []
        for m in re.finditer(r'(?is)<a\b[^>]*href="([^"]*?/(?:play|vodplay)/[^"]+?\.html)"[^>]*>(.*?)</a>', block):
            href, text = m.group(1), self._clean_text(m.group(2))
            if not text:
                eid = re.search(r'-(\d+)\.html$', href)
                text = '第%s集' % (eid.group(1) if eid else len(eps) + 1)
            eps.append((text, self._abs(href)))
        return eps

    def _play_lists(self, html):
        """返回 (播放来源名列表, 每个来源的 集名$地址 列表)

        来源名与选集块按文档顺序一一对应：stui 模板是「名-块」交替，
        MacCMS 默认模板是「全部 tab 名」在前、「各来源选集块」在后，
        因此用 FIFO 队列取名字，两种模板都成立。
        """
        froms, groups = [], []
        names = []
        tok = re.compile(
            r'(?is)<h3[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h3>'
            r'|data-dropdown-value="([^"]+)"'
            r'|<(ul|div)[^>]*class="[^"]*(?:stui-content__playlist|module-play-list-content)[^"]*"[^>]*>(.*?)</\3>'
        )
        for m in tok.finditer(html):
            if m.group(1) is not None or m.group(2) is not None:
                t = self._clean_text(m.group(1) or m.group(2))
                if t and len(t) <= 24:
                    names.append(t)
                continue
            eps = self._eps(m.group(4) or '')
            if not eps:
                continue
            # 去重：正序/倒序两个容器内容一致（仅顺序相反）时只保留一个
            if groups and sorted(e[1] for e in groups[-1]) == sorted(e[1] for e in eps):
                continue
            froms.append(names.pop(0) if names else ('线路%d' % (len(froms) + 1)))
            groups.append(eps)
        # 兜底：全文扫描 /play/{vid}-{sid}-{eid}.html，按 sid 分组
        if not groups:
            buckets, order = {}, []
            for m in re.finditer(
                    r'(?is)<a\b[^>]*href="([^"]*?/(?:play|vodplay)/\d+-(\d+)-(\d+)\.html)"[^>]*>(.*?)</a>', html):
                href, sid, eid, text = m.group(1), m.group(2), m.group(3), m.group(4)
                if sid not in buckets:
                    buckets[sid] = []
                    order.append(sid)
                buckets[sid].append((self._clean_text(text) or ('第%s集' % eid), self._abs(href)))
            for sid in order:
                froms.append('线路%s' % sid)
                groups.append(buckets[sid])
        return froms, groups

    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
            url = self._abs(str(vid))
            html = self.fetch(url, headers=self.headers).text

            name = ''
            nm = re.search(r'(?is)<h1[^>]*>(.*?)</h1>', html)
            if nm:
                name = self._clean_text(nm.group(1))
            if not name:
                tm = re.search(r'(?is)<title>(.*?)</title>', html)
                name = self._clean_text(tm.group(1)) if tm else ''

            pic = ''
            pm = re.search(r'(?is)<(?:a|div)[^>]*class="[^"]*\bpic\b[^"]*"[^>]*>.*?<img\b[^>]*>', html)
            if pm:
                it = re.search(r'(?is)<img\b[^>]*>', pm.group(0)).group(0)
                pic = (self._attr(it, 'data-original') or self._attr(it, 'data-src')
                       or self._attr(it, 'src'))
            if not pic:
                im = re.search(r'(?is)<img\b[^>]*>', html)
                if im:
                    pic = (self._attr(im.group(0), 'data-original') or self._attr(im.group(0), 'data-src')
                           or self._attr(im.group(0), 'src'))
            pic = self._abs(pic)

            desc = ''
            dm = re.search(r'(?is)<span[^>]*class="[^"]*detail-content[^"]*"[^>]*>(.*?)</span>', html)
            if dm:
                desc = self._clean_text(dm.group(1))
            if not desc:
                dm = re.search(r'(?is)<meta[^>]*name="description"[^>]*content="([^"]*)"', html)
                desc = dm.group(1) if dm else ''

            froms, groups = self._play_lists(html)
            play_from = '$$$'.join(froms) if froms else 'LIBVIO'
            play_url = '$$$'.join(['#'.join(['%s$%s' % (n, u) for n, u in eps]) for eps in groups])

            video = {
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic,
                'vod_year': self._meta(html, '年份'),
                'vod_area': self._meta(html, '地区'),
                'vod_actor': self._meta(html, '主演'),
                'vod_director': self._meta(html, '导演'),
                'vod_remarks': self._meta(html, '状态') or self._meta(html, '更新'),
                'vod_content': desc,
                'vod_play_from': play_from,
                'vod_play_url': play_url or '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    # -------------------------------------------------------------- 搜索
    def _search_post(self, path, params, marker):
        """POST 搜索并兼容 app 的 fetch：data 传 str、显式 Content-Type、手动跟随 302。"""
        headers = dict(self.headers)
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        data = urllib.parse.urlencode(params)  # str，不转 bytes（app Java 桥兼容）
        html = ''
        try:
            resp = self.fetch(self.host + path, headers=headers, data=data,
                              allow_redirects=False)  # 不传 method=，由 data 隐式 POST
            html = resp.text
            if marker not in html:
                loc = ''
                try:
                    loc = resp.headers.get('Location') or resp.headers.get('location') or ''
                except Exception:
                    loc = ''
                if loc:
                    html = self.fetch(self._abs(loc), headers=headers).text
        except Exception:
            html = ''
        if marker not in html:  # 兜底：自动跟随
            try:
                html = self.fetch(self.host + path, headers=headers, data=data).text
            except Exception:
                html = ''
        return html

    def _suggest(self, key):
        """MacCMS v10 的 ajax suggest（JSON），部分版本存在且比搜索页更稳"""
        try:
            url = self.host + '/index.php/ajax/suggest?mid=1&wd=' + urllib.parse.quote(key) + '&limit=50'
            obj = json.loads(self.fetch(url, headers=self.headers).text)
            out = []
            for it in (obj.get('list') or []):
                vid = it.get('id') or it.get('vod_id')
                if vid is None:
                    continue
                out.append({
                    'vod_id': '/detail/%s.html' % vid,
                    'vod_name': it.get('name') or it.get('vod_name') or '',
                    'vod_pic': it.get('pic') or it.get('vod_pic') or '',
                    'vod_remarks': '',
                })
            return out
        except Exception:
            return []

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)  # app 可能传字符串
        except Exception:
            pg = 1
        if pg > 1:  # 搜索结果页无分页
            return {'list': [], 'page': pg}
        try:
            # 1) GET /search/-------------.html?wd=  （站点实际搜索路径）
            url = self.host + '/search/-------------.html?wd=' + urllib.parse.quote(key) + '&submit='
            try:
                html = self.fetch(url, headers=self.headers).text
            except Exception:
                html = ''
            videos = self._extract_list(html) if html else []
            # 2) POST /vodsearch/（部分 MacCMS v10 仅认 POST）
            if not videos:
                html = self._search_post('/vodsearch/', {'wd': key, 'submit': 'search'}, self.detail_re)
                videos = self._extract_list(html)
            # 3) ajax suggest（JSON）
            if not videos:
                videos = self._suggest(key)
            return {'list': videos, 'page': pg}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg}

    # -------------------------------------------------------------- 播放
    def _brace_json(self, html, start):
        """从 html[start]=='{' 起按括号配对取出一段 JSON 并解析"""
        depth, i, n = 0, start, len(html)
        while i < n:
            c = html[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    raw = html[start:i + 1]
                    try:
                        return json.loads(raw)
                    except Exception:
                        try:
                            return json.loads(raw.replace("\\'", "'"))
                        except Exception:
                            return None
            i += 1
        return None

    def _clean_url(self, u):
        u = (u or '').strip()
        u = (u.replace('\\/', '/').replace('\\u0026', '&').replace('\\u003d', '=')
             .replace('&amp;', '&').replace('\\', ''))
        if u.startswith('//'):
            u = 'https:' + u
        cands = [u]
        try:
            cands.append(urllib.parse.unquote(u))
        except Exception:
            pass
        for c in cands:  # 原样先判，避免误伤带 %2B 等签名的直链
            if re.match(r'^https?://', c or ''):
                return c
        try:  # base64 兜底
            d = base64.b64decode(u + '=' * (-len(u) % 4)).decode('utf-8', 'replace')
            if re.match(r'^https?://', d):
                return d
        except Exception:
            pass
        return u

    def _parse_player_url(self, html):
        """播放页内联 player_aaaa / player_data JSON 中的真实地址"""
        for key in ('player_aaaa', 'player_data', 'player_'):
            i = html.find(key)
            if i < 0:
                continue
            j = html.find('{', i)
            if j < 0:
                continue
            obj = self._brace_json(html, j)
            if isinstance(obj, dict):
                for k in ('url', 'url_next', 'link', 'vod_url'):
                    if obj.get(k):
                        u = self._clean_url(str(obj[k]))
                        if re.match(r'https?://', u):
                            return u
        m = re.search(r'''(?is)["'](https?:[^"']*?\.(?:m3u8|mp4)[^"']*)["']''', html)
        if m:
            return self._clean_url(m.group(1))
        m = re.search(r'''(?is)(?:url|src|source)\s*[:=]\s*["']([^"']+?)["']''', html)
        if m:
            u = self._clean_url(m.group(1))
            if re.match(r'https?://', u):
                return u
        return ''

    def playerContent(self, flag, id, vipFlags):
        try:
            url = self._abs(str(id))
            if re.search(r'/(?:play|vodplay)/', url):
                html = self.fetch(url, headers=self.headers).text
                real = self._parse_player_url(html)
                if real:
                    return {'parse': 0, 'url': real, 'header': dict(self.headers)}
            # 已经是直链或解析失败：交给播放器（带 Referer 防 403）
            return {'parse': 0, 'url': url, 'header': dict(self.headers)}
        except Exception as e:
            self.log('playerContent error:', e)
            return {'parse': 0, 'url': self._abs(str(id)), 'header': dict(self.headers)}

    def localProxy(self, param):
        return None


def main():
    """本地测试块：python 脚本名.py 直接运行"""
    sp = Spider()
    sp.init('')
    print('=== homeContent ===')
    r = sp.homeContent({})
    print('classes:', [c['type_name'] for c in r['class']])
    print()
    print('=== categoryContent（全部分类）===')
    for c in r['class']:
        r2 = sp.categoryContent(c['type_id'], 1, {}, {})
        print('  %s: %d 项' % (c['type_name'], len(r2['list'])))
    print()
    print('=== 翻页（第2页必须与第1页不同）===')
    first_tid = r['class'][0]['type_id']
    p1 = sp.categoryContent(first_tid, 1, {}, {})
    p2 = sp.categoryContent(first_tid, 2, {}, {})
    if p1['list'] and p2['list']:
        print('  p1 first:', p1['list'][0]['vod_id'], '| p2 first:', p2['list'][0]['vod_id'])
    print()
    print('=== 兼容性：字符串 pg / 字符串 extend ===')
    print('  str pg:', len(sp.categoryContent(first_tid, '1', {}, {})['list']), '项')
    print('  str extend:', len(sp.categoryContent(first_tid, 1, {}, '{}')['list']), '项')
    print()
    print('=== detailContent ===')
    if p1['list']:
        r3 = sp.detailContent([p1['list'][0]['vod_id']])
        if r3['list']:
            v = r3['list'][0]
            plays = v['vod_play_url'].split('$$$')
            print('  name:', v['vod_name'], '| 来源数:', len(v['vod_play_from'].split('$$$')), '| 首源集数:', len(plays[0].split('#')))
            print()
            print('=== playerContent ===')
            if plays and plays[0] != '#':
                r4 = sp.playerContent(v['vod_play_from'], plays[0].split('$', 1)[1], None)
                print('  parse:', r4['parse'], '| url:', r4['url'][:80])


if __name__ == '__main__':
    main()
