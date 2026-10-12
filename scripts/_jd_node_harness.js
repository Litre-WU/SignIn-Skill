// 在 Node 中以最小 DOM shim 运行 JD 官方 js_security_v3 ParamsSign
// 关键：不要把 JS 内置对象(Object/Array/RegExp/Date...) 传进沙箱，
//       否则 vm realm 的字面量/regexp 与外部构造函数的 RegExp.$1 会错位。
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');

function loadSigner() {
  const DEC = path.join(__dirname, '_jd_jssec.dec.js');
  if (fs.existsSync(DEC)) return fs.readFileSync(DEC, 'utf8');
  // 缺件时从京东 CDN 自愈下载（gzip 伪装）并解压落盘
  const url = process.env.JD_JSSEC_URL ||
    'https://storage.360buyimg.com/webcontainer/js_security_v3_0.1.4.js?v=20240117';
  const https = require('https');
  const zlib = require('zlib');
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      if (res.statusCode !== 200) { reject(new Error('下载签名器 HTTP ' + res.statusCode)); return; }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const buf = Buffer.concat(chunks);
        let txt;
        if (buf[0] === 0x1f && buf[1] === 0x8b) txt = zlib.gunzipSync(buf).toString('utf8');
        else txt = buf.toString('utf8');
        try { fs.writeFileSync(DEC, txt); } catch (e) {}
        resolve(txt);
      });
    }).on('error', reject);
  });
}

class El {
  constructor(t) {
    this.tagName = String(t || 'div').toUpperCase(); this.style = {}; this.dataset = {};
    this.children = []; this.childNodes = []; this.attributes = {}; this._ls = [];
    this.nodeType = 1; this.nodeName = this.tagName;
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  removeAttribute(k) { delete this.attributes[k]; }
  appendChild(c) { this.children.push(c); this.childNodes.push(c); return c; }
  insertBefore(c) { this.children.push(c); this.childNodes.push(c); return c; }
  removeChild(c) { return c; }
  addEventListener(t, f) { this._ls.push([t, f]); }
  removeEventListener() {}
  dispatchEvent() { return true; }
  getElementsByTagName() { return []; }
  getElementsByClassName() { return []; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  getContext() { return null; }
  toDataURL() { return 'data:,'; }
  getBoundingClientRect() { return { x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
  contains() { return false; }
}
class Ev { constructor(t, o) { this.type = t; Object.assign(this, o || {}); } preventDefault() {} stopPropagation() {} }

function mkBrowserGlobals(ua) {
  const store = {};
  const ls = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
    clear: () => { for (const k in store) delete store[k]; },
    key: (i) => Object.keys(store)[i] ?? null,
  };
  Object.defineProperty(ls, 'length', { get: () => Object.keys(store).length });
  const doc = {
    createElement: (t) => new El(t),
    createElementNS: (ns, t) => new El(t),
    createTextNode: (t) => ({ nodeValue: t, nodeType: 3 }),
    createDocumentFragment: () => new El('#fragment'),
    getElementsByTagName: () => [new El('script')],
    getElementsByClassName: () => [],
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    removeEventListener: () => {},
    documentElement: new El('html'),
    body: new El('body'),
    head: new El('head'),
    cookie: '',
    referrer: 'https://bean.jd.com/myJingBean/list',
    visibilityState: 'visible',
    hidden: false,
    readyState: 'complete',
    fonts: { ready: Promise.resolve([]), check: () => true, load: () => Promise.resolve([]) },
    defaultView: null,
    location: null,
    onvisibilitychange: null,
  };
  const nav = {
    userAgent: ua || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
    language: 'zh-CN', languages: ['zh-CN', 'zh'],
    platform: 'Win32', vendor: 'Google Inc.',
    product: 'Gecko', productSub: '20030107',
    appVersion: '5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
    appName: 'Netscape', appCodeName: 'Mozilla',
    hardwareConcurrency: 16, deviceMemory: 8, maxTouchPoints: 0,
    pdfViewerEnabled: true, webdriver: false, cookieEnabled: true, onLine: true,
    doNotTrack: null, msMaxTouchPoints: 0,
    plugins: { length: 5, 0: { name: 'PDF Viewer' }, 1: { name: 'Chrome PDF Viewer' }, 2: { name: 'Chromium PDF Viewer' }, 3: { name: 'Microsoft Edge PDF Viewer' }, 4: { name: 'WebKit built-in PDF' } },
    mimeTypes: { length: 2, 0: { type: 'application/pdf' }, 1: { type: 'text/pdf' } },
    userAgentData: {
      brands: [{ brand: 'Chromium', version: '141' }, { brand: 'Google Chrome', version: '141' }, { brand: 'Not-A.Brand', version: '99' }],
      mobile: false, platform: 'Windows',
      getHighEntropyValues: () => Promise.resolve({ architecture: 'x86', bitness: '64', model: '', platformVersion: '15.0.0', uaFullVersion: '141.0.0.0', fullVersionList: [] }),
    },
    javaEnabled: () => false, sendBeacon: () => true,
    oscpu: 'Windows NT 10.0; Win64; x64',
  };
  const scr = { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040, colorDepth: 24, pixelDepth: 24, availLeft: 0, availTop: 0, orientation: { type: 'landscape-primary', angle: 0 } };
  const loc = {
    href: 'https://bean.jd.com/myJingBean/list', protocol: 'https:', host: 'bean.jd.com',
    hostname: 'bean.jd.com', port: '', pathname: '/myJingBean/list', search: '',
    hash: '', origin: 'https://bean.jd.com', ancestorOrigins: { length: 0 },
  };
  const cryptoObj = {
    getRandomValues: (a) => { for (let i = 0; i < a.length; i++) a[i] = Math.floor(Math.random() * 256); return a; },
    subtle: undefined,
    randomUUID: () => 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16); }),
  };
  const noop = () => {};
  const win = {
    document: doc, navigator: nav, screen: scr, location: loc,
    localStorage: ls, sessionStorage: Object.assign({}, ls),
    crypto: cryptoObj,
    innerWidth: 1920, innerHeight: 1040, outerWidth: 1920, outerHeight: 1080,
    devicePixelRatio: 1, pageXOffset: 0, pageYOffset: 0, scrollX: 0, scrollY: 0,
    name: '', closed: false, length: 0, origin: 'https://bean.jd.com',
    isSecureContext: true, crossOriginIsolated: false,
    top: null, self: null, parent: null, frames: [],
    addEventListener: noop, removeEventListener: noop,
    dispatchEvent: () => true, postMessage: noop,
    getComputedStyle: () => ({ getPropertyValue: () => '', length: 0 }),
    matchMedia: () => ({ matches: false, media: '', addListener: noop, removeListener: noop, addEventListener: noop, removeEventListener: noop, dispatchEvent: () => true }),
    requestAnimationFrame: (cb) => setTimeout(() => cb(Date.now()), 16),
    cancelAnimationFrame: noop,
    btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
    atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    performance: { now: () => Date.now(), timeOrigin: Date.now(), memory: {}, mark: noop, measure: noop, getEntriesByName: () => [] },
    Image: function () { return new El('img'); },
    XMLHttpRequest: function () {
      return { open: noop, send: noop, setRequestHeader: noop, getResponseHeader: () => null, addEventListener: noop, removeEventListener: noop, abort: noop, readyState: 0, status: 0, statusText: '', responseText: '', response: '', upload: {}, withCredentials: false };
    },
    WebGLRenderingContext: function () {}, WebGL2RenderingContext: function () {},
    AudioContext: function () {}, OfflineAudioContext: function () {},
    RTCPeerConnection: function () {},
    fetch: () => Promise.reject(new Error('offline')),
    alert: noop, confirm: () => false, prompt: () => null,
    open: () => null, close: noop,
    scrollTo: noop, scroll: noop, scrollBy: noop, focus: noop, blur: noop, print: noop,
    Element: El, HTMLElement: El, HTMLDivElement: El, HTMLCanvasElement: El,
    HTMLScriptElement: El, HTMLIFrameElement: El, HTMLAnchorElement: El, HTMLImageElement: El,
    Node: El, NodeList: El, HTMLCollection: El, DocumentFragment: El, Text: El,
    Event: Ev, CustomEvent: Ev, MouseEvent: Ev, KeyboardEvent: Ev, UIEvent: Ev,
    MessageEvent: Ev, ErrorEvent: Ev, TouchEvent: Ev, PointerEvent: Ev,
    WheelEvent: Ev, DeviceOrientationEvent: Ev, DeviceMotionEvent: Ev, FocusEvent: Ev,
    Blob: function () {}, File: function () {}, FileReader: function () {},
    URL, URLSearchParams,
    TextEncoder, TextDecoder,
    Uint8Array, Uint16Array, Uint32Array, Int32Array, Float32Array, Float64Array,
    ArrayBuffer, DataView,
    ResizeObserver: function () { return { observe: noop, disconnect: noop, unobserve: noop }; },
    IntersectionObserver: function () { return { observe: noop, disconnect: noop, unobserve: noop }; },
    MutationObserver: function () { return { observe: noop, disconnect: noop, takeRecords: () => [] }; },
    Worker: function () { return { postMessage: noop, terminate: noop, addEventListener: noop }; },
    Notification: function () {},
    history: { length: 1, state: null, pushState: noop, replaceState: noop, back: noop, forward: noop, go: noop, scrollRestoration: 'auto' },
    setTimeout, clearTimeout, setInterval, clearInterval,
    queueMicrotask: (cb) => Promise.resolve().then(cb),
    requestIdleCallback: (cb) => setTimeout(() => cb({ didTimeout: false, timeRemaining: () => 50 }), 1),
    cancelIdleCallback: noop,
    structuredClone: (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v))),
    reportError: (e) => console.error(e),
  };
  win.window = win; win.self = win; win.top = win; win.parent = win;
  win.globalThis = win; win.frames = win;
  doc.defaultView = win; doc.location = loc;
  return win;
}

async function sign(bodyObj, functionId, ua) {
  const src = await loadSigner();
  const win = mkBrowserGlobals(ua);
  const sandbox = {};
  for (const k of Object.keys(win)) sandbox[k] = win[k];
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.console = console;
  sandbox.SHA256 = (s) => crypto.createHash('sha256').update(String(s), 'utf8').digest('hex');
  const ctx = vm.createContext(sandbox);
  vm.runInContext(src, ctx, { filename: 'js_security_v3.js', timeout: 60000 });
  const Ctor = sandbox.ParamsSign;
  if (typeof Ctor !== 'function') throw new Error('ParamsSign not exported');
  const PSign = new Ctor({
    appId: '73c2f',
    debug: false,
    preRequest: false,
    onSign: function (res) {},
    onRequestTokenRemotely: function () {},
    onRequestToken: function () {},
  });
  const u = {
    appid: 'asset-h5', clientVersion: '1.0.0', client: 'pc',
    t: String(Date.now()),
    body: crypto.createHash('sha256').update(JSON.stringify(bodyObj), 'utf8').digest('hex'),
    functionId: functionId,
  };
  return PSign.sign(u).then((e) => ({ input: u, out: e }));
}

module.exports = { sign, mkBrowserGlobals, loadSigner };

if (require.main === module) {
  const bodyObj = { type: 5, eaId: '4KpUNjgQZtanUeeqbhMYjT47b9Fo', itemId: '1', extraType: 'sign' };
  sign(bodyObj, 'pc_interact_sign_execute').then((r) => {
    console.log('IN :', JSON.stringify(r.input));
    console.log('OUT:', JSON.stringify(r.out, null, 1));
  }).catch((e) => { console.error('ERR', e); process.exit(1); });
}
