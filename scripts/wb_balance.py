#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy 账户积分余额（客户端用量页同一个数）只读查询。

★为什么不是 wb_score.py 里那个 2300：
  /v2/billing/meter/checkin-activity-status 的 `total_credits` 只是「Buddy加油站 本期活动
  累计签到积分」，恒等于 连签天数 × daily_credit；客户端用量页/钱包读的是另一个接口。

★真余额（2026-10-23 逆向自客户端 app.asar 明文 JS + 实测 200）：
  POST https://<domain>/billing/meter/get-user-resource-summary   ← 注意**不带 /v2**
  必需头：Authorization: Bearer <accessToken>、Content-Type、Accept、**X-Device-Token**
  缺 X-Device-Token → HTTP 403 `code=10085 请求不合法`（网关放行、业务侧拒），换 UA/加
  Origin/Referer/X-User-Id/X-Domain/X-Request-ID 都无效；`/v2/` 前缀一律 404 Route Not Found。
  X-Device-Token 出自腾讯 T-Sec TuringShield 桌面 SDK，客户端用 N-API 桥加载：
    %LOCALAPPDATA%/Programs/WorkBuddyAI/resources/app.asar.unpacked/native/turing-sdk
    configure(channelId, productName, productVersion, keychainStorageEnabled) → fetchDeviceToken()
  channelId / productName 从同目录 cli/product.json 的 config.turingSdk 读（本机实测 109144）。
  本脚本不复制任何加密逻辑：起 node 调客户端自带的 .node（见 wb_turing_token.js），只拿令牌。

只读、幂等，可每天跑。绝不打印 Bearer / 设备令牌本体（只打长度）。
"""
import json
import os
import subprocess
import sys
# 仅是喂给 SDK 的元数据；实测版本串取错也能拿到有效令牌，不做硬校验。
FALLBACK_VERSION = os.environ.get("WB_TURING_VERSION", "5.9.0")
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOTS = [
    os.path.join(os.path.expanduser("~"), ".qoder-cn", "skills"),
    os.path.join(os.path.expanduser("~"), ".agents", "skills"),
    os.path.join(os.path.expanduser("~"), ".workbuddy", "skills"),
]


def _utf8_stream():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def find_buddy_station():
    """定位 totorosir-workbuddy-score 的 buddy_station.py（复用它的三通道取凭证逻辑）。"""
    for root in SKILL_ROOTS:
        p = os.path.join(root, "totorosir-workbuddy-score", "scripts", "buddy_station.py")
        if os.path.isfile(p):
            return p
    return None


def find_client_sdk():
    """返回 (addon_dir, channel_id, product_name)；客户端没装/没配 Turing 则 None。"""
    local = os.environ.get("LOCALAPPDATA") or ""
    bases = [os.path.join(local, "Programs", "WorkBuddyAI"),
             os.path.join(local, "Programs", "WorkBuddy"),
             r"C:\Program Files\WorkBuddyAI"]
    for base in bases:
        unpacked = os.path.join(base, "resources", "app.asar.unpacked")
        addon = os.path.join(unpacked, "native", "turing-sdk")
        if not os.path.isdir(os.path.join(addon, "build", "Release")):
            continue
        channel_id, product_name = None, "WorkBuddy"
        for probe in (os.path.join(unpacked, "cli", "product.json"),):
            try:
                cfg = json.load(open(probe, encoding="utf-8"))
                channel_id = (cfg.get("config") or {}).get("turingSdk", {}).get("channelId")
                product_name = cfg.get("productName") or product_name
            except Exception:
                pass
        if not channel_id:
            return addon, None, product_name
        return addon, channel_id, product_name
    return None, None, None


def query_balance(addon_dir, channel_id, product_name, domain, bearer, uid):
    """在同一个 node 进程里「取设备令牌 + 发请求」；跨进程复用令牌会被服务端拒（10085）。"""
    helper = os.path.join(HERE, "wb_balance_query.js")
    if not os.path.isfile(helper):
        return None, "缺少 wb_balance_query.js"
    payload = json.dumps({"addonDir": addon_dir.replace("\\", "/"), "channelId": channel_id,
                          "productName": product_name, "version": FALLBACK_VERSION,
                          "domain": domain, "bearer": bearer, "uid": uid})
    try:
        r = subprocess.run(["node", helper], input=payload, capture_output=True, timeout=90,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None, "本机没有 node（客户端原生桥需要 node 加载 .node）"
    except subprocess.TimeoutExpired:
        return None, "查询超时（90s）"
    try:
        out = json.loads((r.stdout or "").strip())
    except Exception:
        return None, "解析 node 输出失败 rc=%s %s" % (r.returncode, (r.stderr or "").strip()[:200])
    if out.get("error"):
        return None, "原生桥/请求异常：%s" % out["error"]
    return out, None


def read_uid_domain(auth_file):
    try:
        d = json.load(open(auth_file, encoding="utf-8"))
        return (d.get("account") or {}).get("uid") or "", (d.get("auth") or {}).get("domain") or "www.workbuddy.cn"
    except Exception:
        return "", "www.workbuddy.cn"


def money(v):
    try:
        return "%.2f" % float(v)
    except Exception:
        return str(v)


def report(data):
    groups = data.get("CreditGroups") or []
    bits = []
    for g in groups:
        remain = float(g.get("CycleRemainCapacity") or 0)
        total = float(g.get("CycleTotalCapacity") or 0)
        if remain or total:
            bits.append("%s 剩%s/%s(%s笔)" % (g.get("Name") or g.get("Kind"), money(remain),
                                          money(total), g.get("TotalCount")))
    print("[余额] 账户可用 %s credits · 套餐=%s · %s" % (
        money(data.get("TotalCredits")),
        data.get("SubscriptionPackageName") or "?",
        "付费用户" if data.get("IsPaidUser") else "非付费"))
    if bits:
        print("[分组] " + " | ".join(bits))
    for p in (data.get("Packages") or []):
        print("[池]   %s 剩 %s / 总 %s / 冻结 %s（%s 笔）" % (
            p.get("PackageCode"), money(p.get("CycleRemainCapacity")),
            money(p.get("CycleTotalCapacity")), money(p.get("CycleFrozenCapacity")),
            p.get("TotalCount")))


def main():
    _utf8_stream()
    bs_path = find_buddy_station()
    if not bs_path:
        print("[skip] 未找到 buddy_station.py（totorosir-workbuddy-score 未安装），余额查询跳过")
        return 0
    addon_dir, channel_id, product_name = find_client_sdk()
    if not addon_dir:
        print("[skip] 本机没装 WorkBuddy 桌面端（找不到 native/turing-sdk），余额查询跳过")
        return 0
    if not channel_id:
        print("[skip] product.json 未配置 config.turingSdk.channelId，该构建不启用设备令牌")
        return 0

    sys.path.insert(0, os.path.dirname(bs_path))
    try:
        import buddy_station as bs
    except Exception as exc:
        print("[失败] 导入 buddy_station 异常: %s" % exc)
        return 3
    try:
        # 固定走 local 通道：auto 会退化到 rt，真的消耗一次服务端 refresh 轮换。
        bearer, domain, _ = bs._resolve_auth("local")
    except Exception as exc:
        print("[失败] 取客户端登录态失败（%s）——【WorkBuddy登录失效】，解法是在客户端里重新登录" % exc)
        return 3
    auth_file = None
    try:
        auth_file = bs.find_login_state()
    except Exception:
        pass
    uid, _ = read_uid_domain(auth_file) if auth_file else ("", "www.workbuddy.cn")

    out, err = query_balance(addon_dir, channel_id, product_name, domain, bearer, uid)
    if err:
        print("[失败] %s" % err)
        return 3
    print("[鉴权] X-Device-Token 由客户端自带原生桥现取（channelId=%s · len=%s，同一进程取完即用）"
          % (channel_id, out.get("tokenLen")))
    body = out.get("body") or {}
    if out.get("http") != 200 or body.get("code") != 0:
        print("[失败] HTTP %s code=%s msg=%s" % (out.get("http"), body.get("code"), body.get("msg")))
        if body.get("code") == 10085:
            print("       → 10085=服务端没接受这支设备令牌；先确认客户端能正常打开用量页，别重试轰炸")
        print("       →【WorkBuddy余额失效】")
        return 3
    report(body.get("data") or {})
    return 0


if __name__ == "__main__":
    sys.exit(main())
