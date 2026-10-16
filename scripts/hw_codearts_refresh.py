#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
hw_codearts_refresh.py — 华为码道 CodeArts 临时凭证「离线续期」核心
==================================================================
账号状态保持方法（参考本机 Our Free Model 桌面端 src/oauth.ts 逆向）：
  CodeArts Agent 登录时走 OAuth2 + PKCE + DPoP，换回一组 IAM 临时 AK/SK
  （access_key_id / secret_access_key / security_token，约 2 小时寿命）
  以及一份 **refresh_token**（约 28 天寿命）+ PKCE code_verifier + DPoP EC 密钥对。
  客户端在有效期内靠 `safelyRenewTokenInterval` 定时自我续期；一旦客户端没开着，
  state.vscdb 里的临时 AK/SK 就会**过期**（本脚本原本会退回失效的 devcloud cookie，
  导致天天误报【华为码道失效】）。

  本模块复刻 OFM 的续期链路，让签到脚本**无需客户端在前台也能自己续命**：
    POST https://sts.cn-north-4.myhuaweicloud.com/v1/oauth2/tokens
      headers: DPoP: <ES256 JWS{htm:POST, htu:<上面URL>, iat, jti}>
               Content-Type: application/x-www-form-urlencoded
      body:    client_id=codearts-agent
               code_verifier=<PKCE codeVerifier>
               grant_type=refresh_token
               refresh_token=<当前 refresh_token>
    → 200 JSON: {credentials:{access_key_id, secret_access_key, security_token, expiration},
                 refresh_token:<轮换后的新值>}
    → 失败终态: data.error=="invalid_grant" 或 error_code 含 "ExpiredRefreshToken"
                （refresh_token 也被消费/过期 → 只能重开客户端登录）

  ★refresh_token 是一次性消费的（每刷一次服务端下发新值，旧值作废）。客户端在后台
    也会续期并消费它，所以本地缓存的 refresh_token 可能落后于 state.vscdb 里那份。
    故续期按「候选成对」顺序重试：每个候选 = (refresh_token, codeVerifier, dpop 私钥)
    ——三件必须配套（refresh_token 的 cnf 绑定公钥），不能跨对混用。任一成功即把新
    三元组写回本地缓存文件 hw_codearts_session.json，认服务端为权威。

字段命名对齐：本模块对外的 credential 同时给出 camelCase（现有 hw_codearts.py 用的
accessKey/secretKey/securitytoken/expires_at）与 snake_case（OFM 口径），两侧通吃。

用法（调试）:
  python hw_codearts_refresh.py probe     # 只读 session，打印结构（脱敏）+ 有效期
  python hw_codearts_refresh.py refresh   # 实打实刷一次，打印是否拿回新 AK/SK
  python hw_codearts_refresh.py verify    # 刷新 + 立刻用它打 delivery 验真
"""
import base64
import hashlib
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
CFG_DIR = BASE  # state.vscdb 路径来自 APPDATA\codearts-agent，不在这里
CACHE_PATH = os.path.join(BASE, "hw_codearts_session.json")

# ── OFM src/oauth.ts 常量（原样搬）──────────────────────────────────────────
CLIENT_ID = "codearts-agent"
STS_TOKEN_ENDPOINT = "https://sts.cn-north-4.myhuaweicloud.com/v1/oauth2/tokens"
TOKEN_TIMEOUT_MS = 60  # 秒
# 距过期不足这么秒就先续（与 OFM REFRESH_LEAD_MS 同语义；给 20 分钟冗余）
REFRESH_LEAD_S = 20 * 60

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── v10 / DPAPI 读取 state.vscdb（复用 browser_cookies 解密链）───────────────
def _state_paths():
    ud = os.environ.get("HW_CODEARTS_UD") or os.path.join(
        os.environ.get("APPDATA", ""), "codearts-agent")
    return (os.path.join(ud, "User", "globalStorage", "state.vscdb"), ud)


def load_client_session():
    """返回解密后的完整 session dict（含 refresh_token/loginContext/AK-SK），失败返回 (None, 原因)。"""
    db, ud = _state_paths()
    if not os.path.isfile(db):
        return None, "没找到 CodeArts Agent 的 state.vscdb（未安装/未登录：%s）" % db
    try:
        import browser_cookies as bc
        raw = bc.raw_read_shared(db)
        if not raw:
            return None, "state.vscdb 打不开（客户端独占锁）"
        import sqlite3
        tmp = os.path.join(os.environ.get("TEMP", "."), "_hw_ref_state.db")
        with open(tmp, "wb") as f:
            f.write(raw)
        try:
            con = sqlite3.connect(tmp)
            try:
                row = con.execute(
                    "SELECT value FROM ItemTable WHERE key LIKE ?",
                    ('%HuaweiCloudSession%',)).fetchone()
                # ★同连接先取判据（tmp 随后就删）：usages 历史键在 → 本机曾登录过，
                #   session 键却没了 = 登录态被清掉（多半点了退出登录）
                had_account = con.execute(
                    "SELECT 1 FROM ItemTable WHERE key LIKE '%huawei-cloud-authentication%usages%' LIMIT 1"
                ).fetchone() is not None
            finally:
                con.close()
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if not row:
            return None, ("state.vscdb 里 HuaweiCloudSession 已消失——客户端登录态被清掉"
                          "（多半是点了退出登录），打开 CodeArts Agent 重新登录即可恢复续期链路"
                          if had_account else
                          "state.vscdb 里没有 HuaweiCloudSession（客户端从未登录）")
        v = row[0]
        if isinstance(v, str):
            v = v.encode("utf-8", "surrogateescape")
        env = json.loads(v)
        blob = bytes(env["data"]) if isinstance(env, dict) and "data" in env else v
        return json.loads(bc.decrypt_v10(bc.master_key(ud), blob).decode("utf-8")), ""
    except Exception as e:
        return None, "读取桌面端 session 失败：%s: %s" % (type(e).__name__, str(e)[:140])


# ── base64url（无填充）──────────────────────────────────────────────────────
def _b64u(raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_int(s):
    return int.from_bytes(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)), "big")


def _int_b64u(n):
    # 32 字节定长（P-256 坐标 / d 均 32B）
    return _b64u(n.to_bytes(32, "big"))


# ── ES256 (P-256) JWS 签名（DPoP proof）──────────────────────────────────────
def _jose_sig(der, curve_bits=256):
    """cryptography ECDSA 返回 DER，JOSE(JWS) 要 r‖s 定长拼接。"""
    # DER: 0x30 len 0x02 rlen <r> 0x02 slen <s>
    seq = der[2:] if der[0] == 0x30 else der
    # 手动拆（避开额外依赖）
    i = 0
    assert seq[i] == 0x02, "DER sig 期望 INTEGER"
    i += 1
    rlen = seq[i]; i += 1
    r = int.from_bytes(seq[i:i + rlen], "big"); i += rlen
    assert seq[i] == 0x02, "DER sig 期望第二 INTEGER"
    i += 1
    slen = seq[i]; i += 1
    s = int.from_bytes(seq[i:i + slen], "big")
    key_len = curve_bits // 8  # 32
    return r.to_bytes(key_len, "big") + s.to_bytes(key_len, "big")


def _ec_private_from_jwk(jwk):
    from cryptography.hazmat.primitives.asymmetric.ec import (
        EllipticCurvePrivateNumbers, EllipticCurvePublicNumbers, SECP256R1)
    priv = _b64u_int(jwk["d"])
    pub = EllipticCurvePublicNumbers(_b64u_int(jwk["x"]), _b64u_int(jwk["y"]), SECP256R1())
    return EllipticCurvePrivateNumbers(priv, pub).private_key(SECP256R1())


def build_dpop_proof(priv_jwk, pub_jwk, htm, htu):
    """OFM signDpopJws 的等价实现：ES256 签的 DPoP JWT。
    header={alg:ES256, typ:dpop+jwt, jwk:pub(去私钥字段)}，payload={htm,htu,iat,jti}。"""
    pub_only = {k: pub_jwk[k] for k in ("kty", "crv", "x", "y") if k in pub_jwk}
    header = {"alg": "ES256", "typ": "dpop+jwt", "jwk": pub_only}
    payload = {"htm": htm, "htu": htu,
               "iat": int(time.time()),
               "jti": os.urandom(32).hex()}
    signing_input = ("%s.%s" % (
        _b64u(json.dumps(header, separators=(",", ":"), sort_keys=False).encode("utf-8")),
        _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8")))).encode("ascii")
    from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
    from cryptography.hazmat.primitives.hashes import SHA256
    key = _ec_private_from_jwk(priv_jwk)
    der = key.sign(signing_input, ECDSA(SHA256()))
    sig = _b64u(_jose_sig(der, 256))
    return (signing_input + ("." + sig).encode("ascii")).decode("ascii")


# ── 对 refresh_token 解码 exp（判断它自己还有多久，纯本地，不发请求）────────
def refresh_token_exp_ms(rt):
    try:
        p = rt.split(".")[1]
        pl = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        return int(pl["exp"] * 1000) if isinstance(pl.get("exp"), (int, float)) else 0
    except Exception:
        return 0


# ── 调 STS 用 refresh_token 换新临时凭证（不发网络除非 refresh=True）────────
class RefreshTerminal(Exception):
    """refresh_token 终态失效（已被消费/过期/不匹配）→ 该 token 不能再试第二次，须重开客户端登录。"""


def exchange_refresh_token(rt, code_verifier, priv_jwk, pub_jwk, fetch_timeout=TOKEN_TIMEOUT_MS):
    """POST STS token endpoint，返回 {access_key_id, secret_access_key, security_token,
    expiration, refresh_token}。失败：终态抛 RefreshTerminal，其他抛 RuntimeError。"""
    proof = build_dpop_proof(priv_jwk, pub_jwk, "POST", STS_TOKEN_ENDPOINT)
    body = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "code_verifier": code_verifier,
        "grant_type": "refresh_token",
        "refresh_token": rt,
    }).encode("ascii")
    req = urllib.request.Request(STS_TOKEN_ENDPOINT, data=body, method="POST", headers={
        "DPoP": proof,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "CodeArtsAgent/refresh",
    })
    try:
        r = urllib.request.urlopen(req, timeout=fetch_timeout, context=CTX)
        status = r.status
        data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            data = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            data = {}
    except Exception as e:
        raise RuntimeError("STS 网络错误：%s" % str(e)[:140])
    cred = data.get("credentials") if isinstance(data, dict) else None
    if status == 200 and cred:
        return {
            "access_key_id": cred.get("access_key_id", ""),
            "secret_access_key": cred.get("secret_access_key", ""),
            "security_token": cred.get("security_token", ""),
            "expiration": cred.get("expiration", ""),
            # refresh_token 也会轮换：新值非空才覆盖（与 OFM 一致），否则沿用旧值
            "refresh_token": data.get("refresh_token") or rt,
        }
    err = (data or {}).get("error", "") if isinstance(data, dict) else ""
    ecode = str((data or {}).get("error_code", "")) if isinstance(data, dict) else ""
    emsg = str((data or {}).get("error_msg", "")) if isinstance(data, dict) else ""
    # ★实测两种终态形态：
    #   ① OFM 口径：data.error=="invalid_grant" 或 error_code 含 "ExpiredRefreshToken"
    #   ② STS5.1806 / error_msg "invalid refresh token" —— refresh_token 单次轮换，
    #      旧值已被消费（本模块刷成功一次后 vscdb 里那份就是旧值），再试必然失败，
    #      且继续重试可能触发重放检测烧掉整条 token 家族 → 必须按**终态**处理，
    #      同一候选只允许试一次。
    if (err == "invalid_grant" or "ExpiredRefreshToken" in ecode
            or "invalid refresh token" in emsg.lower() or ecode == "STS5.1806"):
        raise RefreshTerminal("HTTP %s refresh_token 已终态失效（%s %s）→ 须重开客户端登录"
                              % (status, ecode or err, emsg))
    raise RuntimeError("HTTP %s STS 刷新失败：%s" % (status, json.dumps(data, ensure_ascii=False)[:180]))


# ── 缓存（本地持久化最新的 refresh 三元组）─────────────────────────────────
def load_cache():
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(c):
    c["saved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CACHE_PATH)


def _norm(d):
    """统一 credential 键：同时提供 camelCase（hw_codearts.py 旧字段）与 snake_case。"""
    if not d:
        return d
    exp = d.get("expires_at") or d.get("expiration") or ""
    ak = d.get("accessKey") or d.get("access_key_id") or ""
    sk = d.get("secretKey") or d.get("secret_access_key") or ""
    st = d.get("securitytoken") or d.get("security_token") or ""
    out = dict(d)
    out.update({"accessKey": ak, "secretKey": sk, "securitytoken": st,
                "access_key_id": ak, "secret_access_key": sk, "security_token": st,
                "expires_at": exp, "expiration": exp})
    return out


def _exp_ms(d):
    e = (d or {}).get("expires_at") or (d or {}).get("expiration") or ""
    if not e:
        return 0
    try:
        return int(datetime.strptime(e[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        try:
            return int(datetime.fromisoformat(e.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return 0


def _has_material(sess):
    lc = (sess or {}).get("loginContext") or {}
    pk = lc.get("pkcePair") or {}
    dp = lc.get("dpopKeyPair") or {}
    return bool(sess.get("refresh_token") and pk.get("codeVerifier")
                and (dp.get("privateKeyJwk") or {}).get("d"))


def refresh_from_session(sess, source=""):
    """给定一份完整 session（含 refresh_token + loginContext），刷出新 credential 并写缓存。"""
    lc = sess["loginContext"]
    rt = sess["refresh_token"]
    new = exchange_refresh_token(
        rt, lc["pkcePair"]["codeVerifier"],
        lc["dpopKeyPair"]["privateKeyJwk"], lc["dpopKeyPair"]["publicKeyJwk"])
    # 组装成可再次续期的完整结构（保留 PKCE + DPoP 密钥对，轮换后的新 rt）
    merged = dict(sess)
    merged["accessKey"] = new["access_key_id"]
    merged["secretKey"] = new["secret_access_key"]
    merged["securitytoken"] = new["security_token"]
    merged["expires_at"] = new["expiration"]
    merged["refresh_token"] = new["refresh_token"]
    merged["_refreshed_via"] = source or "sts"
    merged["_refreshed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # 缓存：续期材料（不含临时 AK/SK 的旧值）+ **本次刷出来的临时凭证**，
    #   后者在 2 小时有效期内可被下次运行直接复用，避免每跑一次就烧一次 refresh_token
    save_cache({
        "refresh_token": new["refresh_token"],
        "code_verifier": lc["pkcePair"]["codeVerifier"],
        "dpop_private_jwk": lc["dpopKeyPair"]["privateKeyJwk"],
        "dpop_public_jwk": lc["dpopKeyPair"].get("publicKeyJwk") or
            {k: lc["dpopKeyPair"]["privateKeyJwk"][k] for k in ("kty", "crv", "x", "y")},
        "rt_exp_ms": refresh_token_exp_ms(new["refresh_token"]),
        "live_cred": {"accessKey": new["access_key_id"], "secretKey": new["secret_access_key"],
                      "securitytoken": new["security_token"], "expires_at": new["expiration"]},
        "domain_id": sess.get("domainId") or sess.get("domain_id") or "",
        "user_id": sess.get("user_id") or (sess.get("account") or {}).get("id") or "",
        "user_name": sess.get("user_name") or (sess.get("account") or {}).get("label") or "",
    })
    return _norm(merged)


def get_valid_credential(auto_refresh=True, verbose=False):
    """★主入口，供 hw_codearts.client_credential 调用。
    自愈顺序：
      1) 读 state.vscdb —— 若临时 AK/SK 仍新鲜（含 20min lead 余量）直接用，并把它
         的 refresh 三元组同步进本地缓存（认客户端为最新轮换权威）；
      1.5) vscdb 过期但缓存里有上次刷出的临时凭证且仍新鲜 → 直接复用（省一次
         refresh_token 消耗——它是单次轮换的，一天跑多次只应刷一次）；
      2) 都过期 → 按「候选成对」(缓存三元组, vscdb 三元组) 逐个尝试刷新；
         成功即返回新 credential（已写缓存）；
      3) 全部候选都终态失败 → (None, 需要重开客户端登录的原因)。
    返回 (credential dict | None, source | reason)。"""
    def log(m):
        if verbose:
            print("  [refresh]", m)

    sess, why = load_client_session()
    now_ms = int(time.time() * 1000)

    # 1) 新鲜直接用
    if sess and _exp_ms(sess) > now_ms + REFRESH_LEAD_S * 1000 and _has_material(sess):
        try:
            # 顺手把这份（客户端可能刚刷过的）最新 refresh 三元组写缓存，防落后
            lc = sess["loginContext"]
            save_cache({
                "refresh_token": sess["refresh_token"],
                "code_verifier": lc["pkcePair"]["codeVerifier"],
                "dpop_private_jwk": lc["dpopKeyPair"]["privateKeyJwk"],
                "dpop_public_jwk": lc["dpopKeyPair"].get("publicKeyJwk") or
                    {k: lc["dpopKeyPair"]["privateKeyJwk"][k] for k in ("kty", "crv", "x", "y")},
                "rt_exp_ms": refresh_token_exp_ms(sess["refresh_token"]),
                "live_cred": {"accessKey": sess.get("accessKey") or "",
                              "secretKey": sess.get("secretKey") or "",
                              "securitytoken": sess.get("securitytoken") or "",
                              "expires_at": sess.get("expires_at") or ""},
                "domain_id": sess.get("domainId") or "",
                "user_id": sess.get("user_id") or (sess.get("account") or {}).get("id") or "",
                "user_name": sess.get("user_name") or (sess.get("account") or {}).get("label") or "",
            })
        except Exception:
            pass
        return _norm(sess), "client-fresh"

    # 1.5) vscdb 过期，但缓存里有上次刷出来的临时凭证且仍在有效期 → 直接复用，
    #      不烧 refresh_token（临时 AK/SK 寿命约 2h，每日任务一天跑多次只刷一次）
    cache = load_cache()
    lc_cred = cache.get("live_cred") or {}
    if (lc_cred.get("accessKey") and lc_cred.get("secretKey")
            and _exp_ms(lc_cred) > now_ms + 60 * 1000):
        return _norm(dict(lc_cred, refresh_token=cache.get("refresh_token", ""),
                          loginContext={"pkcePair": {"codeVerifier": cache.get("code_verifier", "")},
                                        "dpopKeyPair": {"privateKeyJwk": cache.get("dpop_private_jwk") or {},
                                                        "publicKeyJwk": cache.get("dpop_public_jwk") or {}}
                                        } if _has_material_cache() else {})), "cache-live"

    if not auto_refresh:
        return (_norm(sess), "client-stale") if sess else (None, why or "无 session")

    # 2) 过期 → 组装候选三元组（缓存优先，其次 vscdb），逐个刷新
    if not (sess and _has_material(sess)) and not _has_material_cache():
        return None, why or ("vscdb 过期且无可用 refresh 材料（未登录过 CodeArts Agent？）")

    cands = []
    if cache.get("refresh_token") and cache.get("code_verifier") and (cache.get("dpop_private_jwk") or {}).get("d"):
        cands.append(("cache", cache["refresh_token"], cache["code_verifier"],
                      cache["dpop_private_jwk"], cache.get("dpop_public_jwk") or
                      {k: cache["dpop_private_jwk"][k] for k in ("kty", "crv", "x", "y")},
                      sess))
    if sess and _has_material(sess):
        lc = sess["loginContext"]
        # 若 vscdb 的 rt 与缓存 rt 相同则不必重复
        if not (cache.get("refresh_token") == sess["refresh_token"]):
            cands.append(("vscdb", sess["refresh_token"], lc["pkcePair"]["codeVerifier"],
                          lc["dpopKeyPair"]["privateKeyJwk"],
                          lc["dpopKeyPair"].get("publicKeyJwk") or
                          {k: lc["dpopKeyPair"]["privateKeyJwk"][k] for k in ("kty", "crv", "x", "y")},
                          sess))

    term_msgs = []
    for (label, rt, cv, priv, pub, base_sess) in cands:
        # refresh_token 终态判断：它自己的 exp 若已过，跳过（省一次注定失败的请求）
        if refresh_token_exp_ms(rt) and refresh_token_exp_ms(rt) < now_ms:
            term_msgs.append("%s: refresh_token 自身已过期" % label)
            continue
        # 用该候选配套三元组拼一份可刷的 session
        trial = dict(base_sess or {})
        trial["refresh_token"] = rt
        trial.setdefault("loginContext", {})
        trial["loginContext"] = {
            "pkcePair": {"codeVerifier": cv},
            "dpopKeyPair": {"privateKeyJwk": priv, "publicKeyJwk": pub}}
        try:
            log("尝试用 %s 的 refresh_token 续期…" % label)
            cred = refresh_from_session(trial, source="refresh:" + label)
            log("续期成功，新 expires_at=%s" % cred.get("expires_at"))
            return cred, "refreshed:" + label
        except RefreshTerminal as e:
            term_msgs.append("%s: %s" % (label, str(e)[:80]))
            log("候选 %s 终态：%s" % (label, str(e)[:80]))
            continue
        except Exception as e:
            term_msgs.append("%s: %s" % (label, str(e)[:80]))
            log("候选 %s 失败（非终态）：%s" % (label, str(e)[:80]))
            continue

    return None, "所有 refresh 候选均失败 →【华为码道需重登】" + " | ".join(term_msgs)


def _has_material_cache():
    c = load_cache()
    return bool(c.get("refresh_token") and c.get("code_verifier") and (c.get("dpop_private_jwk") or {}).get("d"))


# ── 调试命令 ───────────────────────────────────────────────────────────────
def cmd_probe():
    sess, why = load_client_session()
    now_ms = int(time.time() * 1000)
    if not sess:
        print("[session] 读取失败：", why)
    else:
        print("[session] AK/SK  =", bool(sess.get("accessKey")),
              "expires_at =", sess.get("expires_at"),
              "(剩余 %s)" % ("%.1f 小时" % ((_exp_ms(sess) - now_ms) / 3600000) if _exp_ms(sess) else "?"))
        print("[session] refresh_token 有 =", bool(sess.get("refresh_token")),
              " 其自身 exp =",
              datetime.fromtimestamp(refresh_token_exp_ms(sess.get("refresh_token", "")) / 1000,
                                     timezone.utc).strftime("%Y-%m-%d %H:%M") if refresh_token_exp_ms(sess.get("refresh_token", "")) else "?")
        print("[session] PKCE+DPoP 齐 =", _has_material(sess))
    c = load_cache()
    print("[cache] 存在 =", bool(c), ("refresh_token exp=%s" %
          datetime.fromtimestamp(c["rt_exp_ms"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
          if c.get("rt_exp_ms") else "") if c else "")
    return 0


def cmd_refresh():
    cred, src = get_valid_credential(auto_refresh=True, verbose=True)
    if cred:
        print("[OK] 来源=%s 新 expires_at=%s AK=%s…" % (
            src, cred.get("expires_at"), (cred.get("accessKey") or "")[:8]))
        return 0
    print("[FAIL]", src)
    return 1


def cmd_verify():
    rc = cmd_refresh()
    if rc:
        return rc
    # 清掉 hw 的凭证缓存，让它重新走（现在应命中刚刷好写进缓存的新鲜临时凭证）
    import hw_codearts as hw
    hw._CRED = {"tried": False, "cred": None, "why": ""}
    st, data, why = hw.get_delivery("", "")
    if data is not None:
        print("[验真] delivery OK，活动 %d 项 → 续期链路打通 ✅" % len(data.get("items") or []))
        return 0
    print("[验真] delivery 失败：HTTP %s %s" % (st, why))
    return 2


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "probe":
        sys.exit(cmd_probe())
    elif cmd == "refresh":
        sys.exit(cmd_refresh())
    elif cmd == "verify":
        sys.exit(cmd_verify())
    else:
        print(__doc__)
        sys.exit(1)
