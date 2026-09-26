# -*- coding: utf-8 -*-
"""
VS影院  TVBox Python Spider（影视仓 / OK影视）
站点：https://m.ytshengde.com/   （MacCMS v10 + myui 模板，模板目录 /template/vssanyi/）

实测结构（2026-09-26 用移动端 UA + curl 探测确认）：
  · 首页/分类列表：/sanyitp/{id}.html      第 N 页：/sanyitp/{id}-{N}.html
  · 详情页：      /sanyidt/{id}.html
  · 播放页：      /sanyipy/{id}-{sid}-{eid}.html（页面内含 var player_aaaa={...}，url 为真实 m3u8）
  · 列表项：      <div class="myui-vodlist__box">
                    <a class="myui-vodlist__thumb lazyload" rel="nofollow"
                       href="/sanyidt/{id}.html" title="片名" data-original="/upload/...jpg">
                       <span class="pic-text text-right">全10集</span></a>
                  ※ 注意：真实 class 里**没有** wide（是 "myui-vodlist__thumb lazyload"），
                    且 data-original 挂在 <a> 上而不是 <img> 上。
  · 播放源 tabs：<ul class="nav nav-tabs active"><li><a href="#playlist1" data-toggle="tab">无尽</a>…</ul>
    播放列表：  <div id="playlist1" class="tab-pane fade in clearfix">
                  <ul class="myui-content__list sort-list clearfix">
                    <li><a class="btn btn-default" href="/sanyipy/288624-1-1.html">第01集</a></li>…
    每个 playlist 块里还夹着一条站方 APP 引流链（//app2.zstv47.com…），按 href 前缀 /sanyipy/ 过滤。

反爬（重要）：
  · 站点前置 __xcdn 前置 CDN 的人机校验：触发时返回 408 + "<title>Bot detection</title>"。
    校验是**纯工作量证明**、无需看图：
        GET  /__xcdn/captcha/api/init                 -> {"challenge":"…","difficulty":4}
        解   sha256(challenge + str(nonce)).hexdigest() 前 difficulty 位为 '0'
        GET  /__xcdn/captcha/api/verify
             headers: X-CDN-VERIFY-NONCE=<nonce>, X-CDN-VERIFY-RESULT=<hash>
        成功后下发 cookie __xcdn_captcha_verified，并有一段时间的免验证窗口。
    本源已内置该 PoW 自动破解（纯 hashlib，难度 4 时 <0.1s），遇到校验页自动解一次再重试。
  · 站内搜索带图形验证码（MacCMS 后台开启了搜索验证），命中时返回"系统安全验证"页，
    程序无法自动过图形码 —— searchContent 会正常尝试，拿不到结果就返回空列表（不会报错）。
"""
import sys
import os
import re
import json
import base64
import hashlib
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
                resp = e          # 408 / 403 等也把 body 交出去，交给上层判断
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
        self.host = 'https://m.ytshengde.com'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        # type_id 直接用真实路径，翻页时把 '.html' 换成 '-{pg}.html'
        self.categories = {
            '电影': '/sanyitp/1.html',
            '电视剧': '/sanyitp/2.html',
            '综艺': '/sanyitp/3.html',
            '动漫': '/sanyitp/4.html',
            '短剧': '/sanyitp/5.html',
            '大陆综艺': '/sanyitp/23.html',
            '日韩综艺': '/sanyitp/24.html',
            '欧美综艺': '/sanyitp/25.html',
            '港台综艺': '/sanyitp/26.html',
            '国产动漫': '/sanyitp/27.html',
            '日韩动漫': '/sanyitp/28.html',
            '欧美动漫': '/sanyitp/29.html',
            '其他动漫': '/sanyitp/30.html',
        }
        self.search_path = '/sanyisc/-------------.html'
        self._xcdn_done = False
        self._img = '/template/vssanyi/statics/img/load.gif'

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

    # ------------------------------------------------------- __xcdn 人机校验
    def _is_challenge(self, html):
        return ('xcdn-captcha' in html) or ('Bot detection' in html)

    def _xcdn_solve(self):
        """纯哈希工作量证明，无第三方依赖；成功则把 cookie 写回 self.headers"""
        try:
            resp = self.fetch(self.host + '/__xcdn/captcha/api/init', headers=self.headers)
            txt = self._text(resp)
            if not txt.lstrip().startswith('{'):
                return False                      # 没拿到 challenge（当前处于免验证窗口）
            data = json.loads(txt)
            challenge = data.get('challenge') or ''
            if not challenge:
                return False
            diff = int(data.get('difficulty') or 4)
            target = '0' * diff
            nonce = 0
            while True:
                nonce += 1
                hashv = hashlib.sha256((challenge + str(nonce)).encode('utf-8')).hexdigest()
                if hashv.startswith(target):
                    break
                if nonce > 50000000:      # 兜底，避免死循环
                    return False
            hd = dict(self.headers)
            hd['X-CDN-VERIFY-NONCE'] = str(nonce)
            hd['X-CDN-VERIFY-RESULT'] = hashv
            vresp = self.fetch(self.host + '/__xcdn/captcha/api/verify', headers=hd)
            sc = ''
            try:
                sc = vresp.headers.get('Set-Cookie') or vresp.headers.get('set-cookie') or ''
            except Exception:
                sc = ''
            if sc:
                self.headers['Cookie'] = sc.split(';')[0]
            self.log('__xcdn 校验通过, difficulty=%d nonce=%d cookie=%s'
                     % (diff, nonce, 'yes' if sc else 'no'))
            return True
        except Exception as e:
            self.log('__xcdn solve error:', e)
            return False

    def _http(self, url, extra=None):
        """统一请求入口：超时重试 + 命中 __xcdn 校验页自动破一次再重试"""
        hd = dict(self.headers)
        if extra:
            hd.update(extra)
        html = ''
        for attempt in range(3):
            try:
                html = self._text(self.fetch(url, headers=hd))
            except Exception as e:
                self.log('fetch error(第%d次):' % (attempt + 1), url, e)
                html = ''
            if html:
                break
            try:
                import time
                time.sleep(1)
            except Exception:
                pass
        if self._is_challenge(html):
            self.log('触发 __xcdn 校验，尝试自动破解')
            if self._xcdn_solve():
                self._xcdn_done = True
                hd2 = dict(self.headers)
                if extra:
                    hd2.update(extra)
                for attempt in range(2):
                    try:
                        html = self._text(self.fetch(url, headers=hd2))
                    except Exception as e:
                        self.log('refetch error:', e)
                        html = ''
                    if html and not self._is_challenge(html):
                        break
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
        """返回 [(vod_id, vod_name, vod_pic, vod_remarks)]，按 vod_id 去重保序"""
        items = []
        seen = set()

        def push(href, title, pic, remark):
            m = re.search(r'/sanyidt/(\d+)\.html', href or '')
            if not m:
                return
            vid = m.group(1)
            if vid in seen:
                return
            seen.add(vid)
            items.append((m.group(0), (title or '').strip(),
                          self._full(pic), (remark or '').strip()))

        # 优先只看主列表容器 <ul class="myui-vodlist clearfix">…</ul>，避免把侧栏推荐混进来
        scopes = []
        m = re.search(r'<ul class="myui-vodlist clearfix">', html)
        if m:
            e = html.find('</ul>', m.start())
            if e > m.start():
                scopes.append(html[m.start():e])
        scopes.append(html)

        for src in scopes:
            # 主正则：列表中每个合子的海报锚点（data-original 挂在 <a> 上）
            for m in re.finditer(
                    r'<a class="myui-vodlist__thumb[^"]*"[^>]*?href="(/sanyidt/\d+\.html)"'
                    r'[^>]*?title="([^"]*)"[^>]*?data-original="([^"]*)"[^>]*?>(.*?)</a>',
                    src, re.S):
                rk = re.search(r'pic-text[^>]*>\s*([^<]*?)\s*<', m.group(4))
                push(m.group(1), m.group(2), m.group(3), rk.group(1) if rk else '')

            # 兜底：属性顺序无关，按锚点逐块提取
            if not items:
                for m in re.finditer(r'<a class="myui-vodlist__thumb', src):
                    seg = src[m.start():m.start() + 1200]
                    a = re.search(r'href="(/sanyidt/\d+\.html)"', seg)
                    if not a:
                        continue
                    t = re.search(r'title="([^"]*)"', seg)
                    p = re.search(r'data-original="([^"]*)"', seg)
                    rk = re.search(r'pic-text[^>]*>\s*([^<]*?)\s*<', seg)
                    push(a.group(1), t.group(1) if t else '', p.group(1) if p else '',
                         rk.group(1) if rk else '')
            if items:
                break
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
            html = self._http(self._page_url(self.categories['电影'], 1))
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
        extend = self._parse_extend(extend)
        try:
            path = tid or ''
            if path in self.categories:
                path = self.categories[path]           # 类别名 -> 路径
            elif path in self.categories.values():
                pass                                   # 已是分类路径
            elif re.search(r'/sanyitp/\d+\.html', str(path)):
                path = re.search(r'(/sanyitp/\d+)\.html', str(path)).group(1) + '.html'
            elif re.search(r'\d', str(path)):
                path = '/sanyitp/%s.html' % re.sub(r'\D', '', str(path))  # 纯数字 tid
            else:
                path = self.categories['电影']

            html = self._http(self._page_url(path, pg))
            videos = [{'vod_id': i[0], 'vod_name': i[1], 'vod_pic': i[2],
                       'vod_remarks': i[3]} for i in self._extract_list(html)]
            return {'list': videos, 'page': pg, 'pagecount': 9999,
                    'limit': 20, 'total': 999999}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 20, 'total': 0}

    # ------------------------------------------------------------------ 详情
    def _meta(self, html, label):
        """取 <span>地区：</span><a …>美国</a> 或 <span>导演：</span>未知</p> 两种写法"""
        m = re.search(label + r'[：:]\s*</span>\s*<a[^>]*>\s*([^<]*?)\s*</a>', html)
        if m and m.group(1).strip():
            return m.group(1).strip()
        m = re.search(label + r'[：:]\s*</span>\s*([^<>]{1,40}?)\s*<', html)
        return m.group(1).strip() if m else ''

    def detailContent(self, ids):
        try:
            one = ids[0] if isinstance(ids, (list, tuple)) else ids
            url = self._full(one)
            html = self._http(url)
            if not html:
                return {'list': []}

            title = ''
            m = re.search(r'<h1 class="title">\s*([^<]*?)\s*</h1>', html)
            if m:
                title = m.group(1)
            if not title:
                m = re.search(r'<title>\s*《?(.*?)》?\s*[-_|]', html)
                title = m.group(1).strip() if m else ''

            pic = ''
            m = re.search(r'myui-content__thumb.*?data-original="([^"]+)"', html, re.S)
            if m:
                pic = m.group(1)
            if not pic:
                m = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', html)
                pic = m.group(1) if m else ''

            remarks = ''
            m = re.search(r'myui-content__thumb.*?pic-text[^>]*>\s*([^<]*?)\s*<', html, re.S)
            if m:
                remarks = m.group(1)

            actor = ''
            m = re.search(r'主演[：:]\s*</span>(.*?)</p>', html, re.S)
            if m:
                actor = re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', m.group(1))).strip('&nbsp;')

            content = ''
            m = re.search(r"Layer\.Text\('剧情简介','(.*?)'", html, re.S)
            if not m:
                m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html)
            if m:
                content = re.sub(r'&nbsp;|\s+', ' ', m.group(1)).strip()
                content = (content.replace('剧情介绍：', '').replace('&amp;', '&')).strip()

            # ---- 播放源（tabs 顺序 = playlistN 顺序）----
            names = {}
            for sid, nm in re.findall(r'href="#playlist(\d+)"[^>]*>\s*([^<]*?)\s*</a>', html):
                names[sid] = nm or ('线路' + sid)

            play_from, play_url = [], []
            parts = re.split(r'<div id="playlist(\d+)"', html)
            # parts = [前置, sid1, body1, sid2, body2, ...]
            for i in range(1, len(parts) - 1, 2):
                sid, body = parts[i], parts[i + 1]
                eps = []
                for href, nm in re.findall(
                        r'<a[^>]*href="(/sanyipy/\d+-\d+-\d+\.html)"[^>]*>\s*([^<]*?)\s*</a>', body):
                    nm = nm.strip() or '第%d集' % (len(eps) + 1)
                    eps.append('%s$%s' % (nm, self._full(href)))
                if eps:
                    play_from.append(names.get(sid, '线路' + sid))
                    play_url.append('#'.join(eps))

            # 兜底：详情页结构变化时，按 /sanyipy/ 链接的 sid 分组
            if not play_url:
                groups = {}
                for m2 in re.finditer(
                        r'<a[^>]*href="(/sanyipy/\d+-(\d+)-\d+\.html)"[^>]*>\s*([^<]*?)\s*</a>', html):
                    groups.setdefault(m2.group(2), []).append(
                        '%s$%s' % (m2.group(3).strip(), self._full(m2.group(1))))
                for sid in sorted(groups, key=lambda x: int(x)):
                    play_from.append(names.get(sid, '线路' + sid))
                    play_url.append('#'.join(groups[sid]))

            video = {
                'vod_id': one,
                'vod_name': title,
                'vod_pic': self._full(pic),
                'vod_year': self._meta(html, '年份'),
                'vod_area': self._meta(html, '地区'),
                'vod_actor': actor,
                'vod_director': self._meta(html, '导演'),
                'vod_remarks': remarks,
                'vod_content': content,
                'vod_play_from': '$$$'.join(play_from) if play_from else 'VS影院',
                'vod_play_url': '$$$'.join(play_url) if play_url else '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    # ------------------------------------------------------------------ 搜索
    def _search_post(self, path, params, marker):
        """POST 搜索兼容写法：data 传 str、显式 Content-Type、手动跟随 302"""
        headers = dict(self.headers)
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        data = urllib.parse.urlencode(params)
        html = ''
        try:
            resp = self.fetch(self.host + path, headers=headers, data=data)
            html = self._text(resp)
        except Exception:
            html = ''
        if marker not in html:
            loc = ''
            try:
                loc = resp.headers.get('Location') or resp.headers.get('location') or ''
            except Exception:
                loc = ''
            if loc:
                html = self._http(self._full(loc))
        return html

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        try:
            kw = urllib.parse.quote(key)
            videos = []
            # 站方启用了搜索图形验证码：正常搜索优先，命中验证页则返回空列表（不报错）
            url = '%s%s?wd=%s' % (self.host, self.search_path, kw)
            if pg > 1:
                url += '&page=%d' % pg
            html = self._http(url)
            if html and '系统安全验证' in html:
                self.log('搜索被图形验证码拦截（MacCMS 搜索验证已开启），返回空列表')
                return {'list': [], 'page': pg}
            for i in self._extract_list(html):
                videos.append({'vod_id': i[0], 'vod_name': i[1],
                               'vod_pic': i[2], 'vod_remarks': i[3]})
            if not videos and pg == 1:
                # 兜底：POST 方式再试一次
                html = self._search_post(self.search_path, {'wd': key}, '/sanyidt/')
                for i in self._extract_list(html):
                    videos.append({'vod_id': i[0], 'vod_name': i[1],
                                   'vod_pic': i[2], 'vod_remarks': i[3]})
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
            m = re.search(r'player_aaaa\s*=\s*(\{.*?\})\s*</script>', html, re.S)
            if not m:
                m = re.search(r'player_aaaa\s*=\s*(\{.*\})', html, re.S)
            if m:
                try:
                    data = json.loads(m.group(1))
                except Exception:
                    data = {}
                play_url = (data.get('url') or '').strip()
                if play_url and str(data.get('encrypt')) == '1':
                    try:
                        play_url = base64.b64decode(
                            play_url + '=' * (-len(play_url) % 4)).decode('utf-8', 'replace')
                    except Exception:
                        pass
            if not play_url:
                play_url = url
            parse = 0 if re.search(r'\.(m3u8|mp4|flv)(\?|$)', play_url) else 1
            return {'parse': parse, 'url': play_url,
                    'header': dict(self.headers), 'flag': flag}
        except Exception as e:
            self.log('playerContent error:', e)
            return {'parse': 1, 'url': id, 'header': dict(self.headers)}


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
        print('  %-8s %-22s %d 项 %s' % (
            c['type_name'], c['type_id'], len(r2['list']),
            (r2['list'][0]['vod_name'] + ' / ' + r2['list'][0]['vod_remarks']) if r2['list'] else ''))
    print()
    first_tid = r['class'][0]['type_id']
    print('=== 翻页（第1页 vs 第2页）===')
    p1 = sp.categoryContent(first_tid, 1, {}, {})
    p2 = sp.categoryContent(first_tid, 2, {}, {})
    print('  p1 first:', p1['list'][0]['vod_id'] if p1['list'] else None)
    print('  p2 first:', p2['list'][0]['vod_id'] if p2['list'] else None)
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
    rs = sp.searchContent('庆余年', False, 1)
    print('  结果数:', len(rs['list']), [x['vod_name'] for x in rs['list'][:5]])


if __name__ == '__main__':
    main()
