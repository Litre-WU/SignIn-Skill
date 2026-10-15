#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
loomy_points.py — 讯飞 Loomy (loomy.xunfei.cn) 每日积分
=========================================================
接口(2026-10-12 页面实测修正 —— 原 /api/... 已 404，正确前缀是 /api/workspace/...):
  GET /api/workspace/auth/points-summary       个人积分汇总 {permanent, daily}（★有效）
  GET /api/workspace/team/points/balance       团队积分余额
  GET /api/workspace/team/points/daily-limit   今日额度
  GET /api/workspace/team/points/records       积分流水
  ★团队三接口在个人版(未加入团队)下返回 HTTP 400 {"code":"100001","error":"请先选择一个团队"}，
    属正常业务态不是失效，脚本已容错。
鉴权: 纯 Cookie(讯飞统一登录态), 无独立 refresh 接口 → cookie 失效需重抓。
配置 loomy_config.json: {"cookie": "<完整 Cookie 头>", "cookie_updated": iso}

用法:
  python loomy_points.py init "<cookie 串>"
  python loomy_points.py status
  python loomy_points.py auto     # 每日: 查汇总+今日额度(触发/确认每日发放)
"""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "loomy_config.json")
HOST = "https://loomy.xunfei.cn"
API = "/api/workspace"  # 2026-10-12 实测: 直连 /api/... 返回 404，须带 /workspace 前缀

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_cfg(cfg):
    cfg["cookie_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get(path, cookie):
    req = urllib.request.Request(HOST + path, headers={
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "cookie": cookie,
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
        "referer": HOST + "/chat",
    })
    for attempt in (1, 2):
        try:
            r = urllib.request.urlopen(req, timeout=25, context=CTX)
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                return e.code, {"raw": raw.decode("utf-8", "replace")[:200]}
        except Exception as e:
            # 纯传输层抖动（read timeout / 连接重置）重试一次再判失败，
            # 否则一次网络打嗝就让总控把整个 Loomy 报成【失效】
            if attempt == 1:
                time.sleep(3)
                continue
            return -1, {"message": "网络异常 %s（已重试 1 次）" % e}


def fmt_data(d):
    """容错打印: 常见字段直出, 其余 dump 截断。"""
    if not isinstance(d, dict):
        return str(d)[:200]
    return json.dumps(d, ensure_ascii=False)[:400]


def cmd_init():
    if len(sys.argv) < 3 or not sys.argv[2].strip():
        print("用法: python loomy_points.py init \"<cookie 串>\"")
        print("抓取: 浏览器登录 loomy.xunfei.cn → F12 → Network 任意 /api/ 请求 → 复制整行 cookie 头")
        return 2
    cookie = sys.argv[2].strip().strip('"')
    cfg = {"cookie": cookie}
    st, j = get(API + "/auth/points-summary", cookie)
    if st == 200 and isinstance(j, dict) and (j.get("success") or "data" in j):
        print("[OK] cookie 有效:", fmt_data(j.get("data") or j))
    elif st == 401:
        print("[警告] cookie 无效(401 请先登录) — 请从已登录浏览器重新抓取")
    else:
        print("[警告] 验证返回 HTTP %s %s" % (st, fmt_data(j)))
    save_cfg(cfg)
    print("[OK] 已写入 %s" % CFG_PATH)
    return 0


def _auto_core(quiet_fail=False):
    cfg = load_cfg()
    if not cfg or not cfg.get("cookie"):
        print("[失败] 未配置 cookie —【Loomy失效】需 init(F12 抓 cookie)")
        return 2
    st, j = get(API + "/auth/points-summary", cfg["cookie"])
    if st == 401:
        print("[失败] cookie 失效(401) —【Loomy失效】需重抓 cookie")
        return 3
    if st != 200 or not isinstance(j, dict):
        print("[失败] points-summary HTTP %s %s" % (st, fmt_data(j)))
        return 3
    data = j.get("data") if "data" in j else j
    print("[积分] %s" % fmt_data(data))
    # 团队额度接口: 个人版未加入团队时返回 400 {"code":"100001","error":"请先选择一个团队"} -> 正常业务态
    st2, j2 = get(API + "/team/points/daily-limit", cfg["cookie"])
    if st2 == 200 and isinstance(j2, dict) and (j2.get("success") or "data" in j2):
        print("[今日额度] %s" % fmt_data(j2.get("data") if "data" in j2 else j2))
    elif isinstance(j2, dict) and str(j2.get("error") or "").find("团队") >= 0:
        print("[今日额度] 个人版未加入团队，跳过（属正常）")
    return 0


def cmd_status():
    return _auto_core()


def cmd_auto():
    # 每日积分: Loomy 无手动签到接口(前端 bundle 全量路径里无 sign/checkin/claim),
    # 每日赠送随站点活跃自动入账 —— 本脚本每日查询即确认入账 + 保持会话活跃。
    return _auto_core()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "init":
        sys.exit(cmd_init())
    elif cmd == "status":
        sys.exit(cmd_status())
    elif cmd == "auto":
        sys.exit(cmd_auto())
    else:
        print(__doc__)
        sys.exit(1)
