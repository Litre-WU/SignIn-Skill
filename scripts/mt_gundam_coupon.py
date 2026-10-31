#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美团福利社 H5(gundam) 领券 · 纯接口版
======================================
覆盖"福利社"tab 的 gundam H5 活动页（标题如"周末加码必得百元券包"）：
  - 跨券墙 (gd-cross-ticket-wall-new)  ← 百元券包主力
      GET  https://market.waimai.meituan.com/playcenter/generalcoupon/info   (cookie-only)
      POST https://promotion.waimai.meituan.com/playcenter/generalcoupon/fetch
      body {activityViewId,tabs:[{planCode,rightCodes}],gdId,pageId,instanceId,...,mtFingerprint}
      ★ 风控关键: info 下发的 Set-Cookie(ta.uuid/iuuid) 必须带到 fetch, 否则 subcode=12"活动太火爆"
      ★ tabs 只放 status===0(可领取) 的券, 按 planCode 分组; status===1=已领
  - 限时抢券 (gd-limited-time-grab-coupon)
      GET  https://rights-apigw.meituan.com/api/rights/activity/secKill/info?activityId=...
      POST .../secKill/grab   body {activityId,gdId,pageId,instanceId,rightCode,roundCode,grabToken,appVersion}
  - 天降掉券 (fall-ticket-new)
      POST https://promotion.waimai.meituan.com/playcenter/fallCoupon/fetch  body {activityViewId,mtFingerPrint,riskFingerPrint}
      POST .../fallCoupon/record  （查已领记录）

全自动发现链路（不写死活动 ID，活动每周轮换也能跟上）：
  getBottomTabConfig → fls tab 的 webviewUrl(gundam_id)
  → GET gd2/wm/<gid> HTML 取 gdId/pageId/pageConfigJsonUrl
  → GET page-config.json 取全部领券组件参数
  → 逐组件执行 领券

登录态: Cookie: token=<wm_logintoken>（复用 mt_config.json）

用法:
  python mt_gundam_coupon.py          # 执行领券（幂等）
  python mt_gundam_coupon.py status   # 查看今日领取记录
"""
import gzip
from http.cookiejar import CookieJar
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "mt_config.json")
STATE_PATH = os.path.join(BASE, "mt_gundam_state.json")
LOG_PATH = os.path.join(BASE, "mt_coupon.log")
sys.path.insert(0, BASE)

import mt_api_coupon as mt  # 复用 gen_mtgsig / http_post / 配置加载

HOST_TAB = mt.HOST + "/fulishemini/getBottomTabConfig?" + mt.QS
GUNDAM_TPL = "https://market.waimai.meituan.com/gd2/wm/%s?gundam_id=%s&tenant=gundam&isMultiTab=true&gdEntry=wxTab"
RIGHTS = "https://rights-apigw.meituan.com/api/rights/activity/secKill"
PROMO = "https://promotion.waimai.meituan.com"
MARKET = "https://market.waimai.meituan.com"
def find_node():
    """MT_NODE → ~/.workbuddy 里的 node（按版本目录通配，别钉死版本号）→ 系统安装 → PATH。
    ★原先这里写死了某个 node 版本目录，那颗子一升级福利社这步就整步报错。"""
    import glob
    import shutil
    cands = [os.environ.get("MT_NODE")]
    cands += sorted(glob.glob(os.path.expanduser(
        "~/.workbuddy/binaries/node/versions/*/node.exe")), reverse=True)
    cands += [r"C:\Program Files\nodejs\node.exe", r"C:\Program Files (x86)\nodejs\node.exe",
              shutil.which("node")]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return "node"


NODE = find_node()
H5_SIGNER = os.path.join(BASE, "mt_h5_sign.js")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def http(url, data=None, method="GET", cookie=""):
    req = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": mt.UA,
        "Content-Type": "application/json",
        "Accept": "*/*", "Accept-Encoding": "gzip",
        "Referer": "https://market.waimai.meituan.com/",
        "Cookie": cookie,
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        if raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        return e.code, raw.decode("utf-8", "replace")


# ---------------------------------------------------------------- 发现链路
def find_gundam_id(cfg):
    """getBottomTabConfig → 底部 tab 的 webviewUrl 里取 gundam_id（pagePath 中 URL 编码）。

    2026-10-12 实测：底部 tab 改版为 home / new / mine 三项，原福利社 fls（gundam H5）入口下线。
    因此先按 id=fls 精确匹配，未命中则退化为扫描全部 tab 找任意 webview/gundam 入口。"""
    body_cfg = dict(cfg)
    _, dfpid = mt.gen_mtgsig("POST", HOST_TAB, "probe=1")
    body_cfg["_finger_applets"] = dfpid
    body = mt.build_body_str(body_cfg, "", extra={})
    mtgsig, _ = mt.gen_mtgsig("POST", HOST_TAB, body)
    c, t = mt.http_post(HOST_TAB, body, mtgsig, cfg.get("openIdCipher", ""),
                        cfg.get("open_id", ""), cfg.get("wm_uuid", ""),
                        cfg.get("csecuserid", ""), cfg.get("token", ""))
    if c != 200:
        raise RuntimeError("getBottomTabConfig HTTP %s" % c)
    j = json.loads(t)
    tabs = (j.get("data") or {}).get("bottomTabs", [])
    for tab in tabs:
        if tab.get("id") == "fls":
            m = re.search(r"gundam_id(?:=|%3D)([A-Za-z0-9]+)", tab.get("pagePath", ""))
            if m:
                return m.group(1)
    # 退化：fls 入口下线后，扫描全部 tab 找任意 gundam webview 入口
    for tab in tabs:
        m = re.search(r"gundam_id(?:=|%3D)([A-Za-z0-9]+)", tab.get("pagePath", "") or "")
        if m:
            return m.group(1)
    return None


def fetch_page(gid):
    """GET gundam H5 页 → (html, gdId, pageId, page_config_url)"""
    url = GUNDAM_TPL % (gid, gid)
    c, t = http(url, cookie="token=" + "")
    if c != 200:
        raise RuntimeError("gundam page HTTP %s" % c)
    m_gd = re.search(r'"gdId"\s*:\s*(\d+)', t)
    m_pg = re.search(r'"pageId"\s*:\s*(\d+)', t)
    m_cfg = re.search(r'pageConfigJsonUrl\\?"?\s*:\s*\\?"([^"\\]+)', t)
    return t, (m_gd.group(1) if m_gd else ""), (m_pg.group(1) if m_pg else ""), (m_cfg.group(1) if m_cfg else "")


def parse_components(cfg_url):
    """page-config.json → 全部领券组件参数"""
    c, t = http(cfg_url, cookie="")
    if c != 200:
        raise RuntimeError("page-config HTTP %s" % c)
    j = json.loads(t)
    grabs, falls, walls = [], [], []
    def walk(n):
        if isinstance(n, dict):
            nm = n.get("name") or ""
            p = n.get("props") or {}
            if nm == "@gdc/gd-limited-time-grab-coupon" and p.get("activityId"):
                grabs.append({"activityId": p["activityId"], "instanceId": p.get("instanceID", "")})
            elif nm == "@gdc/fall-ticket-new" and p.get("playActivityId"):
                falls.append({"activityViewId": p["playActivityId"], "instanceId": p.get("instanceID", "")})
            elif nm == "@gdc/gd-cross-ticket-wall-new":
                tc = p.get("ticketConfig") or {}
                if tc.get("playActivityId"):
                    walls.append({"activityViewId": tc["playActivityId"], "instanceId": p.get("instanceID", "")})
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(j)
    # grab 去重（renderTree 里每个组件出现两次：props 一次 + slotData 一次）
    seen, uniq = set(), []
    for g in grabs:
        if g["activityId"] not in seen:
            seen.add(g["activityId"])
            uniq.append(g)
    seen_w, uniq_w = set(), []
    for w in walls:
        if w["activityViewId"] not in seen_w:
            seen_w.add(w["activityViewId"])
            uniq_w.append(w)
    return uniq, falls, uniq_w


# ---------------------------------------------------------------- 领券
def secKill_info(activity_id, cookie):
    c, t = http("%s/info?activityId=%s" % (RIGHTS, activity_id), cookie=cookie)
    if c != 200:
        return None
    try:
        j = json.loads(t)
    except Exception:
        return None
    return j if j.get("code") == 1 else None


def secKill_grab(cfg, info_data, activity_id, instance_id, cookie):
    cur = (info_data or {}).get("currentGrabCouponInfo") or {}
    coupons = cur.get("coupon") or []
    if not coupons:
        return False, "info 无可抢券"
    right = coupons[0].get("rightCode")
    if not right or not cur.get("token") or not cur.get("roundCode"):
        return False, "缺 rightCode/grabToken/roundCode"
    body = {
        "activityId": activity_id,
        "gdId": cfg["_gdId"],
        "pageId": cfg["_pageId"],
        "instanceId": instance_id,
        "rightCode": right,
        "roundCode": cur["roundCode"],
        "grabToken": cur["token"],
        "appVersion": cfg.get("wm_appversion", "1.52.0"),
    }
    q = urllib.parse.urlencode({
        "cType": cfg.get("wm_ctype", "fulishe_wxapp"),
        "fpPlatform": 13,
        "wx_openid": cfg.get("open_id", ""),
        "appVersion": cfg.get("wm_appversion", "1.52.0"),
        "latitude": cfg.get("wm_latitude", 0),
        "longitude": cfg.get("wm_longitude", 0),
        "actualLatitude": cfg.get("wm_actual_latitude", 0),
        "actualLongitude": cfg.get("wm_actual_longitude", 0),
    })
    c, t = http("%s/grab?%s" % (RIGHTS, q), data=json.dumps(body).encode(),
                method="POST", cookie=cookie)
    try:
        j = json.loads(t)
    except Exception:
        return False, "grab 响应非 JSON: %s" % t[:120]
    sub = ((j.get("data") or {}).get("subCode"))
    toast = (((j.get("data") or {}).get("coupon") or {}).get("toastMsg")) or ""
    if j.get("code") == 1 and sub == 1:
        return True, "抢券成功"
    if sub == 9017:
        return True, "今日已领过(幂等)"
    return False, "subCode=%s %s" % (sub, toast or j.get("msg", ""))


def fall_fetch(cfg, activity_view_id, instance_id, cookie):
    _, dfpid = mt.gen_mtgsig("POST", PROMO + "/playcenter/fallCoupon/fetch", "probe=1")
    q = urllib.parse.urlencode({
        "gdId": cfg["_gdId"], "pageId": cfg["_pageId"], "instanceId": instance_id,
        "wm_uuid": cfg.get("wm_uuid", ""), "token": cfg.get("token", ""),
        "userId": cfg.get("userid", ""),
        "initialLat": cfg.get("wm_latitude", 0), "initialLng": cfg.get("wm_longitude", 0),
        "actualLat": cfg.get("wm_actual_latitude", 0), "actualLng": cfg.get("wm_actual_longitude", 0),
        "wm_appversion": cfg.get("wm_appversion", "1.52.0"),
        "ctype": cfg.get("wm_ctype", "fulishe_wxapp"), "app": 7, "fpPlatform": 13,
    })
    body = {"activityViewId": activity_view_id, "mtFingerPrint": dfpid, "riskFingerPrint": dfpid}
    c, t = http("%s/playcenter/fallCoupon/fetch?%s" % (PROMO, q),
                data=json.dumps(body).encode(), method="POST", cookie=cookie)
    try:
        j = json.loads(t)
    except Exception:
        return False, "响应非 JSON: %s" % t[:120]
    code = j.get("code")
    msg = j.get("message") or j.get("msg") or ""
    if code == 0:
        return True, "天降券领取成功"
    if code == 2000:  # 今日次数已消耗光
        return True, "今日天降次数已用尽(幂等): %s" % msg
    return False, "code=%s %s" % (code, msg)


def fall_record(cfg, activity_view_id, instance_id, cookie):
    q = urllib.parse.urlencode({
        "gdId": cfg["_gdId"], "pageId": cfg["_pageId"], "instanceId": instance_id,
        "wm_uuid": cfg.get("wm_uuid", ""), "token": cfg.get("token", ""),
        "userId": cfg.get("userid", ""),
        "initialLat": cfg.get("wm_latitude", 0), "initialLng": cfg.get("wm_longitude", 0),
        "actualLat": cfg.get("wm_actual_latitude", 0), "actualLng": cfg.get("wm_actual_longitude", 0),
        "wm_appversion": cfg.get("wm_appversion", "1.52.0"),
        "ctype": cfg.get("wm_ctype", "fulishe_wxapp"), "app": 7, "fpPlatform": 13,
    })
    body = {"activityViewId": activity_view_id, "mtFingerPrint": "", "riskFingerPrint": ""}
    c, t = http("%s/playcenter/fallCoupon/record?%s" % (PROMO, q),
                data=json.dumps(body).encode(), method="POST", cookie=cookie)
    try:
        j = json.loads(t)
    except Exception:
        return []
    out = []
    for cp in ((j.get("data") or {}).get("couponList") or []):
        out.append({"name": cp.get("name"), "face": cp.get("faceValueStr"),
                    "limit": cp.get("limitStr"), "etime": cp.get("etime")})
    return out


# ---------------------------------------------------------------- 跨券墙
def h5_sign(method, url, body_obj):
    """Node 沙箱: H5guard.sign -> mtgsig; H5guard.getfp -> mtFingerprint"""
    body_json = json.dumps(body_obj, separators=(",", ":"), ensure_ascii=False)
    r = subprocess.run([NODE, H5_SIGNER, method, url, body_json],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=90, cwd=BASE)
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and "mtgsig" in line:
            o = json.loads(line)
            return o["mtgsig"], o.get("mtFingerprint", "")
    raise RuntimeError("h5 sign fail rc=%s out=%s" % (r.returncode, r.stdout[:200]))


def wall_info(opener, token, activity_view_id, instance_id, cfg):
    """GET generalcoupon/info (market 域)。opener 带 cookie jar 收 Set-Cookie(风控必需)"""
    qs = urllib.parse.urlencode({
        "isMini": 1, "ctype": cfg.get("wm_ctype", "fulishe_wxapp"), "isInDpEnv": 0,
        "initialLng": cfg.get("wm_longitude", 0), "initialLat": cfg.get("wm_latitude", 0),
        "actualLat": cfg.get("wm_actual_latitude", 0), "actualLng": cfg.get("wm_actual_longitude", 0),
        "fpPlatform": 13, "wxOpenId": cfg.get("open_id", ""),
        "appVersion": cfg.get("wm_appversion", "1.52.0"),
        "activityViewId": activity_view_id, "gdId": cfg["_gdId"], "pageId": cfg["_pageId"],
        "instanceId": instance_id, "clientType": cfg.get("wm_ctype", "fulishe_wxapp"),
        "gdBs": "0000", "new_gundam": 1,
    })
    url = MARKET + "/playcenter/generalcoupon/info?" + qs
    # ★2026-10-31 修复：网关 10-27 起对 /playcenter/generalcoupon/info 强制 csec/H5guard 校验，
    # 裸请求恒返 openresty 403（HTML）。真实浏览器抓包(记录91)是 GET + mtgsig 挂 **query**、
    # 并带 yodaReady=h5&csecplatform=4&csecversion=4.3.0。实测：原样请求 403、加签后 200，
    # 且假 activityViewId 加签前也是 403 → 403 是网关签名拦截而非活动失效。
    url += "&yodaReady=h5&csecplatform=4&csecversion=4.3.0"
    mtgsig, _ = h5_sign("GET", url, None)
    url += "&mtgsig=" + urllib.parse.quote(mtgsig if isinstance(mtgsig, str) else json.dumps(mtgsig))
    req = urllib.request.Request(url, headers={
        "Cookie": "token=" + token, "User-Agent": mt.UA,
        "Referer": MARKET + "/gd2/wm/4TtwZI", "Accept": "application/json, text/plain, */*"})
    with opener.open(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
    j = json.loads(body)
    if j.get("code") != 0:
        raise RuntimeError("wall info code=%s" % j.get("code"))
    return j["data"]


def wall_tabs(coupon_list):
    """Nn(): 只取 status===0(可领取), 按 planCode 分组"""
    m = OrderedDict()
    for c in coupon_list:
        if c.get("status") == 0:
            m.setdefault(c["planCode"], []).append(c["rightCode"])
    return [{"planCode": k, "rightCodes": v} for k, v in m.items()]


def wall_fetch(cookie_str, token, activity_view_id, instance_id, cfg, tabs, partner):
    """POST generalcoupon/fetch (promotion 域)。mtgsig 放 header, 必须带 info 下发的 cookie
    ★2026-10-31：网关同样对 fetch 强制 csec 校验（缺 query 三件套恒 403 HTML），
    对齐真实浏览器抓包(记录119 fallCoupon/record)：query 带 yodaReady/csecplatform/csecversion，
    且 h5_sign 必须对**最终完整 url** 计算（签名输入含 query）。"""
    url = (PROMO + "/playcenter/generalcoupon/fetch?isMini=1&ctype=%s&isInDpEnv=0"
           "&yodaReady=h5&csecplatform=4&csecversion=4.3.0" % cfg.get("wm_ctype", "fulishe_wxapp"))
    data = {
        "initialLng": cfg.get("wm_longitude", 0), "initialLat": cfg.get("wm_latitude", 0),
        "actualLat": cfg.get("wm_actual_latitude", 0), "actualLng": cfg.get("wm_actual_longitude", 0),
        "fpPlatform": 13, "wxOpenId": cfg.get("open_id", ""),
        "appVersion": cfg.get("wm_appversion", "1.52.0"),
        "activityViewId": activity_view_id, "tabs": tabs,
        "gdId": cfg["_gdId"], "pageId": cfg["_pageId"], "instanceId": instance_id,
        "clientType": cfg.get("wm_ctype", "fulishe_wxapp"),
        "partner": partner if partner is not None else 4,
        "appid": "wx2c348cf579062e56",
    }
    # ★2026-10-31 修复二：网关现对 POST 做 body 级签名校验。真实浏览器(记录119)签名时
    # body 里**已含** mtFingerPrint；原实现是先签再注入指纹 → 签名与实发 body 不一致 → 403。
    # 改两遍签：第一遍取 fp，注入后对最终 body 再签。
    _, fp = h5_sign("POST", url, data)
    data["mtFingerprint"] = fp
    mtgsig, _ = h5_sign("POST", url, data)
    # ★2026-10-31 修复三（根因）：fetch 风控校验 mtgsig.a3(dfpid) 与 Cookie 的 WEBDFPID 一致。
    # 浏览器端两者同源(localStorage 固定值)；我们签名器每次随机新生成 → 不同步就恒 403。
    # 实测「cookie WEBDFPID=本次签名 a3」即放行(假 tabs 返 501 参数错误=进入业务层)。
    try:
        a3 = json.loads(mtgsig).get("a3", "")
    except Exception:
        a3 = ""
    if a3:
        cookie_str = re.sub(r"WEBDFPID=[^;]*;?\s*", "", cookie_str).rstrip("; ")
        cookie_str = (cookie_str + "; WEBDFPID=" + a3) if cookie_str else "WEBDFPID=" + a3
    req = urllib.request.Request(
        url, data=json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "mtgsig": mtgsig, "Cookie": cookie_str,
                 "Origin": MARKET, "Referer": MARKET + "/", "User-Agent": mt.UA},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def wall_claim(cfg, token, activity_view_id, instance_id):
    """单个跨券墙全流程: info(收cookie) -> tabs -> fetch。返回 (ok, msg, 明细)"""
    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    data = wall_info(opener, token, activity_view_id, instance_id, cfg)
    cl = data.get("couponList") or []
    claimable = [c for c in cl if c.get("status") == 0]
    claimed = [c for c in cl if c.get("status") == 1]
    detail = "已领 %d 张 ¥%s / 可领 %d 张 ¥%s" % (
        len(claimed), sum(c["couponValue"] for c in claimed),
        len(claimable), sum(c["couponValue"] for c in claimable))
    if not claimable:
        return True, "无待领券(幂等): %s" % detail, []
    tabs = wall_tabs(cl)
    cookie_str = "; ".join("%s=%s" % (c.name, c.value) for c in cj) + "; token=" + token
    st, resp = wall_fetch(cookie_str, token, activity_view_id, instance_id, cfg, tabs, data.get("partner"))
    try:
        j = json.loads(resp)
    except Exception:
        return False, "fetch 响应非 JSON(http %s): %s" % (st, resp[:120]), []
    if j.get("code") == 0:
        got = [(c.get("couponName"), c.get("couponValue")) for c in (j.get("data") or {}).get("couponList") or []
               if c.get("status") == 10]
        val = sum(v for _, v in got)
        return True, "✅ 领取成功 %d 张 ¥%s (%s)" % (len(got), val, detail), got
    sub = j.get("subcode")
    if sub == 11:
        return False, "活动太火爆(11): %s" % detail, []
    if sub in (4, 7):
        return False, "未登录(%s)，需重抓 wm_logintoken" % sub, []
    return False, "失败 code=%s subcode=%s %s (%s)" % (j.get("code"), sub, j.get("msg", ""), detail), []


# ---------------------------------------------------------------- 主流程
def run():
    cfg = mt.load_json(CONFIG_PATH, {}) or {}
    ok, missing = mt.check_config(cfg)
    if not ok:
        print("[失败] mt_config.json 缺少字段: %s" % ", ".join(missing))
        return 1
    if not cfg.get("wm_logintoken"):
        print("[失败] 缺 wm_logintoken")
        return 1

    state = mt.load_json(STATE_PATH, {}) or {}
    today = datetime.now().strftime("%Y-%m-%d")

    print("=" * 62)
    print("美团福利社 H5 领券 %s" % datetime.now().strftime("%F %T"))
    print("=" * 62)

    # 1) 发现活动页
    gid = find_gundam_id(cfg)
    if not gid:
        print("[提示] 底部 tab 已无福利社(fls) gundam 入口（2026-10-12 起改版为 home/new/mine），")
        print("       活动页入口已下线 — 属服务端变更，非脚本失效，本平台跳过。")
        log("gundam entry gone (tab 改版)")
        return 0
    print("[1/6] 福利社 gundam_id = %s" % gid)

    html, gd_id, page_id, cfg_url = fetch_page(gid)
    if not (gd_id and page_id and cfg_url):
        print("[中断] 页面解析失败 gdId=%s pageId=%s cfg=%s" % (gd_id, page_id, bool(cfg_url)))
        return 2
    title = re.search(r'"title"\s*:\s*"([^"]+)"', html)
    print("[2/6] 页面: %s  gdId=%s pageId=%s" % (title.group(1) if title else "?", gd_id, page_id))
    cfg["_gdId"] = int(gd_id)
    cfg["_pageId"] = int(page_id)

    grabs, falls, walls = parse_components(cfg_url)
    print("[3/6] 组件: 跨券墙 %d 个, 限时抢 %d 个, 天降掉券 %d 个"
          % (len(walls), len(grabs), len(falls)))

    cookie = "token=" + cfg["wm_logintoken"]
    results = []

    # 2) 跨券墙（百元券包主力）
    for w in walls:
        # ★2026-10-31：单墙异常(网关/风控变迁)不得中断整个 gundam 流程——
        # 10-27 网关升级后 info 抛 RuntimeError 曾把限时抢/天降一起带崩(日志无 gundam 行=崩了)
        try:
            okr, msg, got = wall_claim(cfg, cfg["wm_logintoken"], w["activityViewId"], w["instanceId"])
        except Exception as e:
            okr, msg, got = False, "异常: %s" % e, []
        print("      [跨券墙 %s] %s — %s" % (w["activityViewId"][:12], "✅" if okr else "❌", msg))
        results.append({"type": "跨券墙", "activity": w["activityViewId"], "ok": okr, "msg": msg})
        for name, val in got:
            results.append({"type": "跨券墙券", "activity": w["activityViewId"], "ok": True,
                            "msg": "%s ¥%s" % (name, val), "coupon": name})

    # 3) 限时抢券
    for g in grabs:
        info = secKill_info(g["activityId"], cookie)
        if not info:
            print("      [限时抢 %s] 非进行中活动(过期/未开始)，跳过" % g["activityId"])
            continue  # 过期/无效活动，info 非 code:1
        d = info["data"]
        cur = d.get("currentGrabCouponInfo") or {}
        cps = cur.get("coupon") or []
        stock = cps[0].get("residueStock") if cps else None
        now, end = d.get("currentTime", 0), d.get("activityEndTime", 0)
        if now > end:
            print("      [限时抢 %s] 活动已结束" % g["activityId"])
            results.append({"type": "限时抢", "activity": g["activityId"],
                            "ok": True, "msg": "活动已结束", "coupon": ""})
            continue
        if stock is not None and stock <= 0:
            print("      [限时抢 %s] 今日库存已抢完 (%s)"
                  % (g["activityId"], (cps[0].get("couponName") or "")))
            results.append({"type": "限时抢", "activity": g["activityId"],
                            "ok": True, "msg": "库存已抢完", "coupon": cps[0].get("couponName")})
            continue
        okr, msg = secKill_grab(cfg, d, g["activityId"], g["instanceId"], cookie)
        cname = cps[0].get("couponName") if cps else ""
        print("      [限时抢 %s] %s — %s %s" % (g["activityId"], "✅" if okr else "❌", msg, cname))
        results.append({"type": "限时抢", "activity": g["activityId"], "ok": okr,
                        "msg": msg, "coupon": cname})

    # 4) 天降掉券
    for f in falls:
        okr, msg = fall_fetch(cfg, f["activityViewId"], f["instanceId"], cookie)
        print("      [天降 %s] %s — %s" % (f["activityViewId"][:12], "✅" if okr else "❌", msg))
        results.append({"type": "天降", "activity": f["activityViewId"], "ok": okr, "msg": msg})
        for rec in fall_record(cfg, f["activityViewId"], f["instanceId"], cookie):
            print("           已领记录: %s %s元(满%s) " % (rec["name"], rec["face"], rec["limit"]))
            results.append({"type": "天降记录", "activity": f["activityViewId"], "ok": True,
                            "msg": "%s %s元" % (rec["name"], rec["face"])})

    state[today] = {
        "gundam_id": gid, "gdId": gd_id, "pageId": page_id,
        "results": results, "ts": datetime.now().strftime("%F %T"),
    }
    mt.save_json(STATE_PATH, state)
    n_ok = sum(1 for r in results if r["ok"])
    print("[完成] %d 项处理，%d 项成功/幂等。明细见 %s" % (len(results), n_ok, STATE_PATH))
    log("gundam gid=%s grabs=%d falls=%d ok=%d/%d" % (gid, len(grabs), len(falls), n_ok, len(results)))
    return 0


def status():
    st = mt.load_json(STATE_PATH, {}) or {}
    if not st:
        print("暂无记录")
        return 0
    for k in sorted(st):
        v = st[k]
        print("%s  gundam=%s" % (k, v.get("gundam_id")))
        for r in v.get("results", []):
            print("   %-6s %-22s %s %s" % (r["type"], r.get("coupon") or r["activity"][:18],
                                            "✅" if r["ok"] else "❌", r["msg"]))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit(status() if cmd == "status" else run())
