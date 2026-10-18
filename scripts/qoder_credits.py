#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
qoder_credits.py — Qoder CN 每日领 100 Credits
==============================================
产品: Qoder CN 桌面端（%LOCALAPPDATA%/Programs/Qoder CN），用户数据 %APPDATA%/com.qodercn.app.stable
活动: 每日 100 通用 Credits，30 天有效，仅限桌面端领取（2026-09-18 起）

★ 凭证获取（无需抓包，全自动）:
  %APPDATA%/com.qodercn.app.stable/auth.v1.dat 是 Chromium「v10」加密信封，
  与浏览器 cookie / 千问办公 auth-v2.dat **同一套解密链**：
    Local State → os_crypt.encrypted_key → 去 "DPAPI" 5B 头 → CryptUnprotectData
    → 32B AES key → AESGCM(nonce=ev[3:15]).decrypt(ev[15:])
  明文: {"schemaVersion":1,"token":"dt-...","refreshToken":"drt-...","expiresAt":"...","user":{...}}
  ★优先实时读该文件（客户端自续期、不抢 refresh_token 轮换、不踢下线）；
    qoder_config.json 仅作兜底/便携。token 前缀 dt-（device token）。

★ 接口（2026-10-15 抓包验证）:
  HOST = https://openapi.qoder.com.cn
  GET  /sash/api/v1/me/campaigns
       → {uid, showCampaign, claimable, campaignUrl, campaigns:[
            {campaignId, campaignKey, actionType, startAt, endAt, claimStatus,
             benefit:{kind, amount, validity:{mode,days|fixedEnd}},
             requiredAchievementKey, achievementCompleted, unavailableReason, placements[]}]}
  POST /sash/api/v1/me/campaigns/{campaignId}/claim     body 空（content-length: 0）
       → {grantId, status:"CLAIMED", replayed:bool, benefit:{...},
          campaignId, campaignKey, claimedAt, grantedAt, expiresAt}

★ 必需请求头（2026-10-15 二分实测）:
  authorization: Bearer <dt-token>   +   cosy-clienttype: 10
  其余全是**装饰性**头，缺了照样 200：cosy-version / cosy-machineos /
  cosy-machinehostname / cosy-machineid / cosy-machinetoken / cosy-machinecode /
  cosy-machinetype / bx-v / sec-* / origin / referer / cookie —— 全部不需要。
  ★但**不能完全没有 cosy-clienttype**：缺任何 cosy-* 时服务端返回
    {"showCampaign":false,"campaigns":[]}（按客户端类型过滤活动），不报错但拿不到活动。

★ 关键机制:
  - 活动**每日一期**：窗口为北京时间当日 10:00 ~ 次日 09:59（实测 startAt/endAt
    相隔 86340s），每期 campaignId 是新的 UUIDv7 → **绝不能硬编码 campaignId**，
    必须每次 GET campaigns 动态取。campaignKey（如 act-20261013-847）是活动模板 key，不随期变。
  - 挑选: actionType=="CLAIM_BENEFIT" 且 benefit.kind=="CREDITS"（每日 100 的那期）
  - ★窗口切换边界：总控 10:00 跑与窗口开场(10:00)几乎重合，此刻列表里可能同时存在刚
    过期的旧一期(已 CLAIMED)与新一期。若按返回顺序取首个匹配，会误判「今日已领」而
    **静默漏领整天** —— 故优先挑「窗口覆盖当前时刻」的那期；若选中的是已过期一期，
    等 WAIT_ROLL 秒重取一次。
  - 幂等: claimStatus=="CLAIMED" 直接跳过；重复 claim 返回**同一 grantId** 且
    replayed=true，服务端不重复发放 —— 可安全每天跑。

配置 qoder_config.json（可选兜底）: {"token": "dt-...", "refreshToken": "drt-..."}

★ 保活（2026-10-18 照 Our Free Model 的 qoder-oauth.ts 移植，但★默认不动手）:
  POST {host}/api/v1/deviceToken/refresh  body {"refresh_token","machine_id"}
    → {token|device_token|access_token, refresh_token?, expires_at?, user_id?, user_name?}
  三条硬约束（不遵守就会把桌面端踢下线）：
    ① 桌面端 auth.v1.dat 持有**同一支** refresh_token（轮换制）——我们刷一次它就被作废，
       客户端下次自续期必被拒、只能重登。故只在**已过期/临期(<1h)** 时才发，且要 `--force`。
    ② 刷请求要 `machine_id`（设备登录时生成）。本机 auth.v1.dat 里**没有**这个字段、
       也查不到 machine_token.json → 取不到就**不猜、不发**（瞎编 id 等于凭空注册新设备）。
    ③ 新凭证只写 qoder_<variant>_live_cache.json，★绝不回写 auth.v1.dat。
  判据：expiresAt / refreshTokenExpiresAt 一律由服务端给的值算，解不出就当未知、不刷。

★ 空活动列表的三种情形（旧版只会笼统报"头缺失"，容易误判成脚本失效）:
  a) 有 CLAIMED 但没 CLAIMABLE → 今日已领（幂等）；10:00 前跑则报"尚未刷新"（别当已领）
  b) 列表里没有任何 CLAIM_BENEFIT **且** usage 里没有 addOnQuota
     → 【Qoder未开通每日领取】：该账号从没在 Qoder 侧开通过，解法是**用官方桌面客户端登录一次**，
       不是失效（照 OFM isQoderNotActivated）
  c) 真空列表 → 才是 cosy-clienttype 头缺失或活动下线

用法:
  python qoder_credits.py status        # 只读：活动清单 + 今日是否已领
  python qoder_credits.py auto          # 每日：领取全部 CLAIMABLE 活动（定时任务用这个）
  python qoder_credits.py probe         # 强制领取一次，打印服务端原文
  python qoder_credits.py keepalive     # 保活体检（只报有效期；过期/临期才考虑续期）
  python qoder_credits.py keepalive --force  # 强制试一次离线续期（★会作废桌面端那支 refresh_token）
  python qoder_credits.py init          # 从已安装客户端导入凭证到 config
"""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE_DIR, "qoder_config.json")
HOST = "https://openapi.qoder.com.cn"
UA = "QoderCN/0.4.7"

# ── 双区（2026-10-16 逆向 Our Free Model 桌面客户端补入）──────────────────
# OFM 的 qoder-product.ts 把 Qoder 拆成两个 product，端点与凭据**完全隔离**：
#   QODER    (id=qoder)   openApiBase=https://openapi.qoder.sh       authBase=qoder.com
#   QODER_CN (id=qodercn) openApiBase=https://openapi.qoder.com.cn   authBase=qoder.cn
# 签到端点两区同形（/sash/api/v1/me/campaigns + /claim），头也同为 cosy-clienttype:10，
# 故只换 host / UA / user-data 目录即可复用全部逻辑。
# ★国际版凭据目录名未实测（本机未装国际版），故给候选列表逐个试。
VARIANTS = {
    "cn": {"name": "Qoder CN", "host": "https://openapi.qoder.com.cn", "ua": "QoderCN/0.4.7",
           "dirs": ["com.qodercn.app.stable", "Qoder CN"],
           "cfg": "qoder_config.json", "required": True},
    "intl": {"name": "Qoder 国际版", "host": "https://openapi.qoder.sh", "ua": "Qoder/0.4.7",
             "dirs": ["com.qoder.app.stable", "Qoder"],
             "cfg": "qoder_intl_config.json", "required": False},
}
DEFAULT_VARIANTS = ("cn", "intl")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# 每日 100 Credits 的活动特征
ACTION_CLAIM = "CLAIM_BENEFIT"
KIND_CREDITS = "CREDITS"
WAIT_ROLL = 20  # 窗口切换（每日 10:00）时重取新一期的等待秒数


def _user_data_dir(variant="cn"):
    """返回该区**存在**的 user-data 目录；都不存在时回退首选（供报错提示用）。"""
    dirs = VARIANTS[variant]["dirs"]
    appdata = os.environ.get("APPDATA", "")
    for d in dirs:
        p = os.path.join(appdata, d)
        if os.path.isdir(p):
            return p
    return os.path.join(appdata, dirs[0])


# ── 凭证 ──────────────────────────────────────────────────────────────────
def _decrypt_auth(ud, variant="cn"):
    """解密 auth.v1.dat（Chromium v10 信封）。返回 dict 或 None。"""
    path = os.path.join(ud, "auth.v1.dat")
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
        print("[警告] 解密 auth.v1.dat 失败: %s" % e)
        return None


def load_credential(variant="cn"):
    """优先实时读桌面端凭证（客户端自续期），config 兜底。"""
    ud = _user_data_dir(variant)
    live = _decrypt_auth(ud, variant) if ud else None
    if live and live.get("token"):
        live["_source"] = "client"
        return live
    try:
        with open(_cfg_path(variant), encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("token"):
            cfg["_source"] = "config"
            return cfg
    except Exception:
        pass
    return None


def _cfg_path(variant="cn"):
    return os.path.join(BASE_DIR, VARIANTS[variant]["cfg"])


def save_cfg(c, variant="cn"):
    cfg = {"token": c.get("token", ""), "refreshToken": c.get("refreshToken", "")}
    u = c.get("user") or {}
    cfg["user"] = u.get("name") or u.get("email") or u.get("phone")
    cfg["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(_cfg_path(variant), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── HTTP ──────────────────────────────────────────────────────────────────
def _hdrs(token, variant="cn"):
    return {"user-agent": VARIANTS[variant]["ua"],
            "accept": "*/*",
            "cosy-clienttype": "10",          # ★唯一必需的业务头（两区同值）
            "authorization": "Bearer " + token}


def call(method, path, token, label="", quiet=False, variant="cn"):
    url = VARIANTS[variant]["host"] + path
    req = urllib.request.Request(url, data=None, headers=_hdrs(token, variant), method=method)
    try:
        r = urllib.request.urlopen(req, timeout=25, context=CTX)
        raw = r.read()
        try:
            return r.status, json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return r.status, {"raw": raw.decode("utf-8", "replace")[:200]}
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
def get_campaigns(token, variant="cn"):
    return call("GET", "/sash/api/v1/me/campaigns", token, "campaigns", variant=variant)


def _in_window(c, now):
    """活动窗口是否覆盖当前时刻。缺窗口字段视为覆盖（服务端字段变更时保守放行）。"""
    try:
        return float(c.get("startAt")) <= now <= float(c.get("endAt"))
    except (TypeError, ValueError):
        return True


def _window_over(c):
    """窗口是否已过期（endAt 早于当前时刻）。"""
    try:
        return float(c.get("endAt")) < time.time()
    except (TypeError, ValueError):
        return False


def pick_credits(campaigns, now=None):
    """挑出每日 Credits 活动：CLAIM_BENEFIT + benefit.kind=CREDITS。

    ★活动每日一期、每期 campaignId 是新的 UUIDv7；总控 10:00 跑与窗口开场(10:00 CST)
    几乎重合，此刻列表里可能**同时存在刚过期的旧一期(已 CLAIMED)与新一期**——若按返回
    顺序取首个匹配，就会误判「今日已领」而**静默漏领整天**。故优先挑「窗口覆盖当前时刻」
    的那一期，取不到再回退到任意一期。
    """
    now = float(now) if now is not None else time.time()
    cands = [c for c in (campaigns or [])
             if c.get("actionType") == ACTION_CLAIM
             and (c.get("benefit") or {}).get("kind") == KIND_CREDITS]
    if not cands:
        return None
    live = [c for c in cands if _in_window(c, now)]
    return (live or cands)[0]


def claimable_benefits(campaigns):
    """所有「可领」的 claim benefit（★按官方实现：不看 benefit.kind，全领再累加）。

    我们的旧版只领挑中的那一个；若服务端某天下发多个 CLAIMABLE（例如每日 100 +
    一个运营加码），旧版会静默漏掉其余。按 CLAIMABLE 全领更贴近官方客户端行为。
    """
    return [c for c in (campaigns or [])
            if c.get("actionType") == ACTION_CLAIM and c.get("claimStatus") == "CLAIMABLE"]


def claimed_benefit(campaigns):
    """列表里是否存在已领过的 CLAIM_BENEFIT（用来区分「今天已领」与「压根没活动」）。"""
    return any(c.get("actionType") == ACTION_CLAIM and c.get("claimStatus") == "CLAIMED"
               for c in (campaigns or []))


def campaign_refreshed_today(now=None):
    """每日活动在**北京时间 10:00** 换期（OFM QODER_CAMPAIGN_REFRESH_HOUR_UTC8=10）。
    10 点前跑，列表里还是昨天那一轮——此时判「今天已领」是错的，该说「尚未刷新」。"""
    try:
        from datetime import timedelta
        return (datetime.now(timezone.utc) + timedelta(hours=8)).hour >= 10
    except Exception:
        return True


def account_not_activated(campaigns, usage_body):
    """★「账号未开通每日领取」与「凭证失效」的鉴别（照 OFM isQoderNotActivated）：
    活动列表里没有任何 CLAIM_BENEFIT，**且** usage 里没有 addOnQuota 字段
    → 该账号从没在 Qoder 侧开通过每日领取，唯一解法是用官方桌面客户端登录一次它；
    不是脚本报废、也不是登录失效。"""
    if campaigns is None:
        return False
    if any(c.get("actionType") == ACTION_CLAIM for c in (campaigns or [])):
        return False
    if not isinstance(usage_body, dict):
        return False
    usage = usage_body.get("qoderUsage")
    if not isinstance(usage, dict):
        return False
    return usage.get("addOnQuota") is None


def _ts(v):
    try:
        return datetime.fromtimestamp(int(v), timezone.utc).astimezone().strftime("%m-%d %H:%M")
    except Exception:
        return "-"


def fmt_campaign(c):
    if not c:
        return "无 CREDITS 类活动"
    b = c.get("benefit") or {}
    v = b.get("validity") or {}
    return ("%s | +%s %s（%s天有效）| claimStatus=%s | 窗口 %s ~ %s"
            % (c.get("campaignKey"), b.get("amount"), b.get("kind"),
               v.get("days"), c.get("claimStatus"),
               _ts(c.get("startAt")), _ts(c.get("endAt"))))


def do_claim(token, cid, variant="cn"):
    return call("POST", "/sash/api/v1/me/campaigns/%s/claim" % cid, token, "claim", variant=variant)


# ── 账号未开通鉴别 ──────────────────────────────────────────────────────────
USAGE_PATH = "/sash/api/v2/me/usage"


def get_usage(token, variant="cn"):
    """用量接口（只为鉴别"账号未开通"，失败不致命 → 静默返回 None）。"""
    st, j = call("GET", USAGE_PATH, token, "usage", quiet=True, variant=variant)
    return j if st == 200 and isinstance(j, dict) else None


# ── 保活：deviceToken 离线续期（2026-10-18 照 OFM qoder-oauth.ts 移植）────────
# POST {host}/api/v1/deviceToken/refresh  body {"refresh_token","machine_id"}
#   → {token|device_token|access_token, refresh_token, expires_at, refresh_token_expires_at,
#      user_id, user_name}
# ⚠⚠ **默认不动手**，两个硬原因：
#   ① refresh_token 是轮换制。桌面端自己持有**同一支**（本机 auth.v1.dat），我们刷一次
#      就把它的 refresh_token 作废 → 客户端下次自续期会被拒、被迫重新登录。
#      故只在「桌面端凭证已过期/临期且客户端没在跑」时才值得刷，且必须显式 --force。
#   ② 刷请求要带 `machine_id`（设备登录时生成、存在客户端自己的凭据里），
#      本机 auth.v1.dat **没有这个字段**，machine_token.json 也不存在 → 现取不到。
#      缺 machine_id 时不猜、不发（猜出来的 id 等于凭空注册新设备）。
# 新凭证只写 qoder_live_cache.json，★绝不回写 auth.v1.dat。
REFRESH_PATH = "/api/v1/deviceToken/refresh"
LIVE_CACHE_TPL = "qoder_%s_live_cache.json"
REFRESH_LEAD_S = 3600                      # 距过期不足 1h 才认为"该续期"（OFM REFRESH_LEAD_MS）
REFRESH_TERMINAL = ("invalid_grant", "expired", "revoked", "invalid refresh token")


def _parse_iso(v):
    """ISO8601 → epoch 秒；解不出返回 None（★过期时间只认服务端给的值，绝不猜）。"""
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        pass
    try:
        return int(float(v))
    except Exception:
        return None


def cred_expiry(c):
    """(access 到期秒, refresh_token 到期秒)。auth.v1.dat 用 expiresAt/refreshTokenExpiresAt。"""
    return _parse_iso(c.get("expiresAt")), _parse_iso(c.get("refreshTokenExpiresAt"))


def load_live_cache(variant="cn"):
    p = os.path.join(BASE_DIR, LIVE_CACHE_TPL % variant)
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("token") else None
    except Exception:
        return None


def save_live_cache(variant, cred):
    try:
        with open(os.path.join(BASE_DIR, LIVE_CACHE_TPL % variant), "w", encoding="utf-8") as f:
            json.dump(cred, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[警告] 续期缓存写入失败: %s" % e)


def pick_live_credential(variant="cn"):
    """取当前可用凭证：桌面端 auth.v1.dat 优先；过期/临期时才考虑自己缓存的续期结果。
    返回 (cred, 说明)。"""
    ud = _user_data_dir(variant)
    live = _decrypt_auth(ud, variant) if ud else None
    cached = load_live_cache(variant)
    now = time.time()
    for src, c in (("client", live), ("cache", cached)):
        if not c or not c.get("token"):
            continue
        exp, _rt = cred_expiry(c)
        if exp is None or exp - now > REFRESH_LEAD_S:
            return c, src
    # 两个都不新鲜：优先返回客户端那份（至少它可能是刚被客户端自己续过的）
    if live and live.get("token"):
        return live, "client(临期)"
    if cached and cached.get("token"):
        return cached, "cache(临期)"
    return None, "-"


def refresh_token(variant, cred, force=False):
    """离线续期一次。默认仅在客户端凭据已过期时动手；同一支 refresh_token 只试一次。"""
    rt = cred.get("refreshToken") or cred.get("refresh_token") or ""
    mid = cred.get("machineId") or cred.get("machine_id") or ""
    if not rt:
        return False, "无 refresh_token — 只能在桌面端重新登录"
    if not mid:
        return False, ("缺 machine_id（auth.v1.dat 里没有该字段、machine_token.json 也不存在）"
                       "——不猜、不发；请在桌面端重新登录一次")
    if not force:
        exp, _ = cred_expiry(cred)
        if exp is not None and exp - time.time() > REFRESH_LEAD_S:
            return False, "距过期还早（>1h），不动轮换凭证"
    last = cred.get("_refreshed_at") or 0
    if last and time.time() - last < 6 * 3600:
        return False, "同一支 refresh_token 已在 %s 前试过（6h 内不重复烧）" % int((time.time() - last) / 60)
    body = json.dumps({"refresh_token": rt, "machine_id": mid}).encode()
    req = urllib.request.Request(VARIANTS[variant]["host"] + REFRESH_PATH, data=body, method="POST",
                                 headers={"content-type": "application/json", "accept": "application/json",
                                          "user-agent": VARIANTS[variant]["ua"]})
    try:
        with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
            st, parsed = r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        st = e.code
        raw = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw": raw[:200]}
    except Exception as e:
        return False, "续期网络失败：%s" % e
    if st in (401, 403):
        return False, "续期被拒（HTTP %s）— 终态，需在桌面端重新登录" % st
    if st != 200:
        low = json.dumps(parsed, ensure_ascii=False).lower()
        if any(m in low for m in REFRESH_TERMINAL):
            return False, "续期终态（%s）— 不再重试，请重新登录" % str(parsed)[:120]
        return False, "续期失败 HTTP %s %s" % (st, str(parsed)[:160])
    tok = parsed.get("token") or parsed.get("device_token") or parsed.get("access_token") or ""
    if not tok:
        return False, "续期响应缺少 token — 终态，请重新登录"
    nxt = dict(cred)
    nxt.update({"token": tok,
                # ★响应可能不带新 refresh_token，必须沿用旧的，不能覆盖成空
                "refreshToken": parsed.get("refresh_token") or parsed.get("refreshToken") or rt,
                "expiresAt": parsed.get("expires_at") or parsed.get("expiresAt") or cred.get("expiresAt"),
                "_refreshed_at": int(time.time())})
    rtx = parsed.get("refresh_token_expires_at") or parsed.get("refreshTokenExpiresAt")
    if rtx:
        nxt["refreshTokenExpiresAt"] = rtx
    save_live_cache(variant, nxt)
    return True, nxt


# ── 命令 ──────────────────────────────────────────────────────────────────
def cmd_init(variant="cn"):
    c = load_credential(variant)
    if not c:
        print("[失败] 未找到凭证 — 需安装并登录「%s」桌面端（%s）"
              % (VARIANTS[variant]["name"], _user_data_dir(variant)))
        return 2
    save_cfg(c, variant)
    st, j = get_campaigns(c["token"], variant)
    print("[OK] 凭证来源=%s 用户=%s" % (c.get("_source"),
          (c.get("user") or {}).get("name") or (c.get("user") or {}).get("email")))
    if st != 200:
        print("[警告] campaigns HTTP %s" % st)
    else:
        print("[活动] " + fmt_campaign(pick_credits(j.get("campaigns"))))
    print("[OK] 已写入 %s" % _cfg_path(variant))
    return 0


def _core(force=False, variant="cn"):
    name = VARIANTS[variant]["name"]
    c, src = pick_live_credential(variant)
    if not c:
        if not VARIANTS[variant]["required"]:
            # 国际版是「装了才算」——没装不是失效，静默跳过，别污染日报。
            return 0
        print("[失败] 未找到凭证 —【Qoder失效】需安装并登录桌面端")
        return 2
    token = c["token"]
    u = c.get("user") or {}
    exp, rt_exp = cred_expiry(c)
    print("[%s][用户] %s | 凭证来源=%s | token 到期=%s | refresh 到期=%s"
          % (name, u.get("name") or u.get("email") or u.get("phone") or "-", src,
             time.strftime("%Y-%m-%d %H:%M", time.localtime(exp)) if exp else "?",
             time.strftime("%Y-%m-%d", time.localtime(rt_exp)) if rt_exp else "?"))

    st, j = get_campaigns(token, variant)
    if st in (401, 403):
        ok, res = refresh_token(variant, c, force=force)
        if ok:
            print("[%s][保活] 已离线续期，重试一次…" % name)
            token = res["token"]
            st, j = get_campaigns(token, variant)
        else:
            print("[%s][保活] 未续期：%s" % (name, res))
    if st != 200:
        print("[%s][失败] campaigns HTTP %s —【Qoder失效】凭证需重新登录" % (name, st))
        return 3
    campaigns = j.get("campaigns") or []
    targets = claimable_benefits(campaigns)

    # ── 无可领：分三种情形说清（旧版只会笼统报"空列表/头缺失"，容易误判成失效）──
    if not targets and not force:
        if claimed_benefit(campaigns):
            stale = all(_window_over(x) for x in campaigns
                        if x.get("actionType") == ACTION_CLAIM and x.get("claimStatus") == "CLAIMED")
            if stale:
                # ★窗口切换边界：总控 10:00 跑、窗口也 10:00 开，此刻拿到的可能仍是刚过期的一期。
                # 直接当"今日已领"会漏领整天 → 等 WAIT_ROLL 秒重取一次。
                print("[%s][窗口切换] 已领的那期刚过期 — 等 %ds 重取新一期..." % (name, WAIT_ROLL))
                time.sleep(WAIT_ROLL)
                st3, j3 = get_campaigns(token, variant)
                if st3 == 200:
                    campaigns = j3.get("campaigns") or []
                    targets = claimable_benefits(campaigns)
            if not targets:
                if not campaign_refreshed_today():
                    print("[%s][未刷新] 今日活动尚未刷新（每日 10:00 换期，现在还没到）"
                          "— 看到的是一个昨天那轮，10 点后重跑即可" % name)
                    return 0
                print("[%s][跳过] 今日已领取（claimStatus=CLAIMED，每日 10:00 刷新下一期）" % name)
                return 0
        elif not campaigns:
            usage = get_usage(token, variant)
            if account_not_activated(campaigns, usage):
                print("[%s][未开通] 【Qoder未开通每日领取】该账号从没在 Qoder 侧开通过每日 100 Credits"
                      "（列表无 CLAIM_BENEFIT 且 usage 无 addOnQuota）"
                      "— 不是脚本失效：用官方桌面客户端登录一次该账号即开通" % name)
                return 4
            print("[%s][提示] 服务端返回空活动列表（showCampaign=%s）— 通常是 cosy-clienttype 头缺失或活动已下线"
                  % (name, j.get("showCampaign")))
            return 3
        else:
            print("[%s][跳过] 当前无可领取活动（claimable=%s，共 %d 期）"
                  % (name, j.get("claimable"), len(campaigns)))
            return 4

    item = pick_credits(campaigns)
    print("[%s][活动] " % name + fmt_campaign(item))
    if force and not targets:
        targets = [item] if item else []
    if not targets:
        print("[%s][跳过] 当前无每日 Credits 活动（可能已结束或未到窗口）" % name)
        return 4
    if len(targets) > 1:
        print("[%s][多期可领] 本期列表里有 %d 个 CLAIMABLE 活动，逐个领取" % (name, len(targets)))

    total = 0
    rc = 0
    for t in targets:
        cid = t.get("campaignId")
        b = t.get("benefit") or {}
        v = b.get("validity") or {}
        st2, r = do_claim(token, cid, variant)
        if st2 != 200:
            print("[%s][领取失败] %s HTTP %s %s" % (name, t.get("campaignKey"), st2, str(r)[:200]))
            rc = 5
            continue
        rb = r.get("benefit") or {}
        if r.get("replayed") is True:
            print("[%s][已领取] %s 重复提交，服务端幂等未重复发放（grantId=%s）"
                  % (name, r.get("campaignKey"), r.get("grantId")))
            continue
        if r.get("status") and r.get("status") != "CLAIMED":
            print("[%s][未成功] %s status=%s" % (name, t.get("campaignKey"), r.get("status")))
            rc = 5
            continue
        amount = rb.get("amount") if rb.get("amount") is not None else b.get("amount")
        try:
            total += float(amount or 0)
        except Exception:
            pass
        print("[%s][领取成功] +%s %s（%s天有效）→ 到期 %s"
              % (name, amount, rb.get("kind") or b.get("kind"), v.get("days"),
                 (r.get("expiresAt") or "")[:10]))
        print("[%s][本期] %s | grantId=%s | status=%s"
              % (name, r.get("campaignKey"), r.get("grantId"), r.get("status")))
    if total == 0 and rc == 0:
        print("[%s][汇总] 本轮无新增发放（全部幂等）" % name)
    elif total > 0:
        print("[%s][汇总] 本轮共 +%s Credits" % (name, ("%g" % total)))
    return rc


def cmd_keepalive(variant="cn"):
    """保活体检：只报有效期；仅在已过期时（或 --force）才动轮换凭证。"""
    name = VARIANTS[variant]["name"]
    c, src = pick_live_credential(variant)
    if not c:
        if not VARIANTS[variant]["required"]:
            return 0          # 没装国际版不是失效，别在体检输出里刷屏
        print("[%s] 未找到凭证（需装并登录桌面端）" % name)
        return 2
    exp, rt_exp = cred_expiry(c)
    left = (exp - time.time()) / 86400.0 if exp else None
    print("[%s][保活] 来源=%s | token 到期=%s%s | refresh 到期=%s"
          % (name, src, time.strftime("%Y-%m-%d %H:%M", time.localtime(exp)) if exp else "?",
             ("（剩 %.1f 天）" % left) if left is not None else "",
             time.strftime("%Y-%m-%d", time.localtime(rt_exp)) if rt_exp else "?"))
    print("[%s][保活] machine_id=%s | 本地续期缓存=%s"
          % (name, "有" if (c.get("machineId") or c.get("machine_id")) else "★无（取不到就不发刷请求）",
             "有" if load_live_cache(variant) else "无"))
    if left is not None and left > REFRESH_LEAD_S / 86400.0:
        print("[%s][保活] 距过期还早 — 不发续期请求（桌面端持有同一支 refresh_token，抢刷会把它踢下线）" % name)
        return 0
    force = "--force" in sys.argv[2:]
    ok, res = refresh_token(variant, c, force=force)
    if ok:
        print("[%s][保活] 已离线续期 → 写入 %s" % (name, LIVE_CACHE_TPL % variant))
        return 0
    print("[%s][保活] 未续期：%s" % (name, res))
    return 0 if not force else 1


def _variants(argv):
    """--variant cn|intl|all（默认 all：两区串行，未装的区静默跳过）。"""
    v = "all"
    for i, a in enumerate(argv):
        if a == "--variant" and i + 1 < len(argv):
            v = argv[i + 1]
        elif a.startswith("--variant="):
            v = a.split("=", 1)[1]
    if v == "all":
        return list(DEFAULT_VARIANTS)
    if v in VARIANTS:
        return [v]
    print("[x] 未知 --variant: %s（cn/intl/all）" % v)
    return []


def _run(cmd):
    """按区串行执行；只要 CN 成功就返回 0（国际版没装不算失败）。"""
    vs = _variants(sys.argv[2:])
    if not vs:
        return 1
    rc = 0
    for v in vs:
        if cmd == "init":
            r = cmd_init(v)
        elif cmd == "keepalive":
            r = cmd_keepalive(v)
        else:
            r = _core(force=(cmd == "probe"), variant=v)
        # 只让「必需区」(cn) 的失败影响退出码
        if VARIANTS[v]["required"] and r != 0:
            rc = r
    return rc


def cmd_status():
    return _run("status")


def cmd_auto():
    return _run("auto")


def cmd_probe():
    return _run("probe")


def cmd_init_all():
    return _run("init")


def cmd_keepalive_all():
    return _run("keepalive")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "init":
        sys.exit(cmd_init_all())
    elif cmd == "status":
        sys.exit(cmd_status())
    elif cmd == "auto":
        sys.exit(cmd_auto())
    elif cmd == "probe":
        sys.exit(cmd_probe())
    elif cmd == "keepalive":
        sys.exit(cmd_keepalive_all())
    else:
        print(__doc__)
        sys.exit(1)
