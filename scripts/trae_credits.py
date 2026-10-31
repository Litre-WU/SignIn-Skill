#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
trae_credits.py — TRAE（字节跳动 IDE）每日签到领积分
==================================================
产品: TRAE SOLO CN 桌面端（api.trae.cn）
奖励: 每日签到积分（实测单日 150，另有每月登录赠送 500 等 entitlement 包）

★ 协议来源（2026-10-16 分析 GitHub 开源项目 Ebony-Vinyl/dsh-our-free-model 的
  vendor/channel-pack/src/trae-credits.ts + trae.ts，其重构自 trae-mate 的
  checkin.rs/credits.rs，为实测可用的参考实现）:

  状态查询  POST https://api.trae.cn/trae/api/v2/ug/checkin_credits/status  body {}
            → {code:0, checked_in:bool, credits:int, enable:bool,
               streak_days:int, total_credits:int}
  领取      POST https://api.trae.cn/trae/api/v2/ug/checkin_credits/claim    body {}
            → {code:0, message:"success"}   ★响应不含积分数！
  余额      POST https://api.trae.cn/trae/api/v2/pay/ide_user_ent_usage
            body {"require_usage": true, "req_source": 2}
            → user_entitlement_pack_list[] → remain = Σ(credits_limit - credits_amount)

★ 认证（与其它平台都不同）:
  Authorization: Cloud-IDE-JWT <access_token>     ★不是 Bearer！
  外加约 20 个客户端头（对齐 trae-mate build_headers），核心是**设备身份确定性派生**:
    - X-Device-Id:       由 user_id 确定性派生 15 位数字（SHA256("devid:"+uid) 逐字节 %10）
    - X-Market-User-Id:  由 user_id 派生 UUID v4（SHA256("market:"+uid)）
    - Vscode-Sessionid:  由 user_id 派生 64 hex（SHA256("sess:"+uid)）
    - X-Request-Id / X-Tt-Trace-Id: 每次请求随机
  同一账号永远得到同一套设备身份 → 多账号各自独立设备配额。

★ 幂等（关键坑）:
  claim 对「今天已签到」同样返回 {code:0, message:"success"}，与真正领取**无法区分**！
  故必须先查 status.checked_in，已签到则跳过；领取成功后补查 status 取 credits
  （status.credits 实测 150，与积分余额里「签到奖励」包 credits_limit:150 吻合）。

★ 错误分类（对齐 trae-mate cooldown.rs）:
  code 1005 = PlanLimit（套餐不含签到，冷却 12h）；code 9074 = 签到人数过多（300s）；
  HTTP 401 = 会话失效（永久，需重新登录）；HTTP 429 = 软限流（60s）。

配置 trae_config.json: {"access_token": "...", "uid": "...", "device_id": "...", "machine_id": "..."}
  access_token: Cloud-IDE-JWT 值（抓包任意 api.trae.cn 请求的 Authorization 头，
                去掉 "Cloud-IDE-JWT " 前缀）
  uid:          X-Uid 头的值（账号 user_id）
  device_id/machine_id: 可选，缺省时脚本按 uid 确定性派生（等价 trae-mate 行为）

用法:
  python trae_credits.py status        # 只读：签到状态 + 积分余额
  python trae_credits.py auto          # 每日：已签跳过 → 领取 → 回查积分（定时任务用这个）
  python trae_credits.py probe         # 强制领取一次，打印服务端原文
  python trae_credits.py init          # 交互式写入配置（粘贴 Cookie/Authorization）
"""
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE_DIR, "trae_config.json")
HOST = "https://api.trae.cn"
UA_CHECKIN = "VSCode 1.107.1 (TRAE SOLO CN)"
TIMEOUT = 30

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# 端点
PATH_STATUS = "/trae/api/v2/ug/checkin_credits/status"
PATH_CLAIM = "/trae/api/v2/ug/checkin_credits/claim"
PATH_ENT_USAGE = "/trae/api/v2/pay/ide_user_ent_usage"
# 错误码
CODE_PLAN_LIMIT = 1005      # 套餐不含签到（12h 冷却）
CODE_BUSY = 9074            # 签到人数过多（300s）


# ── 配置 ──
def load_cfg():
    if not os.path.exists(CFG_PATH):
        return {}
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ── 保活：跟着桌面端活票走（★只读，绝不代它续期）───────────────────────────
# 2026-10-31 拆机核对 Trae CN 3.4.11（旧注释说的"本机拿不到 refresh_token"是错的）：
#   · 客户端把 OAuth 结果写进 %APPDATA%\Trae CN\User\globalStorage\storage.json，
#     键 `iCubeAuthInfo://<authProviderId>`，值是**字节 byteCrypto 信封**
#     （格式与解法只有一份出处：credential_core.byte_crypto_*）。明文里同时有
#     token(14 天) 与 refreshToken(约 180 天)——就是日志里那条
#     exchangeTokenByAuthCode 的产物；设备 EC 私钥在同前缀的 `://icube-dc:<devid>`。
#   · 客户端**每次启动都会** exchangeTokenByRefreshToken 自动续票（日志实证 response
#     success），所以只要 14 天内开过一次 TRAE，我们读到的就永远是活票。
#   ★不去打 ExchangeToken 续期：store 那支 refreshToken 是**单次轮换**且和用户 IDE
#     共用同一支，我们刷一次就把用户客户端的登录态作废（credential_core 铁律 2）。
IDE_TOKEN_FILES = (os.path.join("~", ".trae-cn", "trae-jwt-token"),
                   os.path.join("~", ".trae", "trae-jwt-token"))


def _store_salt_candidates():
    """从装机 main.js 现取 byteCrypto 的 salt 候选——两张表的名字是压缩器赋的
    （当前叫 Aue/Due），客户端一升级就改名，所以按长度捞表、两两异或去试，
    由信封自带的 sha512 前缀当 oracle，试错只会解不开、不会解出脏数据。"""
    import credential_core as cc
    local = os.environ.get("LOCALAPPDATA", "")
    cands = [os.path.join(local, "Programs", name, "resources", "app", "out", "main.js")
             for name in ("Trae CN", "Trae")]
    for js in cands:
        if not js or not os.path.exists(js):
            continue
        try:
            text = open(js, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        i = text.find("byteCrypto.js")
        if i < 0:
            continue
        salts = cc.byte_crypto_salts(text[max(0, i - 30000):i + 6000])
        if salts:
            return salts
    return []


def _store_tokens():
    """解桌面端 storage.json → [(jwt, 来源标签)]；没装/解不开就返回空（不打扰判读）。"""
    import credential_core as cc
    path = cc.find_first([cc.appdata("Trae CN", "User", "globalStorage", "storage.json"),
                          cc.appdata("Trae", "User", "globalStorage", "storage.json")])
    if not path:
        return []
    salts = _store_salt_candidates()
    if not salts:
        return []
    try:
        store = json.load(open(path, encoding="utf-8", errors="replace"))
    except Exception:
        return []
    out = []
    for k, v in store.items():
        if not k.startswith("iCubeAuthInfo://") or not isinstance(v, str):
            continue
        j = cc.byte_crypto_json(v, salts)
        if isinstance(j, dict) and j.get("token"):
            out.append((str(j["token"]), "storage.json#%s" % k.split("://", 1)[1]))
    return out


def _ide_tokens():
    out = []
    for p in IDE_TOKEN_FILES:
        fp = os.path.expanduser(p)
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                t = f.read().strip()
            if t.count(".") == 2:
                out.append((t, fp))
        except Exception:
            pass
    out.extend(_store_tokens())
    return out


def refresh_cfg_from_client(cfg, verbose=True):
    """config 的 JWT 已过期/临期，而桌面端文件里有**更新的一份** → 换用并回写 config。
    ★回写我们自己的 config 是允许的（铁律 4 禁的是回写官方客户端的凭证文件）。"""
    import credential_core as cc
    cur = (cfg.get("access_token") or "").strip()
    cur_exp = cc.expiry_ms(token=cur)
    if cur_exp and cur_exp - time.time() * 1000 > cc.LEAD_S * 1000:
        return cfg                                  # 现凭证还早，不动（零副作用）
    best, best_exp, src = None, cur_exp or 0, None
    for t, fp in _ide_tokens():
        e = cc.expiry_ms(token=t)
        if e and e > best_exp and t != cur:
            best, best_exp, src = t, e, fp
    if not best:
        if cur_exp and cur_exp < time.time() * 1000:
            print("[鉴权][TRAE] ★config 与桌面端本地凭证里都没有更新的活票 → "
                  "打开一次 TRAE 客户端（它启动即自动续票），脚本下次会自己跟上；"
                  "若你根本没装 TRAE 桌面端，则需在 TRAE 网页端登录后抓 Authorization 跑 init")
        return cfg
    cfg = dict(cfg)
    cfg["access_token"] = best
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[警告] 回写 trae_config.json 失败: %s" % e)
    if verbose:
        print("[保活][TRAE] config 的 JWT 已过期/临期，改用桌面端更新的这份（%s，到期 %s），已回写 config"
              % (os.path.basename(src), cc.fmt_exp(best_exp)))
    return cfg


def auth_report(cfg):
    """统一 `[鉴权]` 行（只做加法，原有失效措辞一律保留，日报判读靠它们）。"""
    import credential_core as cc
    tok = (cfg.get("access_token") or "").strip()
    exp = cc.expiry_ms(token=tok)
    cc.auth_line("TRAE", source="trae_config.json(Cloud-IDE-JWT 14天，跟着桌面端活票走)",
                 expires_at=exp, refreshable=False,
                 note="桌面端 storage.json 里的活票只读跟用；store 那支 refreshToken 与"
                      "用户 IDE 共用且单次轮换，本脚本不代刷（刷了会把客户端登录态作废）")
    return exp


# ── 设备身份确定性派生（逐行对齐 dsh trae.ts seededStream）──
def _seeded_stream(seed, salt, nbytes):
    """SHA256(f'{salt}:{seed}' + counterBE32) 串联，与 JS 版逐字节一致。"""
    prefix = ("%s:%s" % (salt, seed)).encode("utf-8")
    out = bytearray()
    counter = 0
    while len(out) < nbytes:
        h = hashlib.sha256()
        h.update(prefix)
        h.update(counter.to_bytes(4, "big"))
        out.extend(h.digest())
        counter += 1
    return bytes(out[:nbytes])


def derive_device_id_15(uid):
    """15 位数字设备 ID：每个字节 %10。"""
    return "".join(str(b % 10) for b in _seeded_stream(uid, "devid", 15))


def derive_market_user_id(uid):
    """UUID v4（version/variant 位按 RFC 4122 修正）。"""
    bs = bytearray(_seeded_stream(uid, "market", 16))
    bs[6] = (bs[6] & 0x0F) | 0x40
    bs[8] = (bs[8] & 0x3F) | 0x80
    hx = bs.hex()
    return "%s-%s-%s-%s-%s" % (hx[0:8], hx[8:12], hx[12:16], hx[16:20], hx[20:32])


def derive_session_id(uid):
    """64 hex session id。"""
    return _seeded_stream(uid, "sess", 32).hex()


def checkin_headers(cfg):
    """签到专用完整客户端头（对齐 trae-mate build_headers / dsh traeCheckinHeaders）。"""
    uid = cfg.get("uid", "")
    if not uid:
        raise RuntimeError("配置缺少 uid（抓包请求头 X-Uid 的值）")
    token = cfg.get("access_token", "")
    if not token:
        raise RuntimeError("配置缺少 access_token")
    trace_id = "00-%s-01" % uuid.uuid4().hex[:16]
    return {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN",
        "User-Agent": UA_CHECKIN,
        "Authorization": "Cloud-IDE-JWT %s" % token,
        "X-Market-Client-Id": "VSCode 1.107.1",
        "X-Market-User-Id": derive_market_user_id(uid),
        "X-User-Region": "CN",
        "X-Device-Id": cfg.get("device_id") or derive_device_id_15(uid),
        "X-Lgw-Req-Sdk-Type": "3",
        "Package-Type": "stable_cn",
        "X-Lscbd-Aid": "787976",
        "X-Lscbd-Platform": "windows",
        "App-Version": "0.1.52",
        "X-Tt-Trace-Id": trace_id,
        "Vscode-Sessionid": derive_session_id(uid),
        "X-Request-Id": str(uuid.uuid4()),
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "none",
    }


# ── HTTP ──
def _decompress(raw, encoding):
    """按 Content-Encoding 解压（gzip/deflate 标准库可解；br 需 brotli，未装则报错）。
    ★TRAE 的余额端点实测返 gzip（status 端点不压缩）——不解压会把合法响应当成空body。"""
    enc = (encoding or "").lower().strip()
    if enc in ("", "identity"):
        return raw
    if enc == "gzip":
        import gzip
        return gzip.decompress(raw)
    if enc == "deflate":
        import zlib
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    if enc == "br":
        try:
            import brotli
            return brotli.decompress(raw)
        except ImportError:
            raise RuntimeError("响应为 br 压缩但未装 brotli（pip install brotli）")
    return raw


def post(path, cfg, body_dict):
    url = HOST + path
    data = json.dumps(body_dict).encode() if body_dict is not None else b"{}"
    req = urllib.request.Request(url, data=data, headers=checkin_headers(cfg), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
            raw = resp.read()
            try:
                raw = _decompress(raw, resp.headers.get("Content-Encoding"))
            except Exception as e:
                return resp.status, {"_error": "解压失败: %s" % e}
            return resp.status, json.loads(raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            raw = _decompress(raw, e.headers.get("Content-Encoding") if e.headers else None)
        except Exception:
            pass
        try:
            return e.code, json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return e.code, {"_raw": raw[:300].decode("utf-8", "replace")}
    except Exception as e:
        return 0, {"_error": "%s: %s" % (type(e).__name__, e)}


def _num(v):
    return v if isinstance(v, (int, float)) else 0


# ── 业务 ──
def fetch_status(cfg):
    """查询签到状态。返回 dict 或 None（失败）。"""
    st, body = post(PATH_STATUS, cfg, {})
    if st == 0 or body.get("_error"):
        return None
    code = body.get("code")
    if code not in (0, None):
        return None
    return body


def claim(cfg):
    """执行领取。返回 (kind, info)。kind: claimed/already/failed/need-status"""
    st, body = post(PATH_CLAIM, cfg, {})
    if st == 0 or body.get("_error"):
        return "failed", body.get("_error") or "network error"
    code = body.get("code")
    msg = body.get("message") or body.get("msg") or ""
    if code == 0:
        # ★claim 响应不含积分 → 回查 status 取 credits
        stt = fetch_status(cfg)
        credit = _num(stt.get("credits")) if stt else 0
        streak = _num(stt.get("streak_days")) if stt else 0
        return "claimed", {"credit": credit, "streak_days": streak, "message": msg}
    if code == CODE_BUSY:
        return "failed", "签到人数过多（code 9074），稍后重试"
    if code == CODE_PLAN_LIMIT:
        return "failed", "套餐不含签到资格（code 1005）"
    if st == 401:
        return "failed", "会话失效（HTTP 401），请重新登录 TRAE"
    return "failed", "code=%s %s" % (code, msg)


def fetch_balance(cfg):
    """积分余额。返回 (total, packages) 或 None。"""
    st, body = post(PATH_ENT_USAGE, cfg, {"require_usage": True, "req_source": 2})
    if st == 0 or body.get("_error"):
        return None
    packs = body.get("user_entitlement_pack_list")
    if not isinstance(packs, list):
        return None
    total = 0
    out = []
    for item in packs:
        if not isinstance(item, dict):
            continue
        base = item.get("entitlement_base_info") or {}
        quota = base.get("quota") or {}
        limit = _num(quota.get("credits_limit"))
        if limit <= 0:
            continue
        usage = item.get("usage") or {}
        used = _num(usage.get("credits_amount"))
        expire = _num(item.get("expire_time"))
        name = base.get("display_desc") or item.get("display_desc") or "资源包"
        out.append({"name": name, "remaining": limit - used, "total": limit,
                    "expire_ms": expire * 1000 if expire > 0 else None})
        total += limit - used
    return total, out


# ── 命令 ──
def cmd_status(cfg):
    stt = fetch_status(cfg)
    if stt is None:
        print("[status] 查询失败：凭据无效或网络异常（检查 trae_config.json）")
        return 1
    print("[status] active=%s today_checked_in=%s daily_credits=%s streak_days=%s total_credits=%s" % (
        stt.get("enable"), stt.get("checked_in"), stt.get("credits"),
        stt.get("streak_days"), stt.get("total_credits")))
    bal = fetch_balance(cfg)
    if bal:
        total, packs = bal
        print("[balance] 剩余合计 %s" % total)
        for p in packs[:10]:
            exp = ""
            if p["expire_ms"]:
                import datetime
                exp = " 到期=%s" % datetime.datetime.fromtimestamp(
                    p["expire_ms"] / 1000).strftime("%Y-%m-%d")
            print("   - %s: %s/%s%s" % (p["name"], p["remaining"], p["total"], exp))
    return 0


def cmd_auto(cfg):
    stt = fetch_status(cfg)
    if stt is None:
        print("[auto] 状态查询失败，跳过（不盲领）")
        return 1
    if stt.get("checked_in"):
        print("[auto] 今日已签到（checked_in=true），幂等跳过")
        return 0
    kind, info = claim(cfg)
    if kind == "claimed":
        print("[auto] 领取成功：+%s 积分（连续 %s 天）" % (info["credit"], info["streak_days"]))
        return 0
    print("[auto] 领取失败：%s" % info)
    return 1


def cmd_probe(cfg):
    st, body = post(PATH_STATUS, cfg, {})
    print("[probe status] HTTP %s :: %s" % (st, json.dumps(body, ensure_ascii=False)[:500]))
    st2, body2 = post(PATH_CLAIM, cfg, {})
    print("[probe claim]  HTTP %s :: %s" % (st2, json.dumps(body2, ensure_ascii=False)[:500]))
    return 0


def cmd_init(argv=None):
    """写配置。支持：init --token <access_token> --uid <uid>（reqable_hunt 非交互落地用）；
    不带参数则进入交互式粘贴。"""
    argv = argv or []
    token = uid = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--token" and i + 1 < len(argv):
            token = argv[i + 1]; i += 2
        elif argv[i] == "--uid" and i + 1 < len(argv):
            uid = argv[i + 1]; i += 2
        else:
            i += 1
    if not token:
        print("粘贴 TRAE 登录态（任一 api.trae.cn 请求的 Authorization 值 或 'token|uid'）：")
        line = input("> ").strip()
        if "|" in line and "=" not in line.split("|")[0]:
            token, uid = [x.strip() for x in line.split("|", 1)]
        else:
            token = line
    token = token.replace("Cloud-IDE-JWT ", "").strip()
    if not token:
        print("[init] 缺少 access_token，放弃")
        return 1
    if not uid:
        uid = input("uid（X-Uid 头的值，必填）: ").strip()
    if not uid:
        print("[init] 缺少 uid（设备身份派生必需），放弃")
        return 1
    cfg = load_cfg()
    cfg["access_token"] = token
    cfg["uid"] = uid
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("[init] 已写入 %s（token=%s… uid=%s）" % (CFG_PATH, token[:12], uid))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "init":
        return cmd_init(sys.argv[2:])
    cfg = refresh_cfg_from_client(load_cfg())
    if not cfg.get("access_token"):
        print("[x] 未配置 trae_config.json（需 access_token + uid）。用法见文件头说明。")
        return 1
    if cmd == "keepalive":
        auth_report(cfg)
        return 0
    auth_report(cfg)
    if cmd == "status":
        return cmd_status(cfg)
    if cmd == "auto":
        return cmd_auto(cfg)
    if cmd == "probe":
        return cmd_probe(cfg)
    print("[x] 未知命令: %s（status/auto/probe/keepalive/init）" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
