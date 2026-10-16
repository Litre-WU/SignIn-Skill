#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
zcode_credits.py — ZCode（智谱）Start Plan 每日额度：查询全自动 / 领取需验证码
============================================================================
产品: ZCode 桌面端，origin = https://zcode.z.ai（activityName「ZCode Start Plan 每日额度」）

★ 协议（2026-10-16 逆向 Our Free Model 桌面客户端 business.mjs 的
  src/zcode-upstream.ts + src/zcode-adapter.ts 段）:

  余额    GET  /api/v1/zcode-plan/billing/balance            Bearer zcode_jwt
          → data.balances[]{plan_id, show_name, unit_type, meter,
            total_units, used_units, remaining_units, available_units, expires_at}
  可领    GET  /api/v1/zcode-plan/billing/preview?app_version=<v>&platform=win32
          → data.plans[]{plan_id, name, priority, entitlements[0].grant_units/unit_type}
  领取    POST /api/v1/zcode-plan/billing/claim     body {"plan_id": "..."}
          → code 0=成功 / 1003=已领取（★是成功）/ 3007=captcha 无效 / 3012=异常活动
  激活    POST /api/v1/event/report  body {"event": "app_launch"|"app_daily_active",
                                          "device_mid":…, "platform":"win32", "app_version":…}
  配置    GET  /api/v1/client/configs?app_version=<v>&platform=unknown
          → data.configs.captcha.region（**服务端下发**，cn / sgp，不要写死）

★ 三个必须记住的点:
  1. **必须先补激活上报再查 preview**。服务端不会主动推送活动，不补
     `event/report` 就直接查 preview 会拿到空列表 → **稳定误报「今日已领」**。
     这与 Qoder 那次「按返回顺序取首个匹配 → 静默漏领」是同一类坑。
  2. **今日已领判据 = 可领 plan 数为 0**（不是「列表为空」，因为列表为空
     也可能只是没补激活）。
  3. **领取端点强制索要阿里云 captcha**：不带 / 带非法都回 `400/3007`，
     且校验**前置于** plan 校验；每个 plan 都要**重新 mint** 一个 param
     （复用会得 3007）。⇒ 本脚本 `status` 全自动，`claim` 需外部注入验证码。

  ⚠ 凭据：官方客户端 `~/.zcode/v2/credentials.json` 的自动解密读取
    **已于 2026-10-05 从上游删除**，现在只能走 OAuth → 必须抓包拿
    `zcode_jwt` + `device_mid`。

配置 zcode_config.json:
  {"zcode_jwt": "...", "device_mid": "...", "app_version": "3.14.3",
   "captcha_region": "cn",           # 可选，默认从 client/configs 拉取
   "captcha_param": ""}              # 可选，领取时注入（一次性）

用法:
  python zcode_credits.py status     # 补激活 → 查可领计划 + 余额（只读）
  python zcode_credits.py auto       # 有可领则领（需 captcha_param，否则提示）
  python zcode_credits.py probe      # 打印服务端原文
  python zcode_credits.py init       # 写入配置

退出码: 0 成功/幂等跳过/未配置跳过   1 失败
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE_DIR, "zcode_config.json")

ORIGIN = "https://zcode.z.ai"
PATH_BALANCE = "/api/v1/zcode-plan/billing/balance"
PATH_PREVIEW = "/api/v1/zcode-plan/billing/preview"
PATH_CLAIM = "/api/v1/zcode-plan/billing/claim"
PATH_EVENT = "/api/v1/event/report"
PATH_CONFIGS = "/api/v1/client/configs"

APP_VERSION_FALLBACK = "3.14.3"
PLATFORM = "win32"
TIMEOUT = 30
# 领取业务码：0=成功，1003=已领取（幂等成功），3007=captcha 无效，3012=异常活动
CODE_OK, CODE_ALREADY, CODE_CAPTCHA, CODE_UNUSUAL = 0, 1003, 3007, 3012

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
    if not cfg.get("app_version"):
        cfg["app_version"] = APP_VERSION_FALLBACK
    return cfg


def _headers(cfg, authorize=False, json_body=True, captcha=None):
    ver = cfg.get("app_version") or APP_VERSION_FALLBACK
    h = {"User-Agent": "ZCode/%s" % ver,
         "HTTP-Referer": ORIGIN,
         "X-ZCode-App-Version": ver,
         "X-Release-Channel": "stable",
         "X-Client-Language": "zh-CN",
         "X-Client-Timezone": "Asia/Shanghai",
         "X-Device-Mid": cfg.get("device_mid", ""),
         "X-Platform": PLATFORM,
         "X-Os-Category": "windows",
         "anthropic-version": "2023-06-01",
         "Accept": "application/json"}
    if json_body:
        h["Content-Type"] = "application/json"
    if authorize and cfg.get("zcode_jwt"):
        h["Authorization"] = "Bearer %s" % cfg["zcode_jwt"]
    if captcha:
        # ★param 与 region 必须来自**同一份**配置，阿里云成对校验，不一致即 3007
        if captcha.get("param"):
            h["x-aliyun-captcha-verify-param"] = captcha["param"]
        if captcha.get("region"):
            h["x-aliyun-captcha-verify-region"] = captcha["region"]
    return h


def _request(cfg, path, method="GET", body=None, authorize=False,
             json_body=True, captcha=None, query=None):
    url = ORIGIN + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=_headers(cfg, authorize, json_body, captcha))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, raw
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        return e.code, raw
    except Exception as e:
        return 0, "%s: %s" % (type(e).__name__, e)


def _json(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v.strip())
        except Exception:
            return None
    return None


# ── 业务 ─────────────────────────────────────────────────────────────────
def report_activation(cfg):
    """★查 preview 前必须补的两个激活事件，否则拿到空列表 → 误报「今日已领」。
    失败不影响主流程（静默）。"""
    ok = 0
    for ev in ("app_launch", "app_daily_active"):
        st, _ = _request(cfg, PATH_EVENT, "POST",
                         {"event": ev, "device_mid": cfg.get("device_mid", ""),
                          "platform": PLATFORM,
                          "app_version": cfg.get("app_version") or APP_VERSION_FALLBACK})
        if st == 200:
            ok += 1
    return ok


def fetch_plans(cfg):
    """可领计划列表（已按 priority 降序）。失败返回 None。"""
    q = {"app_version": cfg.get("app_version") or APP_VERSION_FALLBACK, "platform": PLATFORM}
    st, raw = _request(cfg, PATH_PREVIEW, "GET", query=q)
    if st != 200:
        return None, "preview HTTP %s" % st
    payload = _json(raw)
    if not isinstance(payload, dict):
        return None, "preview 响应非 JSON"
    raws = ((payload.get("data") or {}).get("plans") or [])
    if not isinstance(raws, list):
        return None, "preview 缺少 data.plans"
    out = []
    for item in raws:
        if not isinstance(item, dict):
            continue
        pid = item.get("plan_id")
        if not isinstance(pid, str) or not pid:
            continue
        ents = item.get("entitlements") if isinstance(item.get("entitlements"), list) else []
        first = ents[0] if ents and isinstance(ents[0], dict) else {}
        grant = _num(first.get("grant_units"))
        out.append({"plan_id": pid,
                    "priority": _num(item.get("priority")) or 0,
                    "name": item.get("name") if isinstance(item.get("name"), str) else "",
                    "grant_units": grant,
                    "unit_type": first.get("unit_type") if isinstance(first.get("unit_type"), str) else ""})
    out.sort(key=lambda p: -p["priority"])
    return out, ""


def fetch_balance(cfg):
    """返回 (remaining, unit) 或 (None, err)。"""
    st, raw = _request(cfg, PATH_BALANCE, "GET", authorize=True, json_body=False)
    if st != 200:
        return None, "balance HTTP %s" % st
    payload = _json(raw)
    if not isinstance(payload, dict):
        return None, "balance 响应非 JSON"
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return None, "balance 缺少 data"
    if data.get("displayMode") == "enterprise":
        return 0.0, "enterprise（企业版，无个人额度）"
    buckets = data.get("balances") if isinstance(data.get("balances"), list) else []
    remaining = 0.0
    unit = ""
    for b in buckets:
        if not isinstance(b, dict):
            continue
        v = _num(b.get("available_units"))
        if v is None:
            v = _num(b.get("remaining_units"))
        if v is not None:
            remaining += v
        if not unit and isinstance(b.get("unit_type"), str):
            unit = b["unit_type"]
    return remaining, unit or "units"


def fetch_captcha_region(cfg):
    """★region 由服务端下发（cn / sgp），不能写死——写死非 cn 区 100% 领不到。"""
    q = {"app_version": cfg.get("app_version") or APP_VERSION_FALLBACK, "platform": "unknown"}
    st, raw = _request(cfg, PATH_CONFIGS, "GET", authorize=True, json_body=False, query=q)
    if st != 200:
        return ""
    payload = _json(raw)
    if not isinstance(payload, dict):
        return ""
    cap = ((payload.get("data") or {}).get("configs") or {}).get("captcha") or {}
    r = cap.get("region")
    return r if isinstance(r, str) else ""


def claim_plan(cfg, plan_id, captcha):
    """返回 (kind, info)；kind ∈ claimed / already / need-captcha / failed。"""
    st, raw = _request(cfg, PATH_CLAIM, "POST", {"plan_id": plan_id},
                       authorize=True, captcha=captcha)
    payload = _json(raw)
    code = None
    msg = ""
    if isinstance(payload, dict):
        c = _num(payload.get("code"))
        code = int(c) if c is not None else None
        msg = payload.get("msg") or payload.get("message") or ""
    else:
        msg = (raw or "")[:160]
    if code is None and "unusual" in (raw or "").lower():
        code = CODE_UNUSUAL
    if code == CODE_CAPTCHA or (st == 400 and code in (None, CODE_CAPTCHA)):
        return "need-captcha", msg or "服务端要求验证码（3007）"
    if code == CODE_ALREADY:
        return "already", msg or "今日已领取"
    ok = (st == 200) and (code in (CODE_OK, None))
    if not ok:
        return "failed", "HTTP %s code=%s %s" % (st, code, msg)
    return "claimed", {"plan_id": plan_id, "code": code, "msg": msg}


# ── 命令 ─────────────────────────────────────────────────────────────────
def cmd_status(cfg):
    report_activation(cfg)
    plans, err = fetch_plans(cfg)
    if plans is None:
        print("[status] 可领计划查询失败：%s" % err)
        return 1
    if not plans:
        print("[status] 今日已领取（无可领额度，服务端按日刷新）")
    else:
        print("[status] 可领 %d 个额度：" % len(plans))
        for p in plans:
            print("   - %s | %s | +%s %s" % (p["plan_id"], p["name"] or "-",
                                             p["grant_units"], p["unit_type"]))
    rem, unit = fetch_balance(cfg)
    if rem is None:
        print("[balance] 查询失败：%s" % unit)
    else:
        print("[balance] 剩余 %s %s" % (rem, unit))
    return 0


def cmd_auto(cfg):
    report_activation(cfg)
    plans, err = fetch_plans(cfg)
    if plans is None:
        print("[auto] 可领计划查询失败，跳过（不盲领）：%s" % err)
        return 1
    if not plans:
        print("[auto] 今日已领取，幂等跳过")
        return 0
    param = (cfg.get("captcha_param") or "").strip()
    region = (cfg.get("captcha_region") or "").strip() or fetch_captcha_region(cfg)
    if not param:
        print("[auto] 有 %d 个额度可领，但**领取端点强制阿里云验证码**。" % len(plans))
        print("      请在 ZCode 客户端手动领取，或把验证码 param 写入配置后重跑：")
        print("      zcode_config.json → captcha_param / captcha_region（region 实测=%s）"
              % (region or "未知"))
        return 0
    # ★每个 plan 都要**新的** param —— 复用会得 3007
    total = 0
    for p in plans:
        kind, info = claim_plan(cfg, p["plan_id"], {"param": param, "region": region})
        if kind == "claimed":
            total += 1
            print("[auto] 领取成功：%s" % p["plan_id"])
        elif kind == "already":
            print("[auto] %s：%s" % (p["plan_id"], info))
        elif kind == "need-captcha":
            print("[auto] %s 需要验证码：%s" % (p["plan_id"], info))
            return 0
        else:
            print("[auto] %s 领取失败：%s" % (p["plan_id"], info))
    print("[auto] 本轮领取 %d 个额度" % total)
    return 0


def cmd_probe(cfg):
    print("[probe] 补激活上报...")
    print("   成功 %d/2" % report_activation(cfg))
    st, raw = _request(cfg, PATH_PREVIEW, "GET",
                       query={"app_version": cfg.get("app_version"), "platform": PLATFORM})
    print("[probe preview] HTTP %s" % st)
    print("   %s" % (raw[:600] if raw else "(空响应)"))
    st, raw = _request(cfg, PATH_BALANCE, "GET", authorize=True, json_body=False)
    print("[probe balance] HTTP %s" % st)
    print("   %s" % (raw[:600] if raw else "(空响应)"))
    return 0


def cmd_init(argv=None):
    argv = argv or []
    jwt = mid = ver = region = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--jwt" and i + 1 < len(argv):
            jwt = argv[i + 1]; i += 2
        elif argv[i] == "--mid" and i + 1 < len(argv):
            mid = argv[i + 1]; i += 2
        elif argv[i] == "--version" and i + 1 < len(argv):
            ver = argv[i + 1]; i += 2
        elif argv[i] == "--region" and i + 1 < len(argv):
            region = argv[i + 1]; i += 2
        else:
            i += 1
    if not jwt:
        print("粘贴 zcode_jwt（抓包 zcode.z.ai 请求的 Authorization，去掉 'Bearer '）：")
        jwt = input("JWT> ").strip()
    if not mid:
        print("粘贴 device_mid（请求头 X-Device-Mid）：")
        mid = input("MID> ").strip()
    if not jwt or not mid:
        print("[init] 输入不完整，放弃")
        return 1
    cfg = {"zcode_jwt": jwt.strip(), "device_mid": mid.strip(),
           "app_version": ver or APP_VERSION_FALLBACK}
    if region:
        cfg["captcha_region"] = region
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("[init] 已写入 %s" % CFG_PATH)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd = sys.argv[1]
    if cmd == "init":
        return cmd_init(sys.argv[2:])
    cfg = load_cfg()
    if not (cfg.get("zcode_jwt") or "").strip() or not (cfg.get("device_mid") or "").strip():
        print("[skip] 未配置 ZCode 凭据（需抓包 zcode.z.ai 的 zcode_jwt + device_mid）；"
              "本机未装 ZCode 客户端时本步跳过")
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
