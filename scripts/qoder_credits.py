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

用法:
  python qoder_credits.py status        # 只读：活动清单 + 今日是否已领
  python qoder_credits.py auto          # 每日：发现 CREDITS 活动 → 领取（定时任务用这个）
  python qoder_credits.py probe         # 强制领取一次，打印服务端原文
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
DONE_STATUS = ("CLAIMED", "CONSUMED", "EXPIRED")
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
    c = load_credential(variant)
    if not c:
        if not VARIANTS[variant]["required"]:
            # 国际版是「装了才算」——没装不是失效，静默跳过，别污染日报。
            return 0
        print("[失败] 未找到凭证 —【Qoder失效】需安装并登录桌面端")
        return 2
    token = c["token"]
    u = c.get("user") or {}
    print("[%s][用户] %s | 凭证来源=%s | token 到期=%s"
          % (name, u.get("name") or u.get("email") or u.get("phone") or "-",
             c.get("_source"), (c.get("expiresAt") or "?")[:10]))

    st, j = get_campaigns(token, variant)
    if st != 200:
        print("[%s][失败] campaigns HTTP %s —【Qoder失效】凭证需重新登录" % (name, st))
        return 3
    if not j.get("campaigns"):
        print("[%s][提示] 服务端返回空活动列表（showCampaign=%s）— 通常是 cosy-clienttype 头缺失"
              % (name, j.get("showCampaign")))
        return 3

    item = pick_credits(j.get("campaigns"))
    print("[%s][活动] " % name + fmt_campaign(item))
    if not item:
        print("[%s][跳过] 当前无每日 Credits 活动（可能已结束或未到窗口）" % name)
        return 4

    # ★窗口切换边界兜底：总控 10:00 跑、窗口也 10:00 开，此时拿到的可能仍是刚过期的一期
    # （其 claimStatus 早已是 CLAIMED）。直接当「今日已领」跳过会漏领整天，故重取一次。
    status = item.get("claimStatus")
    for _ in (0, 1):
        if status in DONE_STATUS and not force:
            if _window_over(item):
                print("[%s][窗口切换] 当前这期 %s 刚过期（至 %s）— 等 %ds 重取新一期..."
                      % (name, item.get("campaignKey"), _ts(item.get("endAt")), WAIT_ROLL))
                time.sleep(WAIT_ROLL)
                st3, j3 = get_campaigns(token, variant)
                if st3 != 200:
                    print("[%s][失败] 重取 campaigns HTTP %s" % (name, st3))
                    return 3
                it2 = pick_credits(j3.get("campaigns"))
                if it2 and it2.get("campaignId") != item.get("campaignId"):
                    item = it2
                    print("[%s][新一期] " % name + fmt_campaign(item))
                    status = item.get("claimStatus")
                    continue
                if it2:
                    print("[%s][跳过] 重取后仍是同一期（claimStatus=%s）— 视为今日已领" % (name, status))
                    return 0
                print("[%s][跳过] 重取后无 CREDITS 活动 — 明日总控自动兜住" % name)
                return 4
            print("[%s][跳过] 今日已领取（claimStatus=%s，每日 10:00 刷新下一期）" % (name, status))
            return 0
        break

    st2, r = do_claim(token, item["campaignId"], variant)
    if st2 != 200:
        print("[%s][领取失败] HTTP %s %s" % (name, st2, str(r)[:200]))
        return 5
    b = r.get("benefit") or {}
    v = b.get("validity") or {}
    if r.get("replayed"):
        print("[%s][已领取] 重复提交，服务端幂等未重复发放（grantId=%s，本期 claimedAt=%s）"
              % (name, r.get("grantId"), (r.get("claimedAt") or "")[:19].replace("T", " ")))
    else:
        print("[%s][领取成功] +%s %s（%s天有效）→ 到期 %s"
              % (name, b.get("amount"), b.get("kind"), v.get("days"),
                 (r.get("expiresAt") or "")[:10]))
    print("[%s][本期] %s | grantId=%s | status=%s"
          % (name, r.get("campaignKey"), r.get("grantId"), r.get("status")))
    return 0


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
    else:
        print(__doc__)
        sys.exit(1)
