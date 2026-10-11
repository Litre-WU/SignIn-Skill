#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ModelScope 魔搭社区每日魔粒（纯标准库，自用）

魔粒体系逆向结论（2026-10-11，参考 cnb.cool/codeLong1024/modelscope-magicube 并实测）:
1. 没有签到接口。daily_active(+200) 与 aliyun_bindlogin(+50) 是**会话副作用**——
   当天首次带登录态访问站点即自动入账（有去重），访问首页+魔粒用量页即可触发。
2. interaction_like「收藏/喜欢」+2/次，每日上限 20 次（+40/天）。
   star/unstar 可反复刷: PUT stars 入账 +2，PUT unstar 不扣分不减次数，
   同一模型 star→unstar 循环即可拿满。
3. interaction_comment「发起高质量讨论」+5×2，需真实评论且服务端审核，不自动刷。
4. 短期魔粒 24h 过期（expire_days=1），定时任务每天跑正好循环利用。
5. 魔粒接口认网站登录 cookie（m_session_id/h_uid/csrf_token），不需要 Bearer Token，
   cookie 有效期约 30~60 天。

接口:
  GET  /openapi/v1/magicubes/earn/rules  任务规则与今日进度（today_used/today_remain/amount）
  GET  /openapi/v1/magicubes/balance     余额
  打卡 GET https://www.modelscope.cn/ 与 /magicube/usage（会话副作用触发发放）
  点赞 PUT /api/v1/models/{owner}/{name}/stars    Data.Stars +1
  取消 PUT /api/v1/models/{owner}/{name}/unstar   Data.Stars -1

用法:
  python ms_magicube.py init "cookie整行"     写入凭证
  python ms_magicube.py status                查余额+今日进度
  python ms_magicube.py auto                  打卡+刷点赞（幂等，定时任务入口）
  python ms_magicube.py rules                 只看规则表
"""
import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.error
import ssl

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "ms_config.json")
LOG_PATH = os.path.join(HERE, "ms_magicube.log")

BASE = "https://www.modelscope.cn"
URL_RULES = BASE + "/openapi/v1/magicubes/earn/rules"
URL_BALANCE = BASE + "/openapi/v1/magicubes/balance"
# 刷分用的模型（热门公开模型，star/unstar 循环不改变其净赞数）
FARM_MODEL = "qwen/Qwen2.5-7B-Instruct"
URL_STAR = BASE + "/api/v1/models/" + FARM_MODEL + "/stars"
URL_UNSTAR = BASE + "/api/v1/models/" + FARM_MODEL + "/unstar"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
TIMEOUT = 30
CTX = ssl.create_default_context()

# 可自动化的规则 key 及其含义
LIKE_KEY = "interaction_like"
DAILY_KEY = "daily_active"
ALIYUN_KEY = "aliyun_bindlogin"


def log(msg):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_cfg():
    if not os.path.exists(CFG_PATH):
        return None
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cfg(cfg):
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def require_cfg():
    cfg = load_cfg()
    if not cfg or not cfg.get("cookie"):
        print("[x] 未配置 cookie，请先 init：python ms_magicube.py init \"<Cookie整行>\"")
        sys.exit(2)
    return cfg


def _req(method, url, cookie, body=None):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("cookie", cookie)
    req.add_header("x-modelscope-accept-language", "zh_CN")
    req.add_header("Referer", BASE + "/")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def _json(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None


# ---------------------------------------------------------------- 规则与余额
def fetch_rules(cookie):
    """返回 {rule_key: 规则dict}"""
    st, raw = _req("GET", URL_RULES, cookie)
    if st != 200:
        return None, st, raw
    data = _json(raw)
    if not data or not data.get("success"):
        return None, st, raw
    rules = {}
    for it in (data.get("data") or []):
        rules[it.get("rule_key")] = it
    return rules, st, raw


def fetch_balance(cookie):
    st, raw = _req("GET", URL_BALANCE, cookie)
    if st != 200:
        return None, st
    data = _json(raw)
    if not data or not data.get("success"):
        return None, st
    d = data.get("data") or {}
    if isinstance(d, dict):
        for k in ("balance", "Balance", "amount", "Amount"):
            if k in d:
                return d[k], st
        return d, st
    return d, st


# ---------------------------------------------------------------- 打卡（会话副作用）
def daily_checkin(cookie):
    """访问首页+魔粒用量页，触发每日登录魔粒发放。返回访问成功数。"""
    ok = 0
    for url in (BASE + "/", BASE + "/magicube/usage"):
        st, _ = _req("GET", url, cookie)
        if st == 200:
            ok += 1
        else:
            log("[打卡] 访问失败 HTTP %s: %s" % (st, url))
    return ok


# ---------------------------------------------------------------- 点赞刷分
def like_once(cookie):
    """PUT stars -> PUT unstar，完成 1 次有效互动（+2 魔粒）。
    返回 (ok, msg)。unstar 失败不致命（净赞数多 1 无所谓）。"""
    st, raw = _req("PUT", URL_STAR, cookie, body=b"{}")
    if st != 200:
        j = _json(raw) or {}
        return False, "star HTTP %s %s" % (st, (j.get("Message") or raw[:120]))
    st2, raw2 = _req("PUT", URL_UNSTAR, cookie, body=b"{}")
    if st2 != 200:
        j = _json(raw2) or {}
        # unstar 失败只是没回退净赞数，互动已计入，不判失败
        return True, "ok（unstar 失败 HTTP %s，净赞数未回退）" % st2
    return True, "ok"


# ---------------------------------------------------------------- 命令
def cmd_init(args):
    """init <cookie整行> —— 支持 "a=1; b=2" 或 fetch 头里的 cookie 值"""
    raw = args[0] if args else ""
    if not raw:
        print("用法: python ms_magicube.py init \"<Cookie整行>\"")
        sys.exit(1)
    # 清洗：去换行/首尾空白
    cookie = " ".join(raw.split())
    cfg = load_cfg() or {}
    cfg["cookie"] = cookie
    cfg["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_cfg(cfg)
    # 立即校验
    rules, st, _ = fetch_rules(cookie)
    if rules is None:
        print("[x] cookie 写入但校验失败 HTTP %s（可能无效或需重抓）" % st)
        sys.exit(3)
    bal, _ = fetch_balance(cookie)
    print("[ok] 凭证已写入并校验通过，魔粒余额: %s" % bal)
    print("     可自动化进度: 登录 %s/250 · 点赞 %s/40" % (
        _daily_credit(rules), _like_progress(rules)[0]))


def _daily_credit(rules):
    n = 0
    for k in (DAILY_KEY, ALIYUN_KEY):
        r = rules.get(k) or {}
        n += int(r.get("today_earned_amount") or 0)
    return n


def _like_progress(rules):
    """(今日已得, 今日剩余次数)"""
    r = rules.get(LIKE_KEY) or {}
    used = int(r.get("today_used") or 0)
    remain = int(r.get("today_remain") or 0)
    return int(r.get("today_earned_amount") or 0), remain


def cmd_status(args):
    cfg = require_cfg()
    rules, st, raw = fetch_rules(cfg["cookie"])
    if rules is None:
        log("[x] 查询规则失败 HTTP %s: %s" % (st, (raw or "")[:200]))
        sys.exit(3)
    bal, _ = fetch_balance(cfg["cookie"])
    log("[魔粒] 余额: %s" % bal)
    log("[登录] 今日已得 %s/250（含阿里云绑定 +50）" % _daily_credit(rules))
    got, remain = _like_progress(rules)
    log("[点赞] 今日已得 %s/40，剩余 %s 次" % (got, remain))


def cmd_rules(args):
    cfg = require_cfg()
    rules, st, raw = fetch_rules(cfg["cookie"])
    if rules is None:
        log("[x] 查询失败 HTTP %s" % st)
        sys.exit(3)
    for k, r in sorted(rules.items(), key=lambda x: -(int(x[1].get("amount") or 0))):
        log("  %-40s +%s/次 剩余%s/天cap%s 已得%s | %s" % (
            k, r.get("amount"), r.get("today_remain"), r.get("daily_cap"),
            r.get("today_earned_amount"), r.get("title")))


def cmd_auto(args):
    """打卡 + 刷点赞（幂等）。定时任务入口。"""
    cfg = require_cfg()
    cookie = cfg["cookie"]
    log("──────────────── 魔搭魔粒 auto ────────────────")
    # 1) 规则
    rules, st, raw = fetch_rules(cookie)
    if rules is None:
        log("[x] 查询规则失败 HTTP %s，可能 cookie 失效: %s" % (st, (raw or "")[:150]))
        sys.exit(3)
    bal0, _ = fetch_balance(cookie)
    log("[开始] 余额 %s · 登录已得 %s/250 · 点赞已得 %s/40（剩余 %s 次）" % (
        bal0, _daily_credit(rules), _like_progress(rules)[0], _like_progress(rules)[1]))

    # 2) 打卡（触发每日登录发放）
    before = _daily_credit(rules)
    ok = daily_checkin(cookie)
    time.sleep(1)
    rules, _, _ = fetch_rules(cookie)
    if rules is None:
        log("[x] 打卡后重查规则失败，cookie 可能失效")
        sys.exit(3)
    after = _daily_credit(rules)
    if after > before:
        log("[打卡] ✅ 本次 +%s（访问 %s/2 页成功，触发每日登录发放）" % (after - before, ok))
    else:
        if after > 0:
            log("[打卡] ℹ️ 今日登录魔粒已发放（%s），重复访问无新增属正常" % after)
        else:
            log("[打卡] ⚠️ 今日未发放且累计为 0，登录态可能未真正建立（请重抓 cookie）")

    # 3) 刷点赞
    got, remain = _like_progress(rules)
    if remain <= 0:
        log("[点赞] 今日 %s/40 已拿满，跳过" % got)
    else:
        log("[点赞] 开始刷 %s 轮（star→unstar 循环，每轮 +2）" % remain)
        done, fail = 0, 0
        for i in range(remain):
            ok, msg = like_once(cookie)
            if ok:
                done += 1
                if done % 5 == 0 or done == remain:
                    log("[点赞] 进度 %s/%s" % (done, remain))
            else:
                fail += 1
                log("[点赞] 第 %s 轮失败: %s" % (i + 1, msg))
                if fail >= 3:
                    log("[点赞] 连续失败 3 次，停止（防风控）")
                    break
            time.sleep(1.2)
        rules, _, _ = fetch_rules(cookie)
        got2, remain2 = _like_progress(rules) if rules else (got, remain)
        log("[点赞] 完成 %s 轮，今日进度 %s/40，剩余 %s 次" % (done, got2, remain2))

    # 4) 汇总
    bal1, _ = fetch_balance(cookie)
    rules, _, _ = fetch_rules(cookie)
    if rules:
        daily = _daily_credit(rules)
        got3, _ = _like_progress(rules)
        log("[结束] 登录 %s/250 · 点赞 %s/40 · 余额 %s（参考，短期魔粒 24h 过期）"
            % (daily, got3, bal1))
    else:
        log("[结束] 余额 %s" % bal1)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    cmd, rest = args[0], args[1:]
    if cmd == "init":
        cmd_init(rest)
    elif cmd == "status":
        cmd_status(rest)
    elif cmd == "rules":
        cmd_rules(rest)
    elif cmd == "auto":
        cmd_auto(rest)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
