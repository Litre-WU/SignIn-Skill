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
import hashlib
import hmac
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "hw_codearts_config.json")
HOST = "https://devcloud.cn-north-4.huaweicloud.com"
OPS = "/chat/PromptCenterService/v1/ops"
# ★CodeArts Agent 桌面端走的是另一套网关：snap-access + IAM 临时 AK/SK 签名，
#   完全不用浏览器 cookie（product.json.snapEngineUrl + workbench signer.js/huaweiRequestService）
SNAP_HOST = "snap-access.cn-north-4.myhuaweicloud.com"
SNAP_OPS = "/v1/ops"
SNAP_CHANNEL = "IDE"          # 客户端福利面板实测用的就是这个 channel
SNAP_SIGN_ALGO = "SDK-HMAC-SHA256"
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


# ── 桌面端凭证（★免抓包主链路）────────────────────────────────────────────
# CodeArts Agent 登录后把 IAM 临时凭证存进 VS Code 的 Secret Storage：
#   %APPDATA%\codearts-agent\User\globalStorage\state.vscdb
#   key   = secret://{"extensionId":"huaweicloud.authentication","key":"HuaweiCloudSession"}
#   value = 外层 JSON {"type":"Buffer","data":[...]}，内层是 Chromium v10 信封
#           （AES-256-GCM，主密钥在 <userData>\Local State 的 os_crypt.encrypted_key，DPAPI 解）
#   字段 = accessKey/secretKey/securitytoken/expires_at/refresh_token/loginContext(PKCE+DPoP EC key)
# 客户端访问权益接口时用 SDK-HMAC-SHA256 对请求签名（out-build/vs/platform/request/common/signer.js），
# 全程不带浏览器 cookie —— 所以这条链路不会像 devcloud cookie 那样几天就失效。
_CRED = {"tried": False, "cred": None, "why": ""}


def _state_paths():
    ud = os.environ.get("HW_CODEARTS_UD") or os.path.join(
        os.environ.get("APPDATA", ""), "codearts-agent")
    return (os.path.join(ud, "User", "globalStorage", "state.vscdb"), ud)


def client_credential():
    """返回 {accessKey, secretKey, securitytoken, expires_at} 或 None（并给原因）。"""
    if _CRED["tried"]:
        return _CRED["cred"]
    _CRED["tried"] = True
    db, ud = _state_paths()
    if not os.path.isfile(db):
        _CRED["why"] = "没找到 CodeArts Agent 的 state.vscdb（未安装/未登录/换机器：%s）" % db
        return None
    try:
        import browser_cookies as bc
        raw = bc.raw_read_shared(db)
        if not raw:
            _CRED["why"] = "state.vscdb 打不开（客户端独占锁）"
            return None
        import sqlite3
        tmp = os.path.join(os.environ.get("TEMP", "."), "_hw_state.db")
        with open(tmp, "wb") as f:
            f.write(raw)
        try:
            con = sqlite3.connect(tmp)
            try:
                row = con.execute(
                    "SELECT value FROM ItemTable WHERE key LIKE ?",
                    ('%HuaweiCloudSession%',)).fetchone()
            finally:
                con.close()
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if not row:
            _CRED["why"] = "state.vscdb 里没有 HuaweiCloudSession（客户端未登录）"
            return None
        v = row[0]
        if isinstance(v, str):
            v = v.encode("utf-8", "surrogateescape")
        env = json.loads(v)
        blob = bytes(env["data"]) if isinstance(env, dict) and "data" in env else v
        d = json.loads(bc.decrypt_v10(bc.master_key(ud), blob).decode("utf-8"))
        if not (d.get("accessKey") and d.get("secretKey")):
            _CRED["why"] = "session 里没有 AK/SK（登录类型不支持该链路）"
            return None
        exp = d.get("expires_at") or ""
        if exp:
            try:
                dt = datetime.strptime(exp[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                if dt <= datetime.now(timezone.utc):
                    _CRED["why"] = "客户端凭证已过期（expires_at=%s）→ 打开 CodeArts Agent 让它续期" % exp
                    return None
            except ValueError:
                pass
        _CRED["cred"] = d
        return d
    except Exception as e:
        _CRED["why"] = "读取桌面端凭证失败：%s: %s" % (type(e).__name__, str(e)[:120])
        return None


_UNRESERVED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")


def _uq(s):
    """signer.js 的 urlEncode：非 unreserved 字节按 %XX（大写）逐字节转义。"""
    out = []
    for ch in str(s):
        if ord(ch) < 128 and ch in _UNRESERVED:
            out.append(ch)
        else:
            out.append("".join("%%%02X" % b for b in ch.encode("utf-8")))
    return "".join(out)


def snap_headers(method, host, path, query, headers, body_bytes, ak, sk):
    """照抄客户端 signer.js 的规范化：
    ★X-Sdk-Date 必须先进入参与签名的 header 集合（漏了实测 401 APIG.0301
      "header x-sdk-date not signed"）；
    ★canonicalURI 按 '/' 分段转义后**末尾补一个 '/'**（/v1/ops/delivery → /v1/ops/delivery/）。"""
    t = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    h = {k.lower(): str(v).strip() for k, v in headers.items()}
    h["x-sdk-date"] = t
    signed = sorted(h)
    uri = "/".join(_uq(seg) for seg in path.split("/"))
    if not uri.endswith("/"):
        uri += "/"
    qs = "&".join("%s=%s" % (_uq(k), _uq(query[k])) for k in sorted(query))
    payload = h.get("x-sdk-content-sha256") or hashlib.sha256(body_bytes or b"").hexdigest()
    canon = "\n".join([method.upper(), uri, qs,
                       "".join("%s:%s\n" % (k, h[k]) for k in signed),
                       ";".join(signed), payload])
    msg = "%s\n%s\n%s" % (SNAP_SIGN_ALGO, t, hashlib.sha256(canon.encode("utf-8")).hexdigest())
    sig = hmac.new(sk.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    out = dict(headers)
    out["X-Sdk-Date"] = t
    out["Authorization"] = "%s Access=%s, SignedHeaders=%s, Signature=%s" % (
        SNAP_SIGN_ALGO, ak, ";".join(signed), sig)
    return out


def _snap_once(method, path, cred, body=None):
    p = urllib.parse.urlsplit("https://%s%s" % (SNAP_HOST, path))
    query = dict(urllib.parse.parse_qsl(p.query))
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    h = {"Host": SNAP_HOST,
         "Accept": "application/json",
         "User-Agent": UA,
         "Agent-Type": "PromptCenter",       # 客户端 welfare 请求固定带
         "X-Language": "zh-cn",
         "X-Security-Token": cred.get("securitytoken") or ""}
    if data is not None:
        h["Content-Type"] = "application/json"
    signed = snap_headers(method, SNAP_HOST, p.path, query, h, data or b"",
                          cred["accessKey"], cred["secretKey"])
    url = "https://%s%s" % (SNAP_HOST, p.path + (("?" + p.query) if p.query else ""))
    req = urllib.request.Request(url, data=data, headers=signed, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=25)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


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
    """★优先 snap-access + 桌面端 AK/SK 签名（免抓包、不随 cookie 过期）；
       只有读不到客户端凭证时才回退 devcloud 的 cookie/cftk 链路。
       两条链路响应形状一致（{code, data}）。照前端 W5t/SRt：HTTP 500/429 退避 1s/2s/4s。"""
    cred = client_credential()
    if cred:
        name = path.rsplit("/", 1)[-1].split("?")[0]
        b = dict(body) if isinstance(body, dict) else body
        # channel 只跟着「本来就带 channel 的请求」走：claim 带、confirm 不带
        # （实测给 confirm 硬塞 channel 会 HTTP 400，与客户端两处实现一致）
        if isinstance(b, dict) and "channel" in b:
            b["channel"] = SNAP_CHANNEL
        # ★GET 把 channel 放 query；POST 必须只放 body —— 实测 POST 再带 ?channel= 会被
        #   服务端判成 channel 校验失败（HTTP 400 HDN.1000 "channel : unknown exception"）。
        sp = ("%s/%s?channel=%s" % (SNAP_OPS, name, SNAP_CHANNEL)
              if method.upper() == "GET" else "%s/%s" % (SNAP_OPS, name))
        once = lambda: _snap_once(method, sp, cred, b)
    else:
        once = lambda: _once(method, path, cookie, cftk, body)
    st, raw = once()
    for delay in (1, 2, 4):
        if st not in (500, 429):
            break
        time.sleep(delay)
        st, raw = once()
    try:
        j = json.loads(raw)
    except Exception:
        j = {"raw": raw[:300], "_shape": _shape(raw)}
    if isinstance(j, dict):
        j["_auth"] = "snap-access/AK-SK" if cred else "devcloud/cookie"
    return st, j


def _shape(raw):
    """响应体形态描述（登录态排查用，别只说「HTTP 200」）。"""
    s = (raw or "").strip()
    if not s:
        return "空响应体（华为云 WAF/网关在登录态失效时就这么回）"
    low = s[:200].lower()
    if "<html" in low or "<!doctype" in low:
        return "HTML 页（多半被跳转到登录页）"
    return "非 JSON 响应 %dB" % len(s)


def fail_reason(st, j):
    """把 delivery 的失败形态翻成一句可执行结论（调用方再决定怎么标失效）。"""
    if st in (401, 403):
        return "HTTP %s 明确拒绝" % st
    if isinstance(j, dict) and j.get("code") in (401, 403):
        return "业务码 %s（未登录）" % j.get("code")
    shape = j.get("_shape") if isinstance(j, dict) else None
    if shape:
        return "HTTP %s 但%s" % (st, shape)
    return "HTTP %s %s" % (st, errmsg(j))


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
    if not ok(j):
        return st, None, fail_reason(st, j)
    return st, (j.get("data") or {}), ""


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
    st, data, why = get_delivery(cookie, cftk)
    if data is None:
        print("[警告] delivery 没拿到活动清单（%s）— 仍写入配置" % why)
    else:
        print("[OK] cookie 有效，活动 %d 项" % len(data.get("items") or []))
        for it in (data.get("items") or []):
            print("   - " + fmt_item(it))
    save_cfg(cfg)
    print("[OK] 已写入 %s（cftk=%s）" % (CFG_PATH, cftk or "未提取到"))
    return 0


def _core(try_claim_even_if_not_claimable=False):
    cfg = load_cfg() or {}
    cred = client_credential()
    if not cred and not cfg.get("cookie"):
        print("[失败] 读不到 CodeArts Agent 桌面端凭证（%s），且未配 cookie"
              " —【华为码道失效】装了该客户端并保持登录即可免抓包" % _CRED["why"])
        return 2
    cookie = cfg.get("cookie") or ""
    cftk = cfg.get("cftk") or cftk_from_cookie(cookie)
    cid = str(cfg.get("campaign_id") or "1")
    print("[鉴权] %s" % (("snap-access + 桌面端 AK/SK（免抓包）expires_at=%s"
                          % (cred.get("expires_at") or "?")) if cred
                         else "devcloud cookie/cftk（抓包）"))

    st, data, why = get_delivery(cookie, cftk)
    if data is None:
        # 走回退链路（cookie）时别急着让用户抓包：多数情况是 CodeArts Agent 没开着，
        # 桌面端临时凭证读不到才降级到 cookie，而 cookie 那份早就不新了。
        fix = ("IAM 临时凭证已拿到但接口空响应，可能是活动下线或签名口径变化"
               if cred else
               "先打开并登录 CodeArts Agent（免抓包链路会自己恢复；现在读不到桌面端凭证：%s）；"
               "确实没用该客户端时才需要重抓 devcloud cookie" % _CRED["why"])
        print("[失败] delivery %s —【华为码道失效】%s" % (why, fix))
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
    # ★delivery 通、活动清单在、只是服务端说不可领 —— 这是业务态不是失效。
    #   实测权益刷新周期并非自然日（10-14 显示 claimedAt=09-27），所以每天跑、
    #   claimable 为真才领；返回 4 会让总控天天误报「华为码道异常」。
    if status in DONE_STATUS:
        print("[跳过] 今日已领（claimable=%s status=%s，前端文案「今日已签到，明天再来吧」）"
              % (claimable, status))
    else:
        print("[今日不可领] claimable=%s status=%s（未到权益刷新时间，非失效）" % (claimable, status))
    if try_claim_even_if_not_claimable:
        st1, j1 = do_claim(cookie, cftk, it.get("campaignId") or cid)
        print("[试探] claim HTTP %s → %s" % (st1, errmsg(j1)))
    # 无论能否领，都拉一次积分桶确认余额
    st2, j2 = do_confirm(cookie, cftk, it.get("campaignId") or cid)
    if ok(j2):
        print("[积分桶] %s" % fmt_bucket(j2.get("data")))
    else:
        print("[积分桶] HTTP %s %s" % (st2, errmsg(j2)))
    return 0


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
