#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
minimax_credits.py — MiniMax Code 每日签到领积分
===============================================
产品: MiniMax Code 桌面端（agent.minimax.cn）
奖励: 七日签到 cycle（实测单日 800 积分档，bonus_points 为其中「额外」部分）

★ 协议来源（2026-10-16 分析 GitHub 开源项目 Ebony-Vinyl/dsh-our-free-model 的
  vendor/channel-pack/src/minimax-credits.ts，端点来自 asar UI chunk 直读+实测）:

  状态  GET  https://agent.minimax.cn/minimax-cloud/api/v1/signin/status?timezone_id=<IANA>
        → data.scene + data.days[7]（day_no/points/bonus_points/status/is_today）
  领取  POST https://agent.minimax.cn/minimax-cloud/api/v1/signin/claim?timezone_id=<IANA>
        body {} → data.claim_result（1=本次真领取，2=已领过）+ data.points
  余额  GET  https://agent.minimax.cn/minimax-cloud/api/v1/credit/details
        → ★平铺响应（details[]/total_count 与 base_resp 同级，无 data 键）
          details[].remaining_amount 实测是**字符串**（"800.00"）

★ 四个必须记住的点（实测结论）:
  1. timezone_id 是 query 参数且**必填**（客户端 IANA 时区名，国内填 Asia/Shanghai）；
     不带/非法都报 invalid timezone_id，且那也是 **HTTP 200**。
  2. 业务码在 **base_resp.status_code**（不是 code）——只看 HTTP 状态会误判成功。
  3. points 是**总数**，bonus_points 是其中「额外」部分，**不得相加**
     （实测第 1 天 points:800 / bonus_points:400，按钮就是「签到得 800」+「额外400」角标）。
  4. 「今日已领」判据是 **is_today && status==3**（CLAIMED），
     不能用「没有 Claimable」反推。

★ 幂等: claim_result==2（AlreadyClaimed）即今天已领；重复领取同样 HTTP 200。
  auto 流程：先查 status（is_today && status==3 → 跳过）→ claim。

★ 面板硬约束（解析失败即视为响应异常，不编造）:
  days 恰好 7 条；day_no 为 1..7 无重复；status ∈ {1,2,3,4}；
  最多 1 条 Claimable、最多 1 条 is_today；scene ∈ {0..4}。

★ 凭证保活（2026-10-17 改造，参考 Our Free Model `vendor/channel-pack/src/minimax-oauth.ts`）:
  access_token 寿命**只有约 1 小时**（实测 expiresAtMs - 签发 ≈ 3600s），且 MiniMax Code
  桌面端**自己会续期并轮换**它 —— 手工抓包写进 config 那份几天后必 401（2026-10-17 实报，
  当时 auth.json 里的新 token 一打就通，config 那份已被轮换掉）。所以现在按四级取凭证：
    1) 桌面端 `~/.minimax/auth/prod/cn/mcode-public/auth.json` 的 accessToken（未过期即用，
       客户端在跑就是免费保活）；
    2) 本地缓存 `minimax_session.json`（我们自己刷出来的那份，可能领先于客户端）；
    3) 都过期 → `POST https://account.minimax.cn/oauth2/token` 用
       grant_type=refresh_token 离线换新（refresh_token 前缀 mmort_，同样 60 字符）；
    4) 兜底 config 里手工抓的 access_token。
  ★**单次轮换**：同一 refresh_token 只试一次、绝不重试（防重放烧掉整条 token 家族），
    `invalid_grant/expired/revoked` 视为终态直接提示重登；换新结果**只写 minimax_session.json，
    不回写桌面端 auth.json**（客户端在跑会与我们争抢同一支 refresh）。
  令牌响应硬校验照抄客户端 `parseMinimaxTokenGrant`：token_type 必须 Bearer、
  scope 必须含 `agent.default`、expires_in 必须为正；★过期时间**只能取 expires_in**，
  accessToken 不是 JWT（`mmoat_` 前缀、0 个点），别去解 payload。

配置 minimax_config.json: {"access_token": "...", "timezone_id": "Asia/Shanghai"}
  access_token 仅作兜底；正常情况无需配置，桌面端登录着即可自动续期。
  （仍支持手工抓包：任意 agent.minimax.cn 请求的 Authorization 头去掉 "Bearer "。）

用法:
  python minimax_credits.py auth          # 只读：本次会用哪条凭证链路 + 有效期
  python minimax_credits.py auth --force  # 强制离线刷一次（验证 refresh_token 是否还活着）
  python minimax_credits.py status        # 只读：七日面板 + 今日是否已领 + 余额
  python minimax_credits.py auto          # 每日：未领则领取（定时任务用这个）
  python minimax_credits.py probe         # 强制领取一次，打印服务端原文
  python minimax_credits.py init          # 交互式写入配置
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE_DIR, "minimax_config.json")
SESSION_PATH = os.path.join(BASE_DIR, "minimax_session.json")
HOST = "https://agent.minimax.cn"
PREFIX = "/minimax-cloud/api/v1"
TIMEOUT = 30
DEFAULT_TZ = "Asia/Shanghai"

# OAuth 常量（账号主机/client_id/scope/audience 全部来自桌面端 auth.json 与 asar contracts.js）
ACCOUNT_HOST = "https://account.minimax.cn"
TOKEN_PATH = "/oauth2/token"
CLIENT_ID = "mcode-public"
SCOPE = "agent.default"
AUDIENCE = "agent-backend"
# 距过期不足这么多毫秒就不再用它，直接走刷新
EXPIRY_MARGIN_MS = 120_000
CLIENT_AUTH_PATHS = [
    os.path.join(os.path.expanduser("~"), ".minimax", "auth", "prod", "cn",
                 CLIENT_ID, "auth.json"),
]

# 单日状态（asar SigninDayStatus）
ST_UPCOMING, ST_CLAIMABLE, ST_CLAIMED, ST_DISABLED = 1, 2, 3, 4
STATUS_VALUES = (1, 2, 3, 4)
# 领取结果（asar SigninClaimResult）
CR_CLAIMED, CR_ALREADY = 1, 2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def load_cfg():
    cfg = {}
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    if not cfg.get("timezone_id"):
        cfg["timezone_id"] = DEFAULT_TZ
    return cfg


def _now_ms():
    return int(time.time() * 1000)


def _fmt_ms(ms):
    if not ms:
        return "未知"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ms / 1000))


def read_client_credential():
    """读桌面端自己的凭据（客户端在跑就会自动续期）。文件由客户端并发写，读坏就跳过。"""
    for path in CLIENT_AUTH_PATHS:
        try:
            with open(path, encoding="utf-8") as f:
                records = (json.load(f) or {}).get("records") or {}
        except Exception:
            continue
        recs = [r for r in records.values()
                if isinstance(r, dict) and isinstance(r.get("accessToken"), str)
                and r["accessToken"]]
        if not recs:
            continue
        rec = next((r for r in recs if r.get("clientId") == CLIENT_ID), recs[0])
        return {"access_token": rec["accessToken"],
                "refresh_token": rec.get("refreshToken") or "",
                "expires_at_ms": int(rec.get("expiresAtMs") or 0),
                "src": "桌面端 auth.json"}
    return None


def load_session():
    if not os.path.exists(SESSION_PATH):
        return None
    try:
        with open(SESSION_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    if isinstance(d, dict) and d.get("access_token"):
        d.setdefault("refresh_token", "")
        d.setdefault("expires_at_ms", 0)
        d["src"] = "本地缓存 session"
        return d
    return None


def save_session(cred):
    try:
        with open(SESSION_PATH, "w", encoding="utf-8") as f:
            json.dump({k: cred.get(k) for k in
                       ("access_token", "refresh_token", "expires_at_ms", "refreshed_at")},
                      f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _is_terminal_refresh_error(msg):
    return bool(re.search(r"invalid_grant|expired|revoked", msg, re.I))


def refresh_access_token(refresh_token):
    """grant_type=refresh_token 离线换新。★同一支只试一次，绝不重试。"""
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "scope": SCOPE,
        "audience": AUDIENCE,
    }).encode()
    req = urllib.request.Request(ACCOUNT_HOST + TOKEN_PATH, data=body, method="POST",
                                 headers={"Accept": "application/json",
                                          "Content-Type": "application/x-www-form-urlencoded",
                                          "User-Agent": "MiniMaxCode/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw).get("error") or raw[:80]
        except Exception:
            detail = raw[:80]
        raise RuntimeError("HTTP %s %s" % (e.code, detail))
    except Exception as e:
        raise RuntimeError("%s: %s" % (type(e).__name__, e))
    # 硬校验照抄客户端 parseMinimaxTokenGrant，不满足即视为无效凭据
    if str(payload.get("token_type", "")).lower() != "bearer":
        raise RuntimeError("令牌响应 token_type 非 Bearer")
    if SCOPE not in str(payload.get("scope", "")).split():
        raise RuntimeError("令牌响应 scope 不含 %s" % SCOPE)
    token = payload.get("access_token")
    expires_in = payload.get("expires_in")
    if not isinstance(token, str) or not token:
        raise RuntimeError("令牌响应缺少 access_token")
    if not isinstance(expires_in, (int, float)) or expires_in <= 0:
        raise RuntimeError("令牌响应缺少 expires_in（过期时间只能由它算，token 不是 JWT）")
    return {"access_token": token,
            "refresh_token": payload.get("refresh_token") or refresh_token,
            "expires_at_ms": _now_ms() + int(expires_in * 1000),
            "refreshed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "src": "离线刷新 refresh_token"}


def _request(url, token, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Authorization": "Bearer %s" % token,
         "Accept": "application/json",
         "User-Agent": "MiniMaxCode/1.0"}
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
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


class Session(object):
    """凭证解析 + 401 时自动续期重试一次。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.cred = None
        self.notes = []
        self._tried = set()
        self._retried_401 = False

    def resolve(self, force_refresh=False):
        if self.cred:
            return self.cred
        client = read_client_credential()
        cached = load_session()
        if not force_refresh:
            for c in (client, cached):
                if c and c["expires_at_ms"] - _now_ms() > EXPIRY_MARGIN_MS:
                    self.cred = c
                    return c
        # 缓存那份可能领先于客户端（客户端也在轮换），故优先
        candidates = []
        for src in (cached, client, self.cfg):
            rt = src.get("refresh_token") if src else None
            if rt and rt not in candidates:
                candidates.append(rt)
        for rt in candidates:
            if rt in self._tried:
                continue
            self._tried.add(rt)
            try:
                fresh = refresh_access_token(rt)
            except Exception as e:
                msg = str(e)
                self.notes.append("刷新失败(%s…): %s" % (rt[:6], msg))
                if _is_terminal_refresh_error(msg):
                    self.notes.append("refresh_token 已终态失效，同一支不再重试")
                    break
                continue
            save_session(fresh)
            self.cred = fresh
            return fresh
        if self.cfg.get("access_token") and not force_refresh:
            self.cred = {"access_token": self.cfg["access_token"],
                         "refresh_token": "", "expires_at_ms": 0, "src": "config 手工凭证"}
            return self.cred
        return None

    def describe(self):
        c = self.resolve()
        if c is None:
            return "[鉴权] 无可用凭证（桌面端 auth.json / session 缓存 / config 均不可用）"
        # config 手工兜底那份没有 expires_at（抓包只拿到 token 本身），别算剩余分钟
        if not c["expires_at_ms"]:
            life = "到期未知"
        else:
            life = "到期=%s（剩 %.0f 分）" % (
                _fmt_ms(c["expires_at_ms"]), (c["expires_at_ms"] - _now_ms()) / 60000.0)
        return "[鉴权] 来源=%s %s%s" % (
            c["src"], life, ("· " + "；".join(self.notes)) if self.notes else "")

    def request(self, url, method="GET", body=None):
        st, payload = self._once(url, method, body)
        if st in (401, 403) and not self._retried_401:
            self._retried_401 = True
            self.cred = None
            st, payload = self._once(url, method, body, force_refresh=True)
        return st, payload

    def _once(self, url, method, body, force_refresh=False):
        cred = self.resolve(force_refresh)
        if cred is None:
            return 0, {"_error": "未取到 MiniMax 凭证（桌面端未登录且无可用的 refresh_token）"}
        return _request(url, cred["access_token"], method, body)


def _unwrap(payload):
    """两个端点形状不同：signin/* 是信封（data 下），credit/details 平铺。
    有 data 对象就用它，否则用顶层。"""
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("data")
    if isinstance(nested, dict):
        return nested
    return payload


def _check_base_resp(payload):
    """业务码在 base_resp.status_code；非 0 返回错误信息，否则返回 None。"""
    if not isinstance(payload, dict):
        return "响应异常"
    base = payload.get("base_resp")
    if isinstance(base, dict):
        code = base.get("status_code")
        if isinstance(code, (int, float)) and code != 0:
            return base.get("status_msg") or ("业务错误 %s" % code)
    return None


def _auth_err(st, payload):
    """把登录态问题从「解析失败」里剥出来：401/403 或只有 error/message 的错误体，
    都是 token 掉了，不是响应形状变了。（2026-10-16 实测：过期 token 返 `{"error":"invalid access token"}`，
    被 parse_panel 的硬约束兜成「面板解析失败」，用户看不出该重抓凭证。）
    走到这里说明保活四级（桌面端 auth.json → 本地缓存 → 离线刷新 → config）已全部用尽。"""
    if isinstance(payload, dict) and st in (401, 403):
        msg = str(payload.get("error") or payload.get("message") or payload.get("_raw") or "")[:60]
        return "【MiniMax 登录态失效】HTTP %s %s —— 凭证保活四级均已用尽，" \
               "打开 MiniMax Code 重新登录一次即可（脚本随后直读 ~/.minimax/auth 的活凭证，" \
               "无需再手工抓 Authorization）" % (st, msg)
    if isinstance(payload, dict) and not payload.get("base_resp") and (
            payload.get("error") or payload.get("_raw")):
        return "接口报错：HTTP %s %s" % (st, str(payload.get("error") or payload.get("_raw"))[:80])
    return ""


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse_panel(data):
    """复刻 asar validateSigninPanel 的硬约束；不满足返回 None（不编造）。"""
    if not isinstance(data, dict):
        return None
    scene = _num(data.get("scene"))
    if scene is None or scene not in (0, 1, 2, 3, 4):
        return None
    days = data.get("days")
    if not isinstance(days, list) or len(days) != 7:
        return None
    seen = set()
    claimable = 0
    today = 0
    out = []
    for d in days:
        if not isinstance(d, dict):
            return None
        day_no = _num(d.get("day_no"))
        points = _num(d.get("points"))
        status = _num(d.get("status"))
        bonus_raw = d.get("bonus_points")
        bonus = 0 if bonus_raw is None else _num(bonus_raw)
        if day_no is None or int(day_no) != day_no or day_no < 1 or day_no > 7:
            return None
        if day_no in seen:
            return None
        if points is None or points < 0:
            return None
        if bonus is None or bonus < 0:
            return None
        if not isinstance(d.get("is_today"), bool):
            return None
        if status is None or status not in STATUS_VALUES:
            return None
        seen.add(day_no)
        if status == ST_CLAIMABLE:
            claimable += 1
        if d.get("is_today"):
            today += 1
        out.append({"day_no": int(day_no), "points": points, "bonus_points": bonus,
                    "status": int(status), "is_today": d.get("is_today")})
    if claimable > 1 or today > 1:
        return None
    return {"scene": int(scene), "days": out}


def panel_to_status(panel):
    """面板 → 签到状态语义。★dailyCredit = points（不相加 bonus_points）。"""
    today = next((d for d in panel["days"] if d["is_today"]), None)
    claimed_today = today is not None and today["status"] == ST_CLAIMED
    # 连续天数：从今日（或最近一个 Claimable 的前一天）向前数连续 CLAIMED
    days = sorted(panel["days"], key=lambda d: d["day_no"])
    idx = next((i for i, d in enumerate(days) if d["is_today"]), -1)
    streak = 0
    if idx >= 0:
        i = idx if days[idx]["status"] == ST_CLAIMED else (
            idx - 1 if days[idx]["status"] == ST_CLAIMABLE else -1)
        while i >= 0 and days[i]["status"] == ST_CLAIMED:
            streak += 1
            i -= 1
    claimable = next((d for d in panel["days"] if d["status"] == ST_CLAIMABLE), None)
    target = today or claimable
    return {
        "active": True,
        "today_checked_in": claimed_today,
        "streak_days": streak,
        "daily_credit": target["points"] if target else 0,
    }


# ── 业务 ──
def fetch_status(ses):
    url = "%s%s/signin/status?%s" % (HOST, PREFIX,
                                     urllib.parse.urlencode({"timezone_id": ses.cfg["timezone_id"]}))
    st, payload = ses.request(url)
    if st == 0:
        return None, payload.get("_error", "network error")
    bad = _auth_err(st, payload)
    if bad:
        return None, bad
    err = _check_base_resp(payload)
    if err:
        return None, err
    panel = parse_panel(_unwrap(payload))
    if panel is None:
        return None, "面板解析失败（响应形状不符硬约束）"
    return panel, ""


def claim(ses):
    url = "%s%s/signin/claim?%s" % (HOST, PREFIX,
                                    urllib.parse.urlencode({"timezone_id": ses.cfg["timezone_id"]}))
    st, payload = ses.request(url, "POST", {})
    if st == 0:
        return "failed", payload.get("_error", "network error")
    bad = _auth_err(st, payload)
    if bad:
        return "failed", bad
    err = _check_base_resp(payload)
    if err:
        return "failed", err
    data = _unwrap(payload)
    result = data.get("claim_result")
    if result == CR_ALREADY:
        return "already", "今日已签到"
    if result != CR_CLAIMED:
        return "failed", "签到响应缺少有效 claim_result（%s）" % result
    points = data.get("points")
    return "claimed", {"credit": points if isinstance(points, (int, float)) else 0}


def fetch_balance(ses):
    st, payload = ses.request("%s%s/credit/details" % (HOST, PREFIX))
    if st == 0:
        return None
    err = _check_base_resp(payload)
    if err:
        return None
    data = _unwrap(payload)
    details = data.get("details")
    if not isinstance(details, list) and _num(data.get("total_count")) is None:
        return None
    total = 0.0
    for entry in details if isinstance(details, list) else []:
        if not isinstance(entry, dict):
            continue
        v = entry.get("remaining_amount")
        if isinstance(v, str):
            try:
                v = float(v.strip())
            except Exception:
                continue
        if isinstance(v, (int, float)):
            total += v
    return round(total, 2)


# ── 命令 ──
def cmd_status(ses):
    print(ses.describe())
    panel, err = fetch_status(ses)
    if panel is None:
        print("[status] 查询失败：%s" % err)
        return 1
    st = panel_to_status(panel)
    print("[status] scene=%s today_checked_in=%s streak_days=%s daily_credit=%s" % (
        panel["scene"], st["today_checked_in"], st["streak_days"], st["daily_credit"]))
    for d in sorted(panel["days"], key=lambda x: x["day_no"]):
        tag = {1: "未开始", 2: "可领", 3: "已领", 4: "禁用"}.get(d["status"], "?")
        mark = " ←今天" if d["is_today"] else ""
        print("   Day%d: %s 分（额外 %s）[%s]%s" % (
            d["day_no"], d["points"], d["bonus_points"], tag, mark))
    bal = fetch_balance(ses)
    print("[balance] %s" % ("查询失败" if bal is None else "%s 积分" % bal))
    return 0


def cmd_auto(ses):
    print(ses.describe())
    panel, err = fetch_status(ses)
    if panel is None:
        print("[auto] 状态查询失败，跳过（不盲领）：%s" % err)
        return 1
    st = panel_to_status(panel)
    if st["today_checked_in"]:
        print("[auto] 今日已签到（is_today && status=3），幂等跳过")
        return 0
    kind, info = claim(ses)
    if kind == "claimed":
        print("[auto] 领取成功：+%s 积分" % info["credit"])
        return 0
    if kind == "already":
        print("[auto] 今日已签到，幂等跳过")
        return 0
    print("[auto] 领取失败：%s" % info)
    return 1


def cmd_probe(ses):
    print(ses.describe())
    panel, err = fetch_status(ses)
    print("[probe status] %s" % (json.dumps(panel, ensure_ascii=False) if panel else "FAIL: %s" % err))
    kind, info = claim(ses)
    print("[probe claim] kind=%s info=%s" % (kind, json.dumps(info, ensure_ascii=False)))
    return 0


def cmd_auth(argv):
    """凭证链路自检：走的是哪一级、refresh_token 还在不在、能否打通业务接口。★只报有无，不打印值。"""
    ses = Session(load_cfg())
    cred = ses.resolve(force_refresh="--force" in argv)
    print(ses.describe())
    client, cached = read_client_credential(), load_session()
    print("[凭据源] 桌面端 auth.json=%s（refresh_token %s）· 本地缓存=%s（refresh_token %s）"
          "· config 手工凭证=%s" % (
              "有" if client else "无",
              "有" if client and client.get("refresh_token") else "无",
              "有" if cached else "无",
              "有" if cached and cached.get("refresh_token") else "无",
              "有" if ses.cfg.get("access_token") else "无"))
    if cred is None:
        print("[x] 未取得任何凭证 → 打开 MiniMax Code 登录一次即可恢复")
        return 1
    panel, err = fetch_status(ses)
    if panel is None:
        print("[验证] 接口不通：%s" % err)
        return 1
    st = panel_to_status(panel)
    print("[验证] 接口通 · 今日已领=%s · 连续 %s 天 · 单日 %s 分" % (
        st["today_checked_in"], st["streak_days"], st["daily_credit"]))
    return 0


def cmd_init(argv=None):
    """写兜底配置。支持：init --token <access_token> [--refresh-token <rt>] [--tz Asia/Shanghai]；
    不带参数则进入交互式粘贴。★正常情况下无需手工抓包，桌面端登录着即可自动续期。"""
    argv = argv or []
    token = rt = tz = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--token" and i + 1 < len(argv):
            token = argv[i + 1]; i += 2
        elif argv[i] == "--refresh-token" and i + 1 < len(argv):
            rt = argv[i + 1]; i += 2
        elif argv[i] == "--tz" and i + 1 < len(argv):
            tz = argv[i + 1]; i += 2
        else:
            i += 1
    if not token and not rt:
        print("粘贴 MiniMax 登录态（任一 agent.minimax.cn 请求的 Authorization 值，不含 'Bearer '）：")
        token = input("> ").strip()
    token = token.replace("Bearer ", "").strip()
    if not token and not rt:
        print("[init] 输入为空，放弃")
        return 1
    cfg = {"timezone_id": tz or DEFAULT_TZ}
    if token:
        cfg["access_token"] = token
    if rt:
        cfg["refresh_token"] = rt
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("[init] 已写入 %s（%s）" % (CFG_PATH,
          "、".join([k for k in ("access_token", "refresh_token") if cfg.get(k)])))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "init":
        return cmd_init(sys.argv[2:])
    if cmd == "auth":
        return cmd_auth(sys.argv[2:])
    ses = Session(load_cfg())
    if cmd == "status":
        return cmd_status(ses)
    if cmd == "auto":
        return cmd_auto(ses)
    if cmd == "probe":
        return cmd_probe(ses)
    print("[x] 未知命令: %s（auth/status/auto/probe/init）" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
