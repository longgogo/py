# -*- coding: utf-8 -*-
"""
VS影院  TVBox Python Spider（影视仓 / OK影视）
站点：https://www.vasouy.com/   （MacCMS v10 + 海螺 module- 模板）

旧域名 m.ytshengde.com 已废弃（__xcdn 接口超时、站点半死），现行域名 www.vasouy.com。
结构实测（2026-09-28，移动端 UA + curl）：
  · 分类列表：/va/{cid}.html       第 N 页：/va/{cid}-{N}.html（-0 即第一页）
  · 详情页：  /sou/{id}.html       （页内含"module-item"卡片、video-info 元信息区）
  · 播放页：  /play/{id}-{sid}-{eid}.html
              页内有明文直链：var now="https://cdn.yzzyvip-29.com/.../index.m3u8";
              → playerContent 直接 parse=0 出直链，无需嗅探。
  · 列表卡片：<div class="module-item">
                <a href="/sou/{id}.html" title="片名" class="module-item-pic">
                  <img class="lazyload" data-src="海报">
                <div class="module-item-titlebox"><a ... class="module-item-title">
                <div class="module-item-text">HD国语</div>   ← 副标题/备注
              （侧栏热搜锚点 <a href="/sou/N.html" class="hot"> 无 title 属性，
                按「卡片锚点必须带 title=」提取即可天然过滤。）
  · 详情页线路：<div class="module-tab-item tab-item"><span data-dropdown-value="云播资源">…
                线路名顺序与剧集块 <div class="sort-item"> 顺序一一对应
                （实测：云播资源→sid1 共72集、快播资源→sid0 共26集）。
  · 搜索：    /search.php?searchword={wd}  翻页 &page={pg}，无图形验证码。
  · 反爬：    搜索等请求偶发 503 +「加载中…」meta-refresh 过渡页，站点会在响应头
              下发节流 cookie（ssea2_search 等），带上 cookie 重试一次即过。
                本源自管 cookie（解析 Set-Cookie 回填 Cookie 头），实测连续搜索可通。
                无 __xcdn / 无图形验证码，旧源那套 PoW 已不需要。
"""
import sys
import re
import json
import http.cookies
import urllib.parse

# ---- base Spider 导入：app 内有 base.spider，本地测试走 fallback ----
try:
    from base.spider import Spider
except Exception:
    class Spider:
        """本地测试用最小实现：方法与 app 版保持一致的调用习惯"""

        def __init__(self):
            self.headers = {}

        def fetch(self, url, headers=None, data=None, method='GET', timeout=15, **kwargs):
            import urllib.request
            import urllib.error
            import ssl
            import gzip
            try:
                ssl._create_default_https_context = ssl._create_unverified_context
            except Exception:
                pass
            h = dict(self.headers)
            if headers:
                h.update(headers)
            if data is not None and method == 'GET':
                method = 'POST'   # 带 data 时自动升级为 POST
            req = urllib.request.Request(url, headers=h, method=method)
            if data:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                req.data = data
            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                resp = e          # 503 等也把 body 交出去，交给上层判断
            body = resp.read()
            if body[:2] == b'\x1f\x8b':
                body = gzip.decompress(body)

            class R:
                pass
            r = R()
            r.text = body.decode('utf-8', 'replace')
            r.content = body
            try:
                r.status_code = resp.getcode()
            except Exception:
                r.status_code = 200
            try:
                r.headers = dict(resp.headers)
            except Exception:
                r.headers = {}

            def to_json():
                return json.loads(r.text)
            r.json = to_json
            return r


class Spider(Spider):

    def getName(self):
        return 'VS影院'

    def log(self, *args):
        # 子类自带日志实现，绝不依赖 base Spider 的 log
        print('[VS影院]', *args)

    def init(self, extend=''):
        self.host = 'https://www.vasouy.com'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        # type_id 直接用真实路径，翻页时用 /va/{cid}-{pg}.html
        self.categories = {
            '电影': '/va/1.html',
            '电视剧': '/va/2.html',
            '综艺': '/va/3.html',
            '动漫': '/va/4.html',
        }
        self.search_path = '/search.php'
        self._cookies = {}

    # ------------------------------------------------------------------ 基础
    def isVideoFormat(self, url):
        return bool(re.match(r'https?://.+\.(m3u8|mp4|flv)', url or ''))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        return None

    def _parse_extend(self, extend):
        """兼容 app 传 dict 或 JSON 字符串两种情况"""
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend.strip() else {}
            except Exception:
                extend = {}
        return extend if isinstance(extend, dict) else {}

    def _text(self, resp):
        try:
            t = resp.text
        except Exception:
            t = ''
        if isinstance(t, bytes):
            t = t.decode('utf-8', 'replace')
        return t or ''

    def _is_loading(self, html):
        """站方偶发的 503「加载中…」meta-refresh 过渡页"""
        return ('加载中' in html[:2000]) and ('http-equiv="refresh"' in html[:2000])

    def _absorb_cookies(self, resp):
        """解析响应里的 Set-Cookie，存入 self._cookies 供后续请求带上"""
        try:
            hs = getattr(resp, 'headers', None)
            if not hs:
                return
            raw = []
            try:
                for k, v in hs.items():
                    if str(k).lower() == 'set-cookie':
                        raw.append(v)
            except Exception:
                pass
            if not raw and hasattr(hs, 'get'):
                v = None
                for key in ('set-cookie', 'Set-Cookie'):
                    try:
                        v = hs.get(key)
                    except Exception:
                        v = None
                    if v:
                        raw.append(v)
            for r in raw:
                for part in str(r).split('\n'):
                    try:
                        c = http.cookies.SimpleCookie()
                        c.load(part)
                        for name, morsel in c.items():
                            if morsel.value:
                                self._cookies[name] = morsel.value
                    except Exception:
                        pass
        except Exception:
            pass

    def _cookie_header(self):
        if not self._cookies:
            return None
        return '; '.join('%s=%s' % (k, v) for k, v in self._cookies.items())

    def _http(self, url, extra=None):
        """统一请求入口：失败/命中加载过渡页自动重试（等待 2/4/6 秒递增）"""
        waits = [2, 4, 6]
        html = ''
        for attempt in range(3):
            hd = dict(self.headers)
            ck = self._cookie_header()
            if ck:
                hd['Cookie'] = ck
            if extra:
                hd.update(extra)
            try:
                resp = self.fetch(url, headers=hd)
                self._absorb_cookies(resp)
                html = self._text(resp)
            except Exception as e:
                self.log('fetch error(第%d次):' % (attempt + 1), url, e)
                html = ''
            if html and not self._is_loading(html):
                break
            if html and self._is_loading(html):
                self.log('命中「加载中」过渡页，%d 秒后重试（已存 cookie: %s）'
                         % (waits[attempt], list(self._cookies)))
            try:
                import time
                time.sleep(waits[attempt])
            except Exception:
                pass
        return html

    def _full(self, u):
        if not u:
            return ''
        if u.startswith('http'):
            return u
        if u.startswith('//'):
            return 'https:' + u
        return self.host + (u if u.startswith('/') else '/' + u)

    # ------------------------------------------------------------------ 列表
    def _extract_list(self, html):
        """返回 [(vod_id, vod_name, vod_pic, vod_remarks)]，按 vod_id 去重保序

        卡片锚点必须带 title= 属性 —— 侧栏热搜锚点（class="hot"）没有 title，
        天然过滤掉，不用再圈定主列表容器。
        """
        items = []
        seen = set()

        def push(href, title, pic, remark):
            m = re.search(r'/sou/(\d+)\.html', href or '')
            if not m:
                return
            vid = m.group(1)
            if vid in seen:
                return
            seen.add(vid)
            items.append((m.group(0), (title or '').strip(),
                          self._full(pic), (remark or '').strip()))

        # 卡片锚点：href + title 两个属性都有（属性顺序无关）
        for m in re.finditer(
                r'<a[^>]*href="(/sou/\d+\.html)"[^>]*?title="([^"]*)"[^>]*?>', html):
            # 从该锚点向后取 1200 字符找 data-src 与 module-item-text
            seg = html[m.start():m.start() + 1200]
            pic = re.search(r'data-src="([^"]+)"', seg)
            # 副标题：卡片内的 module-item-text（取最近的，别越过下一张卡）
            nxt = html.find('<a', m.start() + 10)
            end = min(m.start() + 1200, nxt if nxt > 0 else m.start() + 1200)
            rk = re.search(r'module-item-text">\s*([^<]*?)\s*<', html[m.start():end])
            push(m.group(1), m.group(2), pic.group(1) if pic else '',
                 rk.group(1) if rk else '')
        return items

    def _page_url(self, path, pg):
        path = path if path.startswith('/') else '/' + path
        if pg <= 1:
            return self.host + path
        if path.endswith('.html'):
            return self.host + path[:-5] + '-%d.html' % pg
        return self.host + path.rstrip('/') + '-%d.html' % pg

    def homeContent(self, filter):
        classes = [{'type_name': name, 'type_id': path}
                   for name, path in self.categories.items()]
        return {'class': classes, 'filters': {}}

    def homeVideoContent(self):
        try:
            html = self._http(self.host + '/')
            videos = [{'vod_id': i[0], 'vod_name': i[1], 'vod_pic': i[2],
                       'vod_remarks': i[3]} for i in self._extract_list(html)]
            return {'list': videos[:30]}
        except Exception as e:
            self.log('homeVideoContent error:', e)
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)          # app 可能传字符串
        except Exception:
            pg = 1
        self._parse_extend(extend)
        try:
            path = tid or ''
            if path in self.categories:
                path = self.categories[path]           # 类别名 -> 路径
            elif re.search(r'/va/\d+', str(path)):
                path = re.search(r'/va/\d+(\.\d+)*', str(path)).group(0) + '.html'
            elif re.search(r'\d', str(path)):
                path = '/va/%s.html' % re.sub(r'\D', '', str(path))  # 纯数字 tid
            else:
                path = self.categories['电影']

            html = self._http(self._page_url(path, pg))
            videos = [{'vod_id': i[0], 'vod_name': i[1], 'vod_pic': i[2],
                       'vod_remarks': i[3]} for i in self._extract_list(html)]
            return {'list': videos, 'page': pg, 'pagecount': 9999,
                    'limit': 144, 'total': 999999}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 144, 'total': 0}

    # ------------------------------------------------------------------ 详情
    def _meta_links(self, html, label):
        """导演/主演：<span class="video-info-itemtitle">导演：</span>
           <div class="video-info-item video-info-actor">…<a>名字</a>…</div>"""
        m = re.search(r'video-info-itemtitle">\s*' + label + r'[：:]\s*</span>'
                      r'(.*?)</div>', html, re.S)
        if not m:
            return ''
        names = re.findall(r'<a[^>]*>\s*([^<>]+?)\s*</a>', m.group(1))
        return ','.join(dict.fromkeys(n.strip() for n in names if n.strip()))

    def _meta_plain(self, html, label):
        """备注/语言等：<span class="video-info-itemtitle">备注：</span>
           <div class="video-info-item">全36集</div>"""
        m = re.search(r'video-info-itemtitle">\s*' + label + r'[：:]\s*</span>\s*'
                      r'<div class="video-info-item"[^>]*>\s*([^<]*?)\s*<', html)
        return m.group(1).strip() if m else ''

    def detailContent(self, ids):
        try:
            one = ids[0] if isinstance(ids, (list, tuple)) else ids
            url = self._full(one)
            html = self._http(url)
            if not html:
                return {'list': []}

            title = ''
            m = re.search(r'<h1 class="page-title">\s*([^<]*?)\s*</h1>', html)
            if m:
                title = m.group(1).strip()
            if not title:
                m = re.search(r'<title>\s*《?(.*?)》?\s*[-_在线]', html)
                title = m.group(1).strip() if m else ''

            pic = ''
            m = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', html)
            if m:
                pic = m.group(1)
            if not pic:
                m = re.search(r'video-cover.*?data-src="([^"]+)"', html, re.S)
                if m:
                    pic = m.group(1)

            # 类型 / 年份 / 地区：video-info-aux 里的 tag 链接与外链参数
            vod_type = ''
            m = re.search(r'class="tag-link"[^>]*>\s*(?:<[^>]+>)*\s*([^<]+?)\s*</a>', html)
            if m:
                vod_type = m.group(1).strip()
            year = ''
            m = re.search(r'[?&]year=(\d{4})', html)
            if m:
                year = m.group(1)
            area = ''
            m = re.search(r'[?&]area=([^"&\'>]+)', html)
            if m:
                area = urllib.parse.unquote(m.group(1))

            content = ''
            m = re.search(r'video-info-itemtitle">\s*剧情[：:]\s*</span>\s*'
                          r'<div class="video-info-item video-info-content"[^>]*>'
                          r'(.*?)</div>', html, re.S)
            if m:
                content = re.sub(r'\s+', ' ', m.group(1)).strip()
            if not content:
                m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html)
                if m:
                    content = re.sub(r'\s+', ' ', m.group(1)).strip()
                    content = re.sub(r'^.*?剧情介绍[：:]?', '', content)

            # ---- 播放源：线路名 tab 顺序与 sort-item 剧集块顺序一一对应 ----
            names = re.findall(r'data-dropdown-value="([^"]+)"', html)
            blocks = re.split(r'<div class="sort-item">', html)[1:]
            play_from, play_url = [], []
            for i, body in enumerate(blocks):
                # 该块内只取同一条线路（第一个出现的 sid）的剧集
                sm = re.search(r'href="/play/\d+-(\d+)-\d+\.html"', body)
                if not sm:
                    continue
                sid = sm.group(1)
                eps = []
                for href, nm in re.findall(
                        r'<a[^>]*href="(/play/\d+-%s-\d+\.html)"[^>]*>\s*([^<]*?)\s*</a>'
                        % re.escape(sid), body):
                    nm = nm.strip() or '第%d集' % (len(eps) + 1)
                    eps.append('%s$%s' % (nm, self._full(href)))
                if eps:
                    nm = names[i] if i < len(names) else ('线路%d' % (i + 1))
                    play_from.append(nm)
                    play_url.append('#'.join(eps))

            video = {
                'vod_id': one,
                'vod_name': title,
                'vod_pic': self._full(pic),
                'vod_year': year,
                'vod_area': area,
                'vod_type': vod_type,
                'vod_actor': self._meta_links(html, '主演'),
                'vod_director': self._meta_links(html, '导演'),
                'vod_remarks': self._meta_plain(html, '备注') or self._meta_plain(html, '状态'),
                'vod_content': content,
                'vod_play_from': '$$$'.join(play_from) if play_from else 'VS影院',
                'vod_play_url': '$$$'.join(play_url) if play_url else '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    # ------------------------------------------------------------------ 搜索
    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        try:
            params = {'searchword': key}
            if pg > 1:
                params['page'] = pg
            url = self.host + self.search_path + '?' + urllib.parse.urlencode(params)
            html = self._http(url)
            videos = [{'vod_id': i[0], 'vod_name': i[1],
                       'vod_pic': i[2], 'vod_remarks': i[3]}
                      for i in self._extract_list(html)]
            return {'list': videos, 'page': pg}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg}

    # ------------------------------------------------------------------ 播放
    def playerContent(self, flag, id, vipFlags):
        try:
            url = self._full(id)
            play_url = ''
            html = self._http(url)
            # 播放页明文直链：var now="https://cdn.xxx/.../index.m3u8";
            m = re.search(r'var\s+now\s*=\s*"([^"]*)"', html)
            if m:
                play_url = m.group(1).strip()
            if not play_url:
                # 兜底：页内任意 m3u8/mp4
                m = re.search(r'(https?://[^"\'\s]+?\.m3u8[^"\'\s]*)', html)
                if not m:
                    m = re.search(r'(https?://[^"\'\s]+?\.mp4[^"\'\s]*)', html)
                if m:
                    play_url = m.group(1)
            parse = 0 if re.search(r'\.(m3u8|mp4|flv)(\?|$)', play_url) else 1
            if parse == 1:
                play_url = url       # 交给 TVBox 内置浏览器嗅探
            hd = dict(self.headers)
            hd['Referer'] = self.host + '/'
            return {'parse': parse, 'url': play_url, 'header': hd, 'flag': flag}
        except Exception as e:
            self.log('playerContent error:', e)
            hd = dict(self.headers)
            hd['Referer'] = self.host + '/'
            return {'parse': 1, 'url': id, 'header': hd}


def main():
    """本地测试块：python VS影院.py 直接运行"""
    sp = Spider()
    sp.init('')
    print('=== homeContent ===')
    r = sp.homeContent({})
    print('classes:', [c['type_name'] for c in r['class']])
    print()
    print('=== 分类列表 ===')
    for c in r['class']:
        r2 = sp.categoryContent(c['type_id'], 1, {}, {})
        print('  %-6s %-12s %d 项 %s' % (
            c['type_name'], c['type_id'], len(r2['list']),
            (r2['list'][0]['vod_name'] + ' / ' + r2['list'][0]['vod_remarks']) if r2['list'] else ''))
    print()
    first_tid = r['class'][0]['type_id']
    print('=== 翻页（第1页 vs 第2页）===')
    p1 = sp.categoryContent(first_tid, 1, {}, {})
    p2 = sp.categoryContent(first_tid, 2, {}, {})
    i1 = {v['vod_id'] for v in p1['list']}
    i2 = {v['vod_id'] for v in p2['list']}
    print('  p1=%d项 p2=%d项 交集=%d（应为0）' % (len(i1), len(i2), len(i1 & i2)))
    print()
    print('=== 兼容性：字符串 pg / 字符串 extend ===')
    print('  str pg:', len(sp.categoryContent(first_tid, '1', {}, {})['list']), '项')
    print('  str extend:', len(sp.categoryContent(first_tid, 1, {}, '{}')['list']), '项')
    print()
    print('=== detailContent ===')
    if p1['list']:
        v = sp.detailContent([p1['list'][0]['vod_id']])['list']
        if v:
            v = v[0]
            froms = v['vod_play_from'].split('$$$')
            urls = v['vod_play_url'].split('$$$')
            print('  name=%s | year=%s | area=%s | remarks=%s'
                  % (v['vod_name'], v['vod_year'], v['vod_area'], v['vod_remarks']))
            print('  导演=%s | 主演=%s' % (v['vod_director'][:30], v['vod_actor'][:40]))
            print('  简介=%s' % v['vod_content'][:60])
            print('  来源:', froms)
            for f, u in zip(froms, urls):
                eps = u.split('#')
                print('   %s -> %d 集, 首集: %s' % (f, len(eps), eps[0][:70]))
            print()
            print('=== playerContent ===')
            if urls and urls[0] and urls[0] != '#':
                pid = urls[0].split('#')[0].split('$', 1)[1]
                r4 = sp.playerContent(froms[0], pid, None)
                print('  parse=%s' % r4['parse'])
                print('  url=%s' % r4['url'][:120])
    print()
    print('=== searchContent ===')
    rs = sp.searchContent('康熙来了', False, 1)
    print('  结果数:', len(rs['list']), [x['vod_name'] for x in rs['list'][:5]])


if __name__ == '__main__':
    main()
