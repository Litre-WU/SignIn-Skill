#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美团福利社领券 · 纯接口版 (mtgsig 沙箱还原方案)
================================================
方案: 在 Node 沙箱中运行逆向提取的 wx-jsguard 签名模块(原算法, 非重放),
     每次请求实时生成新鲜 mtgsig → Python 发起真实领券请求。

链路: listActivityCoupon(30300 预请求) -> grantActivityCoupon(30301 领取)

用法:
  python mt_api_coupon.py dryrun    # 仅生成签名+打印请求体(不发网络)
  python mt_api_coupon.py claim     # 执行领券(幂等)
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


def claim():
    cfg = load_json(CONFIG_PATH, {}) or {}
    ok, missing = check_config(cfg)
    if not ok:
        print("[失败] mt_config.json 缺少字段: %s" % ", ".join(missing))
        print("  (openIdCipher/csecuserid/token 等取自抓包请求头, 已在 analyze 时记录)")
        return 1

    state = load_json(STATE_PATH, {}) or {}
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get(today) == "done":
        print("[幂等跳过] 今日(%s)已领过。删除 mt_claim_state.json 可重跑。" % today)
        return 0

    print("=" * 62)
    print("美团福利社领券(API+沙箱签名) %s" % datetime.now().strftime("%F %T"))
    print("=" * 62)

    def send(url, psub, extra=None):
        # 先生成一次拿 dfpid(finger_applets) -> 注入 body -> 再对最终 body 签名
        _, dfpid = gen_mtgsig("POST", url, "probe=1")
        cfg["_finger_applets"] = dfpid
        body_str = build_body_str(cfg, psub, extra)
        mtgsig, _ = gen_mtgsig("POST", url, body_str)
        code, text = http_post(
            url, body_str, mtgsig,
            cfg.get("openIdCipher", ""), cfg.get("open_id", ""),
            cfg.get("wm_uuid", ""), cfg.get("csecuserid", ""), cfg.get("token", ""),
        )
        return code, text, mtgsig[:60]

    # 1) 预请求
    print("[1/2] listActivityCoupon (30300) ...")
    c1, t1, s1 = send(URL_LIST, 30300)
    print("      HTTP %s mtgsig=%s..." % (c1, s1))
    print("      resp: %s" % t1[:400])
    save_json(os.path.join(BASE, "mt_list_resp.json"), {"http": c1, "body": t1[:200000]})
    if c1 != 200:
        print("[中断] 预请求 HTTP %s — 签名未通过或登录态失效。" % c1)
        return 2
    try:
        j1 = json.loads(t1)
        if j1.get("code") not in (0, 200, "0", "200"):
            print("[中断] 业务码异常: %s" % j1.get("msg", ""))
            return 2
    except Exception:
        pass

    # 2) 领取 (JSON content-type, 复刻 urls.js grantActivityCoupon 定义)
    print("[2/2] grantActivityCoupon (30301, JSON) ...")
    try:
        j1 = json.loads(t1)
        data1 = j1.get("data", {})
        cfg_conf = data1.get("config", {})
    except Exception:
        data1, cfg_conf = {}, {}

    # tabs: 复刻 getNeedFetchTabs — list+preGrantList 中 type=1 且有 rightCode(无 couponViewId) 按 planCode 分组
    # (已领过的券会带 couponViewId, 自动排除; 全部已领时 tabs 为空数组也照发, 服务端幂等)
    tabs_map = {}
    for it in (data1.get("list") or []) + (data1.get("preGrantList") or []):
        if isinstance(it, dict) and it.get("type") == 1:
            d = it.get("data") or {}
            if d.get("rightCode") and not d.get("couponViewId"):
                tabs_map.setdefault(d.get("planCode", ""), []).append(d["rightCode"])
    tabs_arr = [{"planCode": pc, "rightCodes": rcs} for pc, rcs in tabs_map.items()]
    print("      可领取 tabs: %d 组 / rightCodes: %d 个"
          % (len(tabs_arr), sum(len(t["rightCodes"]) for t in tabs_arr)))
    if not tabs_arr:
        print("[幂等] 今日券均已领取 (所有券已带 couponViewId)。")
        state[today] = "done"
        state["%s|ts" % today] = datetime.now().strftime("%F %T")
        save_json(STATE_PATH, state)
        return 0

    # 组 JSON body (与真实抓包逐字段对齐, 见 build_grant_body 注释)
    full = build_grant_body(cfg, data1, tabs_arr)
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
        state[today] = "done"
        state["%s|ts" % today] = datetime.now().strftime("%F %T")
        save_json(STATE_PATH, state)
        print("[完成] 领取成功 ✅  今日已记录幂等。")
    else:
        print("[未成功] 服务端未确认领取, 响应已存盘人工核对 (可能今日已领/库存空/风控)。")
    log("claim http1=%s http2=%s success=%s" % (c1, c2, success))
    return 0 if success else 3


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
    print("领取记录:")
    st = load_json(STATE_PATH, {}) or {}
    for k, v in sorted(st.items()):
        print("  %s -> %s" % (k, v))
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
    elif cmd == "market":
        sys.exit(try_market_coupon(load_json(CONFIG_PATH, {}) or {}))
    elif cmd == "dryrun":
        sys.exit(dryrun())
    elif cmd == "status":
        sys.exit(status())
    else:
        print(__doc__)
        sys.exit(1)
