#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美团福利社领券 · 纯接口版 (mtgsig 沙箱还原方案)
================================================
方案: 在 Node 沙箱中运行逆向提取的 wx-jsguard 签名模块(原算法, 非重放),
     每次请求实时生成新鲜 mtgsig → Python 发起真实领券请求。

链路: listActivityCoupon(30300 预请求) -> grantActivityCoupon(30301 领取)

★2026-10-12 起两项重要变更:
  1. 列表请求体由 form 改为 **JSON**(Content-Type: application/json),
     与小程序当前版本抓包逐字段对齐(数值字段为数字, osType="Windows", distributorChannel=0);
     JSON 体未通过时自动回退旧 form 体, 保证兼容。
  2. 幂等由**日级**(state[today]=="done" 整日跳过)改为 **rightCode 级**:
     红包墙当天会刷新批次(实测 totalCouponValue 从 ¥222 涨到 ¥412),
     日级标记会把后出现的新批次全部挡掉, 造成"当天没领"的错觉。
     现按 grant 实际发送过的 rightCode 记录, 只领新出现的券。

用法:
  python mt_api_coupon.py dryrun    # 仅生成签名+打印请求体(不发网络)
  python mt_api_coupon.py claim     # 执行领券(rightCode 级幂等)
  python mt_api_coupon.py probe     # 只拉列表打印可领券, 不领取
  python mt_api_coupon.py share     # 只读查分享弹窗(querySharePopWindow)
  python mt_api_coupon.py market    # 营销页红包（需抓包过营销页，可选）
  python mt_api_coupon.py status
"""
import gzip
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
# Node 可执行: 优先环境变量 MT_NODE；否则常见本机路径；否则命令 node 本身
NODE = os.environ.get("MT_NODE") or ""
if not NODE:
    for cand in [
                 r"C:\Program Files\nodejs\node.exe",
                 r"C:\Program Files (x86)\nodejs\node.exe",
                 "node", "node.exe"]:
        if cand in ("node", "node.exe") or os.path.exists(cand):
            NODE = cand
            break
SANDBOX = os.path.join(BASE, "jsguard_node_sandbox.js")
CONFIG_PATH = os.path.join(BASE, "mt_config.json")
STATE_PATH = os.path.join(BASE, "mt_claim_state.json")
LOG_PATH = os.path.join(BASE, "mt_coupon.log")

APP_ID = "wx0b42a347aafbe0d0"
HOST = "https://media.meituan.com"
QS = ("yodaReady=wx&csecappid=%s&csecplatform=3&csecversionname=1.52.0&csecversion=1.3.0" % APP_ID)
URL_LIST = HOST + "/fulishemini/couponActivity/listActivityCoupon?" + QS
URL_GRANT = HOST + "/fulishemini/couponActivity/grantActivityCoupon?" + QS
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
      "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
      "UnifiedPCWindowsWechat(0xf2541f0d) XWEB/25715")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
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


def gen_mtgsig(method, url, body_str):
    """调 Node 沙箱, 用还原的 wx-jsguard 原算法对 (method,url,body) 现算 mtgsig"""
    r = subprocess.run(
        [NODE, SANDBOX, method, url, body_str],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        cwd=BASE,
    )
    if r.returncode != 0:
        raise RuntimeError("sandbox fail rc=%s err=%s" % (r.returncode, (r.stderr or "")[:300]))
    out = json.loads(r.stdout.strip())
    if not out.get("ok"):
        raise RuntimeError("sandbox no sig: %s" % r.stdout[:300])
    return out["mtgsig"], out.get("dfpid", "")


def build_body_str(cfg, psub_code, extra=None):
    """按抓包参数序构造 form body(顺序与原请求保持一致)"""
    d = [
        ("city_id_level3", cfg.get("city_id_level3", "411621")),
        ("city_id_level2", cfg.get("city_id_level2", "411600")),
        ("actual_city_id_level3", cfg.get("actual_city_id_level3", "411621")),
        ("actual_city_id_level2", cfg.get("actual_city_id_level2", "411600")),
        ("wm_actual_longitude", cfg.get("wm_actual_longitude", "114394821")),
        ("wm_actual_latitude", cfg.get("wm_actual_latitude", "34060001")),
        ("wm_longitude", cfg.get("wm_longitude", "114394821")),
        ("wm_latitude", cfg.get("wm_latitude", "34060001")),
        ("unionid", cfg.get("unionid", "")),
        ("open_id", cfg.get("open_id", "")),
        ("wm_uuid_source", "server"),
        ("lch", cfg.get("lch", "1256")),
        ("user_id", cfg.get("userid", "")),
        ("userid", cfg.get("userid", "")),
        ("req_time", str(int(time.time() * 1000))),
        ("wm_logintoken", cfg.get("wm_logintoken", "")),
        ("wm_appversion", cfg.get("wm_appversion", "1.52.0")),
        ("wm_visitid", cfg.get("wm_visitid", "")),
        ("wm_uuid", cfg.get("wm_uuid", "")),
        ("wm_dplatform", cfg.get("wm_dplatform", "windows")),
        ("wm_dversion", cfg.get("wm_dversion", "4.1.15.13")),
        ("wm_dtype", cfg.get("wm_dtype", "microsoft")),
        ("wm_ctype", cfg.get("wm_ctype", "fulishe_wxapp")),
        ("waimai_sign", "/"),
        # 领券业务参数
        ("pSubCode", str(psub_code)),
        ("requestType", "0"),
        ("requestSource", "1"),
        ("fp_platform", "13"),
        ("appId", APP_ID),
        ("expoId", cfg.get("expoId", "")),
        ("cPosition", "1005"),
        ("pBizLine", "9000"),
        ("couponActivityScene", "1"),
        ("osType", "windows"),
        ("finger_applets", cfg.get("_finger_applets", "")),
    ]
    if cfg.get("distributorChannel"):
        d.append(("distributorChannel", cfg["distributorChannel"]))
    if extra:
        for k, v in extra.items():
            d.append((k, v))
    return urllib.parse.urlencode(d)


def http_post(url, body_str, mtgsig, openid_cipher, openid, csecuuid, csecuserid, token):
    req = urllib.request.Request(url, data=body_str.encode("utf-8"), method="POST")
    for k, v in {
        "Host": "media.meituan.com",
        "geographyInfo": "%7B%7D",
        "openIdCipher": openid_cipher,
        "mtgsig": mtgsig,
        "xweb_xhr": "1",
        "csecuuid": csecuuid,
        "x-env": "online",
        "csecuserid": csecuserid,
        "openId": openid,
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "token": token,
        "Accept": "*/*",
        "Referer": "https://servicewechat.com/%s/275/page-frame.html" % APP_ID,
        "Accept-Encoding": "gzip",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            elif raw[:1] == b"\x78":
                try:
                    raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                except Exception:
                    pass
            return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        if raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        return e.code, raw.decode("utf-8", "replace")



def http_post_json(url, body_json, mtgsig, cfg):
    """grant 用: application/json (urls.js 定义 headers content-type application/json)"""
    req = urllib.request.Request(url, data=body_json.encode("utf-8"), method="POST")
    for k, v in {
        "Host": "media.meituan.com",
        "geographyInfo": "%7B%7D",
        "openIdCipher": cfg.get("openIdCipher", ""),
        "mtgsig": mtgsig,
        "xweb_xhr": "1",
        "csecuuid": cfg.get("wm_uuid", ""),
        "x-env": "online",
        "csecuserid": cfg.get("csecuserid", ""),
        "openId": cfg.get("open_id", ""),
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": UA,
        "Content-Type": "application/json",
        "token": cfg.get("token", ""),
        "Accept": "*/*",
        "Referer": "https://servicewechat.com/%s/275/page-frame.html" % APP_ID,
        "Accept-Encoding": "gzip",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        if raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        return e.code, raw.decode("utf-8", "replace")

def check_config(cfg):
    need = ["wm_logintoken", "expoId", "open_id", "unionid", "wm_uuid", "userid", "openIdCipher", "csecuserid", "token"]
    missing = [k for k in need if not cfg.get(k)]
    return (not missing), missing


def build_grant_body(cfg, data1, tabs_arr):
    """构造 grantActivityCoupon JSON body — 与 2026-10-09 真实抓包逐字段对齐。

    抓包关键点:
      - osType: "Windows" (大写 W)
      - unpl: v1_ 开头的真实埋点串 (非空)
      - pageId/moduleId: 页面/模块埋点 ID
      - finger_applets: WX__ver1.2.0_CCCC_ 开头的设备指纹长串 (不是 dfpid)
      - sessionId: hex 随机串, 形如 "1a11f1d7388-d2ac-4679-b66f" (11-4-4-4)
      - distributorChannel: 0 (数字)
      - 数值型字段均为数字而非字符串: userid/lch/city codes/经纬度/req_time 等
      - wm_did/wm_mac 为空字符串
    """
    def as_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return v  # 转不动就保留原值, 避免误伤

    # 抓包里的数字字段 (build_body_str 产出全是字符串, 这里统一转数字)
    numeric_keys = (
        "city_id_level3", "city_id_level2", "actual_city_id_level3",
        "actual_city_id_level2", "wm_actual_longitude", "wm_actual_latitude",
        "wm_longitude", "wm_latitude", "lch", "userid", "req_time",
    )

    # 公共参数(dict) — 先按 form 序产出再转 JSON dict
    body_pairs = build_body_str(cfg, 30301)
    full = {k: v[0] for k, v in urllib.parse.parse_qs(body_pairs, keep_blank_values=True).items()}

    # 数字化
    for k in numeric_keys:
        if k in full:
            full[k] = as_int(full[k])
    # wm_did/wm_mac 空串 (抓包原样)
    full["wm_did"] = ""
    full["wm_mac"] = ""
    # distributorChannel 抓包为数字 0 (与 wm 渠道号 lch=1256 是两个字段)
    full["distributorChannel"] = 0

    # 业务字段 (抓包对齐)
    full.update({
        "activityName": (data1.get("config") or {}).get("activityName", ""),
        "activityCode": (data1.get("config") or {}).get("activityCode", ""),
        "sessionId": _gen_session_id(),
        "unpl": cfg.get("unpl", ""),
        "tabs": tabs_arr,
        "requestType": 0, "requestSource": 1,
        "couponActivityScene": 1, "activityScene": 1,
        "fp_platform": 13, "cPosition": 1005, "pBizLine": 9000, "pSubCode": 30301,
        "osType": "Windows",
        "pageId": cfg.get("pageId", "c_waimai_7hs96y41"),
        "moduleId": cfg.get("moduleId", "b_waimai_gci8oda9_mc"),
        "finger_applets": cfg.get("finger_applets_real", "") or cfg.get("_finger_applets", ""),
        "hostAppVersion": "",
    })
    if data1.get("recallToken"):
        full["recallToken"] = data1["recallToken"]
    if data1.get("preGrantSource"):
        full["preGrantSource"] = data1["preGrantSource"]
    return full


def _gen_session_id():
    """复刻抓包 sessionId 格式: 4 段 hex, 11-4-4-4, 如 "1a11f1d7388-d2ac-4679-b66f" """
    seg = lambda n: "".join(random.choice("0123456789abcdef") for _ in range(n))
    return "%s-%s-%s-%s" % (seg(11), seg(4), seg(4), seg(4))


def build_list_body_json(cfg, psub=30300):
    """惠省红包墙**列表**请求 JSON body — 与 2026-10-12 抓包逐字段对齐。

    抓包: POST /fulishemini/couponActivity/listActivityCoupon
          Content-Type: application/json, pSubCode=30300
    与旧 form 体(build_body_str)字段集一致, 差异:
      - JSON 且数值字段为数字(userid/lch/经纬度/req_time/cPosition/fp_platform...)
      - osType="Windows"(大写), 旧 form 体是小写 windows
      - distributorChannel=0(数字; mt_config 里的 1256 是 wm 渠道号 lch, 不是这个字段)
      - requestType=0 / requestSource=1 / couponActivityScene=1
      - hostAppVersion="" / wm_did="" / wm_mac=""
    """
    def as_int(v, d=0):
        try:
            return int(v)
        except (TypeError, ValueError):
            return d

    return {
        "wm_did": "",
        "wm_mac": "",
        "waimai_sign": "/",
        "wm_ctype": cfg.get("wm_ctype", "fulishe_wxapp"),
        "wm_dtype": cfg.get("wm_dtype", "microsoft"),
        "wm_dversion": cfg.get("wm_dversion", "4.1.15.53"),
        "wm_dplatform": cfg.get("wm_dplatform", "windows"),
        "wm_uuid": cfg.get("wm_uuid", ""),
        "wm_visitid": cfg.get("wm_visitid", ""),
        "wm_appversion": cfg.get("wm_appversion", "1.52.0"),
        "wm_logintoken": cfg.get("wm_logintoken", ""),
        "req_time": int(time.time() * 1000),
        "userid": as_int(cfg.get("userid")),
        "user_id": as_int(cfg.get("userid")),
        "lch": as_int(cfg.get("lch", "1256"), 1256),
        "wm_uuid_source": "server",
        "hostAppVersion": "",
        "open_id": cfg.get("open_id", ""),
        "unionid": cfg.get("unionid", ""),
        "fp_platform": 13,
        "appId": APP_ID,
        "cPosition": 1005,
        "pBizLine": 9000,
        "pSubCode": psub,
        "finger_applets": cfg.get("finger_applets_real", "") or cfg.get("_finger_applets", ""),
        "expoId": cfg.get("expoId", ""),
        "requestType": 0,
        "requestSource": 1,
        "couponActivityScene": 1,
        "osType": "Windows",
        "distributorChannel": 0,
        "wm_latitude": as_int(cfg.get("wm_latitude"), 34060001),
        "wm_longitude": as_int(cfg.get("wm_longitude"), 114394821),
        "wm_actual_latitude": as_int(cfg.get("wm_actual_latitude"), 34060001),
        "wm_actual_longitude": as_int(cfg.get("wm_actual_longitude"), 114394821),
        "actual_city_id_level2": cfg.get("actual_city_id_level2", "411600"),
        "actual_city_id_level3": cfg.get("actual_city_id_level3", "411621"),
        "city_id_level2": cfg.get("city_id_level2", "411600"),
        "city_id_level3": cfg.get("city_id_level3", "411621"),
    }


def fetch_list(cfg):
    """拉红包墙列表。先 JSON 体(当前小程序版本), 失败自动回退旧 form 体。
    返回 (ok, data, msg, src)"""
    # 先 probe 一次拿 dfpid 作 finger_applets 兜底
    try:
        _, dfpid = gen_mtgsig("POST", URL_LIST, "probe=1")
        cfg["_finger_applets"] = dfpid
    except Exception as e:
        print("      [warn] probe 拿 dfpid 失败: %s" % e)

    # --- 首选: JSON 体 ---
    body_json = json.dumps(build_list_body_json(cfg), ensure_ascii=False, separators=(",", ":"))
    try:
        mtgsig, _ = gen_mtgsig("POST", URL_LIST, body_json)
        c, t = http_post_json(URL_LIST, body_json, mtgsig, cfg)
        if c == 200:
            try:
                j = json.loads(t)
                if j.get("code") in (0, 200, "0", "200"):
                    return True, j.get("data") or {}, "ok", "json"
                print("      [回退] JSON 列表体业务码 %s %s" % (j.get("code"), j.get("msg", "")))
            except Exception:
                print("      [回退] JSON 列表体响应非 JSON: %s" % t[:120])
        else:
            print("      [回退] JSON 列表体 HTTP %s" % c)
    except Exception as e:
        print("      [回退] JSON 列表体异常: %s" % e)

    # --- 回退: 旧 form 体 ---
    body_str = build_body_str(cfg, 30300)
    try:
        mtgsig, _ = gen_mtgsig("POST", URL_LIST, body_str)
        c, t = http_post(
            URL_LIST, body_str, mtgsig,
            cfg.get("openIdCipher", ""), cfg.get("open_id", ""),
            cfg.get("wm_uuid", ""), cfg.get("csecuserid", ""), cfg.get("token", ""),
        )
        if c != 200:
            return False, None, "HTTP %s: %s" % (c, t[:150]), "form"
        try:
            j = json.loads(t)
        except Exception:
            return False, None, "响应非 JSON: %s" % t[:150], "form"
        if j.get("code") not in (0, 200, "0", "200"):
            return False, None, "code=%s %s" % (j.get("code"), j.get("msg", "")), "form"
        return True, j.get("data") or {}, "ok", "form"
    except Exception as e:
        return False, None, "form 体异常: %s" % e, "form"


def wall_tabs(data, exclude_rc=None):
    """红包墙可领券按 planCode 分组 → tabs。

    ★status/couponViewId 语义(2026-10-12 00:58 + 22:49 两次实测确认):
      couponViewId==null          = **可领**(00:58 的 21 张即此态, grant 后全部到账)
      couponViewId 有值           = **已在卡包**(领过了, 勿再发)
      ★注意: 本端点 status 语义与分销会场**相反**——这里 status==1 才是可领
      (00:58: status=1 的 21 张 cvId 全为 null; status=0 的 22 张 cvId 全有值)。
      但 cvId 与 status 并非服务端契约(实测 21/21、22/22 完全相关只是巧合对齐),
      **故以 couponViewId 为唯一权威判据**, status 仅作诊断参考:
      万一日后服务端省略/改动 status, 也不会漏券; 误发已拥有券则由服务端幂等兜底。
    exclude_rc: 本地已发送过的 rightCode(grant code:200 即视为服务端已处理,
    含互斥未发放), 实现 rightCode 级幂等 —— 当天后出现的新批次不受影响。
    返回 (tabs, detail)。
    """
    exclude_rc = exclude_rc or set()
    tabs_map = {}
    detail = []
    now = int(time.time() * 1000)
    for it in (data.get("list") or []) + (data.get("preGrantList") or []):
        if not (isinstance(it, dict) and it.get("type") == 1):
            continue
        d = it.get("data") or {}
        rc = d.get("rightCode")
        if not rc:
            continue
        cv = d.get("couponViewId")
        et = d.get("couponEndTime") or 0
        item = {
            "name": d.get("couponName", ""),
            "value": d.get("couponValue", 0),
            "limit": d.get("priceLimit", 0),
            "planCode": d.get("planCode", ""),
            "rightCode": rc,
            "held": bool(cv),                 # 已在卡包
            "status": d.get("status"),
            "expired": bool(et and et < now),
            "skipped": rc in exclude_rc,
            "claimable": (not cv) and not (et and et < now),
        }
        detail.append(item)
        if item["claimable"] and rc not in exclude_rc:
            tabs_map.setdefault(d.get("planCode", ""), []).append(rc)
    tabs = [{"planCode": pc, "rightCodes": rcs} for pc, rcs in tabs_map.items()]
    return tabs, detail


URL_SHARE_POP = HOST + "/fulishemini/querySharePopWindow?" + QS


def query_share_pop(cfg):
    """只读查分享弹窗(querySharePopWindow, form 体, scene=1)。
    2026-10-12 实测返回 {"code":0,"data":null} = 无弹窗/无待领分享奖励。
    返回 (ok, msg, data)"""
    import urllib.parse as _up
    d = [
        ("city_id_level3", cfg.get("city_id_level3", "411621")),
        ("city_id_level2", cfg.get("city_id_level2", "411600")),
        ("actual_city_id_level3", cfg.get("actual_city_id_level3", "411621")),
        ("actual_city_id_level2", cfg.get("actual_city_id_level2", "411600")),
        ("wm_actual_longitude", cfg.get("wm_actual_longitude", "114394821")),
        ("wm_actual_latitude", cfg.get("wm_actual_latitude", "34060001")),
        ("wm_longitude", cfg.get("wm_longitude", "114394821")),
        ("wm_latitude", cfg.get("wm_latitude", "34060001")),
        ("scene", "1"),
        ("unionid", cfg.get("unionid", "")),
        ("open_id", cfg.get("open_id", "")),
        ("wm_uuid_source", "server"),
        ("lch", cfg.get("lch", "1256")),
        ("user_id", cfg.get("userid", "")),
        ("userid", cfg.get("userid", "")),
        ("req_time", str(int(time.time() * 1000))),
        ("wm_logintoken", cfg.get("wm_logintoken", "")),
        ("wm_appversion", cfg.get("wm_appversion", "1.52.0")),
        ("wm_visitid", cfg.get("wm_visitid", "")),
        ("wm_uuid", cfg.get("wm_uuid", "")),
        ("wm_dplatform", cfg.get("wm_dplatform", "windows")),
        ("wm_dversion", cfg.get("wm_dversion", "4.1.15.53")),
        ("wm_dtype", cfg.get("wm_dtype", "microsoft")),
        ("wm_ctype", cfg.get("wm_ctype", "fulishe_wxapp")),
        ("waimai_sign", "/"),
    ]
    body_str = _up.urlencode(d)
    try:
        _, dfpid = gen_mtgsig("POST", URL_SHARE_POP, "probe=1")
        cfg["_finger_applets"] = dfpid
        mtgsig, _ = gen_mtgsig("POST", URL_SHARE_POP, body_str)
        c, t = http_post(
            URL_SHARE_POP, body_str, mtgsig,
            cfg.get("openIdCipher", ""), cfg.get("open_id", ""),
            cfg.get("wm_uuid", ""), cfg.get("csecuserid", ""), cfg.get("token", ""),
        )
    except Exception as e:
        return False, "异常: %s" % e, None
    if c != 200:
        return False, "HTTP %s" % c, None
    try:
        j = json.loads(t)
    except Exception:
        return False, "响应非 JSON", None
    if j.get("code") not in (0, 200, "0", "200"):
        return False, "code=%s %s" % (j.get("code"), j.get("msg", "")), None
    return True, "ok", j.get("data")


def claim():
    cfg = load_json(CONFIG_PATH, {}) or {}
    ok, missing = check_config(cfg)
    if not ok:
        print("[失败] mt_config.json 缺少字段: %s" % ", ".join(missing))
        print("  (openIdCipher/csecuserid/token 等取自抓包请求头, 已在 analyze 时记录)")
        return 1

    state = load_json(STATE_PATH, {}) or {}
    today = datetime.now().strftime("%Y-%m-%d")
    # ★2026-10-12: 日级幂等 → rightCode 级幂等。
    # 旧格式 state[today]=="done"(字符串) 会让当天后出现的新批次全部被挡掉,
    # 造成"当天没领"的错觉(红包墙当天会刷新, 实测 totalCouponValue ¥222→¥412)。
    # 现按 grant 实际发送过的 rightCode 记录, 只领新出现的券; 旧字符串格式自动迁移。
    st = state.get(today)
    if not isinstance(st, dict):
        st = {"granted_rc": [], "granted": [], "legacy_done": (st == "done")}
        state[today] = st
    granted_rc = set(st.get("granted_rc") or [])

    print("=" * 62)
    print("美团惠省红包墙领券(API+沙箱签名) %s" % datetime.now().strftime("%F %T"))
    print("=" * 62)

    # 1) 列表（JSON 体优先, 失败回退旧 form 体）
    print("[1/2] listActivityCoupon (30300) ...")
    ok, data1, msg, src = fetch_list(cfg)
    if not ok:
        print("[中断] 列表拉取失败: %s" % msg)
        log("list fail: %s" % msg)
        return 2
    conf = data1.get("config") or {}
    print("      列表体=%s  活动: %s (activityCode=%s)  totalCouponValue=¥%.1f"
          % (src, conf.get("activityName", "?"), conf.get("activityCode", "?"),
             (data1.get("totalCouponValue") or 0) / 100.0))
    save_json(os.path.join(BASE, "mt_list_resp.json"),
              {"http": 200, "body": json.dumps({"code": 200, "msg": "成功", "data": data1},
                                               ensure_ascii=False)})

    # 可领券 = couponViewId 为空(00:58 实测: 该态 grant 后全部到账; 与 status==1 完全相关,
    # 但 cvId 才是权威判据 —— 本端点 status 语义与分销会场相反, 勿照搬 status==0);
    # 带 couponViewId = 已在卡包, 不再发。再按本地 rightCode 去重。
    tabs, detail = wall_tabs(data1, granted_rc)
    n_claim = sum(len(t["rightCodes"]) for t in tabs)
    n_held = sum(1 for d in detail if d["held"])
    n_skip = sum(1 for d in detail if d.get("skipped"))
    n_exp = sum(1 for d in detail if d["expired"])
    print("      券总数 %d: 可领 %d（%d 组）/ 已在卡包 %d / 本地幂等 %d / 已过期 %d"
          % (len(detail), n_claim, len(tabs), n_held, n_skip, n_exp))
    for d in detail:
        if d["claimable"] and not d.get("skipped"):
            print("        · %s ¥%.1f 满¥%.1f可用" % (d["name"], d["value"] / 100.0, d["limit"] / 100.0))

    if not tabs:
        print("[幂等] 无可领券：今日批次均已处理（本地已记录 %d 个 rightCode，已在卡包 %d 张）。"
              % (len(granted_rc), n_held))
        st["idempotent"] = True
        st["ts"] = datetime.now().strftime("%F %T")
        st["wall_total"] = data1.get("totalCouponValue")
        save_json(STATE_PATH, state)
        # 分享弹窗只读确认(不影响主流程; 2026-10-12 实测 data=null 无待领奖励)
        try:
            sok, _smsg, sdata = query_share_pop(cfg)
            if sok:
                print("      [分享弹窗] %s" % ("无(data=null)，无待领分享奖励" if not sdata
                                              else "有待处理内容: %s" % json.dumps(sdata, ensure_ascii=False)[:300]))
        except Exception as e:
            print("      [分享弹窗] 查询失败(不影响主流程): %s" % e)
        return 0

    # 2) 领取（JSON content-type, 复刻 urls.js grantActivityCoupon 定义）
    print("[2/2] grantActivityCoupon (30301, JSON) ...")
    full = build_grant_body(cfg, data1, tabs)
    body_json = json.dumps(full, ensure_ascii=False, separators=(",", ":"))
    mtgsig, _ = gen_mtgsig("POST", URL_GRANT, body_json)
    c2, t2 = http_post_json(URL_GRANT, body_json, mtgsig, cfg)
    print("      HTTP %s" % c2)
    print("      resp: %s" % t2[:400])
    save_json(os.path.join(BASE, "mt_grant_resp.json"), {"http": c2, "body": t2[:200000]})

    success = False
    try:
        j2 = json.loads(t2)
        success = j2.get("code") in (0, 200, "0", "200")
    except Exception:
        success = c2 == 200
    if success:
        sent_rc = [rc for t in tabs for rc in t["rightCodes"]]
        granted_rc.update(sent_rc)
        st["granted_rc"] = sorted(granted_rc)
        got = []
        try:
            j2 = json.loads(t2)
            for tab in ((j2.get("data") or {}).get("tabs") or []):
                for cp in (tab.get("couponList") or []):
                    if isinstance(cp, dict) and cp.get("couponViewId"):
                        got.append({"name": cp.get("couponName", ""),
                                    "value": cp.get("couponValue", 0),
                                    "limit": cp.get("priceLimit", 0)})
        except Exception:
            pass
        st["granted"] = (st.get("granted") or []) + got
        st["ts"] = datetime.now().strftime("%F %T")
        st["wall_total"] = data1.get("totalCouponValue")
        val = sum(g["value"] for g in got)
        print("[完成] 领取成功 ✅  本次发放 %d 张 ¥%.1f（本次处理 %d 个 rightCode，本地累计 %d 个）"
              % (len(got), val / 100.0, len(sent_rc), len(granted_rc)))
        for g in got:
            print("        + %s ¥%.1f 满¥%.1f" % (g["name"], g["value"] / 100.0, g["limit"] / 100.0))
        log("claim ok got=%d val=%.1f sent_rc=%d total_rc=%d"
            % (len(got), val / 100.0, len(sent_rc), len(granted_rc)))
    else:
        print("[未成功] 服务端未确认领取, 响应已存盘人工核对 (可能互斥/库存空/风控)。")
        print("        ★未记录 rightCode, 下次运行会重试同一批。")
        st["last_fail"] = {"ts": datetime.now().strftime("%F %T"), "resp": t2[:300]}
        log("claim fail http=%s resp=%s" % (c2, t2[:200]))
    save_json(STATE_PATH, state)
    return 0 if success else 3


def probe():
    """只拉列表打印可领券, 不领取(诊断用)"""
    cfg = load_json(CONFIG_PATH, {}) or {}
    ok, missing = check_config(cfg)
    if not ok:
        print("[失败] mt_config.json 缺少字段: %s" % ", ".join(missing))
        return 1
    ok, data1, msg, src = fetch_list(cfg)
    if not ok:
        print("[中断] 列表拉取失败: %s" % msg)
        return 2
    conf = data1.get("config") or {}
    print("活动: %s (activityCode=%s)  列表体=%s  totalCouponValue=¥%.1f  recallToken=%s"
          % (conf.get("activityName", "?"), conf.get("activityCode", "?"), src,
             (data1.get("totalCouponValue") or 0) / 100.0, (data1.get("recallToken") or "")[:40]))
    tabs, detail = wall_tabs(data1)
    n_held = sum(1 for d in detail if d["held"])
    n_exp = sum(1 for d in detail if d["expired"])
    print("券总数 %d: 可领 %d（%d 组）/ 已在卡包 %d / 已过期 %d"
          % (len(detail), sum(len(t["rightCodes"]) for t in tabs), len(tabs), n_held, n_exp))
    for d in detail:
        if d["claimable"]:
            print("  · %s ¥%.1f 满¥%.1f  rc=%s" % (d["name"], d["value"] / 100.0,
                                                   d["limit"] / 100.0, d["rightCode"]))
    try:
        sok, _smsg, sdata = query_share_pop(cfg)
        if sok:
            print("分享弹窗: %s" % ("无(data=null)" if not sdata else json.dumps(sdata, ensure_ascii=False)[:300]))
    except Exception as e:
        print("分享弹窗查询失败: %s" % e)
    return 0


def dryrun():
    cfg = load_json(CONFIG_PATH, {}) or {}
    body_str = build_body_str(cfg, 30300)
    mtgsig, dfpid = gen_mtgsig("POST", URL_LIST, body_str)
    print("### dryrun ###")
    print("POST %s" % URL_LIST)
    print("body: %s" % body_str[:400])
    print("mtgsig: %s" % mtgsig)
    print("dfpid:  %s" % dfpid)
    print("\n### 配置状态 ###")
    ok, missing = check_config(cfg)
    print("  完整" if ok else "  缺少: %s" % ", ".join(missing))
    return 0


def status():
    cfg = load_json(CONFIG_PATH, {}) or {}
    ok, missing = check_config(cfg)
    print("配置: %s" % ("完整" if ok else "缺少 %s" % missing))
    print("导入时间: %s" % cfg.get("_imported_at", "未知"))
    print("领取记录(rightCode 级幂等, 2026-10-12 起):")
    st = load_json(STATE_PATH, {}) or {}
    for k in sorted(st):
        if k.endswith("|ts"):
            continue
        v = st[k]
        if isinstance(v, str):
            # 旧日级格式
            print("  %s -> %s (旧日级格式)" % (k, v))
            continue
        if not isinstance(v, dict):
            continue
        n_rc = len(v.get("granted_rc") or [])
        got = v.get("granted") or []
        val = sum(g.get("value", 0) for g in got if isinstance(g, dict)) / 100.0
        print("  %s  rightCode=%d 个, 发放 %d 张 ¥%.1f, 墙总额 ¥%.1f%s  %s"
              % (k, n_rc, len(got), val, (v.get("wall_total") or 0) / 100.0,
                 " [旧数据迁移]" if v.get("legacy_done") else "", v.get("ts", "")))
        for g in got[-8:]:
            if isinstance(g, dict):
                print("     + %s ¥%.1f 满¥%.1f" % (g.get("name", "?"), g.get("value", 0) / 100.0,
                                                   g.get("limit", 0) / 100.0))
        if v.get("last_fail"):
            print("     ! 最后一次失败 %s: %s" % (v["last_fail"].get("ts"), str(v["last_fail"].get("resp"))[:120]))
    return 0


URL_MARKET_PRE = HOST + "/fulishemini/couponActivity/realTimeMarketingPreSend?" + QS
URL_MARKET_SEND = HOST + "/fulishemini/couponActivity/realTimeMarketingSendCoupon?" + QS


def try_market_coupon(cfg):
    """营销页红包（realTimeMarketing 链路, source=MARKET_PAGE）。

    反编译依据: components/coupon-area/urls.js
      realTimeMarketingPreSend (预请求) -> realTimeMarketingSendCoupon (JSON 领取)
    与 HOME 券包链路同构, 复用同一套 mtgsig 签名与公共参数。
    需要抓包过一次营销页（带 recallToken/pageId）, 否则 config 无营销页字段时优雅跳过。
    返回 0/2/3, 不影响主领券流程。
    """
    if not cfg.get("market_recall_token") and not cfg.get("recall_token"):
        print("[跳过] 营销页红包: 未配置 recallToken（需抓包一次营销页领券）")
        return 0
    print("[可选] 营销页红包 realTimeMarketing ...")
    try:
        _, dfpid = gen_mtgsig("POST", URL_MARKET_PRE, "probe=1")
        cfg["_finger_applets"] = dfpid
        body_pairs = build_body_str(cfg, 30300, extra={"requestSource": "2"})
        body_str = body_pairs
        mtgsig, _ = gen_mtgsig("POST", URL_MARKET_PRE, body_str)
        c1, t1 = http_post(
            URL_MARKET_PRE, body_str, mtgsig,
            cfg.get("openIdCipher", ""), cfg.get("open_id", ""),
            cfg.get("wm_uuid", ""), cfg.get("csecuserid", ""), cfg.get("token", ""),
        )
        print("      preSend HTTP %s resp: %s" % (c1, t1[:200]))
        if c1 != 200:
            return 2
        j1 = json.loads(t1)
        if j1.get("code") not in (0, 200, "0", "200"):
            print("      业务码: %s" % j1.get("msg", ""))
            return 2
        data1 = j1.get("data") or {}
        tabs_map = {}
        for it in (data1.get("list") or []) + (data1.get("preGrantList") or []):
            if isinstance(it, dict) and it.get("type") == 1:
                d = it.get("data") or {}
                if d.get("rightCode") and not d.get("couponViewId"):
                    tabs_map.setdefault(d.get("planCode", ""), []).append(d["rightCode"])
        tabs_arr = [{"planCode": pc, "rightCodes": rcs} for pc, rcs in tabs_map.items()]
        if not tabs_arr:
            print("      [幂等] 营销页红包均已领取")
            return 0
        full = build_grant_body(cfg, data1, tabs_arr)
        full["recallToken"] = cfg.get("market_recall_token") or cfg.get("recall_token", "")
        body_json = json.dumps(full, ensure_ascii=False, separators=(",", ":"))
        mtgsig, _ = gen_mtgsig("POST", URL_MARKET_SEND, body_json)
        c2, t2 = http_post_json(URL_MARKET_SEND, body_json, mtgsig, cfg)
        print("      sendCoupon HTTP %s resp: %s" % (c2, t2[:200]))
        ok = False
        try:
            j2 = json.loads(t2)
            ok = j2.get("code") in (0, 200, "0", "200")
        except Exception:
            ok = c2 == 200
        print("      [完成] 营销页红包领取成功" if ok else "      [未成功] 响应已存盘人工核对")
        save_json(os.path.join(BASE, "mt_market_resp.json"), {"http": c2, "body": t2[:200000]})
        return 0 if ok else 3
    except Exception as e:
        print("      [异常] %s" % e)
        return 2


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "claim":
        rc = claim()
        # 主券包完成后顺带尝试营销页红包（独立幂等，失败不影响主流程）
        cfg = load_json(CONFIG_PATH, {}) or {}
        if cfg.get("enable_market_coupon"):
            try:
                try_market_coupon(cfg)
            except Exception as e:
                print("[警告] 营销页红包异常: %s" % e)
        sys.exit(rc)
    elif cmd == "probe":
        sys.exit(probe())
    elif cmd == "share":
        cfg = load_json(CONFIG_PATH, {}) or {}
        ok, msg, data = query_share_pop(cfg)
        print("querySharePopWindow: %s %s" % ("✅" if ok else "❌", msg))
        if ok:
            print("data=%s" % json.dumps(data, ensure_ascii=False))
            print("（data=null = 无分享弹窗/无待领分享奖励）")
        sys.exit(0 if ok else 2)
    elif cmd == "market":
        sys.exit(try_market_coupon(load_json(CONFIG_PATH, {}) or {}))
    elif cmd == "dryrun":
        sys.exit(dryrun())
    elif cmd == "status":
        sys.exit(status())
    else:
        print(__doc__)
        sys.exit(1)
