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


COOKIE_SRC = {"name": "", "age_min": 0}   # 本次 cookie 到底从哪拿到的（判读要用）


def _esentutl_copy(src, dst):
    """用 esentutl 备份语义复制被 Chromium 独占锁的 Cookies 库。

    ★2026-10-15 实测纠正旧结论："esentutl 100% 可复制"只在**浏览器没在跑**时成立：
      Thorium 运行时它回 `-1032 JET_errFileAccessDenied`，加 /v 还会挂死；
      robocopy /B、cmd copy、Python open 同样"另一个程序正在使用此文件"。
      所以这里必须带短超时并**把失败原因带出来**（旧版静默 False → 上层悄悄退回陈旧快照，
      表现为"明明刚重新登录却一直 login_expired"）。返回 (ok, 说明)。
    """
    import subprocess
    try:
        if os.path.isfile(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        r = subprocess.run(["esentutl.exe", "/y", src, "/d", dst, "/o"],
                           capture_output=True, text=True, timeout=20)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
            return True, "复制 %dB" % os.path.getsize(dst)
        tail = " | ".join(l.strip() for l in out.splitlines() if l.strip())[-160:]
        return False, "rc=%s %s" % (r.returncode, tail or "无输出")
    except subprocess.TimeoutExpired:
        return False, "esentutl 20s 超时（锁未释放）"
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e)[:120])


def _raw_read(ck_path, verbose=False):
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

    for attempt in range(3):                        # 独占锁不会因为多等 10s 就放开，3 次足够
        h = k32.CreateFileW(ck_path, 0x80000000, 0x00000007, None, 3, 0, None)
        if h and h != wintypes.HANDLE(-1).value:
            size = k32.GetFileSize(h, None)
            buf = (c_char * size)()
            read = wintypes.DWORD(0)
            k32.ReadFile(h, buf, size, byref(read), None)
            k32.CloseHandle(h)
            raw = bytes(buf[:read.value])
            _refresh_tmp_cache(raw)
            return raw
        time.sleep(1.2)

    # 快路径失败 → esentutl 备份语义（失败也不再静默，把原因留给 verbose/上层）
    snap = os.path.join(tempfile.gettempdir(), "_jd_ck_vss.db")
    ok, why = _esentutl_copy(ck_path, snap)
    if verbose:
        print("[cookie] 直读失败(%s)，原因：%s" % ("独占锁 err=32", why))
    if ok:
        try:
            with open(snap, "rb") as f:
                raw = f.read()
            _refresh_tmp_cache(raw)
            return raw
        except OSError:
            pass
    return None


def _refresh_tmp_cache(raw):
    """把最新 Cookies 快照写入 TEMP 缓存，同时解除 manual 配置的短路条件。"""
    import tempfile
    try:
        with open(os.path.join(tempfile.gettempdir(), "_jd_ck.db"), "wb") as f:
            f.write(raw)
    except OSError:
        pass


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
    """取 .jd.com 登录 cookie，按**新鲜度**排序的三级来源：
      1) CDP 9222 实时读（唯一能在浏览器开着时拿到"刚刚登录"的新 cookie）
      2) 磁盘直读（浏览器没在跑时可用；跑着会被独占锁挡住）
      3) TEMP 快照（可能陈旧，调用方据此改判读，不要一律当"用户没登录"）
    ★2026-10-15 实测纠正：Thorium 在跑时 Cookies 库谁都拷不动 —— CreateFileW(SHARE_ALL)、
      esentutl /y（JET_errFileAccessDenied -1032，/v 还会直接挂死）、robocopy /B、cmd copy
      全部失败，所以"esentutl 100% 可复制"只对"浏览器没开着"的场景成立。
    """
    ud = _browser_ud()
    if not ud:
        raise RuntimeError("未找到浏览器 User Data 目录（设 JD_BROWSER_UD 指定）")
    ck_path = os.path.join(ud, "Default", "Network", "Cookies")

    ck = _cdp_cookies()
    if ck and ck.get("thor"):
        COOKIE_SRC.update(name="cdp", age_min=0)
        if verbose:
            print("[cookie] CDP 9222 实时读取 %d 个" % len(ck))
        return ck

    if os.path.isfile(ck_path):
        raw = _raw_read(ck_path, verbose=verbose)
        if raw:
            COOKIE_SRC.update(name="disk", age_min=0)
            if verbose:
                print("[cookie] 磁盘直读 OK %d 字节" % len(raw))
            return _read_cookies_db_bytes(raw)

    tmp = os.path.join(os.environ.get("TEMP", ""), "_jd_ck.db")
    if os.path.isfile(tmp):
        try:
            ck = _read_cookies_db(tmp)
            if ck.get("thor"):
                age = int((time.time() - os.path.getmtime(tmp)) / 60)
                COOKIE_SRC.update(name="temp_cache", age_min=age)
                if verbose:
                    print("[cookie] 浏览器在跑、cookie 库拷不动 → 退回 TEMP 快照（%d 分钟前，"
                          "%s）；刚重新登录过的话这个快照是旧的"
                          % (age, time.strftime("%m-%d %H:%M",
                                                time.localtime(os.path.getmtime(tmp)))))
                return ck
        except Exception:
            pass

    raise RuntimeError("无法读取京东 cookie（9222 未开 + 磁盘独占锁 + 无 TEMP 快照）")


def stale_hint():
    """login_expired 时的判读纠正：陈旧快照导致的失效不是用户没登录。"""
    if COOKIE_SRC.get("name") == "temp_cache" and COOKIE_SRC.get("age_min", 0) > 5:
        return ("；但本次用的是 %d 分钟前的磁盘快照 —— Thorium 正在运行时 Cookies 库被独占锁"
                "（esentutl / robocopy /B / cmd copy 实测都拷不动），若你刚重新登录过，"
                "请**关掉 Thorium 再跑一次**，或用 `thorium.exe --remote-debugging-port=9222` "
                "启动后重跑，别误判成未登录" % COOKIE_SRC["age_min"])
    return ""


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


def save_cfg(cookies, manual=False):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies, "ts": int(time.time()),
                   "manual": bool(manual)}, f, ensure_ascii=False)


def ensure_cookies(verbose=False):
    """取最新 cookie；取不到则退回已保存配置（标记 stale）。返回 (cookies, stale)。

    优先级（时间戳感知）：
      1. 手动配置（用户抓包写入，manual=true）比 TEMP 缓存新 → 直接用配置
         （避免陈旧的 TEMP 缓存把新鲜抓包盖掉——2026-10-12 实测踩坑；
          每日自动提取的配置不带 manual 标记，不会拦截磁盘直读）
      2. 磁盘直读 → TEMP 缓存 → CDP 9222
      3. 全部失败 → 退回已存配置（stale=True）
    """
    cfg = load_cfg()
    cfg_ck = cfg.get("cookies") or {}
    cfg_ts = cfg.get("ts") or 0
    tmp = os.path.join(os.environ.get("TEMP", ""), "_jd_ck.db")
    tmp_ts = int(os.path.getmtime(tmp)) if os.path.isfile(tmp) else 0
    # manual 短路必须带 TTL：否则「配置比 TEMP 缓存新」这个条件一旦成立就永远成立
    # （TEMP 缓存只在磁盘直读成功时刷新，而短路会让磁盘直读根本不执行 → 死锁）。
    # 2026-10-14 实测踩坑：10-12 的 manual 配置把 10-14 重新登录的新 cookie 挡了两天。
    MANUAL_TTL = 6 * 3600
    fresh = (time.time() - cfg_ts) < MANUAL_TTL
    if cfg_ck.get("thor") and cfg.get("manual") and fresh and cfg_ts > tmp_ts:
        if verbose:
            print("[cookie] 用手动配置（%s，新于 TEMP 缓存 %s）" % (
                time.strftime("%m-%d %H:%M", time.localtime(cfg_ts)),
                time.strftime("%m-%d %H:%M", time.localtime(tmp_ts)) if tmp_ts else "无"))
        return cfg_ck, False
    try:
        ck = extract_cookies(verbose)
        save_cfg(ck)
        return ck, False
    except Exception as e:
        if cfg_ck.get("thor"):
            if verbose:
                print("[cookie] 实时提取失败(%s)，退回已保存配置" % e)
            return cfg_ck, True
        raise


# ---------------------------------------------------------------- h5st 签名
def node_sign(function_id, body, req_appid="asset-h5", sign_appid="73c2f"):
    """调京东官方 js_security_v3 签名器，返回 (t, h5st)。

    req_appid  = 请求参数里的 appid（京豆 asset-h5 / 互动中心 pc_interact_center）
    sign_appid = PSign 的 appId，即 h5st 第 3 段（京豆 73c2f / 互动中心 9a92f）
    两者是不同东西，抓包实测确认，不要混为一个。
    """
    if not os.path.isfile(CLI):
        raise RuntimeError("签名器 CLI 缺失: %s" % CLI)
    if not (os.path.isfile(NODE) or shutil_which(NODE)):
        raise RuntimeError("未找到 Node.js（设 JD_NODE 指定 node.exe 路径）")
    out = subprocess.run([NODE, CLI, function_id, json.dumps(body, separators=(",", ":")),
                          req_appid, sign_appid],
                         capture_output=True, text=True, timeout=180, cwd=BASE)
    if out.returncode != 0:
        raise RuntimeError("h5st 签名失败: %s %s" % (out.stdout[-300:], out.stderr[-600:]))
    line = out.stdout.strip().splitlines()[-1]
    r = json.loads(line)
    return r["input"]["t"], r["h5st"]


# ---------------------------------------------------------------- HTTP
_LAST_CALL = [0.0]


def _throttle(gap=4.0):
    """请求节流：京东 WAF 按端点频率限制（实测连打即 403），统一间隔。"""
    dt = time.time() - _LAST_CALL[0]
    if 0 < dt < gap:
        time.sleep(gap - dt)
    _LAST_CALL[0] = time.time()


def _req(function_id, body, method, appid=None, sign_appid=None,
         referer=None, origin=None):
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

    req_appid = appid or APPID
    sign_id = sign_appid or "73c2f"
    ref = referer or "https://bean.jd.com/myJingBean/list"
    org = origin or "https://bean.jd.com"

    t, hs = node_sign(function_id, body, req_appid, sign_id)
    params = {
        "h5st": hs,
        "uuid": uuid_,
        "loginType": 3,
        "appid": req_appid,
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
    req.add_header("Referer", ref)
    req.add_header("Origin", org)
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
                       "下次运行会自动读取新 cookie" + stale_hint()}
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
                    "msg": "京东登录态失效（服务端 code=3 请先登录）：请在 Thorium 浏览器打开 jd.com 重新登录"
                           + stale_hint()})
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
                "msg": "京东登录态失效：请在 Thorium 浏览器打开 jd.com 重新登录" + stale_hint()}
    stt = parse_sign_state(q)
    if not stt.get("ok"):
        return {"ok": False, "state": "query_bad", "msg": stt.get("msg")}
    return {"ok": True, "done": stt["done"], "continueSignDay": stt["continueSignDay"],
            "completionCnt": stt["completionCnt"], "signList": stt["signList"],
            "eaId": stt["eaId"], "name": stt["name"]}


# ================================================================
# 互动中心（interact.jd.com，PC 端「天天抽奖」转盘）
# ================================================================
# 2026-10-12 自行逆向 interact.jd.com 官方前端包
# （storage.360buyimg.com/channel2022/jd-interactive-center/index-legacy-*.js）还原。
# 注意与京豆是两套 appid：
#   请求参数 appid = pc_interact_center；PSign appId（h5st 第3段）= 9a92f
#   （京豆是 asset-h5 / 73c2f，切勿混用）
#
# 接口（全部实测跑通）:
#   奖励查询  GET  pc_interact_reward_query   body={type:0, rk:false}
#             → data={total, used, usable, nexp}（usable=可抽奖次数）
#   任务列表  GET  pc_interact_assign_query   body={type:1}
#             → data.assignmentInfoList[]（每项 id/type/extraType/completionFlag/...）
#   抽奖信息  GET  pc_interact_assign_query   body={type:0}
#             → data.lotteryDrawInfo / data.initCompletionInfo / data.resourceData
#   最近获奖  GET  pc_interact_assign_query   body={type:3} → data.recentRewardList
#   做任务    POST pc_interact_assign_execute
#             body={eaId, type, itemId, extraType, rk, actionType}
#             → data.assignmentRewardInfo.virtualPointReward.quantity（抽奖次数+N）
#   抽奖      POST pc_interact_assign_execute
#             body={rk:false, eaId, type:30}
#             → data.assignmentRewardInfo.couponRewards[]（红包/优惠券/京豆）
#
# errCode: 302 任务已完成 / 303 不能重复 / 304 抽奖次数不足 / 305 领取成功 /
#          306 已领过 / 309 有未完成任务 / 999 刷新重试
#
# ★ WAF 按端点频率限制（实测连打同端点即 HTTP 403 空响应），已内置节流；
#   403 时优雅降级不中断（换端点或等次日）。

INTERACT_APPID = "pc_interact_center"
INTERACT_SIGN_APPID = "9a92f"
INTERACT_REFERER = "https://interact.jd.com/"
ISTATE = os.path.join(BASE, "jd_interact_state.json")

# 2026-10-12 抓包实测 eaId（活动实例 id，服务端可能轮换，state 文件会动态更新）
LOTTERY_EAID_DEFAULT = "Xjwi1vL7vuSJAyHWU6HVXV6MEfh"   # 天天抽奖转盘
SIGN_TASK_EAID_DEFAULT = "TLBebEJwk4ADHLtRfDsRcV4UvS1"  # 互动中心签到任务（送抽奖机会）

# 可自动做的任务类型（order=需真实下单，不做；followShop/productsInfo/shoppingActivity/sign 可自动）
AUTO_TASK_EXTRA_TYPES = ("sign", "followShop", "productsInfo", "shoppingActivity")
# 浏览类任务用 actionType:0（模拟自动触发），其余用 1（模拟点击）
BROWSE_EXTRA_TYPES = ("productsInfo", "shoppingActivity")


def load_istate():
    if os.path.isfile(ISTATE):
        try:
            with open(ISTATE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_istate(st):
    st["ts"] = int(time.time())
    with open(ISTATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def _is_waf_blocked(st):
    """HTTP 403 空响应 = WAF 频率限制（京东按端点限流）。"""
    return st == 403


def interact_api(function_id, body, method="get"):
    """互动中心通用调用（自动带 pc_interact_center/9a92f + 节流 + JSON 解析）。"""
    _throttle(4.0)
    st, txt = _req(function_id, body, method,
                   appid=INTERACT_APPID, sign_appid=INTERACT_SIGN_APPID,
                   referer=INTERACT_REFERER, origin=INTERACT_REFERER)
    try:
        return st, json.loads(txt)
    except Exception:
        return st, {"_raw": txt[:500]}


def interact_reward():
    """抽奖机会查询 → {total, used, usable, nexp} 或 None。"""
    st, r = interact_api("pc_interact_reward_query", {"type": 0, "rk": False})
    if _is_waf_blocked(st):
        return {"_blocked": True}
    if isinstance(r, dict) and r.get("success"):
        return r.get("data") or {}
    return {"_raw": r if not isinstance(r, dict) else json.dumps(r, ensure_ascii=False)[:200]}


def interact_assign_query(qtype):
    """任务列表(type:1)/抽奖信息(type:0)/最近获奖(type:3)。"""
    st, r = interact_api("pc_interact_assign_query", {"type": qtype})
    if _is_waf_blocked(st):
        return {"_blocked": True}
    if isinstance(r, dict) and r.get("success"):
        return r.get("data") or {}
    return {"_raw": r if not isinstance(r, dict) else json.dumps(r, ensure_ascii=False)[:200]}


def _task_item_id(task):
    """复刻前端 x(task)：从各类 detail 里取 itemId。"""
    sd = task.get("signDetail")
    if sd and sd.get("itemId"):
        return str(sd["itemId"])
    for key in ("productList", "activityChannelList", "shopList"):
        lst = task.get(key) or []
        for it in lst:
            if it.get("status") == 1 and it.get("itemId"):
                return str(it["itemId"])
    od = task.get("orderDetail")
    if od and od.get("itemId"):
        return str(od["itemId"])
    return "1"


def interact_do_task(task):
    """执行单个任务 → {code, msg, gain}（gain=获得的抽奖机会数）。"""
    extra = task.get("extraType") or ""
    action = 0 if extra in BROWSE_EXTRA_TYPES else 1
    body = {
        "eaId": task.get("id") or task.get("eaId"),
        "type": task.get("type", 5),
        "itemId": _task_item_id(task),
        "extraType": extra,
        "rk": bool(task.get("rk", False)),
        "actionType": action,
    }
    st, r = interact_api("pc_interact_assign_execute", body, "post")
    if _is_waf_blocked(st):
        return {"code": "403", "msg": "WAF 限流", "gain": 0}
    code = _code_of(r)
    msg = (r or {}).get("errMessage") or ERR_MSG.get(code, "")
    gain = 0
    awi = ((r or {}).get("data") or {}).get("assignmentRewardInfo") or {}
    vp = awi.get("virtualPointReward") or {}
    try:
        gain = int(vp.get("quantity") or 0)
    except Exception:
        pass
    return {"code": code, "msg": msg, "gain": gain, "success": (r or {}).get("success")}


def parse_lottery_reward(resp):
    """解析抽奖奖励 → 人类可读字符串 + 结构化列表。"""
    awi = ((resp or {}).get("data") or {}).get("assignmentRewardInfo") or {}
    items = []
    for c in awi.get("couponRewards") or []:
        items.append({
            "kind": "coupon", "name": c.get("rewardName") or "券",
            "quota": c.get("quota"), "threshold": c.get("usageThreshold"),
            "range": c.get("useRange"), "time": c.get("useTimeRange"),
            "couponId": c.get("couponId"),
        })
    for j in awi.get("jingDouRewards") or []:
        items.append({"kind": "bean", "name": "京豆", "quantity": j.get("quantity")})
    vp = awi.get("virtualPointReward") or {}
    if vp.get("quantity"):
        items.append({"kind": "chance", "name": "抽奖机会", "quantity": vp.get("quantity")})
    if not items:
        keys = awi.get("keys") or []
        name_map = awi.get("localRewardNameMap") or {}
        for k in keys:
            items.append({"kind": "key%s" % k, "name": name_map.get(str(k)) or "奖品%s" % k})
    return items


def interact_draw(ea_id):
    """抽奖一次 → {code, msg, items, success}。"""
    st, r = interact_api("pc_interact_assign_execute",
                         {"rk": False, "eaId": ea_id, "type": 30}, "post")
    if _is_waf_blocked(st):
        return {"code": "403", "msg": "WAF 限流", "items": []}
    code = _code_of(r)
    msg = (r or {}).get("errMessage") or ERR_MSG.get(code, "")
    items = parse_lottery_reward(r) if (r or {}).get("success") else []
    return {"code": code, "msg": msg, "items": items, "success": (r or {}).get("success")}


def _reward_text(items):
    parts = []
    for it in items:
        if it.get("kind") == "coupon":
            parts.append("%s%.0f元(满%.0f可用,%s)" % (
                it.get("name") or "券", it.get("quota") or 0,
                it.get("threshold") or 0, it.get("time") or ""))
        elif it.get("kind") == "bean":
            parts.append("京豆x%s" % it.get("quantity"))
        elif it.get("kind") == "chance":
            parts.append("抽奖机会+%s" % it.get("quantity"))
        else:
            parts.append(it.get("name") or "奖品")
    return "、".join(parts) if parts else "无"


def run_interact_auto(force=False):
    """互动中心每日流程：查机会 → 抽奖 → 做任务 → 再抽奖。发 JSON。"""
    res = {"ts": int(time.time()), "draws": [], "tasks": []}
    state = load_istate()
    lottery_eaid = state.get("lottery_eaId") or LOTTERY_EAID_DEFAULT

    # 1) 抽奖机会
    rw = interact_reward()
    if rw.get("_blocked"):
        res.update({"ok": False, "state": "waf_blocked",
                    "msg": "reward_query 被 WAF 限流(403)，稍后再试"})
        return res
    if "_raw" in rw:
        res.update({"ok": False, "state": "reward_bad", "msg": str(rw.get("_raw"))[:200]})
        return res
    usable = int(rw.get("usable") or 0)
    res["reward"] = {"total": rw.get("total"), "used": rw.get("used"), "usable": usable}

    # 2) 抽奖（把现有机会抽完）
    drawn = 0
    while usable > 0 and drawn < 30:
        d = interact_draw(lottery_eaid)
        res["draws"].append(d)
        drawn += 1
        if d.get("code") == "403":
            res["waf_blocked"] = True
            break
        if d.get("success"):
            usable -= 1
            res.setdefault("rewards", []).append(_reward_text(d.get("items") or []))
            continue
        code = d.get("code")
        if code in ("304",):       # 抽奖次数不足
            break
        if code in ("302", "303", "305", "306"):
            usable -= 1
            continue
        if code in ("3", "-100"):
            res.update({"ok": False, "state": "login_expired",
                        "msg": "京东登录态失效：请在 Thorium 重新登录 jd.com" + stale_hint()})
            return res
        # 其他错误（如 999 火爆）停止重试，避免触发风控
        res["draw_note"] = "code=%s %s" % (code, d.get("msg"))
        break

    # 3) 做任务（任务列表查询被限流时用缓存/内置签到任务兜底）
    tasks = []
    q = interact_assign_query(1)
    if q.get("_blocked"):
        res["task_query"] = "waf_blocked"
        if state.get("sign_task_eaId"):
            tasks = [{"id": state["sign_task_eaId"], "type": 5,
                      "extraType": "sign", "name": "互动签到(缓存eaId)"}]
    elif "_raw" in q:
        res["task_query"] = "bad"
    else:
        lst = q.get("assignmentInfoList") or []
        for t in lst:
            if not t.get("completionFlag") and (t.get("extraType") in AUTO_TASK_EXTRA_TYPES):
                tasks.append({"id": t.get("id"), "type": t.get("type"),
                              "extraType": t.get("extraType"),
                              "name": t.get("name") or t.get("extraType"),
                              "rk": t.get("rk", False)})
        # 缓存未完成签到任务 eaId 供限流时兜底（只从未完成项取，避免被已完成项覆盖）
        for t in tasks:
            if t.get("extraType") == "sign" and t.get("id"):
                state["sign_task_eaId"] = t["id"]
    if not tasks and not q.get("_blocked"):
        # 列表拿到了但没有未完成任务 → 用内置签到任务兜底（幂等）
        tasks = [{"id": state.get("sign_task_eaId") or SIGN_TASK_EAID_DEFAULT,
                  "type": 5, "extraType": "sign", "name": "互动签到"}]

    gained = 0
    for t in tasks:
        if not t.get("id"):
            continue
        r = interact_do_task(t)
        res["tasks"].append({"name": t.get("name"), **{k: r.get(k) for k in ("code", "msg", "gain")}})
        if r.get("code") == "403":
            res["waf_blocked"] = True
            break
        gained += int(r.get("gain") or 0)
    if gained:
        res["chance_gained"] = gained
        save_istate(state)

    # 4) 任务送了新机会 → 再抽
    usable2 = usable + gained
    if usable2 > 0 and not res.get("waf_blocked"):
        while usable2 > 0 and drawn < 30:
            d = interact_draw(lottery_eaid)
            res["draws"].append(d)
            drawn += 1
            if d.get("code") == "403":
                res["waf_blocked"] = True
                break
            if d.get("success"):
                usable2 -= 1
                res.setdefault("rewards", []).append(_reward_text(d.get("items") or []))
                continue
            # 304 次数不足 / 302 303 305 306 幂等完成 → 各消耗一次后继续；
            # 其他错误（999 火爆等）停止，避免触发风控
            if d.get("code") in ("304", "302", "303", "305", "306"):
                usable2 -= 1
                if d.get("code") == "304":
                    break  # 服务端明确没次数了，不必再试
                continue
            break

    ok_draws = [d for d in res["draws"] if d.get("success")]
    ok_tasks = [t for t in res["tasks"] if t.get("gain")]
    res["ok"] = True
    res["state"] = "done"
    res["summary"] = "抽奖%d次(成功%d) 做任务%d项(获得机会+%d)" % (
        len(res["draws"]), len(ok_draws), len(res["tasks"]), gained)
    if res.get("rewards"):
        res["reward_text"] = "；".join(res["rewards"])
    if res.get("waf_blocked"):
        res["summary"] += " [部分请求被WAF限流]"
    save_istate(state)
    return res


def run_interact_status():
    """只读：抽奖机会 + 任务完成情况。"""
    rw = interact_reward()
    if rw.get("_blocked"):
        return {"ok": False, "state": "waf_blocked", "msg": "reward_query 被 WAF 限流(403)"}
    if "_raw" in rw:
        return {"ok": False, "state": "reward_bad", "msg": str(rw.get("_raw"))[:200]}
    out = {"ok": True, "reward": rw}
    q = interact_assign_query(1)
    if q.get("_blocked"):
        out["tasks"] = "waf_blocked"
    elif "_raw" not in q:
        lst = q.get("assignmentInfoList") or []
        out["tasks"] = [{"name": t.get("name"), "extraType": t.get("extraType"),
                         "done": t.get("completionFlag")} for t in lst]
    return out


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
    elif cmd == "interact":
        r = run_interact_auto()
    elif cmd == "interact_status":
        r = run_interact_status()
    else:
        print("未知命令: %s（支持 cookie/auto/status/sign/interact/interact_status）" % cmd)
        sys.exit(2)
        return
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0 if r.get("ok") else 1)


if __name__ == "__main__":
    main()
