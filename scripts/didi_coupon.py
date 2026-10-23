#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
didi_coupon.py — 滴滴出行自动领券 + 福利中心（打车平台线）
============================================================
逆向来源（2026-10-23，从开源实现静态还原，未实跑）：
  hudiemon/didi（master, BoxJs userscript, javascript-obfuscator 混淆）
  还原方法：Node 提取字符串数组 + 旋转 IIFE + RC4/base64 解码器 → 全量回代源码。
  ★本脚本为「从新编写」的 Python 实现，未搬运其混淆代码，仅复用接口契约。

覆盖能力（与 hudiemon/didi 1.3.0 对齐）：
  1) 领券 rebate：POST https://union.didi.cn/api/v1.0/reward/receive ×4 业务线
     🚖ut-dunion-wyc(打车) / ⛽ut-dunion-car(加油) / 🐷ut-dunion-kf(花小猪) / 🚚ut-dunion-freight(货运)
  2) 福利中心 flzx（base https://ut.xiaojukeji.com）：
     init     POST https://api.didi.cn/webx/chapter/product/init（prod_key=welfare-center）
     bubble   POST /ut/welfare/api/home/getBubble → clickBubble（气泡逐个点）
     signIn   POST /ut/welfare/api/action/dailySign（每日签到领福利金）
     guaguale POST /ut/welfare/api/home/divideData → joinDivide(明日) + divideReward(今日)

★鉴权：**H5 登录票据 token**（非 cookie）。获取方式：
    浏览器打开滴滴领券页 https://vv.didi.cn/a8ZdG0j?source_id=88446DIDI88446tkmmchild1001
    → 点「立即领取」登录 → F12 控制台执行：
      localStorage.getItem('didih5_trinity_login_ticket_role_121230').replace(/"/g, '')
    有效期约 7-30 天，过期需重新登录领券页获取。

★签名 wsgsig（ut.xiaojukeji.com 与 api.didi.cn 的 webx 接口必带，GET/POST 均是）：
    sig = md5('R4doMFFeMNlliIWMq' + JSON.stringify(payload))   # 十六进制
    kv  = 'ts={unix}&v=1&os=web&av=02&kv=0000010001&vl={payload的UTF8字节数}&sig={sig}'
    rand4 = 4 随机字节；xored = kv 逐字节 XOR rand4（rand4 循环复用）
    wsgsig = 'dd03-' + base64(rand4 + xored)（去掉尾部 = padding）
  ★union.didi.cn 的 reward/receive 不需要 wsgsig。

请求形态（POST，application/json）：
  ut 实例（福利中心）: body = {lat,lng,platform:'na',xenv:'h5', **data, token, env:<JSON字符串>}
                        params = {wsgsig}
                        headers Origin/Referer = https://page.udache.com
  union 实例（领券） : body = {xoid,dchn,dsi,xpsid,xenv:'h5',source_id,req_env,xspm_from,
                        xpsid_from,xbiz,xpsid_root,xpsid_share,source_from,dunion_callback,
                        product_type, **item, token, env:<对象>}
  webx init          : body = 活动 payload；params = {wsgsig}；wsgsig 签的是 body 本身

响应约定（errno==0 成功）：
  union:  {errno, errmsg, data:{rewards:[{coupon:{name, max_benefit_capacity:{value,unit}, usage_limit}}]}}
  ut:     {errno, errmsg, data:{...}}；dailySign→data.subsidy_state.subsidy_amount
          getBubble→data.bubble_list[{cycle_id,bubble_type,pre_content,reward_count}]
                    data.bonus_info.total_amount / exchange_total_amount
          divideData→data.divide_data.divide['YYYY-MM-DD'][.{reward.type,activity_id}|{task_id,activity_id}]

★失效判据（2026-10-23 无效 token 冒烟实测，三个接口均按契约响应）：
  ut 侧 errno=6001「登录信息失效，请重新登录」；union 侧 errno=1000010005「登录失败」。
  ★product/init **不校验 token**（无效 token 也返 errno 0 success，且响应 data 的键要增量
  合并进 defaultPayload）——init 只负责灌会话字段，验 token 必须用 getBubble。

固定业务参数（抄自客户端，勿改）：
  source_id='0hF8j5Cy9'  appIdMap[h5]='30004'  fromChannelMap[h5]='8'
  定位 cityId='1' lat='39.9592' lng='116.29871'（北京，客户端硬编码）

配置 didi_coupon_config.json：
  {"tokens": ["<token1>", "<token2>"], "lat": "...", "lng": "...", "city_id": "1", "updated": "..."}
  支持一次 init 传入多个 token（英文分号 ; 分隔）。

用法：
  python didi_coupon.py init "<token>"                 # 单个 token
  python didi_coupon.py init "<token1>;<token2>"       # 多账号
  python didi_coupon.py sync                           # ★从本机浏览器登录态自动取 token
                                                    # （Thorium 开 9222，领券页登录后跑这条即可）
  python didi_coupon.py status                          # 只读：福利金余额/气泡概览
  python didi_coupon.py rebate                          # 只做：4 业务线领券
  python didi_coupon.py welfare                         # 只做：福利中心(签到+气泡+瓜瓜乐)
  python didi_coupon.py auto                            # 每日全量（总控调用）
  python didi_coupon.py probe                           # 调试：打一次 getBubble 看原文
"""
import base64
import hashlib
import json
import os
import random
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "didi_coupon_config.json")

WELFARE_BASE = "https://ut.xiaojukeji.com"
UNION_BASE = "https://union.didi.cn"
WEBX_INIT = "https://api.didi.cn/webx/chapter/product/init"
PAGE_ORIGIN = "https://page.udache.com"
WSGSIG_SALT = "R4doMFFeMNlliIWMq"
SOURCE_ID = "0hF8j5Cy9"
APPID_H5 = "30004"
FROM_CHANNEL_H5 = "8"
ENV_H5 = "h5"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1")

# 4 条领券业务线（prod_key/dsi 抄自客户端，dsi 是服务端下发的活动标识）
REBATE_ITEMS = [
    {"icon": "🚖", "prod_key": "ut-dunion-wyc", "dsi": "db8bf1838942ee8ecc4cbbc972479e35662dxwza"},
    {"icon": "⛽", "prod_key": "ut-dunion-car", "dsi": "409987539335bae2bcc0d2faf40205d866270ngw"},
    {"icon": "🐷", "xbiz": "190101", "product_type": "kf", "prod_key": "ut-dunion-kf",
     "dsi": "a239aa37f893c43c379ccd844cd1c6ce6624nk5q"},
    {"icon": "🚚", "prod_key": "ut-dunion-freight", "dsi": "19302500f7d09edfc5d7386ed67b7166662e0d0r"},
]

# ★失效判据（2026-10-23 无效 token 冒烟实测）：
#   ut 福利中心侧 errno=6001「登录信息失效，请重新登录」；
#   union 领券侧 errno=1000010005「登录失败」。
#   注意 product/init（webx）**不需要 token**（无效 token 也返 errno 0 success），
#   所以 init 不能用来验 token 有效性——验 token 用 getBubble。
WELFARE_AUTH_ERR = 6001
UNION_AUTH_ERR = 1000010005
# 幂等成功态：今日已签过再签返 40009「重复签到」——当天第二次跑总控时会遇到，
#   算成功不算失败（2026-10-23 实跑二次验证）。
SIGN_DUP_ERR = 40009

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── 配置 ──────────────────────────────────────────────────────────────────
def load_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_cfg(cfg):
    cfg["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    tmp = CFG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CFG_PATH)


def tokens_of(cfg):
    """归一化 token 列表：支持 str（; 分隔）或 list。"""
    t = cfg.get("tokens") or cfg.get("token") or []
    if isinstance(t, str):
        t = [x.strip() for x in t.split(";")]
    out = []
    for x in t:
        if isinstance(x, str) and x.strip():
            out.append(x.strip().strip('"'))
    return out


# ── 工具 ──────────────────────────────────────────────────────────────────
def _jdumps(obj):
    """与 JS JSON.stringify 一致：无空格、非 ASCII 不转义。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def random_string(n):
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def rand_int(lo, hi):
    return random.randint(lo, hi)


def get_wsgsig(payload_str):
    """★ut/webx 接口签名。payload_str 必须是 _jdumps 后的请求体 JSON 字符串。
    ★字节级对齐 JS 原版：Buffer.from(String.fromCharCode(...rand4, ...xored)) 按 **UTF-8**
    编码（码元 ≥128 的会膨胀为 2 字节），服务端按 UTF-8 解回字符码再 XOR——必须照搬，
    不能图省事用 latin1 单字节，否则签名校验不过。"""
    sig = hashlib.md5((WSGSIG_SALT + payload_str).encode("utf-8")).hexdigest()
    kv = ("ts=%d&v=1&os=web&av=02&kv=0000010001&vl=%d&sig=%s"
          % (int(time.time()), len(payload_str.encode("utf-8")), sig))
    mask = os.urandom(4)
    raw = kv.encode("utf-8")
    xored = bytes(b ^ mask[i % 4] for i, b in enumerate(raw))
    s = "".join(chr(b) for b in (mask + xored))
    return "dd03-" + base64.b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")


# ── HTTP ──────────────────────────────────────────────────────────────────
def post_json(url, body, params=None, headers=None, timeout=25):
    """POST JSON。返回解析后的 dict；失败带 _fail/_http。query 串手动拼到 URL。"""
    full = url
    if params:
        full += "?" + urllib.parse.urlencode(params)
    data = _jdumps(body).encode("utf-8")
    hdrs = {"content-type": "application/json", "user-agent": UA,
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(full, data=data, headers=hdrs, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            body_txt = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            body_txt = ""
        return {"_http": e.code, "_body": body_txt}
    except Exception as e:
        return {"_fail": "%s: %s" % (type(e).__name__, str(e)[:150])}


def _err(j):
    """统一取 (errno, errmsg)。网络层失败返回 (None, 描述)。"""
    if not isinstance(j, dict):
        return None, "响应非对象"
    if j.get("_fail"):
        return None, "网络错误: %s" % j["_fail"]
    if j.get("_http"):
        return j["_http"], "HTTP %s %s" % (j["_http"], j.get("_body", "")[:120])
    return j.get("errno"), j.get("errmsg") or ""


# ── 福利中心（ut.xiaojukeji.com）──────────────────────────────────────────
class Welfare:
    """一个 token 一个实例。defaultPayload 会被 product/init 的响应增量更新。"""

    def __init__(self, token, cfg):
        self.token = token
        self.cfg = cfg
        self.lat = str(cfg.get("lat") or "39.9592")
        self.lng = str(cfg.get("lng") or "116.29871")
        self.city_id = str(cfg.get("city_id") or "1")
        self.dchn = random_string(7)
        self.xoid = str(uuid.uuid4())
        # defaultPayload 初始四键 + init 响应增量（与客户端一致）
        self.default_payload = {"lat": self.lat, "lng": self.lng,
                                "platform": "na", "xenv": ENV_H5}

    def _post(self, path, data=None):
        payload = dict(self.default_payload)
        if data:
            payload.update(data)
        payload["token"] = self.token
        env_str = _jdumps({"cityId": self.city_id, "longitude": self.lng, "latitude": self.lat,
                           "appid": APPID_H5, "token": self.token, "fromChannel": FROM_CHANNEL_H5})
        body = dict(payload)
        body["env"] = env_str
        wsgsig = get_wsgsig(_jdumps(payload))
        return post_json(WELFARE_BASE + path, body, params={"wsgsig": wsgsig},
                         headers={"origin": PAGE_ORIGIN, "referer": PAGE_ORIGIN + "/"})

    def init(self):
        """product/init（webx）。响应 data 的键增量合并入 defaultPayload。
        ★此接口不校验 token（无效 token 也 errno 0），它的作用是拿服务端下发的
        xpsid/xpsid_root 等会话字段并灌进 defaultPayload——别用它验 token。"""
        payload = {"xbiz": "", "prod_key": "welfare-center", "xpsid": "", "dchn": self.dchn,
                   "xoid": self.xoid, "xenv": "h5", "xspm_from": "", "xpsid_root": "",
                   "xpsid_from": "", "xpsid_share": "", "need_page_config": False,
                   "need_share_config": False}
        j = post_json(WEBX_INIT, payload, params={"wsgsig": get_wsgsig(_jdumps(payload))})
        if not isinstance(j, dict) or j.get("_fail") or j.get("_http"):
            return None, _err(j)[1]
        errno, errmsg = j.get("errno"), j.get("errmsg") or ""
        data = j.get("data") or {}
        if errno != 0:
            return errno, errmsg
        if isinstance(data, dict):
            for k, v in data.items():
                self.default_payload[k] = v
        return 0, "ok"

    def get_bubble(self):
        return self._post("/ut/welfare/api/home/getBubble")

    def click_bubble(self, cycle_id, bubble_type):
        return self._post("/ut/welfare/api/action/clickBubble",
                          {"cycle_id": cycle_id, "bubble_type": bubble_type})

    def daily_sign(self):
        return self._post("/ut/welfare/api/action/dailySign")

    def divide_data(self):
        return self._post("/ut/welfare/api/home/divideData")

    def join_divide(self, reward_type, activity_id):
        return self._post("/ut/welfare/api/action/joinDivide",
                          {"count": 1, "type": reward_type, "activity_id": activity_id})

    def divide_reward(self, task_id, activity_id):
        return self._post("/ut/welfare/api/action/divideReward",
                          {"task_id": task_id, "activity_id": activity_id})


# ── 领券（union.didi.cn，无 wsgsig）───────────────────────────────────────
def _rebate_one(token, item):
    """单业务线领券。返回 (errno, errmsg, rewards[])。
    body 结构（与客户端逐键对齐）：base(15键) ← item(prod_key/dsi[/xbiz/product_type])
    ← token ← env(对象)。★latitude/longitude/cityId 在 JS 里取自 merged（无此三键），
    undefined 被 JSON.stringify 丢弃——这里同样不放入，保持字节级一致。"""
    dchn = random_string(7)
    merged = {"xoid": str(uuid.uuid4()), "dchn": dchn, "dsi": "", "xpsid": "", "xenv": ENV_H5,
              "source_id": SOURCE_ID, "req_env": ENV_H5, "xspm_from": "", "xpsid_from": "",
              "xbiz": "240101", "xpsid_root": "", "xpsid_share": "", "source_from": "",
              "dunion_callback": "", "product_type": "didi"}
    for k, v in item.items():
        if k != "icon":
            merged[k] = v
    merged["token"] = token
    env_obj = {"isOpenWeb": True, "isHitButton": True, "dchn": dchn,
               "newAppid": APPID_H5, "newTicket": token, "fromChannel": FROM_CHANNEL_H5,
               "xAxes": str(rand_int(200, 250)), "yAxes": str(rand_int(400, 450)),
               "timeCost": rand_int(12345, 67890), "userAgent": UA}
    body = dict(merged)
    body["env"] = env_obj
    j = post_json(UNION_BASE + "/api/v1.0/reward/receive", body)
    errno, errmsg = _err(j)
    rewards = []
    if errno == 0:
        rewards = (j.get("data") or {}).get("rewards") or []
    return errno, errmsg, rewards


# ── 业务动作 ──────────────────────────────────────────────────────────────
def run_rebate(token):
    """4 业务线领券。返回 (ok_count, fail_msg, got[], auth_fail)。
    ★auth_fail 判据加阈值：**≥2 条线**同时返 1000010005 才判失效——实测有效 token
    也可能单线返登录失败（花小猪线活动后端更严，2026-10-23 实证：wyc/car/freight
    三条鉴权通过仅返「当前城市无活动」，kf 单线 1000010005，但福利中心签到正常）。"""
    got, fails = [], []
    auth_lines = 0
    for item in REBATE_ITEMS:
        icon = item["icon"]
        errno, errmsg, rewards = _rebate_one(token, item)
        if errno == UNION_AUTH_ERR:
            auth_lines += 1
            print("  %s【%s】登录失败：%s" % (icon, item.get("prod_key"), errmsg))
            continue
        if errno != 0:
            fails.append("%s%s" % (icon, errmsg or errno))
            print("  %s【%s】领取失败：%s" % (icon, item.get("prod_key"), errmsg or errno))
            continue
        if not rewards:
            print("  %s【%s】今日已领完（无新券）" % (icon, item.get("prod_key")))
            continue
        for r in rewards:
            c = r.get("coupon") or {}
            cap = c.get("max_benefit_capacity") or {}
            line = "%s【%s】%s%s、%s" % (icon, c.get("name"), cap.get("value"),
                                        cap.get("unit"), c.get("usage_limit"))
            print("  " + line)
            got.append(line)
    return len(got), ";".join(fails[:3]), got, auth_lines >= 2


def run_welfare(token, cfg, do_sign=True, do_bubble=True, do_ggl=True):
    """福利中心全流程。返回 dict 统计。"""
    st = {"ok": False, "reason": "", "signed": False, "bubbles": 0, "joined": False,
          "rewarded": False, "total": None}
    w = Welfare(token, cfg)
    errno, errmsg = w.init()
    if errno != 0:
        st["reason"] = "init: %s" % (errmsg or errno)
        print("[福利中心] init 失败：%s — 可能 token 失效" % (errmsg or errno))
        return st
    st["ok"] = True

    if do_bubble:
        j = w.get_bubble()
        e, m = _err(j)
        if e == WELFARE_AUTH_ERR:
            st["reason"] = "登录失效: %s" % (m or e)
            print("[福利中心] 登录失效：%s —【滴滴失效】需重新登录领券页取 token" % (m or e))
            return st
        if e != 0:
            print("[福利中心] 气泡查询失败：%s" % (m or e))
        else:
            data = j.get("data") or {}
            bi = data.get("bonus_info") or {}
            st["total"] = bi.get("total_amount")
            print("[福利中心] 福利金 %s ≈ %s 元" % (
                bi.get("total_amount"), bi.get("exchange_total_amount")))
            for b in (data.get("bubble_list") or []):
                cid, btype = b.get("cycle_id"), b.get("bubble_type")
                if not cid:
                    # cycle_id 空 = 无可点气泡。签到型空泡即「今日已签」（签到后
                    # 服务端把 sign 泡置空，2026-10-23 实证），给个明确提示不静默。
                    if btype == "sign":
                        print("  🫧【福利中心】签到气泡：今日已签（无待点气泡）")
                    continue
                j2 = w.click_bubble(cid, btype)
                e2, m2 = _err(j2)
                if e2 == 0:
                    st["bubbles"] += 1
                    print("  🫧【福利中心】%s：+%s福利金" % (
                        b.get("pre_content"), b.get("reward_count")))
                else:
                    print("  🫧【福利中心】%s 点击失败：%s" % (b.get("pre_content"), m2 or e2))

    if do_sign:
        j = w.daily_sign()
        e, m = _err(j)
        if e == SIGN_DUP_ERR or "重复" in str(m):
            st["signed"] = True
            print("🍩【福利中心】今日已签过（重复签到，幂等跳过）")
        elif e == WELFARE_AUTH_ERR:
            st["reason"] = "登录失效: %s" % (m or e)
            print("[福利中心] 登录失效：%s —【滴滴失效】需重新登录领券页取 token" % (m or e))
            return st
        elif e != 0:
            print("[福利中心] 签到：%s" % (m or e))
        else:
            amt = ((j.get("data") or {}).get("subsidy_state") or {}).get("subsidy_amount")
            st["signed"] = True
            print("🍩【福利中心】签到成功，获得 %s 福利金" % amt)

    if do_ggl:
        j = w.divide_data()
        e, m = _err(j)
        if e != 0:
            print("[福利中心] 瓜瓜乐数据失败：%s" % (m or e))
        else:
            divide = ((j.get("data") or {}).get("divide_data") or {}).get("divide") or {}
            today = datetime.now().strftime("%Y-%m-%d")
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            tmr = divide.get(tomorrow) or {}
            tdy = divide.get(today) or {}
            rw = tmr.get("reward") or {}
            if rw.get("type") and tmr.get("activity_id"):
                j2 = w.join_divide(rw.get("type"), tmr.get("activity_id"))
                e2, m2 = _err(j2)
                if e2 == 0:
                    st["joined"] = True
                    print("🍉【福利中心】瓜瓜乐：报名成功")
                else:
                    print("🚫【福利中心】瓜瓜乐：%s" % (m2 or e2))
            if tdy.get("task_id") and tdy.get("activity_id"):
                j3 = w.divide_reward(tdy.get("task_id"), tdy.get("activity_id"))
                e3, m3 = _err(j3)
                if e3 == 0:
                    st["rewarded"] = True
                    print("🍉【福利中心】瓜瓜乐：今日奖励已领取")
                else:
                    print("🚫【福利中心】瓜瓜乐领奖：%s" % (m3 or e3))
    return st


# ── 命令 ──────────────────────────────────────────────────────────────────
def _no_cfg():
    print("[skip] 未配置滴滴 token（didi_coupon_config.json 缺失或无 tokens）——"
          "浏览器打开滴滴领券页登录后 F12 取 localStorage "
          "didih5_trinity_login_ticket_role_121230，用 init 落地。跳过不算失效")
    return 0


def _mask(t):
    return (t[:10] + "…" + t[-6:]) if len(t) > 20 else t


def cmd_init():
    if len(sys.argv) < 3 or not sys.argv[2].strip():
        print("用法: python didi_coupon.py init \"<token>\"")
        print("  或: python didi_coupon.py init \"<token1>;<token2>\"   # 多账号分号分隔")
        print("获取: 浏览器打开 https://vv.didi.cn/a8ZdG0j?source_id=88446DIDI88446tkmmchild1001")
        print("      → 点「立即领取」登录滴滴 → F12 控制台执行:")
        print("      localStorage.getItem('didih5_trinity_login_ticket_role_121230').replace(/\"/g, '')")
        print("      复制输出的字符串（引号已去掉）即为 token，有效期约 7-30 天")
        return 2
    arg = sys.argv[2].strip().strip('"')
    # 支持传入 .txt 文件（内含 token 或整串）
    if os.path.exists(arg) and "=" not in arg[:8]:
        try:
            with open(arg, "r", encoding="utf-8", errors="replace") as f:
                arg = f.read().strip()
        except Exception as e:
            print("[失败] 读取文件失败: %s" % e)
            return 2
    toks = [x.strip().strip('"') for x in arg.split(";") if x.strip()]
    if not toks:
        print("[失败] 未解析到 token")
        return 2
    cfg = load_cfg() or {}
    old = tokens_of(cfg)
    merged = old + [t for t in toks if t not in old]
    cfg["tokens"] = merged
    cfg.setdefault("lat", "39.9592")
    cfg.setdefault("lng", "116.29871")
    cfg.setdefault("city_id", "1")
    # 验证：用 getBubble 验 token（★不是 init——product/init 不校验 token）
    for t in toks:
        w = Welfare(t, cfg)
        w.init()
        j = w.get_bubble()
        e, m = _err(j)
        if e == WELFARE_AUTH_ERR:
            print("[警告] token（%s）登录失效：%s —— 仍写入配置，需重新登录领券页取 token" % (
                _mask(t), m or e))
        elif e == 0:
            bi = (j.get("data") or {}).get("bonus_info") or {}
            print("[OK] token 有效（%s）福利金 %s ≈ %s 元" % (
                _mask(t), bi.get("total_amount"), bi.get("exchange_total_amount")))
        else:
            print("[警告] token（%s）验证未过（errno=%s %s）—— 仍写入配置" % (_mask(t), e, m))
    save_cfg(cfg)
    print("[OK] 已写入 %s（共 %d 个 token，本轮新增 %d）" % (CFG_PATH, len(merged), len(toks)))
    return 0  # init 验证失败也落盘，返回 0 让总控续跑其它平台


def cmd_status():
    cfg = load_cfg()
    toks = tokens_of(cfg) if cfg else []
    if not toks:
        return _no_cfg()
    rc = 0
    for t in toks:
        w = Welfare(t, cfg)
        w.init()
        j = w.get_bubble()
        e, m = _err(j)
        if e == WELFARE_AUTH_ERR:
            print("[%s] 登录失效：%s —【滴滴失效】需重新登录领券页取 token" % (_mask(t), m or e))
            rc = 2
            continue
        if e != 0:
            print("[%s] 余额查询失败：%s" % (_mask(t), m or e))
            rc = 2
            continue
        bi = (j.get("data") or {}).get("bonus_info") or {}
        print("[%s] 福利金 %s ≈ %s 元" % (_mask(t), bi.get("total_amount"),
                                          bi.get("exchange_total_amount")))
    return rc


def cmd_rebate():
    cfg = load_cfg()
    toks = tokens_of(cfg) if cfg else []
    if not toks:
        return _no_cfg()
    rc = 0
    for t in toks:
        print("[领券] 账号 %s" % _mask(t))
        n, fails, _, auth_fail = run_rebate(t)
        print("[领券] %s 本轮新券 %d 张%s" % (_mask(t), n, (" | 失败：" + fails) if fails else ""))
        if auth_fail:
            rc = 2
    return rc


def cmd_welfare():
    cfg = load_cfg()
    toks = tokens_of(cfg) if cfg else []
    if not toks:
        return _no_cfg()
    rc = 0
    for t in toks:
        print("[福利中心] 账号 %s" % _mask(t))
        st = run_welfare(t, cfg)
        if not st.get("ok"):
            print("[失效] %s 福利中心链路异常：%s —【滴滴失效】需重新登录领券页取 token" % (
                _mask(t), st.get("reason")))
            rc = 2
    return rc


def cmd_probe():
    cfg = load_cfg()
    toks = tokens_of(cfg) if cfg else []
    if not toks:
        return _no_cfg()
    t = toks[0]
    w = Welfare(t, cfg)
    e, m = w.init()
    print("[probe] init errno=%s msg=%s" % (e, m))
    j = w.get_bubble()
    print("[probe] getBubble 原文:\n%s" % json.dumps(j, ensure_ascii=False)[:800])
    return 0


# ── sync：从本机浏览器登录态自动取 token（阿里云盘同款思路）──────────────────
def _browser_tokens():
    """双通道取滴滴 H5 登录票据：
    1) CDP：枚举标签页找 didi.cn 页面，Runtime.evaluate 读 localStorage
       （键前缀 didih5_trinity_login_ticket，role 后缀随活动变，用前缀匹配）
    2) leveldb 兜底：扫浏览器 Local Storage 文件按键名定位、按值提取
    返回 [(key, value)]，无登录态返回 []。"""
    out = []
    # 通道 1：CDP
    try:
        import urllib.request as _u
        tabs = json.load(_u.urlopen("http://127.0.0.1:9222/json/list", timeout=4))
        didi_tabs = [t for t in tabs if "didi" in (t.get("url") or "").lower()
                     and t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        for t in didi_tabs:
            try:
                import websocket  # websocket-client
                # ★suppress_origin=True：不带 Origin 头，否则 Chrome 系 WS 端点
                #   403「Rejected an incoming WebSocket connection」（全项目通用绕法）
                ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=8,
                                                 suppress_origin=True)
                expr = ("Object.keys(localStorage)"
                        ".filter(function(k){return k.indexOf('didih5_trinity_login_ticket')===0})"
                        ".map(function(k){return k+'='+localStorage.getItem(k)})"
                        ".join('\\u0001')")
                ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                    "params": {"expression": expr, "returnByValue": True}}))
                msg = json.loads(ws.recv())
                ws.close()
                val = ((msg.get("result") or {}).get("result") or {}).get("value") or ""
                for pair in str(val).split("\x01"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        # ★localStorage 的值是 JSON 字符串化过的（自带双引号），
                        # 必须剥掉——官方 README 的取票命令也带 .replace(/"/g,'')
                        v = v.strip().strip('"').strip()
                        if v:
                            out.append((k.strip(), v))
            except Exception:
                continue
    except Exception:
        pass
    # 通道 2：leveldb 兜底
    if not out:
        try:
            import glob
            import browser_cookies as bc
            ud = bc.browser_ud()
            profs = ["Default"] + [os.path.basename(p) for p in
                                   glob.glob(os.path.join(ud, "Profile*")) if os.path.isdir(p)]
            for prof in profs:
                lsdir = os.path.join(ud, prof, "Local Storage", "leveldb")
                if not os.path.isdir(lsdir):
                    continue
                for f in glob.glob(os.path.join(lsdir, "*")):
                    try:
                        raw = open(f, "rb").read()
                    except Exception:
                        continue
                    idx = raw.find(b"didih5_trinity_login_ticket")
                    while idx != -1:
                        seg = raw[idx:idx + 4096]
                        eq = seg.find(b"=")
                        if eq != -1:
                            val = []
                            for c in seg[eq + 1:]:
                                if 33 <= c < 127:
                                    val.append(chr(c))
                                else:
                                    break
                            v = "".join(val).strip().strip('"')
                            if len(v) >= 16:
                                out.append(("didih5_trinity_login_ticket(leveldb)", v))
                        idx = raw.find(b"didih5_trinity_login_ticket", idx + 1)
        except Exception:
            pass
    # 去重（保序）
    seen, uniq = set(), []
    for k, v in out:
        if v not in seen:
            seen.add(v)
            uniq.append((k, v))
    return uniq


def cmd_sync():
    """从浏览器登录态取 token 并写入配置（替代手工 F12 抄 localStorage）。"""
    cfg = load_cfg() or {}
    found = _browser_tokens()
    if not found:
        print("[skip] 浏览器里没有滴滴登录态——请先在 Thorium 打开领券页 "
              "https://vv.didi.cn/a8ZdG0j 点「立即领取」完成登录，再跑 sync")
        return 0
    old = tokens_of(cfg)
    added = 0
    for k, v in found:
        if v not in old:
            old.append(v)
            added += 1
    cfg["tokens"] = old
    cfg.setdefault("lat", "39.9592")
    cfg.setdefault("lng", "116.29871")
    cfg.setdefault("city_id", "1")
    # 逐个验证
    ok = 0
    for t in [v for _, v in found]:
        w = Welfare(t, cfg)
        w.init()
        j = w.get_bubble()
        e, m = _err(j)
        if e == WELFARE_AUTH_ERR:
            print("[警告] 从浏览器取到的票据（%s）已失效：%s" % (_mask(t), m or e))
        elif e == 0:
            bi = (j.get("data") or {}).get("bonus_info") or {}
            print("[OK] 票据有效（%s）福利金 %s ≈ %s 元" % (
                _mask(t), bi.get("total_amount"), bi.get("exchange_total_amount")))
            ok += 1
        else:
            print("[警告] 票据（%s）验证未过（errno=%s %s）" % (_mask(t), e, m))
    save_cfg(cfg)
    print("[OK] 已写入 %s（浏览器取到 %d 个，新增 %d，有效 %d）" % (
        CFG_PATH, len(found), added, ok))
    return 0


def cmd_auto():
    cfg = load_cfg()
    toks = tokens_of(cfg) if cfg else []
    if not toks:
        return _no_cfg()
    rc = 0
    for t in toks:
        print("=" * 46)
        print("[滴滴] 账号 %s" % _mask(t))
        n, fails, _, auth_fail = run_rebate(t)
        print("[领券] 新券 %d 张%s" % (n, (" | 失败：" + fails) if fails else ""))
        st = run_welfare(t, cfg)
        if not st.get("ok") or auth_fail:
            print("[失效] 福利中心/领券链路异常：%s —【滴滴失效】需重新登录领券页取 token" % (
                st.get("reason") or ("登录失败(union errno=%s)" % UNION_AUTH_ERR)))
            rc = 2
        print("[汇总] %s 领券 %d 张 | 签到 %s | 气泡 %d | 瓜瓜乐报名 %s 领奖 %s | 福利金余额 %s" % (
            _mask(t), n, "✓" if st.get("signed") else "✗", st.get("bubbles") or 0,
            "✓" if st.get("joined") else "✗", "✓" if st.get("rewarded") else "✗",
            st.get("total")))
    return rc


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "init":
        sys.exit(cmd_init())
    elif cmd == "sync":
        sys.exit(cmd_sync())
    elif cmd == "status":
        sys.exit(cmd_status())
    elif cmd == "rebate":
        sys.exit(cmd_rebate())
    elif cmd == "welfare":
        sys.exit(cmd_welfare())
    elif cmd == "probe":
        sys.exit(cmd_probe())
    elif cmd == "auto":
        sys.exit(cmd_auto())
    else:
        print(__doc__)
        sys.exit(1)
