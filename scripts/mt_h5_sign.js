// H5guard 签名器 (Node 沙箱还原)
//   输出: {"mtgsig": ..., "mtFingerprint": ...}
//   用法: node mt_h5_sign.js <method> <url> <bodyJson>
// 注意: H5guard.getfp() 依赖 init() 后的内部状态; 内部 setInterval 会挂住事件循环, 必须 process.exit(0)
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const code = fs.readFileSync(path.join(__dirname, "mt_H5guard.js"), "utf-8");
const noop = () => {};
const stubEl = () => ({ style: {}, getAttribute: () => null, setAttribute: noop, appendChild: noop, removeChild: noop, getContext: () => null, parentNode: null, addEventListener: noop, removeEventListener: noop });
const documentStub = { cookie: "", createElement: stubEl, getElementById: stubEl, querySelector: stubEl, querySelectorAll: () => [], getElementsByTagName: () => [], body: stubEl(), head: stubEl(), documentElement: stubEl(), addEventListener: noop, readyState: "complete", title: "" };
const navigatorStub = { userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x7300283B) WindowsWechat(0x63090c33) XWEB/14607 Flue", platform: "Win32", language: "zh-CN", languages: ["zh-CN"], appVersion: "5.0", vendor: "Google Inc.", plugins: [], mimeTypes: [], hardwareConcurrency: 8, maxTouchPoints: 0, cookieEnabled: true, onLine: true, sendBeacon: noop };
const screenStub = { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040, colorDepth: 24, pixelDepth: 24 };
const locationStub = { href: "https://market.waimai.meituan.com/playcenter/generalcoupon/fetch", hostname: "market.waimai.meituan.com", host: "market.waimai.meituan.com", protocol: "https:", origin: "https://market.waimai.meituan.com", search: "", pathname: "/playcenter/generalcoupon/fetch", hash: "" };
const windowStub = {};
Object.assign(windowStub, { document: documentStub, navigator: navigatorStub, screen: screenStub, location: locationStub, addEventListener: noop, removeEventListener: noop, setTimeout, setInterval, clearTimeout, clearInterval, Date, Math, console, JSON, Object, Array, String, Number, Boolean, RegExp, Error, encodeURIComponent, decodeURIComponent, btoa: (s) => Buffer.from(s, "binary").toString("base64"), atob: (s) => Buffer.from(s, "base64").toString("binary"), performance: { now: () => Date.now() }, localStorage: { getItem: () => null, setItem: noop, removeItem: noop }, sessionStorage: { getItem: () => null, setItem: noop, removeItem: noop }, innerWidth: 1920, innerHeight: 937, devicePixelRatio: 1, XMLHttpRequest: function () { return { open: noop, send: noop, setRequestHeader: noop, addEventListener: noop }; }, fetch: () => Promise.resolve({ json: () => Promise.resolve({}) }) });
windowStub.window = windowStub; windowStub.self = windowStub; windowStub.globalThis = windowStub; windowStub.top = windowStub; windowStub.parent = windowStub;
const ctx = vm.createContext(windowStub);
try { vm.runInContext(code, ctx, { timeout: 10000 }); } catch (e) { console.error("LOAD ERR:", String(e).slice(0, 400)); }
try { windowStub.H5guard.init({ xhrHook: false, fetchHook: false, domains: [] }); } catch (e) { console.error("INIT ERR:", String(e).slice(0, 400)); }

const [,, method, url, bodyJson] = process.argv;
const body = bodyJson ? JSON.parse(bodyJson) : undefined;
const reqCfg = { url: url, method: method || "GET", data: body, headers: { "Content-Type": "application/json" }, params: {} };
Promise.resolve()
  .then(() => windowStub.H5guard.sign(reqCfg))
  .then((res) => {
    let fp = "";
    try { fp = windowStub.H5guard.getfp(); } catch (e) { fp = "FP_ERR:" + String(e && e.message || e).slice(0, 200); }
    console.log(JSON.stringify({ mtgsig: (res.headers || res).mtgsig, mtFingerprint: fp }));
  })
  .catch((e) => console.log(JSON.stringify({ error: String(e && e.message || e).slice(0, 300) })))
  .finally(() => process.exit(0));
