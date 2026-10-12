// CLI: node _jd_sign_cli.js <functionId> <bodyJson> [reqAppid] [signAppId] [ua]
//   注意两个 appid 是不同东西（抓包实测）：
//     请求参数 appid   京豆=asset-h5          互动中心=pc_interact_center
//     PSign appId      京豆=73c2f（h5st第3段） 互动中心=9a92f
//   默认 reqAppid=asset-h5 / signAppId=73c2f（京豆签到）
// 输出 JSON: {input:{...}, h5st:"..."}
'use strict';
const H = require('./_jd_node_harness.js');
const [fn, bodyJson, reqAppid, signAppid, ua] = process.argv.slice(2);
if (!fn) { console.error('usage: node _jd_sign_cli.js <functionId> <bodyJson> [reqAppid] [signAppId] [ua]'); process.exit(2); }
let body = {};
try { body = bodyJson ? JSON.parse(bodyJson) : {}; } catch (e) { console.error('bad bodyJson', e.message); process.exit(2); }
H.sign(body, fn, ua, reqAppid || 'asset-h5', signAppid || '73c2f').then((r) => {
  process.stdout.write(JSON.stringify({ input: r.input, h5st: r.out.h5st, raw: r.out }) + '\n');
}).catch((e) => { console.error('ERR', e && e.stack); process.exit(1); });
