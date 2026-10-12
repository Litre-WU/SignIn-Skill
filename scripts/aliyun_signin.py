#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aliyun_signin.py — 阿里云盘（aliyundrive）每日签到
=================================================
浏览器已登录 www.aliyundrive.com → 本机直接取凭证，无需扫码、无需抓包。

★凭证来源：Chromium **Local Storage** 的 leveldb。
  与 Cookies 库不同，Local Storage 的 .ldb/.log 文件**不被运行中的浏览器独占锁**，
  随时可读 → 不依赖 CDP 9222、不依赖用户关浏览器。
  ★★坑：leveldb 用前缀压缩，完整 key（`<origin>\\x00\\x01<keyname>`）在 .ldb 里
  不一定连续出现 → 按 key 正则搜索会 0 命中。改为**按值搜索**：
  搜 `"refresh_token":"<32位hex>"` 指纹，再向两侧用括号配对扩出完整 token JSON。

★刷新不会使旧 refresh_token 失效（2026-10-12 实测：同一代 token 连刷两次、
  以及两代 token 并存均返回 200）→ **与浏览器 Web 端不互斥**，不会把浏览器踢下线。

接口（已实测打通）:
  POST https://auth.aliyundrive.com/v2/account/token
       body {"grant_type":"refresh_token","refresh_token":"..."}
       → access_token / refresh_token / expires_in(7200)
  POST https://member.aliyundrive.com/v1/activity/sign_in_list
       body {"_rx-s":"mobile"}  header Authorization: Bearer <access_token>
       → **兼做签到与查状态**（幂等：重复调用 signInCount 不递增）
       result: signInCount / isReward / signInLogs[{day,status,calendarMonth,
               calendarDay,rewardAmount,type,reward{name,description}}]
  POST https://member.aliyundrive.com/v1/activity/sign_in_reward
       body {"signInDay":<day>,"_rx-s":"mobile"} → 领奖
       ★已知限制：当前被服务端按客户端版本门控，返回 403「请升级最新客户端访问」。
         签到本身不受影响；仅在 isReward 有待领时尝试，403 记录为受限、不算失败。

命令行:
  python aliyun_signin.py auto           # 取凭证 → 签到 → 领奖（默认）
  python aliyun_signin.py status         # 只读播报（今日是否已签/累计天数）
  python aliyun_signin.py probe          # 只探凭证来源 + 原始签到响应（不写状态）
  python aliyun_signin.py init <rt>      # 手动写 refresh_token（32位hex）
  python aliyun_signin.py init auto      # 强制从浏览器重新提取并写配置
"""
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.request import ProxyHandler, build_opener

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
CFG = os.path.join(BASE, "aliyun_config.json")
STATE = os.path.join(BASE, "aliyun_sign_state.json")

# 外网直连（与 c189_signin.py 一致；沙箱 http_proxy 只拦 localhost 才需绕）
opener = build_opener(ProxyHandler({}))

AUTH_URL = "https://auth.aliyundrive.com/v2/account/token"
MEMBER_URL = "https://member.aliyundrive.com/v1/activity"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 阿里云盘 token JSON 指纹：refresh_token 是 32 位小写 hex
RT_PAT = re.compile(rb'"refresh_token"\s*:\s*"([0-9a-f]{32})"')
# leveldb 目录里无需解析的固定文件
LS_SKIP = {"LOCK", "CURRENT", "LOG", "LOG.old"}


# ------------------------------------------------------------------ 配置/状态
def load_cfg():
    if not os.path.isfile(CFG):
        return {}
    try:
        with open(CFG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    cfg["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_state():
    if not os.path.isfile(STATE):
        return {}
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ HTTP
def http_post(url, body, headers=None, timeout=20):
    """POST JSON，返回 (code, text)。非 2xx 走 HTTPError 分支，不抛异常。"""
    req = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    req.add_header("Referer", "https://www.aliyundrive.com/")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception:
            return e.code, "HTTP %s" % e.code
    except Exception as e:
        return -1, "EXC %s" % e


# ------------------------------------------------------------------ 浏览器提取
def browser_ud():
    """浏览器 User Data 目录（复用 browser_cookies 的探测逻辑）。"""
    try:
        import browser_cookies
        ud = browser_cookies.browser_ud()
        if ud:
            return ud
    except Exception:
        pass
    local = os.environ.get("LOCALAPPDATA", "")
    for name in ("Thorium", "Chromium"):
        p = os.path.join(local, name, "User Data")
        if os.path.isdir(p):
            return p
    return ""


def _ls_dirs():
    """候选 Local Storage leveldb 目录（Default + Profile N）。"""
    ud = browser_ud()
    if not ud:
        return []
    dirs = [os.path.join(ud, "Default", "Local Storage", "leveldb")]
    dirs += sorted(glob.glob(os.path.join(ud, "Profile *", "Local Storage", "leveldb")))
    return [d for d in dirs if os.path.isdir(d)]


def _match_brace(data, start):
    """从 data[start]=='{' 配对到对应 '}'，返回下标；跳过字符串内的括号。"""
    depth, i, n = 0, start, len(data)
    while i < n:
        c = data[i:i + 1]
        if c == b'"':
            i += 1
            while i < n:
                if data[i:i + 1] == b"\\":
                    i += 2
                    continue
                if data[i:i + 1] == b'"':
                    i += 1
                    break
                i += 1
            continue
        if c == b"{":
            depth += 1
        elif c == b"}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _expand_json(data, m):
    """从 refresh_token 指纹位置向前找 '{'、向后配对 '}'，解出完整 token JSON。"""
    limit = max(0, m.start() - 8192)
    for start in range(m.start() - 1, limit, -1):
        if data[start:start + 1] != b"{":
            continue
        end = _match_brace(data, start)
        if end is None:
            continue
        try:
            obj = json.loads(data[start:end + 1].decode("utf-8", "replace"))
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("refresh_token") and obj.get("access_token"):
            return obj
    return None


def extract_browser_token(verbose=False):
    """从浏览器 Local Storage 里提取阿里云盘 token JSON → dict 或 None。"""
    best = None
    for d in _ls_dirs():
        prof = os.path.basename(os.path.dirname(os.path.dirname(d)))
        for f in sorted(glob.glob(os.path.join(d, "*"))):
            if not os.path.isfile(f) or os.path.basename(f) in LS_SKIP:
                continue
            try:
                with open(f, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            for m in RT_PAT.finditer(data):
                tok = _expand_json(data, m)
                if not tok:
                    continue
                tok["_src"] = "%s/%s" % (prof, os.path.basename(f))
                if best is None or len(tok.get("expire_time") or "") > len(best.get("expire_time") or ""):
                    best = tok
                    if verbose:
                        print("    [提取] %s → refresh_token=%s…" % (tok["_src"], tok["refresh_token"][:8]))
    return best


# ------------------------------------------------------------------ token
def _iso_after(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=int(seconds))).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ttl_ok(expire_time, margin=600):
    """access_token 是否还有 margin 秒以上有效期。"""
    if not expire_time:
        return False
    try:
        s = str(expire_time).replace("Z", "+00:00")
        exp = datetime.fromisoformat(s)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return (exp - datetime.now(timezone.utc)).total_seconds() > margin
    except Exception:
        return False


def refresh_token(rt):
    """refresh_token → access_token。返回 (ok, dict, msg)。"""
    code, txt = http_post(AUTH_URL, {"grant_type": "refresh_token", "refresh_token": rt})
    try:
        j = json.loads(txt)
    except Exception:
        return False, {}, "HTTP %s 非JSON: %s" % (code, txt[:120])
    if j.get("access_token"):
        return True, j, ""
    return False, j, "%s / %s" % (j.get("code"), j.get("message") or txt[:100])


def ensure_token(cfg, verbose=True):
    """拿一个可用 access_token：优先配置里的，失败回退浏览器重新提取。

    返回 (access_token, info_dict, src_desc)；失败时 access_token 为 None。
    命中即回存配置（refresh_token 一并更新，便于下次直接复用）。
    """
    cands = []
    if cfg.get("refresh_token"):
        cands.append(("config", {k: cfg.get(k) for k in
                                 ("refresh_token", "access_token", "expire_time")}))
    b = extract_browser_token(verbose)
    if b and b.get("refresh_token") and b.get("refresh_token") != cfg.get("refresh_token"):
        cands.append(("browser", b))

    if not cands:
        return None, cfg, "配置无 refresh_token，且浏览器 Local Storage 里未找到阿里云盘 token"

    errs = []
    for src, c in cands:
        merged = dict(c)
        # access_token 仍有效 → 直接复用，不刷新（少一次请求，也少一次凭证轮换）
        if c.get("access_token") and _ttl_ok(c.get("expire_time")):
            tag = "(access有效)"
        else:
            ok, j, msg = refresh_token(c["refresh_token"])
            if not ok:
                errs.append("%s:%s" % (src, msg))
                continue
            for k in ("access_token", "refresh_token", "expires_in"):
                if j.get(k):
                    merged[k] = j[k]
            merged["expire_time"] = _iso_after(j.get("expires_in") or 7200)
            if j.get("user_id"):
                merged["user_id"] = j["user_id"]
            tag = "(已刷新)"

        # ★命中即回存（复用分支也要存，否则配置永远为空、每次都得靠浏览器）
        for k in ("refresh_token", "access_token", "expire_time", "expires_in"):
            if merged.get(k):
                cfg[k] = merged[k]
        cfg["source"] = src
        if src == "browser":
            for k in ("user_name", "user_id", "nick_name", "default_drive_id"):
                if merged.get(k):
                    cfg[k] = merged[k]
        save_cfg(cfg)
        return merged["access_token"], merged, "%s%s" % (src, tag)

    return None, cfg, " ；".join(errs)


# ------------------------------------------------------------------ 签到
def sign_in_list(at):
    """签到 + 查状态（幂等）。返回 (http_code, result_dict|None, raw_text)。"""
    code, txt = http_post(MEMBER_URL + "/sign_in_list", {"_rx-s": "mobile"},
                          {"Authorization": "Bearer " + at})
    try:
        j = json.loads(txt)
    except Exception:
        return code, None, txt[:200]
    if isinstance(j, dict) and isinstance(j.get("result"), dict):
        return code, j["result"], txt
    return code, None, txt[:200]


def claim_reward(at, day):
    """领当日奖励。返回 (ok, msg)。403=服务端按客户端版本门控（已知限制）。"""
    code, txt = http_post(MEMBER_URL + "/sign_in_reward",
                          {"signInDay": day, "_rx-s": "mobile"},
                          {"Authorization": "Bearer " + at})
    if code == 200:
        return True, "HTTP 200 %s" % txt[:120]
    if code == 403:
        return False, "HTTP 403 领奖被客户端版本门控（已知限制，签到不受影响）"
    return False, "HTTP %s %s" % (code, txt[:120])


CN = "零一二三四五六七八九"
# status 语义（实测）：normal=已签到，miss=未签/未来日
NOT_SIGNED = {"miss", "notsign", "not_sign", "unsigned", ""}


def _cn2int(v):
    """「十月」→10、「12」→12、「十一」→11。解析不了返回 None。"""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    t = str(v).strip().rstrip("月")
    if not t:
        return None
    if t.isdigit():
        return int(t)
    if t == "十":
        return 10
    if t.startswith("十") and len(t) == 2 and t[1] in CN:
        return 10 + CN.index(t[1])
    if "十" in t:
        a, _, b = t.partition("十")
        try:
            return CN.index(a) * 10 + (CN.index(b) if b else 0)
        except ValueError:
            return None
    if len(t) == 1 and t in CN:
        return CN.index(t)
    return None


def today_entry(logs, now=None):
    """在 signInLogs 里找「今天那条已签到记录」。

    ★坑：calendarMonth 是**中文**（"十月"）、calendarDay 是**字符串**（"12"），
      直接 int() 会全军覆没 → 走 _cn2int。
    ★判据：日期命中 且 status 不是 miss（未签/未来日也会出现在 logs 里）。
    """
    n = now or datetime.now()
    for e in logs or []:
        if _cn2int(e.get("calendarMonth")) != n.month or _cn2int(e.get("calendarDay")) != n.day:
            continue
        if str(e.get("status") or "").lower() in NOT_SIGNED:
            continue
        return e
    return None


# ------------------------------------------------------------------ 命令
def cmd_init(arg):
    if arg == "auto":
        tok = extract_browser_token(verbose=True)
        if not tok:
            print("[失败] 浏览器 Local Storage 里未找到阿里云盘 token（请在浏览器登录 www.aliyundrive.com）")
            return 3
        cfg = load_cfg()
        for k in ("refresh_token", "access_token", "expire_time", "user_name", "user_id", "nick_name"):
            if tok.get(k):
                cfg[k] = tok[k]
        cfg["source"] = "browser"
        save_cfg(cfg)
        print("[ok] 已从浏览器提取并写入 aliyun_config.json：user=%s rt=%s… 来源=%s" %
              (cfg.get("user_name") or cfg.get("nick_name") or "?", cfg["refresh_token"][:8], tok.get("_src")))
        return 0

    rt = (arg or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{32}", rt):
        print("[失败] refresh_token 应是 32 位十六进制，收到: %r" % arg)
        print("       用法: aliyun_signin.py init <32位refresh_token> | init auto")
        return 2
    ok, j, msg = refresh_token(rt.lower())
    if not ok:
        print("[失败] 该 refresh_token 校验不通过: %s" % msg)
        return 3
    cfg = load_cfg()
    cfg.update({"refresh_token": rt.lower(), "access_token": j["access_token"],
                "refresh_token_new": j.get("refresh_token") or rt.lower(),
                "expire_time": _iso_after(j.get("expires_in") or 7200),
                "expires_in": j.get("expires_in"), "source": "manual"})
    if j.get("refresh_token"):
        cfg["refresh_token"] = j["refresh_token"]
    save_cfg(cfg)
    print("[ok] refresh_token 校验通过并写入 aliyun_config.json（有效期 %ss）" % j.get("expires_in"))
    return 0


def cmd_status():
    cfg = load_cfg()
    at, info, src = ensure_token(cfg, verbose=False)
    if not at:
        print("【阿里云盘登录失效】%s" % src)
        return 3
    code, res, raw = sign_in_list(at)
    if res is None:
        print("[失败] sign_in_list HTTP %s: %s" % (code, raw))
        return 3
    n = datetime.now()
    ent = today_entry(res.get("signInLogs"), n)
    rw = (ent or {}).get("reward") or {}
    print("账号=%s  凭证=%s" % (cfg.get("user_name") or cfg.get("nick_name") or "?", src))
    print("累计签到=%s  今日已签=%s  待领奖=%s" %
          (res.get("signInCount"), "是" if ent else "否", res.get("isReward")))
    if ent:
        print("今日: 第%s天 status=%s 奖励=%s(%s)" %
              (ent.get("day"), ent.get("status"), rw.get("name") or "-", ent.get("rewardAmount") or "-"))
    return 0


def cmd_probe():
    cfg = load_cfg()
    print("== 浏览器 Local Storage 提取 ==")
    tok = extract_browser_token(verbose=True)
    if tok:
        print("  命中: user_name=%s user_id=%s rt=%s… 来源=%s" %
              (tok.get("user_name"), tok.get("user_id"), tok["refresh_token"][:8], tok.get("_src")))
    else:
        print("  未命中（请在浏览器登录 www.aliyundrive.com 后重试）")
    print("  配置里已有 rt=%s（source=%s）" %
          ((cfg.get("refresh_token") or "无")[:8], cfg.get("source") or "-"))
    print()
    at, info, src = ensure_token(cfg, verbose=False)
    if not at:
        print("== 取 access_token 失败 ==\n  %s" % src)
        return 3
    print("== 签到响应（只读展示，不写状态）==")
    print("  凭证来源: %s" % src)
    code, res, raw = sign_in_list(at)
    print("  HTTP %s" % code)
    print(json.dumps(res or raw, ensure_ascii=False, indent=2)[:2000])
    return 0


def cmd_auto():
    cfg = load_cfg()
    at, info, src = ensure_token(cfg, verbose=False)
    if not at:
        print(json.dumps({"ok": False, "platform": "阿里云盘", "msg": "登录失效: %s" % src},
                         ensure_ascii=False))
        print("【阿里云盘登录失效】%s —— 请在浏览器打开 www.aliyundrive.com 重新登录，"
              "或执行: aliyun_signin.py init <32位refresh_token>" % src)
        return 3

    code, res, raw = sign_in_list(at)
    if res is None:
        print(json.dumps({"ok": False, "platform": "阿里云盘",
                          "msg": "sign_in_list HTTP %s: %s" % (code, raw)}, ensure_ascii=False))
        print("[失败] 阿里云盘签到请求失败 HTTP %s %s" % (code, raw))
        return 3

    n = datetime.now()
    daykey = "%d-%d" % (n.month, n.day)
    ent = today_entry(res.get("signInLogs"), n)
    st = load_state()
    first = bool(ent) and st.get("last_daykey") != daykey
    if ent:
        st.update({"last_daykey": daykey, "last_count": res.get("signInCount"),
                   "last_day": ent.get("day"), "last_run": time.strftime("%Y-%m-%d %H:%M:%S")})
        save_state(st)

    rw = (ent or {}).get("reward") or {}
    reward_msg = ""
    if res.get("isReward") and ent is not None:
        ok_r, reward_msg = claim_reward(at, ent.get("day") or res.get("signInCount"))
        if ok_r:
            reward_msg = "奖励已领取: %s" % reward_msg
        else:
            reward_msg = "【领奖受限】%s" % reward_msg

    out = {
        "ok": bool(ent),
        "platform": "阿里云盘",
        "user": cfg.get("user_name") or cfg.get("nick_name") or "?",
        "cred_src": src,
        "signed_today": bool(ent),
        "first_today": first,
        "sign_in_count": res.get("signInCount"),
        "cycle_day": (ent or {}).get("day"),
        "reward": rw.get("name") or "",
        "reward_type": (ent or {}).get("type"),
        "reward_amount": (ent or {}).get("rewardAmount"),
        "reward_claim": reward_msg,
    }
    print(json.dumps(out, ensure_ascii=False))

    if ent:
        desc = rw.get("name") or ("%s×%s" % (ent.get("type") or "-", ent.get("rewardAmount") or "-"))
        tag = "签到成功" if first else "今日已签（幂等，未重复计数）"
        print("[ok] 阿里云盘 %s｜累计 %s 天｜第 %s 天｜奖励 %s%s" %
              (tag, res.get("signInCount"), ent.get("day"), desc,
               "｜" + reward_msg if reward_msg else ""))
    else:
        print("[失败] 阿里云盘签到后仍未查到今日记录：HTTP %s %s" % (code, str(res)[:200]))
    return 0 if ent else 3


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if cmd == "init":
        if len(sys.argv) < 3:
            print("[中断] 用法: aliyun_signin.py init <32位refresh_token> | init auto")
            return 2
        return cmd_init(sys.argv[2])
    if cmd == "status":
        return cmd_status()
    if cmd == "probe":
        return cmd_probe()
    if cmd == "auto":
        return cmd_auto()
    print("未知命令: %s（支持 auto/status/probe/init）" % cmd)
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
