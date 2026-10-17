#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
jd_interact_inpage.py — 京东互动中心「页内执行」版（走真浏览器指纹）
==================================================================
为什么需要它（2026-10-17 实测）：`pc_interact_assign_execute` 这类写接口对
urllib 侧一律回 **HTTP 403 + 零字节**，且与"端点频率限流"无关（当日第一条 POST 即
403、同批 GET 全通、同日京豆 POST 正常）。逐项排除后只剩一个差别：京东按
**functionId + 客户端风控指纹（jrtd）**逐接口设闸。

★无头实例也不行：在 headless 里**连页面自己**发的 `pc_interact_assign_query` GET、
`pc_interact_reward_center` GET、`pc_interact_sign_execute` POST 全部 403
（同期 `pc_interact_kit_query`/`pc_interact_game_query` 是 200），说明自动化环境被整体标记。
→ 本脚本**只连你自己带 9222 启动的 Thorium**，绝不自己拉起 headless，也绝不回收你的实例。

在页面上下文里用京东自己的 SDK 发请求（与 bundle 的 `requestColorEncrypto` 同口径）：
  body 签 SHA256(JSON.stringify(去掉 functionId/mock 的参数))、x-api-eid-token 取
  window.getJsToken 的实时 jsToken、h5st 走 window.PSign.sign，fetch 带 credentials:"include"。

用法:
  python jd_interact_inpage.py check     # 只读：环境自检（9222 / SDK 全局 / 页面登录态 / 各接口通不通）
  python python jd_interact_inpage.py auto  # 领今日免费抽奖机会 → 有可抽就抽（会真实消耗机会）

前提: 你自己用 `thorium.exe --remote-debugging-port=9222` 启动 Thorium。
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CDP = os.environ.get("WB_CDP", "http://127.0.0.1:9222")
PAGE = "https://interact.jd.com/"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 与 _jd_interact_main.js 的 requestColorEncrypto 同口径的页内请求器
JS_LIB = r"""
window.__jdReq = (async function (method, params) {
  const getUuid = () => {
    const m = document.cookie.match(/(?:^| )__jda=([^;]*)/);
    if (!m) return "";
    const p = decodeURIComponent(m[1]).split(".");
    return p.length > 1 ? p[1] : "";
  };
  const getArea = () => {
    const m = document.cookie.match(/(?:^| )ipLoc-djd=([^;]*)/);
    return m ? decodeURIComponent(m[1]).replace(/-/g, "_").split(".")[0] : "";
  };
  const functionId = params.functionId;
  const o = {};
  Object.keys(params).forEach(k => { if (k !== "functionId" && k !== "mock") o[k] = params[k]; });
  const t = Date.now();
  let c = "";
  try { c = (window.SHA256 && window.SHA256(JSON.stringify(o))) || ""; } catch (e) {}
  const h = {appid: "pc_interact_center", clientVersion: "1.0.0", client: "pc", t: t, body: c, functionId: functionId};
  const f = await new Promise(res => {
    try { window.getJsToken(tk => res((tk && tk.jsToken) || null)); } catch (e) { res(null); }
  });
  const signed = await window.PSign.sign(h);
  const q = {functionId: functionId, body: JSON.stringify(o), h5st: encodeURI(signed.h5st), uuid: getUuid(),
             loginType: 3, appid: "pc_interact_center", clientVersion: "1.0.0", client: "pc", t: t, area: getArea()};
  if (f) q["x-api-eid-token"] = f;
  const usp = new URLSearchParams();
  Object.keys(q).forEach(k => { if (q[k] !== null && q[k] !== undefined) usp.append(k, String(q[k])); });
  const url = "https://api.m.jd.com/" + (method === "get" ? ("?" + usp.toString()) : "");
  const opt = {method: method.toUpperCase(), credentials: "include", headers: {}};
  if (method === "post") {
    opt.headers["content-type"] = "application/x-www-form-urlencoded";
    opt.body = usp.toString();
  }
  const r = await fetch(url, opt);
  const txt = await r.text();
  let j = null;
  try { j = JSON.parse(txt); } catch (e) {}
  return {status: r.status, eid: !!f, len: txt.length, json: j, raw: j ? null : txt.slice(0, 200)};
});
"ok"
"""


def _http(path, timeout=5, method="GET"):
    req = urllib.request.Request(CDP + path, method=method)
    with OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def cdp_online():
    try:
        return _http("/json/version")
    except Exception:
        return None


def find_page(host="interact.jd.com"):
    try:
        for t in _http("/json/list"):
            if t.get("type") == "page" and host in (t.get("url") or ""):
                return t
    except Exception:
        pass
    return None


def open_page(url):
    req = urllib.request.Request(CDP + "/json/new?" + urllib.parse.quote(url, safe=":/?&="), method="PUT")
    with OPENER.open(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


class Conn(object):
    """自带事件队列的 CDP 连接（headless_browser.Cdp 会把非应答消息丢弃，收不了事件）。"""

    def __init__(self, ws_url):
        from websocket import create_connection
        self.ws = create_connection(ws_url, timeout=60, suppress_origin=True)
        self.i = 0

    def cmd(self, method, params=None):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params or {}}))
        return self.i

    def wait(self, mid, seconds=60):
        t0 = time.time()
        while time.time() - t0 < seconds:
            self.ws.settimeout(2)
            try:
                m = json.loads(self.ws.recv())
            except Exception:
                continue
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError("%s -> %s" % (m["error"].get("code"), m["error"].get("message")))
                return m.get("result") or {}
        raise RuntimeError("CDP 等待超时 id=%s" % mid)

    def ev(self, expr, seconds=60):
        mid = self.cmd("Runtime.evaluate",
                       {"expression": expr, "awaitPromise": True, "returnByValue": True})
        r = self.wait(mid, seconds)
        if r.get("exceptionDetails"):
            return {"_js_error": str(r["exceptionDetails"])[:280]}
        return (r.get("result") or {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def attach(wait_load=8):
    """连用户自己带 9222 的浏览器；没有就明确报缺前提，绝不退化成 headless。
    ★也必须拒绝 headless 的 9222：无头实例是被京东风控整体标记的那类（连页面自己的
      GET 都 403），连上它只会得出"页内也不行"的假结论（2026-10-17 实踩）。"""
    if not cdp_online():
        print("[前提缺失] 9222 不可达。请用 `thorium.exe --remote-debugging-port=9222` 启动 Thorium 再跑。\n"
              "★本脚本不会自启 headless —— 实测无头实例连页面自己的 pc_interact_assign_query GET 都被 403。")
        return None
    try:
        v = _http("/json/version")
        ua = (v.get("User-Agent") or "").lower()
        headless = ("headless" in ua) or not (v.get("Browser") or "")
    except Exception:
        headless = False
    if headless:
        print("[拒绝] 当前 9222 是**无头实例**（Browser=%s），它已被京东风控标记，测出的 403 不代表真浏览器。\n"
              "        请在你自己的 Thorium（有窗口、日常在用）上带 --remote-debugging-port=9222 重启后再跑。"
              % v.get("Browser"))
        return None
    p = find_page()
    if not p:
        p = open_page(PAGE)
        time.sleep(wait_load)
        p = find_page() or p
    conn = Conn(p["webSocketDebuggerUrl"])
    conn.cmd("Runtime.enable"); conn.wait(conn.i)
    if conn.ev(JS_LIB) != "ok":
        print("[x] 页内请求器注入失败")
        conn.close()
        return None
    return conn


def call(conn, method, **params):
    expr = 'window.__jdReq(%s, %s)' % (json.dumps(method), json.dumps(params, ensure_ascii=False))
    return conn.ev(expr, seconds=90)


def brief(r):
    """压掉长字段，只留判读需要的。"""
    if not isinstance(r, dict):
        return r
    out = {"status": r.get("status"), "eid": r.get("eid"), "len": r.get("len")}
    j = r.get("json")
    if isinstance(j, dict):
        out["success"] = j.get("success")
        out["code"] = j.get("code") or j.get("errCode")
        out["msg"] = (j.get("msg") or j.get("message") or "")[:60]
        d = j.get("data")
        if isinstance(d, dict):
            out["data_keys"] = sorted(d.keys())[:9]
    elif r.get("raw"):
        out["raw"] = r["raw"]
    return out


def cmd_check(conn):
    print("[环境] %s" % json.dumps(conn.ev("""JSON.stringify({
        href: location.href.slice(0,46), PSign: typeof window.PSign, getJsToken: typeof window.getJsToken,
        SHA256: typeof window.SHA256, fp: typeof window._JdJrTdRiskFpInfo,
        pin: (document.cookie.match(/(?:^| )pin=([^;]*)/)||[])[1]||null})""", 20), ensure_ascii=False))
    print("[GET  pc_interact_assign_query type:1] → %s" % json.dumps(
        brief(call(conn, "get", functionId="pc_interact_assign_query", type=1)), ensure_ascii=False))
    print("[GET  pc_interact_reward_query type:0] → %s" % json.dumps(
        brief(call(conn, "get", functionId="pc_interact_reward_query", type=0, rk=False)), ensure_ascii=False))
    print("[POST pc_interact_assign_execute 基准] → %s" % json.dumps(
        brief(call(conn, "post", functionId="pc_interact_assign_execute",
                   eaId="TLBebEJwk4ADHLtRfDsRcV4UvS1", type=5, itemId="1",
                   extraType="sign", rk=False, actionType=1)), ensure_ascii=False))
    return 0


def cmd_auto(conn):
    q = call(conn, "get", functionId="pc_interact_assign_query", type=1)
    lst = (((q or {}).get("json") or {}).get("data") or {}).get("assignmentInfoList") or []
    pend = [t for t in lst if not t.get("completionFlag") and t.get("extraType") in
            ("sign", "followShop", "productsInfo", "shoppingActivity")]
    print("[待做任务] %d 项: %s" % (len(pend), [t.get("name") for t in pend][:6]))
    gained = 0
    for t in pend:
        item = "1"
        sd = t.get("signDetail") or {}
        if sd.get("itemId"):
            item = str(sd["itemId"])
        else:
            for key in ("productList", "activityChannelList", "shopList"):
                for it in (t.get(key) or []):
                    if it.get("status") == 1 and it.get("itemId"):
                        item = str(it["itemId"]); break
        r = call(conn, "post", functionId="pc_interact_assign_execute",
                 eaId=t.get("id"), type=t.get("type"), itemId=item,
                 extraType=t.get("extraType"), rk=t.get("rk") or False,
                 actionType=0 if t.get("extraType") in ("productsInfo", "shoppingActivity") else 1)
        b = brief(r)
        nq = ((((r or {}).get("json") or {}).get("data") or {}).get("assignmentRewardInfo") or {})
        print("  %-26s %s +机会=%s" % ((t.get("name") or t.get("extraType"))[:26],
                                        json.dumps(b, ensure_ascii=False)[:150],
                                        (nq.get("virtualPointReward") or {}).get("quantity")))
        if b.get("success"):
            gained += int(((nq.get("virtualPointReward") or {}).get("quantity")) or 0)
    rew = call(conn, "get", functionId="pc_interact_reward_query", type=0, rk=False)
    rd = (((rew or {}).get("json") or {}).get("data") or {})
    print("[机会池] total=%s used=%s usable=%s  本次新增=%s" % (
        rd.get("total"), rd.get("used"), rd.get("usable"), gained))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    conn = attach()
    if conn is None:
        return 1
    try:
        if sys.argv[1] == "check":
            return cmd_check(conn)
        if sys.argv[1] == "auto":
            return cmd_auto(conn)
        print("[x] 未知命令: %s（check/auto）" % sys.argv[1])
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
