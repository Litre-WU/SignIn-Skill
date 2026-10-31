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


def _user_dict(c):
    """归一 user：客户端实时是 dict，config 历史(老 cmd_refresh 写法)可能是字符串。"""
    u = (c or {}).get("user")
    return u if isinstance(u, dict) else {"name": u or ""}


def load_credential(force_refresh=False):
    """★凭证装载 + 自动续期（2026-10-31 加固版）。

    force_refresh=True: 跳过 ①② 新鲜判定，直接进入 ③ rt 续期
    （_core 遇到「本地看似新鲜但服务端 401」时的强刷通道）。

    顺序: ① 客户端 auth-v2.dat 新鲜(>1h 缓冲) → 直接用，并把 rt 写回 config(轮换权威)
          ② config 新鲜 → 直接用
          ③ 两者皆临期/过期 → 依次用 rt 候选离线续期(config rt → live rt，去重)，
             成功写回 config。★修复点：旧版续期块只在「config 有 token」分支内执行，
             「客户端过期 + config 缺失/无 rt」场景（桌面端一周没开 + config 被清）
             会拿着一堆可用 refreshToken 却从不续期，直接返回过期 token 被误判失效。
          ④ 全部续期失败 → 返回手头最新 token 并明确提示（_core 遇 401 还会强刷重试）

    实测(10-31): refresh 端点只校验 refresh_token，不强验 base Authorization 是否过期；
    refreshTokenExpiresAt 元数据滞后不可信 → 一律直接试刷；失败的 rt 不被消费可安全重试。
    """
    ud = _user_data_dir()
    live = _decrypt_auth_v2(ud) if ud else None
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = None

    def _fresh(t):
        return bool(t) and _jwt_exp(t) - time.time() > 3600

    # ① 客户端新鲜 → 权威（它自己会续期），把 rt 写回 config——但**仅在 live 血缘
    #    比 config 更新时**（exp 更大）。防反向覆盖：若脚本先 ③ 续期（config 手里是
    #    新活 rt，客户端那份旧 rt 已被消费成死签），客户端随后回写 auth-v2.dat 时，
    #    无条件写回会用死 rt 顶掉活 rt，导致下次到期自动续期全失败被误判失效。
    if not force_refresh and live and _fresh(live.get("token")):
        live["_source"] = "client"
        if live.get("refreshToken"):
            cfg_exp = _jwt_exp((cfg or {}).get("token") or "")
            if _jwt_exp(live["token"]) >= cfg_exp:
                try:
                    save_cfg(live["token"], live["refreshToken"],
                             {"user": _user_dict(live).get("name")})
                except Exception:
                    pass
        return live

    # ② config 新鲜 → 直接用
    if cfg and _fresh(cfg.get("token")):
        cfg["_source"] = "config"
        return cfg

    # ③ 都临期/过期 → 用 rt 续期（不论 token 来自 config 还是 live，只要手里有任何 rt）
    # force 模式下跳过"本地判新鲜"过滤——本地 exp 与服务端判决不一致（401 场景）时照样强刷。
    rt_cands = []
    if cfg and cfg.get("token") and cfg.get("refreshToken") and \
            (force_refresh or not _fresh(cfg["token"])):
        rt_cands.append((cfg["token"], cfg["refreshToken"], "config"))
    if live and live.get("refreshToken") and \
            (force_refresh or not _fresh(live.get("token"))) and \
            live["refreshToken"] not in [x[1] for x in rt_cands]:
        rt_cands.append((live.get("token") or "", live["refreshToken"], "client"))
    user0 = _user_dict(cfg).get("name") if cfg else _user_dict(live).get("name")
    for base_tok, rt, src in rt_cands:
        st, j = call("POST", "/api/v1/deviceToken/refresh", base_tok,
                     body={"refresh_token": rt, "target": "c"},
                     label="refresh(自动续期:%s)" % src)
        tok = (j or {}).get("device_token")
        nrt = (j or {}).get("refresh_token")
        if st == 200 and tok and nrt:
            save_cfg(tok, nrt, {"user": user0})
            print("[续期] 自动续期(%s)成功 → 新 token 剩余约 %d 天" %
                  (src, max(0, _jwt_exp(tok) - int(time.time())) // 86400))
            out = {"token": tok, "refreshToken": nrt, "user": user0,
                   "_source": "auto-renewed:" + src}
            return out
        print("[续期] 自动续期(%s) HTTP %s %s" % (src, st, str(j)[:120]))

    # ④ 兜底：返回手头过期凭证（_core 的 401 强刷重试是最后防线），并明确提示
    if rt_cands:
        print("[续期] 全部 rt 候选续期失败 — 需打开桌面端重新登录一次"
              "（脚本会随后同步新 rt）")
    if cfg and cfg.get("token"):
        cfg["_source"] = "config-stale"
        return cfg
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
             {"user": _user_dict(c).get("name"),
              "tier": _user_dict(c).get("tier")})
    st, d = get_wallets(c["token"])
    print("[OK] 凭证来源=%s 用户=%s 版本=%s" % (c.get("_source"),
          _user_dict(c).get("name"), _user_dict(c).get("tier")))
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
    # ★2026-10-31 兼容：config 的 user 历史上被存成字符串(cmd_refresh 老写法)，
    # 客户端实时的 user 是 dict。统一归一，不再 AttributeError。
    u = _user_dict(c)
    print("[用户] %s | %s | 凭证来源=%s | token 到期=%s" % (
        u.get("name") or "-",
        u.get("tier") or "-",
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
    if d is None and st in (401, 403):
        # ★本地 exp 判新鲜但服务端已判死（提前轮换/撤销）→ 强制走一次自动续期重试。
        # 旧 load_credential 只在"本地判定过期"时才续期，这种时钟不一致场景会直接误红。
        print("[钱包] HTTP %s — 服务端判 token 无效，强制执行自动续期重试…" % st)
        c2 = load_credential(force_refresh=True)
        if c2 and c2.get("token") != token:
            token = c2["token"]
            print("[用户] 续期后凭证来源=%s" % c2.get("_source"))
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
    save_cfg(tok, rt, {"user": _user_dict(c).get("name")})
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
