#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用浏览器 Cookie 提取 (browser_cookies.py)
==========================================
从本机 Thorium/Chromium 的 Cookies 库里，按域名提取**已解密**的登录 cookie。

★解决的问题：Chromium 的 Cookies SQLite 库被运行中的浏览器实例**独占锁**，
直接 sqlite3.connect 会失败。本模块用 CreateFileW(GENERIC_READ, FILE_SHARE_READ|
WRITE|DELETE) 绕开共享锁把文件读进内存，再走 SQLite 解析，**不影响正在运行的浏览器**。

解密链（Chromium v10 加密 cookie）：
  Local State → os_crypt.encrypted_key (base64, 去掉 "DPAPI" 5B 头)
    → CryptUnprotectData (DPAPI, 当前用户上下文) → 32B AES-256 主密钥
  cookie encrypted_value: "v10" + 12B nonce + ciphertext+tag
    → AESGCM(key).decrypt(nonce, ct, None)

优先级（与 jd_web_signin.py 一致）：
  1. 磁盘直读（绕独占锁，26 次×1.2s 重试；成功则顺手刷新 TEMP 缓存）
  2. TEMP 缓存：本平台 `_wb_ck_<tag>.db` 优先，**其次任意平台的整库副本**
     （`_wb_ck_*.db` / `_jd_ck.db`，按修改时间倒序）——整库副本里含全部域名的
     cookie，所以别的平台留下的缓存也能救本平台（磁盘锁死时的唯一出路）
  3. CDP 9222（浏览器带 --remote-debugging-port 启动时，Network.getAllCookies，
     能拿到 httpOnly cookie）

用法:
  from browser_cookies import extract
  ck = extract(["quark.cn"], tag="quark")     # → {name: value}
  ck = extract(["aliyundrive.com"], tag="aliyun")

环境变量:
  WB_BROWSER_UD  指定 User Data 目录（默认自动探测 Thorium → Chromium）
"""
import glob
import json
import os
import shutil
import sqlite3
import tempfile
import time

__all__ = ["extract", "extract_full", "browser_ud", "cookie_header", "probe_domains"]

SHARE_READ = 0x00000001
SHARE_WRITE = 0x00000002
SHARE_DELETE = 0x00000004
SHARE_ALL = SHARE_READ | SHARE_WRITE | SHARE_DELETE
GENERIC_READ = 0x80000000
OPEN_EXISTING = 3


# ---------------------------------------------------------------- 浏览器定位
def browser_ud():
    """浏览器 User Data 目录（thorium 优先，可用 WB_BROWSER_UD 覆盖）。"""
    env = os.environ.get("WB_BROWSER_UD")
    if env and os.path.isdir(env):
        return env
    local = os.environ.get("LOCALAPPDATA", "")
    for name in ("Thorium", "Chromium"):
        p = os.path.join(local, name, "User Data")
        if os.path.isdir(p):
            return p
    return ""


def _cookies_paths(ud):
    """候选 Cookies 库路径：Default 优先，其次各 Profile N。"""
    if not ud:
        return []
    paths = [os.path.join(ud, "Default", "Network", "Cookies")]
    paths += sorted(glob.glob(os.path.join(ud, "Profile *", "Network", "Cookies")))
    return [p for p in paths if os.path.isfile(p)]


# ---------------------------------------------------------------- DPAPI 主密钥
def _dpapi(data):
    import ctypes
    from ctypes import POINTER, c_char, create_string_buffer, byref, string_at, wintypes

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


def _master_key(ud):
    """从 Local State 解出 AES-256 主密钥（失败抛 RuntimeError）。"""
    import base64

    ls_path = os.path.join(ud, "Local State")
    with open(ls_path, encoding="utf-8") as f:
        ls = json.load(f)
    raw = base64.b64decode(ls["os_crypt"]["encrypted_key"])
    key = _dpapi(raw[5:])                     # 去掉 "DPAPI" 5B 前缀
    if not key:
        raise RuntimeError("DPAPI 解 master key 失败")
    return key


# ---------------------------------------------------------------- 绕锁直读
def _raw_read(ck_path, retries=26, pause=1.2):
    """CreateFileW 带共享标志读文件，绕开 Chromium 独占锁。失败返回 None。"""
    import ctypes
    from ctypes import POINTER, c_char, byref, wintypes

    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.GetFileSize.argtypes = [wintypes.HANDLE, POINTER(wintypes.DWORD)]
    k32.GetFileSize.restype = wintypes.DWORD
    k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                             POINTER(wintypes.DWORD), wintypes.LPVOID]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    for _ in range(retries):
        h = k32.CreateFileW(ck_path, GENERIC_READ, SHARE_ALL, None, OPEN_EXISTING, 0, None)
        if h and h != wintypes.HANDLE(-1).value:
            try:
                size = k32.GetFileSize(h, None)
                buf = (c_char * size)()
                read = wintypes.DWORD(0)
                k32.ReadFile(h, buf, size, byref(read), None)
                return bytes(buf[:read.value])
            finally:
                k32.CloseHandle(h)
        time.sleep(pause)
    return None


# ---------------------------------------------------------------- SQLite 解析
def _rows(db_path, domains):
    """取候选 cookie 行（带 path / is_secure，注入浏览器时要用）。"""
    like = " OR ".join(["host_key LIKE ?"] * len(domains))
    params = ["%" + d for d in domains]
    con = sqlite3.connect(db_path)
    try:
        return con.execute(
            "SELECT host_key, name, encrypted_value, path, is_secure FROM cookies WHERE " + like,
            params).fetchall()
    finally:
        con.close()


def _decrypted(rows, key):
    """解密行 → [(host_key, name, value, path, secure)]（解不开的跳过）。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    out = []
    for host, name, ev, path, secure in rows:
        if not ev or ev[:3] != b"v10":
            continue
        try:
            v = AESGCM(key).decrypt(ev[3:15], ev[15:], None).decode("utf-8", "replace")
        except Exception:
            continue
        if v:
            out.append((host, name, v, path or "/", bool(secure)))
    return out


def _parse_db_full(db_path, domains, key):
    """解析一个 Cookies 库，返回 [{name, value, domain, path, secure}]（保留 host_key）。"""
    return [{"name": name, "value": v, "domain": host, "path": path, "secure": secure}
            for host, name, v, path, secure in _decrypted(_rows(db_path, domains), key)]


def _candidate_caches(tag):
    """TEMP 里的候选整库缓存，按「本平台专属 → 其余按修改时间倒序」排列。

    ★通用收益：任何一个平台成功直读 Cookies 库时写的缓存都是**整库副本**，
      里面也含其他平台的 cookie。所以京东的 `_jd_ck.db` 同样能救夸克 —— 只要
      它比磁盘当前可读状态更新（磁盘被独占锁时这是唯一出路）。
    """
    tmp = tempfile.gettempdir()
    seen, out = set(), []
    own = os.path.join(tmp, "_wb_ck_%s.db" % tag)
    if os.path.isfile(own):
        seen.add(own)
        out.append(own)
    others = []
    for p in glob.glob(os.path.join(tmp, "_wb_ck_*.db")) + glob.glob(os.path.join(tmp, "_jd_ck.db")):
        if os.path.isfile(p) and p not in seen:
            seen.add(p)
            others.append(p)
    others.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return out + others


def _parse_bytes_full(raw, domains, key):
    """把内存中的 Cookies 库字节落到临时文件再解析（保留 host_key）。"""
    tmp = os.path.join(tempfile.gettempdir(), "_wb_ck_tmp.db")
    try:
        with open(tmp, "wb") as f:
            f.write(raw)
        return _parse_db_full(tmp, domains, key)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------- CDP 回退
def _cdp_raw():
    """走 9222 拿全量 cookie 原始列表（含 httpOnly）。拿不到返回 []。"""
    import urllib.request

    try:
        import websocket
    except ImportError:
        return []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:9222/json/list", timeout=4) as r:
            pages = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return []
    if not pages:
        return []
    target = pages[0]
    for p in pages:
        if p.get("type") == "page":
            target = p
            break
    try:
        ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=10,
                                         suppress_origin=True)
    except Exception:
        return []
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
        for _ in range(40):
            msg = json.loads(ws.recv())
            if msg.get("id") == 2:
                return msg.get("result", {}).get("cookies") or []
        return []
    except Exception:
        return []
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _cdp_cookies(domains):
    """浏览器带 9222 调试端口时，用 Network.getAllCookies 取 cookie（含 httpOnly）。"""
    got = {}
    for c in _cdp_raw():
        d = c.get("domain") or ""
        if any(d == dom or d.endswith("." + dom) for dom in domains):
            n, v = c.get("name"), c.get("value") or ""
            if v and (n not in got or len(v) > len(got[n])):
                got[n] = v
    return got or None


def _cdp_cookies_full(domains):
    """同 _cdp_cookies，但保留 domain/path/secure（注入用）。"""
    out = []
    for c in _cdp_raw():
        d = c.get("domain") or ""
        if any(d == dom or d.endswith("." + dom) for dom in domains) and c.get("value"):
            out.append({"name": c.get("name"), "value": c["value"], "domain": d,
                        "path": c.get("path") or "/", "secure": bool(c.get("secure"))})
    return out or None


# ---------------------------------------------------------------- 主入口
def _collect(domains, tag="wb", verbose=False, allow_cdp=True):
    """按优先级取指定域名的登录 cookie，返回 [{name,value,domain,path,secure}]。

    优先级：1) 磁盘直读（绕独占锁）2) TEMP 整库缓存 3) CDP 9222。失败返回 []。
    """
    ud = browser_ud()
    if not ud:
        if verbose:
            print("[cookie] 未找到浏览器 User Data 目录（设 WB_BROWSER_UD 指定）")
        return []

    paths = _cookies_paths(ud)
    if not paths:
        if verbose:
            print("[cookie] 未找到 Cookies 库: %s" % ud)
        return []

    # 1) 磁盘直读（逐个候选路径尝试）
    raw = None
    for p in paths:
        raw = _raw_read(p)
        if raw:
            if verbose:
                print("[cookie] 磁盘直读 OK %s (%d 字节)" % (os.path.basename(os.path.dirname(os.path.dirname(p))), len(raw)))
            break
    if raw:
        try:
            key = _master_key(ud)
            got = _parse_bytes_full(raw, domains, key)
            if got:
                # 顺手刷新 TEMP 缓存（本平台专属 + 通用 all），供其他平台回退
                for name in ("_wb_ck_%s.db" % tag, "_wb_ck_all.db"):
                    try:
                        with open(os.path.join(tempfile.gettempdir(), name), "wb") as f:
                            f.write(raw)
                    except OSError:
                        pass
                return got
            if verbose:
                print("[cookie] 磁盘库中未解析到 %s 的 cookie（可能未登录或换过 profile）" % domains)
        except Exception as e:
            if verbose:
                print("[cookie] 磁盘解析失败: %s" % e)

    # 2) TEMP 缓存：本平台专属优先，其次任意平台的整库副本（按新鲜度）
    for cache in _candidate_caches(tag):
        try:
            got = _parse_db_full(cache, domains, _master_key(ud))
            if got:
                if verbose:
                    print("[cookie] TEMP 缓存命中 %d 个（%s, %s）" % (
                        len(got), os.path.basename(cache),
                        time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(cache)))))
                return got
        except Exception as e:
            if verbose:
                print("[cookie] TEMP 缓存解析失败 %s: %s" % (os.path.basename(cache), e))

    # 3) CDP 9222
    if allow_cdp:
        got = _cdp_cookies_full(domains)
        if got:
            if verbose:
                print("[cookie] CDP 9222 命中 %d 个" % len(got))
            return got

    return []


def extract(domains, tag="wb", verbose=False, allow_cdp=True):
    """按优先级提取指定域名的登录 cookie。

    domains: 域名后缀列表，如 ["quark.cn"] / ["aliyundrive.com"]
    tag:     TEMP 缓存文件名后缀（避免多平台互相覆盖）
    返回 {name: value}（同名多域取最长值）；失败返回 {}。
    """
    best = {}
    for c in _collect(domains, tag, verbose, allow_cdp):
        cur = best.get(c["name"])
        if cur is None or len(c["value"]) > len(cur):
            best[c["name"]] = c["value"]
    return best


def extract_full(domains, tag="wb", verbose=False, allow_cdp=True):
    """同 extract()，但保留 host_key：[{name,value,domain,path,secure}]。
    ★往浏览器里注入登录态必须用它——domain 照抄库里的 host_key（前导点写法），
      否则子域收不到（2026-10-15 掘金救援实测）。"""
    return _collect(domains, tag, verbose, allow_cdp)


def cookie_header(ck):
    """{name: value} → "n1=v1; n2=v2" 字符串（按名字排序保证可复现）。"""
    return "; ".join("%s=%s" % (k, ck[k]) for k in sorted(ck))


def probe_domains(domains, tag="wb"):
    """诊断用：打印候选 Cookies 库里各域名的 cookie 名清单（走绕锁读取，不解密）。"""
    ud = browser_ud()
    if not ud:
        print("未找到 User Data")
        return
    key = _master_key(ud)
    for p in _cookies_paths(ud):
        raw = _raw_read(p, retries=2, pause=0.3)
        prof = os.path.basename(os.path.dirname(os.path.dirname(p)))
        if not raw:
            print("%s: 读取失败(独占锁)" % prof)
            continue
        tmp = os.path.join(tempfile.gettempdir(), "_wb_probe.db")
        try:
            with open(tmp, "wb") as f:
                f.write(raw)
            like = " OR ".join(["host_key LIKE ?"] * len(domains))
            con = sqlite3.connect(tmp)
            try:
                rows = con.execute(
                    "SELECT host_key, name, length(encrypted_value) FROM cookies WHERE " + like,
                    ["%" + d for d in domains]).fetchall()
            finally:
                con.close()
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        print("%s: %d 行" % (prof, len(rows)))
        for host, name, ln in rows[:80]:
            print("   %-30s %-32s enc=%sB" % (host, name, ln or 0))
