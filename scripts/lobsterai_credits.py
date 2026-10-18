#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
lobsterai_credits.py — LobsterAI（有道龙虾）每日签到领积分
=========================================================
产品: LobsterAI 桌面端（lobsterai-server.youdao.com）
奖励: 每日签到积分（实测「每日登录奖励」100/天，有效期约一周，逐日发放）

★ 协议来源（2026-10-16 分析 GitHub 开源项目 Ebony-Vinyl/dsh-our-free-model 的
  vendor/channel-pack/src/lobsterai-credits.ts，其重构自 lobsterai2api/sigin.py，
  为实测可用的参考实现）:

  0) 版本号  GET https://api-overmind.youdao.com/openapi/get/luna/hardware/lobsterai/prod/update
            → 外层 {code, msg}，载荷在 data.value.version（★非统一信封）
  1) 槽位    GET {apiBase}/api/client-activities/slot
                 ?placement=desktop_sidebar&clientVersion=<V>&containerApiVersion=2&platform=win32
            → data.activity.activityCode / data.slotState / activity.configRevision
  2) 上下文  GET {apiBase}/api/client-activities/{activityCode}/context?configRevision=<N>
            → data.state.claimedToday / data.actions[]（须含 "check_in"）
  3) 签到    POST {apiBase}/api/client-activities/{activityCode}/actions/check_in
            body {configRevision, idempotencyKey:<uuid4>, payload:{}}
            → data.result.creditsGranted | rewardCredits | credits（三级回退）

  余额: GET {apiBase}/api/user/profile-summary
       → data.creditItems[]（label/creditsRemaining/expiresAt）+ data.totalCreditsRemaining
       ★用 profile-summary 不用 /api/user/quota（后者只显示 freeCreditsTotal=300，
         不含活动积分；实测 profile-summary 5297.72 vs quota 300）

★ 认证（三级，auto 择优；2026-10-18 起首选模式C）:
  模式C「桌面端免抓包 + 离线续期」（★首选，零配置）:
    直接读本机 LobsterAI 桌面端自己的存储 %APPDATA%/LobsterAI/lobsterai.sqlite 的
    `kv` 表（只读，`mode=ro&immutable=1` 起、失败回退 `mode=ro`；客户端在跑也读得出）：
      auth_tokens                    → {accessToken, refreshToken}
      keyfrom.attribution.v1         → {firstKeyfrom, latestKeyfrom, updatedAt}
      auth_user                      → {userId, yid, nickname, phone, accountMode}
      installation_uuid              → uuid（38 位）
      client_sidebar_banner.schedule.desktop_sidebar.v2 → clientVersion（本机实测 2026.10.13）
    accessToken 是 **JWT**（payload: accountMode/exp/iat/sub/type/yid），实测有效期约 30 天
    → 过期时间一律由 JWT `exp` 或续期响应的 `expiresIn` 算，**别猜**。
    续期：POST {apiBase}/api/auth/refresh，★**匿名头**（不带 Authorization）
      body {firstKeyfrom, latestKeyfrom, version, uuid, userId, refreshToken}
      ★ firstKeyfrom/latestKeyfrom 用**存储的原值**，不取当前时刻——对齐官方客户端
        （其 RefreshToken 从不更新该字段，每次发的都是登录那一刻的值）。
      → data {accessToken, refreshToken, expiresIn, user{...}}
      ⚠ refreshToken 可能**不在响应里** → 必须沿用旧值，不能覆盖成空串。
      ⚠ refresh_token 是轮换制 → **同一支只试一次**；HTTP 401/403 或响应含
        `40100/40101/token rejected/refresh token was rejected` 视为终态，绝不重试。
      ⚠ 新凭证**只写自己的 lobsterai_live_cache.json，绝不回写桌面端 sqlite**
        （客户端在跑会争抢同一支，回写会把它的登录态搞坏）。
    距过期不足 1h（REFRESH_LEAD）才刷；还早就直接用，零副作用。
  模式A「Web 门户 cookie」（次选，需浏览器保持登录）:
    浏览器登录 lobsterai.youdao.com 后，抓包任意 lobsterai-server.youdao.com
    请求的整串 Cookie 写入 config 的 "cookie" 字段。实测全链路可用
    （profile-summary / slot / context / check_in 均返回 code:0）。
    ★判据订正（2026-10-18）：服务端**只认 `lobsterai_web_session`**（host_key 在
      `lobsterai-server.youdao.com`）——`NTES_YD_SESS`/`DICT_SESS` 不在盘上也能过，
      别把它们当"没登录"的判据。该值会被服务端重建，config 里的旧值不会自动更新
      （本平台不在第 0 步 cookie_sync 名单里），所以「请先登录」多半是**陈旧 cookie**
      而非账号失效：先按模式C 或 `browser_cookies.extract_full(...)` 重取再判。
  模式B「桌面客户端 Bearer（手工抓包）」:
    抓桌面端请求的 Authorization: Bearer <access_token> 写入 "access_token"。
    ⚠ 桌面客户端默认「direct mode」强制直连（日志原话 System proxy disabled），
    Reqable 系统代理抓不到它的流量——要抓得先改客户端代理设置；★有桌面端在装了模式C
    就根本不用抓包，本模式仅留作异地/无桌面端时的兜底。

★ 幂等: 客户端幂等（idempotencyKey uuid4）+ 双重预检（claimedToday 与 actions
  含 check_in 都要判）——只看 claimedToday 会漏「活动有但今天不该领」。

★ 槽位参数固定值（照抄 sigin.py，与运行环境无关，改了可能拿不到活动）:
  placement=desktop_sidebar / containerApiVersion=2 / platform=win32

配置 lobsterai_config.json（二选一，均可只配一个字段）:
  模式A（推荐）: {"cookie": "<Thorium 登录 lobsterai.youdao.com 后的整串 Cookie>"}
  模式B: {"access_token": "<桌面端 Bearer 值>"}

用法:
  python lobsterai_credits.py status        # 只读：活动槽位 + 签到状态 + 余额
  python lobsterai_credits.py auto          # 每日：三步签到（定时任务用这个）
  python lobsterai_credits.py probe         # 强制走一遍，打印每步服务端原文
  python lobsterai_credits.py init          # 交互式写入配置
"""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE_DIR, "lobsterai_config.json")
API_BASE = "https://lobsterai-server.youdao.com"
VERSION_API = "https://api-overmind.youdao.com/openapi/get/luna/hardware/lobsterai/prod/update"
FALLBACK_VERSION = "2026.9.4"
UA = "LobsterAI/2026.9.4"
TIMEOUT = 30

# 槽位固定参数（照抄 sigin.py）
SLOT_PLACEMENT = "desktop_sidebar"
SLOT_CONTAINER_API_VERSION = "2"
SLOT_PLATFORM = "win32"

# ── 模式C：桌面端免抓包 + 离线续期（2026-10-18 逆向 Our Free Model lobsterai-oauth.ts）──
REFRESH_PATH = "/api/auth/refresh"
LIVE_CACHE_PATH = os.path.join(BASE_DIR, "lobsterai_live_cache.json")
USERDATA_DIRS = ("LobsterAI", "lobsterai")          # 同一客户端的两个写法，逐个试
REFRESH_LEAD_MS = 3600 * 1000                        # 距过期不足 1h 才刷（OFM REFRESH_LEAD_MS 同语义）
SESSION_DEAD_MARKERS = ("40100", "40101", "token rejected", "refresh token was rejected")
CLIENT_CAPABILITIES = "kimi-k3-agentic-v1,thinking-level-control-v1"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def load_cfg():
    if not os.path.exists(CFG_PATH):
        return {}
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ── 模式C：桌面端凭证 + 保活 ────────────────────────────────────────────────
def _jwt_exp_ms(token):
    """JWT 的 exp（毫秒）。非 JWT / 解不出 → None（★过期时间只有这一条来路 + expiresIn）。"""
    try:
        import base64
        seg = (token or "").split(".")[1]
        seg += "=" * (-len(seg) % 4)
        exp = json.loads(base64.urlsafe_b64decode(seg)).get("exp")
        return int(exp) * 1000 if exp else None
    except Exception:
        return None


def _kv_from_sqlite(path):
    """只读打开桌面端 sqlite 的 kv 表。客户端在跑时 `mode=ro` 会撞锁，故先试 immutable。"""
    import sqlite3
    uri_base = "file:%s" % path.replace("\\", "/")
    for q in ("mode=ro&immutable=1", "mode=ro"):
        try:
            c = sqlite3.connect("%s?%s" % (uri_base, q), uri=True, timeout=3)
            try:
                return dict(c.execute("select key, value from kv"))
            finally:
                c.close()
        except Exception:
            continue
    return None


def read_desktop_credential():
    """从桌面端存储取 Bearer 凭证（免抓包、免浏览器）。没有则返回 None。"""
    appdata = os.environ.get("APPDATA", "")
    for d in USERDATA_DIRS:
        p = os.path.join(appdata, d, "lobsterai.sqlite")
        if not os.path.exists(p):
            continue
        kv = _kv_from_sqlite(p)
        if not kv:
            continue

        def _j(key):
            try:
                v = json.loads(kv.get(key) or "{}")
                return v if isinstance(v, dict) else {}
            except Exception:
                return {}

        tok = _j("auth_tokens")
        if not tok.get("accessToken"):
            continue
        kf = _j("keyfrom.attribution.v1")
        au = _j("auth_user")
        ver = ""
        for k, v in kv.items():
            if str(k).startswith("client_sidebar_banner.schedule."):
                try:
                    ver = json.loads(v).get("clientVersion") or ""
                except Exception:
                    ver = ""
                break
        exp = _jwt_exp_ms(tok["accessToken"])
        return {
            "access_token": tok["accessToken"],
            "refresh_token": tok.get("refreshToken") or "",
            "expires_at": exp,
            "first_keyfrom": str(kf.get("firstKeyfrom") or ""),
            "latest_keyfrom": str(kf.get("latestKeyfrom") or ""),
            "uuid": str(kv.get("installation_uuid") or "").strip('"'),
            "user_id": str(au.get("userId") or au.get("yid") or ""),
            "nickname": au.get("nickname") or "",
            "client_version": ver,
            "_source": "desktop-sqlite",
        }
    return None


def load_live_cache():
    try:
        with open(LIVE_CACHE_PATH, encoding="utf-8") as f:
            c = json.load(f)
        return c if isinstance(c, dict) and c.get("access_token") else None
    except Exception:
        return None


def save_live_cache(cred):
    """★只写自己的缓存，绝不回写桌面端 sqlite（客户端在跑会争抢同一支 refresh_token）。"""
    try:
        with open(LIVE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cred, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[警告] 续期缓存写入失败: %s" % e)


def _exp_ms(cred):
    for key in ("expires_at",):
        v = cred.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return _jwt_exp_ms(cred.get("access_token") or "")


def needs_refresh(cred, now_ms=None):
    """lead-time 判据：距过期不足 1h 才算该刷。拿不到过期时间时视为不需要（别滥烧轮换凭证）。"""
    exp = _exp_ms(cred)
    if exp is None:
        return False
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    return exp - now_ms <= REFRESH_LEAD_MS


def refresh_desktop(cred, verbose=False):
    """续期一次（★同一支只试一次，终态错误绝不重试）。返回 (ok, cred_or_msg)。"""
    if not cred.get("refresh_token"):
        return False, "桌面端凭据无 refresh_token，需在 LobsterAI 客户端重新登录一次"
    version = cred.get("client_version") or fetch_client_version()
    body = {
        "firstKeyfrom": cred.get("first_keyfrom") or "",
        # 用**存储的** latestKeyfrom，不取当前时刻——官方客户端 RefreshToken 从不更新它，
        # 每次发的都是登录那一刻的值（对齐其 auth.go/client.go 行为）。
        "latestKeyfrom": cred.get("latest_keyfrom") or "",
        "version": version,
        "refreshToken": cred["refresh_token"],
    }
    if cred.get("uuid"):
        body["uuid"] = cred["uuid"]
    if cred.get("user_id"):
        body["userId"] = cred["user_id"]
    headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": UA}
    req = urllib.request.Request(API_BASE + REFRESH_PATH, data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
            st, parsed = resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        st = e.code
        raw = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"_raw": raw[:200]}
    except Exception as e:
        return False, "续期网络失败：%s" % e
    raw_text = json.dumps(parsed, ensure_ascii=False)
    ok, data, msg = _envelope(parsed)
    if not ok:
        terminal = st in (401, 403) or any(m in raw_text or m in msg for m in SESSION_DEAD_MARKERS)
        label = "（终态，不再重试）" if terminal else ""
        return False, "续期失败%s：%s" % (label, msg)
    new_at = data.get("accessToken") or ""
    if not new_at:
        return False, "续期响应缺少 accessToken，请在 LobsterAI 客户端重新登录"
    exp_ms = _jwt_exp_ms(new_at)
    ei = data.get("expiresIn")
    if isinstance(ei, (int, float)) and ei > 0:
        exp_ms = int(time.time() * 1000) + int(ei) * 1000
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    nxt = dict(cred)
    nxt.update({
        "access_token": new_at,
        # ★响应可能不带新 refreshToken（沿用旧的）——覆盖成空串就等于烧掉续期能力
        "refresh_token": data.get("refreshToken") or cred["refresh_token"],
        "expires_at": exp_ms,
        "_source": "desktop-sqlite+refresh",
    })
    if user.get("nickname"):
        nxt["nickname"] = user["nickname"]
    if user.get("userId") or user.get("yid"):
        nxt["user_id"] = str(user.get("userId") or user.get("yid"))
    if verbose:
        print("[保活] 续期成功，新 expires_at=%s" % _fmt_ts(exp_ms))
    save_live_cache(nxt)
    return True, nxt


def _fmt_ts(ms):
    if not ms:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ms / 1000))


def resolve_cfg(pref="auto"):
    """按 pref 选认证链路，返回可直接喂给 _headers/_get/_post 的 cfg 字典。
    auto：桌面 Bearer（必要时先续期）> config.access_token > config.cookie。"""
    cfg = load_cfg()
    if pref in ("auto", "bearer"):
        cred = load_live_cache() or read_desktop_credential()
        if cred:
            if not cred.get("expires_at"):
                cred["expires_at"] = _exp_ms(cred)
            if pref == "auto" and needs_refresh(cred):
                ok, res = refresh_desktop(cred)
                cred = res if ok else cred
                if not ok:
                    print("[保活] 续期未完成（仍用现凭证试一次）：%s" % res)
            out = {"access_token": cred["access_token"], "_cred": cred}
            print("[鉴权] 桌面端 Bearer（免抓包，来源=%s）| 到期=%s | 用户=%s"
                  % (cred.get("_source"), _fmt_ts(cred.get("expires_at")), cred.get("nickname") or "-"))
            return out
    if pref in ("auto", "bearer") and cfg.get("access_token"):
        return {"access_token": cfg["access_token"]}
    if pref in ("auto", "cookie") and cfg.get("cookie"):
        print("[鉴权] Web 门户 cookie（config）")
        return {"cookie": cfg["cookie"]}
    return None


def keepalive_retry(cfg, err_msg):
    """Bearer 链路被服务端判过期时续期一次并返回新 cfg（只一次，终态不重试）。"""
    cred = cfg.get("_cred") if cfg else None
    if not cred:
        return None
    text = str(err_msg or "")
    if not any(k in text for k in ("401", "403", "失效", "请先登录", "accessToken")) \
            and not any(m in text for m in SESSION_DEAD_MARKERS):
        return None
    ok, res = refresh_desktop(cred, verbose=True)
    if not ok:
        print("[保活] %s" % res)
        return None
    print("[保活] 已续期，重试一次…")
    return {"access_token": res["access_token"], "_cred": res}



def _headers(cfg, accept="application/json"):
    """双认证模式：
    - config 有 cookie   → Web 门户模式（lobsterai.youdao.com 登录态的 cookie，
                          实测全链路可用：profile-summary/slot/context/check_in）
    - config 有 access_token → 桌面客户端模式（Bearer）
    两者都没配则报错。"""
    h = {
        "Accept": accept,
        "User-Agent": UA,
    }
    if cfg.get("cookie"):
        h["Cookie"] = cfg["cookie"]
        # Web 门户的 CORS 校验：带 Origin/Referer 与服务端实测形态一致
        h["Origin"] = "https://lobsterai.youdao.com"
        h["Referer"] = "https://lobsterai.youdao.com/portal"
        h["sec-ch-ua"] = '"Not(A:Brand";v="24", "Chromium";v="122"'
        h["sec-ch-ua-mobile"] = "?0"
        h['sec-ch-ua-platform'] = '"Windows"'
        h["Sec-Fetch-Site"] = "same-site"
        h["Sec-Fetch-Mode"] = "cors"
        h["Sec-Fetch-Dest"] = "empty"
    else:
        token = cfg.get("access_token", "")
        if not token:
            raise RuntimeError("配置缺少 access_token 或 cookie（二选一）")
        h["Authorization"] = "Bearer %s" % token
    h.setdefault("Content-Type", "application/json")
    return h


def _get(url, cfg):
    req = urllib.request.Request(url, headers=_headers(cfg), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw[:300]}
    except Exception as e:
        return 0, {"_error": "%s: %s" % (type(e).__name__, e)}


def _post(url, cfg, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers=_headers(cfg), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw[:300]}
    except Exception as e:
        return 0, {"_error": "%s: %s" % (type(e).__name__, e)}


def _envelope(body):
    """拆统一信封 {code, msg, data}；返回 (ok, data, message)。"""
    if not isinstance(body, dict) or body.get("_error"):
        return False, {}, body.get("_error", "响应异常") if isinstance(body, dict) else "响应异常"
    code = body.get("code")
    if code != 0:
        return False, {}, body.get("msg") or body.get("message") or ("code=%s" % code)
    data = body.get("data")
    if not isinstance(data, dict):
        return False, {}, "data 为空（accessToken 可能已失效）"
    return True, data, ""


def fetch_client_version():
    """版本号查询（★外层 code/msg，载荷在 data.value.version，非统一信封）。"""
    st, body = _get(VERSION_API, {"access_token": "x"})  # 该端点无需鉴权
    try:
        value = body["data"]["value"]
        ver = value.get("version") if isinstance(value, dict) else None
        if isinstance(ver, str) and ver.strip():
            return ver.strip()
    except Exception:
        pass
    return FALLBACK_VERSION


# ── 三步签到 ──
def fetch_slot(cfg, client_version):
    q = urllib.parse.urlencode({
        "placement": SLOT_PLACEMENT,
        "clientVersion": client_version,
        "containerApiVersion": SLOT_CONTAINER_API_VERSION,
        "platform": SLOT_PLATFORM,
    })
    st, body = _get("%s/api/client-activities/slot?%s" % (API_BASE, q), cfg)
    ok, data, msg = _envelope(body)
    if not ok:
        return None, msg
    activity = data.get("activity") if isinstance(data.get("activity"), dict) else {}
    return {
        "slotState": data.get("slotState") or "",
        "activityCode": activity.get("activityCode") or "",
        "configRevision": activity.get("configRevision") or 0,
    }, ""


def fetch_context(cfg, slot):
    url = "%s/api/client-activities/%s/context?configRevision=%s" % (
        API_BASE, urllib.parse.quote(slot["activityCode"]), slot["configRevision"])
    st, body = _get(url, cfg)
    ok, data, msg = _envelope(body)
    if not ok:
        return None, msg
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    actions = data.get("actions") if isinstance(data.get("actions"), list) else []
    return {"claimedToday": state.get("claimedToday") is True,
            "actions": [a for a in actions if isinstance(a, str)]}, ""


def claim(cfg, slot):
    url = "%s/api/client-activities/%s/actions/check_in" % (
        API_BASE, urllib.parse.quote(slot["activityCode"]))
    body = {"configRevision": slot["configRevision"],
            "idempotencyKey": str(uuid.uuid4()),
            "payload": {}}
    st, resp = _post(url, cfg, body)
    ok, data, msg = _envelope(resp)
    if not ok:
        return "failed", msg
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    credit = 0
    for key in ("creditsGranted", "rewardCredits", "credits"):
        v = result.get(key)
        if isinstance(v, (int, float)):
            credit = v
            break
    return "claimed", {"credit": credit, "message": result.get("message") or ""}


def run_checkin(cfg, verbose=False):
    """完整三步签到，返回 (kind, info)。"""
    version = fetch_client_version()
    if verbose:
        print("[step0] clientVersion = %s" % version)
    slot, err = fetch_slot(cfg, version)
    if slot is None:
        return "failed", "槽位查询失败：%s" % err
    if verbose:
        print("[step1] slot = %s" % json.dumps(slot, ensure_ascii=False))
    if slot["slotState"] != "available" or not slot["activityCode"]:
        return "inactive", "无可用活动（slotState=%s）" % slot["slotState"]
    ctx, err = fetch_context(cfg, slot)
    if ctx is None:
        return "failed", "上下文查询失败：%s" % err
    if verbose:
        print("[step2] context = %s" % json.dumps(ctx, ensure_ascii=False))
    if ctx["claimedToday"]:
        return "already", "今天已签到"
    if "check_in" not in ctx["actions"]:
        return "inactive", "当前不可签到（actions=%s）" % ctx["actions"]
    kind, info = claim(cfg, slot)
    if verbose:
        print("[step3] claim -> %s %s" % (kind, info))
    return kind, info


def fetch_balance(cfg):
    st, body = _get("%s/api/user/profile-summary" % API_BASE, cfg)
    ok, data, msg = _envelope(body)
    if not ok:
        return None
    items = data.get("creditItems") if isinstance(data.get("creditItems"), list) else []
    total = data.get("totalCreditsRemaining") or 0
    if not isinstance(total, (int, float)):
        total = 0
    packs = []
    for it in items:
        if not isinstance(it, dict):
            continue
        packs.append({
            "name": it.get("label") or it.get("type") or "积分包",
            "remaining": it.get("creditsRemaining") or 0,
            "expiresAt": it.get("expiresAt") or "",
        })
    return total, packs


# ── 命令 ──
def cmd_status(cfg):
    version = fetch_client_version()
    slot, err = fetch_slot(cfg, version)
    if slot is None:
        ncfg = keepalive_retry(cfg, err)
        if ncfg:
            slot, err = fetch_slot(ncfg, version)
            cfg = ncfg
        if slot is None:
            print("[status] 槽位查询失败：%s" % err)
            return 1
    print("[slot] state=%s activity=%s configRevision=%s" % (
        slot["slotState"], slot["activityCode"], slot["configRevision"]))
    if slot["slotState"] == "available" and slot["activityCode"]:
        ctx, err = fetch_context(cfg, slot)
        if ctx is None:
            print("[status] 上下文查询失败：%s" % err)
        else:
            print("[checkin] claimedToday=%s actions=%s" % (ctx["claimedToday"], ctx["actions"]))
    bal = fetch_balance(cfg)
    if bal:
        total, packs = bal
        print("[balance] 总剩余 %s" % total)
        for p in packs[:10]:
            exp = " 到期=%s" % p["expiresAt"] if p["expiresAt"] else ""
            print("   - %s: %s%s" % (p["name"], p["remaining"], exp))
    return 0


def cmd_auto(cfg):
    kind, info = run_checkin(cfg)
    if kind == "failed":
        ncfg = keepalive_retry(cfg, info if isinstance(info, str) else json.dumps(info, ensure_ascii=False))
        if ncfg:
            kind, info = run_checkin(ncfg)
    if kind == "claimed":
        print("[auto] 领取成功：+%s 积分" % info.get("credit"))
        return 0
    if kind == "already":
        print("[auto] 今日已签到，幂等跳过")
        return 0
    if kind == "inactive":
        print("[auto] 当前无可领活动：%s" % info)
        return 0
    print("[auto] 领取失败：%s" % info)
    return 1


def cmd_probe(cfg):
    kind, info = run_checkin(cfg, verbose=True)
    print("[probe] 结果 kind=%s info=%s" % (kind, json.dumps(info, ensure_ascii=False)))
    bal = fetch_balance(cfg)
    print("[probe balance] %s" % (json.dumps(bal, ensure_ascii=False)[:400] if bal else None))
    return 0


def cmd_init(argv=None):
    """写配置。支持：init --token <access_token>（桌面客户端模式）
    或 init --cookie '<整串cookie>'（Web 门户模式，reqable_hunt 非交互落地用）；
    不带参数则进入交互式粘贴。"""
    argv = argv or []
    token = cookie = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--token" and i + 1 < len(argv):
            token = argv[i + 1]; i += 2
        elif argv[i] == "--cookie" and i + 1 < len(argv):
            cookie = argv[i + 1]; i += 2
        else:
            i += 1
    if not token and not cookie:
        print("粘贴 LobsterAI 登录态：")
        print("  方式1（Web 门户，推荐）：Thorium 登录 lobsterai.youdao.com 后，抓包任意 "
              "lobsterai-server.youdao.com 请求的整串 Cookie")
        print("  方式2（桌面客户端）：Authorization 头（不含 'Bearer '）")
        line = input("> ").strip()
        if "=" in line:
            cookie = line
        else:
            token = line
    out = {}
    if cookie:
        out["cookie"] = cookie.strip()
    if token:
        out["access_token"] = token.replace("Bearer ", "").strip()
    if not out:
        print("[init] 输入为空，放弃")
        return 1
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    mode = "cookie(Web门户)" if cookie else "token(桌面端)"
    print("[init] 已写入 %s（模式=%s）" % (CFG_PATH, mode))
    return 0


def cmd_keepalive(cfg):
    """只读体检 + 按需续期（★只在距过期<1h 时才动 refresh_token，不会天天烧轮换凭证）。"""
    cred = (cfg or {}).get("_cred")
    if not cred:
        print("[保活] 当前走的是 cookie/手工 token 链路，没有可续期的桌面端凭证")
        return 0
    exp = cred.get("expires_at")
    left_h = (exp - time.time() * 1000) / 3600000.0 if exp else None
    print("[保活] 到期=%s%s | refresh_token=%s"
          % (_fmt_ts(exp), ("（剩 %.1f 小时）" % left_h) if left_h is not None else "（未知）",
             "有" if cred.get("refresh_token") else "无"))
    if left_h is None:
        print("[保活] 解不出过期时间（非 JWT 且无缓存），按不刷处理——真失效时会自动续期重试一次")
        return 0
    if not needs_refresh(cred):
        print("[保活] 距过期还早（阈值 1h），无需续期")
        return 0
    ok, res = refresh_desktop(cred, verbose=True)
    print("[保活] %s" % ("已续期，新凭证写入 lobsterai_live_cache.json" if ok else res))
    return 0 if ok else 1


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "init":
        return cmd_init(sys.argv[2:])
    pref = "auto"
    for a in sys.argv[2:]:
        if a.startswith("--auth="):
            pref = a.split("=", 1)[1]
    if pref not in ("auto", "bearer", "cookie"):
        print("[x] 未知 --auth: %s（auto/bearer/cookie）" % pref)
        return 1
    cfg = resolve_cfg(pref)
    if cfg is None:
        print("[x] 无可用凭证。三选一：")
        print("    ① 打开并登录一次 LobsterAI 桌面客户端（★免抓包，脚本会自动读 %s）"
              % os.path.join("%LobsterAI%", "lobsterai.sqlite"))
        print("    ② Thorium 登录 lobsterai.youdao.com 后：init --cookie '<整串 Cookie>'")
        print("    ③ 桌面端抓 Authorization 头：init --token <Bearer 值>")
        return 1
    if cmd == "status":
        return cmd_status(cfg)
    if cmd == "auto":
        return cmd_auto(cfg)
    if cmd == "probe":
        return cmd_probe(cfg)
    if cmd == "keepalive":
        return cmd_keepalive(cfg)
    print("[x] 未知命令: %s（status/auto/probe/keepalive/init）" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
