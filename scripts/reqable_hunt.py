#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reqable_hunt.py — Reqable 抓包的自动化入口（配合 Qoder 的 reqable MCP）

定位：抓包本身只能由 MCP 做（Reqable 本地 9000/9016 只有 `Hello Reqable!`，
没有公开的 REST 路由可让 Python 直接读记录）。本脚本负责 MCP 之外的两端——
**前置体检/配置** 与 **把抓到的记录变成可用凭证**，中间那一步由 agent 调 MCP 完成。

三个命令：
  python reqable_hunt.py doctor                 体检：Reqable 在跑吗 / 系统代理 / 根证书 / 下一步
  python reqable_hunt.py doctor --launch        没在跑就拉起 Reqable（幂等）
  python reqable_hunt.py restore-proxy          撤掉系统代理（关掉 Reqable 后必做，见文末风险）
  python reqable_hunt.py scan [平台id]          打印注册表：每个平台抓哪个接口、提哪个字段、落到哪条命令
  python reqable_hunt.py harvest --file rec.json [--apply]
                                                吃 capture_live_get_by_id 返回的记录 JSON（单个对象或数组），
                                                自动识别平台→抽凭证→（--apply 才）写回 config 并验证

★为什么要它：旧流程要用户「抓 1 条请求 → 复制整行 cookie 粘给我」。现在只要用户在
小程序/浏览器里做一次动作，agent 用 MCP 过滤取记录、本脚本落地，用户不用碰任何文本。

★安全：全程掩码打印；--apply 前自动备份 config；抓包记录含 cookie/token，别把 rec.json
放进会被发布出去的目录。
"""
import argparse
import datetime
import glob
import json
import os
import shutil
import subprocess
import socket
import sys
import winreg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
PORTS = (9000, 9016)
EXE_GLOBS = [
    r"C:\Program Files\Reqable\Reqable.exe",
    r"C:\Program Files (x86)\Reqable\Reqable.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Reqable\Reqable.exe"),
]


# ─────────────────────────────────── 小工具 ───────────────────────────────────
def mask(v, keep=6):
    """凭证只打头尾，避免整串进日志/对话。"""
    if not isinstance(v, str) or not v:
        return "-"
    if len(v) <= keep * 2:
        return v[0:2] + "…"
    return "%s…%s(len%d)" % (v[:keep], v[-4:], len(v))


def hdr(rec, name):
    """从记录里按名取请求/响应头（大小写不敏感）。"""
    for h in ((rec.get("request") or {}).get("headers") or []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def hdr_joined(rec, name, sep="; "):
    """取**所有**同名请求头并用 sep 拼接（Chromium/ Electron 会把 cookie 拆成多条头）。"""
    vals = [h.get("value", "") for h in ((rec.get("request") or {}).get("headers") or [])
            if h.get("name", "").lower() == name.lower() and h.get("value")]
    return sep.join(vals)


def jwt_field(token, dotted):
    """从 JWT 载荷里取点分字段（如 'data.id'）。解析失败返回空串。
    TRAE 的 Cloud-IDE-JWT 载荷形如 {"data":{"id":"<uid>","source":"refresh_token",...}}。"""
    import base64 as _b64
    parts = token.split(".")
    if len(parts) != 3:
        return ""
    try:
        pad = "=" * (-len(parts[1]) % 4)
        payload = json.loads(_b64.urlsafe_b64decode(parts[1] + pad).decode("utf-8", "replace"))
    except Exception:
        return ""
    cur = payload
    for key in dotted.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return ""
        cur = cur[key]
    return cur if isinstance(cur, str) else ""


def resp_json(rec):
    b = ((rec.get("response") or {}).get("body") or {})
    txt = b.get("text") if isinstance(b, dict) else None
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def req_json(rec):
    b = ((rec.get("request") or {}).get("body") or {})
    txt = b.get("text") if isinstance(b, dict) else None
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def port_open(port, timeout=1.2):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        pass
    # ★沙箱回退：bash 沙箱的网络层会挡 localhost 直连（http_proxy 环境变量在场时，
    # 连 socket 也可能被拦），此时转 PowerShell Test-NetConnection 探测——PowerShell
    # 工具不在同一层沙箱里，能代表本机真实状态。agent 跑 doctor 必走这条。
    if os.name == "nt" and (os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")):
        try:
            ps = ("$t=Test-NetConnection -ComputerName 127.0.0.1 -Port %d -InformationLevel Quiet "
                  "-WarningAction SilentlyContinue; if ($t) {'OPEN'} else {'CLOSED'}" % port)
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=15)
            return "OPEN" in (out.stdout or "")
        except Exception:
            return False
    return False


def proxy_state():
    """读 IE/Edge/WinINET 那一套系统代理注册表（Chromium 也认它）。"""
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
    except OSError:
        return None, None, None
    out = []
    for name in ("ProxyEnable", "ProxyServer", "ProxyOverride"):
        try:
            out.append(winreg.QueryValueEx(k, name)[0])
        except OSError:
            out.append(None)
    winreg.CloseKey(k)
    return tuple(out)


def set_proxy_enable(enable):
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                       r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                       0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1 if enable else 0)
    winreg.CloseKey(k)
    # 通知 shell 刷新，否则部分进程还用旧值
    ctypes_refresh()


def ctypes_refresh():
    try:
        import ctypes
        INTERNET_OPTION_SETTINGS_CHANGED, INTERNET_OPTION_REFRESH = 39, 37
        for opt in (INTERNET_OPTION_SETTINGS_CHANGED, INTERNET_OPTION_REFRESH):
            ctypes.windll.wininet.InternetSetOptionW(0, opt, 0, 0)
    except Exception:
        pass


def ca_installed():
    """Reqable 的根证书要进「受信任的根证书颁发机构」，否则小程序/浏览器的 HTTPS 全是解密失败。

    注意 `certutil -store Root <名字>` **不做子串匹配**（找不到时回 0x80090011），
    所以只能全量导出再搜；证书名形如
    `CN=Reqable CA (Oct 7, 2026, DB6AD3B6), O=Reqable, LLC`，"Reqable" 是 ASCII，
    即便 GBK 输出解码失败也能命中。返回 (是否装在, 装在哪, 检测到的其它 MITM CA)。"""
    found_in, others = [], []
    for label, store in (("计算机 Root", "Root"), ("当前用户 Root", "-user Root")):
        try:
            p = subprocess.run("certutil -store %s" % store, shell=True,
                               capture_output=True, timeout=60)
            txt = ""
            for enc in ("gbk", "utf-8"):
                try:
                    txt = p.stdout.decode(enc, "replace")
                    break
                except Exception:
                    continue
            if "Reqable" in txt:
                found_in.append(label)
            for alt in ("mitmproxy", "Charles", "Fiddler", "HttpToolkit", "Proxifier"):
                if ("CN=%s" % alt) in txt or ("O=%s" % alt) in txt:
                    others.append("%s@%s" % (alt, label))
        except Exception:
            pass
    return bool(found_in), found_in, others


def find_exe():
    for g in EXE_GLOBS:
        hits = glob.glob(g)
        if hits:
            return hits[0]
    return None


# ─────────────────────────────────── 注册表 ───────────────────────────────────
# 每条：id / 平台 / 用户要做的动作 / MCP 过滤参数 / 记录识别 / 提取 / 落地命令
REGISTRY = [
    {
        "id": "csair", "name": "南方航空",
        "action": "打开 PC 微信「中国南方航空」小程序首页（会自动 wx.login 换 sessionId）",
        "filter": {"type": "keyword", "pattern": "mini/api/login/login", "regex": False},
        "match": lambda rec: "/mini/api/login/login" in ((rec.get("request") or {}).get("path") or ""),
        "extract": lambda rec: {"login_json": json.dumps(resp_json(rec), ensure_ascii=False)},
        "land": lambda f: [PY, os.path.join(HERE, "csair_signin.py"), "refresh", f["login_json"]],
        "verify": lambda rec: bool((resp_json(rec) or {}).get("sessionId")),
        "note": "sessionId 只能由小程序内 wx.login 换取，无服务端刷新接口；抓到后 refresh 一次即恢复全链路",
    },
    {
        "id": "modelscope", "name": "魔搭 ModelScope",
        "action": "浏览器打开 https://www.modelscope.cn 并保持已登录（刷新一次页面即可）",
        "filter": {"type": "host", "hosts": ["www.modelscope.cn"]},
        "match": lambda rec: "modelscope.cn" in (rec.get("url") or ""),
        "extract": lambda rec: {"cookie": hdr(rec, "cookie")},
        "land": lambda f: [PY, os.path.join(HERE, "ms_magicube.py"), "init", f["cookie"]],
        "verify": lambda rec: "m_session_id" in hdr(rec, "cookie"),
        "note": "m_session_id 会被服务端重建/异地登录踢；cookie_sync 一般够用，它失败时才走这条",
    },
    {
        "id": "libao", "name": "利宝保险",
        "action": "小程序里进任意页面（authorization 头会自动带上）",
        "filter": {"type": "host", "hosts": ["cs.libao.cn"]},
        "match": lambda rec: "cs.libao.cn" in (rec.get("url") or ""),
        "extract": lambda rec: {"auth": hdr(rec, "authorization")},
        "land": lambda f: [PY, os.path.join(HERE, "libao_integral.py"), "init", f["auth"]],
        "verify": lambda rec: bool(hdr(rec, "authorization")),
        "note": "★只能证明登录态是否有效；「领取异常 请联系客服」是服务端风控，抓到也一样领不到",
    },
    {
        "id": "gr", "name": "GR 小程序（丰田 GAZOO Racing）",
        "action": "★在小程序里【手动分享一次文章】——这是判定「接口改版 vs 账号限流」的唯一对照样本",
        "filter": {"type": "keyword", "pattern": "shareArticle", "regex": False},
        "match": lambda rec: "toyotagazooracing" in (rec.get("url") or ""),
        # user/acquisition 的 body 里有 openId+token；oauth2 响应里有 refresh_token
        "extract": lambda rec: {
            "openid": (req_json(rec) or {}).get("openId", ""),
            "token": (req_json(rec) or {}).get("token", ""),
        },
        "land": lambda f: [PY, os.path.join(HERE, "gr_signin.py"), "init",
                           "--token", f["token"], "--openid", f["openid"]],
        "verify": lambda rec: bool((req_json(rec) or {}).get("openId")),
        "note": "分享真实入账判据是响应 data.id 非空；status:1+data.id:null 在配额耗尽时属正常，"
                "余量>0 却 id:null 才要对比人工抓包（见 SKILL.md「GR 分享 diff」）",
    },
    {
        "id": "huawei", "name": "华为码道 CodeArts Doer",
        "action": "优先【打开 CodeArts Agent 桌面端并登录一次】（会自动续 IAM 临时 AK/SK，免抓包）",
        "filter": {"type": "keyword", "pattern": "PromptCenterService", "regex": False},
        "match": lambda rec: "devcloud" in (rec.get("url") or ""),
        "extract": lambda rec: {"cookie": hdr(rec, "cookie")},
        "land": lambda f: [PY, os.path.join(HERE, "hw_codearts.py"), "init", f["cookie"]],
        "verify": lambda rec: "devclouddevuibjtcftk" in hdr(rec, "cookie"),
        "note": "回退链路才需要 cookie 抓包；devcloud 鉴权键是会话级 cookie 不落盘，必须开抓包/CDP 才取到",
    },
    {
        "id": "trae", "name": "TRAE（字节跳动）",
        "action": "打开 TRAE 桌面端并登录，进任意会发请求的页面（如签到/积分页）",
        "filter": {"type": "host", "hosts": ["api.trae.cn"]},
        "match": lambda rec: "api.trae.cn" in (rec.get("url") or ""),
        # Authorization = Cloud-IDE-JWT <JWT>（★非 Bearer）；uid 优先从 JWT 载荷
        # data.id 解（实测签到/API 请求根本不带 x-uid 头），x-uid 仅作兜底
        "extract": lambda rec: {
            "token": hdr(rec, "authorization").replace("Cloud-IDE-JWT ", "").strip(),
            "uid": jwt_field(hdr(rec, "authorization"), "data.id") or hdr(rec, "x-uid"),
        },
        "land": lambda f: [PY, os.path.join(HERE, "trae_credits.py"), "init",
                           "--token", f["token"], "--uid", f["uid"]],
        "verify": lambda rec: "Cloud-IDE-JWT" in hdr(rec, "authorization"),
        "note": "token 是 JWT（source=refresh_token，实测约 14 天有效），过期后重新抓；"
                "uid 从 JWT 载荷 data.id 解（设备身份派生必需）；抓到同域静态资源请求会缺字段，换一条 API 请求",
    },
    {
        "id": "lobsterai", "name": "LobsterAI（有道）",
        "action": "★浏览器打开并登录 https://lobsterai.youdao.com/portal ，刷新一下页面即可"
                  "（Web 门户 cookie 认证全链路可用；桌面客户端默认 direct mode 抓不到）",
        "filter": {"type": "host", "hosts": ["lobsterai-server.youdao.com"]},
        "match": lambda rec: "lobsterai-server.youdao.com" in (rec.get("url") or ""),
        # ★Web 门户模式：cookie 在记录里是**多条**同名头，必须全取拼接
        "extract": lambda rec: {"cookie": hdr_joined(rec, "cookie")},
        "land": lambda f: [PY, os.path.join(HERE, "lobsterai_credits.py"), "init",
                           "--cookie", f["cookie"]],
        "verify": lambda rec: "lobsterai_web_session" in hdr_joined(rec, "cookie"),
        "note": "关键 cookie: lobsterai_web_session + NTES_YD_SESS + DICT_SESS + P_INFO（有道账号体系）；"
                "Thorium 保持登录即可，可随时重新提取；桌面端 Bearer 模式见脚本文件头",
    },
    {
        "id": "minimax", "name": "MiniMax Code",
        "action": "打开 MiniMax Code 桌面端并登录，进签到/积分页（或任意会发请求的页面）",
        "filter": {"type": "host", "hosts": ["agent.minimax.cn"]},
        "match": lambda rec: "agent.minimax.cn" in (rec.get("url") or ""),
        "extract": lambda rec: {"token": hdr(rec, "authorization").replace("Bearer ", "").strip()},
        "land": lambda f: [PY, os.path.join(HERE, "minimax_credits.py"), "init", "--token", f["token"]],
        "verify": lambda rec: bool(hdr(rec, "authorization")),
        "note": "token 实测前缀 mmoat_（60 字符非 JWT）；timezone_id 脚本默认 Asia/Shanghai，不用抓",
    },
]


def find_target(rec):
    for t in REGISTRY:
        try:
            if t["match"](rec):
                return t
        except Exception:
            continue
    return None


# ─────────────────────────────────── doctor ───────────────────────────────────
def cmd_doctor(args):
    print("=" * 64)
    print("Reqable 抓包前置体检  %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 64)

    running = port_open(PORTS[0])
    exe = find_exe()
    print("[进程] 9000 %s · 9016 %s%s" % (
        "可达(Reqable 在跑)" if running else "不可达(未运行)",
        "可达" if port_open(PORTS[1]) else "不可达",
        "" if exe else "  ·  没找到 Reqable.exe，请手动启动或用 --launch 搜索"))
    if not running and exe:
        if args.launch:
            # ★注意：agent 工具链会回收每次调用的子进程树，GUI 程序（Reqable）活不过
            # 一个工具调用——所以脚本只能「试着拉」，拉完端口不开属预期。
            # 正解：让用户在交互会话里手动双击打开 Reqable（图标/开始菜单），
            # 那种进程归用户会话所有，不会被回收。
            try:
                subprocess.Popen([exe], cwd=os.path.dirname(exe))
            except Exception:
                pass
            for _ in range(8):
                if port_open(PORTS[0], 2.0):
                    running = True
                    break
                import time as _t; _t.sleep(2.5)
            print("[拉起] %s → %s" % (exe, "已就绪" if running else "仍不可达"))
            if not running:
                print("       ⚠ agent 拉起的 GUI 进程会被工具链回收（活不过一次调用）。")
                print("       → 请你在桌面上【手动双击打开 Reqable】，然后再跑一次 doctor 验证。")
        else:
            print("[建议] 手动打开 Reqable（或在桌双击图标）；开机自启用户可省这步")

    enable, server, override = proxy_state()
    print("[系统代理] ProxyEnable=%s ProxyServer=%s Override=%s" % (
        enable, server or "-", (str(override)[:40] + "…") if override else "-"))
    if running and not enable:
        print("  ↑ Reqable 在跑但代理没开 → 抓不到流量：让 agent 调 `proxy_set{overrideSystem:true}`")
    if (not running) and enable and server and "9000" in str(server):
        print("  ⚠ 危险：代理指向 9000 但 Reqable 没在跑 → 本机所有走系统代理的 HTTPS 都会失败"
              "（签到脚本会成片假失效）。立刻 `reqable_hunt.py restore-proxy` 或重开 Reqable")

    has_ca, where, others = ca_installed()
    if has_ca:
        print("[根证书] 已安装：%s%s" % (" + ".join(where),
              "  ·  另有其它 MITM 证书(%s)，若某 App 解不出来优先怀疑它们抢占" % ", ".join(others) if others else ""))
    else:
        print("[根证书] 未检测到 → HTTPS 内容解不出来。在 Reqable 里 设置→证书→安装根证书"
              "（装到「本地计算机」的受信任根，只装当前用户的话 PC 微信小程序不一定认）")
        if others:
            print("           本机已有其它 MITM CA：%s —— 先卸载再装 Reqable，避免两套根互踩" % ", ".join(others))

    print("\n[MCP 侧] Python 读不到抓包记录（9000 只有 `Hello Reqable!`，无公开 REST 路由），")
    print("         所以抓包这步必须让 agent 走 reqable MCP：")
    print("           1) capture_live_set_enabled{enabled:true}    开抓")
    print("           2) 你在小程序/浏览器里做一次动作（见 scan 的动作列）")
    print("           3) capture_live_filter{filters:[…]}          按注册表里的 pattern 过滤")
    print("           4) capture_live_get_by_id{id:N}              取整条记录 → 存 rec.json")
    print("           5) python reqable_hunt.py harvest --file rec.json --apply")
    return 0


def cmd_restore_proxy(args):
    enable, server, _ = proxy_state()
    print("当前 ProxyEnable=%s ProxyServer=%s" % (enable, server or "-"))
    set_proxy_enable(False)
    e2, s2, _ = proxy_state()
    print("已撤除系统代理 → ProxyEnable=%s（Reqable 可以继续开着，只是不再接管流量）" % e2)
    print("提醒：下次要抓包时重新 `proxy_set{overrideSystem:true}` 或 `doctor --launch`")
    return 0


# ─────────────────────────────────── scan ────────────────────────────────────
def cmd_scan(args):
    want = args.target
    rows = [t for t in REGISTRY if not want or t["id"] == want or t["name"] == want]
    if not rows:
        print("未知目标。可选 id：%s" % " / ".join(t["id"] for t in REGISTRY))
        return 2
    for t in rows:
        print("─" * 62)
        print("%-10s %s" % (t["id"], t["name"]))
        print("  你要做的  : %s" % t["action"])
        print("  MCP 过滤  : capture_live_filter{filters:[%s]}" % json.dumps(t["filter"], ensure_ascii=False))
        print("  落地命令  : harvest --file rec.json --apply")
        print("  备注      : %s" % t["note"])
    print("─" * 62)
    return 0


# ─────────────────────────────────── harvest ─────────────────────────────────
def cmd_harvest(args):
    raw = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception as e:
        print("[x] rec 不是合法 JSON：%s" % str(e)[:80])
        return 2
    recs = data if isinstance(data, list) else [data]
    print("[输入] %d 条记录" % len(recs))

    plans = {}
    for rec in recs:
        t = find_target(rec)
        if not t:
            print("  跳过（注册表里没有匹配项）: %s" % (rec.get("url") or "?")[:90])
            continue
        if not t["verify"](rec):
            print("  %s：记录形态不对（可能抓到了同域的其它请求），继续找下一条" % t["id"])
            continue
        fields = {k: v for k, v in t["extract"](rec).items() if v}
        cur = plans.setdefault(t["id"], {"t": t, "fields": {}, "cmds": []})
        for k, v in fields.items():
            cur["fields"].setdefault(k, v)
    if not plans:
        print("[x] 没提取到任何凭证。先确认：抓包时确实做过那个动作、且 capture 是开启状态（`scan` 看动作列）")
        return 3

    for pid, plan in plans.items():
        t, f = plan["t"], plan["fields"]
        print("─" * 62)
        print("[%s] %s" % (pid, t["name"]))
        print("   提取: %s" % ", ".join("%s=%s" % (k, mask(v)) for k, v in f.items()))
        missing = []
        if pid == "gr":
            missing = [k for k in ("openid", "token") if not f.get(k)]
        elif pid == "trae":
            missing = [k for k in ("token", "uid") if not f.get(k)]
        if missing:
            print("   [!] 字段不全（缺 %s）→ 多半只抓到了其中一条请求，把同会话的 API 请求记录一起放进来" % ",".join(missing))
            continue
        cmd = t["land"](f)
        plan["cmds"].append(cmd)
        if not args.apply:
            print("   将执行: %s   （加 --apply 才真写 config）" % " ".join(x if len(x) < 46 else x[:44] + "…" for x in cmd[1:]))
            continue
        for c in plan["cmds"]:
            cfgs = [os.path.join(HERE, n) for n in
                    ({"csair": "csair_config.json", "modelscope": "ms_config.json", "libao": "libao_config.json",
                      "gr": "gr_config.json", "huawei": "hw_codearts_config.json",
                      "trae": "trae_config.json", "lobsterai": "lobsterai_config.json",
                      "minimax": "minimax_config.json"}.get(pid, "") or "",) if n]
            for cf in cfgs:
                if os.path.exists(cf):
                    bak = cf + ".bak-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                    shutil.copyfile(cf, bak)
                    print("   备份 %s" % os.path.basename(bak))
            p = subprocess.run(c, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=180,
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            tail = (p.stdout or "").strip().splitlines()[-4:]
            print("   rc=%d" % p.returncode)
            for l in tail:
                print("     | %s" % l[:120])
    if not args.apply:
        print("\n（演练模式：没有写任何 config。确认无误后加 --apply）")
    return 0


def main():
    p = argparse.ArgumentParser(description="Reqable 抓包自动化入口（体检 / 注册表 / 记录→凭证）")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="体检 Reqable/代理/证书 并给出下一步")
    d.add_argument("--launch", action="store_true", help="没在跑就拉起 Reqable")
    d.set_defaults(func=cmd_doctor)
    r = sub.add_parser("restore-proxy", help="撤掉系统代理（关 Reqable 后必做）")
    r.set_defaults(func=cmd_restore_proxy)
    s = sub.add_parser("scan", help="打印抓包注册表")
    s.add_argument("target", nargs="?", default="", help="平台 id，留空=全部")
    s.set_defaults(func=cmd_scan)
    h = sub.add_parser("harvest", help="吃 capture 记录 JSON，自动识别平台并落地凭证")
    h.add_argument("--file", default="", help="记录 JSON（capture_live_get_by_id 原文，对象或数组）；不给则读 stdin")
    h.add_argument("--apply", action="store_true", help="真写回 config（默认只演练，且写前自动备份）")
    h.set_defaults(func=cmd_harvest)
    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
