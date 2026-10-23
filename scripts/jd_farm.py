#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jd_farm.py — 京东「东东农场」自动化（微信小程序 webview 链路）
============================================================
逆向来源（2026-10-17，全部实测跑通）：
  1) 京东微信小程序 wx91d27dbf599dff74 反编译包 —— dd_farm/waterdrop 是空 skyline 壳，
     真正业务在 webview H5；
  2) 活动页 bundle https://storage11.360buyimg.com/ifloors/00043240/static/js/main.4a9d7475.js
     —— 抽出全部 functionId；
  3) Reqable 实抓（WeChatAppEx.exe 走系统代理可直抓，非 direct mode）。

架构：东东农场是内嵌在小程序里的 H5 活动页
  页面  https://pro.m.jd.com/mini/active/9RQKznJKT9x6SSfKcAqGhU31U1H/index.html
  接口  POST https://api.m.jd.com/client.action   （农场核心 appid=signed_farm_mp）
        POST https://api.m.jd.com/                 （任务平台 appid=activities_platform）
  ★鉴权：**纯 cookie，无 h5st 签名**（与 PC 京豆签到 jd_web_signin.py 不同）。
    必需 cookie：pin / wq_uin / wq_skey / sdtoken；请求体带 x-api-eid-token
    （= cookie 3AB9D23F7A4B3CSS 的值，本身即 jdd03… 开头）。
    这套是**微信小程序登录态**，与 PC 的 pt_key 系不同，有效期短，需在微信里打开农场刷新后抓。

固定公共参数（每个请求都带，抄自客户端）：
  client=android  clientVersion=1.1.10  screen=414*812  wqDefault=false
  loginType=11  t=<毫秒>  body=<JSON>  functionId=<接口>

已实测接口族（functionId / appid）：
  farm_home                 signed_farm_mp   读主页：bottleWater(瓶内水滴)/treeLevel/
                                              currentProcess/waterGramSingleTime(单次耗水,实测10)
                                              /firstWateringCompleted/farmHomeSwitch.signIconShow
  farm_water                signed_farm_mp   ★浇水：body{waterType:1,onlineGiftPackageFlg:false}
                                              → bottleWater 递减、leftProcess 进度、stagePrize
                                              （浇水有机会得红包 = 用户要的"红包任务"一环）
  water_pop_window          signed_farm_mp   ★每日免费水滴弹窗领取：body{requestType:1}
  farm_red_dot              signed_farm_mp   浏览活跃上报：body{pageVisit:...}
  farm_task_list            signed_farm_mp   任务清单：result.taskList[]{taskType,taskId,
                                              taskStatus,waterCounts,pipeExt.assignmentId,...}
  farm_do_task              signed_farm_mp   做任务：body{taskType,taskId,channel:0,pipeExt}
                                              ext{prstate:0}；浏览类需真浏览，快速打会 6002 限流
  farm_task_receive_award   signed_farm_mp   领任务奖：同上；6002=限流（跳过，非失效）
  farm_plant_tree           signed_farm_mp   种树（换作物）body{level:0,type:plantLevel}
  farm_rain_round_icon      signed_farm_mp   水滴红包雨入口：userRoundState/curRoundToken/
                                              rainPageUrl（红包雨是实时小游戏，跨活动，仅报状态）
  apTaskList                activities_platform 活动平台任务（linkId=taskActId=b_ob6ZUuE77kgDezYBbQKw）

幂等/状态：
  farm_water bottleWater<waterGramSingleTime → 水不够，本轮不再浇（正常，非失效）
  farm_water result.finished=true → 该树已种成（等兑换）
  bizCode 6002/6005「做任务的用户太多了」→ 服务端限流，**跳过不算失败**
  bizCode 其它 或 code!=0 → 记 msg；-201/未登录 → 提示重抓小程序 cookie

配置 jd_farm_config.json：
  {"cookie": "<整串小程序 Cookie>", "x_api_eid_token": "jdd03...",
   "area": "7_527_0_0", "max_water_rounds": 40, "updated": "..."}
  cookie 与 x_api_eid_token 二选一优先：cookie 里若已含 3AB9D23F7A4B3CSS 会自动抽 eid。

用法：
  python jd_farm.py init "<整串 cookie>"        # 抓取一次小程序登录态落地
  python jd_farm.py status                       # 只读：瓶水/树进度/签到态/任务概览
  python jd_farm.py tasks                         # 只读列可做任务
  python jd_farm.py water                         # 只做：领每日免费水滴 + 自动浇水到水尽
  python jd_farm.py auto                          # 每日全量（总控调用）：
                                                  #   领免费水 → 自动浇水 → 尝试做任务/领奖
  python jd_farm.py probe                         # status + 一次试探浇水，看响应原文
"""
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "jd_farm_config.json")
API = "https://api.m.jd.com"
FARM_PATH = "/client.action"        # signed_farm_mp
ACT_PATH = "/"                        # activities_platform
REFERER = "https://pro.m.jd.com/mini/active/9RQKznJKT9x6SSfKcAqGhU31U1H/index.html?wxAppName=jd&babelChannel=ttt13&omitH5Params=1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
      "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
      "UnifiedPCWindowsWechat(0xf2541f35) XWEB/25799 miniProgram/wx91d27dbf599dff74")
APP_FARM = "signed_farm_mp"
APP_ACT = "activities_platform"
DEFAULT_LINK_ID = "b_ob6ZUuE77kgDezYBbQKw"
# 服务端限流码（"做任务的用户太多了" / "活动太火爆"）—— 跳过不算失败
#   405=账号级瞬时频控（短时间打太密触发，退避即恢复，非 cookie 失效）
#   6002/6005=做任务并发限流；2031=无计时任务（业务空态）
THROTTLE = (6002, 6005, 2031)
TRANSIENT = (405,) + THROTTLE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── 配置 ──────────────────────────────────────────────────────────────────
def load_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_cfg(cfg):
    cfg["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    tmp = CFG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CFG_PATH)


def _eid_from_cookie(cookie):
    m = re.search(r"3AB9D23F7A4B3CSS=([^;]+)", cookie or "")
    return m.group(1).strip() if m else ""


def cookie_header(cfg):
    c = cfg.get("cookie") or ""
    # 允许 cookies 是按域 dict（复用总控里常见格式）
    if isinstance(c, dict):
        parts = []
        for v in c.values():
            parts.append(v if isinstance(v, str) else json.dumps(v))
        c = "; ".join(parts)
    # 应用最近一次轮换出的 sdtoken（★服务端每个响应都下发新值 set;1800;<token>，
    #   客户端即用即换；长循环复用旧值会被判风控 405「活动太火爆」）
    rot = cfg.get("_sdtoken")
    if rot:
        c = re.sub(r"(?<![A-Za-z_])sdtoken=[^;]*", "sdtoken=" + rot, c)
    return c.strip()


def _rotate_sdtoken(cfg, resp):
    """从响应头 x-rp-sdtoken（格式 `set;1800;<value>`）抽新 sdtoken，写回 cfg。
    返回是否更新。不立即落盘（由调用方在动作结束时 save_cfg，减少写盘次数）。"""
    try:
        hv = resp.getheader("x-rp-sdtoken") if hasattr(resp, "getheader") else None
    except Exception:
        hv = None
    if not hv:
        return False
    parts = hv.split(";")
    if len(parts) >= 3 and parts[0].strip() == "set":
        new = ";".join(parts[2:]).strip()
        if new and new != cfg.get("_sdtoken"):
            cfg["_sdtoken"] = new
            return True
    return False


# ── HTTP ──────────────────────────────────────────────────────────────────
def call(appid, fid, body, cfg, path=FARM_PATH, ext=None, retry=2):
    """打一个 client.action 请求。返回解析后的 dict（失败带 _fail）。
    ★session_ua：会话来源决定 UA 特征（iPhone 真机会话配 iPhone UA 更一致、降低风控），
    缺省用模块 UA（Windows miniProgram）。"""
    cookie = cookie_header(cfg)
    eid = cfg.get("x_api_eid_token") or _eid_from_cookie(cookie)
    ua = cfg.get("session_ua") or UA
    form = {
        "appid": appid, "client": "android", "clientVersion": "1.1.10",
        "screen": "414*812", "wqDefault": "false", "loginType": "11",
        "t": str(int(time.time() * 1000)),
        "body": json.dumps(body, ensure_ascii=False), "functionId": fid,
    }
    if ext is not None:
        form["ext"] = json.dumps(ext, ensure_ascii=False)
    if path == FARM_PATH:
        form["x-api-eid-token"] = eid
    data = urllib.parse.urlencode(form).encode()

    last = None
    for attempt in range(retry + 1):
        # headers 每轮重建：轮换后的 sdtoken 即用即换（cookie_header 读 cfg._sdtoken）
        headers = {
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
            "user-agent": ua, "origin": "https://pro.m.jd.com", "referer": REFERER,
            "cookie": cookie_header(cfg), "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9", "accept-encoding": "gzip",
        }
        req = urllib.request.Request(API + path, data=data, headers=headers, method="POST")
        try:
            r = urllib.request.urlopen(req, timeout=25)
            raw = r.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            _rotate_sdtoken(cfg, r)   # ★轮换 sdtoken，供下一个请求即用即换
            j = json.loads(raw.decode("utf-8", "replace"))
            # 农场侧「活动太火爆」(bizCode 405) 是账号级临时频控：退避后重试一次
            bc405 = (j.get("data") or {}).get("bizCode") if isinstance(j.get("data"), dict) else None
            if bc405 == 405 and attempt < retry:
                time.sleep(3 + 3 * attempt)
                continue
            return j
        except urllib.error.HTTPError as e:
            last = {"_http": e.code, "_body": e.read().decode("utf-8", "replace")[:200]}
        except Exception as e:
            last = {"_fail": "%s: %s" % (type(e).__name__, str(e)[:150])}
        if attempt < retry:
            time.sleep(1.5 * (attempt + 1))
    return last or {"_fail": "unknown"}


def biz(j):
    """返回 (bizCode, bizMsg, result)。外层 code!=0 视为异常。"""
    if not isinstance(j, dict):
        return None, "响应非对象", {}
    if j.get("_fail") or j.get("_http"):
        return None, "网络/HTTP 错误: %s" % (j.get("_fail") or j.get("_http")), {}
    code = j.get("code")
    d = j.get("data") or {}
    if isinstance(d, dict):
        return d.get("bizCode", code), d.get("bizMsg") or j.get("msg") or j.get("errMsg"), (d.get("result") or d)
    return code, j.get("msg"), {}


# ── 业务动作 ──────────────────────────────────────────────────────────────
def get_home(cfg):
    j = call(APP_FARM, "farm_home", {"version": 30, "channelParam": "2", "babelChannel": "ttt13"}, cfg)
    bc, bm, res = biz(j)
    return bc, bm, res


def claim_free_water(cfg):
    """每日免费水滴弹窗领取（water_pop_window requestType=1）。"""
    j = call(APP_FARM, "water_pop_window",
             {"version": 30, "channelParam": "2", "requestType": 1, "babelChannel": "ttt13"}, cfg)
    bc, bm, res = biz(j)
    return bc, bm


def report_visit(cfg, page_visit=True):
    """浏览活跃上报（farm_red_dot）。"""
    j = call(APP_FARM, "farm_red_dot",
             {"version": 30, "channelParam": "2", "noviceGuidanceShouldShow": False,
              "pageVisit": page_visit, "babelChannel": "ttt13", "showDesktopTask": False}, cfg)
    bc, bm, res = biz(j)
    return bc, bm


def water_once(cfg, water_type=1):
    """浇一次水。返回 (bc, bm, result)。"""
    j = call(APP_FARM, "farm_water",
             {"version": 30, "channelParam": "2", "waterType": water_type,
              "onlineGiftPackageFlg": False, "babelChannel": "ttt13"}, cfg)
    return biz(j)


def task_list(cfg):
    j = call(APP_FARM, "farm_task_list", {"version": 30, "channelParam": "2", "babelChannel": "ttt13"}, cfg)
    bc, bm, res = biz(j)
    return bc, bm, (res.get("taskList") or []) if isinstance(res, dict) else []


def do_task(cfg, t):
    body = {"taskType": t.get("taskType"), "taskId": t.get("taskId"),
            "taskInsert": False, "itemId": "", "channel": 0, "pipeExt": t.get("pipeExt") or {}}
    j = call(APP_FARM, "farm_do_task", body, cfg, ext={"prstate": "0"})
    return biz(j)


def receive_award(cfg, t, link_id=None):
    """★领任务水滴走 apTaskDrawAward（activities_platform 域）——抓包铁证：真机今天领水
    成功就是这条，返回 {code:0, data:[{awardName:WATER, awardGivenNumber:'10'}]}。
    之前误用 signed_farm_mp 域的 farm_task_receive_award，被 6002「做任务的用户太多了」
    挡住——那是**域/接口选错**，不是浏览任务不可自动化。
    注意参数：channel=4（不是 0）、checkVersion=true、linkId=taskActId 必带。
    未完成浏览时返回 code=2014「领取次数不足」（业务态，非技术拒绝）。"""
    body = {"taskType": t.get("taskType") or t.get("awardName"), "taskId": t.get("id", t.get("taskId")),
            "channel": 4, "checkVersion": True,
            "linkId": link_id or cfg.get("task_act_id") or DEFAULT_LINK_ID,
            "pipeExt": t.get("pipeExt") or {}}
    j = call(APP_ACT, "apTaskDrawAward", body, cfg, path=ACT_PATH)
    return j.get("code"), j.get("errMsg") or j.get("msg"), (j.get("data") or [])


def limit_time_task(cfg, link_id=None):
    """计时任务（apDoLimitTimeTask，activities_platform）。抓包样本返回 2031
    「没有需要查询的计时任务」= 当前无进行中计时任务（正常空态，非失效）。
    农场有时挂"计时领水"活动（在线 N 分钟领水），有则此项能自动领。"""
    j = call(APP_ACT, "apDoLimitTimeTask",
             {"linkId": link_id or cfg.get("task_act_id") or DEFAULT_LINK_ID}, cfg, path=ACT_PATH)
    return j.get("code"), j.get("errMsg") or j.get("msg"), j.get("data")


def rain_status(cfg):
    j = call(APP_FARM, "farm_rain_round_icon",
             {"version": 30, "channelParam": "2", "babelChannel": "ttt13"}, cfg)
    return biz(j)


def ap_task_list(cfg, link_id=None):
    """活动平台任务全量（appid=activities_platform, apTaskList）。
    ★比 farm_task_list 完整得多：每项含 taskItemList[].pipeExt.itemId（真实 itemId，
    farm 侧是 -9999 占位）+ awardName/rewardId/canDrawAwardNum/taskFinished 等。
    农场 taskActId=b_ob6… 即 linkId；该域频控独立于 signed_farm_mp（farm 侧被限流时这里往往仍通）。
    返回 (code, errMsg, tasks[])。"""
    j = call(APP_ACT, "apTaskList",
             {"linkId": link_id or cfg.get("task_act_id") or DEFAULT_LINK_ID,
              "queryType": 0, "channel": 4, "area": (cfg.get("area") or "7-527-0-0").replace("_", "-")},
             cfg, path=ACT_PATH)
    d = j.get("data") if isinstance(j, dict) else None
    return j.get("code"), j.get("errMsg") or j.get("msg"), (d if isinstance(d, list) else [])


def real_item_id(t):
    """从 apTaskList 任务项取真实 itemId（首个 taskItemList 项的 pipeExt.itemId）。"""
    for ti in (t.get("taskItemList") or []):
        iid = (ti.get("pipeExt") or {}).get("itemId") or ti.get("itemId")
        if iid:
            return str(iid)
    return ""


def ap_report_pre(cfg, link_id, t, item_id):
    """浏览任务前置上报（apReportTaskPreInfo，activities_platform）。实测 code=0。
    与 apTaskDrawAward 配套：真机领水成功序列 = 前置上报 →（浏览计时）→ apTaskDrawAward 领取。"""
    j = call(APP_ACT, "apReportTaskPreInfo",
             {"linkId": link_id, "taskId": t.get("id"), "itemId": item_id,
              "taskType": t.get("taskType"), "channel": 4}, cfg, path=ACT_PATH)
    return j.get("code"), j.get("errMsg") or j.get("msg")


# ── 浇水主循环 ────────────────────────────────────────────────────────────
def run_water_loop(cfg, max_rounds=40, sleep=1.6, verbose=True):
    """自动浇水（★自举 + 快速浇水优先，不依赖 farm_home）。
    farm_water 两种模式：waterType=1 普通(单次耗 ~10ml)、waterType=2 快速(单次耗 ~50ml，
    每日有 fastWaterCount 上限)。响应自带 bottleWater/waterNum(本次实耗)/canFastWater/
    fastWaterCount/finished/leftProcess，据此动态选模式、把瓶水浇到底：
      canFastWater=true 且瓶水够 → waterType=2 猛浇；否则 → waterType=1 补到见底。
    farm_home 被单接口频控时照样能浇（自举，从第一次 farm_water 读状态）。

    返回 ok 含义：只要**没有真·鉴权失败**就 ok=True；
    throttled=True 表示因频控提前收尾（上层据此软跳过、不报失效）。"""
    bottle = None       # 瓶内水（首轮后由响应填充）
    per = 10            # 上一次实际耗水（普通默认 10，首轮后用响应 waterNum 覆盖）
    can_fast = None     # 快速浇水是否可用（首轮从 farm_home 或首次响应得到）
    watered_fast = watered_normal = 0
    got_prize = []
    finished = False
    throttled = False
    auth_fail = None

    # 先尝试读 farm_home 拿初始瓶水 + canFastWater（拿不到不影响，farm_water 自举）
    bc, bm, home = get_home(cfg)
    if isinstance(home, dict) and "bottleWater" in home:
        bottle = int(home.get("bottleWater") or 0)
        per = int(home.get("waterGramSingleTime") or per)
        can_fast = bool(home.get("canFastWater"))
        if verbose:
            print("[农场] 瓶水 %d | 普通单次耗 %d | 快速可浇=%s | 进度 %s" % (
                bottle, per, can_fast, home.get("currentProcess")))
    elif bc in TRANSIENT:
        if verbose:
            print("[农场] farm_home 被频控(bizCode=%s)，改由 farm_water 自举" % bc)
    else:
        auth_fail = bm

    for i in range(max_rounds):
        # 选模式：快速可用且（瓶水未知 或 够快速一次）→ 快速；否则普通
        fast_cost = 50  # 快速浇水经验单次耗水，首轮真实值用响应 waterNum 修正
        wt = 1
        if can_fast and (bottle is None or bottle >= fast_cost):
            wt = 2
        elif bottle is not None and bottle < per:
            break  # 瓶水连普通一次都不够
        if bottle is not None and bottle < (fast_cost if wt == 2 else per):
            wt = 1  # 快速不够退普通

        bc2, bm2, res = water_once(cfg, water_type=wt)
        if not isinstance(res, dict) or "bottleWater" not in res:
            # 水不够 / 频控 / 未登录
            if bc2 in TRANSIENT or "太火爆" in str(bm2) or "太多" in str(bm2):
                throttled = True
                if verbose:
                    print("[浇水] 第 %d 次(wt=%d)遇频控（%s），收尾（非失效）" % (
                        watered_fast + watered_normal + 1, wt, bm2))
            elif auth_fail is None and (watered_fast + watered_normal) == 0:
                if "水" in str(bm2) and ("不足" in str(bm2) or "没有" in str(bm2)):
                    if verbose:
                        print("[浇水] 瓶水为空，无需浇（明日领免费水滴）")
                else:
                    auth_fail = bm2
            break
        per = int(res.get("waterNum") or per)      # 本次实耗（普通10/快速50）
        bottle = int(res.get("bottleWater") or 0)
        can_fast = bool(res.get("canFastWater"))
        fast_cost = per if wt == 2 else fast_cost  # 记住快速单次成本
        if wt == 2:
            watered_fast += 1
        else:
            watered_normal += 1
        if res.get("finished"):
            finished = True
        for sp in (res.get("stagePrize") or []):
            if sp.get("prizeDesc"):
                got_prize.append("%s×%s" % (sp.get("prizeDesc"), sp.get("value")))
        if verbose:
            print("[浇水] %s第 %d 次(耗%d) → 瓶水 %d | 快速可浇=%s | %s%s" % (
                "⚡" if wt == 2 else "", (watered_fast + watered_normal), per, bottle,
                can_fast, res.get("leftProcess") or "",
                (" | 🎁" + ",".join(got_prize)) if got_prize else ""))
        if finished:
            break
        # 见底判断：还剩的水连最省模式(普通 per)都不够就停
        if bottle is not None and bottle < min(per, fast_cost):
            break
        time.sleep(sleep)

    return {"ok": auth_fail is None, "watered": watered_fast + watered_normal,
            "watered_fast": watered_fast, "watered_normal": watered_normal,
            "bottle_left": bottle, "finished": finished, "prizes": got_prize,
            "throttled": throttled, "reason": auth_fail}


# 浏览类任务：真完成依赖点击跳转后的 uploadInteractiveAssignment(assignmentToken)，
# 该 token 只有真实浏览器停留 6s 才生成，纯 API 拿不到（do_task/detail/receive 一律 6002/-4001）。
# 与 PC 互动中心同属硬限制，脚本**不空打**（每次 6002 会累积触发更宽频控），只如实标注需手动。
BROWSE_TYPES = ("BROWSE_CHANNEL", "BROWSE_PRODUCT", "BROWSE")


# 领水接口勘误（2026-10-18 真机抓包时序定论）：
#   真机成功领水链路 = apTaskList(读) → apTaskDrawAward(activities_platform 域) → +N WATER。
#   领之前**不需要** apReportTaskPreInfo / uploadInteractiveAssignment 前置（连接 3429 时序证实）。
#   之前误用 signed_farm_mp 域的 farm_task_receive_award → 6002「做任务的用户太多了」（域选错，非任务不可自动化）。
#   apTaskDrawAward 能否领 = 该任务 canDrawAwardNum>0 或 taskFinished=true；
#   纯浏览任务 canDraw 由服务端在“真实浏览满 6s”后置位，脚本无法强制，未达标的记 manual。
def run_tasks(cfg, verbose=True, max_draw=12):
    """领任务水滴（★正确接口 = apTaskDrawAward, activities_platform 域）。
    1) 先领计时任务 apDoLimitTimeTask（在线 N 分钟自动领水，若有则纯 API 可拿）；
    2) 遍历 apTaskList，对 canDrawAwardNum>0 / taskFinished 的任务逐个 apTaskDrawAward 领取；
    3) 未满足条件的浏览类只计数（不空打：draw 未就绪会 2014，白耗调用还喂养频控）。
    返回统计 dict {awarded, water_gained, manual, timed_task}。"""
    stats = {"awarded": 0, "water_gained": 0, "manual": 0, "timed_task": 0}
    link_id = cfg.get("task_act_id") or DEFAULT_LINK_ID
    # 1) 计时领水任务（有进行中计时才返回奖，否则 2031 空态，不算失败）
    tc, tm, tdata = limit_time_task(cfg, link_id)
    if tc == 0 and tdata:
        stats["timed_task"] += 1
        w = _water_of(tdata)
        stats["water_gained"] += w
        if verbose:
            print("[计时任务] 领取成功 +%s水" % w)
    elif verbose and tc not in (2031,) and tc not in TRANSIENT:
        print("[计时任务] code=%s %s" % (tc, tm))

    # 2) 常规任务领取
    code, msg, tasks = ap_task_list(cfg)
    if not tasks:
        if verbose:
            print("[任务] apTaskList 无任务或限流（code=%s %s）" % (code, msg))
        return stats
    drew = 0
    for t in tasks:
        title = t.get("taskShowTitle") or t.get("taskTitle") or t.get("taskType")
        can_draw = int(t.get("canDrawAwardNum") or 0)
        finished = bool(t.get("taskFinished"))
        if not (can_draw > 0 or finished):
            # 未就绪（多为纯浏览需真人点击）→ 计数不空打
            stats["manual"] += 1
            continue
        if drew >= max_draw:
            break
        drew += 1
        bc, bm, data = receive_award(cfg, t, link_id)
        if bc in (0, 200):
            w = _water_of(data)
            stats["awarded"] += 1
            stats["water_gained"] += w
            if verbose:
                print("[任务] 「%s」领水成功 +%s水" % (title, w))
        elif bc in TRANSIENT or "太快" in str(bm):
            if verbose:
                print("[任务] 「%s」领水被频控（%s），下次再领" % (title, bm))
        elif bc == 2014:
            # 到这一步仍 2014 = 表面 canDraw 但实际额度竞争失败，归 manual
            stats["manual"] += 1
            stats["awarded"] -= 0
            if verbose:
                print("[任务] 「%s」领取次数不足(2014)，需真实浏览/明日再领" % title)
        elif verbose:
            print("[任务] 「%s」领水 code=%s %s" % (title, bc, bm))
        time.sleep(1.0)
    if verbose and stats["manual"]:
        print("[任务] 共 %d 项未就绪（多为浏览类需真人点击），已就绪 %d 项全部尝试领取"
              % (stats["manual"], drew))
    return stats


def _water_of(data):
    """从 apTaskDrawAward/计时任务响应 data 里汇总水滴数。data 可能是 list[award] 或 dict。"""
    if isinstance(data, dict):
        data = data.get("data") or data.get("taskAwardResultVOS") or [data]
    if not isinstance(data, list):
        return 0
    tot = 0
    for a in data:
        if isinstance(a, dict) and str(a.get("awardName", "")).upper() == "WATER":
            try:
                tot += int(a.get("awardGivenNumber") or 0)
            except (TypeError, ValueError):
                pass
    return tot


# ── 命令 ──────────────────────────────────────────────────────────────────
def _cookie_from_stream_log(path):
    """从 Stream 抓包日志（*.txt）里抽 Cookie 头，挑农场必需项拼成整串 cookie。
    适用 neptune/minilog/blackhole 等含完整请求头的 .txt（微信真机/开发者工具导出）。
    取文件中**最后一条** Cookie 行（通常是最新的会话）。"""
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except Exception as e:
        print("[失败] 读日志文件出错：%s" % str(e)[:120])
        return None
    cookies = re.findall(r"[Cc]ookie:\s*(.+)", txt)
    if not cookies:
        print("[失败] 日志里没有 Cookie 头")
        return None
    line = cookies[-1].strip()
    d = {m.group(1): m.group(2) for m in re.finditer(r"([A-Za-z0-9_]+)=([^;]*)", line)}
    # 农场鉴权必需 + 常见辅助项
    need = ["pin", "wq_uin", "wq_skey", "sdtoken", "__jda", "__jdb",
            "shshshfpa", "shshshfpx", "visitkey", "3AB9D23F7A4B3CSS", "3AB9D23F7A4B3C9B"]
    miss = [k for k in ("pin", "wq_skey", "sdtoken") if not d.get(k)]
    if miss:
        print("[失败] 日志 cookie 缺农场必需项 %s（换一条含完整登录态的请求，如 blackhole/api.m）" % miss)
        return None
    ck = "; ".join("%s=%s" % (k, d[k]) for k in need if d.get(k))
    print("[解析] 从日志提取 %d 项 cookie（pin=%s wq_uin=%s eid=%s…）" % (
        ck.count("="), d.get("pin"), d.get("wq_uin"), (d.get("3AB9D23F7A4B3CSS") or "")[:12]))
    return ck


def cmd_init():
    if len(sys.argv) < 3 or not sys.argv[2].strip():
        print("用法: python jd_farm.py init \"<整串小程序 cookie>\"")
        print("  或: python jd_farm.py init \"<Stream 抓包日志 .txt 路径>\"  ← 自动从 Cookie 头提取")
        print("抓取: 微信打开京东小程序→进「东东农场」→Reqable 过滤 api.m.jd.com/client.action"
              " → 复制任意一条的整行 cookie（含 pin/wq_skey/sdtoken/3AB9D23F7A4B3CSS）")
        print("（或用 reqable_hunt.py harvest 自动落地）")
        return 2
    arg = sys.argv[2].strip().strip('"')
    # 传的是 .txt 日志路径 → 从中提取 cookie；否则按整串 cookie 处理
    if (not arg.startswith("pin=") and not arg.startswith("__")
            and "=" not in arg[:6] and os.path.exists(arg)):
        cookie = _cookie_from_stream_log(arg)
        if not cookie:
            return 2
    else:
        cookie = arg
    cfg = {"cookie": cookie, "x_api_eid_token": _eid_from_cookie(cookie),
           "area": "7_527_0_0", "max_water_rounds": 40,
           "task_act_id": DEFAULT_LINK_ID}
    bc, bm, home = get_home(cfg)
    if isinstance(home, dict) and "bottleWater" in home:
        print("[OK] cookie 有效 | 瓶水 %s | 树等级 %s | 进度 %s" % (
            home.get("bottleWater"), home.get("treeLevel"), home.get("currentProcess")))
    else:
        print("[警告] farm_home 未取得（%s）—— 仍写入配置，可能 cookie 已过期需在微信重开农场" % bm)
    save_cfg(cfg)
    print("[OK] 已写入 %s（eid=%s…）" % (CFG_PATH, (cfg["x_api_eid_token"] or "")[:12]))
    return 0


def _persist(cfg):
    """把轮换后的 sdtoken 落盘（cfg._sdtoken），下次运行即用最新值，减少风控命中。"""
    try:
        save_cfg(cfg)
    except Exception:
        pass


def _no_cfg():
    print("[skip] 未配置小程序登录态（jd_farm_config.json 缺失或无 cookie）——"
          "微信打开东东农场后用 reqable_hunt 抓一条 client.action 落地即可。跳过不算失效")
    return 0


def cmd_status():
    cfg = load_cfg()
    if not cfg or not cookie_header(cfg):
        return _no_cfg()
    bc, bm, home = get_home(cfg)
    if bc in TRANSIENT:
        print("[限流] farm_home bizCode=%s %s —— 账号级瞬时频控（短时间打太密），"
              "退避即恢复，非失效。稍后或明日再跑" % (bc, bm))
        _persist(cfg)
        return 0
    if not isinstance(home, dict) or "bottleWater" not in home:
        print("[失效] farm_home bizCode=%s msg=%s —【东东农场失效】小程序登录态多半过期，"
              "需在微信里重新打开东东农场刷新 cookie" % (bc, bm))
        _persist(cfg)
        return 2
    sw = home.get("farmHomeSwitch") or {}
    print("[农场] 瓶水 %s | 单次浇水耗 %s | 树等级 %s | 进度 %s | 已种成 %s 次" % (
        home.get("bottleWater"), home.get("waterGramSingleTime"), home.get("treeLevel"),
        home.get("currentProcess"), home.get("completeTimes")))
    print("[状态] 首次浇水完成=%s | 有作物=%s | 签到入口显示=%s | 任务入口显示=%s" % (
        home.get("firstWateringCompleted"), home.get("hasPlantSku"),
        sw.get("signIconShow"), sw.get("taskIconShow")))
    if str(bc) not in ("0", "200", "None"):
        print("[提示] 外层 bizCode=%s %s" % (bc, bm))
    rbc, rbm, rres = rain_status(cfg)
    if isinstance(rres, dict) and rres.get("userRoundState") is not None:
        print("[红包雨] 状态=%s 倒计时=%ss 入口=（实时小游戏，需手动进）" % (
            rres.get("userRoundState"), int((rres.get("curRoundEndCountDown") or 0) / 1000)))
    return 0


def cmd_tasks():
    cfg = load_cfg()
    if not cfg or not cookie_header(cfg):
        return _no_cfg()
    code, msg, tasks = ap_task_list(cfg)
    if not tasks:
        print("[任务] 无任务（apTaskList code=%s %s）" % (code, msg))
        return 0
    print("[任务] 共 %d 项（apTaskList 全量，含真实 itemId）：" % len(tasks))
    for t in tasks:
        award = (t.get("configBaseList") or [{}])[0]
        tt = str(t.get("taskType", "")).upper()
        can_draw = int(t.get("canDrawAwardNum") or 0)
        if can_draw > 0 or t.get("taskFinished"):
            tag = "可领奖"
        elif tt.startswith("BROWSE"):
            tag = "需真实浏览"
        else:
            tag = "待上报"
        print("  - [%s] %s | +%s%s | %s | itemId=%s" % (
            tag, t.get("taskShowTitle") or t.get("taskType"),
            award.get("awardGivenNumber"), award.get("interactiveAwardName") or "",
            t.get("taskType"), real_item_id(t)[:16]))
    return 0


def cmd_water(probe=False):
    cfg = load_cfg()
    if not cfg or not cookie_header(cfg):
        return _no_cfg()
    if probe:
        bc, bm, res = water_once(cfg)
        print("[试探浇水] bizCode=%s msg=%s\n%s" % (bc, bm, json.dumps(res, ensure_ascii=False)[:600]))
        return 0
    # 先领每日免费水，再浏览上报，再浇水
    fbc, fbm = claim_free_water(cfg)
    print("[免费水] bizCode=%s %s" % (fbc, fbm))
    report_visit(cfg)
    stat = run_water_loop(cfg, max_rounds=int(cfg.get("max_water_rounds") or 40))
    _persist(cfg)
    if stat.get("ok"):
        print("[完成] 本轮浇水 %d 次，剩余瓶水 %s%s%s" % (
            stat.get("watered", 0), stat.get("bottle_left"),
            " | 已种成🎉" if stat.get("finished") else "",
            " | 中途频控收尾(非失效)" if stat.get("throttled") else ""))
        return 0
    print("[失败] 浇水中断：%s —【东东农场失效】" % stat.get("reason"))
    return 3


def cmd_auto():
    cfg = load_cfg()
    if not cfg or not cookie_header(cfg):
        return _no_cfg()
    fbc, fbm = claim_free_water(cfg)
    print("[免费水] bizCode=%s %s" % (fbc, fbm))
    if fbc in (-201,) or "unLogin" in str(fbm):
        print("[失效] 小程序登录态过期 —【东东农场失效】需微信重开农场刷新 cookie")
        return 2
    report_visit(cfg)
    # ★领任务水放浇水前：领到的水直接进瓶，喂给随后的浇水循环
    tstat = run_tasks(cfg)
    wstat = run_water_loop(cfg, max_rounds=int(cfg.get("max_water_rounds") or 40))
    _persist(cfg)
    print("[汇总] 领任务水 +%s（计时%s/常规%s） | 浇水 %s 次(普通%s/快速⚡%s) → 瓶水剩 %s | 未就绪待手动 %s%s" % (
        tstat.get("water_gained", 0), tstat.get("timed_task", 0), tstat.get("awarded", 0),
        wstat.get("watered", 0), wstat.get("watered_normal", 0), wstat.get("watered_fast", 0),
        wstat.get("bottle_left"), tstat.get("manual", 0),
        " | 已种成🎉" if wstat.get("finished") else
        ("（中途频控收尾）" if wstat.get("throttled") else "")))
    if wstat.get("ok"):
        return 0
    print("[失败] 浇水主链路异常：%s —【东东农场失效】" % wstat.get("reason"))
    return 3


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "init":
        sys.exit(cmd_init())
    elif cmd == "status":
        sys.exit(cmd_status())
    elif cmd == "tasks":
        sys.exit(cmd_tasks())
    elif cmd == "water":
        sys.exit(cmd_water())
    elif cmd == "probe":
        sys.exit(cmd_water(probe=True))
    elif cmd == "auto":
        sys.exit(cmd_auto())
    else:
        print(__doc__)
        sys.exit(1)
