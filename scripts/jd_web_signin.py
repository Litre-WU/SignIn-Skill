#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jd_web_signin.py — 京东京豆 Web 端每日签到（PC 浏览器登录态）
==============================================================
来源: 2026-10-12 自行逆向 bean.jd.com/myJingBean/list 的官方前端包还原，
     未使用任何第三方仓库实现。核心签名器直接调用京东官方下发的
     js_security_v3_0.1.4.js（Node 沙箱 + 最小 DOM shim 运行），
     保证与线上算法逐位一致。

链路（已实测跑通，2026-10-12）:
  页面   https://bean.jd.com/myJingBean/list  （SPA，老的 /bean/index 已 404）
  查询   GET  api.m.jd.com/?functionId=pc_interact_sign_query&type=1
  签到   POST api.m.jd.com/  functionId=pc_interact_sign_execute
                        body={type:5, eaId, itemId:"1", extraType:"sign"}
  挂载   POST api.m.jd.com/  functionId=pc_interact_sign_execute
                        body={type:0, eaId:"task"}   （幂等，可能送豆）

请求三件套（全部由本地 cookie 直接构造，无需远程取 token）:
  h5st            官方 js_security_v3 签名器生成（10 段分号结构）
  uuid            cookie __jda 的第二段
  area            cookie ipLoc-djd（7-527-0-0 → 7_527_0_0）
  x-api-eid-token cookie 3AB9D23F7A4B3CSS（本身即 "jdd03..." 开头，可直接用）

登录态:
  Thorium 浏览器 .jd.com 域 PC cookie（thor/pin/unick/flash/3AB9D23F7A4B3C9B/...）。
  从磁盘 Cookies 库离线提取（CreateFileW 绕独占锁 + DPAPI + AES-256-GCM），
  浏览器开着或关着都能读；每次运行都重新提取以保证新鲜。

命令行:
  python jd_web_signin.py cookie   # 重新提取浏览器 cookie → jd_web_config.json
  python jd_web_signin.py auto     # 查询→未签到则签到（幂等），发 JSON
  python jd_web_signin.py status   # 只读查询今日签到状态
  python jd_web_signin.py sign     # 强制签到（调试用）
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(BASE, "jd_web_config.json")
def find_node():
    """定位 Node.js：JD_NODE 环境变量 → 常见安装路径 → PATH 上的 node。"""
    import glob

    def shutil_which(x):
        import shutil
        return shutil.which(x)

    cands = []
    env = os.environ.get("JD_NODE")
    if env:
        cands.append(env)
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        cands += sorted(glob.glob(os.path.join(
            local, "..", "Local", ".workbuddy", "binaries", "node", "versions", "*", "node.exe")),
            reverse=True)
        cands += sorted(glob.glob(os.path.join(
            os.environ.get("USERPROFILE", ""), ".workbuddy", "binaries", "node", "versions", "*", "node.exe")),
            reverse=True)
    for p in (r"C:\Program Files\nodejs\node.exe", r"C:\Program Files (x86)\nodejs\node.exe"):
        cands.append(p)
    w = shutil_which("node")
    if w:
        cands.append(w)
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return "node"


NODE = find_node()
CLI = os.path.join(BASE, "_jd_sign_cli.js")
API = "https://api.m.jd.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/141.0.0.0 Safari/537.36")
APPID = "asset-h5"
CLIENT_VERSION = "1.0.0"
CLIENT = "pc"

# 需要出现在 Cookie 里的关键登录键（缺任一基本可判失效）
NEED_KEYS = ("thor", "pin", "flash")


# ---------------------------------------------------------------- cookie 提取
def _browser_ud():
    """浏览器 User Data 目录（thorium 优先，可用 JD_BROWSER_UD 覆盖）。"""
    env = os.environ.get("JD_BROWSER_UD")
    if env and os.path.isdir(env):
        return env
    for name in ("Thorium", "Chromium"):
        p = os.path.join(os.environ.get("LOCALAPPDATA", ""), name, "User Data")
        if os.path.isdir(p):
            return p
    return ""


def _dpapi(data):
    import ctypes
    from ctypes import wintypes, POINTER, c_char, create_string_buffer, byref, string_at

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", POINTER(c_char))]

    buf = create_string_buffer(data, len(data))
    inb = DATA_BLOB(len(data), ctypes.cast(buf, POINTER(c_char)))
    outb = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(byref(inb), None, None, None, None, 0, byref(outb)):
        return None
    s = string_at(outb.pbData, outb.cbData)
    ctypes.windll.kernel32.LocalFree(outb.pbData)
    return s


def _read_cookies_db(path):
    """读一个 Cookies SQLite 文件，返回 {name: value}（同名取最长）。"""
    import base64
    import sqlite3
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    with open(os.path.join(_browser_ud(), "Local State"), encoding="utf-8") as f:
        ls = json.load(f)
    key = _dpapi(base64.b64decode(ls["os_crypt"]["encrypted_key"])[5:])
    if not key:
        raise RuntimeError("DPAPI 解 master key 失败")
    con = sqlite3.connect(path)
    rows = con.execute(
        "SELECT host_key, name, encrypted_value FROM cookies "
        "WHERE host_key LIKE '%.jd.com' OR host_key LIKE '%jd.hk'").fetchall()
    con.close()
    best = {}
    for host, name, ev in rows:
        if not ev or ev[:3] != b"v10":
            continue
        try:
            v = AESGCM(key).decrypt(ev[3:15], ev[15:], None).decode("utf-8", "replace")
        except Exception:
            continue
        if not v:
            continue
        cur = best.get(name)
        if cur is None or len(v) > len(cur):
            best[name] = v
    return best


def _raw_read(ck_path):
    import ctypes
    import tempfile
    from ctypes import wintypes, POINTER, c_char, create_string_buffer, byref

    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.GetFileSize.argtypes = [wintypes.HANDLE, POINTER(wintypes.DWORD)]
    k32.GetFileSize.restype = wintypes.DWORD
    k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                             POINTER(wintypes.DWORD), wintypes.LPVOID]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    for attempt in range(26):                      # Chromium 独占锁，时紧时松，耐心重试
        h = k32.CreateFileW(ck_path, 0x80000000, 0x00000007, None, 3, 0, None)
        if h and h != wintypes.HANDLE(-1).value:
            size = k32.GetFileSize(h, None)
            buf = (c_char * size)()
            read = wintypes.DWORD(0)
            k32.ReadFile(h, buf, size, byref(read), None)
            k32.CloseHandle(h)
            raw = bytes(buf[:read.value])
            tmp = os.path.join(tempfile.gettempdir(), "_jd_ck.db")
            try:                                    # 顺手刷新 TEMP 缓存
                with open(tmp, "wb") as f:
                    f.write(raw)
            except OSError:
                pass
            return raw
        time.sleep(1.2)
    return None


def _cdp_cookies():
    """浏览器开着 9222 调试端口时，用 CDP Network.getAllCookies 取最新 cookie。"""
    import urllib.error
    try:
        import websocket
    except ImportError:
        return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:9222/json/list", timeout=4) as r:
            pages = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None
    target = None
    for p in pages:
        if p.get("type") == "page" and "jd.com" in (p.get("url") or ""):
            target = p
            break
    if target is None and pages:
        target = pages[0]
    if not target:
        return None
    try:
        ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=10,
                                         suppress_origin=True)
    except Exception:
        return None
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
        got = {}
        for _ in range(40):
            msg = json.loads(ws.recv())
            if msg.get("id") == 2:
                for c in msg.get("result", {}).get("cookies", []):
                    d = (c.get("domain") or "")
                    if d == ".jd.com" or d.endswith(".jd.com") or d.endswith("jd.hk"):
                        n = c.get("name")
                        v = c.get("value") or ""
                        if v and (n not in got or len(v) > len(got[n])):
                            got[n] = v
                break
        return got or None
    except Exception:
        return None
    finally:
        try:
            ws.close()
        except Exception:
            pass


def extract_cookies(verbose=False):
    """按优先级取 .jd.com 登录 cookie：磁盘直读 → TEMP 缓存 → CDP 9222。"""
    ud = _browser_ud()
    if not ud:
        raise RuntimeError("未找到浏览器 User Data 目录（设 JD_BROWSER_UD 指定）")
    ck_path = os.path.join(ud, "Default", "Network", "Cookies")

    if os.path.isfile(ck_path):
        raw = _raw_read(ck_path)
        if raw:
            if verbose:
                print("[cookie] 磁盘直读 OK %d 字节" % len(raw))
            return _read_cookies_db_bytes(raw)
        if verbose:
            print("[cookie] 磁盘被独占锁，转 TEMP 缓存 / CDP")

    tmp = os.path.join(os.environ.get("TEMP", ""), "_jd_ck.db")
    if os.path.isfile(tmp):
        try:
            ck = _read_cookies_db(tmp)
            if ck.get("thor"):
                if verbose:
                    print("[cookie] 用 TEMP 缓存（%s）" % time.strftime(
                        "%m-%d %H:%M", time.localtime(os.path.getmtime(tmp))))
                return ck
        except Exception:
            pass

    ck = _cdp_cookies()
    if ck and ck.get("thor"):
        if verbose:
            print("[cookie] 用 CDP 9222 实时读取 %d 个" % len(ck))
        return ck
    raise RuntimeError("无法读取京东 cookie（磁盘锁 + 无缓存 + 9222 未开）")


def _read_cookies_db_bytes(raw):
    import base64
    import sqlite3
    import tempfile
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    with open(os.path.join(_browser_ud(), "Local State"), encoding="utf-8") as f:
        ls = json.load(f)
    key = _dpapi(base64.b64decode(ls["os_crypt"]["encrypted_key"])[5:])
    if not key:
        raise RuntimeError("DPAPI 解 master key 失败")
    tmp = os.path.join(tempfile.gettempdir(), "_jd_web_ck_%d.db" % os.getpid())
    with open(tmp, "wb") as f:
        f.write(raw)
    try:
        con = sqlite3.connect(tmp)
        rows = con.execute(
            "SELECT host_key, name, encrypted_value FROM cookies "
            "WHERE host_key LIKE '%.jd.com' OR host_key LIKE '%jd.hk'").fetchall()
        con.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    best = {}
    for host, name, ev in rows:
        if not ev or ev[:3] != b"v10":
            continue
        try:
            v = AESGCM(key).decrypt(ev[3:15], ev[15:], None).decode("utf-8", "replace")
        except Exception:
            continue
        if not v:
            continue
        cur = best.get(name)
        if cur is None or len(v) > len(cur):
            best[name] = v
    return best


def load_cfg():
    if os.path.isfile(CFG):
        with open(CFG, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cfg(cookies):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies, "ts": int(time.time())}, f, ensure_ascii=False)


def ensure_cookies(verbose=False):
    """取最新 cookie；取不到则退回已保存配置（标记 stale）。返回 (cookies, stale)。"""
    try:
        ck = extract_cookies(verbose)
        save_cfg(ck)
        return ck, False
    except Exception as e:
        ck = (load_cfg().get("cookies") or {})
        if ck.get("thor"):
            if verbose:
                print("[cookie] 实时提取失败(%s)，退回已保存配置" % e)
            return ck, True
        raise


# ---------------------------------------------------------------- h5st 签名
def node_sign(function_id, body):
    """调京东官方 js_security_v3 签名器，返回 (t, h5st)。"""
    if not os.path.isfile(CLI):
        raise RuntimeError("签名器 CLI 缺失: %s" % CLI)
    if not (os.path.isfile(NODE) or shutil_which(NODE)):
        raise RuntimeError("未找到 Node.js（设 JD_NODE 指定 node.exe 路径）")
    out = subprocess.run([NODE, CLI, function_id, json.dumps(body, separators=(",", ":"))],
                         capture_output=True, text=True, timeout=180, cwd=BASE)
    if out.returncode != 0:
        raise RuntimeError("h5st 签名失败: %s %s" % (out.stdout[-300:], out.stderr[-600:]))
    line = out.stdout.strip().splitlines()[-1]
    r = json.loads(line)
    return r["input"]["t"], r["h5st"]


# ---------------------------------------------------------------- HTTP
def _req(function_id, body, method):
    cookies, stale = ensure_cookies()
    miss = [k for k in NEED_KEYS if not cookies.get(k)]
    if miss:
        raise RuntimeError("登录态不完整，缺 cookie: %s（浏览器登录京东后跑 jd_web_signin.py cookie）" % ",".join(miss))

    jda = cookies.get("__jda", "")
    uuid_ = jda.split(".")[1] if jda.count(".") >= 1 else ""
    area = (cookies.get("ipLoc-djd") or "").replace("-", "_").split(".")[0]
    eid = cookies.get("3AB9D23F7A4B3CSS") or ("jdd03" + cookies.get("3AB9D23F7A4B3C9B", ""))
    if not uuid_:
        raise RuntimeError("cookie __jda 缺失，无法取 uuid")

    t, hs = node_sign(function_id, body)
    params = {
        "h5st": hs,
        "uuid": uuid_,
        "loginType": 3,
        "appid": APPID,
        "clientVersion": CLIENT_VERSION,
        "client": CLIENT,
        "t": t,
        "body": json.dumps(body, separators=(",", ":")),
        "functionId": function_id,
        "x-api-eid-token": eid,
        "area": area,
    }
    cookie_line = "; ".join("%s=%s" % (k, v) for k, v in cookies.items())

    if method == "get":
        url = API + "?" + urllib.parse.urlencode(params)
        data = None
    else:
        url = API
        data = urllib.parse.urlencode(params).encode("utf-8")

    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("User-Agent", UA)
    req.add_header("Cookie", cookie_line)
    req.add_header("Referer", "https://bean.jd.com/myJingBean/list")
    req.add_header("Origin", "https://bean.jd.com")
    req.add_header("Accept", "application/json, text/plain, */*")
    req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
    if method == "post":
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def api(function_id, body, method):
    st, txt = _req(function_id, body, method)
    try:
        return st, json.loads(txt)
    except Exception:
        return st, {"_raw": txt[:800]}


# ---------------------------------------------------------------- 业务
def query():
    return api("pc_interact_sign_query", {"type": 1}, "get")


def today_str():
    return time.strftime("%Y-%m-%d", time.localtime())


def parse_sign_state(data):
    """从 query 响应解析今日签到状态。"""
    if not data.get("success"):
        return {"ok": False, "msg": "查询失败: %s" % json.dumps(data, ensure_ascii=False)[:300]}
    d = data.get("data") or {}
    lst = d.get("assignmentInfoList") or []
    sign = None
    for a in lst:
        if a.get("extraType") == "sign" or a.get("type") == 5:
            sign = a
            break
    if not sign:
        return {"ok": False, "msg": "未找到签到任务（assignmentInfoList 空）", "raw": d}
    sd = sign.get("signDetail") or {}
    sign_list = sd.get("signList") or []
    td = today_str()
    signed_today = any(str(x).startswith(td) for x in sign_list)
    done = bool(sign.get("completionFlag")) or signed_today or sd.get("status") == 2
    return {
        "ok": True,
        "eaId": sign.get("id"),
        "name": sign.get("name"),
        "done": done,
        "completionFlag": sign.get("completionFlag"),
        "completionCnt": sign.get("completionCnt"),
        "status": sd.get("status"),
        "continueSignDay": sd.get("continueSignDay"),
        "signList": sign_list,
        "activityId": (d.get("resourceData") or {}).get("activityId"),
    }


# errCode → 中文含义（来自 index-legacy 前端错误表）
ERR_MSG = {
    "-1": "出了一点儿小问题，请重试",
    "-1000": "活动太火爆，请稍后再来哦~",
    "-100": "请先登录哦~",
    "3": "请先登录哦~",
    "101": "活动太火爆，请稍后再来~",
    "102": "活动太火爆，请稍后再来~",
    "201": "服务器跟不上你啦，请稍后重试哦~",
    "300": "活动太火爆了，请稍后再来",
    "301": "活动太火爆了，请稍后重试~",
    "302": "任务已经完成",
    "303": "任务不能重复执行哦",
    "304": "抽奖次数不足",
    "305": "任务领取成功",
    "306": "任务已经领取过",
    "307": "倒计时任务还没有领取哦",
    "308": "浏览时间不足哦",
    "309": "您还有未完成的任务哦",
    "310": "啊哦，您可能穿越了，请稍后重试哦~",
    "401": "啊哦，活动太火爆了，请稍后重试吧~",
    "999": "请刷新页面，稍后重试~",
}


def _code_of(resp):
    if not isinstance(resp, dict):
        return None
    c = resp.get("errCode", resp.get("code"))
    return None if c is None else str(c)


def _is_login_err(resp):
    c = _code_of(resp)
    return c in ("3", "-100") or (isinstance(resp, dict) and resp.get("code") == "3")


def execute(body):
    return api("pc_interact_sign_execute", body, "post")


def sum_beans(resp):
    """从 execute 响应提取京豆数。"""
    if not isinstance(resp, dict):
        return 0
    if resp.get("success") is False:
        return 0
    d = resp.get("data") or resp
    awi = d.get("assignmentRewardInfo") or {}
    total = 0
    for r in awi.get("jingDouRewards") or []:
        try:
            total += int(r.get("quantity") or 0)
        except Exception:
            pass
    return total


def run_auto(force=False):
    res = {"ts": int(time.time())}
    st, q = query()
    if st != 200:
        return {"ok": False, "state": "http_%s" % st, "msg": json.dumps(q, ensure_ascii=False)[:300]}
    if _is_login_err(q):
        return {"ok": False, "state": "login_expired",
                "msg": "京东登录态失效（服务端 code=3 请先登录）：请在 Thorium 浏览器打开 jd.com 重新登录，"
                       "下次运行会自动读取新 cookie"}
    stt = parse_sign_state(q)
    if not stt.get("ok"):
        return {"ok": False, "state": "query_bad", "msg": stt.get("msg")}
    res.update({
        "eaId": stt["eaId"], "activityId": stt["activityId"],
        "continueSignDay": stt["continueSignDay"], "done_before": stt["done"],
    })
    if stt["done"] and not force:
        res.update({"ok": True, "state": "already", "beans": 0,
                    "msg": "今日已签到（连签 %s 天）" % stt.get("continueSignDay")})
        return res

    # 挂载任务（type:0 eaId:task）幂等，可能送豆
    st2, r2 = execute({"type": 0, "eaId": "task"})
    mount_beans = sum_beans(r2)
    res["mount"] = {"code": (r2 or {}).get("errCode"), "msg": (r2 or {}).get("errMessage"),
                    "beans": mount_beans}

    # 正式签到
    st3, r3 = execute({"type": 5, "eaId": stt["eaId"], "itemId": "1", "extraType": "sign"})
    code = _code_of(r3)
    msg = (r3 or {}).get("errMessage") or ERR_MSG.get(code, "")
    beans = sum_beans(r3)
    res["sign"] = {"code": code, "msg": msg, "beans": beans}

    if _is_login_err(r3):
        res.update({"ok": False, "state": "login_expired",
                    "msg": "京东登录态失效（服务端 code=3 请先登录）：请在 Thorium 浏览器打开 jd.com 重新登录"})
    elif code == "302" or "已完成" in msg:
        res.update({"ok": True, "state": "already", "beans": 0,
                    "msg": "今日已签到（服务端返回任务已完成）"})
    elif beans > 0:
        res.update({"ok": True, "state": "signed", "beans": beans + mount_beans,
                    "msg": "签到成功 +%d 京豆" % (beans + mount_beans)})
    elif (r3 or {}).get("success") is True:
        res.update({"ok": True, "state": "signed", "beans": mount_beans,
                    "msg": "签到成功（未解析到京豆数）"})
    else:
        res.update({"ok": False, "state": "sign_failed",
                    "msg": "签到返回: code=%s msg=%s" % (code, msg or json.dumps(r3, ensure_ascii=False)[:300])})
    return res


def run_status():
    st, q = query()
    if st != 200:
        return {"ok": False, "state": "http_%s" % st, "msg": json.dumps(q, ensure_ascii=False)[:300]}
    if _is_login_err(q):
        return {"ok": False, "state": "login_expired",
                "msg": "京东登录态失效：请在 Thorium 浏览器打开 jd.com 重新登录"}
    stt = parse_sign_state(q)
    if not stt.get("ok"):
        return {"ok": False, "state": "query_bad", "msg": stt.get("msg")}
    return {"ok": True, "done": stt["done"], "continueSignDay": stt["continueSignDay"],
            "completionCnt": stt["completionCnt"], "signList": stt["signList"],
            "eaId": stt["eaId"], "name": stt["name"]}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if cmd == "cookie":
        try:
            ck = extract_cookies(verbose=True)
        except Exception as e:
            print("[fail] %s" % e)
            sys.exit(3)
        save_cfg(ck)
        miss = [k for k in NEED_KEYS if not ck.get(k)]
        print("已提取 %d 个 cookie → %s" % (len(ck), CFG))
        print("登录键: %s" % {k: (ck.get(k, "")[:10] + "...") for k in
                            ("thor", "pin", "unick", "flash", "3AB9D23F7A4B3C9B", "3AB9D23F7A4B3CSS")})
        if miss:
            print("[warn] 缺少关键 cookie: %s（浏览器可能未登录京东）" % ",".join(miss))
            sys.exit(3)
        return
    if cmd == "auto":
        r = run_auto()
    elif cmd == "sign":
        r = run_auto(force=True)
    elif cmd == "status":
        r = run_status()
    else:
        print("未知命令: %s（支持 cookie/auto/status/sign）" % cmd)
        sys.exit(2)
        return
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0 if r.get("ok") else 1)


if __name__ == "__main__":
    main()
