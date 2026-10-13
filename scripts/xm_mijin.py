# -*- coding: utf-8 -*-
# xm_mijin.py —— 小米商城「做任务领米金」自动化
# 链路：personalHome 取米金页 sign → venue/page(v1) 取任务清单 → infinite/do → infinite/done
# 幂等：done 返回 code=200001「达到任务上限」即本任务已完成；code=0 且 awardList 非空=真实入账
# 用法：xm_mijin.py probe | auto
import urllib.request, urllib.parse, gzip, json, time, sys, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _mishop_client import SERVICE_TOKEN, USER_ID, XM_UUID, headers as _base_headers

H_SHOP = "https://shop-api.retail.mi.com"   # personalHome
H_M = "https://m.mi.com"                    # 米金页 venue + infinite do/done
H_XSHOP = "https://xiaomishop.retail.mi.com"  # 米金额度

STATE = os.path.join(HERE, "_mijin_state.json")


def _mk(host):
    h = _base_headers()
    h["Host"] = urllib.parse.urlparse(host).netloc
    h["Referer"] = host
    return h


def post(host, path, payload):
    url = host + path
    h = _mk(host)
    data = json.dumps([{}, payload], separators=(",", ":"), ensure_ascii=False).encode()
    h["Content-Length"] = str(len(data))
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        r = op.open(req, timeout=25)
        raw = r.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return e.code, raw.decode("utf-8", "replace")


def get(host, path):
    url = host + path
    h = _mk(host)
    h.pop("Content-Type", None)
    req = urllib.request.Request(url, headers=h, method="GET")
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        r = op.open(req, timeout=30)
        raw = r.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return e.code, raw.decode("utf-8", "replace")


def _j(body):
    try:
        return json.loads(body)
    except Exception:
        return {}


def mi_coin():
    """米金余额"""
    st, body = post(H_XSHOP, "/mtop/xiaomishop/mi/amount/personal/center/info",
                    {"scene": "1", "appId": "mishop-rn"})
    d = _j(body)
    if d.get("code") == 0:
        return (d.get("data") or {}).get("amountTotal")
    return None


def mijin_sign():
    """从 personalHome 取米金页最新 sign"""
    st, body = post(H_SHOP, "/mtop/mf/usercenter/personalHome",
                    {"lat": "30.535470", "lng": "114.512096",
                     "cityId": "205", "provinceId": "18"})
    d = _j(body)
    data = d.get("data") or {}
    j = ((data.get("personalAssets") or {}).get("miGoldRemindInfos") or {}).get("jumpUrl", "")
    m = re.search(r"pageid=(\d+)&pdl=(\w+)&sign=([0-9a-f]+)", j or "")
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None, None, None


def task_list():
    """米金商城页任务清单（venue/page v1 + sign）"""
    pid, pdl, sign = mijin_sign()
    if not sign:
        return []
    st, body = get(H_M, "/mtop/navi/venue/page?page_id=%s&pdl=%s&sign=%s" % (pid, pdl, sign))
    d = _j(body)
    if d.get("code") != 0:
        return []
    floors = (d.get("data") or {}).get("floors") or []
    for f in floors:
        if (f.get("module_key") or "") == "mi_task_floor":
            tf = f.get("data") or {}
            return tf.get("actIdList") or [], tf.get("actId")
    return [], None


def do_task(act_id, task_id):
    st, body = post(H_M, "/mtop/mf/act/infinite/do",
                    {"actId": act_id, "taskId": task_id})
    d = _j(body)
    return (d.get("data") or {}).get("taskToken"), d.get("code"), d.get("message")


def done_task(task_token, act_id, task_type, extra=None):
    st, body = post(H_M, "/mtop/mf/act/infinite/done",
                    {"taskToken": task_token, "actId": act_id,
                     "taskType": task_type, "extra": extra})
    return _j(body)


def probe():
    print("== 米金余额 ==")
    print("amountTotal =", mi_coin())
    tl, act = task_list()
    if not tl:
        print("!! 任务清单拉取失败")
        return
    print("== actId ==", act, " tasks:", len(tl))
    for t in tl:
        spec = t.get("taskSpecConfig") or {}
        print("  [%s] type=%s name=%s duration=%s" % (
            t.get("id"), t.get("type"), t.get("taskName"), spec.get("duration", "")))


def auto():
    before = mi_coin()
    print("米金余额 before:", before)
    tl, act = task_list()
    if not tl:
        print("!! 任务清单拉取失败")
        return
    print("actId:", act, "tasks:", len(tl))
    got_total = 0
    done_cnt = 0
    skip_cnt = 0
    for t in tl:
        tid = t.get("id")
        ttype = t.get("type")
        name = t.get("taskName") or ""
        spec = t.get("taskSpecConfig") or {}
        # type 211 = 下载/打开第三方 App，无法纯脚本完成
        if ttype == 211:
            print("  [skip] %s (type=211 需真实App行为)" % name)
            skip_cnt += 1
            continue
        dur = spec.get("duration") or 0
        try:
            dur = int(dur)
        except Exception:
            dur = 0
        tk, code, msg = do_task(act, tid)
        if not tk:
            print("  [do失败] %s code=%s msg=%s" % (name, code, msg))
            continue
        if dur > 0:
            time.sleep(min(dur + 1, 12))
        d = done_task(tk, act, ttype)
        dcode = d.get("code")
        dmsg = d.get("message")
        if dcode == 200001:
            print("  [已完成] %s (达到任务上限)" % name)
            skip_cnt += 1
            continue
        aws = (d.get("data") or {}).get("awardList") or []
        gain = 0
        for a in aws:
            try:
                gain += int(a.get("awardValue") or 0)
            except Exception:
                pass
        if dcode == 0 and gain > 0:
            got_total += gain
            done_cnt += 1
            print("  [领取] %s +%d 米金 (%d项)" % (name, gain, len(aws)))
        else:
            print("  [done] %s code=%s msg=%s" % (name, dcode, dmsg))
        time.sleep(1)
    after = mi_coin()
    print("----")
    print("米金余额 after:", after, " delta:", (after - before) if (before is not None and after is not None) else "?")
    print("新完成任务:", done_cnt, " 跳过/已完成:", skip_cnt, " 本轮领取:", got_total)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "probe":
        probe()
    elif cmd == "auto":
        auto()
