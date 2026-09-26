# -*- coding: utf-8 -*-
"""
ZIP0影视（zip0.com）TVBox Python 爬虫源 —— 影视仓 / OK影视 通用

站点结构（2026-09-26 实测）：
  分类页   /category/movie|short|tv|variety|documentary|sports?page=N   （SSR 直出 article.video-card；?page=N 实测有效）
  首页     /  为 SPA 门户，SSR 无影视列表 → 用 /category/movie 第 1 页当首页推荐
  影片页   /watch?source={线路}&id={id}&episode={n}  SSR 内嵌 TanStack 流式 JSON：
             $R[15]={id:"99152",source:"ffzy",sourceName:"线路 4",title:"…",poster:"…",
                     year:"…",remarks:"…",category:"…",area:"…",description:"…",
                     actors:"…",director:"…",episodes:$R[16]=[$R[17]={name:"HD中字",url:"https://…/index.m3u8"}]}
           → 真实播放地址就是 episodes[].url（直链 m3u8，实测无需 Referer 即可拉取）
  搜索     /search?q=xxx 服务端渲染无结果（客户端渲染），真实接口是 TanStack serverFn:
             GET /_serverFn/{fid}?payload=<seroval信封JSON>
           信封 = {"t":<节点树>,"f":127,"m":[]}；节点 {t:0数字|1字符串|2常量|9数组|10对象}
           必须带 Origin / Sec-Fetch-* 头，否则站点 WAF 直接 403。
           一次调用只查一条线路，需多线路并发（本实现串行查若干条并去重）。
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

    # 搜索 serverFn id（2026-09-26 构建；站点重新构建后 hash 会变，脚本内置自动重探测兜底）
    SEARCH_FID = '924908a6328d92c97055b1d048defe7b4f8102dee6907ac36be30470204c7535'

    def getName(self):
        return 'ZIP0影视'

    def log(self, *args):
        # 安全日志：子类自带实现，绝不依赖 base Spider 的 log
        print('[zip0]', *args)

    def init(self, extend=''):
        self.host = 'https://zip0.com'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                          'Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        self.categories = {
            '电影': 'movie',
            '短剧': 'short',
            '电视剧': 'tv',
            '综艺': 'variety',
            '纪录片': 'documentary',
            '体育': 'sports',
        }
        # 参与聚合搜索的线路（搜索接口一次只查一条线路，按实测质量排序取前几条）
        self.search_sources = ['bfzy', 'lzi', 'dyttzy', 'ffzy', 'jisu']
        self._fid_cache = self.SEARCH_FID

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
        url = url.replace('&amp;', '&')
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.host + url
        return url

    def _get(self, url, extra=None):
        """带一次重试的 GET（本机到该站偶发 SSL 握手 / 读超时）"""
        headers = dict(self.headers)
        if extra:
            headers.update(extra)
        for i in range(2):
            try:
                return self.fetch(url, headers=headers).text
            except Exception as e:
                self.log('fetch error(%d):' % i, url[:90], e)
        return ''

    # ---------------- 列表页（SSR 直出的 article.video-card） ----------------

    def _extract_list(self, html):
        """返回 (vod_id, vod_name, vod_pic, vod_remarks) 四元组列表
        真实结构：
          <article class="video-card">
            <a aria-label="播放 死亡赌局" href="/watch?source=dyttzy&amp;id=84451&amp;episode=1"
               class="video-card__poster-link">
              <img alt="《死亡赌局》封面" class="video-card__poster" src="https://…webp"/>
              <span class="video-card__remarks">HD</span></a>
            <div class="video-card__body">
              <a href="/watch?…" class="video-card__title">死亡赌局</a>
              <div class="video-card__meta"><span>2026</span><span>剧情片</span></div>
            </div></article>
        """
        out = []
        for m in re.finditer(r'<article class="video-card">([\s\S]*?)</article>', html):
            blk = m.group(1)
            href = re.search(r'href="(/watch\?[^"]+)"', blk)
            if not href:
                continue
            src = re.search(r'source=([^&"\']+)', href.group(1))
            vid = re.search(r'id=(\d+)', href.group(1))
            if not (src and vid):
                continue
            pic = re.search(r'class="video-card__poster"[^>]*src="([^"]+)"', blk)
            if not pic:
                pic = re.search(r'<img[^>]*src="([^"]+)"', blk)
            name = re.search(r'class="video-card__title">([^<]*)</a>', blk)
            if not name:
                al = re.search(r'aria-label="[^"]*?([^"]*)"', blk)
                name = al
            rem = re.search(r'class="video-card__remarks">([^<]*)<', blk)
            out.append(('%s|%s' % (src.group(1), vid.group(1)),
                        name.group(1).strip() if name else '',
                        self._abs(pic.group(1)) if pic else '',
                        rem.group(1).strip() if rem else ''))
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

    def _category_url(self, tid, pg):
        slug = tid
        if slug in self.categories.values():
            pass
        elif slug in self.categories:
            slug = self.categories[slug]
        else:
            slug = str(slug).strip('/').split('/')[-1].split('?')[0]
        url = '%s/category/%s' % (self.host, slug)
        if pg > 1:
            url += '?page=%d' % pg
        return url

    # ---------------- 标准方法 ----------------

    def homeContent(self, filter):
        classes = [{'type_name': name, 'type_id': slug}
                   for name, slug in self.categories.items()]
        return {'class': classes, 'filters': {}}

    def homeVideoContent(self):
        """首页推荐：本站门户页 SSR 无影视列表，用「电影」分类第 1 页代替"""
        try:
            html = self._get(self._category_url('movie', 1))
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
            html = self._get(self._category_url(tid, pg))
            videos = self._to_videos(self._extract_list(html))
            return {'list': videos, 'page': pg, 'pagecount': 9999,
                    'limit': 60, 'total': 999999}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 60, 'total': 0}

    # ---------------- 详情页（解析流式 JSON） ----------------

    def _js_field(self, html, key):
        """从流式 JSON 里取字符串字段，兼容 \\" 转义"""
        m = re.search(r'(?<![\w$])%s:"((?:[^"\\]|\\.)*)"' % key, html)
        if not m:
            return ''
        return m.group(1).replace('\\"', '"').replace('\\/', '/').replace('\\\\', '\\')

    def detailContent(self, ids):
        try:
            raw = ids[0] if isinstance(ids, (list, tuple)) else ids
            raw = str(raw)
            if raw.startswith('http'):
                url = raw
            elif '|' in raw:
                src, vid = raw.split('|', 1)
                url = '%s/watch?source=%s&id=%s' % (self.host, src, vid)
            else:
                return {'list': []}
            html = self._get(url)
            if not html or 'episodes:' not in html:
                return {'list': []}
            # 锚定到影片对象内部（元数据字段都排在 episodes: 之前），避免误命中路由 manifest 里的同名字段
            pos = html.find('episodes:')
            seg = html[max(0, pos - 4000):pos + 8000]

            name = self._js_field(seg, 'title')
            poster = self._js_field(seg, 'poster')
            # 剧集：{name:"HD中字",url:"https://…/index.m3u8"}（url 即真实播放地址）
            eps = re.findall(r'\{name:"((?:[^"\\]|\\.)*)",url:"((?:[^"\\]|\\.)*)"\}', seg)
            episodes = [(re.sub(r'<[^>]+>', '', n).strip() or ('第%d集' % (i + 1)),
                         u.replace('\\/', '/').replace('&amp;', '&'))
                        for i, (n, u) in enumerate(eps)]

            source_name = self._js_field(seg, 'sourceName') or 'ZIP0'
            video = {
                'vod_id': raw,
                'vod_name': name,
                'vod_pic': self._abs(poster),
                'vod_year': self._js_field(seg, 'year'),
                'vod_area': self._js_field(seg, 'area'),
                'vod_actor': self._js_field(seg, 'actors'),
                'vod_director': self._js_field(seg, 'director'),
                'vod_remarks': self._js_field(seg, 'remarks'),
                'vod_content': self._js_field(seg, 'description'),
                'vod_play_from': source_name,
                'vod_play_url': '#'.join(['%s$%s' % (n, u) for n, u in episodes]) or '#',
            }
            return {'list': [video]}
        except Exception as e:
            self.log('detailContent error:', e)
            return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        """detailContent 里 episodes[].url 就是直链 m3u8（ffzy / zy360 等实测 200 可拉取，无需 Referer）"""
        try:
            url = id if isinstance(id, str) else str(id)
            if not re.match(r'https?://', url) and not url.startswith('magnet:'):
                url = self._abs(url)
            return {
                'parse': 0,
                'url': url.replace('&amp;', '&'),
                'header': dict(self.headers),
            }
        except Exception as e:
            self.log('playerContent error:', e)
            return {'parse': 0, 'url': id if isinstance(id, str) else str(id),
                    'header': dict(self.headers)}

    # ---------------- 搜索（TanStack serverFn + seroval 序列化） ----------------

    def _srl_enc(self, v, box):
        if isinstance(v, bool):
            return {'t': 2, 's': 2 if v else 3}
        if isinstance(v, str):
            return {'t': 1, 's': v}
        if v is None:
            return {'t': 2, 's': 0}
        if isinstance(v, (int, float)):
            return {'t': 0, 's': v}
        if isinstance(v, dict):
            box[0] += 1
            return {'t': 10, 'i': box[0],
                    'p': {'k': list(v.keys()),
                          'v': [self._srl_enc(x, box) for x in v.values()]}}
        if isinstance(v, (list, tuple)):
            box[0] += 1
            return {'t': 9, 'i': box[0], 'a': [self._srl_enc(x, box) for x in v]}
        return {'t': 1, 's': str(v)}

    def _srl_dec(self, n, depth=0):
        if not isinstance(n, dict) or depth > 30:
            return n
        t = n.get('t')
        if t in (0, 1):          # 数字 / 字符串
            return n.get('s')
        if t == 2:               # 常量
            return {0: None, 1: None, 2: True, 3: False, 4: 0,
                    5: float('inf'), 6: float('-inf'), 7: float('nan')}.get(n.get('s'))
        if t == 3:               # BigInt
            return n.get('s')
        if t == 9:               # 数组
            return [self._srl_dec(x, depth + 1) for x in (n.get('a') or [])]
        if t in (10, 11):        # 对象（10 = Object 原型，11 = null 原型）
            p = n.get('p') or {}
            return dict(zip(p.get('k') or [],
                            [self._srl_dec(x, depth + 1) for x in (p.get('v') or [])]))
        return None

    def _search_one(self, fid, key, source):
        box = [0]
        node = self._srl_enc({'data': {'area': 'all', 'type': 'all', 'year': 'all',
                                       'query': key, 'source': source}}, box)
        payload = json.dumps({'t': node, 'f': 127, 'm': []},
                             ensure_ascii=False, separators=(',', ':'))
        url = '%s/_serverFn/%s?payload=%s' % (self.host, fid,
                                              urllib.parse.quote(payload, safe=''))
        # WAF 校验这些头，缺任一个都会 403
        headers = dict(self.headers)
        headers.update({
            'x-tsr-serverFn': 'true',
            'accept': 'application/x-tss-framed, application/x-ndjson, application/json',
            'Origin': self.host,
            'Referer': self.host + '/search',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
        })
        html = self.fetch(url, headers=headers).text
        obj = json.loads(html)
        res = self._srl_dec(obj)
        return ((res or {}).get('result') or {}).get('items') or []

    def _discover_fid(self):
        """站点重新构建后 serverFn hash 会变：从 video.functions 包里重新找候选 id"""
        try:
            html = self._get(self.host + '/search')
            m = re.search(r'/assets/video\.functions-[A-Za-z0-9_\-]+\.js', html)
            if not m:
                return []
            js = self._get(self.host + m.group(0))
            return [x for x in re.findall(r'`([0-9a-f]{64})`', js) if x != self.SEARCH_FID]
        except Exception as e:
            self.log('discover fid error:', e)
            return []

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg > 1:
            return {'list': [], 'page': pg}
        try:
            seen, videos = set(), []
            for src in self.search_sources:
                items = []
                try:
                    items = self._search_one(self._fid_cache, key, src)
                except Exception as e:
                    self.log('search error:', src, e)
                    for fid in (self._discover_fid() if src == self.search_sources[0] else []):
                        try:
                            items = self._search_one(fid, key, src)
                            if items:
                                self._fid_cache = fid
                                self.log('search fid 已更新为', fid)
                                break
                        except Exception:
                            continue
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    title = (it.get('title') or '').strip()
                    if not title or title in seen:
                        continue
                    seen.add(title)
                    videos.append({
                        'vod_id': '%s|%s' % (it.get('source'), it.get('id')),
                        'vod_name': title,
                        'vod_pic': self._abs(it.get('poster') or ''),
                        'vod_remarks': it.get('remarks') or it.get('year') or '',
                    })
            return {'list': videos, 'page': pg}
        except Exception as e:
            self.log('searchContent error:', e)
            return {'list': [], 'page': pg}

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
    print('=== homeVideoContent ===')
    hv = sp.homeVideoContent()
    print('  %d 项' % len(hv['list']), hv['list'][0] if hv['list'] else None)
    print()
    print('=== categoryContent（全部分类）===')
    for c in r['class']:
        r2 = sp.categoryContent(c['type_id'], 1, {}, {})
        print('  %-6s: %3d 项 | 例: %s %s' % (c['type_name'], len(r2['list']),
                                             r2['list'][0]['vod_id'] if r2['list'] else '-',
                                             r2['list'][0]['vod_name'] if r2['list'] else ''))
    print()
    print('=== 翻页（第2页必须与第1页不同）===')
    first_tid = r['class'][0]['type_id']
    p1 = sp.categoryContent(first_tid, 1, {}, {})
    p2 = sp.categoryContent(first_tid, 2, {}, {})
    if p1['list'] and p2['list']:
        print('  p1 first:', p1['list'][0]['vod_id'], '| p2 first:', p2['list'][0]['vod_id'])
        print('  两组前3项是否不同:', [x['vod_id'] for x in p1['list'][:3]] !=
              [x['vod_id'] for x in p2['list'][:3]])
    print()
    print('=== 兼容性：字符串 pg / 字符串 extend ===')
    print('  str pg:', len(sp.categoryContent(first_tid, '1', {}, {})['list']), '项')
    print('  str extend:', len(sp.categoryContent(first_tid, 1, {}, '{}')['list']), '项')
    print()
    print('=== searchContent ===')
    s = sp.searchContent('罪火', False, 1)
    print('  %d 项' % len(s['list']))
    for v in s['list'][:5]:
        print('    ', v['vod_id'], v['vod_name'], '|', v['vod_remarks'])
    print('  str pg:', len(sp.searchContent('罪火', False, '1')['list']), '项')
    print()
    print('=== detailContent（电影，单集）===')
    if p1['list']:
        r3 = sp.detailContent([p1['list'][0]['vod_id']])
        if r3['list']:
            v = r3['list'][0]
            print('  vid:', v['vod_id'], '| name:', v['vod_name'], '| year:', v['vod_year'],
                  '| area:', v['vod_area'], '| 线路:', v['vod_play_from'])
            print('  分类:', r3['list'][0]['vod_remarks'], '| 导演:', v['vod_director'][:40])
            print('  演员:', v['vod_actor'][:60])
            print('  海报:', v['vod_pic'][:90])
            eps = v['vod_play_url'].split('#')
            print('  集数:', len(eps), '| 首集:', eps[0][:90])
            print()
            print('=== playerContent ===')
            r4 = sp.playerContent(v['vod_play_from'], eps[0].split('$', 1)[1], None)
            print('  parse:', r4['parse'], '| url:', r4['url'][:120])
    print()
    print('=== detailContent（电视剧，多集）===')
    tv = sp.categoryContent('tv', 1, {}, {})
    for item in tv['list'][:6]:
        r5 = sp.detailContent([item['vod_id']])
        if r5['list']:
            v = r5['list'][0]
            eps = v['vod_play_url'].split('#')
            if len(eps) > 1:
                print('  vid:', v['vod_id'], '| name:', v['vod_name'], '| 线路:', v['vod_play_from'],
                      '| 集数:', len(eps))
                print('    首集:', eps[0][:90])
                print('    末集:', eps[-1][:90])
                r6 = sp.playerContent(v['vod_play_from'], eps[2].split('$', 1)[1], None)
                print('    player(第3集) parse:', r6['parse'], '| url:', r6['url'][:110])
                break
    print()
    print('=== 详情异常输入 ===')
    print('  乱码 id:', sp.detailContent(['badid'])['list'])


if __name__ == '__main__':
    main()
