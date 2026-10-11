#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美团分销会场领券 · 纯接口版 (mt_union_coupon.py)
================================================
覆盖"美团分销中心/分销会场"（用户抓包 wxde8ac0a21135c07d 的 distributionVenue 链路）:

链路:
  1. POST media.meituan.com/fulishemini/couponActivity/listActivityCoupon/distributionVenue
     （mp 签名 gen_mtgsig 即可）→ 当日会场券列表 + recallToken
     ★ recallToken 含时间戳后缀、时效极短，每次必须现拉，不能复用存盘响应
  2. list 中 type==1 且 status==0 的券按 planCode 分组为 tabs（已领券 status=1 自动排除）
  3. POST .../grantActivityCoupon/distributionVenue?yodaReady=h5&csecplatform=4&csecversion=4.3.0
     ★ 必须用 H5 签名 h5_sign；mp 签名(csecplatform=3) 会被拒 code:30001 召回Token为空或已过期
     body 以福利社 grant 完整字段为底(build_grant_body) + 会场专属字段覆盖:
       activityName/activityCode/recallToken/appId=mtunion_h5/distributorChannel=3/osType/fp_platform=11
  4. 附带: 分销中心页内嵌的 gundam 跨券墙（generalcoupon/info→fetch）
     参数取自 mt_union_config.json（gdId/pageId/activityViewId/instanceId），复用 mt_gundam_coupon.wall_claim
     无配置时优雅跳过

登录态: 复用 mt_config.json 的 wm_logintoken（同账号 1005134378，分销接口认账号级 token）

用法:
  python mt_union_coupon.py          # 领券（幂等，按日记录）
  python mt_union_coupon.py probe    # 只拉列表打印可领券，不领取
  python mt_union_coupon.py status   # 查看历史记录
"""
import json
import os
import sys
import time
from collections import OrderedDict
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import mt_api_coupon as mt
import mt_gundam_coupon as G

CONFIG_PATH = mt.CONFIG_PATH                 # mt_config.json（设备字段 + wm_logintoken）
UNION_CONFIG_PATH = os.path.join(BASE, "mt_union_config.json")  # 分销小程序抓包字段（gdId/AV/instanceId）
STATE_PATH = os.path.join(BASE, "mt_union_state.json")
LOG_PATH = mt.LOG_PATH

URL_LIST = mt.HOST + "/fulishemini/couponActivity/listActivityCoupon/distributionVenue?" + mt.QS
URL_GRANT = (mt.HOST + "/fulishemini/couponActivity/grantActivityCoupon/distributionVenue"
             "?yodaReady=h5&csecplatform=4&csecversion=4.3.0")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg):
    mt.log("[union] " + msg)


def _to_int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- 列表
def venue_list(cfg):
    """拉分销会场券列表。返回 (ok, data, msg)"""
    body_obj = {
        "requestType": 0,
        "couponActivityScene": 1,
        "distributorChannel": 3,
        "wm_uuid": cfg.get("wm_uuid", ""),
        "mtFingerprint": "",
        "fp_platform": 11,
        "wm_appversion": "1.1.0",
        "city_id_level2": cfg.get("city_id_level2", "411600"),
        "wm_actual_latitude": _to_int(cfg.get("wm_actual_latitude"), 34060001),
        "wm_actual_longitude": _to_int(cfg.get("wm_actual_longitude"), 114394821),
        "appId": "mtunion_h5",
        "open_id": cfg.get("open_id", ""),
        "expoId": cfg.get("expoId", ""),
        "wm_dplatform": "windows",
        "container": "mt_applet",
    }
    body_json = json.dumps(body_obj, separators=(",", ":"), ensure_ascii=False)
    mtgsig, _ = mt.gen_mtgsig("POST", URL_LIST, body_json)
    c, t = mt.http_post_json(URL_LIST, body_json, mtgsig, cfg)
    if c != 200:
        return False, None, "HTTP %s: %s" % (c, t[:150])
    try:
        j = json.loads(t)
    except Exception:
        return False, None, "响应非 JSON: %s" % t[:150]
    if j.get("code") not in (0, 200, "0", "200"):
        return False, None, "code=%s %s" % (j.get("code"), j.get("msg", ""))
    return True, j.get("data") or {}, "ok"


def venue_tabs(data, exclude_rc=None):
    """type==1 且 status==0 的券按 planCode 分组 → tabs。
    exclude_rc: 本地已记录处理过的 rightCode（grant 返回 code:200 即视为服务端已处理，
    含互斥未发放），重跑时过滤掉，实现 rightCode 级幂等。
    返回 (tabs, 明细列表)。status==1=已领，其他状态也排除。"""
    exclude_rc = exclude_rc or set()
    tabs_map = OrderedDict()
    detail = []
    now = int(time.time() * 1000)
    for it in (data.get("list") or []):
        if not (isinstance(it, dict) and it.get("type") == 1):
            continue
        d = it.get("data") or {}
        rc = d.get("rightCode")
        if not rc:
            continue
        st = d.get("status")
        et = d.get("couponEndTime") or 0
        item = {
            "name": d.get("couponName", ""),
            "value": d.get("couponValue", 0),
            "planCode": d.get("planCode", ""),
            "rightCode": rc,
            "status": st,
            "limit": d.get("priceLimit", 0),
            "start": d.get("couponStartTime", 0),
            "end": et,
            "expired": bool(et and et < now),
            "skipped": rc in exclude_rc,
        }
        detail.append(item)
        if st == 0 and not item["expired"] and rc not in exclude_rc:
            tabs_map.setdefault(d.get("planCode", ""), []).append(rc)
    tabs = [{"planCode": pc, "rightCodes": rcs} for pc, rcs in tabs_map.items()]
    return tabs, detail


# ---------------------------------------------------------------- 领取
def venue_grant(cfg, data, tabs):
    """H5 签名调会场 grant。返回 (ok, msg, resp_json)"""
    conf = data.get("config") or {}
    # finger_applets: 先用沙箱打一次 probe 拿 dfpid
    _, dfpid = mt.gen_mtgsig("POST", mt.URL_GRANT, "probe=1")
    cfg["_finger_applets"] = dfpid
    full = mt.build_grant_body(cfg, data, tabs)
    # 会场专属字段覆盖
    full.update({
        "activityName": conf.get("activityName", ""),
        "activityCode": conf.get("activityCode", ""),
        "recallToken": data.get("recallToken", ""),
        "appId": "mtunion_h5",
        "distributorChannel": 3,
        "osType": "Windows",
        "fp_platform": 11,
    })
    body_json = json.dumps(full, ensure_ascii=False, separators=(",", ":"))
    mtgsig, _ = G.h5_sign("POST", URL_GRANT, body_json)
    c, t = mt.http_post_json(URL_GRANT, body_json, mtgsig, cfg)
    if c != 200:
        return False, "HTTP %s: %s" % (c, t[:150]), None
    try:
        j = json.loads(t)
    except Exception:
        return False, "响应非 JSON: %s" % t[:150], None
    code = j.get("code")
    if code in (0, 200, "0", "200"):
        return True, "成功", j
    return False, "code=%s %s" % (code, j.get("msg", "")), j


def count_granted(resp_j):
    """grant 响应里 data.tabs[].couponList[] 中带 couponViewId 的视为已发放入账"""
    got = []
    for tab in ((resp_j or {}).get("data") or {}).get("tabs") or []:
        for cp in (tab.get("couponList") or []):
            if isinstance(cp, dict) and cp.get("couponViewId"):
                got.append({"name": cp.get("couponName", ""), "value": cp.get("couponValue", 0)})
    return got


# ---------------------------------------------------------------- 分销中心 gundam 跨券墙
def union_wall_claim(cfg):
    """分销中心页内嵌的 gundam 跨券墙（用户第 2 个抓包: generalcoupon/info→fetch）。
    参数从 mt_union_config.json 取；无配置则跳过。返回 (ok, msg, 券明细)"""
    uc = mt.load_json(UNION_CONFIG_PATH, {}) or {}
    av = uc.get("activityViewId")
    inst = uc.get("instanceId")
    gd = uc.get("gdId")
    pg = uc.get("pageId")
    if not (av and inst and gd and pg):
        return None, "未配置 gdId/pageId/activityViewId/instanceId（跳过）", []
    wall_cfg = dict(cfg)
    wall_cfg["_gdId"] = int(gd)
    wall_cfg["_pageId"] = int(pg)
    # 登录态直接用 mt_config 的账号级 wm_logintoken（已验证 info 可用；
    # mt_union_config 里抓包的新 token 已失效）
    try:
        return G.wall_claim(wall_cfg, wall_cfg["wm_logintoken"], av, inst)
    except Exception as e:
        return False, "异常: %s" % e, []


# ---------------------------------------------------------------- 主流程
def run(probe_only=False):
    cfg = mt.load_json(CONFIG_PATH, {}) or {}
    ok, missing = mt.check_config(cfg)
    if not ok:
        print("[失败] mt_config.json 缺少字段: %s" % ", ".join(missing))
        return 1
    if not cfg.get("wm_logintoken"):
        print("[失败] 缺 wm_logintoken")
        return 1

    state = mt.load_json(STATE_PATH, {}) or {}
    today = datetime.now().strftime("%Y-%m-%d")
    stoday = state.setdefault(today, {"granted": [], "granted_rc": []})
    granted_rc = set(stoday.get("granted_rc") or [])

    print("=" * 62)
    print("美团分销会场领券 %s" % datetime.now().strftime("%F %T"))
    print("=" * 62)

    # 1) 拉列表
    print("[1/3] listActivityCoupon/distributionVenue ...")
    ok, data, msg = venue_list(cfg)
    if not ok:
        print("[中断] 列表拉取失败: %s" % msg)
        log("list fail: %s" % msg)
        return 2
    conf = data.get("config") or {}
    print("      会场: %s (activityCode=%s)" % (conf.get("activityName", "?"), conf.get("activityCode", "?")))
    mt.save_json(os.path.join(BASE, "mt_venue_resp.json"), {"code": 200, "data": data})

    tabs, detail = venue_tabs(data, granted_rc)
    n_claim = sum(len(t["rightCodes"]) for t in tabs)
    n_done = sum(1 for d in detail if d["status"] == 1)
    n_skip = sum(1 for d in detail if d.get("skipped"))
    n_exp = sum(1 for d in detail if d["expired"])
    print("      券总数 %d: 可领 %d（%d 组）/ 已领 %d / 本地幂等 %d / 已过期 %d"
          % (len(detail), n_claim, len(tabs), n_done, n_skip, n_exp))
    for d in detail:
        if d["status"] == 0 and not d["expired"] and not d.get("skipped"):
            print("        · %s ¥%s 满%s可用" % (d["name"], d["value"], d["limit"]))
    if probe_only:
        return 0

    if not tabs:
        print("[幂等] 会场券均已领取或已处理（本地记录 %d 个 rightCode）。" % len(granted_rc))
        stoday["venue"] = stoday.get("venue") or "idle"
        stoday["ts"] = datetime.now().strftime("%F %T")
        # 仍继续尝试跨券墙
    else:
        # 2) 领取（recallToken 过期则重拉列表重试一次）
        for attempt in (1, 2):
            print("[2/3] grantActivityCoupon/distributionVenue（H5 签名，第 %d 次）..." % attempt)
            ok, msg, j = venue_grant(cfg, data, tabs)
            mt.save_json(os.path.join(BASE, "mt_venue_grant_resp.json"),
                         {"http": 200, "body": json.dumps(j, ensure_ascii=False) if j else ""})
            if ok:
                got = count_granted(j)
                val = sum(g["value"] for g in got)
                # code:200 即视为本批 rightCode 全部已处理（含互斥未发放），记录幂等
                sent_rc = [rc for t in tabs for rc in t["rightCodes"]]
                granted_rc.update(sent_rc)
                stoday["granted_rc"] = sorted(granted_rc)
                stoday["granted"] = (stoday.get("granted") or []) + got
                stoday["venue"] = "ok"
                stoday["ts"] = datetime.now().strftime("%F %T")
                print("      ✅ 领取成功：响应内已发放 %d 张 ¥%s（本次处理 %d 个 rightCode）"
                      % (len(got), val, len(sent_rc)))
                for g in got:
                    print("        + %s ¥%s" % (g["name"], g["value"]))
                log("grant ok tabs=%d got=%d val=%s" % (len(tabs), len(got), val))
                break
            print("      ❌ %s" % msg)
            if "30001" in str(msg) or "召回" in str(msg):
                if attempt == 1:
                    print("      recallToken 过期，重拉列表...")
                    ok2, data, msg2 = venue_list(cfg)
                    if ok2:
                        tabs, _ = venue_tabs(data, granted_rc)
                        if not tabs:
                            print("      重拉后无可领券（幂等）")
                            stoday["venue"] = "ok"
                            stoday["ts"] = datetime.now().strftime("%F %T")
                            break
                        continue
                    print("      重拉失败: %s" % msg2)
            stoday["venue"] = "fail"
            stoday["msg"] = msg
            stoday["ts"] = datetime.now().strftime("%F %T")
            log("grant fail: %s" % msg)
            break

    # 3) 分销中心 gundam 跨券墙
    print("[3/3] 分销中心跨券墙（generalcoupon/info→fetch）...")
    try:
        wok, wmsg, wgot = union_wall_claim(cfg)
        if wok is None:
            print("      [跳过] %s" % wmsg)
        else:
            print("      %s %s" % ("✅" if wok else "❌", wmsg))
            stoday["wall"] = {"ok": wok, "msg": wmsg}
            log("wall ok=%s msg=%s" % (wok, wmsg))
    except Exception as e:
        print("      [异常] %s" % e)
        stoday["wall"] = {"ok": False, "msg": str(e)}

    mt.save_json(STATE_PATH, state)
    print("[完成] 明细见 %s" % STATE_PATH)
    return 0


def status():
    st = mt.load_json(STATE_PATH, {}) or {}
    if not st:
        print("暂无记录")
        return 0
    for k in sorted(st):
        v = st[k]
        if not isinstance(v, dict):
            continue
        print("%s  venue=%s  %s" % (k, v.get("venue", "?"), v.get("ts", "")))
        for g in (v.get("granted") or []):
            print("   + %s ¥%s" % (g["name"], g["value"]))
        if v.get("msg"):
            print("   msg: %s" % v["msg"])
        w = v.get("wall")
        if w:
            print("   wall: %s %s" % ("✅" if w["ok"] else "❌", w["msg"]))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "probe":
        sys.exit(run(probe_only=True))
    if cmd == "status":
        sys.exit(status())
    sys.exit(run())
