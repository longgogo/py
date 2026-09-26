# -*- coding: utf-8 -*-
"""
可可影视（kkys19.com）TVBox Python 爬虫源 —— 影视仓 / OK影视 通用

站点结构（2026-09-26 实测）：
  列表页   /show/{tid}-{类型}-{地区}-{语言}-{年份}-{排序}-{页码}.html   18 条/页
  频道 id  1=电影 2=连续剧 3=动漫 4=综艺纪录 6=短剧（/channel/{id}.html 为频道首页，无分页）
  今日更新 /label/new.html    24 条
  详情页   /detail/{id}.html
  播放页   /play/{id}-{线路sid}-{剧集eid}.html  内嵌 gogogo() 的 src: "https://…/index.m3u8?appId=kkdy&sign=…"
  搜索     /search?k={关键词}&page={页码}&t={token}，token 从任意页面 <input type="hidden" name="t" value="…">
"""
import sys, os, re, json, urllib.parse

# ---- base Spider 导入：app 内有 base.spider，本地测试走 fallback ----
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
                method = 'POST'  # 带 data 时自动升级为 POST（搜索等接口必需）
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
        return '可可影视'

    def log(self, *args):
        # 安全日志：子类自带实现，绝不依赖 base Spider 的 log
        print('[kkys]', *args)

    def init(self, extend=''):
        self.host = 'https://www.kkys19.com'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        # 频道 id（逐个实测 /show/{id}------1.html 均 200 且有 18 条数据）
        self.categories = {
            '电影': '1',
            '连续剧': '2',
            '动漫': '3',
            '综艺纪录': '4',
            '短剧': '6',
        }
        # 筛选行 -> URL 字段下标（/show/{tid}-类型-地区-语言-年份-排序-页码.html）
        self.filter_map = {'类型': 'class', '地区': 'area', '语言': 'lang',
                           '年份': 'year', '排序': 'order'}
        self._filter_cache = {}
        self._token_cache = ''

    def isVideoFormat(self, url):
        return bool(re.match(r'https?://.+\.(m3u8|mp4)', url))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ---------------- 通用工具 ----------------

    def _parse_extend(self, extend):
        """兼容 app 传 dict 或 JSON 字符串两种情况"""
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend.strip() else {}
            except Exception:
                extend = {}
        return extend if isinstance(extend, dict) else {}

    def _abs(self, url):
        if not url:
            return ''
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.host + url
        return url

    def _get(self, url):
        """带一次重试的 GET（本站偶发 SSL 握手超时 / 429 限流）"""
        for i in range(2):
            try:
                return self.fetch(url, headers=self.headers).text
            except Exception as e:
                self.log('fetch error(%d):' % i, url, e)
        return ''

    # ---------------- 列表解析 ----------------

    def _extract_list(self, html):
        """列表项提取：主正则 + 逐块兜底（属性顺序无关）。
        返回统一的 (vod_id, vod_name, vod_pic, vod_remarks) 元组列表。
        真实结构：
          <div class="module-item"><a href="/detail/123.html" class="v-item">
            <div class="v-item-cover"><img … data-original="占位图"><img … data-original="/vod1/vod/cover/…"></div>
            <div class="v-item-bottom"><span>正片</span></div>
            <div class="v-item-footer">
              <div class="v-item-title" style="display: none">可可影视-kekys.com</div>
              <div class="v-item-title">真实标题</div>   ← 可见标题无 style 属性
            </div></a></div>
        """
        out = []
        for m in re.finditer(r'<a href="(/detail/\d+\.html)" class="v-item">([\s\S]{0,3000}?)</a>', html):
            href, blk = m.group(1), m.group(2)
            cov = re.search(r'<div class="v-item-cover"[\s\S]*?</div>', blk)
            seg = cov.group(0) if cov else blk
            pic = ''
            for p in re.findall(r'data-original="([^"]+)"', seg):
                if 'logo_placeholder' not in p:  # 跳过占位图，取真实封面（可能是 /vod1/… 相对路径）
                    pic = self._abs(p)
                    break
            # 可见标题：无 style 属性的那个；取不到再兜底过滤站名
            vis = re.findall(r'<div class="v-item-title">([^<]*)</div>', blk)
            if not vis:
                vis = [t for t in re.findall(r'<div class="v-item-title"[^>]*>([^<]*)</div>', blk)
                       if 'kekys' not in t and 'kkys' not in t]
            name = vis[0].strip() if vis else ''
            rem = re.search(r'<div class="v-item-bottom">\s*<span>\s*([^<]*?)\s*</span>', blk)
            out.append((href, name, pic, rem.group(1).strip() if rem else ''))
        return out

    def _to_videos(self, items):
        videos = []
        for vid, name, pic, rem in items:
            videos.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic,
                'vod_remarks': rem,
            })
        return videos

    # ---------------- 筛选项（从 /show 页 <div class="filter-row"> 实时解析） ----------------

    def _get_filters(self, tid):
        if tid in self._filter_cache:
            return self._filter_cache[tid]
        filters = []
        try:
            html = self._get('%s/show/%s------1.html' % (self.host, tid))
            for row in re.finditer(r'<div class="filter-row-side">\s*<strong>([^<:：]*)', html):
                label = row.group(1).strip()
                key = self.filter_map.get(label)
                if not key:
                    continue
                tail = html[row.end():row.end() + 6000]
                end = tail.find('<div class="filter-row-side">')
                seg = tail[:end] if end > 0 else tail
                opts = []
                for a in re.finditer(r'href="(/show/[^"]+)"\s*\n?\s*class="filter-item[^"]*">([^<]*)</a>', seg):
                    href, name = a.group(1), a.group(2).strip()
                    path = urllib.parse.unquote(href.replace('/show/', '').replace('.html', ''))
                    parts = path.split('-')
                    val = parts[1] if len(parts) == 2 else (parts[1 + ['class', 'area', 'lang', 'year', 'order'].index(key)]
                                                            if len(parts) >= 6 else '')
                    opts.append({'n': name, 'v': val})
                if opts:
                    filters.append({'key': key, 'name': label, 'value': opts})
        except Exception as e:
            self.log('filters error:', tid, e)
        self._filter_cache[tid] = filters
        return filters

    # ---------------- 标准方法 ----------------

    def homeContent(self, filter):
        classes = [{'type_name': name, 'type_id': tid}
                   for name, tid in self.categories.items()]
        filters = {}
        # 筛选行从 /show 页实时解析（结果缓存，站点不可用时退化为无筛选，不影响分类展示）
        fail = 0
        for name, tid in self.categories.items():
            try:
                f = self._get_filters(tid)
                if f:
                    filters[tid] = f
                    fail = 0
                else:
                    fail += 1
            except Exception as e:
                self.log('homeContent filters error:', tid, e)
                fail += 1
            if fail >= 2:
                break
        return {'class': classes, 'filters': filters}

    def homeVideoContent(self):
        """首页推荐：/label/new.html 今日更新（24 条）"""
        try:
            html = self._get(self.host + '/label/new.html')
            return {'list': self._to_videos(self._extract_list(html))}
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
            path = tid
            if path in self.categories.values():
                pass
            elif path in self.categories:
                path = self.categories[path]
            else:
                path = str(path).strip('/').split('/')[-1].replace('.html', '')

            def val(k):
                v = extend.get(k, '')
                v = v if isinstance(v, str) else ''
                return urllib.parse.quote(v) if v else ''  # 中文筛选值必须编码

            # 路径式分页：/show/{tid}-{类型}-{地区}-{语言}-{年份}-{排序}-{页码}.html
            url = '%s/show/%s-%s-%s-%s-%s-%s-%d.html' % (
                self.host, path, val('class'), val('area'), val('lang'),
                val('year'), val('order'), pg)
            html = self._get(url)
            if not html:  # 页面没取到（超时/限流）才退回无筛选路径重试
                url = '%s/show/%s------%d.html' % (self.host, path, pg)
                html = self._get(url)
            videos = self._to_videos(self._extract_list(html))
            return {'list': videos, 'page': pg, 'pagecount': 9999,
                    'limit': 18, 'total': 999999}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 18, 'total': 0}

    def detailContent(self, ids):
        try:
            raw = ids[0] if isinstance(ids, (list, tuple)) else ids
            url = self._abs(raw)
            if not url.startswith('http'):
                url = self.host + '/detail/%s.html' % str(raw).replace('.html', '')
            html = self._get(url)
            if not html:
                return {'list': []}

            # 标题：.detail-title 里多个 <strong>，CSS 规则为 odd 隐藏 / even 显示 → 取第 2 个
            strongs = re.findall(r'<div class="detail-title">([\s\S]*?)</div>', html)
            name = ''
            if strongs:
                ss = [s.strip() for s in re.findall(r'<strong>([^<]*)</strong>', strongs[0]) if s.strip()]
                if len(ss) >= 2:
                    name = ss[1]
                elif ss:
                    name = ss[0]
            if not name or 'kkys' in name.lower() or 'kekys' in name.lower():
                t = re.search(r'<title>(.*?)</title>', html)
                if t:
                    name = re.split(r'[-_|]', t.group(1))[0].strip()

            pic_m = re.search(r'class="detail-pic"[\s\S]{0,800}?data-original="([^"]+)"', html)
            pic = self._abs(pic_m.group(1)) if pic_m else ''

            tags = re.findall(r'class="detail-tags-item">([^<]*)</a>', html)
            year = tags[0] if tags else ''
            area = tags[1] if len(tags) > 1 else ''

            desc_m = re.search(r'<div class="detail-desc">\s*<p>\s*([\s\S]*?)\s*</p>', html)
            content = ''
            if desc_m:
                content = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()
            if not content:
                d = re.search(r'<meta name="description"\s*content="([^"]*)"', html)
                content = d.group(1).strip() if d else ''

            def info(label):
                m = re.search(r'class="detail-info-row-side">%s:?</div>\s*'
                              r'<div class="detail-info-row-main">([\s\S]*?)</div>' % label, html)
                if not m:
                    return ''
                return re.sub(r'\s+', ' ',
                              re.sub(r'<[^>]+>', '', m.group(1))).strip()

            actors = info('演员')
            director = info('导演')

            # 播放列表：线路标签(source-item-label) 与 剧集块(div.episode-list) 顺序一一对应
            # 输出格式：线路标签用 $$$ 连接；同一线路内 集名$地址 用 # 连接
            labels = re.findall(r'class="source-item-label">([^<]+)<', html)
            blocks = re.findall(r'<div class="episode-list"(?:\s+style="[^"]*")?>(.*?)</div>',
                                html, re.DOTALL)
            play_from, play_url = [], []
            for i, blk in enumerate(blocks):
                eps = re.findall(r'<a href="([^"]+)" class="episode-item"[^>]*><span>([^<]*)</span>', blk)
                if not eps:
                    continue
                lab = labels[i].strip() if i < len(labels) else ('线路%d' % (i + 1))
                play_from.append(lab)
                play_url.append('#'.join(
                    ['%s$%s' % (ep[1].strip() or ('第%d集' % (j + 1)), self._abs(ep[0]))
                     for j, ep in enumerate(eps)]))

            video = {
                'vod_id': raw,
                'vod_name': name,
                'vod_pic': pic,
                'vod_year': year,
                'vod_area': area,
                'vod_actor': actors,
                'vod_director': director,
                'vod_remarks': '',
                'vod_content': content,
                'vod_play_from': '$$$'.join(play_from) if play_from else '可可影视',
                'vod_play_url': '$$$'.join(play_url) if play_url else '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    def _get_search_token(self):
        if self._token_cache:
            return self._token_cache
        try:
            html = self._get(self.host + '/')
            m = re.search(r'name="t"\s+value="([^"]+)"', html)
            if m:
                self._token_cache = m.group(1)
        except Exception as e:
            self.log('token error:', e)
        return self._token_cache

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        try:
            token = self._get_search_token()
            url = '%s/search?k=%s&page=%d&t=%s' % (
                self.host, urllib.parse.quote(key), pg, urllib.parse.quote(token, safe=''))
            html = self._get(url)
            videos = []
            for m in re.finditer(r'<a href="(/detail/\d+\.html)" class="search-result-item">([\s\S]{0,2000}?)</a>',
                                 html):
                blk = m.group(2)
                title = re.search(r'class="title">([^<]*)<', blk)
                if not title:
                    continue
                pic = ''
                for p in re.findall(r'data-original="([^"]+)"', blk):
                    if 'logo_placeholder' not in p:
                        pic = self._abs(p)
                        break
                tag = re.findall(r'class="tags">([\s\S]*?)</div>', blk)
                rem = ''
                if tag:
                    rem = ' '.join(re.findall(r'<span>([^<]*)</span>', tag[0])[:2])
                videos.append({
                    'vod_id': m.group(1),
                    'vod_name': re.sub(r'<[^>]+>', '', title.group(1)).strip(),
                    'vod_pic': pic,
                    'vod_remarks': rem,
                })
            if not videos:  # 兜底：token 失效时重新取一次
                self._token_cache = ''
                token = self._get_search_token()
                html = self._get('%s/search?k=%s&page=%d&t=%s' % (
                    self.host, urllib.parse.quote(key), pg, urllib.parse.quote(token, safe='')))
                videos = self._to_videos(self._extract_list(html))
            return {'list': videos, 'page': pg}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg}

    def playerContent(self, flag, id, vipFlags):
        """播放页内嵌真实地址：gogogo() 里 src: "https://…/index.m3u8?appId=kkdy&sign=…&timestamp=…"
        （入口节点会 302 到 CDN 节点，由播放器自动跟随）"""
        try:
            url = self._abs(id) if not str(id).startswith('http') else id
            if not re.search(r'\.(m3u8|mp4)', url):
                html = self._get(url)
                m = re.search(r'src:\s*"([^"]+?\.(?:m3u8|mp4)[^"]*)"', html)
                if not m:
                    m = re.search(r'(https?://[^\s"\'<>\\]+?\.(?:m3u8|mp4)[^\s"\'<>\\]*)', html)
                if m:
                    url = m.group(1).replace('\\/', '/')
            return {
                'parse': 0,
                'url': url,
                'header': dict(self.headers),
            }
        except Exception as e:
            self.log('playerContent error:', e)
            return {'parse': 0, 'url': id, 'header': dict(self.headers)}

    def localProxy(self, param):
        return None


def main():
    """本地测试块：python 脚本名.py 直接运行"""
    sp = Spider()
    sp.init('')
    print('=== homeContent ===')
    r = sp.homeContent(True)
    print('classes:', [(c['type_name'], c['type_id']) for c in r['class']])
    for tid, f in (r.get('filters') or {}).items():
        print('  filter tid=%s -> %s' % (tid, ', '.join('%s(%d项)' % (x['name'], len(x['value'])) for x in f)))
    print()
    print('=== homeVideoContent（今日更新）===')
    hv = sp.homeVideoContent()
    print('  %d 项' % len(hv['list']), hv['list'][0] if hv['list'] else None)
    print()
    print('=== categoryContent（全部分类）===')
    for c in r['class']:
        r2 = sp.categoryContent(c['type_id'], 1, {}, {})
        print('  %s: %d 项 | 例: %s' % (c['type_name'], len(r2['list']),
                                       r2['list'][0]['vod_name'] if r2['list'] else '-'))
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
    print('=== 筛选（类型=喜剧）===')
    f1 = sp.categoryContent(first_tid, 1, {}, {'class': '喜剧'})
    print('  喜剧: %d 项 | 例: %s' % (len(f1['list']),
                                     f1['list'][0]['vod_name'] if f1['list'] else '-'))
    print()
    print('=== searchContent ===')
    s = sp.searchContent('庆余年', False, 1)
    print('  p1: %d 项' % len(s['list']), s['list'][0] if s['list'] else None)
    s2 = sp.searchContent('庆余年', False, 2)
    print('  p2: %d 项' % len(s2['list']), s2['list'][0] if s2['list'] else None)
    print('  str pg:', len(sp.searchContent('庆余年', False, '1')['list']), '项')
    print()
    print('=== detailContent（电影）===')
    if p1['list']:
        r3 = sp.detailContent([p1['list'][0]['vod_id']])
        if r3['list']:
            v = r3['list'][0]
            froms = v['vod_play_from'].split('$$$')
            urls = v['vod_play_url'].split('$$$')
            print('  name:', v['vod_name'], '| year:', v['vod_year'], '| area:', v['vod_area'])
            print('  导演:', v['vod_director'][:40], '| 演员:', v['vod_actor'][:50])
            print('  海报:', v['vod_pic'][:90])
            print('  线路数:', len(froms), '| 线路:', froms[:5])
            print('  首线路集数:', len(urls[0].split('#')))
            print()
            print('=== playerContent ===')
            ep = urls[0].split('#')[0]
            r4 = sp.playerContent(froms[0], ep.split('$', 1)[1], None)
            print('  parse:', r4['parse'], '| url:', r4['url'][:120])
    print()
    print('=== detailContent（连续剧，验集数）===')
    tv = sp.categoryContent('2', 1, {}, {})
    if tv['list']:
        r5 = sp.detailContent([tv['list'][0]['vod_id']])
        if r5['list']:
            v = r5['list'][0]
            froms = v['vod_play_from'].split('$$$')
            urls = v['vod_play_url'].split('$$$')
            print('  name:', v['vod_name'], '| 线路数:', len(froms), '| 段数一致:', len(froms) == len(urls))
            for i, (f, pu) in enumerate(zip(froms, urls)):
                eps = pu.split('#')
                print('    %-10s %2d 集 | 首集: %s' % (f, len(eps), eps[0][:70]))
                if i >= 2:
                    break


if __name__ == '__main__':
    main()
