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

★ 认证（2026-10-16 实测双模式均可）:
  模式A「Web 门户 cookie」（推荐，免桌面客户端）:
    浏览器登录 lobsterai.youdao.com 后，抓包任意 lobsterai-server.youdao.com
    请求的整串 Cookie 写入 config 的 "cookie" 字段。实测全链路可用
    （profile-summary / slot / context / check_in 均返回 code:0）。
    关键 cookie: lobsterai_web_session + NTES_YD_SESS + DICT_SESS + P_INFO 等
    （有道账号体系一套）。★Thorium 保持登录即可，可随时从浏览器 cookie 库重新提取。
  模式B「桌面客户端 Bearer」:
    抓桌面端请求的 Authorization: Bearer <access_token> 写入 "access_token"。
    ⚠ 桌面客户端默认「direct mode」强制直连（日志原话 System proxy disabled），
    Reqable 系统代理抓不到它的流量——要抓得先改客户端代理设置，故优先用模式A。

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


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "init":
        return cmd_init(sys.argv[2:])
    cfg = load_cfg()
    if not cfg.get("access_token") and not cfg.get("cookie"):
        print("[x] 未配置 lobsterai_config.json（需 access_token 或 cookie）。用法见文件头说明。")
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
