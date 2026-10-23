// WorkBuddy 账户积分余额查询（客户端原生桥内闭环）
// 为什么整条请求都放在这里：X-Device-Token 只在「取到它的那个 SDK 进程活着的时候」有效，
// 另起进程拿令牌再去发请求会回 403 code=10085（2026-10-23 实测）。
// 入参走 stdin 的 JSON（{bearer,uid,domain,addonDir,channelId,productName,version}），
// 避免 Bearer 出现在命令行/进程列表里；本文件不落盘任何凭据。
'use strict';

async function readStdin() {
  let raw = '';
  for await (const chunk of process.stdin) raw += chunk;
  return JSON.parse(raw || '{}');
}

(async () => {
  const cfg = await readStdin();
  const sdk = require(cfg.addonDir);
  if (!sdk.isSupported()) {
    process.stdout.write(JSON.stringify({ error: 'turing sdk unavailable: ' + (sdk.getLoadError() || 'unsupported') }));
    process.exit(4);
  }
  // keychainStorageEnabled=false：只取令牌，不往本机凭据存储写任何东西。
  sdk.configure(Number(cfg.channelId), cfg.productName || 'WorkBuddy', cfg.version || '5.9.0', false);
  const deviceToken = await sdk.fetchDeviceToken({ usingCachedMessage: true, includesOutdatedMessage: false });

  const res = await fetch('https://' + cfg.domain + '/billing/meter/get-user-resource-summary', {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + cfg.bearer,
      'X-User-Id': cfg.uid || '',
      'X-Domain': cfg.domain,
      'X-Device-Token': String(deviceToken || ''),
    },
    body: '{}',
  });
  const text = await res.text();
  process.stdout.write(JSON.stringify({
    http: res.status,
    tokenLen: String(deviceToken || '').length,
    body: text ? JSON.parse(text) : null,
  }));
})().catch((err) => {
  process.stdout.write(JSON.stringify({ error: String((err && err.message) || err) }));
  process.exit(5);
});
