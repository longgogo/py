# -*- coding: utf-8 -*-
"""
简云影视（301 -> 极速追剧 jisuzhuiju.com）TVBox / 影视仓 / OK影视 Python 源
实测站点：https://jisuzhuiju.com  （原域名 jianyunys.com 会 301 跳到这里）

站点真实结构（2026-09-26 用移动端 UA + --compressed 实测）：
  host            https://jisuzhuiju.com
  首页列表        <a href="/detail/{id}.html" class="text-decoration-none">
                    <div class="vod-card"><div class="vod-cover"><img src="...">
                    <div class="vod-card-info"><p class="vod-title">名</p>
                    <p class="vod-subtitle">演员</p>
  分类（有翻页）  /filter?channel={1..5}&type=&area=&year=&sort=hot&page={n}
                  channel: 1=电视剧 2=电影 3=动漫 4=综艺 5=短剧（6 为幽灵频道，0 条）
  详情            /detail/{id}.html  —— 页面内 JSON-LD（TVSeries/Movie）含
                  简介/海报/年份/主演/导演/评分/集数，详情页还有 .detail-meta-grid
  线路与剧集      <button class="source-tab" data-target="source-{i}">线路名</button>
                  <div class="source-panel" id="source-{i}">
                    <a href="/vodplay/{id}-{key}-{ep}.html" class="episode-btn">第N集</a>
  真实播放地址    /api/play-url?vodId={id}&playFrom={key}&index={ep}   （index 从 1 开始！）
                  返回 {"mode":"native|iframe","code":200,"url":"...m3u8..."}
  搜索            /search?keyword={kw}&page={n}&sort=hits   （关键词需 >=2 字，单字恒 0 条）
                  <div class="search-item"><a href="/detail/{id}.html" class="search-item-poster">
                  <img src><a ... class="search-item-title">名</a>
"""
import sys, os, re, json, urllib.parse

# ---- base Spider 导入：app 内有 base.spider，本地测试走 fallback ----
try:
    from base.spider import Spider
except Exception:
    class Spider:
        def __init__(self):
            self.headers = {}

        def fetch(self, url, headers=None, data=None, method='GET', timeout=15, **kwargs):
            """本地 fallback：**kwargs 用于吞掉 app 侧专有参数（allow_redirects / verify 等）"""
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
            # 中文站必须 utf-8，errors='replace' 防止个别脏字节炸掉整页
            r.text = body.decode('utf-8', 'replace')
            r.content = body
            r.status_code = getattr(resp, 'status', 200)
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
        return '简云影视'

    def log(self, *args):
        # 安全日志：子类自带实现，绝不依赖 base Spider 的 log
        print('[简云影视]', *args)

    def init(self, extend=''):
        # 站点 301 到 jisuzhuiju.com，host 直接用最终域名，省掉一次跳转
        self.host = 'https://jisuzhuiju.com'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            # 反盗链站点必须带 Referer，播放时随 header 一起返回
            'Referer': self.host + '/',
        }
        # 分类 tid 直接用 channel 号（值为 '1'..'5'），categoryContent 里拼 /filter
        self.categories = {
            '电视剧': '1',
            '电影': '2',
            '动漫': '3',
            '综艺': '4',
            '短剧': '5',
        }
        # 筛选维度：key 直接就是 query 参数名（type/area/year/sort），extend 可原样拼进 URL
        self.areas = ['', '大陆', '香港', '台湾', '韩国', '日本', '美国', '泰国',
                      '法国', '英国', '德国', '印度', '其他']
        self.years = ['', '2026', '2025', '2024', '2023', '2022', '2021', '2020',
                      '2019', '2018', '-1']
        self.sort_ = [('热度排序', 'hot'), ('上映时间', 'time'), ('评分排序', 'score')]
        # 各频道 type 取值（逐个 curl 抓 /filter?channel=N 页面提取，channel 5 无 type 维度）
        self.types = {
            '1': [('剧情', '7'), ('古装', '9'), ('战争', '10'), ('谍战', '11'), ('爱情', '12'),
                  ('罪案', '13'), ('悬疑', '14'), ('家庭', '15'), ('军旅', '16'), ('喜剧', '17'),
                  ('都市', '18'), ('武侠', '19'), ('言情', '20'), ('偶像', '21'), ('青春', '22'),
                  ('农村', '23'), ('穿越', '24'), ('奇幻', '25'), ('历史', '26'), ('年代', '27'),
                  ('科幻', '28'), ('生活', '29'), ('励志', '31'), ('婚姻', '32'), ('警匪', '33'),
                  ('犯罪', '34'), ('推理', '35'), ('商战', '36'), ('宫廷', '37'), ('仙侠', '38'),
                  ('神话', '39'), ('动作', '40'), ('复仇', '41'), ('惊悚', '42')],
            '2': [('动作', '43'), ('喜剧', '44'), ('爱情', '45'), ('科幻', '46'), ('恐怖', '47'),
                  ('剧情', '48'), ('战争', '49'), ('犯罪', '50'), ('惊悚', '51'), ('冒险', '52'),
                  ('悬疑', '53'), ('动画', '54'), ('武侠', '55'), ('古装', '56'), ('历史', '57'),
                  ('传记', '58'), ('纪录片', '59')],
            '3': [('热血', '60'), ('恋爱', '61'), ('校园', '62'), ('搞笑', '63'), ('机甲', '64'),
                  ('神魔', '65'), ('竞技', '66'), ('冒险', '67'), ('治愈', '68'), ('百合', '69'),
                  ('萝莉', '70'), ('后宫', '71'), ('励志', '72'), ('泡面番', '73'),
                  ('国产动漫', '74'), ('日本动漫', '75'), ('欧美动漫', '76')],
            '4': [('选秀', '77'), ('情感', '78'), ('访谈', '79'), ('播报', '80'), ('旅游', '81'),
                  ('音乐', '82'), ('美食', '83'), ('纪实', '84'), ('曲艺', '85'), ('游戏', '86'),
                  ('亲子', '87'), ('职场', '88'), ('脱口秀', '89'), ('真人秀', '90'), ('晚会', '91')],
            '5': [],
        }

    def isVideoFormat(self, url):
        return bool(re.match(r'https?://.+\.(m3u8|mp4)', url or ''))

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

    # ---------------- 列表页解析 ----------------

    def _extract_list(self, html):
        """首页/分类页统一卡片结构：
        <a href="/detail/{id}.html" class="text-decoration-none"><div class="vod-card">
        <div class="vod-cover"><img src="...">[<span class="vod-badge">全30集</span>]
        <div class="vod-card-info"><p class="vod-title">名</p><p class="vod-subtitle">演员</p>
        返回 (vid, name, pic, remark) 四元组列表。
        """
        items = []
        marks = list(re.finditer(
            r'<a href="/detail/(\d+)\.html"[^>]*class="text-decoration-none"', html))
        if marks:
            for i, m in enumerate(marks):
                end = marks[i + 1].start() if i + 1 < len(marks) else min(len(html), m.start() + 2500)
                seg = html[m.start():end]
                pic = re.search(r'<img[^>]*src="([^"]+)"', seg)
                name = re.search(r'<p class="vod-title[^"]*">(.*?)</p>', seg, re.S)
                sub = re.search(r'<p class="vod-subtitle[^"]*">(.*?)</p>', seg, re.S)
                badge = re.search(r'<span class="vod-badge[^"]*">([^<]*)</span>', seg)
                items.append((
                    '/detail/%s.html' % m.group(1),
                    re.sub(r'<[^>]+>', '', name.group(1)).strip() if name else '',
                    pic.group(1) if pic else '',
                    (badge.group(1).strip() if badge else
                     (re.sub(r'<[^>]+>', '', sub.group(1)).strip() if sub else '')),
                ))
            return items
        # 兜底：属性顺序无关，逐块提取
        marks = list(re.finditer(r'href="/detail/(\d+)\.html"', html))
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else min(len(html), m.start() + 2500)
            seg = html[m.start():end]
            pic = re.search(r'<img[^>]*src="([^"]+)"', seg)
            name = re.search(r'<p class="vod-title[^"]*">(.*?)</p>', seg, re.S)
            items.append((
                '/detail/%s.html' % m.group(1),
                re.sub(r'<[^>]+>', '', name.group(1)).strip() if name else '',
                pic.group(1) if pic else '',
                '',
            ))
        return items

    def _to_videos(self, html):
        videos = []
        seen = set()
        for vid, name, pic, remark in self._extract_list(html):
            if vid in seen:
                continue
            seen.add(vid)
            videos.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic,
                'vod_remarks': remark,
            })
        return videos

    # ---------------- 标准接口 ----------------

    def homeContent(self, filter):
        try:
            classes = [{'type_name': name, 'type_id': tid}
                       for name, tid in self.categories.items()]
        except Exception as e:
            self.log('homeContent error:', e)
            classes = []
        # 有筛选时构造 filters：{type_id: [{'key','name','value':[{'n','v'}]}]}
        filters = {}
        try:
            for name, tid in self.categories.items():
                groups = []
                tps = self.types.get(tid) or []
                if tps:
                    groups.append({
                        'key': 'type', 'name': '类型',
                        'value': [{'n': '全部', 'v': ''}] +
                                 [{'n': n, 'v': v} for n, v in tps],
                    })
                groups.append({
                    'key': 'area', 'name': '地区',
                    'value': [{'n': n if n else '全部', 'v': v} for n, v in
                              [('', ''), ('大陆', '大陆'), ('香港', '香港'), ('台湾', '台湾'),
                               ('韩国', '韩国'), ('日本', '日本'), ('美国', '美国'),
                               ('泰国', '泰国'), ('法国', '法国'), ('英国', '英国'),
                               ('德国', '德国'), ('印度', '印度'), ('其他', '其他')]],
                })
                groups.append({
                    'key': 'year', 'name': '年份',
                    'value': [{'n': n if n else '全部', 'v': v} for n, v in
                              [('', '')] + [(y, y) for y in self.years[1:-1]] + [('其他', '-1')]],
                })
                groups.append({
                    'key': 'sort', 'name': '排序',
                    'value': [{'n': n, 'v': v} for n, v in self.sort_],
                })
                filters[tid] = groups
        except Exception as e:
            self.log('homeContent filters error:', e)
        return {'class': classes, 'filters': filters}

    def homeVideoContent(self):
        try:
            html = self.fetch(self.host + '/', headers=self.headers).text
            return {'list': self._to_videos(html)}
        except Exception as e:
            self.log('homeVideoContent error:', e)
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)  # app 可能传字符串
        except Exception:
            pg = 1
        extend = self._parse_extend(extend)
        try:
            tid = str(tid)
            if tid in self.categories:
                tid = self.categories[tid]
            if not tid.isdigit():
                m = re.search(r'channel=(\d+)', tid)
                tid = m.group(1) if m else '1'
            # 真实格式是 query 式：/filter?channel=N&type=&area=&year=&sort=hot&page=K
            params = {
                'channel': tid,
                'type': str(extend.get('type') or ''),
                'area': str(extend.get('area') or ''),
                'year': str(extend.get('year') or ''),
                'sort': str(extend.get('sort') or 'hot'),
                'page': str(pg),
            }
            url = self.host + '/filter?' + urllib.parse.urlencode(params)
            html = self.fetch(url, headers=self.headers).text
            videos = self._to_videos(html)
            # 页面里能读到总条数：共 <em>4438</em> 条 / 个结果
            total_pages = 9999
            n = re.search(r'共\s*<?[^>]*>?\s*(\d+)', html)
            if n:
                try:
                    total_pages = max(1, (int(n.group(1)) + 11) // 12)  # 每页 12 条
                except Exception:
                    pass
            if pg > total_pages:
                videos = []
            return {'list': videos, 'page': pg, 'pagecount': total_pages,
                    'limit': 12, 'total': total_pages * 12}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 12, 'total': 0}

    # ---------------- 详情 ----------------

    def _parse_meta_grid(self, html):
        """详情页 .detail-meta-grid > .meta-item(.meta-label/.meta-value)"""
        meta = {}
        for m in re.finditer(
                r'<div class="meta-item">\s*<span class="meta-label">(.*?)</span>\s*'
                r'<span class="meta-value">(.*?)</span>', html, re.S):
            k = re.sub(r'<[^>]+>', '', m.group(1)).replace('：', '').strip()
            v = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if k:
                meta[k] = v
        return meta

    def _parse_plays(self, html, vod_id):
        """解析线路 tabs + 面板剧集。
        返回 (play_from_list, play_url_list)，顺序与 tabs 一致。
        """
        tabs = re.findall(
            r'<button class="source-tab[^"]*"[^>]*data-target="(source-\d+)"[^>]*>(.*?)</button>',
            html, re.S)
        tabname = {}
        order = []
        for pid, name in tabs:
            tabname[pid] = re.sub(r'<[^>]+>', '', name).strip()
            order.append(pid)

        panels = {}
        parts = re.split(r'<div class="source-panel"', html)[1:]
        for part in parts:
            pid_m = re.search(r'id="(source-\d+)"', part)
            if not pid_m:
                continue
            pid = pid_m.group(1)
            eps = []
            for m in re.finditer(r'<a href="(/vodplay/[^"]+\.html)"[^>]*>(.*?)</a>', part, re.S):
                eps.append((re.sub(r'<[^>]+>', '', m.group(2)).strip() or '播放',
                            m.group(1)))
            if eps:
                panels[pid] = eps

        froms, urls = [], []
        for pid in order:
            eps = panels.get(pid)
            if not eps:
                continue
            froms.append(tabname.get(pid) or pid)
            # 同一来源内部：集名$地址，集与集之间用 '#'
            urls.append('#'.join('%s$%s' % (n, u) for n, u in eps))

        if froms:
            return froms, urls

        # 兜底：页面没给面板结构时，按 /vodplay/{id}-{key}-{ep}.html 的 key 分组
        groups = {}
        gorder = []
        for m in re.finditer(r'<a href="/vodplay/%s-([A-Za-z0-9_]+)-(\d+)\.html"[^>]*>(.*?)</a>'
                             % re.escape(str(vod_id)), html, re.S):
            key, ep, name = m.group(1), int(m.group(2)), re.sub(r'<[^>]+>', '', m.group(3)).strip()
            if key not in groups:
                groups[key] = {}
                gorder.append(key)
            groups[key][ep] = (name or ('第%d集' % ep),
                               '/vodplay/%s-%s-%d.html' % (vod_id, key, ep))
        for key in gorder:
            eps = [groups[key][e] for e in sorted(groups[key])]
            froms.append(key)
            urls.append('#'.join('%s$%s' % (n, u) for n, u in eps))
        return froms, urls

    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
            vid = str(vid)
            url = vid if vid.startswith('http') else self.host + vid
            html = self.fetch(url, headers=self.headers).text

            # JSON-LD 结构化数据：详情页最可靠的元数据来源
            name = pic = content = year = actor = director = area = ''
            remark = ''
            rating = ''
            for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
                try:
                    d = json.loads(m.group(1))
                except Exception:
                    continue
                for node in (d.get('@graph') or [d]):
                    if not isinstance(node, dict):
                        continue
                    if node.get('@type') in ('TVSeries', 'Movie', 'TVShow', 'VideoObject'):
                        name = node.get('name') or name
                        pic = node.get('image') or node.get('thumbnailUrl') or pic
                        content = content or (node.get('description') or '')
                        year = str(node.get('datePublished') or '') or year
                        actor = node.get('actor') or actor
                        director = node.get('director') or director
                        g = node.get('genre')
                        if isinstance(g, list):
                            g = ','.join([str(x) for x in g])
                        area = g or area
                        rat = node.get('aggregateRating') or {}
                        rating = str(rat.get('ratingValue') or '') or rating
            # 正文兜底
            if not name:
                t = re.search(r'<h1 class="detail-title">(.*?)</h1>', html, re.S)
                if t:
                    name = re.sub(r'<[^>]+>', '', t.group(1)).strip()
            if not pic:
                p = re.search(r'class="detail-poster-wrapper">\s*<img[^>]*src="([^"]+)"', html)
                if p:
                    pic = p.group(1)

            meta = self._parse_meta_grid(html)
            actor = actor or meta.get('主演', '')
            director = director or meta.get('导演', '')
            area = meta.get('地区', '') or area
            year = year or meta.get('年份', '')
            remark = meta.get('备注', '')

            vod_id = vid
            m = re.search(r'/detail/(\d+)\.html', vid)
            if m:
                vod_id = '/detail/%s.html' % m.group(1)

            play_from, play_url = self._parse_plays(html, m.group(1) if m else vod_id)

            video = {
                'vod_id': vod_id,
                'vod_name': name,
                'vod_pic': pic,
                'vod_year': year,
                'vod_area': area,
                'vod_actor': actor,
                'vod_director': director,
                'vod_remarks': remark or (('评分%s' % rating) if rating else ''),
                'vod_content': content,
                'vod_play_from': '$$$'.join(play_from) if play_from else '极速追剧',
                'vod_play_url': '$$$'.join(play_url) if play_url else '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    # ---------------- 搜索 ----------------

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        try:
            # 真实搜索端点（来自首页 JSON-LD 的 SearchAction urlTemplate）：
            # /search?keyword={kw}  实测支持 &page= &sort=hits|year，GET 即可
            url = self.host + '/search?' + urllib.parse.urlencode(
                {'keyword': key, 'page': str(pg), 'sort': 'hits'})
            html = self.fetch(url, headers=self.headers).text
            videos = []
            seen = set()
            for block in html.split('<div class="search-item">')[1:]:
                h = re.search(r'<a href="(/detail/\d+\.html)"[^>]*class="search-item-title[^"]*"[^>]*>(.*?)</a>',
                              block, re.S)
                if not h:
                    h = re.search(r'<a href="(/detail/\d+\.html)"[^>]*>(.*?)</a>', block, re.S)
                if not h:
                    continue
                vid = h.group(1)
                if vid in seen:
                    continue
                seen.add(vid)
                pic = re.search(r'<img[^>]*src="([^"]+)"', block)
                ttype = re.search(r'<span class="search-item-type">(.*?)</span>', block, re.S)
                videos.append({
                    'vod_id': vid,
                    'vod_name': re.sub(r'<[^>]+>', '', h.group(2)).strip(),
                    'vod_pic': pic.group(1) if pic else '',
                    'vod_remarks': re.sub(r'<[^>]+>', '', ttype.group(1)).strip() if ttype else '',
                })
            # 兜底：整页顺序无关提取（标题高亮标签需清理）
            if not videos:
                for m in re.finditer(r'<a href="(/detail/\d+\.html)"[^>]*class="search-item-title[^"]*"[^>]*>(.*?)</a>',
                                     html, re.S):
                    if m.group(1) in seen:
                        continue
                    seen.add(m.group(1))
                    videos.append({
                        'vod_id': m.group(1),
                        'vod_name': re.sub(r'<[^>]+>', '', m.group(2)).strip(),
                        'vod_pic': '',
                        'vod_remarks': '',
                    })
            total_pages = pg
            n = re.search(r'共\s*<em>(\d+)</em>\s*个结果', html)
            if n and videos:
                try:
                    total_pages = max(pg, (int(n.group(1)) + 11) // 12)
                except Exception:
                    total_pages = pg
            return {'list': videos, 'page': pg, 'pagecount': total_pages if videos else pg}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg}

    # ---------------- 播放 ----------------

    def playerContent(self, flag, id, vipFlags):
        """id 形如 /vodplay/638-qiyi-1.html，需再请求 /api/play-url 换真实地址。"""
        try:
            id = str(id)
            headers = dict(self.headers)
            # 已经是直链
            if id.startswith('http') and self.isVideoFormat(id):
                return {'parse': 0, 'url': id, 'header': headers}
            # 兼容磁力等
            if id.startswith('magnet:'):
                return {'parse': 0, 'url': id, 'header': headers}

            m = re.search(r'(\d+)-([A-Za-z0-9_]+)-(\d+)\.html', id)
            if not m:
                # 兜底：当作页面直连，尝试抽 m3u8
                page = id if id.startswith('http') else self.host + id
                html = self.fetch(page, headers=headers).text
                u = re.search(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', html)
                if u:
                    return {'parse': 0, 'url': u.group(1).replace('\\/', '/'), 'header': headers}
                return {'parse': 1, 'url': page, 'header': headers}

            vod_id, play_from, index = m.group(1), m.group(2), m.group(3)
            api = self.host + '/api/play-url?' + urllib.parse.urlencode(
                {'vodId': vod_id, 'playFrom': play_from, 'index': index})
            txt = self.fetch(api, headers=headers).text
            j = json.loads(txt)
            url = (j.get('url') or '').replace('\\/', '/')
            mode = j.get('mode') or 'native'
            if not url:
                return {'parse': 1, 'url': self.host + '/vodplay/%s-%s-%s.html'
                                              % (vod_id, play_from, index), 'header': headers}
            if mode == 'iframe' or not self.isVideoFormat(url):
                # iframe 线路：拉内嵌页再找 m3u8，找不到就交给 app 自己的解析器
                try:
                    ph = dict(headers)
                    ph['Referer'] = self.host + '/vodplay/%s-%s-%s.html' % (vod_id, play_from, index)
                    inner = self.fetch(url, headers=ph).text
                    u = re.search(r'(https?://[^"\'\s\\]+\.m3u8[^"\'\s\\]*)', inner)
                    if u:
                        return {'parse': 0, 'url': u.group(1), 'header': headers}
                except Exception as e:
                    self.log('iframe parse error:', e)
                if self.isVideoFormat(url):
                    return {'parse': 0, 'url': url, 'header': headers}
                return {'parse': 1, 'url': url, 'header': headers}
            return {'parse': 0, 'url': url, 'header': headers}
        except Exception as e:
            self.log('playerContent error:', e)
            return {'parse': 1, 'url': id, 'header': dict(self.headers)}

    def localProxy(self, param):
        return None


def main():
    """本地测试块：python 脚本名.py 直接运行"""
    sp = Spider()
    sp.init('')
    print('=== homeContent ===')
    r = sp.homeContent({})
    print('classes:', [(c['type_name'], c['type_id']) for c in r['class']])
    print('filters keys:', list(r.get('filters', {}).keys()))
    print()
    print('=== homeVideoContent ===')
    hv = sp.homeVideoContent()
    print('首页推荐:', len(hv['list']), '项')
    if hv['list']:
        print('  first:', hv['list'][0])
    print()
    print('=== categoryContent（全部分类）===')
    for c in r['class']:
        r2 = sp.categoryContent(c['type_id'], 1, {}, {})
        print('  %s: %d 项 | 首页首项=%s | pagecount=%s'
              % (c['type_name'], len(r2['list']),
                 r2['list'][0]['vod_name'] if r2['list'] else '-', r2['pagecount']))
    print()
    print('=== 翻页（第2页必须与第1页不同）===')
    first_tid = '2'
    p1 = sp.categoryContent(first_tid, 1, {}, {})
    p2 = sp.categoryContent(first_tid, 2, {}, {})
    if p1['list'] and p2['list']:
        print('  p1 first:', p1['list'][0]['vod_id'], p1['list'][0]['vod_name'],
              '| p2 first:', p2['list'][0]['vod_id'], p2['list'][0]['vod_name'])
    print()
    print('=== 筛选（电影+动作+2024）===')
    pf = sp.categoryContent('2', 1, {}, {'type': '43', 'year': '2024'})
    print('  %d 项 | %s' % (len(pf['list']),
                            ' / '.join([v['vod_name'] for v in pf['list'][:5]])))
    print()
    print('=== 兼容性：字符串 pg / 字符串 extend ===')
    print('  str pg:', len(sp.categoryContent(first_tid, '1', {}, {})['list']), '项')
    print('  str extend:', len(sp.categoryContent(first_tid, 1, {}, '{}')['list']), '项')
    print('  str extend2:', len(sp.categoryContent('2', 1, {}, '{"type":"43"}')['list']), '项')
    print()
    print('=== detailContent ===')
    r3 = sp.detailContent([p1['list'][0]['vod_id']])
    if r3['list']:
        v = r3['list'][0]
        froms = v['vod_play_from'].split('$$$')
        urls = v['vod_play_url'].split('$$$')
        print('  name:', v['vod_name'], '| year:', v['vod_year'], '| area:', v['vod_area'])
        print('  actor:', v['vod_actor'][:40], '| director:', v['vod_director'])
        print('  remarks:', v['vod_remarks'], '| content:', v['vod_content'][:50])
        print('  线路数:', len(froms), froms)
        for f, u in zip(froms, urls):
            print('    %s -> %d 集，首集: %s' % (f, len(u.split('#')), u.split('#')[0][:70]))
        print()
        print('=== playerContent（逐线路验证真实地址）===')
        for f, u in zip(froms, urls[:3]):
            ep = u.split('#')[0].split('$', 1)[1]
            r4 = sp.playerContent(f, ep, None)
            print('  [%s] parse=%s url=%s' % (f, r4['parse'], str(r4['url'])[:95]))
        print()
        print('=== playerContent（剧集站多线路，detail/638）===')
        r5 = sp.detailContent(['/detail/638.html'])
        v5 = r5['list'][0]
        f5 = v5['vod_play_from'].split('$$$')
        u5 = v5['vod_play_url'].split('$$$')
        print('  线路:', f5, '| 各线路集数:', [len(x.split('#')) for x in u5])
        for f, u in zip(f5, u5):
            ep2 = u.split('#')[1].split('$', 1)[1]
            rr = sp.playerContent(f, ep2, None)
            print('  [%s] %s parse=%s url=%s' % (f, ep2.split('/')[-1], rr['parse'], str(rr['url'])[:90]))
    print()
    print('=== searchContent ===')
    for kw in ['功夫', '诛仙']:
        rs = sp.searchContent(kw, False, 1)
        print('  "%s": %d 项 | %s' % (kw, len(rs['list']),
                                      ' / '.join([x['vod_name'] for x in rs['list'][:6]])))
    rs2 = sp.searchContent('功夫', False, 2)
    print('  翻页 "功夫" p2: %d 项 | %s' % (len(rs2['list']),
                                            ' / '.join([x['vod_name'] for x in rs2['list'][:4]])))


if __name__ == '__main__':
    main()
