# coding=utf-8
# !/usr/bin/python
"""
在线之家 www.zxzj.run —— TVBox Python 蜘蛛（py 源，按 base.spider.Spider 格式编写）

站点：苹果 CMS + stui 主题，无 WAF，路由全标准
    · 分类  /vodtype/{分类id}-{页码}.html          （每页 12 条）
    · 列表  /vodshow/{分类id}-{地区}-{排序}-{剧情}-{语言}…-{页码}.html
    · 详情  /voddetail/{id}.html
    · 播放  /vodplay/{id}-{线路}-{集}.html
    · 搜索  /vodsearch/-------------.html?wd={关键词}   ← 关键词必须 UTF-8 编码

挂载方法（TVBox 配置里加一条，api 指向本文件路径或可访问的 URL）：
    {"key":"zxzj_py","name":"在线之家","type":3,"api":"在线之家zxzj.py",
     "searchable":1,"quickSearch":1,"filterable":1}
"""

import os
import re
import json
import sys
import urllib.parse

# 影视仓 / 部分 TVBox 构建加载 py 时工作目录不同, 裸导入 base 会抛
# ModuleNotFoundError → 整个源加载失败 → 主页连源名都看不到、搜索也进不去。
# 先补路径, 再在导入失败时提供最简网络基类, 保证源一定能加载出来。
try:
    sys.path.append("..")
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
except Exception:
    pass

try:
    from base.spider import Spider
except Exception:
    import urllib.request as _ur

    class Spider(object):

        def fetch(self, url, headers=None, timeout=10, **kw):
            req = _ur.Request(url, headers=headers or {})
            op = _ur.build_opener(_ur.ProxyHandler({}))   # 显式清代理, 避免 502 假阴性
            with op.open(req, timeout=timeout) as r:
                body = r.read()
                resp = type("Resp", (), {})()
                resp.content = body
                resp.text = body.decode("utf-8", "replace")
                resp.status_code = getattr(r, "status", 200)
                resp.headers = dict(r.headers)
                return resp


class Spider(Spider):

    HOST = "https://www.zxzj.run"
    host = HOST          # 宿主若不调用 init 也能工作, 避免 self.host 缺失导致全空

    # 导航分类（分类id, 名称）
    CLASSES = [("1", "电影"), ("2", "美剧"), ("3", "韩剧"),
               ("4", "日剧"), ("5", "泰剧"), ("6", "动漫")]

    # 筛选维度名 -> extend 的键
    DIM_KEY = {"剧情": "class", "类型": "class", "地区": "area",
               "语言": "lang", "年份": "year", "排序": "sort"}

    # /vodshow/ 路由的字段位序（实测破译）：1=地区 2=排序 3=剧情 4=语言，其余留空
    DIM_POS = {"area": 0, "sort": 1, "class": 2, "lang": 3}

    # 网盘线路关键词（TVBox 播不了，只看在线线路）
    PAN_WORDS = ("网盘", "云盘", "夸克", "迅雷", "磁力", "ed2k", "百度")

    # 网盘/离线域名（这些链接不是自建解析播放器，别去解析）
    PAN_HOSTS = ("pan.baidu.com", "yunpan", "quark.cn", "xunlei", "aliyundrive",
                 "alipan", "123pan", "caiyun", "115.com", "mypikpak", "uc.cn")

    # 筛选项静态内置(取自站点 /vodtype/ 页实测)。
    # ★ homeContent 在 TVBox 加载源时是同步调用的, 原实现现场并发抓 6 个分类页
    #   实测耗时 7~12s 且常有几个请求失败 → 首页一直转圈 / 源不显示、搜索也进不去。
    #   现在改为零网络请求的静态数据, 站点改版时可手动调 _build_filters_live() 重新采集。
    FILTER_NAMES = {"class": "剧情", "area": "地区"}
    FILTER_DATA = {
        "1": {"class": "喜剧 爱情 恐怖 动作 科幻 剧情 战争 警匪 犯罪 动画 奇幻 冒险",
              "area": "大陆 香港 台湾 欧美 韩国 日本 泰国 印度 俄罗斯 其他"},
        "2": {"class": "剧情 喜剧 爱情 动作 悬疑 恐怖 奇幻 惊悚 犯罪 科幻 音乐 其他",
              "area": "欧美"},
        "3": {"class": "剧情 喜剧 爱情 动作 悬疑 恐怖 奇幻 惊悚 犯罪 科幻 音乐 其他",
              "area": "韩国"},
        "4": {"class": "剧情 喜剧 爱情 动作 悬疑 恐怖 奇幻 惊悚 犯罪 科幻 音乐 其他",
              "area": "日本"},
        "6": {"class": "情感 科幻 热血 推理 搞笑 冒险 萝莉 校园 动作 机战 运动 战争 少年",
              "area": "国产 日本 欧美 其他"},
    }

    UA_MOBILE = ("Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")

    # ------------------------------------------------------------------ 生命周期

    def getName(self):
        return "在线之家"

    def init(self, extend=""):
        """extend 可传自定义域名：直接给 https://xxx ，或 {"host":"https://xxx"}（站点换域名时不用改文件）"""
        self.host = self.HOST
        self._filter_cache = None
        ext = (extend or "").strip()
        if ext:
            try:
                if ext.startswith("{"):
                    d = json.loads(ext)
                    if isinstance(d, dict) and d.get("host"):
                        self.host = str(d["host"]).rstrip("/")
                elif ext.startswith("http"):
                    self.host = ext.rstrip("/")
            except Exception:
                pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ------------------------------------------------------------------ 网络层

    def _hdr(self):
        return {
            "User-Agent": self.UA_MOBILE,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def _req(self, url, headers=None, timeout=15, allow_redirects=True):
        """兼容不同 py 宿主的 self.fetch 签名"""
        h = self._hdr()
        if headers:
            h.update(headers)
        tries = [{"headers": h, "timeout": timeout, "allow_redirects": allow_redirects},
                 {"headers": h, "timeout": timeout},
                 {"headers": h}]
        for kw in tries:
            try:
                return self.fetch(url, **kw)
            except TypeError:
                continue
            except Exception:
                return None
        return None

    def _text(self, url, headers=None, timeout=15):
        """兼容各版本宿主 fetch 的返回类型: str / bytes / Response(.text / .content)。
        部分 TVBox 构建的 fetch 直接返回字符串, 只认 .text 会让所有页面变成空串。"""
        r = self._req(url, headers=headers, timeout=timeout)
        if isinstance(r, bytes):
            return r.decode("utf-8", "ignore")
        if isinstance(r, str):
            return r
        if r is None:
            return ""
        t = getattr(r, "text", None)
        if isinstance(t, bytes):
            t = t.decode("utf-8", "ignore")
        if t is None:
            try:
                c = getattr(r, "content", None)
                t = c.decode("utf-8", "ignore") if isinstance(c, bytes) else (c or "")
            except Exception:
                t = ""
        return t or ""

    # ------------------------------------------------------------------ 解析工具

    @staticmethod
    def _one(pat, text, idx=1):
        m = re.search(pat, text or "", re.S)
        if not m:
            return ""
        try:
            return m.group(idx).strip()
        except Exception:
            return ""

    @staticmethod
    def _clean(s):
        s = re.sub(r"<[^>]+>", "", s or "")
        return re.sub(r"\s+", " ", s).replace("&nbsp;", " ").strip()

    @staticmethod
    def _is_media(u):
        if not u:
            return False
        low = u.lower()
        return (".m3u8" in low) or (".mp4" in low) or (".flv" in low)

    # 列表卡片：首页 / 分类页 / 搜索页三处共用同一套 DOM
    def _parse_cards(self, html):
        out, seen = [], set()
        for blk in re.findall(r'(?s)<div class="stui-vodlist__box">(.*?)</li>', html or ""):
            href = self._one(r'href="(/voddetail/[^"]+)"', blk)
            name = self._one(r'title="([^"]*)"', blk)
            if not href or not name:
                continue
            vid = self._one(r'/voddetail/(\d+)', href) or href
            if vid in seen:
                continue
            seen.add(vid)
            pic = self._one(r'data-original="([^"]*)"', blk) or self._one(r'src="([^"]*)"', blk)
            out.append({
                "vod_id": vid,
                "vod_name": self._clean(name),
                "vod_pic": pic,
                "vod_remarks": self._clean(self._one(r'class="pic-text[^"]*">([^<]*)<', blk)),
            })
        return out

    # ------------------------------------------------------------------ 首页

    def homeContent(self, filter):
        # ★ 必须瞬时返回、绝不联网: TVBox 加载源时同步调用本方法,
        #   原来现场并发抓 6 个分类页(7~12s, 还常丢几个)会让首页一直转圈。
        result = {"class": [{"type_id": t, "type_name": n} for t, n in self.CLASSES],
                  "filters": {}}
        try:
            result["filters"] = self._filters()
        except Exception:
            pass
        return result

    def _filters(self):
        """静态筛选项, 零网络请求; 结果缓存, 且不依赖 init 是否被调用。"""
        if getattr(self, "_filter_cache", None) is None:
            f = {}
            try:
                for tid, dims in self.FILTER_DATA.items():
                    arr = []
                    for key in ("class", "area"):
                        vals = (dims.get(key) or "").split()
                        if vals:
                            arr.append({"key": key, "name": self.FILTER_NAMES[key],
                                        "value": [{"n": v, "v": v} for v in vals]})
                    if arr:
                        f[tid] = arr
            except Exception:
                f = {}
            self._filter_cache = f
        return self._filter_cache

    def homeVideoContent(self):
        html = self._text(self.host + "/", timeout=15)
        return {"list": self._parse_cards(html)}

    def _build_filters_live(self):
        """可选: 站点改版后需重新采集筛选项时手动调用, 不在 homeContent 里跑。"""
        tasks = [t for t, _ in self.CLASSES]
        pages = {}
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
                for tid, html in zip(tasks, ex.map(self._type_page, tasks)):
                    pages[tid] = html
        except Exception:
            for tid in tasks:
                pages[tid] = self._type_page(tid)

        filters = {}
        for tid, html in pages.items():
            fs = self._parse_filter_bar(html)
            if fs:
                filters[tid] = fs
        return filters

    def _type_page(self, tid):
        return self._text("%s/vodtype/%s.html" % (self.host, tid), timeout=12)

    def _parse_filter_bar(self, html):
        out = []
        for ul in re.findall(r'(?s)<ul class="clearfix">(.*?)</ul>', html or ""):
            label = self._clean(self._one(r"<span>(.*?)</span>", ul))
            label = label.replace("：", "").replace(":", "").replace("按", "").strip()
            if not label:
                continue
            key = self.DIM_KEY.get(label)
            if not key or key not in self.DIM_POS:
                continue          # 年份位不支持翻页，直接跳过（见 categoryContent 说明）
            vals = []
            for href, name in re.findall(r'<a href="(/vodshow/[^"]+)">([^<]*)</a>', ul):
                name = self._clean(name)
                if not name or name == "全部":
                    continue
                # 只保留「尾部破折号 >= 3」即可以拼页码的项
                if not self._pageable(href):
                    continue
                vals.append({"n": name, "v": name})
            if vals:
                out.append({"key": key, "name": label, "value": vals})
        # 同一个 key 只留一份
        seen, uniq = set(), []
        for f in out:
            if f["key"] in seen:
                continue
            seen.add(f["key"])
            uniq.append(f)
        return uniq

    @staticmethod
    def _pageable(href):
        body = href[len("/vodshow/"):-len(".html")] if href.endswith(".html") else ""
        return len(body) - len(body.rstrip("-")) >= 3

    # ------------------------------------------------------------------ 分类

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1

        url = self._category_url(tid, pg, extend)
        vlist = self._parse_cards(self._text(url, timeout=15))
        return {"list": vlist, "page": pg, "pagecount": 9999,
                "limit": 90, "total": 999999}

    def _category_url(self, tid, pg, extend):
        ext = extend if isinstance(extend, dict) else {}
        # 选了筛选 -> 走 /vodshow/ 路由
        picked = {}
        for k, v in ext.items():
            if k in self.DIM_POS and v:
                picked[k] = str(v)
        if picked:
            fields = [""] * 11
            for k, v in picked.items():
                fields[self.DIM_POS[k]] = urllib.parse.quote(v)
            body = str(tid) + "-" + "-".join(fields)
            if pg > 1:
                body = body[:-3] + str(pg) + "---"   # 实测：末尾 3 个破折号换成「页码 + ---」
            return "%s/vodshow/%s.html" % (self.host, body)
        # 未筛选 -> 走最干净的 /vodtype/ 路由
        suffix = "" if pg <= 1 else "-%d" % pg
        return "%s/vodtype/%s%s.html" % (self.host, tid, suffix)

    # ------------------------------------------------------------------ 详情

    def detailContent(self, ids):
        vid = str(ids[0]).strip() if ids else ""
        if not vid:
            return {"list": []}
        html = self._text("%s/voddetail/%s.html" % (self.host, vid), timeout=15)
        if not html:
            return {"list": []}

        name = self._one(r'<h1 class="title">(.*?)</h1>', html) \
            or self._one(r"<title>(.*?)</title>", html)
        pic = self._one(r'<div class="stui-content__thumb">.*?data-original="([^"]+)"', html) \
            or self._one(r'data-original="([^"]+)"', html)
        brief = self._one(r'<span class="detail-content"[^>]*>(.*?)</span>', html) \
            or self._one(r'<span class="detail-sketch">(.*?)</span>', html)

        video = {
            "vod_id": vid,
            "vod_name": self._clean(name),
            "vod_pic": pic,
            "vod_content": self._clean(brief),
            "vod_year": self._clean(self._one(r"年份：(.*?)</p>", html)),
            "vod_area": self._clean(self._one(r"地区：(.*?)(?:\s*/|</)", html)),
            "type_name": self._clean(self._one(r"类型：(.*?)(?:\s*/|</)", html)),
            "vod_actor": self._clean(self._one(r"主演：(.*?)</p>", html)),
            "vod_director": self._clean(self._one(r"导演：(.*?)</p>", html)),
            "vod_remarks": self._clean(self._one(r"更新：(\d{4}-\d{2}-\d{2})", html)),
        }

        groups = re.findall(
            r'(?s)<div class="stui-vodlist__head">.*?<h3>(.*?)</h3></div>\s*'
            r'<ul class="stui-content__playlist[^"]*">(.*?)</ul>', html)

        names, lists = [], []
        for gname, gbody in groups:
            gname = self._clean(gname)
            eps = re.findall(r'<a[^>]*href="(/vodplay/[^"]+)"[^>]*>(.*?)</a>', gbody, re.S)
            if not eps:
                continue
            names.append(gname)
            lists.append("#".join("%s$%s" % (self._clean(t), self.host + u) for u, t in eps))

        # 网盘线路单独剥离（TVBox 播不了网盘）；只有网盘时才原样保留
        keep_n, keep_l = [], []
        for n, l in zip(names, lists):
            if any(w in n for w in self.PAN_WORDS):
                continue
            keep_n.append(n)
            keep_l.append(l)
        if not keep_n and names:
            keep_n, keep_l = names, lists
            video["vod_remarks"] = (video["vod_remarks"] + "（仅网盘线路）").strip()

        video["vod_play_from"] = "$$$".join(keep_n)
        video["vod_play_url"] = "$$$".join(keep_l)
        return {"list": [video]}

    # ------------------------------------------------------------------ 搜索

    def searchContent(self, key, quick, pg=1):
        result = {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}
        try:
            try:
                pg = int(pg or 1)
            except Exception:
                pg = 1
            if pg > 1:
                return {"list": [], "page": pg, "pagecount": 1,
                        "limit": 0, "total": 0}   # 站点搜索无翻页
            key = (key or "").strip()
            if not key:
                return result                    # 空词站点会回退成"最新更新"，直接拦掉
            # 关键词必须 UTF-8; GBK 会返回 12 条不相关的"最新更新"
            wd = urllib.parse.quote(key.encode("utf-8"))
            html = self._text("%s/vodsearch/-------------.html?wd=%s" % (self.host, wd),
                              timeout=15)
            lst = self._parse_cards(html)
            return {"list": lst, "page": 1, "pagecount": 1,
                    "limit": len(lst), "total": len(lst)}
        except Exception:
            return result

    def searchContentPage(self, key, quick, pg=1):
        # 部分宿主翻页时调这个方法, 转给标准实现即可
        return self.searchContent(key, quick, pg)

    # ------------------------------------------------------------------ 播放

    def playerContent(self, flag, id, vipFlags):
        url = (id or "").strip()
        if url and not url.startswith("http"):
            url = self.host + ("/" + url.lstrip("/") if not url.startswith("/") else url)

        # 已经是直链
        if self._is_media(url):
            return {"parse": 0, "url": url, "header": {"User-Agent": self.UA_MOBILE}}

        play_page = url
        if "/vodplay/" in url or "/voddetail/" in url:
            html = self._text(url, timeout=15)
            pu = self._player_url(html)
            if pu:
                if self._is_media(pu):
                    return {"parse": 0, "url": pu, "header": {"User-Agent": self.UA_MOBILE}}
                if any(d in pu.lower() for d in self.PAN_HOSTS):
                    # 网盘/离线直链：原样给出（TVBox 播不了，但至少是真地址）
                    return {"parse": 0, "url": pu, "header": {"User-Agent": self.UA_MOBILE}}
                real = self._resolve_player(pu)
                if real:
                    return {"parse": 0, "url": real,
                            "header": {"User-Agent": self.UA_MOBILE}}

        # 兜底：交回播放页，让 TVBox 自己再解析/嗅探一次
        # （自建解析器由服务端 SSR 注入地址，客户端没有二次请求可截，只能这样）
        return {"parse": 1, "url": play_page,
                "header": {"User-Agent": self.UA_MOBILE, "Referer": self.host + "/"}}

    def _player_url(self, html):
        m = re.search(r"player_aaaa\s*=\s*(\{.*?\})\s*(?:<|;|\n)", html or "", re.S)
        if not m:
            return ""
        try:
            return (json.loads(m.group(1)).get("url") or "").strip()
        except Exception:
            return ""

    def _resolve_player(self, player_url):
        """自建解析播放器：服务端把结果以 result_v2 JSON 注入页面，照抄一次即可。
        注意 Sec-Fetch-* 三件套必须齐全，缺 Mode/Site 会被边缘直接 403（0 字节）。"""
        hdrs = {
            "Referer": self.host + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
        }
        body = self._text(player_url, headers=hdrs, timeout=15)
        if not body:
            return ""
        m = re.search(r"result_v2\s*=\s*(\{.*?\})\s*;", body, re.S)
        if not m:
            return ""
        try:
            d = json.loads(m.group(1))
        except Exception:
            return ""
        if isinstance(d, dict) and d.get("isSuccess") is False:
            return ""
        u = ""
        if isinstance(d, dict):
            u = d.get("url") or d.get("play_url") or ""
            if not u and isinstance(d.get("data"), dict):
                u = d["data"].get("url") or d["data"].get("play_url") or ""
        u = (u or "").strip()
        return u if self._is_media(u) else ""

    # ------------------------------------------------------------------ 本地代理（备用）

    def localProxy(self, param):
        try:
            raw = param.get("url") or ""
            pad = "=" * (-len(raw) % 4)
            import base64
            u = base64.urlsafe_b64decode(raw + pad).decode("utf-8")
        except Exception:
            return [404, "text/plain", ""]
        body = self._text(u, headers={"Referer": self.host + "/"})
        return [200, "application/vnd.apple.mpegurl", body]
