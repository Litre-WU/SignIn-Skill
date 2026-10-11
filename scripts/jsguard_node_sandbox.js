// jsguard_node_sandbox.js
// 在 Node 中运行逆向提取的 wx-jsguard 模块, mock 微信小程序环境,
// 产出新鲜 mtgsig 签名 (sign 方法), 用于美团福利社领券接口.
//
// 用法: node jsguard_node_sandbox.js "<method> <url> <body>"
//   输出 JSON: { ok, mtgsig, dfpid, siua }
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const BASE = __dirname;

// ---------- 1) 读取提取的模块体 ----------
const jsguardBody = fs.readFileSync(path.join(BASE, "_jsguard_body.js"), "utf8");
const typeofBody = fs.readFileSync(path.join(BASE, "_dep_typeof_body.js"), "utf8");
const promiseBody = fs.readFileSync(path.join(BASE, "_dep_promise_body.js"), "utf8");

// ---------- 2) mock wx / 浏览器全局 ----------
const storage = {};
const sysInfo = {
  platform: "windows",
  system: "Windows 10 x64",
  version: "4.1.15.13",
  SDKVersion: "3.8.12",
  brand: "microsoft",
  model: "PCRT00A01",
  pixelRatio: 1.5,
  screenWidth: 2560,
  screenHeight: 1392,
  windowWidth: 1280,
  windowHeight: 800,
  language: "zh_CN",
  benchmarkLevel: 1,
  statusBarHeight: 24,
  battery: 80,
  wifi: true,
  networkType: "wifi",
  fontSizeSetting: 16,
  appName: "wechat",
  appVersion: "4.1.15.13",
};
const accountInfo = { miniProgram: { appId: "wx0b42a347aafbe0d0", envVersion: "release", version: "1.52.0" } };
const APPID = (process.env.MT_APPID || "wx0b42a347aafbe0d0");

function mkWx() {
  const wx = {
    getStorageSync: (k) => storage[k],
    setStorageSync: (k, v) => { storage[k] = v; },
    removeStorageSync: (k) => { delete storage[k]; },
    getSystemInfoSync: () => Object.assign({}, sysInfo),
    getSystemInfo: (o) => { o && o.success && o.success(Object.assign({}, sysInfo)); },
    getAccountInfoSync: () => JSON.parse(JSON.stringify(accountInfo)),
    getNetworkType: (o) => { o && o.success && o.success({ networkType: "wifi" }); },
    getBatteryInfoSync: () => ({ level: 80, isCharging: false }),
    getDeviceInfo: () => ({ brand: "microsoft", model: "PCRT00A01", system: "Windows 10 x64", platform: "windows" }),
    getWindowInfo: () => ({ pixelRatio: 1.5, screenWidth: 2560, screenHeight: 1392, windowWidth: 1280, windowHeight: 800, statusBarHeight: 24 }),
    getAppBaseInfo: () => ({ SDKVersion: "3.8.12", version: "8.0.49", language: "zh_CN" }),
    getAppAuthorizeSetting: () => ({}),
    onAppHide: () => {}, offAppHide: () => {}, onError: () => {}, offError: () => {},
    onUnhandledRejection: () => {}, offUnhandledRejection: () => {}, onPageNotFound: () => {}, offPageNotFound: () => {},
    getLaunchOptionsSync: () => ({ path: "pages/index/index", scene: 1001, query: {}, referrerInfo: {} }),
    getEnterOptionsSync: () => ({ path: "pages/index/index", scene: 1001, query: {} }),
    getLocation: () => {}, getPrivacySetting: (o) => { o && o.success && o.success({ needAuthorization: false }); },
    onScreenRecordingStateChanged: () => {},
    // 网络由外部处理: 返回固定成功响应, 防止 jsguard 联网上报干扰
    request: (opt) => { opt && opt.fail && setTimeout(() => opt.fail({ errMsg: "request:fail mock" }), 0); },
    checkPermission: (o) => { o && o.success && o.success({ authorized: false }); },
    getSetting: (o) => { o && o.success && o.success({ authSetting: {} }); },
  };
  return wx;
}

// ---------- 3) VM 沙箱 ----------
const wx = mkWx();

function runModule(body, moduleObj, extraGlobals, requireFn) {
  const sandbox = {
    require: requireFn || require, module: moduleObj, exports: moduleObj.exports,
    window: new Proxy({ wx, WeixinJSBridge: undefined, __wxConfig: { envVersion: "release" }, wx },
      { get(t, k) { return k in t ? t[k] : (extraGlobals && extraGlobals[k]); }, set(t, k, v) { t[k] = v; return true; } }),
    document: { createElement: () => ({ style: {} }), getElementsByTagName: () => [] },
    navigator: { userAgent: "Mozilla/5.0 MicroMessenger", platform: "Win32", language: "zh-CN" },
    location: { href: "https://servicewechat.com/" + APPID + "/275/page-frame.html", protocol: "https:" },
    localStorage: { getItem: () => null, setItem: () => {} },
    history: {}, screen: { width: 2560, height: 1392 },
    alert: () => {}, confirm: () => false, prompt: () => null,
    setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, JSON, Error, Promise, Uint8Array, Object, Array,
  };
  if (extraGlobals) Object.assign(sandbox, extraGlobals);
  sandbox.globalThis = sandbox; sandbox.self = sandbox;
  const ctx = vm.createContext(sandbox);
  vm.runInContext(body, ctx, { filename: "mod.js" });
  return moduleObj.exports;
}

// typeof 模块
let typeofMod = { exports: {} };
runModule(typeofBody, typeofMod);
// promise 模块
let promiseMod = { exports: {} };
const promiseRequire = (p) => {
  if (p.indexOf("typeof") >= 0) return typeofMod.exports;
  throw new Error("require not mapped: " + p);
};
runModule(promiseBody, promiseMod, { Symbol, TypeError }, promiseRequire);
// jsguard 主模块: require 按路径分发
let jsguardMod = { exports: {} };
const jsguardRequire = (p) => {
  if (p.indexOf("typeof") >= 0) return typeofMod.exports;
  if (p.indexOf("promise-polyfill") >= 0) return promiseMod.exports;
  throw new Error("require not mapped: " + p);
};
runModule(jsguardBody, jsguardMod, { wx }, jsguardRequire);

// ---------- 4) initSync + sign ----------
const jsguard = jsguardMod.exports && (jsguardMod.exports.default || jsguardMod.exports);
if (!jsguard || !jsguard.initSync) {
  console.error("jsguard export keys:", Object.keys(jsguardMod.exports || {}));
  process.exit(2);
}
const inst = jsguard.initSync({ appid: APPID, noSensor: true });

const args = process.argv.slice(2);
let method = "POST", url = "", body = "";
if (args.length >= 3) { method = args[0]; url = args[1]; body = args[2]; }
else if (args.length === 2) { method = "POST"; url = args[0]; body = args[1]; }

const reqObj = { url, data: body, header: { "content-type": "application/x-www-form-urlencoded" }, method };
let sig;
try {
  sig = inst.sign(reqObj);            // sign(options) — oe(a,t=!0) 里 a 即 request 对象
} catch (e) {
  console.error("sign() fail:", e && e.message);
  try { sig = inst.signWithSiua(reqObj); } catch (e2) { console.error("signWithSiua fail:", e2 && e2.message); process.exit(3); }
}

// 从 sign 后的请求对象中提取 mtgsig
let mtgsig = null;
try {
  mtgsig = (reqObj.header && reqObj.header.mtgsig) || (reqObj.header && reqObj.header.mtgsig1) || null;
} catch (e) {}
console.log(JSON.stringify({
  ok: !!mtgsig,
  mtgsig: mtgsig ? (typeof mtgsig === "string" ? mtgsig : JSON.stringify(mtgsig)) : null,
  headerKeys: reqObj.header ? Object.keys(reqObj.header) : [],
  dfpid: inst.finger ? inst.finger.d() : null,
}, null, 2));
process.exit(0);   // 显式退出: 避免 jsguard 内部 siuaTimer setInterval 阻塞

