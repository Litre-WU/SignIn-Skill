#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy 领积分（Buddy 加油站）—— 每日签到 + 派猫猫旅行全自动闭环。

底层调用 totorosir-workbuddy-score 技能的 buddy_station.py：
  - POST /v2/billing/meter/daily-checkin  签到（幂等，100/天）
  - POST /activity/growth/buddy/travel/claim  领取旅行奖励（先领）
  - POST /activity/growth/buddy/travel/depart  派出 Buddy（后派，每日 1 次，5-10 积分）
授权通道：A 本机登录态（atrest.key 已落盘，客户端关闭也能解密）/ B 网页会话 / C 长效令牌。

子命令:
  auto          签到 + 旅行闭环（先领后派，幂等），定时任务用这个
  status        只读播报（不执行任何写操作）
  probe         探测授权通道可用性

退出码: 0 成功（含幂等跳过）/ 1 失败
"""
import json
import os
import subprocess
import sys

PY = sys.executable

HOME = os.path.expanduser("~")
# buddy_station.py 候选位置（skill 目录 / skillhub 分发后缀）
BS_CANDIDATES = [
    os.path.join(HOME, ".workbuddy", "skills", "totorosir-workbuddy-score", "scripts", "buddy_station.py"),
    os.path.join(HOME, ".workbuddy", "skills", "totorosir-workbuddy-score__skillhub", "scripts", "buddy_station.py"),
]


def find_bs():
    for p in BS_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def run_bs(args):
    """调用 buddy_station.py，返回 (ok, stdout, stderr)。"""
    bs = find_bs()
    if not bs:
        return False, "", "未找到 buddy_station.py（skill 未安装？）"
    cmd = [PY, bs] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False, "", "buddy_station.py 执行超时（180s）"
    except Exception as e:
        return False, "", "调用失败: %s" % e
    return r.returncode == 0, r.stdout, r.stderr


def parse_report(out):
    """从 buddy_station.py 的 --json 输出取关键数字。"""
    try:
        d = json.loads(out)
    except Exception:
        return None
    return d


def fmt(d):
    """格式化人类可读汇总。"""
    lines = []
    total = d.get("total_credits")
    streak = d.get("streak_days")
    cr = d.get("checkin_result") or {}
    act = cr.get("action")
    if act == "checked_in":
        lines.append("[签到] 签到成功 +%s 积分" % d.get("daily_credit", "?"))
    elif act == "skipped":
        lines.append("[签到] 今日已签，无需重复打卡")
    else:
        lines.append("[签到] 动作=%s %s" % (act, cr.get("message", "")))
    lines.append("[积分] 余额 %s · 连续 %s 天" % (total, streak))

    t = d.get("travel") or {}
    if t.get("available"):
        state = t.get("state")
        name = t.get("location_name") or ""
        if state == "arrived":
            lines.append("[旅行] Buddy 已到达%s，可领 %s 积分" % (name and "（%s）" % name, t.get("reward_credit")))
        elif state == "traveling":
            lines.append("[旅行] 旅行中（%s）奖励 %s 积分，剩余 %s" % (name, t.get("reward_credit"), t.get("remaining_text")))
        else:
            lines.append("[旅行] 空闲")
    return "\n".join(lines)


def cmd_auto(args):
    ok, out, err = run_bs(["checkin", "--travel-auto", "--json", "--no-toast", "--no-push"])
    if not ok:
        print("[x] WorkBuddy 领积分失败: %s" % (err or out).strip()[:300])
        return 1
    d = parse_report(out)
    if not d:
        print("[x] 无法解析 buddy_station.py 输出")
        print(out.strip()[:500])
        return 1
    print(fmt(d))
    # 旅行闭环动作日志（先领后派的执行记录）
    for entry in (d.get("travel") or {}).get("auto_log") or []:
        print("[旅行] %s" % entry)
    return 0


def cmd_status(args):
    ok, out, err = run_bs(["--json", "--no-toast", "--no-push"])
    if not ok:
        print("[x] 查询失败: %s" % (err or out).strip()[:300])
        return 1
    d = parse_report(out)
    if not d:
        print("[x] 无法解析输出")
        return 1
    print(fmt(d))
    return 0


def cmd_probe(args):
    ok, out, err = run_bs(["--probe"])
    print(out.strip() or err.strip())
    return 0 if ok else 1


def main():
    p = argparse = None
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if cmd in ("-h", "--help"):
        print(__doc__)
        return 0
    handlers = {"auto": cmd_auto, "status": cmd_status, "probe": cmd_probe}
    fn = handlers.get(cmd)
    if not fn:
        print("[x] 未知子命令: %s（可用: auto / status / probe）" % cmd)
        return 1
    return fn(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
