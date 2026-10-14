#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
qwenwork_credits.py — 千问办公 QwenWorkCN 每日 100 积分
=======================================================
产品: 阿里「千问办公」桌面端 QwenWorkCN（安装目录 %LOCALAPPDATA%/Programs/QwenWorkCN）
      免费版权益: 首次注册赠 2000 积分(90 天) + 每日登录赠送 100 积分(当日有效)

★ 凭证获取（无需用户抓包，全自动）:
  用户数据目录 %APPDATA%/QwenWorkCN/auth-v2.dat 是 Chromium「v10」加密信封
  （= DPAPI 保护的 AES-256-GCM，与浏览器 cookie 同一套），结构:
    {"schemaVersion":2,"token":"<JWT>","refreshToken":"ory_rt_...",
     "expiresAt":"...","refreshStrategy":"device_token","user":{...}}
  解密链: Local State → os_crypt.encrypted_key → 去 "DPAPI" 5B 头 → CryptUnprotectData
          → 32B AES key → AESGCM(nonce=ev[3:15]).decrypt(ev[15:])
  ★优先实时读这个文件（桌面端自己会续期，永不踢下线），config 仅作兜底/便携。

★ 接口（2026-10-14 从 app.asar → out/main/main.js 反查）:
  BASE = https://gateway.qwenwork.cn        (constants$3.K = "gateway.qwenwork.cn")
  GET  /api/v1/adapter/user/wallets                       钱包余额（★可用）
       → data.daily_credits.total_balance / monthly_credits / longterm_credits
       → data.active_wallets.wallets[] = {balance, valid_to}
  GET  /api/v1/adapter/user/account-context?include=user,plan,quota,page,data_sharing
       → data.quota.remaining（= 今日可用额度）
  POST /api/v1/deviceToken/refresh   {refresh_token, target:"c"} → 续期（会轮换 refresh_token）
  GET  /sash/api/v1/me/daily-check-in/status     （前端常量，★生产网关当前 404 未开放）
  POST /sash/api/v1/me/daily-check-in/claim      （同上；status 枚举 CLAIMABLE/
       CLAIMED_TODAY/DISABLED/NOT_STARTED/ENDED；claim 结果 CLAIMED/ALREADY_CLAIMED）

鉴权头: Authorization: Bearer <token> + X-QwenWork-{Version,Release-Version,Build,
       Platform,Arch,Channel} + User-Agent: QoderWork

★ 结论（2026-10-14 实测）: 免费版每日 100 积分是**登录/每日 00:00 由服务端自动发放**，
  桌面端无手动领取动作（前端 bundle 里签到卡片走 /sash 前缀，生产网关未路由）。
  因此本脚本的「每日动作」= 校验当日 100 是否已入账 + 尝试签到接口（404 则自动略过）。

配置 qwenwork_config.json（可选兜底）: {"token": "...", "refreshToken": "..."}

用法:
  python qwenwork_credits.py status          # 只看钱包/额度
  python qwenwork_credits.py auto            # 每日: 签到探测 + 钱包核对
  python qwenwork_credits.py refresh         # 手动续期（会轮换 refresh_token，慎用）
  python qwenwork_credits.py init            # 从已安装客户端导入凭证到 config
"""
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE_DIR, "qwenwork_config.json")
HOST = "https://gateway.qwenwork.cn"
UA = "QoderWork"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def _user_data_dir():
    return os.path.join(os.environ.get("APPDATA", ""), "QwenWorkCN")


def _jwt_exp(token):
    """返回 JWT exp（epoch 秒），解析失败返回 0"""
    try:
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return int(json.loads(base64.urlsafe_b64decode(seg)).get("exp") or 0)
    except Exception:
        return 0


# ── 凭证 ──────────────────────────────────────────────────────────────────
def _decrypt_auth_v2(ud):
    """解密 auth-v2.dat（Chromium v10 信封）。返回 dict 或 None。"""
    path = os.path.join(ud, "auth-v2.dat")
    if not os.path.exists(path):
        return None
    try:
        sys.path.insert(0, BASE_DIR)
        import browser_cookies as bc
        key = bc._master_key(ud)
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        ev = open(path, "rb").read()
        if ev[:3] != b"v10":
            return None
        return json.loads(AESGCM(key).decrypt(ev[3:15], ev[15:], None).decode("utf-8"))
    except Exception as e:
        print("[警告] 解密 auth-v2.dat 失败: %s" % e)
        return None


def load_credential():
    """★优先实时读桌面端凭证（它自己续期，不冲突）；config 兜底。"""
    ud = _user_data_dir()
    live = _decrypt_auth_v2(ud) if ud else None
    if live and live.get("token"):
        exp = _jwt_exp(live["token"])
        # 未过期（留 1h 缓冲）就用实时的
        if exp - time.time() > 3600:
            live["_source"] = "client"
            return live
    cfg = None
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = None
    if cfg and cfg.get("token"):
        cfg["_source"] = "config"
        return cfg
    # 实时的虽然临期，也总比没有强
    if live and live.get("token"):
        live["_source"] = "client-expiring"
        return live
    return None


def save_cfg(token, refresh_token, extra=None):
    cfg = {"token": token, "refreshToken": refresh_token}
    if extra:
        cfg.update(extra)
    cfg["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── HTTP ──────────────────────────────────────────────────────────────────
def hdrs(token, with_body=False):
    h = {"Accept": "application/json",
         "User-Agent": UA,
         "X-QwenWork-Version": "1.2.5",
         "X-QwenWork-Release-Version": "1.2.5-26092902",
         "X-QwenWork-Build": "26092902",
         "X-QwenWork-Platform": "win32",
         "X-QwenWork-Arch": "x64",
         "X-QwenWork-Channel": "stable"}
    if with_body:
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = "Bearer " + token
    return h


def call(method, path, token, body=None, label="", quiet=False):
    url = HOST + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers=hdrs(token, body is not None), method=method)
    try:
        r = urllib.request.urlopen(req, timeout=20, context=CTX)
        raw = r.read().decode("utf-8", "replace")
        try:
            return r.status, json.loads(raw)
        except Exception:
            return r.status, {"raw": raw[:200]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:200]}
    except Exception as e:
        if not quiet:
            print("[%s] %s -> 网络异常 %s" % (label, path, e))
        return -1, {"message": str(e)}


# ── 业务 ──────────────────────────────────────────────────────────────────
def get_wallets(token):
    st, j = call("GET", "/api/v1/adapter/user/wallets", token, label="wallets")
    if st != 200:
        return st, None
    return st, (j.get("data") or j)


def get_quota(token):
    st, j = call("GET", "/api/v1/adapter/user/account-context?include=user,plan,quota",
                 token, label="ctx", quiet=True)
    if st != 200:
        return None
    return ((j.get("data") or {}).get("quota") or {})


def checkin_status(token):
    return call("GET", "/sash/api/v1/me/daily-check-in/status", token,
                label="checkin", quiet=True)


def checkin_claim(token):
    return call("POST", "/sash/api/v1/me/daily-check-in/claim", token, body={},
                label="claim", quiet=True)


def _ms(ts):
    try:
        return datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def fmt_wallets(d):
    if not d:
        return "读取失败"
    parts = []
    for k, label in (("daily_credits", "日包"), ("monthly_credits", "月包"),
                     ("longterm_credits", "长期")):
        v = (d.get(k) or {}).get("total_balance")
        if v is not None:
            parts.append("%s=%s" % (label, v))
    aw = (d.get("active_wallets") or {}).get("wallets") or []
    for w in aw[:3]:
        parts.append("在账 %s(至 %s)" % (w.get("balance"), (w.get("valid_to") or "")[:10]))
    return " / ".join(parts) or str(d)[:200]


# ── 命令 ──────────────────────────────────────────────────────────────────
def cmd_init():
    c = load_credential()
    if not c:
        print("[失败] 未找到凭证 — 需安装并登录「千问办公」桌面端（%s）" % _user_data_dir())
        return 2
    save_cfg(c["token"], c.get("refreshToken", ""),
             {"user": (c.get("user") or {}).get("name"),
              "tier": (c.get("user") or {}).get("tier")})
    st, d = get_wallets(c["token"])
    print("[OK] 凭证来源=%s 用户=%s 版本=%s" % (c.get("_source"),
          (c.get("user") or {}).get("name"), (c.get("user") or {}).get("tier")))
    if d is None:
        print("[警告] 钱包读取 HTTP %s" % st)
    else:
        print("[钱包] %s" % fmt_wallets(d))
    print("[OK] 已写入 %s" % CFG_PATH)
    return 0


def _core(try_claim=True):
    c = load_credential()
    if not c:
        print("[失败] 未找到凭证 —【千问办公失效】需安装并登录桌面端")
        return 2
    token = c["token"]
    exp = _jwt_exp(token)
    print("[用户] %s | %s | 凭证来源=%s | token 到期=%s" % (
        (c.get("user") or {}).get("name") or "-",
        (c.get("user") or {}).get("tier") or "-",
        c.get("_source"),
        datetime.fromtimestamp(exp, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
        if exp else "?"))

    if try_claim:
        st, j = checkin_status(token)
        if st == 200 and isinstance(j, dict):
            data = j.get("data") or j
            status = data.get("status")
            print("[签到] status=%s reward=%s 连签=%s天 累计=%s天 下次=%s" % (
                status, data.get("rewardCredits"), data.get("currentStreakDays"),
                data.get("totalClaimDays"), _ms(data.get("nextClaimAt"))))
            if status == "CLAIMABLE":
                st2, j2 = checkin_claim(token)
                if st2 == 200:
                    d2 = j2.get("data") or j2
                    print("[签到] 领取结果=%s +%s（到期 %s）" % (
                        d2.get("result"), d2.get("rewardCredits"), _ms(d2.get("expiresAt"))))
                else:
                    print("[签到] 领取失败 HTTP %s %s" % (st2, str(j2)[:150]))
            elif status:
                print("[签到] 无需领取（%s）" % status)
        elif st in (404, -1):
            print("[签到] 接口未开放/不可达(HTTP %s) — 免费版每日 100 积分为服务端自动发放，跳过" % st)
        elif st in (401, 403):
            print("[签到] HTTP %s —【千问办公失效】凭证需重新登录" % st)
        else:
            print("[签到] HTTP %s %s" % (st, str(j)[:150]))

    st, d = get_wallets(token)
    if d is None:
        print("[失败] 钱包 HTTP %s —【千问办公失效】" % st)
        return 3
    print("[钱包] %s" % fmt_wallets(d))
    q = get_quota(token)
    if q:
        print("[额度] 剩余 %s（used=%s exceeded=%s）" % (
            q.get("remaining"), q.get("used"), q.get("exceeded")))
    daily = ((d.get("daily_credits") or {}).get("total_balance") or 0)
    if daily >= 100:
        print("[结论] 今日 100 积分已入账 ✓")
        return 0
    print("[结论] 日包 %s < 100 — 今日尚未发放（桌面端登录或 00:00 系统会补发）" % daily)
    return 0


def cmd_status():
    return _core(try_claim=False)


def cmd_auto():
    return _core(try_claim=True)


def cmd_refresh():
    c = load_credential()
    if not c or not c.get("refreshToken"):
        print("[失败] 无 refreshToken，无法续期")
        return 2
    st, j = call("POST", "/api/v1/deviceToken/refresh", c["token"],
                 body={"refresh_token": c["refreshToken"], "target": "c"}, label="refresh")
    if st != 200:
        print("[失败] 续期 HTTP %s %s" % (st, str(j)[:200]))
        return 3
    tok = j.get("device_token")
    rt = j.get("refresh_token")
    if not tok or not rt:
        print("[失败] 响应缺少 device_token/refresh_token: %s" % str(j)[:200])
        return 3
    save_cfg(tok, rt, {"user": (c.get("user") or {}).get("name")})
    print("[OK] 续期成功 → 到期 %s" % datetime.fromtimestamp(
        _jwt_exp(tok), timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M"))
    print("[注意] refresh_token 已轮换，桌面端内存中的旧 token 仍可用到自然过期")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "init":
        sys.exit(cmd_init())
    elif cmd == "status":
        sys.exit(cmd_status())
    elif cmd == "auto":
        sys.exit(cmd_auto())
    elif cmd == "refresh":
        sys.exit(cmd_refresh())
    else:
        print(__doc__)
        sys.exit(1)
