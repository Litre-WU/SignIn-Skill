#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腾势 DENZA（比亚迪）汽车小程序 · 签到 + 自动完成任务领积分脚本
=====================================================================

逆向依据（反编译源码 wxc216bfded475c384 / 版本 213）：
  appservice.app.compiled.js
    - utils/constant/constant-obfuscated.js  全局配置（多环境分支，release=M）
    - header.js（signer：Checksum=sha256(appSecret+nonce+curtime)）
    - crypto.js / sha256.js                  AES-CBC + 签名
  platform/mine/api/apiMine/signIn.js       签到接口（#/commonUc/activity/sign/*）
  page/me/pages/integralTask/integralTask.js 任务系统（task/user/tasks, receiveAward）
  app-service.compiled.js                    任务接口 serviceDir 映射

请求信封（两套场景，均经反编译源码 + 抓包逐字段验证，release=M 分支）：
  ★ 场景 A · unifie（签到家族 signIn / getSignCalendar / getCardList）
    - 网关  https://common-mina-gateway.bydauto.com/denza  （unifie.domain）
    - 路径  /commonUc/<serviceDir>
    - 密钥  utf8(unifie.aes_key) / utf8(unifie.aes_iv)  直接当密钥（非口令派生）
            unifie.aes_key = "3x!5Q#K1NQ@6X~FC"  unifie.aes_iv = "bi@td8Rp%jG^fC!D"
    - 签名  Appkey=common_mina, Checksum=sha256(appSecret+nonce+curtime).lower()
            appSecret = "yD9%R7wnjzEn#CCS", Content-Type=text/plain
    - body  {session_id, check_login, ...biz}   ← 不带 app_client/app_version
  ★ 场景 B · rights（任务系统 task/user/tasks, receiveAward —— 走 apiHostCommonRights）
    - 网关  https://service20.denzacloud.com/?s=ForCommonRightsSrv.forward
            + &serviceDir=task/user/tasks（或 receiveAward）
            ★★2026-10-27 更正：原记为 apiHostCommunity(forwardInformationFlow) 是错的。
              反编译 page/me/pages/integralTask/integralTask.js 里 getTasks 用的是
              `p + API.me_userTask`，而 p=globalData.apiHostCommonRights
              =`?s=ForCommonRightsSrv.forward`；打 forwardInformationFlow 一律回业务
              ret=401「数据请求失败（401）」（与 session、body 字段、引号、UA/Referer 无关，已逐一排除）。
    - 密钥  utf8(top-level aes_key) / utf8(top-level aes_iv)
            aes_key = "QR6?sgk2`%Nc<.=Z"   aes_iv = "hS0W7KlTQYDFjGCM"
    - 签名  Appkey=denza_mina_wx, Checksum=sha256(appSecret+nonce+curtime).lower()
            appSecret = "qpc1sn~>0hr_4<$"   无 Content-Type 头
    - body  {app_client:"mina", app_version:230, session_id, ...biz}
            （myRequest 内部经 n() 注入 app_client/app_version）
  - 两场景响应体均为 AES 密文，用各自场景密钥解密得 {ret,data,msg}；
    ret==200(或"200")成功。任务接口 ret 为字符串，签到 ret 为整数，判断时统一转 str。
  - 注：ret=401「数据请求失败（401）」在本脚本历史上几乎都出自**网关选错**（见上 ★★），
    不是 session 严校验；签到能过而任务 401 时，先核对 host 的 `s=` 参数再怀疑登录态。

登录 / 会话（重要）：
  - 小程序用 wx.login() 拿 code -> POST /?service=mina.decryptCode 换 session
    （session = {session_id, hashId, expired_timestamp, openid, unionid}），存于本地 storage。
  - ★expired_timestamp 实测＝抓包时刻 + 7200（**session 只有 2 小时寿命**，2026-10-27 由
    decryptCode 响应解出），因此“抓一次长期复用”做不到；服务端是否硬校验该时间戳未证实，
    但每天无人值守跑到 2 小时之外就会失效——除非在小程序里重新拉起（它会自己换新 sid）。
  - 抓到的响应体是场景 B 密钥的 AES 密文，**本地即可解出 sid**，不必在代理里看明文：
    `aes_decrypt(响应正文, NORMAL_AES_KEY, NORMAL_AES_IV)` → data.session_id。
  - wx.login 只能在微信内运行，无法在脚本里复现，故 session_id 仍来自抓包。
  - session 失效（ret=21017 / 签到 401）时，须用 Reqable/Charles 在小程序内重新抓一次
    /?service=mina.decryptCode 的响应，把新 session_id 写回配置。

用法（多账号，模型对齐 GR 的 accounts/）：
  python byd_signin.py init   --session <session_id> [--expired <ts>] [--acct 名字]
  python byd_signin.py status [--acct 名字]        # 查积分 / 签到日历
  python byd_signin.py signin [--acct 名字]        # 执行每日签到
  python byd_signin.py tasks  [--acct 名字]        # 领取可领任务奖励
  python byd_signin.py auto   [--acct 名字]        # 签到 + 领任务奖励（挂定时任务用）
  python byd_signin.py probe  [--acct 名字]        # 打印请求信封 + 原始/解密响应（调试）
  --acct 省略 = 遍历 byd_accounts/ 下全部账号；无 byd_accounts/ 则退回 byd_config.json。
"""

import argparse
import base64
import datetime
import hashlib
import json
import os
import random
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# ============================================================
# 两套请求场景（release=M 分支，均由 constant-obfuscated.js 反编译确认）
# ------------------------------------------------------------
# 场景 A：unifie（签到家族 signIn / getSignCalendar / getCardList）
#   网关  https://common-mina-gateway.bydauto.com/denza
#   路径  /commonUc/<serviceDir>
#   密钥  unifie.aes_key / unifie.aes_iv
#   auth  unifie.auth（appKey=common_mina, contentType=text/plain）
#   请求体 {session_id, check_login, ...biz}（无 app_client/app_version）
# ------------------------------------------------------------
# 场景 B：rights（任务系统 task/user/tasks, receiveAward —— 走 apiHostCommonRights）
#   网关  https://service20.denzacloud.com/?s=ForCommonRightsSrv.forward
#   追加  &serviceDir=<dir>
#   密钥  top-level aes_key / aes_iv（normal 场景）
#   auth  top-level auth（appKey=denza_mina_wx，无 contentType）
#   请求体 {app_client:"mina", app_version:230, session_id, ...biz}
# ============================================================

# 场景 A：unifie
GATEWAY = "https://common-mina-gateway.bydauto.com/denza"
UNIFIE_AES_KEY = "3x!5Q#K1NQ@6X~FC"          # unifie.aes_key
UNIFIE_AES_IV = "bi@td8Rp%jG^fC!D"           # unifie.aes_iv
UNIFIE_APP_KEY = "common_mina"
UNIFIE_APP_SECRET = "yD9%R7wnjzEn#CCS"        # unifie.auth.appSecret（抓包 Checksum 反算已验证）
UNIFIE_CONTENT_TYPE = "text/plain"

# 场景 B：rights（任务系统；此常量旧名 COMMUNITY_HOST 指向 apiHostCommunity，是 401 的根因）
RIGHTS_HOST = "https://service20.denzacloud.com/?s=ForCommonRightsSrv.forward"
NORMAL_AES_KEY = "QR6?sgk2`%Nc<.=Z"           # M.aes_key（normal 场景）
NORMAL_AES_IV = "hS0W7KlTQYDFjGCM"            # M.aes_iv
NORMAL_APP_KEY = "denza_mina_wx"              # M.auth.appKey
NORMAL_APP_SECRET = "qpc1sn~>0hr_4<$"         # M.auth.appSecret
# normal 场景 auth 无 contentType -> 请求不带 Content-Type 头

# 与小程序 createNonceStr 同款字符集（校验和仅依赖 appSecret+nonce+curtime，字符集不影响合法性）
NONCE_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BYD_ACCOUNTS_DIR = os.path.join(SCRIPT_DIR, "byd_accounts")
BYD_CFG_PATH = os.path.join(SCRIPT_DIR, "byd_config.json")
TIMEOUT = 30

# 接口表：scene 决定密钥 / auth / URL / 请求体形态
API = {
    "sign_in":       {"scene": "unifie",  "path": "/commonUc/activity/sign/signIn"},
    "sign_calendar": {"scene": "unifie",  "path": "/commonUc/activity/sign/getSignCalendar"},
    "sign_card":     {"scene": "unifie",  "path": "/commonUc/activity/sign/getCardList"},
    "user_task":     {"scene": "normal",  "serviceDir": "&serviceDir=task/user/tasks"},
    "receive_award": {"scene": "normal",  "serviceDir": "&serviceDir=task/user/receiveAward"},
}


# ---------------------------------------------------------------- 加密 / 解密
def aes_encrypt(plain: str, key: str, iv: str) -> str:
    from Crypto.Cipher import AES
    data = plain.encode("utf-8")
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad
    ct = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8")).encrypt(data)
    return base64.b64encode(ct).decode("ascii")


def aes_decrypt(b64: str, key: str, iv: str):
    from Crypto.Cipher import AES
    try:
        data = base64.b64decode(b64)
        pt = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8")).decrypt(data)
        pad = pt[-1]
        if 1 <= pad <= 16:
            pt = pt[:-pad]
        return pt.decode("utf-8", "replace")
    except Exception:
        return ""


# ---------------------------------------------------------------- 签名头
def make_headers(app_key: str, app_secret: str, content_type: str = None):
    nonce = "".join(random.choice(NONCE_CHARS) for _ in range(16))
    curtime = str(int(time.time()))
    chk = hashlib.sha256((app_secret + nonce + curtime).encode("utf-8")).hexdigest().lower()
    h = {
        "Appkey": app_key,
        "Nonce": nonce,
        "Curtime": curtime,
        "Checksum": chk,
        "x-clienttraceid": "mina-" + str(uuid.uuid4()),
        "Algo": "1",
    }
    if content_type:
        h["Content-Type"] = content_type
    return h


# ---------------------------------------------------------------- HTTP 基础
def _http(url, payload: str, headers: dict):
    """POST：payload(已加密) + headers 发送，返回 (status, raw_text)。"""
    data = payload.encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        return 0, str(getattr(e, "reason", e))


def api_call(cfg, api_name, biz=None):
    """调用接口：按 scene 选密钥/auth/URL/请求体，解密响应为 dict。"""
    spec = API[api_name]
    scene = spec["scene"]
    sid = cfg.get("session_id") or (cfg.get("session") or {}).get("session_id") or ""
    if scene == "unifie":
        key, iv = UNIFIE_AES_KEY, UNIFIE_AES_IV
        ak, ask, ct = UNIFIE_APP_KEY, UNIFIE_APP_SECRET, UNIFIE_CONTENT_TYPE
        url = GATEWAY + spec["path"]
        body = {"session_id": sid, "check_login": 1 if sid else 0}
    else:  # normal（任务系统）
        key, iv = NORMAL_AES_KEY, NORMAL_AES_IV
        ak, ask, ct = NORMAL_APP_KEY, NORMAL_APP_SECRET, None
        url = RIGHTS_HOST + spec["serviceDir"]
        body = {"app_client": "mina", "app_version": 230, "session_id": sid}
    if biz:
        body.update(biz)
    payload = aes_encrypt(json.dumps(body, ensure_ascii=False, separators=(",", ":")), key, iv)
    headers = make_headers(ak, ask, ct)
    status, raw = _http(url, payload, headers)
    if status == 0:
        return {"__neterr__": raw, "url": url}
    try:
        dec = aes_decrypt(raw, key, iv)
        resp = json.loads(dec) if dec else {"raw": raw[:500], "decrypt_failed": True}
    except Exception:
        resp = {"raw": raw[:500], "decrypt_failed": True}
    resp["_url"] = url
    resp["_http"] = status
    resp["_scene"] = scene
    return resp


# ---------------------------------------------------------------- 配置 / 账号
def acct_path(name):
    return os.path.join(BYD_ACCOUNTS_DIR, name + ".json") if name else BYD_CFG_PATH


def save_cfg(cfg, path=None):
    p = path or cfg.get("_cfg_path") or BYD_CFG_PATH
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    cfg["token_updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] 写配置失败 {p}: {e}")


def load_cfg(path=None):
    p = path or BYD_CFG_PATH
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return None
    if isinstance(cfg, dict):
        cfg["_cfg_path"] = p
    return cfg


def list_accounts():
    out = []
    if os.path.isdir(BYD_ACCOUNTS_DIR):
        for fn in sorted(os.listdir(BYD_ACCOUNTS_DIR)):
            if fn.endswith(".json") and not fn.endswith(".example.json"):
                out.append((fn[:-5], os.path.join(BYD_ACCOUNTS_DIR, fn)))
        if out:
            return out
    return [("default", BYD_CFG_PATH)]


def resolve_accounts(name=None):
    items = list_accounts()
    if name:
        hit = [(n, p) for n, p in items if n == name]
        if not hit:
            print(f"[x] 未找到账号 '{name}'（byd_accounts/ 下无 {name}.json，或当前为单账号模式）")
            sys.exit(1)
    else:
        hit = items
    out = []
    for n, p in hit:
        cfg = load_cfg(p)
        if not cfg or not cfg.get("session_id"):
            print(f"[!] 账号 {n}: 未配置 session_id（{p}），请先 init --acct {n} …")
            continue
        out.append((n, cfg))
    # 未配置时返回空，由 main 打印 [skip] 并退 0，避免总控误报失效
    return out


# ---------------------------------------------------------------- 业务动作
def do_signin(cfg):
    r = api_call(cfg, "sign_in", {"date": "", "isCard": "0"})
    if r.get("ret") == 200:
        d = r.get("data", {}) or {}
        if d.get("duplicate"):
            print(f"    今日已签到（重复请求，跳过）")
        else:
            print(f"    签到成功，本次 +{d.get('integral', '?')} 积分")
        return True
    print(f"    签到失败 ret={r.get('ret')} msg={r.get('msg','')} {r.get('raw','')[:120]}")
    if r.get("ret") in (21017, 401):
        print("    ★ session 失效，须重新抓包 mina.decryptCode 写入新 session_id")
    return False


def do_tasks(cfg):
    r = api_call(cfg, "user_task", {"reward": "integral", "data_use_for": "mina"})
    rcode = str(r.get("ret")) if isinstance(r, dict) else ""
    if not isinstance(r, dict) or rcode != "200":
        print(f"    任务列表获取失败 ret={r.get('ret')} msg={r.get('msg','')} {r.get('raw','')[:120]}")
        if rcode in ("21017", "401"):
            print("    ★ session 被拒(ret=21017)或路由不对(ret=401)：先确认走的是 RIGHTS_HOST")
            print("      （apiHostCommunity/forwardInformationFlow 会恒返 401，与 session 无关）；")
            print("      确系 session 问题再重抓 mina.decryptCode，用场景B密钥本地解出 sid 后 init --session 覆盖")
        return 0
    data = r.get("data", {}) or {}
    # 真实结构：data 里「值为数组」的键即任务组（full / sub），typeName[键] 只是组显示名；
    # typeSort 也是数组但装的是排序项（无 scene_flag），必须排除
    type_name = data.get("typeName", {}) or {}
    groups = [(k, v) for k, v in data.items()
              if isinstance(v, list) and v and isinstance(v[0], dict) and "scene_flag" in v[0]]
    claimed = 0
    seen = 0
    for typ, tasks in groups:
        gname = type_name.get(typ) or typ
        for t in (tasks or []):
            if not isinstance(t, dict):
                continue
            seen += 1
            st = t.get("status")
            flag = t.get("scene_flag")
            name = t.get("task_name") or flag or "?"
            jump = t.get("jump_flag")
            if st in (2, 3) and flag:
                rr = api_call(cfg, "receive_award", {"reward": "integral", "scene_flag": flag})
                ok = isinstance(rr, dict) and str(rr.get("ret")) == "200"
                print(f"    [领] {gname}/{name}({flag}) status={st}: {'成功' if ok else '失败 ' + str(rr.get('msg',''))[:40]}")
                if ok:
                    claimed += 1
            elif st == 1:
                print(f"    [需手动] {gname}/{name}({flag}) jump={jump} 进度{t.get('current')}/{t.get('target')}"
                      f" —— 需在小程序内完成对应动作（如发帖/浏览）")
            else:
                print(f"    [跳过] {gname}/{name}({flag}) status={st}（4=已完成已领取）")
    print(f"    共 {seen} 个任务，本次领取 {claimed} 个奖励")
    return claimed


def do_status(cfg):
    print("  — 签到日历 —")
    r = api_call(cfg, "sign_calendar")
    if isinstance(r, dict) and str(r.get("ret")) == "200":
        d = r.get("data", {}) or {}
        hs = d.get("historySign", {}) or {}
        cont = hs.get("continuation_days", d.get("continuation_days", "?"))
        print(f"    连续签到: {cont} 天 | 累计: {d.get('durationDays', '?')} 天 | 今日积分: {d.get('todayIntegral', '?')}")
        tips = d.get("tips")
        if tips:
            print(f"    提示: {tips}")
    else:
        rcode = str(r.get("ret")) if isinstance(r, dict) else "?"
        print(f"    日历获取失败 ret={rcode} {r.get('raw','')[:120]}")
        if rcode in ("21017", "401"):
            print("    ★ session 失效，须重新抓包 mina.decryptCode 写入新 session_id")
    print("  — 任务概览 —")
    r2 = api_call(cfg, "user_task", {"reward": "integral", "data_use_for": "mina"})
    if isinstance(r2, dict) and str(r2.get("ret")) == "200":
        data = r2.get("data", {}) or {}
        groups = [v for k, v in data.items()
                  if isinstance(v, list) and v and isinstance(v[0], dict) and "scene_flag" in v[0]]
        total = sum(len(v or []) for v in groups)
        ready = sum(1 for v in groups for t in (v or []) if isinstance(t, dict) and t.get("status") in (2, 3))
        print(f"    任务总数: {total}（可领 {ready} 个，用 `tasks` 命令一键领取）")
    else:
        print(f"    任务获取失败 ret={r2.get('ret')}")


def do_probe(cfg):
    sid = cfg.get("session_id") or ""
    # ---- 场景 A：unifie（签到）----
    print("== 场景A unifie（签到）==")
    body_u = {"session_id": sid, "check_login": 1 if sid else 0, "date": "", "isCard": "0"}
    url_u = GATEWAY + API["sign_in"]["path"]
    enc_u = aes_encrypt(json.dumps(body_u, ensure_ascii=False, separators=(",", ":")),
                        UNIFIE_AES_KEY, UNIFIE_AES_IV)
    print("URL :", url_u)
    print("HEAD:", json.dumps(make_headers(UNIFIE_APP_KEY, UNIFIE_APP_SECRET, UNIFIE_CONTENT_TYPE), ensure_ascii=False))
    print("ENC :", enc_u)
    print("DEC :", json.dumps(body_u, ensure_ascii=False))
    status, raw = _http(url_u, enc_u, make_headers(UNIFIE_APP_KEY, UNIFIE_APP_SECRET, UNIFIE_CONTENT_TYPE))
    print(f"HTTP: {status}")
    print("RAW :", raw[:300])
    if raw:
        print("DEC_RESP:", aes_decrypt(raw, UNIFIE_AES_KEY, UNIFIE_AES_IV)[:500])

    # ---- 场景 B：normal（任务系统）----
    print("\n== 场景B normal（任务系统）==")
    body_n = {"app_client": "mina", "app_version": 230, "session_id": sid,
              "reward": "integral", "data_use_for": "mina"}
    url_n = RIGHTS_HOST + API["user_task"]["serviceDir"]
    enc_n = aes_encrypt(json.dumps(body_n, ensure_ascii=False, separators=(",", ":")),
                        NORMAL_AES_KEY, NORMAL_AES_IV)
    print("URL :", url_n)
    print("HEAD:", json.dumps(make_headers(NORMAL_APP_KEY, NORMAL_APP_SECRET, None), ensure_ascii=False))
    print("ENC :", enc_n)
    print("DEC :", json.dumps(body_n, ensure_ascii=False))
    status, raw = _http(url_n, enc_n, make_headers(NORMAL_APP_KEY, NORMAL_APP_SECRET, None))
    print(f"HTTP: {status}")
    print("RAW :", raw[:300])
    if raw:
        print("DEC_RESP:", aes_decrypt(raw, NORMAL_AES_KEY, NORMAL_AES_IV)[:500])


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="腾势 DENZA 小程序签到脚本（自用，支持多账号 byd_accounts/<名字>.json）")
    ap.add_argument("cmd", choices=["init", "status", "signin", "tasks", "auto", "probe"])
    ap.add_argument("--acct", help="指定单账号（byd_accounts/<名字>.json）；省略则全部")
    ap.add_argument("--session", help="init 用：抓包得到的 session_id")
    ap.add_argument("--expired", help="init 用：session 过期时间戳（expired_timestamp），可选")
    args = ap.parse_args()

    if args.cmd == "init":
        if not args.session:
            print("[x] init 需要 --session <session_id>")
            sys.exit(1)
        cfg = {"session_id": args.session}
        if args.expired:
            try:
                cfg["expired_timestamp"] = int(args.expired)
            except ValueError:
                pass
        cfg["note"] = "session_id 来自真机抓包 /?service=mina.decryptCode 响应；失效需重抓"
        p = acct_path(args.acct)
        save_cfg(cfg, p)
        print(f"[ok] 已写入 {p}  (session_id={args.session[:8]}…)")
        return

    accounts = resolve_accounts(args.acct)
    if not accounts:
        print("[skip] 未配置腾势 DENZA 账号（byd_accounts/ 下无 <名字>.json，且 byd_config.json 缺失 session_id）")
        print("       配置：真机 Reqable 抓 /?service=mina.decryptCode 响应取出 session_id，")
        print("       执行  python byd_signin.py init --session <session_id> [--acct 名字]")
        return
    multi = len(accounts) > 1
    for name, cfg in accounts:
        prefix = f"[{name}] " if multi or args.acct else ""
        print(f"\n{prefix}=== {args.cmd} ===")
        if args.cmd == "signin":
            do_signin(cfg)
        elif args.cmd == "tasks":
            do_tasks(cfg)
        elif args.cmd == "auto":
            do_signin(cfg)
            do_tasks(cfg)
        elif args.cmd == "status":
            do_status(cfg)
        elif args.cmd == "probe":
            do_probe(cfg)


if __name__ == "__main__":
    main()
