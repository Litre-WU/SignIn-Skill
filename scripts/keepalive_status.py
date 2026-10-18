#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
keepalive_status.py — 全平台账号保活体检（★纯只读，不打任何业务写接口）
=====================================================================
为什么需要：签到脚本只在**已经 401 之后**才暴露凭证坏了，而坏掉的当天就领不到东西。
凭证寿命差异极大（京东 sdtoken 1800s / MiniMax AT 约 1h / TRAE JWT 7 天 / Qoder 30 天 /
美团 wm_logintoken 无到期字段），所以需要一张"还剩多久"的表，
在失效**之前**就知道该让用户在哪个客户端里再登录一次。

设计约束：
  · 只读本地文件/config/sqlite；**不发业务请求**（要探活的留给各脚本自己的 status 子命令）
  · 一个平台读失败绝不影响其他平台（逐行 try，异常只标注该行）
  · ★**只有「根凭证」参与临期/过期判定**。根凭证＝坏了只能用户重新登录的那一层
    （TRAE 7 天 JWT、Qoder 30 天、LobsterAI 30 天、华为 rt_exp_ms、小浣熊 token_exp、ZCode jwt）。
    派生短效凭证（阿里云盘 AT 7200s、MiniMax AT 约 1h、华为临时 AK/SK 约 2h、京东 sdtoken 1800s、
    天翼 sessionKey）寿命本来就短，**按 3 天阈值报它们等于天天误报** → 只标 OK/自动轮换。
  · 状态语义：OK / 自动轮换（有每日同步或客户端自续，没到期值也安全）/ 临期 / 已过期 /
    无到期值（服务端没给，≠坏了）/ 未安装 / 缺凭证
  · 到期时间一律走 credential_core.expiry_ms（★只认服务端给的值，解不出就说未知，不猜）

用法：
  python keepalive_status.py            # 全表
  python keepalive_status.py --warn     # 只列需要动作的行（临期/已过期/缺凭证/高危）
退出码：0 无需动作；2 仅临期；1 存在已过期或缺凭证。
"""
import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import credential_core as cc

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CFG = lambda name: os.path.join(BASE_DIR, name)


def _json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _age_days(v):
    """config 里"写入时间"类字段 → 已过去多少天（无到期值时当旁证）。"""
    ms = cc.to_ms(v)
    if not ms:
        try:
            ms = int(float(v)) * 1000
        except Exception:
            return None
    return round((int(time.time() * 1000) - ms) / 86400000.0, 1)


def _mtime_age_days(p):
    try:
        return round((time.time() - os.path.getmtime(p)) / 86400.0, 1)
    except Exception:
        return None


# ── 各平台读数：source / exp_ms / root / refreshable / note ─────────────────
def p_gr():
    c = _json(CFG("gr_config.json"))
    if not c.get("token"):
        return {"source": "无", "note": "缺 gr_config.json"}
    return {"source": "gr_config.json", "exp_ms": cc.expiry_ms(token=c.get("token")), "root": False,
            "refreshable": True,
            "note": "小程序 token 非 JWT、无到期字段；★RT 已接线（401 自动续）——写入距今 %s 天"
                    % _age_days(c.get("token_updated"))}


def p_libao():
    c = _json(CFG("libao_config.json"))
    if not c.get("authorization"):
        return {"source": "无", "note": "缺 libao_config.json"}
    return {"source": "libao_config.json", "exp_ms": None, "root": True, "refreshable": False,
            "note": "★无 RT，只有响应头被动更新；抓包于 %s 天前（经验寿命约 30 天）→ "
                    "到期前手工重抓一次任意业务请求即可续" % _age_days(c.get("created"))}


def p_csair():
    c = _json(CFG("csair_config.json"))
    return {"source": "csair_config.json", "exp_ms": None, "root": True, "refreshable": None,
            "note": "小程序 sessionId **无服务端刷新**（寿命数小时~1 天，要重开小程序抓 /mini/api/login/login）；"
                    "H5 signToken 失效时脚本会自动账号密码重登（Playwright 约 30s）→ 结构性半自动",
            "risk": True}


def p_meituan():
    c = _json(CFG("mt_config.json"))
    if not c.get("wm_logintoken"):
        return {"source": "无", "note": "缺 mt_config.json（美团四件套共用）"}
    # _imported_at 带尾注（"2026-10-09 13:47 (总控…)"），解不出就照原文显示，别打成 None 天前
    imp = str(c.get("_imported_at") or "-").split("(")[0].strip()
    age = _age_days(c.get("_imported_at"))
    return {"source": "mt_config.json", "exp_ms": None, "root": True, "refreshable": False,
            "note": "wm_logintoken 无 RT、无到期字段；导入于 %s%s——**四件套一起坏**，"
                    "失效只能重抓（reqable_hunt.py harvest --apply）"
                    % (imp, ("（距今 %s 天）" % age) if age is not None else ""),
            "risk": True}


def p_ms():
    c = _json(CFG("ms_config.json"))
    if not c.get("cookie"):
        return {"source": "无", "note": "缺 ms_config.json"}
    return {"source": "ms_config.json", "exp_ms": None, "root": False, "refreshable": True,
            "note": "cookie 由第 0 步 cookie_sync 每天从浏览器重取（自身寿命 30~60 天）→ 自动轮换"}


def p_juejin():
    return {"source": "浏览器 9222", "exp_ms": None, "root": True, "refreshable": None,
            "note": "无凭证文件，每次靠 9222 里已登录的掘金页面现取 bdms 签名；"
                    "★headless 临时壳过不了滑块 → 依赖你带着 `--remote-debugging-port=9222` 开 Thorium",
            "risk": True}


def p_workbuddy():
    c = _json(CFG("workbuddy_intl_config.json"))
    return {"source": "委托 buddy_station + intl config", "exp_ms": None, "root": True, "refreshable": False,
            "note": "国内走外部 skill 的三通道择优（本机登录态/网页会话/长效令牌）；"
                    "国际版 cookie 长度 %d，★.cn 登录态在 .ai 域无效、需独立账号"
                    % len(c.get("cookie") or "")}


def p_xhx():
    c = _json(CFG("xhx_config.json"))
    return {"source": "xhx_config.json", "exp_ms": cc.expiry_ms(expires_at=c.get("token_exp")),
            "root": True, "refreshable": bool(c.get("refresh_token")),
            "note": "AT 约 3h（剩余<30min 自动续）；表里的到期值是 token_exp（长效那层）。"
                    "★RT 来自浏览器**会话级** cookie，只有带 9222 的真浏览器能同步到"}


def p_loomy():
    c = _json(CFG("loomy_config.json"))
    if not c.get("cookie"):
        return {"source": "无", "note": "缺 loomy_config.json"}
    return {"source": "loomy_config.json", "exp_ms": None, "root": False, "refreshable": True,
            "note": "web cookie 由 cookie_sync 每天轮换（服务端滚动约 13.5 天）；距今 %s 天"
                    % _age_days(c.get("cookie_updated"))}


def p_loomy_desktop():
    import glob as _g
    hits = _g.glob(os.path.join("C:\\Users\\Public\\Loomy", "*", "userData", "auth-session.json"))
    if not hits:
        return {"source": "无", "exp_ms": None, "root": True, "refreshable": False,
                "note": "没找到桌面端 auth-session.json（桌面端未装/未登录）"}
    p = max(hits, key=os.path.getmtime)
    age = _mtime_age_days(p)
    return {"source": "Public\\Loomy\\*\\auth-session.json", "exp_ms": None, "root": True,
            "refreshable": False,
            "note": "★passport token 固定 14 天、**无续期接口**；文件写入距今 %s 天 → "
                    "约剩 %s 天，到点必须在桌面端重登一次（不是脚本失效）"
                    % (age, round(14 - (age or 0), 1))}


def p_c189():
    c = _json(CFG("c189_config.json"))
    if not c.get("accessToken"):
        return {"source": "无", "note": "缺 c189_config.json"}
    return {"source": "c189_config.json", "exp_ms": None, "root": False,
            "refreshable": bool(c.get("refreshToken")),
            "note": "accessToken→getSessionForPC 换 sessionKey（脚本会回存新 AT/RT，expiresIn 6 天）；"
                    "★根凭证是浏览器 SSON cookie，SSON 掉了要重登 cloud.189.cn 重抓"}


def p_jd():
    c = _json(CFG("jd_web_config.json"))
    ts = c.get("ts")
    age = _age_days(ts) if ts else None
    return {"source": "jd_web_config.json", "exp_ms": None, "root": True, "refreshable": True,
            "note": "每次运行按新鲜度三级重取（磁盘只读直开→CDP 9222→TEMP 快照）；"
                    "上次快照距今 %s 天，manual=%s；★登录态本身会整体会话作废（code=3），"
                    "作废只能重登 jd.com" % (age, c.get("manual"))}


def p_jd_farm():
    c = _json(CFG("jd_farm_config.json"))
    if not c.get("cookie"):
        return {"source": "无", "note": "缺 jd_farm_config.json"}
    return {"source": "jd_farm_config.json", "exp_ms": None, "root": True, "refreshable": False,
            "note": "小程序 cookie（**不在浏览器 cookie 库里**，cookie_sync 救不到）+ _sdtoken 寿命仅 1800s "
                    "每次现取；cookie 更新距今 %s 天" % _age_days(c.get("updated")),
            "risk": True}


def p_aliyun():
    c = _json(CFG("aliyun_config.json"))
    return {"source": "aliyun_config.json", "exp_ms": cc.expiry_ms(expires_at=c.get("expire_time")),
            "root": False, "refreshable": bool(c.get("refresh_token")),
            "note": "★凭证根在浏览器 Local Storage（leveldb 不被锁），每次实读；"
                    "表里的到期是 AT（7200s），用 RT 现换——数值小是正常的，不参与临期判定"}


def p_qwenwork():
    ud = cc.appdata("QwenWorkCN")
    dat = os.path.join(ud, "auth-v2.dat")
    if not os.path.exists(dat):
        return {"source": "未安装", "exp_ms": None, "root": True, "refreshable": False,
                "note": "没有 QwenWorkCN\\auth-v2.dat（未装/未登录该桌面端）"}
    d = cc.read_v10_json(dat, ud) or {}
    return {"source": "QwenWorkCN\\auth-v2.dat", "exp_ms": cc.expiry_ms(token=d.get("accessToken") or d.get("token")),
            "root": True, "refreshable": bool(d.get("refreshToken")),
            "note": "客户端在跑就自续；文件 mtime 距今 %s 天" % _mtime_age_days(dat)}


def _qoder(name, dirs, label):
    ud = cc.find_first([cc.appdata(d) for d in dirs])
    if not ud:
        return {"source": "未安装", "exp_ms": None, "root": True, "refreshable": False,
                "note": "%s 未安装（本机没这个用户数据目录）" % name}
    dat = os.path.join(ud, "auth.v1.dat")
    if not os.path.exists(dat):
        return {"source": "未安装", "exp_ms": None, "root": True, "refreshable": False,
                "note": "%s 目录在但没有 auth.v1.dat —— 未登录，跳过（不是失效）" % name}
    c = cc.read_v10_json(dat, ud) or {}
    if not c.get("token"):
        return {"source": ud, "exp_ms": None, "root": True, "refreshable": False,
                "note": "auth.v1.dat 解不出 token（未登录或格式变更）"}
    rt_exp = cc.expiry_ms(expires_at=c.get("refreshTokenExpiresAt"))
    return {"source": label, "exp_ms": cc.expiry_ms(expires_at=c.get("expiresAt")), "root": True,
            "refreshable": False,
            "note": "RT 到期 %s；★离线续期要 machine_id（本机 auth.v1.dat 里没有）→ "
                    "实际靠客户端自续，临期解法是在 Qoder 里重登一次" % cc.fmt_exp(rt_exp)}


def p_qoder_cn():
    return _qoder("Qoder CN", ["com.qodercn.app.stable", "Qoder CN"], "com.qodercn.app.stable\\auth.v1.dat")


def p_qoder_intl():
    return _qoder("Qoder 国际版", ["com.qoder.app.stable", "Qoder"], "com.qoder.app.stable\\auth.v1.dat")


def p_xm():
    c = _json(CFG("xm_mijin_config.json"))
    y = _json(CFG("yp_rpsign_config.json"))
    return {"source": "config 优先，源码内置抓包值兜底", "exp_ms": None, "root": True, "refreshable": False,
            "note": "App serviceToken 无 RT、无到期字段、也不在浏览器 cookie 库里（抓包来自 iOS App）。"
                    "★重抓只需写 xm_mijin_config.json / yp_rpsign_config.json（脚本已 config 优先），"
                    "不必改源码；当前 xm_config=%s yp_config=%s → 用的是内置兜底那份。"
                    "寿命只能靠心跳观察" % (bool(c), bool(y)),
            "risk": True}


def p_hw():
    s = _json(CFG("hw_codearts_session.json"))
    if not s.get("refresh_token"):
        return {"source": "无", "exp_ms": None, "root": True, "refreshable": False,
                "note": "缺 hw_codearts_session.json（未走免抓包链路）"}
    return {"source": "CodeArts Agent state.vscdb + 会话缓存", "exp_ms": cc.expiry_ms(expires_at=s.get("rt_exp_ms")),
            "root": True, "refreshable": True,
            "note": "临时 AK/SK 约 2h（派生层，客户端在跑自动续）；表里到期是 **refresh_token**（约 28 天、"
                    "每刷轮换，DPoP+PKCE 离线续已接线）；上次保存距今 %s 天"
                    % _age_days(s.get("saved_at"))}


def p_trae():
    """★两个 token 是**同一次登录**发的两种用途（实测 iat 精确相同）：
    trae_config.json 里那份 14 天、签到接口用的就是它 → 它才是根凭证；
    ~/.trae-cn/trae-jwt-token 那份 7 天是 IDE 自用，只当"客户端上次登录时间"的旁证。
    本机搜过 ~/.trae-cn 与 %APPDATA%\\Trae CN：**没有 refresh_token** → 不能离线续期，
    唯一动作是在 TRAE 里重新登录一次（两份会同时刷新）。"""
    cfg = _json(CFG("trae_config.json"))
    f = cc.find_first([cc.home(".trae-cn", "trae-jwt-token"), cc.home(".trae", "trae-jwt-token")])
    if not cfg.get("access_token"):
        return {"source": "无", "exp_ms": None, "root": True, "refreshable": False,
                "note": "缺 trae_config.json 的 access_token（需抓包 Cloud-IDE-JWT）"}
    exp = cc.expiry_ms(token=cfg["access_token"].strip())
    age = _mtime_age_days(f) if f else None
    return {"source": "trae_config.json(Cloud-IDE-JWT 14天)", "exp_ms": exp, "root": True,
            "refreshable": False,
            "note": "★无 refresh_token（本机 Trae 存储里搜不到）→ 只能重登：临期前在 TRAE 客户端登录一次，"
                    "config 与 IDE 自用那份会同时刷新；IDE 那份 mtime 距今 %s 天" % age}


def p_lobster():
    p = cc.find_first([cc.appdata("LobsterAI", "lobsterai.sqlite"), cc.appdata("lobsterai", "lobsterai.sqlite")])
    if not p:
        return {"source": "无", "exp_ms": None, "root": True, "refreshable": False,
                "note": "没装 LobsterAI 桌面端"}
    kv = cc.read_sqlite_kv(p) or {}
    try:
        tok = json.loads(kv.get("auth_tokens") or "{}").get("accessToken") or ""
    except Exception:
        tok = ""
    if not tok:
        return {"source": "LobsterAI\\lobsterai.sqlite(kv)", "exp_ms": None, "root": True,
                "refreshable": False, "note": "kv 里没有 auth_tokens（桌面端未登录）"}
    return {"source": "LobsterAI\\lobsterai.sqlite(kv)", "exp_ms": cc.expiry_ms(token=tok), "root": True,
            "refreshable": True, "note": "JWT 约 30 天；RT 同在库里 → /api/auth/refresh 已接线（lead 1h、单次轮换）"}


def p_minimax():
    s = _json(CFG("minimax_session.json"))
    ap = cc.home(".minimax", "auth", "prod", "cn", "mcode-public", "auth.json")
    d = _json(ap)
    rt = s.get("refresh_token") or d.get("refresh_token")
    return {"source": "桌面端 auth.json + minimax_session.json",
            "exp_ms": cc.expiry_ms(expires_at=s.get("expires_at_ms")), "root": False,
            "refreshable": bool(rt),
            "note": "★表里到期是 AT（约 1h，客户端每 ~50min 自续并**轮换** RT），不判临期；"
                    "真正的根是桌面端登录态——auth.json mtime 距今 %s 天；上次续期距今 %s 天"
                    % (_mtime_age_days(ap), _age_days(s.get("refreshed_at")))}


def p_zcode():
    c = _json(CFG("zcode_config.json"))
    if not c.get("zcode_jwt"):
        return {"source": "无", "note": "缺 zcode_config.json（上游已删自动解密，只能抓包）"}
    return {"source": "zcode_config.json", "exp_ms": cc.expiry_ms(token=c.get("zcode_jwt")), "root": True,
            "refreshable": False,
            "note": "★zcode_jwt 是 JWT 但**payload 里没有 exp**（只有 iat/sub/token_version/user_id）"
                    "→ 服务端不给寿命，体检只能标「无到期值」；无 RT，硬到期即失效需重抓"}


# (平台, 读数函数, 该平台的入口脚本名)
# ★第三列不只是标注：scan() 会**跳过本目录里没有该脚本的平台**。
#   这样导出到公开仓（不含 GR/利宝/掘金，也不含 run_all 心跳）时不会把"别人没装的平台"
#   报成「缺凭证 / 要处理」，本地少装一个平台时同理。
REGISTRY = [
    ("GR 小程序", p_gr, "gr_signin.py"),
    ("利宝保险", p_libao, "libao_integral.py"),
    ("南方航空", p_csair, "csair_signin.py"),
    ("美团系(4 合 1)", p_meituan, "mt_api_coupon.py"),
    ("魔搭 ModelScope", p_ms, "ms_magicube.py"),
    ("掘金", p_juejin, "juejin_signin.py"),
    ("WorkBuddy 系", p_workbuddy, "wb_score.py"),
    ("办公小浣熊", p_xhx, "xhx_office_points.py"),
    ("讯飞 Loomy(web)", p_loomy, "loomy_points.py"),
    ("讯飞 Loomy(桌面)", p_loomy_desktop, "loomy_desktop_tasks.py"),
    ("天翼 189 云盘", p_c189, "c189_signin.py"),
    ("京东 京豆/PC", p_jd, "jd_web_signin.py"),
    ("京东 东东农场", p_jd_farm, "jd_farm.py"),
    ("阿里云盘", p_aliyun, "aliyun_signin.py"),
    ("千问办公", p_qwenwork, "qwenwork_credits.py"),
    ("Qoder CN", p_qoder_cn, "qoder_credits.py"),
    ("Qoder 国际版", p_qoder_intl, "qoder_credits.py"),
    ("小米系(米金/有品)", p_xm, "xm_mijin.py"),
    ("华为码道", p_hw, "hw_codearts.py"),
    ("字节 TRAE", p_trae, "trae_credits.py"),
    ("有道 LobsterAI", p_lobster, "lobsterai_credits.py"),
    ("MiniMax Code", p_minimax, "minimax_credits.py"),
    ("ZCode 智谱", p_zcode, "zcode_credits.py"),
]


def status_of(name, r):
    """返回 (状态文字, 严重度)。严重度 0 无需动作 / 2 临期 / 1 已过期或缺凭证。"""
    if r.get("error"):
        return "读取异常", 1
    src = r.get("source") or "无"
    if src == "未安装":
        return "未安装", 0
    if src == "无":
        return "缺凭证", 1
    exp = r.get("exp_ms")
    root = bool(r.get("root"))
    if exp is None:
        return ("自动轮换", 0) if r.get("refreshable") else ("无到期值", 0)
    d = cc.days_left(exp)
    if d is None:
        return ("自动轮换", 0) if r.get("refreshable") else ("无到期值", 0)
    if not root:
        return "OK", 0                       # 派生短效凭证：寿命短是设计如此，不参与告警
    if d < 0:
        return "已过期", 0 if r.get("refreshable") else 1   # 能自动续的过期会在下次运行时自愈
    if d <= cc.WARN_DAYS:
        return "临期", 2
    return "OK", 0


def scan():
    """跑一遍全部平台，返回 (rows, worst)。rows 每项：
    (平台, 状态, 到期, 剩余天, 续期, 心跳天, 来源, 说明, 严重度)。★纯只读、不发网络请求。
    ★本目录里没有该平台入口脚本的行直接跳过（不报"缺凭证"）——公开仓不含 GR/利宝/掘金，
      把它们算进"要处理"会让用户去修一个自己根本没装的平台。"""
    rows, worst = [], 0
    for name, fn, script in REGISTRY:
        if script and not os.path.exists(os.path.join(BASE_DIR, script)):
            continue
        try:
            r = fn()
        except Exception as e:
            r = {"source": "-", "exp_ms": None, "root": False, "refreshable": None,
                 "note": "%s: %s" % (type(e).__name__, e), "error": True}
        st, sev = status_of(name, r)
        hb = cc.days_since_ok_any(name)          # 总控成功心跳（无到期值的平台只有它有信号）
        if hb is not None and hb > 1.5 and st not in ("已过期", "缺凭证"):
            st, sev = "心跳陈旧", max(sev, 2)     # 超过一天半没成功过 = 链路早就断了或被跳过
        if r.get("risk") and sev == 0:
            sev = 2                              # 结构性卡点（无 RT/依赖 9222/半自动）也进"要盯"
        worst = max(worst, sev)
        exp = r.get("exp_ms")
        d = cc.days_left(exp) if exp else None
        rows.append((name, st, cc.fmt_exp(exp) if exp else "-",
                     ("%.1f" % d) if d is not None else "-",
                     {True: "可自动续", False: "不可续", None: "视情况"}[r.get("refreshable")],
                     ("%.1f" % hb) if hb is not None else "-",
                     r.get("source") or "-", r.get("note") or "", sev))
    return rows, worst


def group(rows):
    """按处置优先级分桶：dead 会直接领不到 / stale 近期没成功 / soon 临期 / watch 结构性卡点。"""
    dead = [r[0] for r in rows if r[1] in ("已过期", "缺凭证", "读取异常")]
    stale = [r[0] for r in rows if r[1] == "心跳陈旧"]
    soon = [r[0] for r in rows if r[1] == "临期"]
    watch = [r[0] for r in rows if r[8] == 2 and r[0] not in dead + stale + soon]
    return dead, stale, soon, watch


def banner(limit_note=110):
    """★给总控用的紧凑预警（2~4 行）。默认不打全表——日报输出格式是判读锚点，
    塞进 23 行表格会把逐任务耗时表推远。要看全表单独跑 `keepalive_status.py`。
    返回 (文本行列表, worst严重度)。"""
    try:
        rows, worst = scan()
        dead, stale, soon, watch = group(rows)
        head = "[保活] %d 平台 | 要处理 %d | 临期 %d | 需盯 %d" % (
            len(rows), len(dead) + len(stale), len(soon), len(watch))
        out = [head]
        if dead:
            out.append("  ★会直接领不到：" + "、".join(dead))
        if stale:
            out.append("  ★心跳陈旧（近期没成功过）：" + "、".join(stale))
        if soon:
            out.append("  ★临期（今天就处理）：" + "; ".join(
                "%s 剩%s天" % (r[0], r[3]) for r in rows if r[0] in soon))
        if watch:
            line = "  ·需盯：" + "、".join(watch)
            out.append(line[:limit_note] + ("…" if len(line) > limit_note else ""))
        if not (dead or stale or soon or watch):
            out.append("  全部正常")
        return out, worst
    except Exception as e:
        return ["[保活] 体检未完成（不影响签到）：%s: %s" % (type(e).__name__, e)], 0


def main():
    warn_only = "--warn" in sys.argv
    rows, worst = scan()
    print("=" * 108)
    print("全平台账号保活体检 %s   （根凭证临期阈值 %d 天 / 续期 lead %ds / 同支 RT 冷却 %dh）"
          % (time.strftime("%Y-%m-%d %H:%M"), cc.WARN_DAYS, cc.LEAD_S, RT_COOLDOWN_H))
    print("=" * 108)
    hdr = "%-18s %-8s %-17s %-6s %-7s %-7s %s"
    print(hdr % ("平台", "状态", "根凭证到期", "剩余天", "续期", "心跳天", "来源"))
    print("-" * 108)
    for row in rows:
        if warn_only and row[8] == 0:
            continue
        n, st, e, dl, ra, hb, src, note, _ = row
        print(hdr % (n, st, e, dl, ra, hb, src))
        if note:
            print(" " * 4 + "→ " + note)
    print("-" * 108)
    dead, stale, soon, watch = group(rows)
    print("结论：%d 个平台 | 要处理 %d | 需盯 %d" % (len(rows), len(dead) + len(stale), len(soon) + len(watch)))
    print("  心跳=总控里该平台上次成功的距今天数（★没有到期字段的平台只能靠它发现衰减，>1.5 天即异常）")
    if dead:
        print("  ★会直接领不到：" + "、".join(dead))
    if stale:
        print("  ★心跳陈旧（近期没成功过，先查是不是失效或被判跳过）：" + "、".join(stale))
    if soon:
        print("  ★临期（今天就处理，别等明天领不到）：" + "、".join(soon))
    if watch:
        print("  ★结构性卡点（不是失效，但每天要留意）：" + "、".join(watch))
    if not (dead or stale or soon or watch):
        print("  全部正常")
    return worst


RT_COOLDOWN_H = cc.RT_RETRY_COOLDOWN_S // 3600

if __name__ == "__main__":
    sys.exit(main())
