#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
cline_credits.py — Cline 账号余额播报（**只有余额，没有每日签到**）
=================================================================
产品: Cline（VS Code 扩展 / Cline CLI），apiBase = https://api.cline.bot

★ 先说结论，避免误期待：
  **Cline 没有每日签到/领积分接口** —— 逆向 Our Free Model 桌面客户端
  （`%LOCALAPPDATA%/Our Free Model/service/packages/standalone/channels/
    business.mjs` 的 `src/cline-credits.ts` 段）确认：
  该模块只有 `fetchClineCreditBalance()` 一个导出，**没有任何 claim/checkin**。
  dsh 上游把 Cline 归为「调用即判定」的不支持渠道，与此处一致。
  故本脚本只做**余额查询**，用于日报里看还剩多少钱，不做任何写操作。

★ 协议（逆向 business.mjs + cline-product.ts）:
  余额  GET https://api.cline.bot/api/v1/users/{account_id}/balance
        → {success:bool, data:{balance:<int>}, error?:string}
        ★balance 是**放大 1e5 倍**的整数 → 真实美元 = balance / 100000
          （CLINE_BALANCE_SCALE = 1e5，实测 5.0 USD → balance=500000）
  ★鉴权: Authorization: Bearer <token>，且 token **必须带 `workos:` 前缀**
        （product.tokenPrefix；脚本会自动补，用户填原始 token 也行）
  ★客户端头（cline-product.ts 的 clientHeaders，照抄）:
        HTTP-Referer: https://cline.bot / X-Title: Cline
        X-IS-MULTIROOT: false / X-CLIENT-TYPE: cline-sdk
  ★account_id 是**必填**的路径参数：缺了没法查（报「凭据缺少账户 id」）

★ 凭据来源：Cline 走 WorkOS OAuth（workOsBase=https://api.workos.com），
  没有像 Qoder/千问那样落在磁盘的明文字段可解密 → **必须抓包**（或手工填）。
  抓包方式：Cline 里触发一次请求，Reqable 过滤 `api.cline.bot`，
  取 Authorization 头（去掉 `Bearer workos:` 前缀）+ 响应里的 account id；
  或直接用 `reqable_hunt.py`（注册表已含 cline）。

配置 cline_config.json: {"access_token": "...", "account_id": "..."}

用法:
  python cline_credits.py status     # 查余额
  python cline_credits.py auto       # 同 status（无签到动作，幂等）
  python cline_credits.py probe      # 打印服务端原文
  python cline_credits.py init       # 写入配置

退出码: 0 成功/未配置跳过   1 失败
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE_DIR, "cline_config.json")

API_BASE = "https://api.cline.bot"
BALANCE_PATH = "/api/v1/users/%s/balance"
TOKEN_PREFIX = "workos:"          # ★缺失会导致 401（服务端按前缀识别 WorkOS 令牌）
BALANCE_SCALE = 100000            # ★balance 是放大 1e5 的整数
TIMEOUT = 30

CLIENT_HEADERS = {
    "HTTP-Referer": "https://cline.bot",
    "X-Title": "Cline",
    "X-IS-MULTIROOT": "false",
    "X-CLIENT-TYPE": "cline-sdk",
}

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def load_cfg():
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _bearer(token):
    """自动补 workos: 前缀（幂等：已带就不重复加）。"""
    t = (token or "").strip()
    if not t:
        return ""
    return t if t.startswith(TOKEN_PREFIX) else TOKEN_PREFIX + t


def _headers(cfg):
    h = {"Accept": "application/json",
         "Authorization": "Bearer %s" % _bearer(cfg.get("access_token", ""))}
    h.update(CLIENT_HEADERS)
    return h


def _request(cfg, path):
    url = API_BASE + path
    req = urllib.request.Request(url, headers=_headers(cfg), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, raw
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        return e.code, raw
    except Exception as e:
        return 0, "%s: %s" % (type(e).__name__, e)


def parse_balance(payload):
    """→ (usd_float, error_str)。判据复刻 parseClineBalanceResponse。"""
    if not isinstance(payload, dict):
        return None, "响应不是 JSON 对象"
    err = payload.get("error")
    if isinstance(err, str) and err.strip():
        return None, err.strip()
    if payload.get("success") is False:
        return None, err or "服务端返回失败"
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, "响应缺少 data 字段"
    raw = data.get("balance")
    if isinstance(raw, str):
        try:
            raw = float(raw.strip())
        except Exception:
            raw = None
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return None, "响应缺少 balance 字段"
    return round(raw / BALANCE_SCALE, 4), ""


def fetch_balance(cfg):
    acct = (cfg.get("account_id") or "").strip()
    if not acct:
        return None, "配置缺少 account_id（Cline 余额接口的路径参数，必填）"
    st, raw = _request(cfg, BALANCE_PATH % urllib.parse.quote(acct, safe=""))
    if st == 0:
        return None, "网络异常：%s" % (raw or "")[:120]
    try:
        payload = json.loads(raw)
    except Exception:
        if st in (401, 403):
            return None, "凭据已失效（HTTP %s）——重新抓包更新 access_token" % st
        return None, "响应非 JSON（HTTP %s）：%s" % (st, (raw or "")[:120])
    usd, err = parse_balance(payload)
    if usd is None:
        return None, err or "余额解析失败"
    return usd, ""


def cmd_status(cfg):
    usd, err = fetch_balance(cfg)
    if usd is None:
        print("[status] 余额查询失败：%s" % err)
        return 1
    print("[status] Cline 余额 = %.4f USD" % usd)
    print("[提示] Cline 无每日签到接口，本步仅播报余额（不执行任何写操作）")
    return 0


def cmd_probe(cfg):
    acct = (cfg.get("account_id") or "").strip()
    st, raw = _request(cfg, BALANCE_PATH % urllib.parse.quote(acct, safe=""))
    print("[probe] HTTP %s" % st)
    print("   %s" % (raw[:600] if raw else "(空响应)"))
    return 0


def cmd_init(argv=None):
    argv = argv or []
    token = acct = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--token" and i + 1 < len(argv):
            token = argv[i + 1]; i += 2
        elif argv[i] == "--account" and i + 1 < len(argv):
            acct = argv[i + 1]; i += 2
        else:
            i += 1
    if not token:
        print("粘贴 Cline access_token（Authorization 头去掉 'Bearer workos:' 后的值）：")
        token = input("Token> ").strip()
    if not acct:
        print("粘贴 account_id（余额接口路径里的用户 id）：")
        acct = input("Account> ").strip()
    if not token or not acct:
        print("[init] 输入不完整，放弃")
        return 1
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump({"access_token": token.strip(), "account_id": acct.strip()},
                  f, ensure_ascii=False, indent=2)
    print("[init] 已写入 %s" % CFG_PATH)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd = sys.argv[1]
    if cmd == "init":
        return cmd_init(sys.argv[2:])
    cfg = load_cfg()
    if not (cfg.get("access_token") or "").strip():
        # Cline 无本机可解密凭据，未配置 ≠ 失效
        print("[skip] 未配置 Cline 凭据（需抓包 api.cline.bot 的 access_token + account_id）；"
              "且 Cline 本身无每日签到接口，本步跳过")
        return 0
    if cmd in ("status", "auto"):
        return cmd_status(cfg)
    if cmd == "probe":
        return cmd_probe(cfg)
    print("[x] 未知命令: %s（status/auto/probe/init）" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
