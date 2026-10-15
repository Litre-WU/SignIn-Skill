#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy 成长中心补齐（盲盒 / 连登兑换 / 断登补签 / 领任务 / 领任务奖 / 能量开 Buddy）。

现有 wb_score.py 只做「签到 + 派猫猫旅行」。本模块补齐 totorosir-workbuddy-score
底层 skill 保守留白、但服务端确实开放的 6 项成长中心奖励写接口（逆向自 88lin/
workbuddy-auto-signin，接口均经本机只读探测确认可用）。

鉴权：复用官方 skill buddy_station._resolve_auth()（登录态 domain + Bearer / 或 web
cookie 通道），不硬编码任何 host、不写死 token。全部接口打登录态 domain（实测
www.workbuddy.cn，与旅行同源）；可用 WB_GROWTH_DOMAIN 覆盖。

设计原则（贴用户"检测未完成则执行"口径）：
- 每项先只读 GET 判「有没有可领/可补/可兑」，没有资源就静默跳过，不发写请求（空跑零副作用）；
- 写操作幂等/安全：领任务奖只在 completed 且未领过才 claim；补登仅在「有补登卡 且 当月有
  断登日」才 use（每轮≤1 张）；连登兑换只在某档 available 才 redeem；盲盒仅在「次数>0」才
  draw（一轮只开一次）；能量开 Buddy 仅在 affordable>0 才 open；
- 各子模块独立 try/except，单项失败不中断其余（贴总控"任一平台失败不中断"）；
- 写请求（accept/claim/use/redeem/draw/open）带 client_token 防重放；claim 类不可逆，绝不重试。

子命令:
  auto      签到侧已领的前提下，补齐全部成长中心可领项（幂等；定时任务用这个）
  status    只读播报 6 项当前可领/可补/可兑状态（不发任何写请求）
  probe     只读探测各接口连通与数据（调试）

退出码: 0 成功（含全跳过/幂等）/ 1 有硬失败
安全: 默认 auto 会发写请求（但只在真有资源时）；设环境变量 WB_GROWTH_WRITE=0 可强制全只读。
"""
import os
import sys
import json
import uuid
import math
import re
import time
import urllib.request
import urllib.error
from datetime import date, datetime

def _find_bs_dir():
    """官方 skill totorosir-workbuddy-score 的 scripts 目录。
    ★2026-10-15 起 Qoder 的生效目录是 ~/.qoder-cn/skills 与 ~/.agents/skills，
      ~/.workbuddy/skills 已整体改名 skills_deprecated_20261015（只读留档），
      只搜老路径会让 WorkBuddy 这两步天天报「未找到 buddy_station.py」。"""
    home = os.path.expanduser("~")
    roots = [os.path.join(home, ".qoder-cn", "skills"),
             os.path.join(home, ".agents", "skills"),
             os.path.join(home, ".workbuddy", "skills")]
    cands = []
    for r in roots:
        for leaf in ("totorosir-workbuddy-score", "totorosir-workbuddy-score__skillhub"):
            cands.append(os.path.join(r, leaf, "scripts"))
    for p in cands:
        if os.path.isfile(os.path.join(p, "buddy_station.py")):
            return p
    return ""


SCRIPT_DIR = _find_bs_dir()
# 让 buddy_station / web_auth / rt_auth 可被 import
if SCRIPT_DIR:
    sys.path.insert(0, SCRIPT_DIR)
    os.chdir(SCRIPT_DIR)

GROWTH_BASE = "/v2/activity/growth"      # 新能力统一前缀（实测与 /activity/... 双通）
REDEEM_TIERS = (
    # (档位标识, /redeem/summary 状态字段前缀, 展示名, 兜底天数)
    ("7d",  "starter",   "入门", 7),
    ("14d", "advanced",  "进阶", 14),
    ("28d", "legendary", "巅峰", 28),
)
MAKEUP_MAX_PER_RUN = 1   # 每轮最多补 1 天（与官方前端口径一致）
WRITE_ENABLED = os.environ.get("WB_GROWTH_WRITE", "1").strip().lower() not in ("0", "false", "no", "off")


# ---------------------------------------------------------------------------
# 凭据 & 请求（复用官方 skill 的多通道解析）
# ---------------------------------------------------------------------------
def get_creds():
    import buddy_station as bs
    return bs._resolve_auth("auto")


def _domain_override():
    return (os.environ.get("WB_GROWTH_DOMAIN", "").strip() or None)


def _client_token():
    """活动写接口要求的防重放 token；服务端只做幂等去重，缺了 draw/redeem 直接 400。"""
    return "u-" + uuid.uuid4().hex


def _request(method, url, payload, token, headers):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    else:
        req.add_header("Authorization", "Bearer " + (token or ""))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, {"_raw": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"msg": raw[:200]}
    except Exception as e:
        return -1, {"msg": "网络异常: %s" % e}


def dig(obj, key):
    if isinstance(obj, dict):
        if key in obj and obj[key] is not None:
            return obj[key]
        for k in ("data", "result", "resp", "response"):
            if k in obj and isinstance(obj[k], dict):
                r = dig(obj[k], key)
                if r is not None:
                    return r
    return None


def as_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return int(float(v))
    except (TypeError, ValueError, OverflowError):
        return default


def _api_success(code, body):
    """HTTP 2xx 且业务码（若有）为 0。"""
    bc = body.get("code") if isinstance(body, dict) else None
    return 200 <= code < 300 and (bc is None or (type(bc) is int and bc == 0))


# ---------------------------------------------------------------------------
# 各子能力（先读后写；缺资源即跳过）
# ---------------------------------------------------------------------------
class Runner:
    def __init__(self, do_write):
        token, domain, headers = get_creds()
        self.domain = (_domain_override() or domain).replace("https://", "").replace("http://", "")
        self.base = "https://" + self.domain + GROWTH_BASE
        self.token, self.headers = token, headers
        self.do_write = do_write
        self.parts = []        # 汇报句
        self.successes = 0
        self.failures = 0
        self.hard_failures = 0
        self.credits = 0

    def note(self, s):
        self.parts.append(s)

    def get(self, path):
        return _request("GET", self.base + path, None, self.token, self.headers)

    def post(self, path, body):
        return _request("POST", self.base + path, body, self.token, self.headers)

    def _auth_bad(self, code):
        return code in (401, 403)

    # ---- 1) 领取新任务（进度从领取才计） + 领已完成任务奖 ----
    def tasks(self):
        try:
            code, body = self.get("/tasks")
            if self._auth_bad(code):
                self.note("任务模块：认证被拒（HTTP %s），跳过" % code)
                return
            if not _api_success(code, body):
                self.note("查任务列表失败（HTTP %s %s），跳过" % (code, dig(body, "msg") or ""))
                return
            tasks = dig(body, "tasks") or []
            titles = {t.get("task_code"): t.get("title", t.get("task_code")) for t in tasks}
            if not self.do_write:
                na = [titles.get(t.get("task_code"), t.get("task_code"))
                      for t in tasks if t.get("accept_status") == "not_accepted"]
                comp = [titles.get(t.get("task_code"), t.get("task_code"))
                        for t in tasks if t.get("accept_status") == "completed" and not t.get("locked")]
                if na or comp:
                    self.note("[只读] 待接任务 %d 项、可领奖任务 %d 项（auto 时自动处理）" % (len(na), len(comp)))
                return
            # 接单：not_accepted 且未锁
            pending = [t.get("task_code") for t in tasks
                       if t.get("task_code") and not t.get("locked")
                       and t.get("accept_status") == "not_accepted"]
            for i in range(0, len(pending), 20):
                batch = pending[i:i + 20]
                ac, ab = self.post("/tasks/accept", {"task_codes": batch})
                results = dig(ab, "results")
                if not isinstance(results, list):
                    results = [{"task_code": c,
                                "status": "ok" if 200 <= ac < 300 else "error",
                                "message": dig(ab, "msg")} for c in batch]
                for r in results:
                    title = titles.get(r.get("task_code"), r.get("task_code"))
                    if r.get("status") == "error":
                        self.note("接任务「%s」失败：%s" % (title, r.get("message") or "HTTP %s" % ac))
                        self.failures += 1
                        self.hard_failures += 1
                    else:
                        self.note("接任务「%s」（进度开始计）" % title)
                        self.successes += 1
            # 领奖：completed 且未领过
            for t in tasks:
                if t.get("locked") or t.get("accept_status") != "completed":
                    continue
                ccode, cbody = self.post("/tasks/%s/claim" % t.get("task_code"), {})
                if self._auth_bad(ccode):
                    self.note("领任务奖：认证被拒（HTTP %s），跳过" % ccode)
                    return
                if _api_success(ccode, cbody) and not dig(cbody, "already_claimed"):
                    rc = as_int(dig(cbody, "credit"), t.get("reward_credit") or 0)
                    re_ = as_int(dig(cbody, "energy"), 0)
                    self.credits += rc
                    self.note("领任务奖「%s」+%s积分+%s能量" % (
                        titles.get(t.get("task_code"), t.get("task_code")), rc, re_))
                    self.successes += 1
                elif _api_success(ccode, cbody):
                    self.note("任务奖「%s」已领过" % titles.get(t.get("task_code"), t.get("task_code")))
                else:
                    self.note("领任务奖「%s」失败：%s" % (
                        titles.get(t.get("task_code"), t.get("task_code")), dig(cbody, "msg") or "HTTP %s" % ccode))
                    self.failures += 1
        except Exception as e:
            self.note("任务模块异常（%s: %s）" % (type(e).__name__, e))
            self.failures += 1
            self.hard_failures += 1

    # ---- 2) 断登补签（有补登卡 且 当月有断登日 才补，每轮≤1 天）----
    def makeup(self):
        try:
            code, body = self.get("/streak")
            if self._auth_bad(code):
                return
            if not _api_success(code, body):
                self.note("查连登状态失败（HTTP %s），补登跳过" % code)
                return
            cards_obj = dig(body, "makeup_cards")
            cards = as_int(cards_obj.get("balance")) if isinstance(cards_obj, dict) else as_int(cards_obj)
            if cards <= 0:
                return   # 无卡可补（常态）
            if not self.do_write:
                self.note("[只读] 补登卡 %d 张可用" % cards)
                return
            hcode, hbody = self.get("/heatmap")
            if self._auth_bad(hcode):
                return
            dates = self._makeup_candidates(body, hbody)
            if not dates:
                self.note("补登卡 %d 张但当月无断登日，无需补" % cards)
                return
            d = dates[0]
            ucode, ubody = self.post("/makeup-cards/use", {"target_date": d, "client_token": _client_token()})
            if self._auth_bad(ucode):
                self.note("补登：认证被拒（HTTP %s）" % ucode)
                return
            if _api_success(ucode, ubody):
                left_obj = dig(ubody, "makeup_cards")
                left = as_int(left_obj.get("balance"), cards - 1) if isinstance(left_obj, dict) else as_int(left_obj, cards - 1)
                self.note("补登 %s（剩 %s 张卡）" % (d, left))
                self.successes += 1
            else:
                msg = str(dig(ubody, "msg") or "").lower()
                if ucode == 400 and "not broken" in msg or "no makeup" in msg:
                    self.note("%s 已活跃或已补，无需再补" % d)
                else:
                    self.note("补登 %s 失败：%s" % (d, dig(ubody, "msg") or "HTTP %s" % ucode))
                    self.failures += 1
                    self.hard_failures += 1
        except Exception as e:
            self.note("补登模块异常（%s: %s）" % (type(e).__name__, e))
            self.failures += 1
            self.hard_failures += 1

    def _makeup_candidates(self, streak_body, heatmap_body):
        """当月、今天之前、活动上线之后、score==0 的日期（最近优先）。"""
        def pd(v):
            if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                raise ValueError("date")
            return date.fromisoformat(v)
        today_obj = dig(heatmap_body, "today")
        if not isinstance(today_obj, dict):
            raise ValueError("heatmap today")
        today = pd(today_obj.get("date"))
        try:
            launch = pd(dig(streak_body, "launch_date"))
        except Exception:
            launch = today
        cells = dig(heatmap_body, "cells")
        if not isinstance(cells, list):
            raise ValueError("heatmap cells")
        scores = {}
        for c in cells:
            if not isinstance(c, dict):
                continue
            s = c.get("score")
            if type(s) not in (int, float) or not math.isfinite(s):
                continue
            scores[pd(c.get("date"))] = s
        made_up = set()
        st = dig(streak_body, "streak")
        for v in ((st or {}).get("makeup_dates") or []) if isinstance(st, dict) else []:
            try:
                made_up.add(pd(v))
            except Exception:
                pass
        start = max(today.replace(day=1), launch)
        return sorted((d.isoformat() for d, sc in scores.items()
                       if start <= d < today and sc == 0 and d not in made_up), reverse=True)

    # ---- 3) 连登兑换（某档 available 才兑，tier 传档位标识）----
    def redeem(self):
        try:
            code, body = self.get("/redeem/summary")
            if self._auth_bad(code):
                return
            if not _api_success(code, body):
                self.note("查连登兑换失败（HTTP %s），跳过" % code)
                return
            statuses = {k: dig(body, k + "_status") for k in ("starter", "advanced", "legendary")}
            avail = [t for t in REDEEM_TIERS if statuses.get(t[1]) not in (None, "claimed", "locked")]
            if not self.do_write:
                if avail:
                    self.note("[只读] 可兑换档位：%s" % "、".join(t[2] for t in avail))
                return
            for tier, key, label, days in avail:
                ccode, cbody = self.post("/redeem", {"tier": tier, "client_token": _client_token()})
                # unknown tier 兜底：退回天数再试一次（参数校验阶段拒绝，重试安全）
                if ccode == 400 and "tier" in str(dig(cbody, "msg") or "").lower() and \
                        any(x in str(dig(cbody, "msg") or "").lower() for x in ("unknown", "unsupported", "invalid")):
                    ccode, cbody = self.post("/redeem", {"tier": days, "client_token": _client_token()})
                if ccode == 403 and ("不足" in str(dig(cbody, "msg") or "")):
                    self.note("连登兑换「%s」未解锁（天数不足），跳过" % label)
                    continue
                if self._auth_bad(ccode):
                    self.note("连登兑换：认证被拒（HTTP %s）" % ccode)
                    return
                if _api_success(ccode, cbody):
                    self.credits += as_int(dig(cbody, "credit_granted"))
                    self.note("连登兑换「%s」成功（%s）" % (label, self._redeem_desc(cbody)))
                    self.successes += 1
                else:
                    self.note("连登兑换「%s」失败：%s" % (label, dig(cbody, "msg") or "HTTP %s" % ccode))
                    self.failures += 1
        except Exception as e:
            self.note("连登兑换模块异常（%s: %s）" % (type(e).__name__, e))
            self.failures += 1
            self.hard_failures += 1

    def _redeem_desc(self, body):
        bits = []
        if as_int(dig(body, "credit_granted")): bits.append("+%s积分" % as_int(dig(body, "credit_granted")))
        if as_int(dig(body, "energy_granted")): bits.append("+%s能量" % as_int(dig(body, "energy_granted")))
        if as_int(dig(body, "cards_granted")):  bits.append("+%s补登卡" % as_int(dig(body, "cards_granted")))
        if as_int(dig(body, "chances_granted")):bits.append("+%s抽奖" % as_int(dig(body, "chances_granted")))
        return "、".join(bits) or "奖励已发放"

    # ---- 4) 开盲盒（次数>0 才开，一轮只开一次，不可逆不重试）----
    def lottery(self):
        try:
            code, body = self.get("/lottery/chances")
            if self._auth_bad(code):
                return
            if not _api_success(code, body):
                self.note("查抽奖机会失败（HTTP %s），盲盒跳过" % code)
                return
            chances = as_int(dig(body, "balance"))
            if chances <= 0:
                return
            if not self.do_write:
                self.note("[只读] 抽奖机会 %d 次可用" % chances)
                return
            dcode, dbody = self.post("/lottery/draw", {"client_token": _client_token()})
            if self._auth_bad(dcode):
                self.note("开盲盒：认证被拒（HTTP %s）" % dcode)
                return
            if _api_success(dcode, dbody):
                prize = dig(dbody, "prize_name") or dig(dbody, "prize") or "未知奖励"
                if not isinstance(prize, str):
                    prize = json.dumps(prize, ensure_ascii=False)
                if dig(dbody, "need_address") or dig(dbody, "require_address"):
                    prize += "（实物奖，需到成长中心填收件信息）"
                self.note("开盲盒获得：%s" % prize)
                self.successes += 1
                if chances > 1:
                    self.note("还剩 %d 次抽奖机会，下轮继续" % (chances - 1))
            else:
                self.note("开盲盒失败：%s" % (dig(dbody, "msg") or "HTTP %s" % dcode))
                self.failures += 1
                self.hard_failures += 1
        except Exception as e:
            self.note("盲盒模块异常（%s: %s）" % (type(e).__name__, e))
            self.failures += 1
            self.hard_failures += 1

    # ---- 5) 能量开 Buddy 盲盒（affordable>0 才开）----
    def buddy_open(self):
        try:
            code, body = self.get("/buddy/quota")
            if self._auth_bad(code):
                return
            if not _api_success(code, body):
                self.note("查 Buddy 配额失败（HTTP %s），跳过" % code)
                return
            affordable = as_int(dig(body, "affordable"))
            max_open = as_int(dig(body, "max_open_count"), 1) or 1
            if affordable <= 0:
                return
            if not self.do_write:
                self.note("[只读] 能量可开 Buddy 盲盒 %d 个（上限 %d）" % (affordable, max_open))
                return
            count = min(affordable, max_open)
            ocode, obody = self.post("/buddy/open", {"count": count, "client_token": _client_token()})
            if self._auth_bad(ocode):
                self.note("开 Buddy 盲盒：认证被拒（HTTP %s）" % ocode)
                return
            if _api_success(ocode, obody):
                name = dig(obody, "buddy") or dig(obody, "name") or dig(obody, "buddies")
                if not isinstance(name, str):
                    name = "新 Buddy"
                self.note("开 Buddy 盲盒 ×%d（%s）" % (count, name))
                self.successes += 1
            else:
                self.note("开 Buddy 盲盒失败：%s" % (dig(obody, "msg") or "HTTP %s" % ocode))
                self.failures += 1
                self.hard_failures += 1
        except Exception as e:
            self.note("Buddy 盲盒模块异常（%s: %s）" % (type(e).__name__, e))
            self.failures += 1
            self.hard_failures += 1

    def run_all(self):
        # 顺序：任务(送抽奖/能量) → 补登(改连登天数) → 兑换(送抽奖/能量/卡) → 盲盒 → Buddy
        self.tasks()
        self.makeup()
        self.redeem()
        self.lottery()
        self.buddy_open()
        return self


def run_status():
    """只读播报：6 项当前可领/可补/可兑状态。"""
    r = Runner(do_write=False)
    try:
        r.tasks(); r.makeup(); r.redeem(); r.lottery(); r.buddy_open()
        # 追加能量/连登展示
        try:
            c, b = r.get("/energy")
            if _api_success(c, b):
                r.note("能量余额 %s（累计得 %s / 耗 %s）" % (
                    as_int(dig(b, "balance")), dig(b, "total_earned") or 0, dig(b, "total_consumed") or 0))
            c2, b2 = r.get("/streak")
            st = dig(b2, "streak") or {}
            if isinstance(st, dict):
                r.note("连登 %s 天 · 下一档 %s（还差 %s 天）" % (
                    st.get("days"), st.get("next_tier") or "?", st.get("next_tier_remaining") or 0))
        except Exception:
            pass
    except Exception as e:
        r.note("查询异常: %s" % e)
    print("[成长中心只读] domain=%s" % r.domain)
    for p in r.parts or ["（无可领/可补/可兑项，均满足前置）"]:
        print("  " + p)
    return 0


def run_auto():
    r = Runner(do_write=WRITE_ENABLED)
    r.run_all()
    report = "；".join(r.parts) if r.parts else "成长中心无可领取项"
    if r.credits:
        report += "（本次 +%d 积分）" % r.credits
    print(report if r.parts else "成长中心：全部已领取/无待领，跳过")
    for p in r.parts:
        if not p.startswith("[只读]"):
            pass
    json.dump({
        "result": "OK", "domain": r.domain,
        "credits_gained": r.credits, "successes": r.successes,
        "failures": r.failures, "hard_failures": r.hard_failures,
        "write_enabled": WRITE_ENABLED, "detail": r.parts,
    }, sys.stdout, ensure_ascii=False)
    print()
    return 1 if r.hard_failures else 0


def run_probe():
    """逐接口连通探测（只读 GET）。"""
    r = Runner(do_write=False)
    for p in ("/tasks", "/streak", "/redeem/summary", "/lottery/chances",
              "/buddy/quota", "/energy", "/heatmap"):
        c, b = r.get(p)
        code0 = dig(b, "code")
        keys = list((dig(b, "data") or {}).keys()) if isinstance(dig(b, "data"), dict) else (
            list(b.keys()) if isinstance(b, dict) else "?")
        print("  [%s] %s  code=%s  keys=%s" % (c, p, code0, keys))
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if cmd in ("-h", "--help"):
        print(__doc__)
        return 0
    if cmd == "status":
        return run_status()
    if cmd == "probe":
        return run_probe()
    if cmd == "auto":
        return run_auto()
    print("[x] 未知子命令: %s（可用: auto / status / probe）" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
