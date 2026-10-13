# -*- coding: utf-8 -*-
# 小米商城 App (MiShop) mtop 接口客户端 —— host shop-api.retail.mi.com
# serviceToken + 请求头来自用户真机抓包 (com.xiaomi.mishop 5.2.272 iOS)
# 凭证优先读同目录 xm_mijin_config.json（公开部署用），否则用内置默认
import urllib.request, urllib.parse, gzip, json, time, sys, os

SERVICE_TOKEN = ""  # 必填: 小米商城 App 抓包的 serviceToken（或放同目录 xm_mijin_config.json）
USER_ID = ""
XM_UUID = ""

_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xm_mijin_config.json")
if os.path.exists(_CFG):
    try:
        with open(_CFG, encoding="utf-8") as _f:
            _c = json.load(_f)
        SERVICE_TOKEN = _c.get("serviceToken") or SERVICE_TOKEN
        USER_ID = str(_c.get("userId") or USER_ID)
        XM_UUID = _c.get("xmUuid") or XM_UUID
    except Exception:
        pass

HOST = "https://shop-api.retail.mi.com"

def headers(body=None, extra=None):
    h = {
        "Host": "shop-api.retail.mi.com",
        "dtoken": "",
        "Referer": "https://shop-api.retail.mi.com",
        "Cookie": "serviceToken=%s; userId=%s; xmUuid=%s" % (SERVICE_TOKEN, USER_ID, XM_UUID),
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
        "d-id": "",
        "x-user-agent": "channel/mishop platform/mishop.ios",
        "magic-device-id": "20260629183123d114c0d52838808f3ee07eca88cdba1600db1e13c0cfd488",
        "ai-recommend-status": "0",
        "mishop-model": "iPhone18,2",
        "locale": "CN",
        "mishop-client-id": "180100031055",
        "device-id": "4A3003F56F85758E4AFC949FE8363A04",
        "network-carrier": "6553565535",
        "ios-version": "system=27.0&device=iPhone18,2",
        "x-yp-app-source": "front-RN-old",
        "ios-app-version": "5.2.272",
        "Connection": "keep-alive",
        "mishop-channel-id": "",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "device-oaid": "eGL7Cdf3Q9ESAMmA1beV6fkOyV9GMlr2H76xvT+f8yWYCnDZfs79A/cA4X8UpZQr",
        "Accept": "*/*",
        "Content-Type": "application/json",
        "mishop-client-versioncode": "5.2.272",
        "d-model": "aVBob25lMTgsMg==",
        "Accept-Encoding": "gzip, deflate, br",
    }
    if body is not None:
        h["Content-Length"] = str(len(body))
    h.update(extra or {})
    return h

def call(path, payload, host=None, method="POST", extra=None):
    url = (host or HOST) + path
    data = None
    h = headers(extra=extra)
    if method == "POST":
        data = json.dumps([{}, payload], separators=(",", ":"), ensure_ascii=False).encode()
        h["Content-Length"] = str(len(data))
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        r = op.open(req, timeout=25)
        raw = r.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return e.code, raw.decode("utf-8", "replace")

def get_page(page_id, sign, pdl="mishop"):
    """会场页 floor 配置（GET）"""
    url = "%s/mtop/navi/venue/v2/page?page_id=%s&pdl=%s&sign=%s" % (
        HOST, page_id, pdl, urllib.parse.quote(sign))
    h = headers()
    h.pop("Content-Type", None)
    req = urllib.request.Request(url, headers=h, method="GET")
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        r = op.open(req, timeout=25)
        raw = r.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return e.code, raw.decode("utf-8", "replace")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "home"
    if cmd == "home":
        st, body = call("/mtop/mf/usercenter/personalHome",
                        {"lat": "30.535470", "lng": "114.512096",
                         "cityId": "205", "provinceId": "18"})
        print("personalHome ->", st)
        print(body[:3000])
