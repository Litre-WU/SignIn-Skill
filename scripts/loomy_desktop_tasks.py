#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
loomy_desktop_tasks.py — Loomy 桌面端新手任务自动完成
=========================================================
★桌面端与 web 端(loomy_points.py)是不同账号体系：
  - web 端:  loomy.xunfei.cn + cookie loomy_web_session（讯飞统一登录）
  - 桌面端:  Electron 客户端，登录态存于
      C:\\Users\\Public\\Loomy\\<sha256(用户名)前12位>\\userData\\auth-session.json
    {session(32位), userid, phone, updatedAt}
    API 鉴权 = HTTP 头  token: <session>（无 cookie）

接口(逆向自 app.asar electron/onboarding-service.js，backend='real'，v2 契约):
  GET  {BASE}/api/v1/onboarding/tasks           → {code,desc,trace_id,data:{tasks,total}}
  POST {BASE}/api/v1/onboarding/tasks/complete  body {"key":"<taskkey>"}
        → data {alreadyCompleted, balance}
  业务码: 000000 成功 / 100001 未知key或需选团队 / 100002 登录失效 / 100003 团队上下文异常

新手任务注册表（与客户端内置 TASK_POINTS 等价，全做满共 10000 积分）:
  first_message    500   发送第一条消息
  pick_skill      1000   选择一个技能
  generate_ppt    1500   生成第一份 PPT
  set_schedule    1000   设置定时任务
  install_skill   1500   技能广场安装技能
  configure_remote 1000  配置远程控制
  create_soul     1500   创建第一个搭子
  share_soul      2000   分享搭子给朋友

说明: 服务端以 complete 接口入账为准（幂等，重复标记 alreadyCompleted=true 不重复加分）。
      积分到账以 balance 字段回显为准。

用法:
  python loomy_desktop_tasks.py status          # 查任务完成状态与余额
  python loomy_desktop_tasks.py run             # 逐个补齐未完成的新手任务
  python loomy_desktop_tasks.py run <key>       # 只补指定 key
  python loomy_desktop_tasks.py probe           # 只做连通/鉴权自检（GET tasks）

100002 = 桌面端 session 已被服务端吊销/过期 → 需在 Loomy 桌面端重新登录一次，
脚本会自动重读 auth-session.json（桌面端登录后该文件会被重写）。
"""
import getpass
import hashlib
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "loomy_desktop_config.json")

TASKS = {
    "first_message": 500,
    "pick_skill": 1000,
    "generate_ppt": 1500,
    "set_schedule": 1000,
    "install_skill": 1500,
    "configure_remote": 1000,
    "create_soul": 1500,
    "share_soul": 2000,
}
TOTAL = sum(TASKS.values())

# ★生产 host 来自 app.asar resources/.env.prod 的 VITE_LOOMY_POINTS_BASE_URL
# （客户端 resolveConfig 优先级: env > 本地 points-config.json store > DEFAULT_BASE_URL，
#  所以本地 points-config.json 里残留的 ossptest 测试地址不能用于鉴权——token 是生产签发的）
DEFAULT_BASE_URL = "https://loomyad.xunfei.cn"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------- 桌面端登录态发现 ----------

def desktop_userdata_dir():
    """C:\\Users\\Public\\Loomy\\<sha256(username)[:12]>\\userData，与客户端 config-path.js 同构"""
    user = getpass.getuser()
    h = hashlib.sha256(user.encode("utf-8")).hexdigest()[:12]
    p = os.path.join("C:", os.sep, "Users", "Public", "Loomy", h, "userData")
    return p if os.path.isdir(p) else None


def load_desktop_session():
    """优先读桌面端 auth-session.json；可用配置文件覆盖（手工指定）。"""
    ud = desktop_userdata_dir()
    if ud:
        try:
            with open(os.path.join(ud, "auth-session.json"), "r", encoding="utf-8") as f:
                d = json.load(f)
            sess = str(d.get("session") or "").strip()
            if sess:
                # ★不要读桌面端 points-config.json 的 baseUrl —— 本安装包残留测试环境地址
                #   ossptest（token 在生产签发，打到测试 host 必回 100002）。
                #   生产 host 由 .env.prod 硬编码 = DEFAULT_BASE_URL。
                base_url = os.environ.get("LOOMY_DESKTOP_BASE_URL", "").strip() or DEFAULT_BASE_URL
                updated = d.get("updatedAt") or 0
                ts = datetime.fromtimestamp(updated / 1000).strftime("%Y-%m-%d %H:%M:%S") if updated else "?"
                return sess, str(d.get("userid") or ""), base_url, f"auth-session.json({ts})"
        except Exception:
            pass
    # 回退：手工配置
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            c = json.load(f)
        sess = str(c.get("session") or "").strip()
        if sess:
            return sess, str(c.get("userid") or ""), str(c.get("base_url") or DEFAULT_BASE_URL), "loomy_desktop_config.json"
    except Exception:
        pass
    return None, None, None, None


def save_manual_cfg(session, userid="", base_url=""):
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "session": session,
            "userid": userid,
            "base_url": base_url or DEFAULT_BASE_URL,
            "cfg_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }, f, ensure_ascii=False, indent=2)


# ---------- HTTP ----------

def request(base_url, path, token, method="GET", body=None):
    headers = {"token": token, "accept": "*/*"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30, context=CTX) as resp:
            text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"网络错误: {e}"
    try:
        j = json.loads(text)
    except Exception:
        return None, f"非 JSON 响应: {text[:120]}"
    code = str(j.get("code") or "")
    if code and code != "000000":
        return None, f"code={code} {j.get('desc') or ''}"
    return j.get("data"), None


# ---------- 命令 ----------

def do_status(token, userid, base_url, src):
    data, err = request(base_url, "/api/v1/onboarding/tasks", token)
    if err:
        hint = "【桌面端登录失效】请在 Loomy 桌面端重新登录（验证码/密码/微信扫码），登录后本脚本自动生效" if "100002" in err else err
        print(f"[状态] 获取失败: {hint}")
        return 1
    tasks = data.get("tasks") or {}
    earned = sum(p for k, p in TASKS.items() if tasks.get(k) is True)
    total = data.get("total") or TOTAL
    print(f"[身份] userid={userid} session={len(token)}位 来源={src}")
    print(f"[进度] 已得 {earned}/{total} 积分")
    for k, p in TASKS.items():
        mark = "✓" if tasks.get(k) is True else "·"
        print(f"  [{mark}] {k:<16} {p:>5} 分")
    if "raw_tasks" not in data:
        extra = {k: v for k, v in tasks.items() if k not in TASKS and v is True}
        if extra:
            print(f"  [i] 服务端另有已完成 key(本脚本注册表外): {list(extra.keys())}")
    return 0


def do_run(token, userid, base_url, src, only_key=None):
    if only_key and only_key not in TASKS:
        print(f"[x] 未知 key: {only_key}（可选: {', '.join(TASKS)}）")
        return 2
    data, err = request(base_url, "/api/v1/onboarding/tasks", token)
    if err:
        if "100002" in err:
            print("[失败] 桌面端登录态已失效 → 请在 Loomy 桌面端重新登录一次，然后重跑本脚本")
        else:
            print(f"[失败] 获取任务状态: {err}")
        return 1
    tasks = data.get("tasks") or {}
    pending = [k for k in TASKS if tasks.get(k) is not True]
    if only_key:
        pending = [only_key] if tasks.get(only_key) is not True else []
    if not pending:
        print(f"[ok] 全部新手任务已完成，无需补做（earned={sum(TASKS[k] for k in TASKS if tasks.get(k) is True)}）")
        return 0
    print(f"[i] 待完成 {len(pending)} 项: {', '.join(pending)}")
    ok = skip = fail = 0
    for k in pending:
        rdata, rerr = request(base_url, "/api/v1/onboarding/tasks/complete", token,
                              method="POST", body={"key": k})
        if rerr:
            if "100002" in rerr:
                print(f"  [x] {k}: 登录失效，中断（请在桌面端重新登录）")
                return 1
            print(f"  [x] {k}: {rerr}")
            fail += 1
            continue
        if rdata.get("alreadyCompleted"):
            print(f"  [-] {k}: 服务端视为已完成（幂等） balance={rdata.get('balance')}")
            skip += 1
        else:
            print(f"  [+] {k}: 完成 +{TASKS[k]} 分  balance={rdata.get('balance')}")
            ok += 1
    print(f"[汇总] 新完成 {ok} / 幂等 {skip} / 失败 {fail}")
    return 0 if fail == 0 else 1


def do_probe(token, userid, base_url, src):
    print(f"[i] base_url={base_url} userid={userid} 来源={src}")
    data, err = request(base_url, "/api/v1/onboarding/tasks", token)
    if err:
        print(f"[probe] GET tasks -> {err}")
        return 1
    print(f"[probe] GET tasks -> OK, tasks={json.dumps(data.get('tasks'), ensure_ascii=False)} total={data.get('total')}")
    return 0


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "status"

    if cmd == "init":  # 手工兜底：init <session> [userid]
        if len(args) < 2:
            print('用法: python loomy_desktop_tasks.py init "<32位session>" [userid]')
            return 2
        save_manual_cfg(args[1].strip(), args[2] if len(args) > 2 else "")
        print("[ok] 已写入 loomy_desktop_config.json（桌面端正常登录时本文件会被 auth-session.json 自动覆盖优先级）")
        return 0

    token, userid, base_url, src = load_desktop_session()
    if not token:
        print("[失败] 未找到桌面端登录态：auth-session.json 不存在/为空。")
        print("       请先安装并登录 Loomy 桌面端；或手工: init \"<session>\" [userid]")
        return 1

    if cmd == "status":
        return do_status(token, userid, base_url, src)
    if cmd == "run":
        return do_run(token, userid, base_url, src, only_key=args[1] if len(args) > 1 else None)
    if cmd == "probe":
        return do_probe(token, userid, base_url, src)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
