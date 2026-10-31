#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
credential_core.py — 全平台「账号保活」共享层（只放纪律，不放平台知识）
=====================================================================
为什么要有这个模块：保活失败的形态高度重复（token 到期→401→叫用户重抓包），
但每个脚本各自实现了一遍解密、过期计算、终态判断、输出措辞，于是：
  · 同一支单次轮换的 refresh_token 被两个脚本同日各刷一次 → 互相作废
  · 过期时间靠"感觉"猜（拿 iat+24h 之类）→ 临期预警全是噪声
  · 401 与"业务码非 0"混成一种失败 → 汇总里到处是【XX失效】
本模块把这套纪律固化成函数，判据只有一份出处（改行为改这里，别在平台脚本里散文重写）。

★五条铁律（来源：Our Free Model 的 refresh.ts / expiry-sync.ts 与各 *-oauth.ts，
  其中三条是它自己踩出来的 issue，不是设计偏好）：
  1) 过期时间**只能由服务端给的值算**：`expires_in` / `expires_at` / JWT `exp`。
     解不出就返回 None 当"未知"，**绝不猜**（猜出来的临期预警会让人天天误报）。
     单位歧义按 Qoder 的尺度判据：>1e12 当毫秒，否则当秒。
  2) refresh_token 多是**单次轮换** → 同一支只试一次；`RefreshGuard` 按 RT 指纹记账，
     指纹变了（真的换到新支）才允许再试，6h 内同指纹一律拒发。
  3) 终态错误**不重试**：401/403 或平台专属终态码（见 TERMINAL_MARKERS）出现即判死，
     直接叫"在客户端重新登录一次"——继续打只会把 token 家族彻底烧掉，
     京东那类风控还会把封锁范围越打越宽。
  4) 刷出来的新凭据**只写自己的 *_live_cache.json，绝不回写官方客户端的凭证文件**
     （客户端持有同一支，回写会争抢、会把用户的登录态搞坏）。
  5) 「不刷」与「不回写有效期」是两件事（OFM issue !IKIRTT 的真实缺陷）：
     跳过续期时**仍要**把到期时间对账输出，否则界面/日报一直显示"已过期"，
     用户看不到任何自救手段。

用法（平台脚本侧）：
    import credential_core as cc
    exp = cc.expiry_ms(expires_in=body.get("expiresIn"), expires_at=c.get("expiresAt"), token=tok)
    if cc.needs_refresh(exp): ...
    ok, why = cc.refresh_allowed("trae", rt)     # 单次轮换守卫
    ...
    cc.auth_line("TRAE", source="桌面端文件", expires_at=exp, refreshable=False)
"""
import base64
import hashlib
import json
import os
import re
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "keepalive_state.json")

LEAD_S = 3600            # 距过期不足 1h 才发续期请求（OFM REFRESH_LEAD_MS 同语义）
WARN_DAYS = 3            # 剩余不足这么多天 → 体检里标"临期"，提示去客户端登录一次
RT_RETRY_COOLDOWN_S = 6 * 3600   # 同一支 RT 试过一次后，这么久内不再试第二次

# 各平台已实测/已抄到的**终态**标记（命中即判死，不重试）。
# 40100/40101/token rejected：LobsterAI 实测（伪造 RT 打过去回 HTTP401+code40100）
# 200003：小浣熊 refresh 终态（OFM raccoon-oauth）
# invalid_grant/expired/revoked：OAuth2 通用 + MiniMax/华为码道
# 会话失效文案：TRAE/有道系服务端原文（照抄分类表，别自己发明）
TERMINAL_MARKERS = (
    "40100", "40101", "token rejected", "refresh token was rejected",
    "200003",
    "invalid_grant", "invalid_client", "expired", "revoked",
    "login expired", "session expired", "session invalidated",
    "unauthorized", "请先登录", "登录已过期", "登录失效", "重新登录",
)


# ── 过期时间：只认服务端给的值 ──────────────────────────────────────────────
def jwt_exp_ms(token):
    """JWT `exp`（毫秒）。非 JWT/解不出 → None。不校验签名，只读 payload。"""
    try:
        seg = (token or "").split(".")[1]
        seg += "=" * (-len(seg) % 4)
        exp = json.loads(base64.urlsafe_b64decode(seg)).get("exp")
        return int(exp) * 1000 if exp else None
    except Exception:
        return None


def to_ms(v):
    """把服务端给的"到期"归一成毫秒。支持：毫秒数 / 秒数（按 >1e12 判尺度）/ ISO 串。
    ★判据来自 Qoder 的 readTimestamp：1e12 分界（约 2001-09 的毫秒值），
      低于它当秒。数字串也能进来。"""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        n = float(v)
        return int(n if n > 1e12 else n * 1000)
    s = str(v).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        n = float(s)
        return int(n if n > 1e12 else n * 1000)
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def expiry_ms(expires_in=None, expires_at=None, token=None, now_s=None):
    """★唯一的过期时间入口，优先级：expires_in(相对) > expires_at(绝对) > JWT exp > None。
    注释里那句"access_token 往往不是 JWT，解不出 payload 就别指望它"就是这个意思。"""
    now_ms = int((now_s if now_s is not None else time.time()) * 1000)
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        return now_ms + int(expires_in) * 1000
    s = str(expires_in or "").strip()
    if re.fullmatch(r"\d+", s) and int(s) > 0:
        return now_ms + int(s) * 1000
    ms = to_ms(expires_at)
    if ms:
        return ms
    return jwt_exp_ms(token)


def days_left(exp_ms, now_ms=None):
    if not exp_ms:
        return None
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    return (exp_ms - now_ms) / 86400000.0


def needs_refresh(exp_ms, lead_s=LEAD_S, now_ms=None):
    """lead-time 判据。**拿不到过期时间时返回 False**——不猜、不滥刷轮换凭证。"""
    if not exp_ms:
        return False
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    return exp_ms - now_ms <= lead_s * 1000


# ── 单次轮换守卫：同一支 refresh_token 只烧一次 ────────────────────────────
def rt_fingerprint(rt):
    return hashlib.sha256(str(rt).encode("utf-8", "replace")).hexdigest()[:12]


def _load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(st):
    tmp = STATE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception:
        pass


def refresh_allowed(platform, rt, now_s=None):
    """(ok, why)。同一支 RT 已试过且没轮换成功 → 冷却期内拒发；
    RT 指纹变化（拿到新一支）则放行。★这是防"两个脚本同天各刷一次互相作废"。"""
    now_s = now_s if now_s is not None else time.time()
    st = _load_state()
    rec = st.get(platform) or {}
    fp = rt_fingerprint(rt)
    if rec.get("rt_fp") == fp and now_s - float(rec.get("at", 0)) < RT_RETRY_COOLDOWN_S:
        left = int((RT_RETRY_COOLDOWN_S - (now_s - float(rec.get("at", 0)))) / 60)
        return False, "同一支 refresh_token %d 分钟前已试过（未换新），冷却中（还约 %d 分钟）" % (
            int((now_s - float(rec.get("at", 0))) / 60), max(left, 0))
    return True, ""


def mark_refresh_attempt(platform, rt, now_s=None, rotated=False):
    """记录一次尝试。rotated=True 表示真拿到了新一支（指纹随即更新，允许下次再试）。"""
    st = _load_state()
    st[platform] = {"rt_fp": rt_fingerprint(rt), "at": now_s if now_s is not None else time.time(),
                    "rotated": bool(rotated),
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    _save_state(st)


# ── 终态判定 ────────────────────────────────────────────────────────────────
def is_terminal(status=None, text="", extra_markers=()):
    """401/403 或命中终态文案 → True（判死，不重试）。"""
    if status in (401, 403):
        return True
    t = str(text or "").lower()
    for m in tuple(TERMINAL_MARKERS) + tuple(extra_markers):
        if str(m).lower() in t:
            return True
    return False


class RefreshTokenExpired(Exception):
    """终态续期失败。★类名固定为 RefreshTokenExpired，判据是**字符串比较**
    （OFM 里 8 个 provider 的错误类都把 name 强制成同一个值；改名会让调度器认不出、
    拿死 token 无限重试）。"""
    def __init__(self, msg=""):
        Exception.__init__(self, msg)
        self.name = "RefreshTokenExpired"


# ── 输出：统一判读口径 ──────────────────────────────────────────────────────
def fmt_exp(exp_ms):
    if not exp_ms:
        return "未知(服务端没给/解不出)"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(exp_ms / 1000))


def auth_line(platform, source="", expires_at=None, refreshable=None, note="", quiet=False):
    """打统一的 `[鉴权]` 行。**只做加法**：不替换各脚本原有的失效措辞
    （【XX失效】/login_expired 这些是日报判读的锚点，动它们会打断汇总口径）。"""
    if quiet:
        return ""
    d = days_left(expires_at)
    left = "" if d is None else ("（已过期 %.1f 天）" % -d if d < 0 else "（剩 %.1f 天）" % d)
    ra = {True: "可离线续期", False: "不可续期(只能客户端重登)", None: "续期能力未知"}[refreshable]
    line = "[鉴权][%s] 来源=%s | 到期=%s%s | %s" % (platform, source or "-", fmt_exp(expires_at), left, ra)
    if d is not None and 0 <= d <= WARN_DAYS:
        line += " | ★临期预警"
    if note:
        line += " | " + note
    print(line)
    return line


# ── 成功心跳：给"服务端不给到期时间"的平台一条衰减信号 ─────────────────────
# 美团/利宝/小米/南航这类平台的凭证**没有到期字段**，体检只能报"未知"，于是坏了要等
# 当天领不到才发现。心跳的用处：每次业务成功就把时间记下来，体检读"上次成功距今几天"——
# 只要某天开始不再更新，就是凭证出事的最早可观测信号。★记账放在总控统一做
# （run_all 每个任务收尾调一次），不在 20 个平台脚本里各写一份。
def record_ok(platform, rc=0, note="", now_s=None):
    st = _load_state()
    rec = st.get("ok") if isinstance(st.get("ok"), dict) else {}
    rec[platform] = {"at": now_s if now_s is not None else time.time(),
                     "rc": rc, "note": str(note)[:120],
                     "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    st["ok"] = rec
    _save_state(st)


def last_ok(platform):
    st = _load_state()
    rec = (st.get("ok") or {}).get(platform) or {}
    return rec


def days_since_ok(platform, now_s=None):
    rec = last_ok(platform)
    if not rec.get("at"):
        return None
    now_s = now_s if now_s is not None else time.time()
    return round(now_s - float(rec["at"]), 1) / 86400.0


def _norm(name):
    return re.sub(r"[\s()（）\-—_/]", "", str(name or "")).lower()


def find_ok(label):
    """按**归一化名字**找心跳记录——体检里的平台名（"字节 TRAE"）与总控任务名
    （"字节TRAE"）只差空格/括号，别要求调用方写完全一致的字符串。"""
    st = _load_state()
    recs = st.get("ok") if isinstance(st.get("ok"), dict) else {}
    want = _norm(label)
    if not want:
        return {}
    if want in recs:
        return recs[want]
    for k, v in recs.items():
        nk = _norm(k)
        if nk == want or want in nk or nk in want:
            return v
    return {}


def days_since_ok_any(label, now_s=None):
    rec = find_ok(label)
    if not rec.get("at"):
        return None
    now_s = now_s if now_s is not None else time.time()
    return round(now_s - float(rec["at"]), 1) / 86400.0


# ── 读官方客户端的存储（两条通用形态）──────────────────────────────────────
def read_v10_json(path, user_data_dir=None):
    """Chromium v10/DPAPI 信封（auth.v1.dat / auth-v2.dat / state.vscdb 里的值同一条链）。
    ★统一走 browser_cookies 的 master_key/decrypt_v10——原来 5 个脚本各写一份，
      任一处改了 DPAPI 调用方式就会让其余几处静默退化。"""
    if not path or not os.path.exists(path):
        return None
    try:
        import browser_cookies as bc
        key = bc.master_key(user_data_dir or bc.browser_ud())
        return json.loads(bc.decrypt_v10(key, open(path, "rb").read()).decode("utf-8"))
    except Exception as e:
        print("[警告] 解密 %s 失败: %s" % (os.path.basename(path), e))
        return None


# ── 字节 byteCrypto 信封（TRAE 桌面端 storage.json 里的本地凭证）──────────────
# 2026-10-31 照 out-build/vs/base/common/byteCrypto.js（装机 main.js 内联）逐行核对：
#   blob = hdr(6) || keyMat(32) || AES-128-CBC( sha512(plain)(64) || plain )
#   hdr  = 116('t') 99('c') 5 16 0 0        ← uKe() 按这 6 字节认版本
#   aesKey/iv 全由 keyMat 派生：n = sha512(keyMat) || SALT(64)
#                                n[0:64] = sha512(n) → aesKey=n[0:16] iv=n[16:32]
#   ★SALT 是包里两张 64 字节表逐字节异或。表名（Aue/Due）是压缩器赋的，客户端一升级
#     就改名，所以**不写死表值**：从 main.js 按长度捞候选表、两两异或当 salt 逐个试，
#     信封自带的 sha512 前缀就是 oracle——试错只会解不开，不会解出脏数据。
BC_HDR = bytes([116, 99, 5, 16, 0, 0])
_BC_TV, _BC_Z2, _BC_OP, _BC_SL = 6, 32, 64, 16


def byte_crypto_salts(js_text):
    """从 JS 文本里捞 byteCrypto 的两张 64 字节表，两两异或出候选 salt。"""
    tables = []
    for m in re.finditer(r"\[(\d{1,3}(?:,\d{1,3}){63})\]", js_text or ""):
        b = bytes(int(x) for x in m.group(1).split(","))
        if b not in tables:
            tables.append(b)
    out = []
    for i, a in enumerate(tables):
        for b in tables[i + 1:]:
            s = bytes(x ^ y for x, y in zip(a, b))
            if s not in out:
                out.append(s)
    return out


def byte_crypto_open(blob, salt):
    """按给定 salt 解一个 byteCrypto blob（bytes）→ 明文 bytes；格式/校验不过 → None。"""
    try:
        if len(blob) <= _BC_TV + _BC_Z2 or blob[:_BC_TV] != BC_HDR:
            return None
        n = bytearray(hashlib.sha512(blob[_BC_TV:_BC_TV + _BC_Z2]).digest() + salt)
        n[:_BC_OP] = hashlib.sha512(bytes(n)).digest()
        key, iv = bytes(n[:_BC_SL]), bytes(n[_BC_SL:2 * _BC_SL])
        ct = blob[_BC_TV + _BC_Z2:]
        if len(ct) % _BC_SL:
            return None
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        raw = d.update(ct) + d.finalize()
        pad = raw[-1]
        if not 1 <= pad <= _BC_SL:
            return None
        raw = raw[:-pad]
        if raw[:_BC_OP] != hashlib.sha512(raw[_BC_OP:]).digest():
            return None
        return raw[_BC_OP:]
    except Exception:
        return None


def byte_crypto_json(b64, salts):
    """base64 信封 → 解出的 dict/list；认不出格式 → None。逐个 salt 试到 oracle 通过。"""
    import base64 as b64m
    try:
        blob = b64m.b64decode(b64, validate=False)
    except Exception:
        return None
    for salt in salts:
        pt = byte_crypto_open(blob, salt)
        if pt is None:
            continue
        try:
            return json.loads(pt.decode("utf-8"))
        except Exception:
            return None
    return None


def read_sqlite_kv(path, timeout=3):
    """只读 Electron 客户端 sqlite 的 `kv` 表 {key: value}。
    ★先 `immutable=1` 再回退 `mode=ro`：客户端在跑时后者会撞独占锁。"""
    import sqlite3
    if not path or not os.path.exists(path):
        return None
    base = "file:%s" % str(path).replace("\\", "/")
    for q in ("mode=ro&immutable=1", "mode=ro"):
        try:
            c = sqlite3.connect("%s?%s" % (base, q), uri=True, timeout=timeout)
            try:
                return dict(c.execute("select key, value from kv"))
            finally:
                c.close()
        except Exception:
            continue
    return None


def find_first(cands):
    """按顺序返回第一个存在的路径（多平台桌面端目录都有大小写/新旧命名两套）。"""
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None


def appdata(*parts):
    return os.path.join(os.environ.get("APPDATA", ""), *parts)


def home(*parts):
    return os.path.join(os.path.expanduser("~"), *parts)
