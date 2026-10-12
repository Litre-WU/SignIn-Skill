#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""京东京豆签到 - jd_signin.py

凭证: jd_config.json(pt_key/pt_pin, 由 jd_login.py 扫码登录获得, 有效期约 90 天)
链路: POST https://api.m.jd.com/client.action  functionId=signBeanIndex&appid=ld  (App UA)
      响应 code=0 & status=1 → 签到成功, data.dailyAward/continuityAward.beanAward.beanCount
           含"已签到"      → 今日已签(幂等)
           code=3          → pt_key 失效, 需重新跑 jd_login.py
           含"跳转至拼图"  → 风控拦截
           含"人数较多"/S101 → 限流, 可稍后重试

用法:
  jd_signin.py auto          每日签到(总控调用, 输出 JSON)
  jd_signin.py status        只读查签到状态(不签到)
  jd_signin.py check         验证 pt_key 是否有效
"""
import json, os, sys, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "jd_config.json")
UA = "JD4iPhone/167169 (iPhone; iOS 13.4.1; Scale/3.00)"
API = "https://api.m.jd.com/client.action"

def load_cfg():
    if not os.path.isfile(CFG):
        return None
    c = json.load(open(CFG, encoding="utf-8"))
    if not (c.get("pt_key") and c.get("pt_pin")):
        return None
    return c

def post(fn, cfg):
    ck = "pt_key=%s;pt_pin=%s;" % (cfg["pt_key"], cfg["pt_pin"])
    body = ("functionId=%s&appid=ld" % fn).encode()
    r = urllib.request.Request(API, data=body)
    r.add_header("User-Agent", UA)
    r.add_header("Cookie", ck)
    r.add_header("Content-Type", "application/x-www-form-urlencoded")
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        x = op.open(r, timeout=30)
        return x.status, x.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, "EXC %s" % e

def parse(text):
    """返回 (state, beans, msg): state in ok/signed/fail/risk/limit"""
    t = text
    try:
        d = json.loads(t)
    except Exception:
        return "fail", 0, "响应非JSON: %s" % t[:120]
    if str(d.get("code", "")) == "3":
        return "fail", 0, "pt_key 失效(用户未登录)"
    if "跳转至拼图" in t:
        return "risk", 0, "触发拼图风控"
    if str(d.get("status", "")) == "1" or '"status":1' in t.replace(" ", ""):
        beans = 0
        src = ""
        data = d.get("data") or {}
        for key in ("dailyAward", "continuityAward"):
            aw = data.get(key) or {}
            bc = (aw.get("beanAward") or {}).get("beanCount")
            if bc:
                try:
                    beans = int(bc)
                except Exception:
                    beans = 0
                src = key
                break
        if not beans and "新人签到" in t:
            import re
            m = re.search(r'beanCount["\']?\s*:\s*["\']?(\d+)', t)
            beans = int(m.group(1)) if m else 0
            src = "新人签到"
        return "ok", beans, "签到成功%s" % ("(%s +%d京豆)" % (src, beans) if beans else "(无京豆明细)")
    if "已签到" in t or "新人签到" in t:
        return "signed", 0, "今日已签到(幂等)"
    if "人数较多" in t or "S101" in t or "S109" in t:
        return "limit", 0, "签到人数较多/限流: %s" % (d.get("errorMessage") or t[:80])
    return "fail", 0, "签到失败: %s" % t[:160]

def do_auto():
    cfg = load_cfg()
    if not cfg:
        print(json.dumps({"ok": False, "state": "nocfg",
                          "msg": "无 jd_config.json 或缺 pt_key/pt_pin, 请先跑 jd_login.py 扫码登录"},
                         ensure_ascii=False))
        return 0 if False else 1
    st, t = post("signBeanIndex", cfg)
    if st != 200:
        print(json.dumps({"ok": False, "state": "fail", "msg": "HTTP %s %s" % (st, t[:120])},
                         ensure_ascii=False))
        return 1
    state, beans, msg = parse(t)
    out = {"ok": state in ("ok", "signed"),
           "state": state, "beans": beans, "msg": msg,
           "pin": cfg.get("pt_pin"), "signRaw": t[:300]}
    print(json.dumps(out, ensure_ascii=False))
    return 0 if state in ("ok", "signed") else 1

def do_check():
    cfg = load_cfg()
    if not cfg:
        print("[失效] 无配置或缺 pt_key/pt_pin"); return 1
    st, t = post("signBeanIndex", cfg)
    print("HTTP %s  %s" % (st, t[:200]))
    state, beans, msg = parse(t)
    print("判定: state=%s beans=%s msg=%s" % (state, beans, msg))
    return 0 if state != "fail" else 1

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    sys.exit(do_check() if cmd == "check" else do_auto())
