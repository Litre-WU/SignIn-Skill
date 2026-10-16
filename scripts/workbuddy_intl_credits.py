#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
workbuddy_intl_credits.py — WorkBuddy 国际版（www.workbuddy.ai）每日签到领积分
=============================================================================
产品: WorkBuddy 国际版（腾讯 WorkBuddy AI，platform=workbuddy-ai）
奖励: Buddy 加油站每日签到（国内版实测 100 积分/天，连续 7/14/28 天有额外档）

★ 协议来源（2026-10-16 逆向本机 WorkBuddyAI 5.8.3 的 resources/app.asar）:

  app.asar 内 CloudAccountRepo（国际版账号）与 DesktopAccountRepo（国内版账号）
  是两套实现，**差异只有两处**，其余端点与字段完全一致：

    |                  | billingPrefix | getCheckinRequestHeaders()      |
    |------------------|---------------|---------------------------------|
    | CloudAccountRepo | ""     （空） | 空实现 → **不带** X-Device-Token |
    | DesktopAccountRepo| "/v2"        | 注入 Turing Shield 设备指纹头    |

  因此国际版的**路径不带 /v2 前缀**：

    状态  POST https://www.workbuddy.ai/billing/meter/checkin-activity-status   body {}
    领取  POST https://www.workbuddy.ai/billing/meter/daily-checkin              body {}
    余额  POST https://www.workbuddy.ai/billing/meter/get-user-resource          body {}

  状态响应 data 字段（asar 内 checkinStatus() 逐字段映射，勿臆造）：
    active / today_checked_in / streak_days / daily_credit / today_credit /
    is_streak_day / next_streak_day / streak_bonus_days / streak_bonus_credit /
    checkin_dates[] / total_credits / start_time / end_time / theme_name /
    season / activity_name / claim_button_text / action_button

  领取响应：成功 → credit + streak_days + is_streak_day；
           重复 → **HTTP 400 + code 10001**（"今天已签到，请明天再来"）。

★★ 三个必须记住的点（2026-10-16 实测，与 GitHub 开源项目 dsh-our-free-model
   对 5.5.2 的判断不同，本机实测以 5.8.3 为准）:

  1. **判定只看响应体 code，不能看 HTTP 状态**：重复领取是 HTTP 400 但属「幂等成功」，
     真正的失败也可能是 HTTP 200。与国内版同一套语义。
  2. **国内版登录态在国际版域无效**：实测拿 www.workbuddy.cn 的 token 打
     www.workbuddy.ai，无论「带 token / 带垃圾 token / 不带 token」都返回
     **同一个 APISIX/3.12.0 网关 401（openresty HTML 页，不是业务 JSON）**，
     且响应带 `Set-Cookie: session=; Expires=Thu, 01 Jan 1970`（清 session）。
     → 这是**网关层拦截**，不是 token 过期；换国内 token 重试没用。
     同域 `https://www.workbuddy.ai/v3/config` 却是 200 code:0，
     说明站点可达、被挡的只是 /billing/meter/* 这一组。
  3. **国际版网关要的是 session cookie，不是 Bearer**：客户端内核里
     CloudAccountRepo 用 Bearer，但网关是 APISIX session 鉴权。
     因此本脚本同时支持两种凭据（cookie 优先，Bearer 兜底）。

  结论：国内版签到已由 wb_score.py / buddy_station.py 覆盖（走 www.workbuddy.cn）；
  本脚本只服务国际版账号。**没有国际版登录态时脚本报「未配置」并退出 0（跳过），
  不会误标【失效】。**

配置 workbuddy_intl_config.json:
  {
    "cookie": "...",          # 推荐：浏览器登录 www.workbuddy.ai 后的整串 Cookie
    "access_token": "...",    # 兜底：Bearer token（网关可能仍 401）
    "domain": "www.workbuddy.ai"
  }
  两者至少填一个；都填时 cookie 优先。

用法:
  python workbuddy_intl_credits.py status     # 只读：活动状态 + 今日是否已签
  python workbuddy_intl_credits.py auto       # 每日：未签则签（定时任务用这个）
  python workbuddy_intl_credits.py probe      # 打印服务端原文（排障用）
  python workbuddy_intl_credits.py init       # 写入配置

退出码: 0 成功/幂等跳过/未配置跳过   1 失败
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE_DIR, "workbuddy_intl_config.json")

DEFAULT_DOMAIN = "www.workbuddy.ai"
# ★国际版 billingPrefix 为空 —— 路径不带 /v2（与国内版 wb_score.py 的关键差异）
STATUS_PATH = "/billing/meter/checkin-activity-status"
CHECKIN_PATH = "/billing/meter/daily-checkin"
# ★余额是 -summary 不是 get-user-resource（后者是分页拉资源包列表，需要分页参数）：
#   asar CloudAccountRepo.billing() → POST /billing/meter/get-user-resource-summary body {}
#   → data.packages[]（cycleRemain / cycleTotal）
RESOURCE_PATH = "/billing/meter/get-user-resource-summary"
TIMEOUT = 30

# 重复领取业务码（国内版同语义：HTTP 400 + code 10001）
CODE_ALREADY = 10001

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
    if not cfg.get("domain"):
        cfg["domain"] = DEFAULT_DOMAIN
    return cfg


def _headers(cfg):
    """cookie 优先（网关 APISIX 认 session），Bearer 兜底。"""
    h = {"Accept": "application/json",
         "User-Agent": "WorkBuddyAI/5.8.3",
         "Origin": "https://" + cfg.get("domain", DEFAULT_DOMAIN),
         "Referer": "https://" + cfg.get("domain", DEFAULT_DOMAIN) + "/"}
    cookie = (cfg.get("cookie") or "").strip()
    token = (cfg.get("access_token") or "").strip()
    if cookie:
        h["Cookie"] = cookie
    if token:
        h["Authorization"] = "Bearer %s" % token
    return h


def _request(cfg, path, body=None):
    """POST body {}（与客户端一致）。返回 (http_code, payload, raw_text)。"""
    url = "https://" + cfg.get("domain", DEFAULT_DOMAIN) + path
    data = json.dumps(body if body is not None else {}).encode("utf-8")
    h = _headers(cfg)
    h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return e.code, None, raw
    except Exception as e:
        return 0, None, "%s: %s" % (type(e).__name__, e)
    try:
        return 200, json.loads(raw), raw
    except Exception:
        return 200, None, raw


def _diagnose(http_code, payload, raw):
    """把网关/形态异常翻成人话。返回 None 表示响应正常可解析。"""
    if http_code == 0:
        return "网络异常：%s" % (raw or "")[:120]
    if payload is None:
        low = (raw or "").lstrip().lower()
        if low.startswith("<html") or "authorization required" in low:
            return ("网关拦截 HTTP %s（返回 HTML 不是业务 JSON）——国际版 /billing/meter/* "
                    "走 APISIX session 鉴权，Bearer token 会被挡；"
                    "请改用浏览器登录态 Cookie" % http_code)
        return "响应非 JSON（HTTP %s）：%s" % (http_code, (raw or "")[:120])
    return None


def _biz(payload):
    """取业务码/消息；非 0 返回错误串，否则 None。"""
    if not isinstance(payload, dict):
        return "响应不是对象"
    code = payload.get("code")
    if isinstance(code, (int, float)) and int(code) != 0:
        return "%s（code %s）" % (payload.get("msg") or "业务错误", int(code))
    if not isinstance(payload.get("data"), dict):
        return "响应缺少 data"
    return None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse_status(data):
    """data → 归一化状态；字段缺失用 None 而不是编造。"""
    return {
        "active": data.get("active"),
        "today_checked_in": data.get("today_checked_in"),
        "streak_days": _num(data.get("streak_days")),
        "daily_credit": _num(data.get("daily_credit")),
        "today_credit": _num(data.get("today_credit")),
        "is_streak_day": data.get("is_streak_day"),
        "next_streak_day": _num(data.get("next_streak_day")),
        "streak_bonus_days": _num(data.get("streak_bonus_days")),
        "streak_bonus_credit": _num(data.get("streak_bonus_credit")),
        "total_credits": _num(data.get("total_credits")),
        "activity_name": data.get("activity_name") or "",
        "claim_button_text": data.get("claim_button_text") or "",
        "checkin_dates": data.get("checkin_dates") or [],
    }


def fetch_status(cfg):
    http_code, payload, raw = _request(cfg, STATUS_PATH)
    diag = _diagnose(http_code, payload, raw)
    if diag:
        return None, diag
    err = _biz(payload)
    if err:
        return None, err
    return parse_status(payload["data"]), ""


def do_checkin(cfg):
    """返回 (kind, info)，kind ∈ claimed / already / failed。"""
    http_code, payload, raw = _request(cfg, CHECKIN_PATH)
    diag = _diagnose(http_code, payload, raw)
    if diag:
        # ★重复领取是 HTTP 400 + code 10001，属幂等成功，不能当网关拦截。
        return "failed", diag
    if not isinstance(payload, dict):
        return "failed", "响应不是对象"
    code = payload.get("code")
    if isinstance(code, (int, float)) and int(code) == CODE_ALREADY:
        return "already", payload.get("msg") or "今天已签到，请明天再来"
    if isinstance(code, (int, float)) and int(code) != 0:
        return "failed", "%s（code %s）" % (payload.get("msg") or "签到失败", int(code))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return "claimed", {"credit": _num(data.get("credit")) or 0,
                       "streak_days": _num(data.get("streak_days")) or 0,
                       "is_streak_day": data.get("is_streak_day")}


def fetch_balance(cfg):
    """积分余额。失败返回 None（余额是锦上添花，不因此判签到失败）。

    响应形状宽容处理：优先 packages[].cycleRemain 求和，其次直接给的 total 类字段。
    """
    http_code, payload, raw = _request(cfg, RESOURCE_PATH)
    if _diagnose(http_code, payload, raw) or _biz(payload):
        return None
    data = payload["data"]
    # ★实测是 PascalCase 且数值为**字符串**：data.Packages[].CycleRemainCapacity
    #   （例：4282.8100019）。客户端 parseResourceSummary 再按到期时间分档，
    #   这里只求总额，够播报用。
    packages = data.get("Packages")
    if not isinstance(packages, list):
        packages = data.get("packages")
    if isinstance(packages, list):
        total = 0.0
        hit = False
        for p in packages:
            if not isinstance(p, dict):
                continue
            v = _num(p.get("CycleRemainCapacity"))
            if v is None:
                v = _num(p.get("cycleRemain"))
            if v is None and isinstance(p.get("CycleRemainCapacity"), str):
                try:
                    v = float(p["CycleRemainCapacity"].strip())
                except Exception:
                    v = None
            if v is not None:
                total += v
                hit = True
        if hit:
            return round(total, 2)
    for key in ("total_credits", "creditsTotal", "total", "left"):
        v = _num(data.get(key))
        if v is not None:
            return v
    return None


# ── 命令 ──
def cmd_status(cfg):
    st, err = fetch_status(cfg)
    if st is None:
        print("[status] 查询失败：%s" % err)
        return 1
    print("[status] active=%s today_checked_in=%s streak_days=%s daily_credit=%s today_credit=%s" % (
        st["active"], st["today_checked_in"], st["streak_days"],
        st["daily_credit"], st["today_credit"]))
    if st["activity_name"]:
        print("   活动   : %s（按钮：%s）" % (st["activity_name"], st["claim_button_text"] or "-"))
    if st["is_streak_day"]:
        print("   连续奖励: 第 %s 天节点，额外 %s 积分" % (
            st["next_streak_day"], st["streak_bonus_credit"]))
    if st["checkin_dates"]:
        print("   已签日期: %s" % ", ".join(str(d) for d in st["checkin_dates"]))
    # 余额只是锦上添花：查不到就静默，不刷「失败」噪音（签到判定不依赖它）。
    bal = fetch_balance(cfg)
    if bal is not None:
        print("[balance] %s 积分" % bal)
    return 0


def cmd_auto(cfg):
    st, err = fetch_status(cfg)
    if st is None:
        print("[auto] 状态查询失败，跳过（不盲领）：%s" % err)
        return 1
    if not st["active"]:
        print("[auto] 活动未开启（active=false），跳过")
        return 0
    if st["today_checked_in"]:
        print("[auto] 今日已签到，幂等跳过")
        return 0
    kind, info = do_checkin(cfg)
    if kind == "claimed":
        print("[auto] 领取成功：+%s 积分（连续 %s 天）" % (info["credit"], info["streak_days"]))
        return 0
    if kind == "already":
        print("[auto] %s，幂等跳过" % info)
        return 0
    print("[auto] 领取失败：%s" % info)
    return 1


def cmd_probe(cfg):
    http_code, payload, raw = _request(cfg, STATUS_PATH)
    print("[probe status] HTTP %s" % http_code)
    print("   %s" % (raw[:600] if raw else "(空响应)"))
    kind, info = do_checkin(cfg)
    print("[probe claim ] kind=%s info=%s" % (kind, json.dumps(info, ensure_ascii=False)))
    return 0


def cmd_init(argv=None):
    """init --cookie "<整串 Cookie>" [--token <bearer>] [--domain www.workbuddy.ai]
    不带参数则交互式粘贴。"""
    argv = argv or []
    cookie = token = domain = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--cookie" and i + 1 < len(argv):
            cookie = argv[i + 1]; i += 2
        elif argv[i] == "--token" and i + 1 < len(argv):
            token = argv[i + 1]; i += 2
        elif argv[i] == "--domain" and i + 1 < len(argv):
            domain = argv[i + 1]; i += 2
        else:
            i += 1
    if not cookie and not token:
        print("粘贴国际版登录态（浏览器登录 www.workbuddy.ai 后复制的整串 Cookie，推荐）：")
        cookie = input("Cookie> ").strip()
        if not cookie:
            print("或粘贴 Bearer token（直接回车跳过）：")
            token = input("Token> ").strip()
    if not cookie and not token:
        print("[init] 输入为空，放弃")
        return 1
    cfg = {"domain": domain or DEFAULT_DOMAIN}
    if cookie:
        cfg["cookie"] = cookie.strip()
    if token:
        cfg["access_token"] = token.replace("Bearer ", "").strip()
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("[init] 已写入 %s（%s）" % (CFG_PATH, "cookie" if cookie else "token"))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd = sys.argv[1]
    if cmd == "init":
        return cmd_init(sys.argv[2:])
    cfg = load_cfg()
    if not (cfg.get("cookie") or "").strip() and not (cfg.get("access_token") or "").strip():
        # ★未配置 ≠ 失效：国际版需要独立账号登录态，静默跳过避免每天误报。
        print("[skip] 未配置 WorkBuddy 国际版登录态（需 www.workbuddy.ai 账号）；"
              "国内版签到由 wb_score.py 负责，本步跳过")
        return 0
    if cmd == "status":
        return cmd_status(cfg)
    if cmd == "auto":
        return cmd_auto(cfg)
    if cmd == "probe":
        return cmd_probe(cfg)
    print("[x] 未知命令: %s（status/auto/probe/init）" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
