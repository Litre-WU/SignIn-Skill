#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quark_signin.py — 夸克网盘（pan.quark.cn）每日签到领空间
======================================================
浏览器已登录 pan.quark.cn → 本机取 cookie，无需抓包。

鉴权：纯 Cookie（`__pus` 是会话核心键，另有 __kps/__kp/__uid/b-user-id/isg/tfstk…）。
  来源优先级：浏览器 Cookies 库直读 → TEMP 整库缓存（含别的平台留下的副本）→
  CDP 9222 → 已存 quark_config.json。命中即在页面级接口实测 401/200 判活。

接口（2026-10-12 实测）:
  POST https://drive-m.quark.cn/1/clouddrive/capacity/growth/sign?pr=ucpro&fr=pc&uc_param_str=
       body {"sign_cyclic": true}     → 执行签到
  GET  https://drive-m.quark.cn/1/clouddrive/capacity/growth/info?pr=ucpro&fr=pc&uc_param_str=
       → 状态；★实测 data 恒为 {}（服务端不返回明细），只能当探活用
  GET  https://drive-m.quark.cn/1/clouddrive/member?pr=ucpro&fr=pc&uc_param_str=
       → data.extend_capacity_composition.**sign_reward**（签到累计奖励字节数）
         data.total_capacity / use_capacity

★鉴权判据（务必用这个，别只看 200）：
  不带 cookie → HTTP 401 {"code":31001,"message":"require login [guest]"}
  带 cookie   → HTTP 200 {"code":0,...}
  info/sign 的 `data` 恒为 {}，不能用来判断"今天签没签"。

★★入账判据：签到前后各查一次 member，比对 `sign_reward` 增量。
  增量 > 0 → 今日签到成功并发放了空间；增量 = 0 → 今日已签（幂等）或当日无奖励。
  （与 c189_signin.py 用容量前后差做判据同一思路）

命令行:
  python quark_signin.py auto            # 取 cookie → 签到 → 播报（默认）
  python quark_signin.py status          # 只读播报（会员类型 / 累计签到奖励 / 总容量）
  python quark_signin.py probe           # 探 cookie 来源 + 三个端点原始响应
  python quark_signin.py init <cookie>   # 手动写整行 Cookie（浏览器 DevTools 复制）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.request import ProxyHandler, build_opener

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
CFG = os.path.join(BASE, "quark_config.json")
STATE = os.path.join(BASE, "quark_sign_state.json")

opener = build_opener(ProxyHandler({}))

DRIVE = "https://drive-m.quark.cn/1/clouddrive"
QS = "?pr=ucpro&fr=pc&uc_param_str="
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
DOMAINS = ["quark.cn"]
# 会话核心键：缺了它基本等于未登录
SESSION_KEYS = ("__pus", "__kps")


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
def api(path, cookie, body=None, method=None, timeout=20):
    """调 quark clouddrive 接口。返回 (http_code, dict|None, raw_text)。"""
    method = method or ("POST" if body is not None else "GET")
    url = DRIVE + path + QS
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (("User-Agent", UA),
                 ("Content-Type", "application/json"),
                 ("Accept", "application/json, text/plain, */*"),
                 ("Referer", "https://pan.quark.cn/"),
                 ("Origin", "https://pan.quark.cn"),
                 ("Cookie", cookie)):
        req.add_header(k, v)
    try:
        with opener.open(req, timeout=timeout) as r:
            code, txt = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            code, txt = e.code, e.read().decode("utf-8", "replace")
        except Exception:
            code, txt = e.code, "HTTP %s" % e.code
    except Exception as e:
        return -1, None, "EXC %s" % e
    try:
        return code, json.loads(txt), txt
    except Exception:
        return code, None, txt[:200]


# ------------------------------------------------------------------ 凭证
def browser_cookies_dict(verbose=False):
    try:
        import browser_cookies
        return browser_cookies.extract(DOMAINS, tag="quark", verbose=verbose)
    except Exception as e:
        if verbose:
            print("    [cookie] 提取异常: %s" % e)
        return {}


def has_session(ck):
    names = set(ck or {})
    return any(k in names for k in SESSION_KEYS)


def cookie_header(ck):
    try:
        import browser_cookies
        return browser_cookies.cookie_header(ck)
    except Exception:
        return "; ".join("%s=%s" % (k, ck[k]) for k in sorted(ck))


def check_login(cookie):
    """在需要登录的端点实测。返回 (ok, member_data, msg)。"""
    code, j, raw = api("/member", cookie)
    if j is None:
        return False, {}, "member HTTP %s %s" % (code, raw)
    if j.get("code") == 0 and isinstance(j.get("data"), dict):
        return True, j["data"], ""
    if j.get("code") == 31001 or code == 401:
        return False, {}, "require login（cookie 失效/已轮换）"
    return False, {}, "code=%s %s" % (j.get("code"), j.get("message") or "")


def ensure_cookie(cfg, verbose=False):
    """取一个可用的整行 Cookie。返回 (cookie, member_data, src_desc)；失败 cookie=None。"""
    cands = []
    ck = browser_cookies_dict(verbose)
    if ck and has_session(ck):
        cands.append(("browser", cookie_header(ck)))
    saved = cfg.get("cookie")
    if saved:
        cands.append(("config", saved))

    errs = []
    for src, line in cands:
        ok, data, msg = check_login(line)
        if ok:
            if src == "browser":
                cfg["cookie"] = line
                cfg["source"] = "browser"
                cfg["member_type"] = data.get("member_type")
                save_cfg(cfg)
            return line, data, src
        errs.append("%s:%s" % (src, msg))

    if not cands:
        return None, {}, "浏览器未取到 quark.cn 会话 cookie（Cookies 库被锁且无缓存），配置里也没有"
    return None, {}, " ；".join(errs)


# ------------------------------------------------------------------ 判据
def sign_reward(data):
    """签到累计奖励字节数（data.extend_capacity_composition.sign_reward）。"""
    comp = (data or {}).get("extend_capacity_composition") or {}
    v = comp.get("sign_reward")
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def mb(n):
    return None if n is None else round(n / 1024.0 / 1024.0, 2)


def gb(n):
    return None if n is None else round(n / 1024.0 / 1024.0 / 1024.0, 2)


# ------------------------------------------------------------------ 命令
def cmd_init(arg):
    if arg == "auto":
        ck = browser_cookies_dict(verbose=True)
        if not ck or not has_session(ck):
            print("[失败] 未取到夸克会话 cookie（需含 __pus/__kps）")
            return 3
        line = cookie_header(ck)
        ok, data, msg = check_login(line)
        if not ok:
            print("[失败] cookie 实测未登录: %s" % msg)
            return 3
        cfg = load_cfg()
        cfg.update({"cookie": line, "source": "browser",
                    "member_type": data.get("member_type")})
        save_cfg(cfg)
        print("[ok] 已写入 quark_config.json：member=%s 累计签到奖励=%sMB" %
              (data.get("member_type"), mb(sign_reward(data))))
        return 0

    line = (arg or "").strip()
    if "__pus" not in line and "__kps" not in line:
        print("[失败] cookie 里看不到 __pus/__kps，可能不是夸克登录态整行 Cookie")
        print("       用法: quark_signin.py init '<整行Cookie>'")
        return 2
    ok, data, msg = check_login(line)
    if not ok:
        print("[失败] 该 cookie 实测未登录: %s" % msg)
        return 3
    cfg = load_cfg()
    cfg.update({"cookie": line, "source": "manual", "member_type": data.get("member_type")})
    save_cfg(cfg)
    print("[ok] cookie 校验通过并写入：member=%s 累计签到奖励=%sMB" %
          (data.get("member_type"), mb(sign_reward(data))))
    return 0


def has_campaign(info_data):
    """growth/info 的 data 里是否有「签到领空间」活动。空 data = 没挂活动 = 不发放。"""
    return bool(info_data)


def growth_info(cookie):
    """GET growth/info。返回 (http_code, data_dict, raw)。
    ★2026-10-13 实测：本账号（SUPER_VIP / PC 会话）该端点 **data 恒为 {}**，
      即服务端没有给这个账号挂「签到领空间」活动（cap_sign）→ 签到不会发放空间。
      成功发放时 data 应含 cap_sign.sign_daily_reward / sign_progress / sign_target。
    """
    code, j, raw = api("/capacity/growth/info", cookie, None, "GET")
    if j is None:
        return code, {}, raw
    return code, (j.get("data") or {}), raw


def cmd_status():
    cfg = load_cfg()
    cookie, data, src = ensure_cookie(cfg)
    if not cookie:
        print("【夸克登录失效】%s" % src)
        return 3
    st = load_state()
    print("凭证=%s  会员=%s" % (src, data.get("member_type")))
    print("累计签到奖励=%sMB  总容量=%sGB  已用=%sGB" %
          (mb(sign_reward(data)), gb(data.get("total_capacity")), gb(data.get("use_capacity"))))
    _c, g, _r = growth_info(cookie)
    if has_campaign(g):
        cap = g.get("cap_sign") or {}
        print("签到活动: 有（今日已签=%s 今日奖励=%sMB 进度=%s/%s）" %
              (cap.get("sign_daily"), mb(cap.get("sign_daily_reward")),
               cap.get("sign_progress"), cap.get("sign_target")))
    else:
        print("签到活动: 【无活动数据】服务端未给该账号挂「签到领空间」活动"
              "（growth/info 的 data 恒为 {}），PC 端签到不发放空间")
    if st.get("last_day"):
        print("上次入账: %s（当日奖励+%sMB）" % (st.get("last_day"), st.get("last_delta_mb")))
    return 0


def cmd_probe():
    cfg = load_cfg()
    print("== Cookie 提取 ==")
    ck = browser_cookies_dict(verbose=True)
    if ck:
        print("  命中 %d 个，含会话键=%s" % (len(ck), has_session(ck)))
        print("  键: %s" % ", ".join(sorted(ck)))
    else:
        print("  未命中")
    print("  配置里已有 cookie=%s（source=%s）" %
          ("是" if cfg.get("cookie") else "否", cfg.get("source") or "-"))
    print()
    cookie, data, src = ensure_cookie(cfg)
    if not cookie:
        print("== 取登录态失败 ==\n  %s" % src)
        return 3
    print("== 端点实测（凭证来源 %s）==" % src)
    for tag, path, body, method in (
            ("member", "/member", None, "GET"),
            ("growth/info", "/capacity/growth/info", None, "GET"),
            ("growth/sign", "/capacity/growth/sign", {"sign_cyclic": True}, "POST")):
        code, j, raw = api(path, cookie, body, method)
        print("  %-12s HTTP %s %s" % (tag, code, (raw or "")[:220]))
    print("  累计签到奖励=%sMB" % mb(sign_reward(data)))
    return 0


def cmd_auto():
    cfg = load_cfg()
    cookie, data, src = ensure_cookie(cfg)
    if not cookie:
        print(json.dumps({"ok": False, "platform": "夸克网盘", "msg": src}, ensure_ascii=False))
        print("【夸克登录失效】%s —— 请在浏览器打开 pan.quark.cn 重新登录，"
              "或执行: quark_signin.py init '<整行Cookie>'" % src)
        return 3

    before = sign_reward(data)
    code, j, raw = api("/capacity/growth/sign", cookie, {"sign_cyclic": True}, "POST")
    ok_req = (code == 200 and isinstance(j, dict) and j.get("code") == 0)
    if not ok_req:
        msg = "sign HTTP %s code=%s %s" % (code, (j or {}).get("code"), (j or {}).get("message") or raw[:120])
        print(json.dumps({"ok": False, "platform": "夸克网盘", "msg": msg}, ensure_ascii=False))
        print("[失败] 夸克网盘签到请求失败：%s" % msg)
        return 3

    ok2, data2, _ = check_login(cookie)
    after = sign_reward(data2) if ok2 else None
    delta = None if (before is None or after is None) else after - before

    today = time.strftime("%Y-%m-%d")
    st = load_state()
    first = (delta or 0) > 0
    if first:
        st.update({"last_day": today, "last_delta_mb": mb(delta),
                   "sign_reward_total_mb": mb(after),
                   "last_run": time.strftime("%Y-%m-%d %H:%M:%S")})
        save_state(st)

    # ★关键判别：该账号到底有没有「签到领空间」活动（2026-10-13 定案）
    _ic, g, _ir = growth_info(cookie)
    campaign = has_campaign(g)

    out = {
        "ok": True,
        "platform": "夸克网盘",
        "cred_src": src,
        "member_type": data.get("member_type"),
        "signed_today": True,
        "first_today": first,
        "reward_delta_mb": mb(delta) if delta is not None else None,
        "sign_reward_total_mb": mb(after),
        "total_capacity_gb": gb(data2.get("total_capacity") if ok2 else data.get("total_capacity")),
        "has_campaign": campaign,
    }
    print(json.dumps(out, ensure_ascii=False))

    if first:
        print("[ok] 夸克网盘 签到成功｜本次 +%sMB｜累计签到奖励 %sMB｜总容量 %sGB" %
              (mb(delta), mb(after), out["total_capacity_gb"]))
    elif st.get("last_day") == today:
        print("[ok] 夸克网盘 今日已签（幂等，本次无新增）｜累计签到奖励 %sMB" % mb(after))
    elif not campaign:
        print("[ok] 夸克网盘 签到接口已执行（服务端 code=0，幂等）｜"
              "【夸克签到无活动数据】该账号在当前 PC 端接口下没有「签到领空间」活动"
              "（growth/info 的 data 恒为 {}，累计签到奖励停在 %sMB 不变），"
              "接口虽返回 code=0 但不发放空间" % mb(after))
        print("     说明：公开资料显示 PC 端签到接口已停止发放，移动端需 kps/sign/vcode 三参数；"
              "本账号为 %s 且 cookie 是 PC 会话（fr=android 会 401）。"
              "需你在夸克 App 内手动签到一次确认是否发放；若发放，抓一条移动端请求我再适配。"
              % data.get("member_type"))
    else:
        print("[ok] 夸克网盘 签到接口已执行（服务端 code=0），但签到奖励无增量："
              "累计 %sMB（可能今日已签/当日奖励已达上限）" % mb(after))
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if cmd == "init":
        if len(sys.argv) < 3:
            print("[中断] 用法: quark_signin.py init '<整行Cookie>' | init auto")
            return 2
        return cmd_init(" ".join(sys.argv[2:]))
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
