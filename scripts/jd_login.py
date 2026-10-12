#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""京东扫码登录(wq_passport 流程) → 换 pt_key/pt_pin，供 jd_signin.py 使用。

流程: new_login_entrance(s_token) → tmauthreflogurl(token) → 生成二维码 → 轮询 tmauthchecktoken → pt_key/pt_pin
用法: jd_login.py            # 生成 jd_qr.png 并轮询 300 秒，成功写 jd_config.json
      jd_login.py --check    # 用现有 jd_config.json 验证 pt_key 是否有效
"""
import json, os, re, sys, time, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "jd_config.json")
QR_PNG = os.path.join(HERE, "jd_qr.png")
UA = ("Mozilla/5.0 (Linux; Android 13; KB2000 Build/TP1A.220905.001; wv) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36")
RET = ("https://wq.jd.com/passport/LoginRedirect?state=%d&returnurl=https%%3A%%2F%%2Fhome.m.jd.com"
       "%%2FmyJd%%2Fnewhome.action%%3Fsceneval%%3D2%%26ufc%%3D%%26" % round(time.time()))

def _open(url, data=None, headers=None, timeout=30):
    r = urllib.request.Request(url, data=data.encode() if isinstance(data, str) else data)
    r.add_header("User-Agent", UA)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        x = op.open(r, timeout=timeout)
        return x.status, x.read().decode("utf-8", "replace"), x.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers
    except Exception as e:
        return -1, "EXC %s" % e, None

def setcookies(h):
    """从 headers 拼 set-cookie 名=值 字典(取第一个非空值; 忽略 Expires=1970 的删除型 cookie)"""
    out = {}
    for c in h.get_all("Set-Cookie") or []:
        if "Expires=Fri, 02-Jan-1970" in c or "Expires=Tue, 31-Dec-1996" in c:
            continue
        m = re.match(r"\s*([^=;]+)=([^;]*)", c)
        if m and m.group(1).strip() not in out and m.group(2).strip():
            out[m.group(1).strip()] = m.group(2).strip()
    return out

def login():
    # 1) new_login_entrance → s_token + guid/lsid/lstoken
    u1 = ("https://plogin.m.jd.com/cgi-bin/mm/new_login_entrance?lang=chs&appid=300&returnurl=%s&source=wq_passport"
          % urllib.parse.quote(RET, safe=""))
    st, b, h = _open(u1, headers={"Referer": "https://plogin.m.jd.com/login/login?appid=300&returnurl=%s&source=wq_passport"
                                        % urllib.parse.quote(RET, safe=""),
                                  "Host": "plogin.m.jd.com"})
    if st != 200:
        print("[1] new_login_entrance 失败 %s %s" % (st, b[:200])); return 1
    d = json.loads(b)
    s_token = d.get("s_token")
    if not s_token:
        print("[1] 未取到 s_token: %s" % b[:200]); return 1
    sc = setcookies(h)
    guid, lsid, lstoken = sc.get("guid"), sc.get("lsid"), sc.get("lstoken")
    if not (guid and lsid and lstoken):
        print("[1] set-cookie 缺失: %s" % list(sc)); return 1
    ck1 = "guid=%s;lang=chs;lsid=%s;lstoken=%s;" % (guid, lsid, lstoken)
    print("[1] s_token OK, guid=%s..." % guid[:8])

    # 2) tmauthreflogurl → token + okl_token
    data2 = "lang=chs&appid=300&returnurl=%s&source=wq_passport" % urllib.parse.quote(RET, safe="")
    u2 = ("https://plogin.m.jd.com/cgi-bin/m/tmauthreflogurl?s_token=%s&v=%d&remember=true"
          % (urllib.parse.quote(s_token, safe=""), round(time.time() * 1000)))
    st, b, h = _open(u2, data=data2, headers={"Referer": "https://plogin.m.jd.com/login/login?appid=300&returnurl=%s&source=wq_passport"
                                                    % urllib.parse.quote(RET, safe=""),
                                             "Host": "plogin.m.jd.com", "Cookie": ck1})
    if st != 200:
        print("[2] tmauthreflogurl 失败 %s %s" % (st, b[:200])); return 1
    d = json.loads(b)
    token = d.get("token")
    if not token:
        print("[2] 未取到 token: %s" % b[:200]); return 1
    okl_token = setcookies(h).get("okl_token")
    if not okl_token:
        print("[2] 未取到 okl_token"); return 1
    print("[2] token OK")

    # 3) 生成二维码图片
    qr_url = "https://plogin.m.jd.com/cgi-bin/m/tmauth?appid=300&client_type=m&token=%s" % token
    try:
        import qrcode
        qrcode.make(qr_url).save(QR_PNG)
    except Exception as e:
        print("[3] 二维码生成失败 %s" % e); return 1
    print("[3] 二维码已生成: %s" % QR_PNG)
    print("     请用京东 App 扫码(首页右上角+ → 扫一扫), 300 秒内有效")

    # 4) 轮询 tmauthchecktoken
    u4 = ("https://plogin.m.jd.com/cgi-bin/m/tmauthchecktoken?token=%s&ou_state=0&okl_token=%s"
          % (urllib.parse.quote(token, safe=""), urllib.parse.quote(okl_token, safe="")))
    hdr4 = {"Host": "plogin.m.jd.com", "Origin": "https://plogin.m.jd.com",
            "Referer": "https://plogin.m.jd.com/login/login?appid=300&returnurl=%s&source=wq_passport"
                       % urllib.parse.quote(RET, safe=""),
            "Cookie": ck1}
    deadline = time.time() + 300
    last = None
    while time.time() < deadline:
        st, b, h = _open(u4, data=data2, headers=hdr4)
        try:
            d = json.loads(b)
        except Exception:
            print("[4] 响应非 JSON: %s" % b[:200]); return 1
        err = d.get("errcode")
        if err == 0:
            sc = setcookies(h)
            pt_key = sc.get("pt_key")
            pt_pin = sc.get("pt_pin")
            if not (pt_key and pt_pin):
                print("[4] 登录成功但缺 pt_key/pt_pin: %s" % list(sc)); return 1
            cfg = {"pt_key": pt_key, "pt_pin": pt_pin,
                   "login_time": time.strftime("%Y-%m-%d %H:%M:%S"), "qr_url": qr_url}
            with open(CFG, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            print("[4] 登录成功! pt_pin=%s 已写 %s" % (pt_pin, CFG))
            return 0
        if err != last:
            print("[4] 等待扫码... errcode=%s(%s)" % (err, d.get("message", b"")))
            last = err
        if err == 21:
            print("[4] 二维码已失效"); return 1
        time.sleep(2)
    print("[4] 超时未扫码"); return 1

def check():
    if not os.path.isfile(CFG):
        print("无配置 %s" % CFG); return 1
    c = json.load(open(CFG, encoding="utf-8"))
    ck = "pt_key=%s;pt_pin=%s;" % (c["pt_key"], c["pt_pin"])
    for fn in ("signBeanIndex", "signBeanAct"):
        u = "https://api.m.jd.com/client.action?functionId=%s&appid=ld" % fn
        st, b, h = _open(u, headers={"Cookie": ck, "User-Agent": UA})
        print("[check %s] %s %s" % (fn, st, b[:160]))
    return 0

if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else login())
