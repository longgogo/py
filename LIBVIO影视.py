# coding=utf-8
# LIBVIO 影视 TVBox Python 蜘蛛（py 源）
# 站点：苹果CMS + stui 默认主题，全站套「x-cdn-challenge: js-pow」挑战
# 关键：挑战为明文 SHA-256 PoW，解一次拿 __cdn_verified cookie（Max-Age=1800），
#       本源内置解算 + TTL 缓存 + 遇挑战自动重解，TVBox 侧完全无感。
# 域名（2026-09-28 依官方发布页 libvio.app/all.html 实测）：
#   · 主入口 www.libviohd.com（挑战+PoW 链路全通），备用 libvio.in / libvio.pw / libvio.to
#   · libvio.run/.mov/.cc/.la/.me/.site/.art/.vip/.cloud/.link 已全部挂「域名停用通知」假站
#   · libvioo.com.de 是全新架构（/movie/{hash}.html 新路由），旧规则不适用，勿用
#   · 旧默认 libvio.to 只是发布页上的「备用线路 03」，国内大概率连不上 —— 本次失效根因
#   · 本源按候选顺序自动切换域名，PoW cookie 按域名各自解算隔离
import re
import json
import time
import hashlib
import urllib.parse

from base.spider import Spider

# 候选域名（实测可走通 PoW 链路的，按发布页主入口优先排序）
_HOSTS = ["https://www.libviohd.com", "https://www.libvio.in",
          "https://www.libvio.pw", "https://www.libvio.to"]
UA = "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36"
# 挑战页只在「像浏览器」的请求上返回完整 PoW 脚本
_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
# 有效分类（其余 type id 在站点里无展示名，属"幽灵分类"，不收录）
_CATS = [("1", "电影"), ("2", "剧集"), ("4", "番剧"),
         ("13", "国剧"), ("15", "日韩"), ("16", "欧美"), ("21", "纪录片")]
# cookie 有效期 1800s，缓存 1400s 留足余量
_CK_TTL = 1400


def _raw(url, cookie=None, headers=None, timeout=20):
    """原始请求（仅解算 WAF 用）。显式清空代理，避免代理环境假阴性。
    urllib.request/error 延迟到此导入，让模块加载更轻（TVBox 加载有超时）。"""
    import urllib.request
    import urllib.error
    req = urllib.request.Request(url)
    for k, v in (headers or _BROWSER).items():
        req.add_header(k, v)
    if cookie:
        req.add_header("Cookie", cookie)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(req, timeout=timeout) as r:
            return r.getcode(), dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read().decode("utf-8", "replace")


def _chal(txt):
    g = lambda p: (re.search(p, txt).group(1) if re.search(p, txt) else None)
    return {"TS": g(r'TS\s*=\s*"([^"]+)"'), "SIG": g(r'SIG\s*=\s*"([^"]+)"'),
            "DIFF": g(r'DIFF\s*=\s*"([^"]+)"'), "MODE": g(r'MODE\s*=\s*"([^"]+)"'),
            "POW": g(r'POW\s*=\s*"([^"]+)"')}


def _pow(sig, diff, limit=50000000):
    i = 0
    while i < limit:
        if hashlib.sha256((sig + str(i)).encode()).hexdigest().startswith(diff):
            return i
        i += 1
    return None


class Spider(Spider):

    def getName(self):
        return "LIBVIO"

    def init(self, extend=""):
        hosts = list(_HOSTS)
        if extend:
            e = str(extend).strip()
            if e.startswith("http"):
                # 用户在配置里手动指定域名时，优先用它，其余作为后备
                hosts = [e.rstrip("/")] + [h for h in _HOSTS if h != e.rstrip("/")]
        self._hosts = hosts
        self._hi = 0
        self.host = hosts[0]
        self._ck = None
        self._ck_host = None
        self._ck_t = 0

    def isVideoFormat(self, url):
        return bool(url) and bool(re.search(r"\.(m3u8|mp4)(\?|$)", url))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ---------------- WAF：js-pow 解算 ----------------
    def _solve(self):
        home = self.host + "/"
        try:
            code, hdr, txt = _raw(home)
        except Exception:
            return None
        info = _chal(txt)
        if not info.get("SIG"):
            return None
        n = _pow(info["SIG"], info["DIFF"])
        if n is None:
            return None
        ck0 = "%s=%s_%s_%s_%s" % (info["POW"], info["TS"], info["MODE"], n, info["SIG"])
        try:
            code, hdr, txt = _raw(home, cookie=ck0)
        except Exception:
            return None
        for k, v in hdr.items():
            if k.lower() == "set-cookie":
                m = re.search(r"(__cdn_verified=[^;]+)", v)
                if m:
                    return m.group(1)
        return None

    def _ck_get(self):
        # cookie 与域名绑定：换域名必须重解，故按 host 校验
        if self._ck and self._ck_host == self.host \
                and (time.time() - self._ck_t) < _CK_TTL:
            return self._ck
        ck = self._solve()
        if ck:
            self._ck = ck
            self._ck_host = self.host
            self._ck_t = time.time()
        return self._ck if self._ck_host == self.host else None

    def _hdr(self):
        h = {"User-Agent": UA}
        ck = self._ck_get()
        if ck:
            h["Cookie"] = ck
        return h

    def _next_host(self):
        # 切到下一个候选域名并作废当前 cookie
        self._hi = (self._hi + 1) % len(self._hosts)
        self.host = self._hosts[self._hi]
        self._ck = None
        self._ck_host = None
        self._ck_t = 0
        return self.host

    def _is_chal(self, t):
        if not t:
            return False
        head = t[:4000]
        return ("正在验证您的浏览器" in head or "cdn_pow" in head
                or "__cdn_verified" in head or "x-cdn-challenge" in head)

    def _fetch(self, url, h):
        for kw in ({"headers": h, "timeout": 20, "allow_redirects": True},
                   {"headers": h, "timeout": 20},
                   {"headers": h}):
            try:
                r = self.fetch(url, **kw)
            except TypeError:
                continue
            except Exception:
                return ""
            if r is None:
                return ""
            try:
                t = getattr(r, "text", None)
                if t:
                    return t
            except Exception:
                pass
            try:
                c = getattr(r, "content", None)
                if c:
                    return c.decode("utf-8", "replace") if isinstance(c, bytes) else str(c)
            except Exception:
                pass
            if isinstance(r, str):
                return r
            return ""
        return ""

    def _rebase(self, url):
        """把任意绝对/相对 URL 换绑到当前 self.host（换域名后旧链接仍然可用）"""
        m = re.match(r"^https?://[^/]+(/.*)?$", url or "")
        if m:
            return self.host + (m.group(1) or "/")
        if url and url.startswith("/"):
            return self.host + url
        return url or ""

    def _get(self, url, retry=True):
        """带多域名自动切换：当前域名解算/请求失败或仍被拦，就换下一个候选域名重试。
        每个域名各自解算 PoW（cookie 按域名隔离），URL 同步换绑到新域。"""
        t = ""
        for i in range(len(self._hosts)):
            u = self._rebase(url)
            h = self._hdr()
            t = self._fetch(u, h)
            if t and not self._is_chal(t):
                return t
            if not retry:
                break
            # 换下一个域名（_hdr 在新域名上会自动重新解算）
            self._next_host()
        return t or ""

    # ---------------- 列表卡片 ----------------
    def _cards(self, html):
        out = []
        for box in re.findall(r'(?s)<div class="stui-vodlist__box">(.*?)</li>', html):
            href = re.search(r'href="(/detail/[^"]+)"', box)
            name = re.search(r'title="([^"]*)"', box)
            if not (href and name):
                continue
            vid = re.search(r"/detail/(\d+)\.html", href.group(1))
            pic = re.search(r'data-original="([^"]*)"', box)
            rem = re.search(r'class="pic-text[^"]*">([^<]*)<', box)
            out.append({
                "vod_id": vid.group(1) if vid else href.group(1),
                "vod_name": name.group(1).strip(),
                "vod_pic": pic.group(1).strip() if pic else "",
                "vod_remarks": rem.group(1).strip() if rem else "",
            })
        seen, uniq = set(), []
        for x in out:
            if x["vod_id"] in seen:
                continue
            seen.add(x["vod_id"])
            uniq.append(x)
        return uniq

    # ---------------- 接口 ----------------
    def homeContent(self, filter):
        return {"class": [{"type_id": t, "type_name": n} for t, n in _CATS], "filters": {}}

    def homeVideoContent(self):
        html = self._get(self.host + "/")
        items = self._cards(html)[:60]
        if not items:                       # 首页被拦/结构变动 → 兜底抓分类首页
            items = self._cards(self._get(self.host + "/type/1.html"))[:60]
        return {"list": items}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        if pg <= 1:
            url = "%s/type/%s.html" % (self.host, tid)
        else:
            url = "%s/type/%s-%d.html" % (self.host, tid, pg)
        items = self._cards(self._get(url))
        return {"list": items, "page": pg, "pagecount": 9999,
                "limit": 20, "total": 999999}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) else ids
        vid = re.sub(r"\D", "", str(vid)) or str(vid)
        html = self._get("%s/detail/%s.html" % (self.host, vid))
        v = {"vod_id": vid}
        if not html:
            return {"list": [v]}
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        v["vod_name"] = re.sub(r"<.*?>", "", h1.group(1)).strip() if h1 else ""
        pic = re.search(r'data-original="([^"]+)"', html)
        v["vod_pic"] = pic.group(1).strip() if pic else ""
        ct = re.search(r'class="[^"]*detail-content[^"]*"[^>]*>(.*?)</', html, re.S)
        v["vod_content"] = re.sub(r"<.*?>", "", ct.group(1)).strip() if ct else ""
        # meta-item 依次为 类型/地区/年份/上映/共N集/更新/主演/导演
        metas = [re.sub(r"<.*?>", "", x).strip()
                 for x in re.findall(r'<span class="meta-item">(.*?)</span>', html, re.S)]
        plain, year = [], ""
        for it in metas:
            if it.startswith("主演"):
                v["vod_actor"] = it.split("：", 1)[-1].strip()
            elif it.startswith("导演"):
                v["vod_director"] = it.split("：", 1)[-1].strip()
            elif it.startswith("更新"):
                v["vod_remarks"] = it.replace("更新", "").strip()
            elif it.startswith("共") and "vod_remarks" not in v:
                v["vod_remarks"] = it.strip()
            elif ("：" not in it and not it.startswith(("共", "上映", "更新"))):
                if re.fullmatch(r"\d{4}", it):
                    year = it
                else:
                    plain.append(it)
        if plain:
            v["type_name"] = plain[0]
        if len(plain) > 1:
            v["vod_area"] = plain[1]
        v["vod_year"] = year
        # 线路：<div class="playlist-panel">…<h3>线路名</h3>…<ul class="stui-content__playlist">剧集</ul>
        groups = re.findall(
            r'(?s)<div class="playlist-panel">.*?<h3>(.*?)</h3>.*?'
            r'<ul class="stui-content__playlist[^"]*">(.*?)</ul>', html)
        if not groups:
            groups = [("线路%d" % (i + 1), pl) for i, pl in
                      enumerate(re.findall(r'(?s)<ul class="stui-content__playlist[^"]*">(.*?)</ul>', html))]
        names, eps = [], []
        for nm, pl in groups:
            nm = re.sub(r"<.*?>", "", nm).strip() or "线路"
            seg = []
            for u, t in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', pl, re.S):
                t = re.sub(r"<.*?>", "", t).strip()
                seg.append("%s$%s" % (t, u))
            if seg:
                names.append(nm)
                eps.append("#".join(seg))
        v["vod_play_from"] = "$$$".join(names)
        v["vod_play_url"] = "$$$".join(eps)
        return {"list": [v]}

    def searchContent(self, key, quick, pg=1):
        key = (key or "").strip()
        pg = int(pg) if str(pg).isdigit() else 1
        if not key:
            return {"list": [], "page": pg}
        kw = urllib.parse.quote(key.encode("utf-8"))
        if pg <= 1:
            body = kw + "-------------"
        else:
            body = kw + "----------%d---" % pg
        items = self._cards(self._get("%s/search/%s.html" % (self.host, body)))
        return {"list": items, "page": pg}

    def playerContent(self, flag, id, vipFlags):
        url = id or ""
        if url.startswith("/"):
            url = self.host + url
        elif not url.startswith("http"):
            url = self.host + "/w/" + url
        html = self._get(url)
        real = ""
        m = re.search(r"player_aaaa\s*=\s*(\{.*?\})\s*</script>", html, re.S)
        if m:
            try:
                o = json.loads(m.group(1))
                real = (o.get("url") or "").replace("\\/", "/")
            except Exception:
                real = ""
        if not real:
            m2 = re.search(r'"url"\s*:\s*"(https?:[^"]+?\.(?:m3u8|mp4)[^"]*)"', html)
            if m2:
                real = m2.group(1).replace("\\/", "/")
        hdr = {"User-Agent": UA, "Referer": self.host + "/"}
        if real:
            return {"parse": 0, "url": real, "header": hdr}
        return {"parse": 1, "url": url, "header": hdr}

    def localProxy(self, param):
        return [200, "application/vnd.apple.mpegurl", ""]
