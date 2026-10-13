# -*- coding: utf-8 -*-
"""美团「答题领现金」游戏自动签到 / 领取任务奖励（纯 Python，Pike WebSocket 协议）。

逆向要点（2026-10-13 完成静态证据闭环 + 协议实测验证）：
- 签到/任务/红包接口不是 HTTP，而是 MGC Pike 实时长连接（businessId=mgc_connect），
  传输层 = Socket.IO v2（EIO=3）over WebSocket：
    wss://pikem0-bj.sankuai.com/pike/?bizId=mgc_connect&EIO=3&transport=websocket
- Pike 应用层协议（帧 42["pike",{v,c,d}]）：
    command:1 客户端鉴权  -> command:2 服务端鉴权 ACK（内含 token/sessionId）
    command:5 客户端业务消息 -> command:6 服务端接收 ACK（cc 序号）
    command:7 服务端业务响应（messageId 为服务端新分配）-> 客户端 command:8 ACK
  请求/响应配对：响应 message.type = 请求 type - 10000
- 鉴权签名 signature = base64(md5(bizId + "browser" + str(random_ms) + SALT))
  SALT = "5d6db287-84b8-46a7-9bcf-14242de3c139"（pike_message_2.3.10.js）
  ★已用抓包帧静态验证：computed == captured 70kIJlSWSwr0SqiJOV08gQ==
- 业务命令（bundle 事件枚举 he + 10000）：
    10100 登录(->100)        10901 Task.Info(->901)    10902 Task.Reward(->902)
    10911 Signin.Info(->911) 10912 Signin.Reward(->912)
    10801 Redpacket.Info(->801) 10802 Redpacket.WidthDraw(->802)
- 签到数据结构（10911 -> sevenDayTaskList）：
    status: 0 未完成 / 1 已完成待领奖 / 2 已领奖（awardTime>0）
    幂等判据 = 服务端 status，不依赖本地标记

子命令：
  probe   只读：连接 + 登录 + 查签到/任务/红包状态（不做任何写操作）
  status  同 probe
  signin  领取七日签到奖励（status==1 的任务走 10912）
  task    领取任务奖励（10901 查询 + 10902 领取）
  draw    红包提现（10802，写操作，auto 不含）
  auto    signin + task + 状态汇报

依赖：websocket-client（envs/default 已装）
配置：同目录 mt_answer_config.json（token/userId/uuid/appId）
"""
import base64
import hashlib
import json
import os
import random
import sys
import threading
import time

import websocket

DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(DIR, "mt_answer_config.json")
STATE = os.path.join(DIR, "mt_answer_state.json")

WS_URL = "wss://pikem0-bj.sankuai.com/pike/?bizId=mgc_connect&EIO=3&transport=websocket"
BIZ_ID = "mgc_connect"
APP_ID = "mgcz6p6s29fz5ygh"
SALT = "5d6db287-84b8-46a7-9bcf-14242de3c139"

# 业务命令类型（请求方），响应 type = 请求 type - 10000
T_LOGIN = 10100
T_TASK_INFO = 10901
T_TASK_REWARD = 10902
T_SIGNIN_INFO = 10911
T_SIGNIN_REWARD = 10912
T_RED_INFO = 10801
T_RED_DRAW = 10802

CMD_LOGIN = 1
CMD_LOGIN_ACK = 2
CMD_UPSTREAM = 5
CMD_UPSTREAM_ACK = 6
CMD_DOWNSTREAM = 7
CMD_DOWNSTREAM_ACK = 8

MSG_TIMEOUT = 15  # 单个业务请求等待响应秒数


def log(msg):
    print(msg, flush=True)


def _ts():
    import time as _t
    return "%.3f" % _t.time()


def sign(random_ms):
    """pike 鉴权签名 = base64(md5(bizId + system + str(random) + SALT))。已静态验证。"""
    s = BIZ_ID + "browser" + str(random_ms) + SALT
    return base64.b64encode(hashlib.md5(s.encode("latin-1")).digest()).decode()


def gen_msg_id():
    """与抓包同形的 messageId（22 字符 base64 字母表），仅用于去重/ACK 关联。"""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    return "".join(random.choice(alphabet) for _ in range(22))


class PikeClient:
    """MGC Pike 长连接客户端（Socket.IO v2 / Engine.IO v3）。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.ws = None
        self.token = None
        self.session_id = None
        self.req_idx = 0
        self._stop = False
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._waiters = {}   # resp_type -> {"event","result","error"}
        self._eio_open = threading.Event()
        self._authed = threading.Event()
        self._logs = []

    # ── 连接 ──────────────────────────────────────────────
    def connect(self):
        self.ws = websocket.create_connection(WS_URL, timeout=30, suppress_origin=True)
        t = threading.Thread(target=self._read_loop, daemon=True)
        t.start()
        if not self._eio_open.wait(10):
            raise RuntimeError("Engine.IO 握手超时（未收到 0{open}）")
        self._auth()
        if not self._authed.wait(15):
            raise RuntimeError("Pike 鉴权超时（未收到 command:2）")
        # engine.io ping：客户端主动发 2，服务端回 3
        threading.Thread(target=self._ping_loop, daemon=True).start()

    def _ping_loop(self):
        while not self._stop:
            time.sleep(8)
            try:
                self.ws.send("2")
            except Exception:
                return

    def _read_loop(self):
        while not self._stop:
            try:
                raw = self.ws.recv()
            except Exception as e:
                import os as _os
                if _os.environ.get("MT_ANSWER_DBG"):
                    print("[%s DBG-read-died]" % _ts(), e, flush=True)
                self._fail_all("连接关闭")
                return
            if not raw:
                continue
            p, body = raw[0], raw[1:]
            if p == "0":
                self._eio_open.set()
            elif p == "4":
                if not body:
                    continue
                k = body[0]
                if k == "0":
                    pass  # socket connect
                elif k == "2":
                    self._on_message(body[1:])
                elif k == "3":
                    pass  # ack
            elif p == "2":
                try:  # 服务端 ping -> 回 pong
                    self.ws.send("3")
                except Exception:
                    return
            elif p == "3":
                pass

    def _on_message(self, payload):
        import os as _os
        if _os.environ.get("MT_ANSWER_DBG"):
            print("[%s DBG-recv-msg]" % _ts(), payload[:160], flush=True)
        try:
            arr = json.loads(payload)
        except Exception as e:
            if _os.environ.get("MT_ANSWER_DBG"):
                print("[DBG-recv-msg parse fail]", e, flush=True)
            return
        if not isinstance(arr, list) or len(arr) < 2 or arr[0] != "pike":
            return
        try:
            inner = json.loads(arr[1]["d"])
        except Exception:
            return
        cmd = inner.get("command")
        data = inner.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                pass
        if cmd == CMD_LOGIN_ACK:
            self.token = data.get("token")
            self.session_id = data.get("sessionId")
            if str(data.get("status", -1)) != "0" or not self.token:
                self._fail_all("鉴权被拒绝 status=%s" % data.get("status"))
                return
            self._authed.set()
        elif cmd == CMD_UPSTREAM_ACK:
            pass  # 服务端已接收，业务响应在 command:7
        elif cmd == CMD_DOWNSTREAM:
            mid = data.get("messageId")
            try:
                msg = json.loads(data.get("message", "{}"))
            except Exception:
                msg = {}
            self._ack_downstream(mid)
            # 服务端 type 可能返回字符串（"100"），统一转 int 以匹配 waiter 键
            try:
                rtype = int(msg.get("type"))
            except (TypeError, ValueError):
                rtype = msg.get("type")
            self._resolve(rtype, msg)
        elif cmd == 3:  # 服务端要求重连等
            self._fail_all("服务端下发 command:%s" % cmd)

    def _ack_downstream(self, mid):
        """对服务端 command:7 推送回 command:8 ACK（忠实模拟客户端）。"""
        if not mid or not self.token:
            return
        self._send_raw(self._pack(CMD_DOWNSTREAM_ACK,
                                  {"messageId": mid, "status": 0, "token": self.token}))

    # ── 收发 ──────────────────────────────────────────────
    def _pack(self, cmd, data):
        return '42["pike",{"v":1,"c":1,"d":%s}]' % json.dumps(
            json.dumps({"command": cmd, "data": data}, ensure_ascii=False,
                       separators=(",", ":")), ensure_ascii=False)

    def _send_raw(self, s):
        self.ws.send(s)

    def _auth(self):
        rnd = int(time.time() * 1000)
        data = {
            "bizId": BIZ_ID, "businessId": BIZ_ID, "random": rnd,
            "appName": "browser", "platform": 3, "network": 4, "deviceId": None,
            "extra": {
                "loginV2": True, "accessToken": None, "appId": APP_ID,
                "userId": str(self.cfg["userId"]),
                "mtDeviceId": self.cfg["uuid"],
                "mtToken": self.cfg["token"], "guestLogin": False,
            },
            "swimlane": "", "alias": "", "sessionId": None,
            "signature": sign(rnd), "rt": None, "sdkVersion": "2.3.10",
        }
        self._send_raw(self._pack(CMD_LOGIN, data))

    def send(self, msg_type, data, timeout=MSG_TIMEOUT):
        """发送业务消息并等待对应响应（resp_type = msg_type - 10000）。返回 {code,data,...}。"""
        rtype = msg_type - 10000
        with self._lock:
            if rtype in self._waiters:
                raise RuntimeError("重复请求 type=%s" % msg_type)
            self._waiters[rtype] = {"event": threading.Event(),
                                    "result": None, "error": None}
        self.req_idx += 1
        payload = {"messageId": gen_msg_id(), "token": self.token,
                   "message": {"type": msg_type, "data": data,
                               "reqIdx": self.req_idx, "retryInfo": {"retryMax": 0}}}
        self._send_raw(self._pack(CMD_UPSTREAM, payload))
        w = self._waiters[rtype]
        import os as _os
        if _os.environ.get("MT_ANSWER_DBG"):
            print("[%s DBG-send] type=%s waiter_id=%s event_id=%s" % (_ts(), msg_type, id(w), id(w["event"])), flush=True)
        if not w["event"].wait(timeout):
            self._drop(rtype)
            raise RuntimeError("请求 type=%s 响应超时" % msg_type)
        with self._lock:
            self._waiters.pop(rtype, None)
        if w["error"]:
            raise RuntimeError(w["error"])
        return w["result"]

    def _resolve(self, rtype, msg):
        import os as _os
        if _os.environ.get("MT_ANSWER_DBG"):
            print("[%s DBG-resolve] rtype=%r waiters=%r" % (_ts(), rtype, list(self._waiters.keys())), flush=True)
        with self._lock:
            w = self._waiters.get(rtype)
            if not w:
                return  # 异步推送 / 非本次请求，丢弃
            w["result"] = msg
            w["event"].set()
            import os as _os2
            if _os2.environ.get("MT_ANSWER_DBG"):
                print("[DBG-resolved-set] waiter_id=%s event_id=%s" % (id(w), id(w["event"])), flush=True)

    def _drop(self, rtype):
        with self._lock:
            self._waiters.pop(rtype, None)

    def _fail_all(self, err):
        with self._lock:
            for w in self._waiters.values():
                w["error"] = err
                w["event"].set()

    def close(self):
        self._stop = True
        try:
            self.ws.close()
        except Exception:
            pass


# ── 业务封装 ─────────────────────────────────────────────
def login(c):
    r = c.send(T_LOGIN, {"login": 1, "version": "200", "gameVer": "unkonw GameVersion",
                         "sdkVer": "0", "appVer": "0",
                         "from": c.cfg.get("inner_source", "10247_ch325"),
                         "lch": "", "plat": "wx",
                         "shareInfo": {"mgcId": "", "type": "", "time": ""}})
    if r.get("code") != 200:
        raise RuntimeError("登录失败: %s" % r)
    return r.get("data", {}).get("playerInfo", {})


def signin_info(c):
    r = c.send(T_SIGNIN_INFO, {})
    if r.get("code") != 200:
        raise RuntimeError("签到信息查询失败: %s" % r)
    return r.get("data", {}).get("sevenDayTaskList", [])


def signin_reward(c, task_id):
    return c.send(T_SIGNIN_REWARD, {"taskId": task_id})


def task_info(c):
    r = c.send(T_TASK_INFO, {})
    if r.get("code") != 200:
        raise RuntimeError("任务信息查询失败: %s" % r)
    return r.get("data", {})


def task_reward(c, task_id):
    return c.send(T_TASK_REWARD, {"taskId": task_id})


def redpacket_info(c):
    r = c.send(T_RED_INFO, {})
    if r.get("code") != 200:
        raise RuntimeError("红包信息查询失败: %s" % r)
    return r.get("data", {}).get("redEnvelopeData", {})


def redpacket_draw(c):
    return c.send(T_RED_DRAW, {})


# ── 展示 ────────────────────────────────────────────────
def show_player(p):
    if not p:
        return
    log("玩家: %s | 金币 %s | 钻石 %s | 等级 %s | 连签 %s 天"
        % (p.get("nickName"), p.get("gold"), p.get("diamond"),
           p.get("curLevel"), p.get("curDays")))


def show_signin(tasks):
    if not tasks:
        log("七日签到: 无数据")
        return
    for t in tasks:
        st = {0: "未完成", 1: "已完成待领奖", 2: "已领奖"}.get(t.get("status"), str(t.get("status")))
        rw = t.get("rewardInfos") or []
        desc = ",".join("item%sx%s" % (x.get("itemId"), x.get("num")) for x in rw)
        log("  任务%s progress=%s/%s [%s] 奖励 %s"
            % (t.get("taskId"), t.get("progress"), t.get("progress"), st, desc))


# ── 子命令 ──────────────────────────────────────────────
def cmd_probe(c):
    p = login(c)
    show_player(p)
    tasks = signin_info(c)
    log("== 七日签到 ==")
    show_signin(tasks)
    try:
        red = redpacket_info(c)
        log("== 红包 ==")
        log("  当前金额: %s 分" % red.get("currentNum"))
        recs = red.get("acquireRecords") or []
        if recs:
            log("  最近入账: %s 笔，最近 %s 分"
                % (len(recs), recs[0].get("num")))
    except Exception as e:
        log("  红包查询失败: %s" % e)
    return {"player": p, "signin": tasks}


def cmd_signin(c):
    """领取七日签到奖励（幂等：只领 status==1 的）。"""
    tasks = signin_info(c)
    log("== 七日签到 ==")
    show_signin(tasks)
    todo = [t for t in tasks if t.get("status") == 1]
    if not todo:
        log("无可领取的签到奖励（全部未完成或已领奖），跳过")
        return {"claimed": [], "tasks": tasks}
    claimed = []
    for t in todo:
        tid = t.get("taskId")
        r = signin_reward(c, tid)
        if r.get("code") == 200:
            d = r.get("data", {})
            log("领取成功 taskId=%s 奖励 %s" % (tid, json.dumps(d, ensure_ascii=False)[:200]))
            claimed.append(tid)
        else:
            log("领取失败 taskId=%s: %s" % (tid, json.dumps(r, ensure_ascii=False)[:200]))
    # 复核
    after = signin_info(c)
    log("== 领取后复核 ==")
    show_signin(after)
    return {"claimed": claimed, "tasks": after}


def cmd_task(c):
    """领取任务奖励（幂等：只领已完成未领取的）。"""
    data = task_info(c)
    log("== 任务 ==")
    log(json.dumps(data, ensure_ascii=False)[:600])
    # 任务列表结构未实测，通用化：递归找 status==1 且有 taskId 的项
    todo = []
    def walk(o):
        if isinstance(o, dict):
            if "taskId" in o and o.get("status") == 1:
                todo.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    if not todo:
        log("无可领取的任务奖励，跳过")
        return {"claimed": [], "data": data}
    claimed = []
    for t in todo:
        tid = t.get("taskId")
        r = task_reward(c, tid)
        if r.get("code") == 200:
            log("任务奖励领取成功 taskId=%s" % tid)
            claimed.append(tid)
        else:
            log("任务奖励领取失败 taskId=%s: %s" % (tid, json.dumps(r, ensure_ascii=False)[:200]))
    return {"claimed": claimed, "data": data}


def cmd_draw(c):
    red = redpacket_info(c)
    cur = red.get("currentNum")
    log("当前红包金额: %s 分" % cur)
    if not cur:
        log("余额为 0，跳过提现")
        return None
    r = redpacket_draw(c)
    log("提现结果: %s" % json.dumps(r, ensure_ascii=False)[:400])
    return r


def cmd_auto(c):
    log("== 登录 ==")
    p = login(c)
    show_player(p)
    log("\n== 签到 ==")
    s = cmd_signin(c)
    log("\n== 任务 ==")
    t = cmd_task(c)
    log("\n== 红包 ==")
    try:
        red = redpacket_info(c)
        log("当前金额: %s 分" % red.get("currentNum"))
    except Exception as e:
        log("红包查询失败: %s" % e)
    return {"player": p, "signin": s, "task": t}


def load_cfg():
    if not os.path.exists(CONFIG):
        sys.exit("[ERR] 缺少配置 %s（需 token/userId/uuid）" % CONFIG)
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    for k in ("token", "userId", "uuid"):
        if not cfg.get(k):
            sys.exit("[ERR] 配置缺字段 %s" % k)
    return cfg


def save_state(st):
    try:
        prev = {}
        if os.path.exists(STATE):
            prev = json.load(open(STATE, encoding="utf-8"))
        prev[time.strftime("%Y-%m-%d")] = {"cmd": st.get("cmd"),
                                           "at": time.strftime("%H:%M:%S"),
                                           "summary": st.get("summary")}
        json.dump(prev, open(STATE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if cmd not in ("probe", "status", "signin", "task", "draw", "auto"):
        sys.exit("未知子命令: %s（probe/status/signin/task/draw/auto）" % cmd)
    cfg = load_cfg()
    c = PikeClient(cfg)
    try:
        c.connect()
        log("已连接 Pike（sessionId=%s）" % c.session_id)
    except Exception as e:
        msg = str(e)
        if "鉴权" in msg or "401" in msg or "拒绝" in msg:
            log("【美团答题token失效】%s" % msg)
            sys.exit(0)
        raise
    try:
        if cmd in ("probe", "status"):
            r = cmd_probe(c)
        elif cmd == "signin":
            r = cmd_signin(c)
        elif cmd == "task":
            r = cmd_task(c)
        elif cmd == "draw":
            r = cmd_draw(c)
        else:
            r = cmd_auto(c)
        save_state({"cmd": cmd, "summary": json.dumps(r, ensure_ascii=False)[:800]})
        log("\n[%s] 完成" % cmd)
    finally:
        c.close()


if __name__ == "__main__":
    main()
