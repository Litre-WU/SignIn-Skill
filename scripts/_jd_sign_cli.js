// CLI: node _jd_sign_cli.js <functionId> <bodyJson> [ua]
// 输出 JSON: {input:{...}, h5st:"..."}
'use strict';
const H = require('./_jd_node_harness.js');
const [fn, bodyJson, ua] = process.argv.slice(2);
if (!fn) { console.error('usage: node _jd_sign_cli.js <functionId> <bodyJson> [ua]'); process.exit(2); }
let body = {};
try { body = bodyJson ? JSON.parse(bodyJson) : {}; } catch (e) { console.error('bad bodyJson', e.message); process.exit(2); }
H.sign(body, fn, ua).then((r) => {
  process.stdout.write(JSON.stringify({ input: r.input, h5st: r.out.h5st, raw: r.out }) + '\n');
}).catch((e) => { console.error('ERR', e && e.stack); process.exit(1); });
