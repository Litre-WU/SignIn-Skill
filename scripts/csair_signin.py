#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
csair_signin.py — 中国南方航空小程序「发现新境」每日签到
=========================================================
反编译对象: 微信小程序 中国南方航空 (APP_ID wx729238547ac7a14c, 版本 470)
来源: 小程序反编译产物 app-service 包 (v470)

链路(纯接口, 已逆向还原, 无加密签名 — 2026-10-09 真实抓包对齐):
  [会员]  POST https://wxapi.csair.com/mini/api/login/isLogin?appid=..&wxchannel=wxopen&envVersion=release
              header: sessionid / channel=ecsair / activitychannel=1 / unnecessaryparam(openId)
              body:   {"ssoKey": unionId, "clientType": "microsoft microsoft"}
              -> cardNo/mobile/certs 均为密文(直接回传即可, 无需解密), cnFullName 明文
  [查签]  GET  .../mini/foundZone/signInPageView?appid=..&wxchannel=wxopen&envVersion=release&memberNo=<cardNo>&signinChannel=foundTheZone
              header: memberNo-encrypt=<cardNo>
              -> signInFlag=true 表示今日已签 / signInNum 连续天数
  [签到]  POST .../mini/foundZone/signIn?appid=..&wxchannel=wxopen&envVersion=release&signinChannel=foundTheZone
              header: memberNo-encrypt=<cardNo>
              body: {certNo: certs[0].certNo, memberNo: cardNo, phone: mobile,
                     userName: cnFullName, email: email}   (全部复用 isLogin 响应密文)

=== 登录保持机制(2026-10-10 反编译还原, appservice.app.compiled.js v470) ===
  sessionId 唯一来源:
    wx.login() -> code  (仅小程序运行时可得)
    POST /mini/api/login/login  body={"code": <code>}
      -> {"sessionId":"wxopen_<uuid>", "openId":..., "unionId":...}   存 storage key "wxLoginInfo"
  该接口是微信 code2session 的服务端直通: 假 code 回 WX40029(=微信 errcode 40029),
  空 code 回 WX41008(=41008)。不存在任何服务端刷新/续期接口。
  客户端自动续期: 请求回 code=W00000("invalid session") 时, 请求包装器自动调
    N() -> wx.login() -> /mini/api/login/login -> 存新 sessionId -> 重发原请求。
  客户端启动时 wx.checkSession 判微信侧 session_key 是否有效:
    有效 -> 复用缓存 sessionId(可能已 stale, 首个请求触发 W00000 后自动刷新);
    失效 -> 直接 wx.login 换新。
  ★失效根因: sessionId 寿命 ≈ 微信 session_key 寿命(数小时~1天)。微信侧会主动
    刷新 session_key, CSAIR 服务端缓存的映射随即失效, 与我方调用频率无关。
    => 纯接口无法长期保活。长期保活的唯一办法: 定期打开小程序(触发自动续期)
       并抓 /mini/api/login/login 的响应, 用 refresh 子命令更新。
  ★抓包要点: 小程序刚打开时的头几个请求可能仍带着 stale sessionId(回 W00000),
    随后客户端透明刷新。要抓的是 /mini/api/login/login 的【响应体】(含全新
    sessionId), 或刷新成功之后的任意请求头里的 sessionid。

用法:
  python csair_signin.py init --session-id <wxopen_...> --union-id <ssoKey> [--open-id <unnecessaryparam>] [--client-type "microsoft microsoft"]
  python csair_signin.py refresh '<login响应JSON>'            # 直接吃 /mini/api/login/login 响应, 自动提取 sessionId/openId/unionId 并校验
  python csair_signin.py refresh --file resp.json
  python csair_signin.py doctor                                 # 凭证健康检查(sessionId / signToken 逐一探活)
  python csair_signin.py status
  python csair_signin.py signin                                 # 执行签到(幂等, 含抽奖机会自动检测)
  python csair_signin.py draw                                   # 手动抽一次(需新鲜 sessionId)

=== 抽奖(2026-10-11 逆向+抓包定案) ===
  天天签到(活动308)连续签满足档位 -> 生成 awardType=lotteryAward「抽奖机会」记录;
  getAward 领取后(received)抽奖资格激活, 实际消耗在小程序页 /page/jump?action=milesEarn&MEID=<lotteryId>:
    POST /wxopen/activity/api/mileagegift/draw?sp=<固定常量>&appid=..&wxchannel=wxopen&envVersion=release
    header: sessionid / channel=ecsair / activitychannel=1 / unnecessaryparam(openId) / memberNo-encrypt
    body: {randomId:lotteryId, memberNo:<isLogin cardNo密文>, signInGiftId:awardId,
           signInActivityId:活动id, rewardId:记录id, signInFlag:1}
  * sp="urk36vrgvr6he34h1lrslhixno11w35p" 为主包 ApiReq 里 isAliWaf 硬编码常量(app-service.compiled.js)。
  * u_atoken/u_asig/u_aref=wxCaptcha 是抓包当次阿里云滑块票据, 非必需。
  * 抽奖记录查询走 H5 marketing-tools awardList(无需 sessionId); 仅 draw 消耗需小程序 sessionId。
  * 错误码: W00000=sessionId失效(需重抓) W11000=校验失败(机会已消耗/无效) W403=缺sp参数。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import gzip
import ssl
import time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "csair_config.json")
LOG = os.path.join(BASE, "csair_signin.log")
STATE = os.path.join(BASE, "csair_state.json")

APP_ID = "wx729238547ac7a14c"
HOST = "https://wxapi.csair.com"
API = {
    "ISLOGIN": HOST + "/mini/api/login/isLogin",
    "PAGE_VIEW": HOST + "/mini/foundZone/signInPageView",
    "SIGN_IN": HOST + "/mini/foundZone/signIn",
}
CHANNEL = "foundTheZone"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) "
      "NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
      "UnifiedPCWindowsWechat(0xf2541f0d) XWEB/25715")

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def http(method, url, json_body=None, params=None, extra_headers=None, cookies=None, timeout=20):
    """JSON 请求; 返回 (status, parsed_json)"""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    body = None
    headers = {
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://servicewechat.com/%s/470/page-frame.html" % APP_ID,
        "Content-Type": "application/json",
    }
    if cookies:
        headers["Cookie"] = "; ".join("%s=%s" % (k, v) for k, v in cookies.items())
    if extra_headers:
        headers.update(extra_headers)
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            try:
                return resp.status, json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return e.code, raw.decode("utf-8", "replace")
    except Exception as e:
        return -1, {"message": "网络异常 %s" % e}


def api_url(path):
    """按真实抓包拼 URL: base + path + appid/wxchannel/envVersion query"""
    return "%s?appid=%s&wxchannel=wxopen&envVersion=release" % (path, APP_ID)


def build_headers(cfg, extra=None):
    """公共请求头(与 2026-10-09 真实抓包逐项对齐)"""
    h = {
        # URL query 里已带 appid/wxchannel/envVersion
        "sessionid": cfg.get("sessionId", ""),
        "channel": "ecsair",
        "activitychannel": "1",
        "unnecessaryparam": cfg.get("openId", ""),  # 抓包值: openId
    }
    if extra:
        h.update(extra)
    return h


def get_member_info(cfg):
    """LOGIN_LOGININFO: 用 ssoKey(unionId) 换会员信息
    返回 data 直接是 member 对象(真实抓包确认: cardNo/mobile/certs 为密文, cnFullName 明文)
    """
    status, j = http("POST", api_url(API["ISLOGIN"]),
                     json_body={"ssoKey": cfg.get("unionId", ""),
                                "clientType": cfg.get("clientType", "microsoft microsoft")},
                     extra_headers=build_headers(cfg))
    if status != 200 or not isinstance(j, dict):
        return None, "isLogin HTTP %s %s" % (status, str(j)[:160])
    if j.get("code") == "W00000" or j.get("message") == "invalid session":
        return None, ("sessionId 已失效(invalid session)。纯接口无法续期, 请打开小程序"
                      "抓 /mini/api/login/login 响应后执行 refresh")
    if j.get("message"):
        return None, "isLogin 业务失败: %s" % j.get("message")
    member = j
    if isinstance(j.get("data"), dict) and ("cardNo" in j["data"] or "memberNo" in j["data"]):
        member = j["data"]
    if not member.get("cardNo") and isinstance(j.get("member"), dict):
        member = j["member"]
    return member, None


H5_AUTH = os.path.join(BASE, "csair_h5_auth.json")


def load_h5_token():
    """从本地缓存读 H5 登录态(TOKEN cookie)。"""
    d = load_json(H5_AUTH, {}) or {}
    return (d.get("TOKEN") or "").strip()


def save_h5_token(token):
    d = load_json(H5_AUTH, {}) or {}
    d["TOKEN"] = token
    d["_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_json(H5_AUTH, d)


def h5_login_by_password(account, password, headless=False):
    """南航 H5 账号密码登录(Playwright 真实浏览器, 自动过阿里云 WAF 挑战)。

    流程: 导航登录接口触发 WAF 挑战 -> 浏览器自动执行挑战脚本通过 ->
    打开登录页填表单点登录 -> 导出 TOKEN/cs1246643sso cookie。
    返回 TOKEN 字符串; 失败抛异常。
    Thorium 不可用(本地 favicon 服务被 WAF 识别), 必须用 Playwright 自带 Chromium。
    """
    from playwright.sync_api import sync_playwright

    ua = ("Mozilla/5.0 (Linux; Android 10; SM-G977N Build/QP1A.190711.020; wv) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/122.0.6261.168 "
          "Safari/537.36 MMWEBID/9858 MicroMessenger/8.0.5.1900(0x28000537) WeChat/arm64 "
          "Weixin NetType/WIFI Language/zh_CN ABI/arm64")
    login_page = "https://m.csair.com/personal_new/login/"
    nav = ("https://m.csair.com/CSMBP/personalCenter/member/ffpUser/login"
           "?type=MOBILE&APPTYPE=touch&chanel=touch&lang=zh&holder=XCX&_=%d" % int(time.time() * 1000))

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        try:
            ctx = browser.new_context(user_agent=ua, viewport={"width": 390, "height": 844})
            page = ctx.new_page()
            # step1: 导航登录接口, 让浏览器自动完成 WAF JS 挑战
            try:
                page.goto(nav, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            passed = False
            for _ in range(15):
                time.sleep(1)
                try:
                    body = page.evaluate(
                        "document.body ? document.body.innerText.slice(0,60) : ''")
                except Exception:
                    body = ""
                if body and "_waf_" not in body:
                    passed = True
                    break
            if not passed:
                raise RuntimeError("WAF 挑战未通过(可能需要人工检查网络/浏览器环境)")
            # step2: 登录页填表单
            page.goto(login_page, wait_until="networkidle", timeout=45000)
            time.sleep(1)
            try:
                page.click('li:has-text("账号密码登录")', timeout=5000)
                time.sleep(0.5)
            except Exception:
                pass
            page.fill('input[placeholder="请输入国内手机/邮箱/会员号/证件号"]', account)
            page.fill('input[placeholder="请输入密码"]', password)
            page.evaluate("document.getElementById('yinsi').click()")
            time.sleep(0.3)
            page.click(".login_btn_div", timeout=5000, force=True)
            # step3: 等 TOKEN cookie
            for _ in range(15):
                time.sleep(1)
                for c in ctx.cookies():
                    if c["name"] == "TOKEN" and c["value"]:
                        return c["value"]
            raise RuntimeError("登录后未出现 TOKEN cookie(账号密码可能错误或需要验证码)")
        finally:
            browser.close()


def refresh_h5_token(cfg, headless=False):
    """用账号密码重登刷新 H5 token, 成功后落盘并返回 token。"""
    acct, pwd = cfg.get("h5_account", ""), cfg.get("h5_password", "")
    if not acct or not pwd:
        raise RuntimeError("配置缺 h5_account/h5_password, 无法自动重登")
    log("[H5] 账号密码重登中(过 WAF)…")
    token = h5_login_by_password(acct, pwd, headless=headless)
    save_h5_token(token)
    log("[H5] 重登成功, TOKEN 已更新")
    return token


def marketing_sign(token, on_invalid=None):
    """marketing-tools 签到(H5体系, 金币/里程奖励) — 链路得自 Sign 仓库 + 真实抓包对齐。

    [1] POST /marketing-tools/activity/join    -> 签到 (respCode 0000/S2001=已签/S00011=token失效)
    [2] POST /marketing-tools/award/awardList  -> 查待领奖励 (awardStatus=waitReceive)
    [3] POST /marketing-tools/award/getAward   -> 逐个领取 {signUserRewardId}
    [4] GET  /marketing-tools/sign/getSignCalendar -> 当月签到日历

    凭证: sign_user_token/TOKEN/cs1246643sso 三个 cookie 同值(isLogin 返回的 member.token)
    """
    base = "https://wxapi.csair.com"
    cookies = {"sign_user_token": token, "TOKEN": token, "cs1246643sso": token}
    hdrs = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781"
                       "(0x6700143B) NetType/WIFI MiniProgramEnv/Windows miniProgram/wx729238547ac7a14c"),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": base,
        "Referer": base + "/h5/sign/",
    }
    result = {"ok": False, "msg": "", "awards": []}

    # [1] 签到
    st, j = http("POST", base + "/marketing-tools/activity/join",
                 params={"type": "APPTYPE", "chanel": "ss", "lang": "zh"},
                 json_body={"activityType": "sign", "channel": "app", "entrance": None},
                 extra_headers=hdrs, cookies=cookies)
    info = j if isinstance(j, dict) else {}
    rc = info.get("respCode", "")
    if rc == "S00011":
        # token 失效: 若提供 on_invalid 回调, 刷新后重试一次
        if on_invalid:
            new_token = on_invalid()
            if new_token and new_token != token:
                log("[H5] token 失效, 已刷新, 重试签到…")
                return marketing_sign(new_token)
        result["msg"] = "token 无效, 需重新抓包或配置账号密码自动重登"
        return result
    if rc == "S2001":
        result["msg"] = "今天已签到"
        result["ok"] = True
    elif rc in ("0000", "0", "200"):
        result["msg"] = "签到成功"
        result["ok"] = True
    elif rc == "0150":
        # join 异步处理: 等 3s 后重查一次日历/领奖
        result["msg"] = "签到中(异步), 稍后重查…"
        result["ok"] = True
        time.sleep(3)
    else:
        result["msg"] = "活动返回: %s" % info.get("respMsg", str(j)[:80])
        return result

    # [2][3] 查待领奖励并逐个领取
    st, j = http("POST", base + "/marketing-tools/award/awardList",
                 params={"type": "APPTYPE", "chanel": "ss", "lang": "zh"},
                 json_body={"activityType": "sign", "awardStatus": "waitReceive",
                            "pageNum": 1, "pageSize": 100},
                 extra_headers=hdrs, cookies=cookies)
    # 动态拉取当前有效 sign 活动(含里程日期清单)
    adv = {}
    try:
        jact = http("POST", base + "/marketing-tools/activity/load",
                    json_body={"activityType": "sign"}, extra_headers=hdrs, cookies=cookies)
        act = (jact[1].get("data") or {}).get("activityDtoList") or []
        if act:
            sa = act[0]["signActivity"]
            adv["activity_id"] = sa.get("activityId")
            adv["activity_name"] = sa.get("activityName")
            adv["start_date"], adv["end_date"] = sa.get("startDate"), sa.get("endDate")
            try:
                pinpoint = json.loads(sa.get("pinpointAwardConfig") or "[]")
            except Exception:
                pinpoint = []
            adv["mileage_days"] = [(d.get("awardDate"), d.get("awardName", ""), d.get("mileage", 0)) for d in pinpoint]
            adv["reward_desc"] = (sa.get("ruleDesc") or "")[:160]
    except Exception:
        pass
    result["activity"] = adv

    if st == 200 and isinstance(j, dict) and j.get("data", {}).get("list"):
        for d in j["data"]["list"]:
            st2, j2 = http("POST", base + "/marketing-tools/award/getAward",
                           params={"type": "APPTYPE", "chanel": "ss", "lang": "zh"},
                           json_body={"activityType": "sign", "signUserRewardId": d["id"]},
                           extra_headers=hdrs, cookies=cookies)
            gift = d.get("awardName", "")
            if st2 == 200 and isinstance(j2, dict):
                rc = j2.get("respCode", "")
                data2 = j2.get("data", {})
                val = None
                if isinstance(data2, dict):
                    val = data2.get("result")
                if rc == "0000" or rc in ("0", "200"):
                    result["awards"].append("%s -> 领取成功(%s)" % (gift, val if val is not None else "done"))
                elif rc == "S0023":
                    result["awards"].append("%s -> 状态异常(S0023, 活动可能已结束, 跳过)" % gift)
                else:
                    result["awards"].append("%s -> %s" % (gift, j2.get("respMsg", str(j2)[:80])))
            else:
                result["awards"].append("%s -> 领取失败" % gift)
    return result


# ---------- 抽奖(mileagegift/draw) ----------
LOTTERY_SP = "urk36vrgvr6he34h1lrslhixno11w35p"  # 主包 ApiReq isAliWaf 硬编码常量


def _h5_ctx(token):
    """marketing-tools H5 请求上下文(cookie/头)。"""
    cookies = {"sign_user_token": token, "TOKEN": token, "cs1246643sso": token}
    hdrs = {
        "Accept": "application/json, text/plain, */*", "Content-Type": "application/json",
        "Origin": HOST, "Referer": HOST + "/h5/sign/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 "
                      "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
                      "miniProgram/wx729238547ac7a14c",
    }
    return cookies, hdrs


def find_lottery_chances(token):
    """查「已领取到账」的抽奖机会(lotteryAward, awardStatus=received)。
    抽奖机会由 getAward 领取激活, 实际消耗在小程序 draw 接口。
    返回 [{'rewardId','lottery_id','gift_id','activity_id','name'}]。"""
    cookies, hdrs = _h5_ctx(token)
    st, j = http("POST", HOST + "/marketing-tools/award/awardList",
                 params={"type": "APPTYPE", "chanel": "ss", "lang": "zh"},
                 json_body={"activityType": "sign", "pageNum": 1, "pageSize": 100},
                 extra_headers=hdrs, cookies=cookies)
    out = []
    if not isinstance(j, dict):
        return out
    for d in (((j.get("data") or {}).get("list")) or []):
        if d.get("awardType") != "lotteryAward" or d.get("awardStatus") != "received":
            continue
        desc = {}
        try:
            desc = json.loads(d.get("awardDesc") or "{}")
        except Exception:
            pass
        lid = desc.get("lotteryId") or ""
        if not lid:
            continue
        out.append({"rewardId": d.get("id"), "lottery_id": lid,
                    "gift_id": d.get("awardId"), "activity_id": str(d.get("activityId")),
                    "name": d.get("awardName", "抽奖机会")})
    return out


def do_draw(cfg, member, chance):
    """消耗一次抽奖机会 -> 小程序 mileagegift/draw。需有效 sessionId。
    返回 (ok:bool, code:str, text:str)。ok=True 表示已出结果(含 W11000=已消耗)。"""
    hdr = build_headers(cfg)
    body = {"randomId": chance["lottery_id"],
            "memberNo": member.get("cardNo", ""),
            "signInGiftId": chance["gift_id"],
            "signInActivityId": chance["activity_id"],
            "rewardId": chance["rewardId"],
            "signInFlag": 1}
    st, j = http("POST", HOST + "/wxopen/activity/api/mileagegift/draw",
                 params={"sp": LOTTERY_SP, "appid": APP_ID,
                         "wxchannel": "wxopen", "envVersion": "release"},
                 json_body=body, extra_headers=hdr)
    if isinstance(j, dict):
        code = str(j.get("code") or j.get("respCode") or "")
        if code in ("W0000", "0000", "0", "200"):
            data = j.get("data")
            prize = ""
            if isinstance(data, dict):
                prize = data.get("prizeName") or data.get("awardName") or json.dumps(
                    data, ensure_ascii=False)[:80]
            elif data:
                prize = str(data)[:80]
            return True, code, "中奖: %s" % (prize or "已抽(无奖品名)")
        if code == "W11000":
            return True, code, "校验失败(机会已消耗/无效)"
        if code == "W00000":
            return False, code, "sessionId 失效, 需重开小程序抓 login 后 refresh"
        if code == "W403":
            return False, code, "访问方式异常(缺 sp 或风控)"
        return False, code, str(j.get("message") or j)[:120]
    if isinstance(j, str) and "aliyun_waf" in j:
        return False, "WAF", "被阿里云滑块拦截(本次 IP/票据失效)"
    return False, "?", str(j)[:120]


def draw_all(token=None, quiet=False):
    """检测 + 消耗全部未抽的抽奖机会(幂等: 按 rewardId 记 state)。
    返回退出码。"""
    cfg = load_json(CONFIG, {}) or {}
    st_raw = load_json(STATE, {})
    state = st_raw if isinstance(st_raw, dict) else {}
    if token is None:
        token = load_h5_token() or cfg.get("signToken", "")
    if not token:
        if not quiet:
            print("[跳过] 抽奖需 H5 token(marketing-tools 查机会), 当前无 token")
        return 0
    chances = find_lottery_chances(token)
    todo = [c for c in chances if not state.get("draw|%s" % c["rewardId"])]
    if not chances:
        if not quiet:
            print("[抽奖] 当前无待消耗的抽奖机会(lotteryAward)。")
        return 0
    if not todo:
        if not quiet:
            print("[抽奖] 检测到 %d 个抽奖机会, 均已处理(见 state)。" % len(chances))
        return 0
    # 消耗需新鲜小程序 sessionId + isLogin cardNo
    member, err = get_member_info(cfg)
    if err:
        print("[抽奖] 有 %d 个抽奖机会待抽, 但小程序 sessionId 不可用: %s" % (len(todo), err[:80]))
        print("       抽奖无法全自动(sessionId 需重开小程序抓包), 请手动或 refresh 后 draw。")
        return 5
    print("[抽奖] 检测到 %d 个待消耗抽奖机会, 逐个抽取…" % len(todo))
    rc = 0
    for c in todo:
        ok, code, txt = do_draw(cfg, member, c)
        state["draw|%s" % c["rewardId"]] = "%s|%s" % (code, txt)
        save_json(STATE, state)
        print("   [%s] %s (%s)" % ("OK" if ok else "失败", txt, c["lottery_id"]))
        if not ok:
            rc = 6
    return rc


def signin_all():
    """全家桶: foundZone 签到(小程序) + marketing-tools 签到收奖(H5)。

    marketing-tools 优先用账号密码登录拿的 H5 token(可自动续期);
    没有账号密码时回退到小程序 isLogin 的 member.token(随 sessionId 一起失效)。
    """
    cfg = load_json(CONFIG, {}) or {}
    code = signin()
    # foundZone 失败不阻断 H5 签到(code>1 才是配置级错误)
    # 优先 H5 账号密码 token
    token = load_h5_token()
    if not token and (cfg.get("h5_account") and cfg.get("h5_password")):
        try:
            token = refresh_h5_token(cfg)
        except Exception as e:
            print("[跳过] H5 账号密码登录失败: %s" % e)
            token = ""
    if not token:
        # 回退: 小程序 isLogin 的 member.token
        token = cfg.get("signToken", "")
        if not token:
            member, err = get_member_info(cfg)
            if err or not member:
                print("[跳过] marketing-tools 需 member.token, 当前无法获取: %s" % err)
                return code
            token = member.get("token", "")
            if token:
                cfg["signToken"] = token
                save_json(CONFIG, cfg)
    if not token:
        print("[跳过] marketing-tools 无 token")
        return code
    print("\n--- marketing-tools 签到(H5, 金币/里程) ---")

    def on_invalid():
        """token 失效时: 有账号密码则自动重登, 否则返回 None。"""
        if cfg.get("h5_account") and cfg.get("h5_password"):
            try:
                return refresh_h5_token(cfg)
            except Exception as e:
                print("[失败] 自动重登失败: %s" % e)
        return None

    r = marketing_sign(token, on_invalid=on_invalid)
    print("[%s] %s" % ("OK" if r["ok"] else "失败", r["msg"]))
    for a in r["awards"]:
        print("   领取: %s" % a)
    act = r.get("activity") or {}
    if act.get("activity_name"):
        print_activity(act)
    # 签到后顺带检测抽奖机会(getAward 领取 lotteryAward 后即激活)
    draw_all(token=token)
    return code


def print_activity(act):
    """打印当前有效签到活动与里程日期"""
    print("\n--- 当前有效签到活动 ---")
    print("  活动: %s (ID=%s)  周期 %s ~ %s" % (
        act.get("activity_name"), act.get("activity_id"),
        act.get("start_date"), act.get("end_date")))
    mdays = act.get("mileage_days") or []
    if mdays:
        print("  里程指定日: %s" % "、".join(
            "%s(%s%s)" % (d[0], d[2] or "", "里程" if d[2] else d[1]) for d in mdays))
    if act.get("reward_desc"):
        print("  规则摘录: %s..." % act["reward_desc"])


def signin():
    cfg = load_json(CONFIG, {}) or {}
    if not cfg.get("sessionId") or not cfg.get("unionId"):
        print("[失败] 未配置凭证。抓包获取后执行:")
        print("  python csair_signin.py init --session-id <sessionid头> --union-id <ssoKey> [--open-id <unnecessaryparam>]")
        return 2

    today = datetime.now().strftime("%Y-%m-%d")
    st_raw = load_json(STATE, {})
    state = st_raw if isinstance(st_raw, dict) else {}
    if state.get(today):
        print("[幂等跳过] 今日(%s)已签到。删除 %s 可重跑。" % (today, os.path.basename(STATE)))
        return 0

    print("=" * 66)
    print("南航签到(发现新境) %s" % datetime.now().strftime("%F %T"))
    print("=" * 66)

    # 1) 会员信息
    member, err = get_member_info(cfg)
    if err:
        log("[失败] 会员信息获取失败: %s" % err)
        return 3
    card_no = member.get("cardNo", "")          # 密文
    mobile = member.get("mobile", "")           # 密文
    cname = member.get("cnFullName", "") or member.get("enFullName", "")
    email = member.get("email", "")
    certs = member.get("certs") or []
    cert_no = next((c["certNo"] for c in certs if c.get("certType") in ("NI", "ID")), "")
    log("会员: 卡号尾号=%s 姓名=%s" % (member.get("cardNo-sensitive", "?"), cname))
    hdr = build_headers(cfg, {
        "memberNo-encrypt": card_no,
        "phone-encrypt": mobile,
    })

    # 2) 查今日是否已签
    st, j = http("GET", api_url(API["PAGE_VIEW"]),
                 params={"memberNo": card_no, "signinChannel": CHANNEL},
                 extra_headers=hdr)
    signed = False
    if isinstance(j, dict):
        data_body = j.get("data") if isinstance(j.get("data"), dict) else j
        signed_flag = j.get("signInFlag") or data_body.get("signInFlag")
        signed = str(signed_flag) == "true"
        if signed:
            state[today] = "已签(查询确认)"
            save_json(STATE, state)
            log("[幂等] 今日已签到 (signInFlag=true)。")
            days = data_body.get("signInNum", "?")
            print("今日已签: 连续签到 %s 天" % days)
            return 0

    # 3) 签到 (body 复用 isLogin 返回的密文)
    body = {"certNo": cert_no, "memberNo": card_no, "phone": mobile,
            "userName": cname, "email": email}
    st, j = http("POST", api_url(API["SIGN_IN"]),
                 params={"signinChannel": CHANNEL},
                 json_body=body, extra_headers=hdr)
    # 成功响应格式(真实抓包验证): {"errorCode":"W0000","errorMsg":"success","data":"签到成功"}
    # 兼容多种成功码: code in (0/200) 或 errorCode=W0000
    ec = (j.get("errorCode") if isinstance(j, dict) else None)
    c0 = (j.get("code") if isinstance(j, dict) else None)
    ok = (isinstance(j, dict) and (ec == "W0000" or c0 in (200, 0, "200", "0", "0000")
                                   or (j.get("message") and st == 200)))
    if ok:
        state[today] = "success"
        state["%s|ts" % today] = datetime.now().strftime("%F %T")
        save_json(STATE, state)
        detail = (j.get("data") if isinstance(j, dict) else "") or ""
        log("[完成] 签到成功 %s" % detail)
        print("[完成] 南航签到成功 ✅ %s" % detail)
        return 0
    msg = str(j)[:200] if isinstance(j, dict) else j
    log("[未成功] 签到响应: %s" % msg)
    print("[未成功] 签到失败, 响应: %s" % msg)
    print("  排查: sessionId 是否过期 — 执行 `python csair_signin.py doctor` 诊断,")
    print("        或打开小程序抓 login 响应后 `python csair_signin.py refresh '<json>'`")
    return 4


def parse_login_response(raw):
    """从 /mini/api/login/login 的响应里提取 {sessionId, openId, unionId}。
    兼容: 裸对象 / {"data":{...}} / {"data":{"data":{...}}} / 抓包工具整条 JSON。
    返回 (dict, err)"""
    try:
        j = json.loads(raw)
    except Exception as e:
        # 试试从整段文本里抠除 JSON 片段(抓包工具常带其他文本)
        import re as _re
        m = _re.search(r'\{[\s\S]*\}', raw)
        if not m:
            return None, "无法解析 JSON: %s" % e
        try:
            j = json.loads(m.group(0))
        except Exception as e2:
            return None, "无法解析 JSON: %s" % e2
    # 逐层下钻
    cand = j
    for _ in range(4):
        if isinstance(cand, dict) and cand.get("sessionId"):
            break
        if isinstance(cand, dict) and isinstance(cand.get("data"), dict):
            cand = cand["data"]
        else:
            break
    if not (isinstance(cand, dict) and cand.get("sessionId")):
        return None, "响应里找不到 sessionId。收到: %s" % str(j)[:200]
    out = {"sessionId": cand["sessionId"]}
    if cand.get("openId"):
        out["openId"] = cand["openId"]
    if cand.get("unionId"):
        out["unionId"] = cand["unionId"]
    return out, None


def refresh_cmd(raw_or_file):
    """refresh: 吃 /mini/api/login/login 响应, 提取凭证, 立即调 isLogin 校验后落盘。"""
    raw = raw_or_file
    if os.path.isfile(raw_or_file):
        with open(raw_or_file, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    creds, err = parse_login_response(raw)
    if err:
        print("[失败] %s" % err)
        print("  期望内容形如: {\"sessionId\":\"wxopen_xxx\",\"openId\":\"oJ5...\",\"unionId\":\"oqy...\"}")
        return 2
    cfg = load_json(CONFIG, {}) or {}
    cfg.update(creds)
    cfg["_updated_at"] = datetime.now().strftime("%F %T")
    # 立即校验
    member, err = get_member_info(cfg)
    if err:
        print("[警告] 凭证已写入, 但校验失败: %s" % err)
        print("  可能抓到的是 stale sessionId(见 docstring「抓包要点」), 请重抓 login 响应。")
        save_json(CONFIG, cfg)
        return 3
    cfg["signToken"] = member.get("token", "") or cfg.get("signToken", "")
    save_json(CONFIG, cfg)
    print("[OK] 凭证已更新并校验通过")
    print("     sessionId: %s" % creds["sessionId"])
    print("     openId:    %s" % creds.get("openId", ""))
    print("     unionId:   %s" % creds.get("unionId", ""))
    print("     会员: %s" % (member.get("cnFullName") or member.get("cardNo-sensitive", "?")))
    print("     signToken: %s" % (cfg["signToken"][:24] + "..." if cfg.get("signToken") else "[无]"))
    return 0


def doctor():
    """凭证健康检查: 逐一探活 sessionId 与 signToken, 给出可执行结论。"""
    cfg = load_json(CONFIG, {}) or {}
    print("=" * 66)
    print("南航凭证健康检查 %s" % datetime.now().strftime("%F %T"))
    print("=" * 66)
    print("sessionId: %s" % (cfg.get("sessionId") or "[未配置]"))
    print("unionId:   %s" % (cfg.get("unionId") or "[未配置]"))
    print("signToken: %s" % ((cfg.get("signToken", "") or "")[:24] + "..." if cfg.get("signToken") else "[未配置]"))
    print()

    # 1) 小程序 session
    member, err = get_member_info(cfg)
    if err and "invalid session" in str(err):
        print("[X] 小程序 sessionId 已失效(W00000 invalid session)。")
        print("    刷新方法:")
        print("      1. 打开「中国南方航空」小程序任意页面(触发自动续期)")
        print("      2. 抓 /mini/api/login/login 的响应体")
        print("      3. python csair_signin.py refresh '<响应JSON>'")
        session_ok = False
    elif err:
        print("[X] isLogin 异常: %s" % err)
        session_ok = False
    else:
        print("[OK] 小程序 sessionId 有效")
        print("     会员: %s  卡号尾号: %s" % (
            member.get("cnFullName") or "?", member.get("cardNo-sensitive", "?")))
        session_ok = True

    # 2) H5 marketing-tools token
    tok = cfg.get("signToken", "")
    if not tok:
        print("\n[!] 未配置 signToken(随 sessionId 一起由 isLogin 返回, refresh 时自动提取)")
    else:
        base = "https://wxapi.csair.com"
        cookies = {"sign_user_token": tok, "TOKEN": tok, "cs1246643sso": tok}
        mh = {"Accept": "application/json, text/plain, */*", "Content-Type": "application/json",
              "Origin": base, "Referer": base + "/h5/sign/",
              "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 "
                            "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
                            "miniProgram/wx729238547ac7a14c"}
        st, j = http("POST", base + "/marketing-tools/activity/join",
                     params={"type": "APPTYPE", "chanel": "ss", "lang": "zh"},
                     json_body={"activityType": "sign", "channel": "app", "entrance": None},
                     extra_headers=mh, cookies=cookies)
        rc = j.get("respCode", "") if isinstance(j, dict) else ""
        if rc == "S00011":
            print("\n[X] H5 signToken 已失效(S00011 获取用户登录信息失败)")
            print("    该 token 与 sessionId 同源(均由 isLogin 返回), 需一起刷新。")
        elif rc == "S2001":
            print("\n[OK] H5 signToken 有效(今日已签到)")
        elif rc in ("0000", "0", "200"):
            print("\n[OK] H5 signToken 有效(今日未签, 可执行 signin)")
        else:
            print("\n[?] H5 signToken 状态未知: %s" % (str(j)[:120] if isinstance(j, dict) else j))

    print("\n结论:")
    if session_ok:
        print("  凭证可用, 执行 `python csair_signin.py signin` 完成签到。")
    else:
        print("  凭证已过期。纯接口无法续期(见脚本头「登录保持机制」),")
        print("  请打开小程序抓 login 响应后执行 refresh。")
    return 0 if session_ok else 1


def init_cfg(session_id, union_id, open_id=None, client_type=None):
    cfg = load_json(CONFIG, {}) or {}
    if session_id:
        cfg["sessionId"] = session_id
    if union_id:
        cfg["unionId"] = union_id
    if open_id:
        cfg["openId"] = open_id
    if client_type:
        cfg["clientType"] = client_type
    cfg["_updated_at"] = datetime.now().strftime("%F %T")
    save_json(CONFIG, cfg)
    print("[OK] 凭证已写入 %s" % CONFIG)
    print("     sessionId: %s" % cfg.get("sessionId", ""))
    print("     unionId:   %s" % cfg.get("unionId", ""))
    print("     openId:    %s" % cfg.get("openId", ""))
    print("     clientType:%s" % cfg.get("clientType", "microsoft microsoft"))


def status():
    cfg = load_json(CONFIG, {}) or {}
    print("配置文件: %s" % CONFIG)
    print("sessionId: %s" % (cfg.get("sessionId") or "[未配置]"))
    print("unionId:   %s" % (cfg.get("unionId") or "[未配置]"))
    print("openId:    %s" % (cfg.get("openId") or "[未配置]"))
    print("clientType:%s" % (cfg.get("clientType") or "microsoft microsoft(默认)"))
    print("更新时间:  %s" % cfg.get("_updated_at", "-"))
    print("领取记录:")
    st = load_json(STATE, {})
    st = st if isinstance(st, dict) else {}
    for k, v in sorted(st.items()):
        print("  %s -> %s" % (k, v))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "signin":
        sys.exit(signin_all())
    elif cmd == "draw":
        sys.exit(draw_all())
    elif cmd == "init":
        sid = union = openid = ctype = None
        args = sys.argv[2:]
        for i in range(0, len(args), 2):
            if args[i] == "--session-id" and i + 1 < len(args):
                sid = args[i + 1]
            elif args[i] == "--union-id" and i + 1 < len(args):
                union = args[i + 1]
            elif args[i] == "--open-id" and i + 1 < len(args):
                openid = args[i + 1]
            elif args[i] == "--client-type" and i + 1 < len(args):
                ctype = args[i + 1]
        init_cfg(sid, union, openid, ctype)
        sys.exit(0)
    elif cmd == "status":
        sys.exit(status())
    elif cmd == "doctor":
        sys.exit(doctor())
    elif cmd == "h5login":
        # 账号密码登录刷新 H5 token(过 WAF), 结果写入 csair_h5_auth.json
        cfg = load_json(CONFIG, {}) or {}
        acct, pwd = cfg.get("h5_account", ""), cfg.get("h5_password", "")
        if not acct or not pwd:
            print("[失败] 配置缺 h5_account/h5_password")
            sys.exit(2)
        headless = "--headless" in sys.argv
        try:
            t = h5_login_by_password(acct, pwd, headless=headless)
            save_h5_token(t)
            print("[OK] H5 登录成功, TOKEN: %s…" % t[:24])
            sys.exit(0)
        except Exception as e:
            print("[失败] %s" % e)
            sys.exit(3)
    elif cmd == "refresh":
        arg = sys.argv[2] if len(sys.argv) > 2 else ""
        if arg == "--file" and len(sys.argv) > 3:
            sys.exit(refresh_cmd(sys.argv[3]))
        if not arg:
            print("用法: python csair_signin.py refresh '<login响应JSON>'")
            print("      python csair_signin.py refresh --file resp.json")
            sys.exit(1)
        sys.exit(refresh_cmd(arg))
    else:
        print(__doc__)
        sys.exit(1)
