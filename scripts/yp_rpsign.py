# -*- coding: utf-8 -*-
# yp_rpsign.py —— 小米有品「每日签到（红包签到）」自动化
#
# 逆向来源（2026-10-14，用户真机抓包 + 签到页 JS）：
#   活动页：https://m.xiaomiyoupin.com/hd/checkInsignIn/index.html?channelId=<actId>&source=YPQD_YPMRQD
#   页面 JS：user-center-fe/production/youpin_activity/checkInsignIn/index.*.js
#   接口族（host=m.xiaomiyoupin.com，body 均 params:[{}, X]）：
#     POST /mtop/act/redPacketSign/getActInfo      [{},{actId}]  活动信息+签到状态
#     POST /mtop/act/redPacketSign/clickSign       [{},{actId}]  签到（★已签到会返 500 dubbo）
#     POST /mtop/act/redPacketSign/getFetchRecord  [{},{actId}]  领取记录
#     POST /mtop/act/redPacketSign/shareOrLike     [{},{id,op}]  分享/点赞
#     POST /mtop/coupon/redpacket/get_user_balance [{},{}]      红包余额
#   判读：
#     getActInfo.data.signUserInfo.sign = true   -> 今日已签到（跳过 clickSign）
#     getActInfo.data.actInfo.status            -> 活动状态（1=进行中）
#     clickSign.data.amount                     -> 本次签到到账金额（元）
#     get_user_balance.data.totalAmount         -> 红包余额（分）
#   注意：clickSign 对「已签到」重复提交返 code:500「failed to get dubbo response」
#         （非标准幂等文案），因此必须先 getActInfo 判状态再决定是否点击。
#
# 凭证：有品 App 登录态（m.xiaomiyoupin.mijiasn=YPQD_YPMRQD 渠道）
#   优先读同目录 yp_rpsign_config.json 的 cookie 字段，否则用内置抓包值。
#
# 用法：python yp_rpsign.py probe | auto
import urllib.request
import urllib.parse
import gzip
import json
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))

HOST = "https://m.xiaomiyoupin.com"
ACT_ID = "686b76a6ac546f0001b930c5"   # 每日签到（红包签到）actId

CFG_PATH = os.path.join(HERE, "yp_rpsign_config.json")

# 有品 App 抓包 Cookie（2026-10-13，App 域 m.xiaomiyoupin.com 实测有效）
DEFAULT_COOKIE = ""  # 必填: 有品 App 抓包的整行 Cookie（或放同目录 yp_rpsign_config.json）

UA_APP = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Mobile/15E148 MIOTStore/20191212 "
          "(YouPin;5.32.0;4A3003F56F85758E;;I;00000000-0000-0000-0000-000000000000;;"
          "4A3003F56F85758E;8F23B042-159F-4B3E-9CCE-EFA48909CE22)")

REFERER = ("https://m.xiaomiyoupin.com/hd/checkInsignIn/index.html?hideNavBar=true"
           "&channelId=" + ACT_ID + "&source=YPQD_YPMRQD")


def load_cookie():
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, encoding="utf-8") as f:
                c = json.load(f).get("cookie")
                if c:
                    return c
        except Exception:
            pass
    return DEFAULT_COOKIE


def post(path, payload, cookie=None):
    url = HOST + path
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    hdrs = {
        "Host": "m.xiaomiyoupin.com",
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": HOST,
        "User-Agent": UA_APP,
        "Referer": REFERER,
        "Content-Length": str(len(body)),
        "Connection": "keep-alive",
        "Accept-Encoding": "gzip, deflate, br",
        "Cookie": cookie or load_cookie(),
    }
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        r = op.open(req, timeout=25)
        raw = r.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return e.code, raw.decode("utf-8", "replace")


def _j(body):
    try:
        return json.loads(body)
    except Exception:
        return {}


def get_act_info(act_id=None):
    st, body = post("/mtop/act/redPacketSign/getActInfo",
                    [{}, {"actId": act_id or ACT_ID}])
    return st, _j(body)


def click_sign(act_id=None):
    st, body = post("/mtop/act/redPacketSign/clickSign",
                    [{}, {"actId": act_id or ACT_ID}])
    return st, _j(body)


def user_balance():
    st, body = post("/mtop/coupon/redpacket/get_user_balance", [{}, {}])
    return st, _j(body)


def fetch_record(act_id=None):
    st, body = post("/mtop/act/redPacketSign/getFetchRecord",
                    [{}, {"actId": act_id or ACT_ID}])
    return st, _j(body)


def probe():
    print("== 活动信息 ==")
    st, d = get_act_info()
    if d.get("code") != 0:
        print("!! getActInfo code=%s msg=%s" % (d.get("code"), d.get("message")))
        return None
    data = d.get("data") or {}
    act = data.get("actInfo") or {}
    su = data.get("signUserInfo") or {}
    aw = data.get("signAwards") or {}
    print("  名称=%s status=%s" % (act.get("name"), act.get("status")))
    print("  周期=%s ~ %s" % (
        time_str(act.get("startTime")), time_str(act.get("endTime"))))
    print("  今日签到=%s 连签天数=dayIndex:%s" % (su.get("sign"), su.get("dayIndex")))
    print("  奖池=%s 剩余=%s" % (aw.get("dayMoneyPool"), aw.get("stockMoneyPool")))
    st2, d2 = user_balance()
    if d2.get("code") == 0:
        amt = (d2.get("data") or {}).get("totalAmount")
        print("  红包余额=%s 分" % amt)
    return su.get("sign")


def time_str(ms):
    if not ms:
        return "?"
    import time
    return time.strftime("%Y-%m-%d", time.localtime(int(ms) / 1000))


def auto():
    signed = probe()
    print("== 签到 ==")
    if signed:
        print("  今日已签到，跳过（clickSign 重复提交会返 500）")
        return
    st, d = click_sign()
    if d.get("code") == 0:
        data = d.get("data") or {}
        print("  ★ 签到成功！到账 %s 元（%s）" % (data.get("amount"), data.get("msg")))
    else:
        print("  签到返回 code=%s msg=%s" % (d.get("code"), d.get("message")))
    # 签到后刷新余额
    st2, d2 = user_balance()
    if d2.get("code") == 0:
        print("  红包余额=%s 分" % (d2.get("data") or {}).get("totalAmount"))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "probe":
        probe()
    elif cmd == "auto":
        auto()
