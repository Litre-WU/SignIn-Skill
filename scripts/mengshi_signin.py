#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MENGSHI (猛士汽车) 每日签到/任务脚本
Version: 2026-10-26

小程序 AppId: wx05c1c045b190e118
Gateway / c-access 双域架构，CryptoJS AES-ECB(PKCS7), RSA-PKCS1v1.5 签名。

=== 凭证（用户需从真实客户端抓包） ===
1) token (session): 从登录后响应或 Cookie 中获取字符串值，格式如："CookieName=Value; ..."
   - 登录接口：/v1/vip/app/wxLogin（需小程序 code 换取 token；目前仅支持 cookie 模式）
   - 若无有效 cookie，返回 code:-10001 "请求体解密失败" 或 -10001 "invalid parameter"

=== API 清单 ===
sign_in        → /v2/app/vip/account/getSignInfo    （获取签到信息）
task_list      → /v1/app/vip/taskClass/list         （任务分类列表）
task_details   → /v1/app/vip/task/details/list/<time>（具体任务列表）
task_finish    → /v1/vip/task/finish/<actionId>     （完成任务/签到）
               其中每日签到 actionId = "rwqd"
late_sign      → /v2/app/vip/account/lateSign/<time>（补签）
points_get     → /v1/vip/account/get                （积分余额）

=== Crypto ===
aes_key = SNJmue8vh2X2dyhR      (production)
rsa_pub = <from store/config.js production PEM>
mode = ECB (非 CBC，与代码中的 CBC label 不同)
request body: {req: aes(json.dumps(biz)+"&ts"), sign: oracle_sign}
headers: sign-encrypt=rsa(plain_sign), platform=miniProgram, version=1.5.0, actid=68
oracle: POST gateway.m-hero.com/v2/sign/get {"aesKey":rsa(aes_key), platform, url}
"""
import argparse
import base64
import datetime
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad

SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "mengshi_config.json"


# =========================
# Constants from store/config.js (production)
# =========================
AES_KEY = b"SNJmue8vh2X2dyhR"
RSA_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAoAWeKqTASqvXUNSe5gplm2brUVBu9LstgE6Etzu8u/TELpnFjsgkXP3yXAM53peu6xcIu/4cpLC3jJlvz8bfgTsm2ai1u/qRlkJQRXaq6jvHQLu/u4olGqsDIq1Y/wz4FcwCnErx+s+mAV0hQFzyPl/Lxj+FEMSy2Ce0+0dLfuuAi0v77/q7h5inwe/g7C+g8LkYjMkj+ke7uGu1qIF8w0GBoRcmCiwHokHB75SkSlN+bHpsqOoFidsk7Vuw6svlpow9C3FnroTzU20p7V8kTuMl4RFihFGeUlfROJUtkQZ0XzfYps0VntOwZLrPb0Oj1P65zPYioGrR5hAEgx543wIDAQAB
-----END PUBLIC KEY-----"""
VERSION = "1.5.0"
ACTID = "68"
GATEWAY = "https://gateway.m-hero.com"   # baseUrl.production（签名服务）
API_HOST = "https://c-access.m-hero.com"  # apiUrl.production（VIP endpoints）
rng_key = RSA.import_key(RSA_PEM)


def ae(p: str) -> str:
    """AES-ECB encrypt"""
    ct = AES.new(AES_KEY, AES.MODE_ECB).encrypt(pad(p.encode("utf-8"), 16))
    return base64.b64encode(ct).decode("ascii")


def ad(b: str) -> str:
    """AES-ECB decrypt"""
    pt = AES.new(AES_KEY, AES.MODE_ECB).decrypt(base64.b64decode(b))
    try:
        return unpad(pt, 16).decode("utf-8")
    except Exception:
        # 有时 padding 不正确但内容正确
        return pt.rstrip(b"\x00").decode("utf-8", "replace")


def re_(p: str) -> str:
    """RSA-PKCS1v1.5 encrypt"""
    ct = PKCS1_v1_5.new(rng_key).encrypt(p.encode("utf-8"))
    return base64.b64encode(ct).decode("ascii")


def http_post(url: str, body: dict, headers: dict, timeout: int = 20):
    d = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=d, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def get_sign(target_url: str) -> str:
    """调用签名服务获取 plain_sign"""
    w = re_(AES_KEY.decode())
    h = {
        "Content-Type": "application/json",
        "sign-encrypt": w,
        "platform": "miniProgram",
        "version": VERSION,
        "actid": ACTID,
    }
    status, raw = http_post(GATEWAY + "/v2/sign/get", {"aesKey": w, "platform": "miniProgram", "url": target_url}, h)
    if status != 200:
        raise ValueError(f"get_sign HTTP{status}: {raw[:200]}")
    j = json.loads(raw)
    return j.get("data", {}).get("sign") or j.get("result", {}).get("sign")


def make_request(url: str, biz: dict, cookie: str):
    ts = int(time.time() * 1000)
    sign = get_sign(url)
    body = {"req": ae(json.dumps(biz) + "&" + str(ts)), "sign": sign}
    h = {
        "Content-Type": "application/json",
        "Cookie": cookie,
        "sign-encrypt": re_(sign),
        "platform": "miniProgram",
        "version": VERSION,
        "actid": ACTID,
    }
    status, raw = http_post(url, body, h)
    if status not in (200, 400, 401):
        print("[!] HTTP", status, raw[:200])
        raise RuntimeError("HTTP error")
    j = json.loads(raw)
    if "resp" in j and j["resp"]:
        dec = ad(j["resp"])
        try:
            return json.loads(dec), status
        except Exception:
            print("[⚠️] Decrypt OK but JSON parse failed:", dec[:300])
            return {}, status
    return j.get("result", {}), status


def load_cookie_from_env() -> str:
    """从环境变量或 config.json 读取 cookie"""
    env_val = os.getenv("MENGSHI_COOKIE")
    if env_val and len(env_val) > 20:
        return env_val
    cfg = CONFIG_FILE
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return data.get("cookie") or ""
        except Exception:
            pass
    return ""


def do_signin(cookie: str):
    """执行签到：完成 rwqd 任务（每日签到 = finish actionId=rwqd）"""
    url = API_HOST + "/v1/vip/task/finish/rwqd"
    print(f"[+] Signing in...")
    resp, status = make_request(url, {}, cookie)
    if status == 401:
        print("[-] Token expired / invalid. Please capture a fresh cookie and update.")
        print("   Guidance: open mini-program '确认签到', view network response 'Set-Cookie' / login response")
        return False
    msg = resp.get("msg", "") or resp.get("message", "") or ""
    ret_code = resp.get("code", 0)
    print(f"[-] ret={ret_code}, msg={msg}")
    print(f"[*] Raw: {json.dumps(resp, ensure_ascii=False)[:300]}")
    return True


def do_status(cookie: str):
    """获取签到状态 & 积分"""
    url = API_HOST + "/v2/app/vip/account/getSignInfo"
    print(f"[+] Querying sign info...")
    resp, status = make_request(url, {}, cookie)
    if status == 401:
        print("[-] Token expired")
        return
    print(f"[+] Status: {json.dumps(resp, ensure_ascii=False)}")


def do_tasks(cookie: str):
    """获取任务列表并完成可领取的任务"""
    print(f"[+] Fetching task list...")
    # 先获取任务分类
    url = API_HOST + "/v1/app/vip/taskClass/list"
    resp, status = make_request(url, {}, cookie)
    if status == 401:
        print("[-] Token expired")
        return
    print(f"[+] Task classes: {json.dumps(resp, ensure_ascii=False)[:400]}")
    
    # 从分类中提取 time 字段，获取具体任务详情
    data = resp.get("data", {})
    task_times = set()
    if isinstance(data, dict):
        for key in ["dailyTasks", "weeklyTasks", "growthTasks", "list"]:
            if key in data and isinstance(data[key], list):
                for item in data[key]:
                    if "time" in item:
                        task_times.add(str(item["time"]))
                    if "actionId" in item:
                        # 直接有 actionId 的可尝试完成
                        finish_task(cookie, item["actionId"], item.get("title", ""))
    
    # 对每个 time 获取详细任务
    for t in task_times:
        detail_url = API_HOST + f"/v1/app/vip/task/details/list/{t}"
        print(f"[+] Fetching tasks for time={t}...")
        detail_resp, d_status = make_request(detail_url, {}, cookie)
        if d_status == 401:
            print("[-] Token expired")
            return
        detail_data = detail_resp.get("data", {})
        if isinstance(detail_data, list):
            for task in detail_data:
                action_id = task.get("actionId")
                title = task.get("title", task.get("name", ""))
                status_val = task.get("status")
                # status: 1=未完成/需前置, 2=可领, 3=已领
                if action_id and status_val == 2:
                    finish_task(cookie, action_id, title)
        elif isinstance(detail_data, dict) and "list" in detail_data:
            for task in detail_data["list"]:
                action_id = task.get("actionId")
                title = task.get("title", task.get("name", ""))
                status_val = task.get("status")
                if action_id and status_val == 2:
                    finish_task(cookie, action_id, title)


def finish_task(cookie: str, action_id: str, title: str = ""):
    """完成单个任务"""
    url = API_HOST + f"/v1/vip/task/finish/{action_id}"
    print(f"[+] Finishing task: {title} (actionId={action_id})")
    resp, status = make_request(url, {}, cookie)
    if status == 401:
        print("[-] Token expired")
        return False
    msg = resp.get("msg", "") or resp.get("message", "") or ""
    ret_code = resp.get("code", 0)
    print(f"  -> ret={ret_code}, msg={msg}")
    return ret_code == 0


def do_points(cookie: str):
    """查询积分余额"""
    url = API_HOST + "/v1/vip/account/get"
    print(f"[+] Querying points...")
    resp, status = make_request(url, {}, cookie)
    if status == 401:
        print("[-] Token expired")
        return
    print(f"[+] Points: {json.dumps(resp, ensure_ascii=False)}")


def main():
    parser = argparse.ArgumentParser(description="Mengshi daily check-in + task")
    parser.add_argument("mode", choices=["auto", "signin", "status", "tasks", "points"], default="auto", nargs="?")
    args = parser.parse_args()

    cookie = load_cookie_from_env()
    if not cookie:
        print("[-] Missing cookie: set MENGSHI_COOKIE env or write mengshi_config.json {\"cookie\":\"...\"}")
        print("[*] Use env:MENGSHI_COOKIE='your-cookie-string'")
        print("[!] No account loaded. Script completed (no false failure).")
        return 0

    if args.mode in ("auto", "signin"):
        print("[1] Sign in")
        do_signin(cookie)
    
    if args.mode in ("auto", "tasks"):
        print("\n[2] Complete tasks")
        do_tasks(cookie)
    
    if args.mode in ("auto", "status"):
        print("\n[3] Query status")
        do_status(cookie)
    
    if args.mode in ("auto", "points"):
        print("\n[4] Query points")
        do_points(cookie)
    
    return 0


if __name__ == "__main__":
    exit(main())
