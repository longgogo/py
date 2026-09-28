# -*- coding: utf-8 -*-
"""
人人影视（人人影视PRO）TVBox / 影视仓 / OK影视 Python 源
站点：https://www.renren.pro

2026-09-28 修复（本机已可直连，7s 左右较慢但 200）：
  1) 播放地址不显示：原源剧集链接是相对路径（/play/{uuid}/{ep}），
     影视仓详情页「播放地址」行显示不出 → 详情里统一补全为完整 URL。
  2) 封面：详情/播放页站点不输出海报 → 但列表页有封面，
     加 _pic_cache（uuid -> 封面），从列表点进详情时带上封面。
  3) 站点走 CDN 偶发连接重置/超时 → 统一 _f 重试入口（5 次递增等待）。
  4) ⚠️ 演员/导演：实测全站详情页（短剧/电影/欧美剧/综艺/国产剧）均**不输出**
     主演/导演任何数据（页面无该字段），站点本身不提供，无法补齐，保持留空。

实测结构（2026-09-26 离线解析 + 2026-09-28 在线复核）：
  host      https://www.renren.pro   （苹果CMS v10 默认模板，路由被改写）
  导航      首页 / ；影视库 /list/all ；搜索 /search?wd=
  分类列表  /list/all?page={n}   ← 全站唯一可翻页列表，每页 48 条
  列表项    div.module-item（封面 img[data-src] / 标题 a.module-item-title / 备注 .module-item-text）
  详情/播放 同一页：/play/{uuid}（默认第 1 集） 与 /play/{uuid}/{ep_uuid}
            · 真实地址内联在 Artplayer 配置里：url: "https://....m3u8"
            · 选集 div.module-blocklist > a[href="/play/{uuid}/{ep_uuid}"][title]
  搜索      GET /search?wd={kw}   结果 div.module-search-item；无分页
"""
import sys, os, re, json, time, urllib.parse

# ---- base Spider 导入：app 内有 base.spider，本地测试走 fallback ----
try:
    from base.spider import Spider
except Exception:
    class Spider:
        def __init__(self):
            self.headers = {}

        def fetch(self, url, headers=None, data=None, method='GET', timeout=15, **kwargs):
            """本地 fallback：**kwargs 吞掉 app 专有参数（allow_redirects / verify 等）"""
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

    # 首页栏目名 -> type_id（这些栏目没有独立 URL，只能从首页对应板块取）
    HOME_SECTIONS = [
        ('最新热播', 'hot'),
        ('电影', 'movie'),
        ('连续剧', 'tv'),
        ('海外剧场', 'haiwai'),
        ('综艺剧场', 'zongyi'),
        ('动漫剧场', 'dongman'),
    ]

    def getName(self):
        return '人人影视'

    def log(self, *args):
        # 安全日志：子类自带实现，绝不依赖 base Spider 的 log
        print('[人人影视]', *args)

    def init(self, extend=''):
        self.host = 'https://www.renren.pro'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            # 反盗链站点必须带 Referer，播放时随 header 一起返回
            'Referer': self.host + '/',
        }
        # type_id 约定：'all' = 影视库（可翻页）；其余 = 首页对应栏目
        self.categories = {'影视库': 'all'}
        for name, tid in self.HOME_SECTIONS:
            self.categories[name] = tid
        self._home_cache = {'ts': 0, 'html': ''}
        # 列表页见过的封面（uuid -> url），详情页无海报时回填
        self._pic_cache = {}

    def isVideoFormat(self, url):
        return bool(re.match(r'https?://.+\.(m3u8|mp4|flv)', url or ''))

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

    def _f(self, url):
        """统一请求入口：站点走 CDN，偶发连接重置/超时，重试 5 次递增等待"""
        last = None
        for i in range(5):
            try:
                r = self.fetch(url, headers=self.headers)
                if getattr(r, 'text', ''):
                    return r
            except Exception as e:
                last = e
            time.sleep(min(1.0 + i * 0.8, 4.0))
        if last:
            raise last
        class _R:
            text = ''
        return _R()

    # ---------------- 列表解析 ----------------

    def _extract_list(self, html):
        """统一处理 div.module-item（首页/影视库同构）。
        返回 (vod_id, vod_name, vod_pic, vod_remarks, vod_content) 五元组。
        """
        items = []
        marks = list(re.finditer(r'<div class="module-item">', html))
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else min(len(html), m.start() + 4000)
            seg = html[m.start():end]

            a = re.search(r'<a href="(/play/[^"]+)"[^>]*class="module-item-title"[^>]*title="([^"]*)"', seg)
            if not a:
                # 标题块在 .module-item-titlebox 里，属性顺序可能不同
                a = re.search(r'<a[^>]*href="(/play/[^"]+)"[^>]*class="module-item-title"', seg)
                if a:
                    nm = re.search(r'title="([^"]*)"', a.group(0))
                    a = (a.group(1), nm.group(1) if nm else '')
            if not a:
                a = re.search(r'<a[^>]*href="(/play/[^"]+)"[^>]*title="([^"]*)"', seg)
            if not a:
                continue
            vid, name = a.group(1), a.group(2)

            pic = re.search(r'<img[^>]*(?:data-src|src)="([^"]+)"', seg)
            note = re.search(r'class="module-item-text"[^>]*>(.*?)</div>', seg, re.S)
            note = re.sub(r'<[^>]+>', '', note.group(1)).strip() if note else ''
            if not note:
                # 首页栏目卡片没有 .module-item-text，退化用封面角标（热播/独家推荐）
                ru = re.findall(r'<span class="(?:rebo|vip)">(.*?)</span>', seg, re.S)
                note = ' '.join([re.sub(r'<[^>]+>', '', x).strip() for x in ru])
            desc = re.search(r'class="module-item-style video-text"[^>]*>(.*?)</div>', seg, re.S)
            desc = re.sub(r'<[^>]+>', '', desc.group(1)).strip() if desc else ''

            items.append((vid, name.strip(), pic.group(1) if pic else '', note, desc))
        if items:
            return items
        # 兜底：属性顺序无关，逐个 /play/ 链接提取（去重）
        seen = set()
        for m in re.finditer(r'<a href="(/play/[^"]+)"[^>]*title="([^"]*)"', html):
            if m.group(1) in seen:
                continue
            seen.add(m.group(1))
            items.append((m.group(1), m.group(2).strip(), '', '', ''))
        return items

    def _to_videos(self, html):
        videos, seen = [], set()
        for vid, name, pic, note, desc in self._extract_list(html):
            if vid in seen or not name:
                continue
            seen.add(vid)
            # 记录封面，详情页无海报时回填
            if pic:
                core = re.search(r'/play/[0-9a-fA-F\-]+', vid)
                if core:
                    self._pic_cache[core.group(0)] = pic
                    if len(self._pic_cache) > 600:
                        # 简单控制体积：丢最早写入的一半
                        for k in list(self._pic_cache)[:300]:
                            self._pic_cache.pop(k, None)
            videos.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic,
                'vod_remarks': note,
            })
        return videos

    def _home_html(self):
        """首页 200KB 左右，同一次调用内缓存，避免分类循环里重复拉取"""
        if self._home_cache['html'] and time.time() - self._home_cache['ts'] < 120:
            return self._home_cache['html']
        html = self._f(self.host + '/').text
        self._home_cache = {'ts': time.time(), 'html': html}
        return html

    def _section_html(self, html, want_names):
        """按 <h2 class="module-title">栏目标题切分首页，取标题命中 want_names 的板块 HTML"""
        parts = re.split(r'(<h2 class="module-title">)', html)
        # re.split 带捕获组：偶数位为分隔符，奇数位为标题起点
        out = []
        for i in range(1, len(parts) - 1, 2):
            title = re.sub(r'<[^>]+>', '', parts[i + 1].split('</h2>')[0]).strip()
            body = parts[i + 1] if i + 1 < len(parts) else ''
            if title in want_names:
                out.append(body)
        return '\n'.join(out)

    # ---------------- 标准接口 ----------------

    def homeContent(self, filter):
        try:
            classes = [{'type_name': name, 'type_id': tid}
                       for name, tid in self.categories.items()]
        except Exception as e:
            self.log('homeContent error:', e)
            classes = []
        # 站点列表接口不接受任何筛选/排序参数（?by= / ?class= / ?year= 实测都被忽略），故不提供筛选
        return {'class': classes, 'filters': {}}

    def homeVideoContent(self):
        try:
            html = self._home_html()
            html = self._section_html(html, {n for n, _ in self.HOME_SECTIONS})
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
            # 允许 app 直接把这个源的分类名当 tid 传
            for name, t in self.categories.items():
                if tid == name:
                    tid = t
                    break
            if tid == 'all':
                # 全站唯一可翻页列表，每页 48 条
                url = self.host + '/list/all?page=%d' % pg
                html = self._f(url).text
                videos = self._to_videos(html)
                # 分页区只有上一页/下一页，没有总页数；用"有没有下一页"判断
                has_next = 'page-next' in html and videos
                pagecount = pg + 1 if has_next else pg
                if not videos:
                    pagecount = pg
                return {'list': videos, 'page': pg, 'pagecount': pagecount,
                        'limit': 48, 'total': pagecount * 48}
            # 其余分类 = 首页对应栏目（该站栏目没有独立 URL，只能就地取）
            names = set()
            for name, t in self.categories.items():
                if t == tid:
                    names.add(name)
            if pg > 1 or not names:
                return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 16, 'total': 0}
            html = self._section_html(self._home_html(), names)
            videos = self._to_videos(html)
            return {'list': videos, 'page': 1, 'pagecount': 1,
                    'limit': 16, 'total': len(videos)}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 48, 'total': 0}

    # ---------------- 详情 ----------------

    def _parse_plays(self, html):
        """选集：div.module-blocklist > a[href="/play/{vod}/{ep}"][title] > span
        锚点属性顺序为 class/href/title，且内部嵌 <div class="playon">，故逐锚点取属性而非整块正则。
        返回 (play_from_list, play_url_list)。站点实际只有一个线路块。
        集链接统一补全为完整 URL（详情页「播放地址」行、部分 app 播放都依赖完整 URL）。
        """
        regions = []
        for p in html.split('<div class="module-blocklist">')[1:]:
            cut = p.find('</main>')
            regions.append(p[:cut] if cut > 0 else p)
        if not regions:
            regions = [html]      # 兜底：整页扫描

        froms, urls = [], []
        for bi, blk in enumerate(regions):
            eps, seen = [], set()
            for am in re.finditer(r'<a\b([^>]*)>(.*?)</a>', blk, re.S):
                attrs, inner = am.group(1), am.group(2)
                h = re.search(r'href="([^"]+)"', attrs)
                if not h:
                    continue
                href = h.group(1)
                if not re.match(r'^(?:https?://[^/]+)?/play/[0-9a-fA-F\-]+/[0-9a-fA-F\-]+$', href):
                    continue
                if href.startswith('http'):
                    href = '/' + href.split('/', 3)[3]
                if href in seen:
                    continue
                seen.add(href)
                nm = re.search(r'title="([^"]*)"', attrs)
                name = (nm.group(1).strip() if nm else '') or \
                    re.sub(r'<[^>]+>', '', inner).strip()
                if not name:
                    name = '第%d集' % (len(eps) + 1)
                eps.append((name, self.host + href))
            if eps:
                froms.append('人人影视' if len(regions) == 1 else '线路%d' % (bi + 1))
                urls.append('#'.join('%s$%s' % (n, u) for n, u in eps))
        return froms, urls

    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
            vid = str(vid)
            url = vid if vid.startswith('http') else self.host + vid
            html = self._f(url).text

            # 片名：meta keywords 最干净，其次 <title>（形如 "名 - 第1集 免费在线观看- ..."）
            name = ''
            kw = re.search(r'<meta name="keywords" content="([^"]*)"', html)
            if kw and kw.group(1).strip():
                name = kw.group(1).strip()
            if not name:
                t = re.search(r'<title>(.*?)</title>', html, re.S)
                if t:
                    name = re.split(r'\s*-\s*', t.group(1).strip())[0].strip()
            # 简介
            content = ''
            h1 = re.search(r'<h1 class="title-info">(.*?)</h1>', html, re.S)
            if h1:
                content = re.sub(r'<[^>]+>', '', h1.group(1)).replace('\u3000', ' ').strip()
            if not content:
                d = re.search(r'<meta name="description" content="([^"]*)"', html)
                content = d.group(1).strip() if d else ''
            # 标签：类型 / 语言 / 地区（如 短剧 国语 大陆；电影为 科幻片 美国 2025）
            tags = [re.sub(r'<[^>]+>', '', x).strip()
                    for x in re.findall(r'class="tag-link"[^>]*>(.*?)</a>', html, re.S)]
            tags = [x for x in tags if x]
            year = ''
            for x in tags:
                if re.match(r'^(19|20)\d{2}$', x):
                    year = x
                    break
            area = tags[-1] if tags else ''
            if re.match(r'^(19|20)\d{2}$', area):
                area = ''
            remark = ''
            tl = re.search(r'<a\s+class="title-link"[^>]*>(.*?)</a>', html, re.S)
            if tl:
                full = re.sub(r'<[^>]+>', '', tl.group(1)).strip()
                if name and full.startswith(name):
                    remark = full[len(name):].strip()
                elif not name:
                    name = full
            # 部分单集影片（如电影）标签里带清晰度，直接当备注
            if not remark:
                for x in tags:
                    if re.search(r'(HD|TC|TS|抢先|中字|国语|粤语)', x):
                        remark = x
                        break

            play_from, play_url = self._parse_plays(html)
            vod_id = vid
            m = re.search(r'/play/[0-9a-fA-F\-]+', vid)
            if m:
                vod_id = m.group(0)

            video = {
                'vod_id': vod_id,
                'vod_name': name,
                # 详情/播放页无海报图（站点不输出）→ 用列表页见过的封面回填
                'vod_pic': self._pic_cache.get(vod_id, ''),
                'vod_year': year,
                'vod_area': area,
                # ⚠️ 站点详情页不输出 主演/导演（全站各类型实测均无此字段），无法补齐
                'vod_actor': '',
                'vod_director': '',
                'vod_remarks': remark,
                'vod_content': content,
                'vod_play_from': '$$$'.join(play_from) if play_from else '人人影视',
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
            # 表单 action="/search"，参数名 wd；实测无分页（?page=2 走站内 404）
            if pg > 1:
                return {'list': [], 'page': pg}
            url = self.host + '/search?' + urllib.parse.urlencode({'wd': key})
            html = self._f(url).text
            videos, seen = [], set()
            for block in html.split('<div class="module-search-item">')[1:]:
                a = re.search(r'<h3>\s*<a[^>]*href="(/play/[^"]+)"[^>]*title="([^"]*)"', block)
                if not a:
                    a = re.search(r'<h3>(.*?)</h3>', block, re.S)
                    if not a:
                        continue
                    href = re.search(r'href="(/play/[^"]+)"', a.group(1))
                    if not href:
                        continue
                    a = (href.group(1), re.sub(r'<[^>]+>', '', a.group(1)).strip())
                vid = a.group(1)
                if vid in seen:
                    continue
                seen.add(vid)
                pic = re.search(r'<img[^>]*(?:data-src|src)="([^"]+)"', block)
                ser = re.search(r'class="video-serial"[^>]*>(.*?)</a>', block, re.S)
                videos.append({
                    'vod_id': vid,
                    'vod_name': re.sub(r'<[^>]+>', '', a.group(2)).strip(),
                    'vod_pic': pic.group(1) if pic else '',
                    'vod_remarks': re.sub(r'<[^>]+>', '', ser.group(1)).strip() if ser else '',
                })
            if not videos:
                # 兜底：整页顺序无关提取
                for m in re.finditer(r'<a[^>]*href="(/play/[^"]+)"[^>]*title="([^"]*)"', html):
                    if m.group(1) in seen:
                        continue
                    seen.add(m.group(1))
                    videos.append({'vod_id': m.group(1), 'vod_name': m.group(2).strip(),
                                   'vod_pic': '', 'vod_remarks': ''})
            # 顺手缓存搜索结果封面
            for v in videos:
                core = re.search(r'/play/[0-9a-fA-F\-]+', v['vod_id'])
                if core and v.get('vod_pic'):
                    self._pic_cache[core.group(0)] = v['vod_pic']
            return {'list': videos, 'page': pg, 'pagecount': pg}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg}

    # ---------------- 播放 ----------------

    def playerContent(self, flag, id, vipFlags):
        """id = /play/{uuid} 或 /play/{uuid}/{ep_uuid}（或完整 URL）：
        真实 m3u8 内联在播放页的 Artplayer 配置里（url: "https://....m3u8"）。"""
        try:
            id = str(id)
            headers = dict(self.headers)
            if id.startswith('magnet:'):
                return {'parse': 0, 'url': id, 'header': headers}
            if self.isVideoFormat(id):
                return {'parse': 0, 'url': id, 'header': headers}

            page = id if id.startswith('http') else self.host + id
            html = self._f(page).text
            url = ''
            # 优先取 Artplayer 的 url 字段（兼容单/双引号与属性顺序）
            m = re.search(r'url\s*:\s*["\']([^"\']+\.(?:m3u8|mp4|flv)[^"\']*)["\']', html, re.I)
            if m:
                url = m.group(1)
            if not url:
                m = re.search(r'url\s*:\s*["\'](https?://[^"\']+)["\']', html)
                if m:
                    url = m.group(1)
            if not url:
                m = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', html)
                if m:
                    url = m.group(1)
            url = (url or '').replace('\\/', '/')
            if not url:
                # 拿不到直链就交给 app 自身解析器处理该播放页
                return {'parse': 1, 'url': page, 'header': headers}
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
    print()
    print('=== 影视库 第1页 ===')
    p1 = sp.categoryContent('all', 1, {}, {})
    print('  %d 项, 首项: %s' % (len(p1['list']),
                                p1['list'][0]['vod_name'] if p1['list'] else '无'))
    p2 = sp.categoryContent('all', 2, {}, {})
    print('  第2页: %d 项, 首项: %s' % (len(p2['list']),
                                       p2['list'][0]['vod_id'] if p2['list'] else '无'))
    print()
    print('=== 详情 ===')
    if p1['list']:
        v = sp.detailContent([p1['list'][0]['vod_id']])['list'][0]
        print('  名:', v['vod_name'], '| 年:', v['vod_year'], '| 地:', v['vod_area'],
              '| 备注:', v['vod_remarks'], '| pic:', ('有' if v['vod_pic'] else '无'))
        print('  简介:', v['vod_content'][:60])
        print('  线路:', v['vod_play_from'], '| 段数:', len(v['vod_play_url'].split('$$$')))
        seg0 = v['vod_play_url'].split('$$$')[0].split('#')[0]
        print('  首集:', seg0)
        print()
        print('=== 播放 ===')
        pl = sp.playerContent(v['vod_play_from'], seg0.split('$', 1)[-1], None)
        print('  parse:', pl['parse'], '| url:', str(pl['url'])[:90])
    print()
    print('=== 搜索 ===')
    rs = sp.searchContent('末日', False, 1)
    print('  结果数:', len(rs['list']), [x['vod_name'] for x in rs['list'][:5]])


if __name__ == '__main__':
    main()
