#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
c189_signin.py — 天翼云盘（天翼189网盘）自动签到
====================================================
来源: 复刻 wes-lin/Cloud189Checkin（底层 cloud189-sdk）的核心签到链路，
     纯 Python 标准库实现，零三方依赖，接入现有 CDP 抓 cookie 体系。

鉴权（浏览器已登录 → CDP 抓 SSON 登录 cookie）:
  1. 登录态 = 189 域的 SSON 单点登录 cookie（浏览器登录 cloud.189.cn 即持有）
  2. CDP 抓到 SSON → 复刻 sdk 的 getSessionForPC，换取 accessToken/refreshToken/sessionKey
  3. 签到 = GET https://cloud.189.cn/mkt/userSign.action?sessionKey=...（WEB 域只需 sessionKey，无需 accessToken 签名）
  4. 容量 = GET https://cloud.189.cn/api/portal/getUserSizeInfo.action?sessionKey=...

命令行:
  python c189_signin.py init   <SSON整行cookie或 sso值>  # 写 c189_config.json
  python c189_signin.py auto    # 检测未签到则签到 + 容量播报（发 JSON）
  python c189_signin.py status  # 只读播报（容量/今日是否已签到）
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from urllib.request import ProxyHandler, build_opener, urlopen

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(BASE, "c189_config.json")
# 沙箱代理拦 localhost；外网走系统代理即可（189 直连）
opener = build_opener(ProxyHandler({}))

WEB_URL = "https://cloud.189.cn"
AUTH_URL = "https://open.e.189.cn"
API_URL = "https://api.cloud.189.cn"
APP_ID = "8025431004"          # const.AppID
CLIENT_TYPE = "TELEPC"
VERSION = "6.2"
CHANNEL_ID = "web_cloud.189.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36")


def http_get(url, headers=None, cookie=None, timeout=15):
    h = {"User-Agent": UA, "Accept": "application/json;charset=UTF-8"}
    if headers:
        h.update(headers)
    if cookie:
        h["Cookie"] = cookie
    req = urllib.request.Request(url, headers=h)
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def http_post_form(url, form, headers=None, cookie=None, timeout=15, redirect="manual"):
    """POST application/x-www-form-urlencoded，返回 (json_body, final_url)。redirect=manual 不自动跟随。"""
    h = {"User-Agent": UA, "Accept": "application/json;charset=UTF-8",
         "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}
    if headers:
        h.update(headers)
    if cookie:
        h["Cookie"] = cookie
    data = urllib.parse.urlencode(form).encode("utf-8")

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    op2 = build_opener(_NoRedirect(), ProxyHandler({}))
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        r = op2.open(req, timeout=timeout)
        body = r.read().decode("utf-8", "replace")
        final_url = r.geturl()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        final_url = getattr(e, "url", url)
    try:
        j = json.loads(body)
    except Exception:
        j = {"_raw": body[:300], "_http": getattr(locals().get('e', None), 'code', None)}
    return j, final_url


def load_cfg():
    if not os.path.exists(CFG):
        return {}
    try:
        with open(CFG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def extract_sson(cookie_line):
    """从整行 cookie 里提取 SSON 值（登录态核心键）。键名以探测为准，优先 SSON。"""
    if not cookie_line:
        return ""
    s = cookie_line.strip()
    # 若是裸值（用户直接给 sso），长度>40 且无 '=' 则当值
    if "=" not in s:
        return s
    parts = {}
    for kv in s.split(";"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            parts[k.strip()] = v.strip()
    # 命中 SSON 相关键（大小写不敏感）
    for key in ("SSON", "sso", "usession", "uSession", "u_session", "SSO"):
        if key in parts:
            return parts[key]
    # 兜底: 找任何名字含 sso/session 的
    for k, v in parts.items():
        lk = k.lower()
        if "sso" in lk or "session" in lk:
            return v
    return ""


def get_session(sson, cfg):
    """严格复刻 sdk CloudAuthClient.loginBySsoCooike:
       unify(不带SSON) → 带SSON访问unify落地页(收服务端会话cookie) → POST getSessionForPC(带redirectURL)
       全程 http.cookiejar 收集 set-cookie（sdk got 默认带 cookie 共享）。"""
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    op = build_opener(urllib.request.HTTPCookieProcessor(cj), ProxyHandler({}))

    def _get(url, cookie=None, timeout=15):
        h = {"User-Agent": UA, "Accept": "application/json;charset=UTF-8"}
        if cookie:
            h["Cookie"] = cookie
        r = op.open(urllib.request.Request(url, headers=h), timeout=timeout)
        return r.geturl(), r.read()

    return_url = "https://m.cloud.189.cn/zhuanti/2020/loginErrorPc/index.html"
    # 1. unify 登录页（取落地 URL；不带 SSON 先探）
    unify_q = urllib.parse.urlencode({
        "appId": APP_ID, "clientType": "10020", "returnURL": return_url,
        "timeStamp": str(int(time.time() * 1000))})
    unify_url = f"{WEB_URL}/api/portal/unifyLoginForPC.action?{unify_q}"
    try:
        land_url, _ = _get(unify_url)
    except Exception as e:
        land_url = unify_url
        print("    [unify 探活失败] %s" % e)
    # 2. 带 SSON 访问 unify 落地页（服务端识别 SSON → set 会话 cookie，jar 收集）
    try:
        land_url, _ = _get(f"{WEB_URL}/api/portal/unifyLoginForPC.action?{unify_q}",
                           cookie=f"SSON={sson}")
    except Exception as e:
        print("    [SSON unify 访问提示] %s" % e)

    # 3. POST getSessionForPC（带 jar 里收到的会话 cookie + redirectURL）
    suffix = {"clientType": CLIENT_TYPE, "version": VERSION,
              "channelId": CHANNEL_ID, "rand": str(int(time.time()))}
    form = {"appId": APP_ID, "redirectURL": land_url, **suffix}
    data = urllib.parse.urlencode(form).encode("utf-8")
    h = {"User-Agent": UA, "Referer": WEB_URL + "/", "Accept": "application/json;charset=UTF-8",
         "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}
    jar_cookie = "; ".join("%s=%s" % (c.name, c.value) for c in cj)
    if jar_cookie:
        h["Cookie"] = jar_cookie
    req = urllib.request.Request(f"{API_URL}/getSessionForPC.action", data=data, headers=h, method="POST")
    with op.open(req, timeout=15) as r:
        sess = json.loads(r.read().decode("utf-8", "replace"))
    if isinstance(sess, dict) and sess.get("sessionKey"):
        return sess
    raise RuntimeError("getSessionForPC 未取到 sessionKey: %s" % str(sess)[:300])


def user_sign(session_key, cfg):
    """GET /mkt/userSign.action?sessionKey=...（WEB 域，纯 sessionKey）"""
    q = urllib.parse.urlencode({
        "rand": str(int(time.time() * 1000)), "clientType": "TELEANDROID",
        "version": VERSION, "model": "KB2000", "sessionKey": session_key})
    return http_get(f"{WEB_URL}/mkt/userSign.action?{q}",
                    headers={"Referer": f"{WEB_URL}/web/main/", "User-Agent": UA})


def get_size_info(session_key):
    q = urllib.parse.urlencode({"sessionKey": session_key})
    return http_get(f"{WEB_URL}/api/portal/getUserSizeInfo.action?{q}",
                    headers={"Referer": f"{WEB_URL}/web/main/", "User-Agent": UA})


def ensure_session(cfg):
    """确保拿到可用 sessionKey: 优先配置里的 accessToken+refreshToken 续，再退回 SSON。"""
    acc = cfg.get("accessToken", "")
    if acc:
        # 用 accessToken 直接 getSessionForPC（sdk loginByAccessToken）
        params = {"appId": APP_ID, "clientType": CLIENT_TYPE, "version": VERSION,
                  "channelId": CHANNEL_ID, "rand": str(int(time.time())), "accessToken": acc}
        try:
            sess = http_get(f"{API_URL}/getSessionForPC.action?" + urllib.parse.urlencode(params),
                            headers={"Referer": WEB_URL, "User-Agent": UA})
            if isinstance(sess, dict) and sess.get("sessionKey"):
                return sess
        except Exception:
            pass
    sso = cfg.get("sson", "")
    if not sso:
        raise RuntimeError("无 accessToken 也无 sson，请先 init")
    sess = get_session(sso, cfg)
    # 回存 refresh/accessToken
    if sess.get("refreshToken"):
        cfg["refreshToken"] = sess["refreshToken"]
    if sess.get("accessToken"):
        cfg["accessToken"] = sess["accessToken"]
        cfg["expiresIn"] = int(time.time() * 1000) + int(sess.get("expiresIn", 6 * 86400) * 1000)
    save_cfg(cfg)
    return sess


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"

    if cmd == "init":
        if len(sys.argv) < 3:
            print("[中断] 用法: c189_signin.py init <SSON整行cookie或sso值>"); return 2
        cookie_line = " ".join(sys.argv[2:])
        sso = extract_sson(cookie_line)
        if not sso:
            print("[中断] 未从输入中提取到 SSON 登录 cookie"); return 2
        cfg = load_cfg()
        cfg["sson"] = sso
        cfg["cookie_line"] = cookie_line
        cfg["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_cfg(cfg)
        print("[ok] 已写入 c189_config.json（sson 前12位=%s...，将校验登录态）" % sso[:12])
        # 立即校验
        try:
            sess = get_session(sso, cfg)
            cfg["sessionKey"] = sess.get("sessionKey", "")
            cfg["loginName"] = sess.get("loginName", "")
            cfg["refreshToken"] = sess.get("refreshToken", "")
            cfg["accessToken"] = sess.get("accessToken", "")
            save_cfg(cfg)
            print("[ok] 登录态校验通过 loginName=%s sessionKey 前12位=%s" %
                  (cfg.get("loginName"), (sess.get("sessionKey") or "")[:12]))
            return 0
        except Exception as e:
            print("[失败] 登录态校验失败: %s" % e); return 3

    if cmd == "status":
        cfg = load_cfg()
        sess = ensure_session(cfg)
        sk = sess.get("sessionKey") or cfg.get("sessionKey", "")
        info = get_size_info(sk)
        print("登录=%s 个人容量=%s 家庭容量=%s" %
              (cfg.get("loginName", "?"), info.get("cloudCapacityInfo"), info.get("familyCapacityInfo")))
        return 0

    if cmd == "auto":
        cfg = load_cfg()
        sess = ensure_session(cfg)
        sk = sess.get("sessionKey") or cfg.get("sessionKey", "")
        before = get_size_info(sk)
        sign = user_sign(sk, cfg)
        after = get_size_info(sk)
        is_signed = bool(sign.get("isSign")) if isinstance(sign, dict) else None
        bonus = (sign.get("netdiskBonus") or 0) if not is_signed else 0
        ptot = int((before.get("cloudCapacityInfo") or {}).get("totalSize", 0))
        atot = int((after.get("cloudCapacityInfo") or {}).get("totalSize", 0))
        delta_mb = round((atot - ptot) / 1024 / 1024, 2)
        cfg["sessionKey"] = sk
        save_cfg(cfg)
        print(json.dumps({
            "loginName": cfg.get("loginName"),
            "isSign": is_signed,
            "bonusMB": bonus,
            "capacityDeltaMB": delta_mb,
            "totalGB": round(atot / 1024 / 1024 / 1024, 2),
            "signRaw": str(sign)[:300],
        }, ensure_ascii=False))
        return 0

    print("未知命令: %s（支持 init/status/auto）" % cmd)
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
