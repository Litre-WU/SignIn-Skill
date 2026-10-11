#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
xhx_office_points.py — 商汤「办公小浣熊」(xiaohuanxiong.com) 每日积分
====================================================================
积分机制(官方 changelog + 规则页 2026-10 确认):
  - 个人免费版: 每日赠送 300 积分, **会话活跃自动发放, 无手动签到接口**
    (实测 GET /api/web/points/v1/balance 即自动入账, 无需任何领取动作)
  - 个人升级版: 每日 500 + 每月 10000;  积分加油包可购买
鉴权: POST /api/web/auth/v1/refresh  body {"refresh_token": <rt>}
      -> data.access_token / data.refresh_token(轮换), 仅需服务端 session 有效(~30天)
  accessToken 短寿命(约3h), 脚本自动续期。
配置 xhx_config.json:
  {"token": <access JWT>, "refresh_token": <rt>, "token_exp": <exp unix>, "rt_updated": iso}

用法:
  python xhx_office_points.py init <access_token> [refresh_token]
  python xhx_office_points.py status     # 查积分余额(顺带触发每日发放)
  python xhx_office_points.py auto       # 每日任务: 续期→查余额确认发放
"""
import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "xhx_config.json")
HOST = "https://xiaohuanxiong.com"
API = HOST + "/api/web"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def load_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_cfg(cfg):
    cfg["cfg_updated"] = now_iso()
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def jwt_exp(token):
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
    except Exception:
        return 0


def http_json(method, url, body=None, token=None):
    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
        "referer": "https://office.xiaohuanxiong.com/",
        "x-client-platform": "web",
        "x-raccoon-language": "zh",
    }
    if token:
        headers["authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
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
        return -1, {"message": "网络异常 %s" % e}


def refresh_token(cfg):
    """用 refresh_token 换新 accessToken(服务端会轮换 rt, 都要保存)。"""
    rt = cfg.get("refresh_token") or ""
    st, j = http_json("POST", API + "/auth/v1/refresh",
                      body={"refresh_token": rt}, token=cfg.get("token"))
    if st == 200 and isinstance(j, dict) and (j.get("data") or {}).get("access_token"):
        d = j["data"]
        cfg["token"] = d["access_token"]
        if d.get("refresh_token"):
            cfg["refresh_token"] = d["refresh_token"]
        cfg["token_exp"] = jwt_exp(d["access_token"])
        save_cfg(cfg)
        return True, "续期成功"
    msg = ""
    if isinstance(j, dict):
        msg = j.get("message") or json.dumps(j, ensure_ascii=False)[:120]
    return False, "HTTP %s %s" % (st, msg)


def ensure_token(cfg):
    """accessToken 剩余 <30 分钟则续期。返回 (cfg, ok, msg)。"""
    exp = int(cfg.get("token_exp") or jwt_exp(cfg.get("token", "")))
    if exp and exp - time.time() < 1800:
        ok, msg = refresh_token(cfg)
        if not ok:
            return cfg, False, msg
    return cfg, True, ""


def get_balance(cfg):
    st, j = http_json("GET", API + "/points/v1/balance", token=cfg.get("token"))
    if st == 200 and isinstance(j, dict) and j.get("code") == 0:
        return j.get("data") or {}, None
    if st == 401 or (isinstance(j, dict) and "token" in str(j.get("message", "")).lower()):
        # token 失效, 强制续期重试一次
        ok, msg = refresh_token(cfg)
        if ok:
            st, j = http_json("GET", API + "/points/v1/balance", token=cfg.get("token"))
            if st == 200 and isinstance(j, dict) and j.get("code") == 0:
                return j.get("data") or {}, None
        return None, "token 续期失败: %s —【小浣熊失效】需重抓 refresh_token" % (msg or "")
    return None, "HTTP %s %s" % (st, str(j)[:150])


def cmd_init():
    args = sys.argv[2:]
    if not args or not args[0]:
        print("用法: python xhx_office_points.py init <access_token> [refresh_token]")
        return 2
    cfg = load_cfg() or {}
    cfg["token"] = args[0].strip()
    cfg["token_exp"] = jwt_exp(cfg["token"])
    if len(args) > 1 and args[1].strip():
        cfg["refresh_token"] = args[1].strip()
    data, err = get_balance(cfg)
    if err:
        print("[警告] accessToken 验证失败: %s" % err)
    else:
        print("[OK] accessToken 有效, 可用积分 %s" % data.get("available_points"))
    save_cfg(cfg)
    print("[OK] 已写入 %s" % CFG_PATH)
    print("     若 init 只给了 access_token, 请之后补抓 refresh_token(网页 F12  Network 里 /auth/v1/refresh 请求的 body), 否则 3 小时后续期失败。")
    return 0


def cmd_status():
    cfg = load_cfg()
    if not cfg or not cfg.get("token"):
        print("[失败] 未配置。执行 init")
        return 2
    data, err = get_balance(cfg)
    if err:
        print("[失败] %s" % err)
        return 3
    exp = int(cfg.get("token_exp") or 0)
    left_h = (exp - time.time()) / 3600 if exp else 0
    print("[积分] 可用 %s · 每日 %s · 奖励 %s · 充值 %s" % (
        data.get("available_points"), data.get("daily_points"),
        data.get("reward_points"), data.get("topup_points")))
    print("[token] accessToken 剩余 %.1f 小时 · refresh_token: %s" % (
        left_h, "已配置" if cfg.get("refresh_token") else "未配置(3小时后失效)"))
    return 0


def cmd_auto():
    cfg = load_cfg()
    if not cfg or not cfg.get("token"):
        print("[失败] 未配置凭证 —【小浣熊失效】需 init(抓包 access/refresh token)")
        return 2
    cfg, ok, msg = ensure_token(cfg)
    if not ok:
        print("[失败] %s —【小浣熊失效】" % msg)
        return 3
    data, err = get_balance(cfg)
    if err:
        print("[失败] %s" % err)
        return 3
    print("[积分] 可用 %s · 每日池 %s（每日300为会话活跃自动发放, balance 查询即触发, 无需手动签到）" % (
        data.get("available_points"), data.get("daily_points")))
    return 0


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
