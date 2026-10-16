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

配置 minimax_config.json: {"access_token": "...", "timezone_id": "Asia/Shanghai"}
  access_token: 抓包任意 agent.minimax.cn 请求的 Authorization 头（去掉 "Bearer "），
                实测前缀 mmoat_、60 字符、非 JWT。

用法:
  python minimax_credits.py status        # 只读：七日面板 + 今日是否已领 + 余额
  python minimax_credits.py auto          # 每日：未领则领取（定时任务用这个）
  python minimax_credits.py probe         # 强制领取一次，打印服务端原文
  python minimax_credits.py init          # 交互式写入配置
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE_DIR, "minimax_config.json")
HOST = "https://agent.minimax.cn"
PREFIX = "/minimax-cloud/api/v1"
TIMEOUT = 30
DEFAULT_TZ = "Asia/Shanghai"

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


def _headers(cfg):
    token = cfg.get("access_token", "")
    if not token:
        raise RuntimeError("配置缺少 access_token")
    return {"Authorization": "Bearer %s" % token,
            "Accept": "application/json",
            "User-Agent": "MiniMaxCode/1.0"}


def _request(url, cfg, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = _headers(cfg)
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
def fetch_status(cfg):
    url = "%s%s/signin/status?%s" % (HOST, PREFIX,
                                     urllib.parse.urlencode({"timezone_id": cfg["timezone_id"]}))
    st, payload = _request(url, cfg)
    if st == 0:
        return None, payload.get("_error", "network error")
    err = _check_base_resp(payload)
    if err:
        return None, err
    panel = parse_panel(_unwrap(payload))
    if panel is None:
        return None, "面板解析失败（响应形状不符硬约束）"
    return panel, ""


def claim(cfg):
    url = "%s%s/signin/claim?%s" % (HOST, PREFIX,
                                    urllib.parse.urlencode({"timezone_id": cfg["timezone_id"]}))
    st, payload = _request(url, cfg, "POST", {})
    if st == 0:
        return "failed", payload.get("_error", "network error")
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


def fetch_balance(cfg):
    st, payload = _request("%s%s/credit/details" % (HOST, PREFIX), cfg)
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
def cmd_status(cfg):
    panel, err = fetch_status(cfg)
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
    bal = fetch_balance(cfg)
    print("[balance] %s" % ("查询失败" if bal is None else "%s 积分" % bal))
    return 0


def cmd_auto(cfg):
    panel, err = fetch_status(cfg)
    if panel is None:
        print("[auto] 状态查询失败，跳过（不盲领）：%s" % err)
        return 1
    st = panel_to_status(panel)
    if st["today_checked_in"]:
        print("[auto] 今日已签到（is_today && status=3），幂等跳过")
        return 0
    kind, info = claim(cfg)
    if kind == "claimed":
        print("[auto] 领取成功：+%s 积分" % info["credit"])
        return 0
    if kind == "already":
        print("[auto] 今日已签到，幂等跳过")
        return 0
    print("[auto] 领取失败：%s" % info)
    return 1


def cmd_probe(cfg):
    panel, err = fetch_status(cfg)
    print("[probe status] %s" % (json.dumps(panel, ensure_ascii=False) if panel else "FAIL: %s" % err))
    kind, info = claim(cfg)
    print("[probe claim] kind=%s info=%s" % (kind, json.dumps(info, ensure_ascii=False)))
    return 0


def cmd_init(argv=None):
    """写配置。支持：init --token <access_token> [--tz Asia/Shanghai]（reqable_hunt 非交互落地用）；
    不带参数则进入交互式粘贴。"""
    argv = argv or []
    token = tz = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--token" and i + 1 < len(argv):
            token = argv[i + 1]; i += 2
        elif argv[i] == "--tz" and i + 1 < len(argv):
            tz = argv[i + 1]; i += 2
        else:
            i += 1
    if not token:
        print("粘贴 MiniMax 登录态（任一 agent.minimax.cn 请求的 Authorization 值，不含 'Bearer '）：")
        token = input("> ").strip()
    token = token.replace("Bearer ", "").strip()
    if not token:
        print("[init] 输入为空，放弃")
        return 1
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump({"access_token": token, "timezone_id": tz or DEFAULT_TZ},
                  f, ensure_ascii=False, indent=2)
    print("[init] 已写入 %s（token=%s…）" % (CFG_PATH, token[:12]))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "init":
        return cmd_init(sys.argv[2:])
    cfg = load_cfg()
    if not cfg.get("access_token"):
        print("[x] 未配置 minimax_config.json（需 access_token）。用法见文件头说明。")
        return 1
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
