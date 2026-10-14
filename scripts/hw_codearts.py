#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
hw_codearts.py — 华为码道 CodeArts Doer 每日领积分
==================================================
域名: https://devcloud.cn-north-4.huaweicloud.com   (网关前缀 /chat)
接口族(2026-10-14 从前端 index.js + DefaultLayout 反查得到):
  GET  /chat/PromptCenterService/v1/ops/delivery?channel=WEB   活动/发放状态清单
  POST /chat/PromptCenterService/v1/ops/claim                  {campaignId, idempotentKey, channel}
  POST /chat/PromptCenterService/v1/ops/confirm                {campaignId}
  POST /chat/PromptCenterService/v1/ops/invite/generate        {campaignId, channel}
  POST /chat/PromptCenterService/v1/ops/invite/confirm-by-code?inviteCode=
  GET  /chat/PromptCenterService/v1/ops/tasks/conversation?channel=WEB
  POST /chat/PromptCenterService/v1/ops/events/conversation    {idempotentKey, channel, context}

★活动清单(delivery.items)实测:
  campaignId=1 每日签到领 1000 积分  type=USER_LOGIN   amount=1000 CREDIT
                                    triggerMode=MANUAL_CLAIM triggerEvent=user.login
  campaignId=2 学生认证领 4000 积分  type=STUDENT_CERTIFIED（需先认证，直领会报 40001 需触发接口激活）
  campaignId=3 推荐码上有礼 1000 积分 type=INVITE_USER
  campaignId=4 新用户注册送 4000 积分 type=NEW_USER_REGISTER (AUTO_GRANT)

★前端领取逻辑(DefaultLayout 反混淆，脚本严格照做):
  1) delivery 里挑 type ∈ {USER_LOGIN/user_login/DAILY_CLAIM/daily_claim/login}
     且 claimable !== false 且 status ∉ {CLAIMED, CONFIRMED, CONSUMED} 的项
  2) POST claim {campaignId, idempotentKey: "claim_<id>_<ms>", channel:"WEB"}
  3) 紧接着 POST confirm {campaignId}   ← CLAIMED → CONFIRMED，积分才真正入账可用
  4) confirm 返回账户桶: totalAmount / remainingAmount / expireAt(30 天有效)

鉴权: Cookie(华为云统一登录态) + 头 cftk(= cookie 里的 devclouddevuibjtcftk)
      + Agent-Type: PromptCenter + X-Language: zh-cn
      cftk 头缺失也能过网关，但页面 home.html 明示 app_cookie_prefix=cftk，带上最稳。
幂等/状态:
  claimable=false + status=CONFIRMED  → 今日已领（前端文案「今日已签到，明天再来吧」）
  强行 claim 会返 HTTP200 + code:40001「尚未到达权益刷新时间，暂时无法领取」
  不可直领的活动(学生认证等)返 code:40001「该活动类型需要先通过触发接口激活」
  风控: HTTP 500/429 由前端 3 次退避重试(1s/2s/4s)，本脚本照做。

配置 hw_codearts_config.json: {"cookie": "<完整 Cookie 头>", "cftk": "可选", "campaign_id": "1"}

用法:
  python hw_codearts.py init "<cookie 串>"
  python hw_codearts.py status     # 只看发放状态 + 积分桶
  python hw_codearts.py probe      # status + 试探性 claim（拿到服务端原文，用于定位刷新时间）
  python hw_codearts.py auto       # 每日: delivery → claim → confirm
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "hw_codearts_config.json")
HOST = "https://devcloud.cn-north-4.huaweicloud.com"
OPS = "/chat/PromptCenterService/v1/ops"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

# 视为「每日签到类」的 campaign type（前端 Ct() 判定条件原样搬过来）
DAILY_TYPES = ("USER_LOGIN", "user_login", "DAILY_CLAIM", "daily_claim", "login")
# 已领取/已到账/已消耗 —— 前端据此判定不可再领
DONE_STATUS = ("CLAIMED", "CONFIRMED", "CONSUMED")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── 配置 ──────────────────────────────────────────────────────────────────
def load_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_cfg(cfg):
    cfg["cookie_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def cftk_from_cookie(cookie):
    """cftk 头 = cookie 里的 devclouddevuibjtcftk（home.html: cftk_cookie_key_cf2）"""
    m = re.search(r"devclouddevuibjtcftk=([^;]+)", cookie or "")
    return m.group(1).strip() if m else ""


# ── HTTP ──────────────────────────────────────────────────────────────────
def hdrs(cookie, cftk):
    h = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "Agent-Type": "PromptCenter",          # 前端 Rc() 固定
        "X-Language": "zh-cn",
        "x-codearts-doer-scenario-type": "web",
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookie,
        "Referer": HOST + "/chat/home",
        "User-Agent": UA,
    }
    if cftk:
        h["cftk"] = cftk
    return h


def _once(method, path, cookie, cftk, body=None):
    url = HOST + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    h = hdrs(cookie, cftk)
    if body is not None:
        h["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=25, context=CTX)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def call(method, path, cookie, cftk, body=None):
    """照前端 W5t/SRt: HTTP 500/429 退避重试 1s/2s/4s，最多 3 次"""
    st, raw = _once(method, path, cookie, cftk, body)
    for delay in (1, 2, 4):
        if st not in (500, 429):
            break
        time.sleep(delay)
        st, raw = _once(method, path, cookie, cftk, body)
    try:
        j = json.loads(raw)
    except Exception:
        j = {"raw": raw[:300]}
    return st, j


def ok(j):
    """前端 Qu(): code===0||code===200||data!==null 视为成功"""
    if not isinstance(j, dict):
        return False
    return j.get("code") in (0, 200) or j.get("data") is not None


def errmsg(j):
    if isinstance(j, dict):
        return j.get("message") or j.get("error") or ("code=%s" % j.get("code"))
    return str(j)[:200]


# ── 业务 ──────────────────────────────────────────────────────────────────
def get_delivery(cookie, cftk):
    st, j = call("GET", OPS + "/delivery?channel=WEB", cookie, cftk)
    if st == 401 or (isinstance(j, dict) and j.get("code") in (401, 403)):
        return st, None
    if not ok(j):
        return st, None
    return st, (j.get("data") or {})


def pick_daily(items, campaign_id="1"):
    """优先按 campaign_id 精确命中；否则回退前端 Ct() 的 type 判定"""
    for it in items or []:
        if str(it.get("campaignId")) == str(campaign_id):
            return it
    for it in items or []:
        if (it.get("type") in DAILY_TYPES and it.get("claimable") is not False
                and not it.get("claimed") and it.get("status") not in DONE_STATUS):
            return it
    return None


def fmt_item(it):
    if not it:
        return "未找到每日签到活动"
    ex = it.get("extra") or {}
    return ("%s | %s %s | claimable=%s status=%s | %s ~ %s"
            % (it.get("title"), it.get("benefitAmount"), it.get("benefitUnit"),
               it.get("claimable"), it.get("status"),
               (ex.get("startTime") or "")[:10], (ex.get("endTime") or "")[:10]))


def do_claim(cookie, cftk, cid):
    key = "claim_%s_%d" % (cid, int(time.time() * 1000))
    return call("POST", OPS + "/claim", cookie, cftk,
                {"campaignId": str(cid), "idempotentKey": key, "channel": "WEB"})


def do_confirm(cookie, cftk, cid):
    return call("POST", OPS + "/confirm", cookie, cftk, {"campaignId": str(cid)})


def fmt_bucket(d):
    if not isinstance(d, dict):
        return "-"
    return ("总 %s / 剩 %s / 已用 %s | 过期 %s | %s"
            % (d.get("totalAmount"), d.get("remainingAmount"), d.get("consumedAmount"),
               (d.get("expireAt") or "")[:10], d.get("bucketLabel") or d.get("pointBucket") or ""))


# ── 命令 ──────────────────────────────────────────────────────────────────
def cmd_init():
    if len(sys.argv) < 3 or not sys.argv[2].strip():
        print("用法: python hw_codearts.py init \"<cookie 串>\"")
        print("抓取: 浏览器登录 devcloud.cn-north-4.huaweicloud.com/chat/home")
        print("      → F12 → Network 任意 PromptCenterService 请求 → 复制整行 cookie 头")
        return 2
    cookie = sys.argv[2].strip().strip('"')
    cftk = cftk_from_cookie(cookie)
    cfg = {"cookie": cookie, "cftk": cftk, "campaign_id": "1"}
    st, data = get_delivery(cookie, cftk)
    if data is None:
        print("[警告] delivery HTTP %s（登录态可能失效）— 仍写入配置" % st)
        if st in (401, 403):
            print("       →【华为码道失效】需重新抓取 cookie")
    else:
        print("[OK] cookie 有效，活动 %d 项" % len(data.get("items") or []))
        for it in (data.get("items") or []):
            print("   - " + fmt_item(it))
    save_cfg(cfg)
    print("[OK] 已写入 %s（cftk=%s）" % (CFG_PATH, cftk or "未提取到"))
    return 0


def _core(try_claim_even_if_not_claimable=False):
    cfg = load_cfg()
    if not cfg or not cfg.get("cookie"):
        print("[失败] 未配置 cookie —【华为码道失效】需 init(F12 抓 cookie)")
        return 2
    cookie = cfg["cookie"]
    cftk = cfg.get("cftk") or cftk_from_cookie(cookie)
    cid = str(cfg.get("campaign_id") or "1")

    st, data = get_delivery(cookie, cftk)
    if data is None:
        print("[失败] delivery HTTP %s —【华为码道失效】cookie 需重抓" % st)
        return 3

    items = data.get("items") or []
    it = pick_daily(items, cid)
    print("[活动] " + fmt_item(it))
    if not it:
        print("[失败] 未定位到每日签到活动（campaign_id=%s）" % cid)
        return 3

    claimable = it.get("claimable") is True
    status = it.get("status")
    if claimable and status not in DONE_STATUS:
        print("[领取] claimable=True → 提交 claim ...")
        st1, j1 = do_claim(cookie, cftk, it.get("campaignId") or cid)
        if not ok(j1):
            print("[领取失败] HTTP %s %s" % (st1, errmsg(j1)))
            return 4
        print("[领取] claim OK → %s" % json.dumps(j1.get("data"), ensure_ascii=False)[:200])
        time.sleep(0.6)
        st2, j2 = do_confirm(cookie, cftk, it.get("campaignId") or cid)
        if ok(j2):
            print("[到账] confirm OK → %s" % fmt_bucket(j2.get("data")))
        else:
            print("[到账警告] confirm HTTP %s %s" % (st2, errmsg(j2)))
        return 0

    # 不可领: 给出服务端原文（用于定位刷新时间）
    print("[跳过] claimable=%s status=%s（前端文案「今日已签到，明天再来吧」）" % (claimable, status))
    if try_claim_even_if_not_claimable:
        st1, j1 = do_claim(cookie, cftk, it.get("campaignId") or cid)
        print("[试探] claim HTTP %s → %s" % (st1, errmsg(j1)))
    # 无论能否领，都拉一次积分桶确认余额
    st2, j2 = do_confirm(cookie, cftk, it.get("campaignId") or cid)
    if ok(j2):
        print("[积分桶] %s" % fmt_bucket(j2.get("data")))
    else:
        print("[积分桶] HTTP %s %s" % (st2, errmsg(j2)))
    return 0 if status in DONE_STATUS else 4


def cmd_status():
    return _core(try_claim_even_if_not_claimable=False)


def cmd_probe():
    return _core(try_claim_even_if_not_claimable=True)


def cmd_auto():
    return _core(try_claim_even_if_not_claimable=False)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "init":
        sys.exit(cmd_init())
    elif cmd == "status":
        sys.exit(cmd_status())
    elif cmd == "probe":
        sys.exit(cmd_probe())
    elif cmd == "auto":
        sys.exit(cmd_auto())
    else:
        print(__doc__)
        sys.exit(1)
