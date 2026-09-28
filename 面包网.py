# -*- coding: utf-8 -*-
"""
面包网 TVBox Python 源（影视仓 / OK影视）
站点：https://v.aiwule.com/  —— 苹果CMS(MacCMS) v10 + ewave 模板(/template/a_0012/)

实测结论（原始 HTML 抓包验证）
  列表  : /vodshow/{tid}-----------.html    翻页 /vodshow/{tid}--------{pg}---.html
  详情  : /voddetail/{vid}.html
  播放  : /vodplay/{vid}-{sid}-{eid}.html
  搜索  : GET /vodsearch/{wd}-------------.html（表单 action 即此；POST /vodsearch/ 为兜底）

  ewave 模板结构（重要，与 MacCMS 默认模板不同）：
    线路 tab  : <li class="swiper-slide ewave-tab" data-target="#ewave-playlist-2">无尽资源<em></em></li>
    选集容器  : .episode-box 内 <ul id="ewave-playlist-2" class="... ewave-playlist-content ...">
                每个 ul 一个线路，tab 的 data-target 与 ul 的 id 精确对应，无正/倒序重复容器
    集链接    : li.ewave-playlist-item > a  href="/vodplay/{vid}-{sid}-{eid}.html"
    元信息    : <span class="...">主演：<a>甲</a><a>乙</a>...</span>  （主演须收集全部 a 文本）
    完整简介  : 「内容简介」区块 <div class="more-box"><p>全文</p></div>
                （标题旁的 .text.text-row-2 是 CSS 截断版，meta description 也是截断版）
    立即播放  : 详情信息区 .btn-box > a[href=/vodplay/{vid}-1-1.html] —— 必须过滤，
                否则会被兜底扫描当成「线路1 第01集」混进选集（旧版 bug）

  分类（实测 <a href="/vodtype/{id}.html">）：
    电影20 电视剧21 动漫23 综艺22 短剧47
    动作24 喜剧25 爱情26 科幻27 恐怖28 剧情29 战争30 动画49
    国产31 香港32 韩国33 欧美34 台湾36 日本37 泰国38
    大陆综艺39 港台40 日韩41 欧美42 ；国产动漫43 日韩动漫44
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
        return '面包网'

    def log(self, *args):
        print('[面包网]', *args)

    def init(self, extend=''):
        self.host = 'https://v.aiwule.com'
        self.detail_re = r'/voddetail/\d+\.html'
        self.headers = {
            'User-Agent': UA,
            # 反盗链：播放与详情都必须带本站 Referer
            'Referer': self.host + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        # 分类（id 均来自站点导航实测 /vodtype/{id}.html）
        self.categories = {
            '电影': '20', '电视剧': '21', '综艺': '22', '动漫': '23', '短剧': '47',
            '动作片': '24', '喜剧片': '25', '爱情片': '26', '科幻片': '27',
            '恐怖片': '28', '剧情片': '29', '战争片': '30', '动画片': '49',
            '国产剧': '31', '港剧': '32', '韩剧': '33', '欧美剧': '34',
            '台剧': '36', '日剧': '37', '泰剧': '38',
            '大陆综艺': '39', '港台综艺': '40', '日韩综艺': '41', '欧美综艺': '42',
            '国产动漫': '43', '日韩动漫': '44',
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
        """提取「标签：值」。值在同一个 span 内，取到 </span> 为止；
        主演等多个 <a> 的字段把全部文本节点用「、」连接（旧版只取到第一个人）。"""
        m = re.search(label + r'\s*[:：]', html)
        if not m:
            return ''
        seg = html[m.end():m.end() + 3000]
        end = seg.find('</span>')
        e2 = seg.find('</p>')
        if end < 0 or (0 <= e2 < end):
            end = e2
        seg = seg[:end] if end >= 0 else re.sub(r'<[^>]*$', '', seg)  # 去掉截断的半个标签
        parts = [t.strip() for t in re.split(r'<[^>]+>', seg) if t.strip()]
        txt = '、'.join(parts)
        return self._clean_text(txt).strip('、 ')

    # -------------------------------------------------------------- 列表解析
    def _extract_list(self, html):
        """从列表页/搜索页提取条目。

        ewave 模板主列表结构（实测）：
          <li><div class="pic"><a href="/voddetail/x.html" title="名">
            <div class="img-wrapper lazyload" data-original="封面" ...></div></a></div>
          <div class="name"><h3><a title="名">名</a></h3><p class="item-status">更新至第38集</p></div></li>
        要点：封面是 div.img-wrapper 的 data-original，没有 <img> 标签；
        「热门排行」等侧栏条目（hot-item，无 title 无封面）必须排除；
        备注在 li 内的 p.item-status 里。
        """
        data, order = {}, []
        for m in re.finditer(r'(?is)<a\b[^>]*href="([^"]*' + self.detail_re + r')"[^>]*>', html):
            vid = m.group(1)
            tag = m.group(0)
            seg = html[m.start():m.start() + 1200]
            li_end = seg.find('</li>')  # 截到条目边界，防止吸到下一个条目
            if li_end > 0:
                seg = seg[:li_end]
            # 只认带封面的条目（主列表/搜索结果），排除排行榜、侧栏纯文字链接
            if ('img-wrapper' not in seg) and ('<img' not in seg.lower()):
                continue
            title = self._attr(tag, 'title')
            pic = (self._attr(tag, 'data-original') or self._attr(tag, 'data-src')
                   or self._attr(tag, 'data-echo'))
            it = re.search(r'(?is)<(?:img|div)\b[^>]*(?:data-original|data-src|data-echo|alt)="[^"]*"[^>]*>', seg)
            if it:
                src = (self._attr(it.group(0), 'data-original') or self._attr(it.group(0), 'data-src')
                       or self._attr(it.group(0), 'data-echo'))
                if not src:
                    src = self._attr(it.group(0), 'src')
                if src and 'load.gif' not in src:  # 跳过懒加载占位图
                    pic = pic or src
                if not title:
                    title = self._attr(it.group(0), 'alt')
            if not title:  # 标题旁的 h3 链接文本兜底
                t = re.search(r'(?is)<h3[^>]*>\s*<a[^>]*>([^<]{1,80})<', seg)
                title = t.group(1) if t else ''
            remark = ''
            rm = re.search(r'(?is)class="[^"]*(?:item-status|pic-text|module-item-note|note|remarks)[^"]*"[^>]*>([^<]{1,40})<', seg)
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
            if not rec['vod_name'] or not rec['vod_pic']:
                continue  # 无名/无封面的为杂项链接，丢弃
            out.append(rec)
        return out

    def _list_url(self, tid, pg):
        t = str(tid)
        if '/' in t or t.startswith('http'):
            return self._abs(t)
        if pg > 1:
            # 页码为第 9 字段（实测第 2 页：/vodshow/20--------2---.html）
            return '%s/vodshow/%s--------%d---.html' % (self.host, t, pg)
        return '%s/vodshow/%s-----------.html' % (self.host, t)

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
                    'limit': len(videos) or 36, 'total': 999999}
        except Exception as e:
            self.log('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 36, 'total': 0}

    # -------------------------------------------------------------- 选集解析
    # 选集区里的非剧集按钮（「立即播放/收藏」在详情信息区，「正序/倒序」是排序开关）
    _JUNK_TEXT = ('立即播放', '收藏', '正序', '倒序', '在线播放', '上一集', '下一集', '举报')

    def _eps(self, block):
        eps, seen = [], set()
        for m in re.finditer(r'(?is)<a\b[^>]*href="([^"]*?/(?:vodplay|play)/[^"]+?\.html)"[^>]*>(.*?)</a>', block):
            href, text = m.group(1), self._clean_text(m.group(2))
            if text in self._JUNK_TEXT:  # 过滤「立即播放」等按钮（按 href 精确重复也挡不住它，故按文字挡）
                continue
            if not text:
                eid = re.search(r'-(\d+)\.html$', href)
                text = '第%s集' % (eid.group(1) if eid else len(eps) + 1)
            url = self._abs(href)
            if url in seen:  # 同一线路内按链接去重
                continue
            seen.add(url)
            eps.append((text, url))
        return eps

    def _play_lists(self, html):
        """返回 (播放来源名列表, 每个来源的 集名$地址 列表)

        1) ewave 模板（本站）：tab <li data-target="#ewave-playlist-N">名</li>
           与 <ul id="ewave-playlist-N"> 精确配对，名字/顺序与网页一致；
        2) MacCMS 默认模板：名集中渲染在选集块之前，FIFO 取名；
        3) 兜底：全文扫描 /vodplay 链接按 sid 分组（已过滤「立即播放」等按钮）。
        """
        # --- 1) ewave：data-target -> tab 名 映射 ---
        tabmap = {}
        for m in re.finditer(r'(?is)<li[^>]*class="[^"]*ewave-tab[^"]*"[^>]*data-target="#([^"]+)"[^>]*>(.*?)</li>', html):
            t = self._clean_text(re.sub(r'(?is)<em[^>]*>.*?</em>', '', m.group(2)))
            if t:
                tabmap[m.group(1)] = t

        froms, groups = [], []
        names = []  # FIFO 队列（MacCMS 默认模板用）
        tok = re.compile(
            r'(?is)<ul\b[^>]*id="(ewave-playlist-[^"]+)"[^>]*>(.*?)</ul>'
            r'|<h[23][^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h[23]>'
            r'|data-dropdown-value="([^"]+)"'
            r'|<(ul|div)[^>]*class="[^"]*(?:module-play-list-content|stui-content__playlist)[^"]*"[^>]*>(.*?)</\5>'
        )
        for m in tok.finditer(html):
            if m.group(1) is not None:  # ewave 选集容器
                eps = self._eps(m.group(2) or '')
                if not eps:
                    continue
                froms.append(tabmap.get(m.group(1), '线路%d' % (len(froms) + 1)))
                groups.append(eps)
                continue
            if m.group(3) is not None or m.group(4) is not None:
                t = self._clean_text(m.group(3) or m.group(4))
                if t and len(t) <= 24:
                    names.append(t)
                continue
            eps = self._eps(m.group(6) or '')
            if not eps:
                continue
            # 去重：正序/倒序两个容器内容一致（仅顺序相反）时只保留一个
            if groups and sorted(e[1] for e in groups[-1]) == sorted(e[1] for e in eps):
                continue
            froms.append(names.pop(0) if names else ('线路%d' % (len(froms) + 1)))
            groups.append(eps)
        if froms:  # ewave/默认模板已命中
            return froms, groups
        # 兜底：全文扫描 /vodplay/{vid}-{sid}-{eid}.html，按 sid 分组
        buckets, order = {}, []
        for m in re.finditer(
                r'(?is)<a\b[^>]*href="([^"]*?/(?:vodplay|play)/\d+-(\d+)-(\d+)\.html)"[^>]*>(.*?)</a>', html):
            href, sid, eid, text = m.group(1), m.group(2), m.group(3), self._clean_text(m.group(4))
            if text in self._JUNK_TEXT:  # 「立即播放」按钮：勿混进选集
                continue
            if sid not in buckets:
                buckets[sid] = []
                order.append(sid)
            url = self._abs(href)
            if not any(u == url for _, u in buckets[sid]):
                buckets[sid].append((text or ('第%s集' % eid), url))
        froms, groups = [], []
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
            # 1) ewave「内容简介」区块（完整全文；标题旁 .text-row-2 与 meta description 都是截断版）
            dm = re.search(r'(?is)<div[^>]*class="[^"]*more-box[^"]*"[^>]*>\s*<p[^>]*>(.*?)</p>', html)
            if dm:
                desc = self._clean_text(dm.group(1))
            if not desc:
                dm = re.search(r'(?is)<div[^>]*class="[^"]*module-info-introduction-content[^"]*"[^>]*>(.*?)</div>', html)
                if dm:
                    desc = self._clean_text(dm.group(1))
            if not desc:
                dm = re.search(r'(?is)<span[^>]*class="[^"]*detail-content[^"]*"[^>]*>(.*?)</span>', html)
                if dm:
                    desc = self._clean_text(dm.group(1))
            if not desc:
                dm = re.search(r'(?is)<meta[^>]*name="description"[^>]*content="([^"]*)"', html)
                desc = self._clean_text(dm.group(1)) if dm else ''

            froms, groups = self._play_lists(html)
            play_from = '$$$'.join(froms) if froms else '面包网'
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

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)  # app 可能传字符串
        except Exception:
            pg = 1
        if pg > 1:  # 搜索结果页无分页
            return {'list': [], 'page': pg}
        try:
            # 1) GET 路径式搜索（页面表单 action 即 /vodsearch/-------------.html）
            url = '%s/vodsearch/%s-------------.html' % (self.host, urllib.parse.quote(key))
            try:
                html = self.fetch(url, headers=self.headers).text
            except Exception:
                html = ''
            videos = self._extract_list(html) if html else []
            # 2) POST /vodsearch/ 兜底
            if not videos:
                html = self._search_post('/vodsearch/', {'wd': key, 'submit': 'search'}, self.detail_re)
                videos = self._extract_list(html)
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
            if re.search(r'/(?:vodplay|play)/', url):
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
            print('  name:', v['vod_name'], '| 来源:', v['vod_play_from'], '| 首源集数:', len(plays[0].split('#')))
            print('  主演:', v['vod_actor'], '| 导演:', v['vod_director'])
            print('  简介:', (v['vod_content'] or '')[:60])
            print()
            print('=== playerContent ===')
            if plays and plays[0] != '#':
                r4 = sp.playerContent(v['vod_play_from'], plays[0].split('$', 1)[1], None)
                print('  parse:', r4['parse'], '| url:', r4['url'][:80])


if __name__ == '__main__':
    main()
