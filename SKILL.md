---
name: 签到啦
description: 一站式签到/领券综合工具，整合七个已抓包验证的自动化入口：美团福利社每日领券+营销页红包、南航（中国南方航空小程序）双链路签到+签到抽奖、魔搭 ModelScope 每日魔粒、WorkBuddy 积分签到+派猫猫旅行、办公小浣熊（商汤 xiaohuanxiong）每日积分、Loomy（讯飞）每日积分。纯接口自动化（非 UI 点击），支持幂等与定时任务。当用户要求"签到"、"领券"、"打卡"、"每天签到"、"美团领券"、"南航签到"、"魔搭魔粒"、"WorkBuddy积分"、"小浣熊积分"、"Loomy积分"、或提及这些平台时使用。配置只需抓 1 条请求发给我即可，方法见 SKILL.md。
---

# 签到啦 · 一键签到/领券合集

整合七个**已抓包验证**的自动化入口，全部纯接口实现，自带幂等（当天不重复执行）与状态文件。

| 平台 | 脚本 | 作用 | 依赖 |
|---|---|---|---|
| 南航（中国南方航空小程序） | `scripts/csair_signin.py` | 发现新境签到 + 营销签到领里程 + 签到抽奖机会检测（抽奖消耗半自动） | Python 标准库（H5 重登需 Playwright） |
| 美团券包 | `scripts/mt_api_coupon.py` | 每日领券 + 营销页红包（可选） | Python + Node（mtgsig 签名沙箱） |
| 美团福利社 H5 活动页 | `scripts/mt_gundam_coupon.py` | 福利社 tab 的 gundam 活动页（"周末加码必得百元券包"）：跨券墙(百元券包主力) + 限时抢券 + 天降掉券，全自动发现活动 ID | Python + Node |
| 魔搭（ModelScope） | `scripts/ms_magicube.py` | 每日登录魔粒 +250 + 点赞刷分 +40（会话副作用 + star/unstar 循环） | Python 标准库 |
| WorkBuddy 积分 | `scripts/wb_score.py` | Buddy 加油站签到 +100/天 + 派猫猫旅行闭环（先领后派，5~10/天） | Python 标准库（底层调 totorosir-workbuddy-score skill） |
| 办公小浣熊（商汤 xiaohuanxiong） | `scripts/xhx_office_points.py` | 每日积分确认（免费版每日送 300，会话活跃自动入账；refresh_token 自动续 accessToken） | Python 标准库 |
| Loomy（讯飞 loomy.xunfei.cn） | `scripts/loomy_points.py` | 每日积分确认（站点活跃自动入账，纯 cookie 鉴权） | Python 标准库 |

> **工作方式**：你抓包、发我请求，我来分析、生成配置、自动执行。你不需要记命令、不需要懂字段，脚本命令只在「导出脚本自用」时才需要（见文末）。

---

## 一、你要做的：抓 1 条请求发我

> 准备：电脑/手机微信挂 **Reqable / mitmproxy / Charles** 代理，正常打开对应小程序操作一次，把下面这条请求「整条复制」（抓包工具里选该请求 → 复制 Request）发给我即可。

### 1) 美团福利社

电脑微信打开「美团小程序 → 福利社」，点一下**领券/待领取**，抓这条请求：
```
https://media.meituan.com/fulishemini/couponActivity/listActivityCoupon...
（或 grantActivityCoupon...，出现哪个抓哪个）
```
**发给我整条请求**（URL + 请求头 + 请求体）。我会自动从里面取出 token / open_id / unionid / userid / openIdCipher / expoId / wm_uuid 等字段生成配置。

> 美团接口带 **mtgsig 动态签名**（wx-jsguard），脚本用还原的原算法实时生成（非重放），需要本机 Node.js（自动探测 `MT_NODE` 环境变量 → 常见安装路径 → `node`）。如果你抓包的设备是手机微信，且版本与脚本内置的不一致，签名可能被风控——**把那台设备的抓包整条发我，我再适配版本字段**。

> **营销页红包**（可选）：在美团小程序里进入任意**营销活动页**（如红包雨/活动会场）点一次领券，把那条 `realTimeMarketingSendCoupon` 请求发我，我会额外配上 `recallToken`，之后每日自动多领一份营销页红包。不抓也能用，只是少这一份。

> **福利社 H5 活动页（"一键领百元券包"）**：福利社底部 tab 本身是一个 gundam 动态 H5 页（不是小程序原生页），脚本 `mt_gundam_coupon.py` 已覆盖。**复用同一条抓包的 wm_logintoken 即可，无需额外抓包**。它自动完成：底部 tab 配置 → 活动 gundam_id → 页面配置 → 全部领券组件（**跨券墙** / 限时抢券 / 天降掉券）。活动每周轮换、activityId 变化都能自动跟上。

---

### 2) 南航

微信打开「中国南方航空」小程序，随便触发一次登录，抓这条请求：
```
POST https://wxapi.csair.com/mini/api/login/isLogin?appid=<小程序appid>&wxchannel=wxopen&envVersion=release
```
**发给我整条请求**（URL + 请求头 + 请求体）。我会从请求头 `sessionid` + 请求体 `ssoKey` 生成配置（`unnecessaryparam` 的 openId 一并记下）。

> 南航会自动顺带完成 **H5 营销签到**领里程（当前活动和里程日期由脚本动态探测）。

**失效与续期（2026-10-10 反编译还原，重要）**：sessionId 的唯一来源是 `wx.login()` 的 code 调 `/mini/api/login/login` 换取（该接口是微信 code2session 直通，假 code 回 `WX40029`、空 code 回 `WX41008`），**不存在任何服务端刷新接口**。sessionId 寿命 ≈ 微信 session_key 寿命（数小时~1 天），微信侧主动刷新后 CSAIR 缓存即失效，与我方调用频率无关。
>
> ★抓包要点：小程序刚打开时的头几个请求可能仍带 stale sessionId（回 `W00000 invalid session`），客户端会透明重登。所以**抓 `isLogin` 请求头有概率拿到的是旧 sessionId**。更稳的目标是抓 **`/mini/api/login/login` 的响应体**（含全新的 sessionId/openId/unionId），或刷新成功之后的任意请求。把响应发我，用 `refresh` 子命令一键更新（会立即调 isLogin 校验，无效会明确提示重抓）。
>
> 排查命令：`python scripts/csair_signin.py doctor`（sessionId 与 H5 signToken 逐一探活，给出可执行结论）。

**★H5 账号密码登录（2026-10-10 攻克，可完全自动化）**：H5 营销签到（`wxapi.csair.com/marketing-tools`）已不依赖小程序 sessionId。只需在 `csair_config.json` 填 `h5_account`/`h5_password`（南航官网/APP 的手机号+密码），脚本会用 Playwright 真实浏览器自动完成「过阿里云 WAF 挑战 → 登录 → 导出 TOKEN」全流程，token 缓存于 `csair_h5_auth.json`，失效（`S00011`）时自动重登刷新。
>
> - WAF 挑战机制：登录接口 `POST m.csair.com/CSMBP/.../ffpUser/login` 被阿里云 WAF 拦截，返回 110KB 挑战页（`renderData` + 混淆 VM 脚本）。**浏览器页面导航会自动执行挑战并放行**，但 **Thorium 不行**（其本地 favicon 服务 `http://127.0.0.1:<port>/favicon.png` 是指纹，挑战无限循环）——必须用 **Playwright 自带 Chromium**。
> - 登录接口请求体经 desStr（DES 变体，key `0979ebb`）加密，响应可能经 SM4-CBC 加密；走真实浏览器表单提交可全部绕开。
> - `signin` 子命令已集成：H5 token 优先，失效自动账号密码重登（headless 可用，约 30s）；无账号密码时回退小程序 token。
> - 手动刷新：`python scripts/csair_signin.py h5login [--headless]`。
>
> 注意：小程序「发现新境」签到（foundZone）仍只能用 sessionId，无法自动续期；H5 营销签到（金币/里程）已全自动。

**★签到抽奖（2026-10-11 抓包+逆向定案，半自动）**：天天签到（活动 308）连续签满足档位后，会生成一条 `awardType=lotteryAward` 的「抽奖机会」记录，脚本 `getAward` 领取（`awardStatus` 变 `received`）后抽奖资格即激活，实际**消耗**在小程序页 `/page/jump?action=milesEarn&MEID=<lotteryId>`。

- **抽奖消耗接口**：`POST /wxopen/activity/api/mileagegift/draw?sp=<固定常量>&appid=..&wxchannel=wxopen&envVersion=release`，请求头带 `sessionid`/`memberNo-encrypt`，请求体 `{randomId:lotteryId, memberNo:<isLogin返回的cardNo密文>, signInGiftId:awardId, signInActivityId:活动id, rewardId:记录id, signInFlag:1}`。`sp` 为主包 `ApiReq` 里 `isAliWaf` 硬编码常量（非动态签名）；抓包 URL 上的 `u_atoken/u_asig/u_aref=wxCaptcha` 是当次阿里云滑块票据，非必需。
- **★关键卡点**：抽奖消耗接口和「发现新境」签到一样**绑定小程序 sessionId**（路径前缀 `/wxopen/`），与 H5 营销签到的 token 体系（`/marketing-tools/`，Playwright 可自动续）不通用。因此**抽奖无法全自动**——sessionId 寿命仅数小时、无服务端刷新接口。
- **脚本行为**：`signin` 末尾自动查 lotteryAward 机会（查询走 H5 marketing-tools，无需 sessionId）：
  - sessionId 有效 → 逐个 `draw` 消耗并按 `rewardId` 记 state（幂等），打印「中奖」；
  - sessionId 失效 → 打印「有 N 个抽奖机会待抽，但小程序 sessionId 不可用」，汇总里提醒重抓。
- **手动抽奖**：抓到**新鲜**的 `/mini/api/login/login` 响应后 `refresh` 更新 sessionId，再跑 `draw` 子命令。sessionId 过期约 30 分钟即 `W00000`，需现抓现用。

---

### 3) 办公小浣熊（商汤 xiaohuanxiong.com）

**没有手动签到/领取接口**——个人免费版每日送 300 积分是"会话活跃自动入账"，脚本每天访问一次积分余额接口即触发/确认发放。

需要抓两样（浏览器 F12 → Network）：
1. 任意一条 `https://xiaohuanxiong.com/api/web/...` 请求的 **Authorization 头**（`Bearer eyJ...`，即 accessToken，寿命仅 3 小时）；
2. **refresh_token**（关键，长期自动续期的唯一凭据）：退出登录再重新登录一次，在 Network 里抓 `POST /api/web/auth/v1/refresh` 的**请求体**里那个 `refresh_token` 字段值；或者关掉浏览器后我从本地 cookie（`raccoon_refresh_token`）里挖。

**发给我这两个值**，我用 `init` 落盘。之后 accessToken 每次运行前自动用 refresh_token 换新（refresh_token 用一次轮换一次，脚本自存）。不配 refresh_token 的话 3 小时后失效，需重抓。

---

### 4) Loomy（讯飞 loomy.xunfei.cn）

同样**没有签到/领取接口**——每日赠送积分随站点活跃自动入账，脚本每天查一次积分即确认。

纯 Cookie 鉴权（讯飞统一登录，无独立续期接口）。抓取方法：浏览器登录 Loomy → F12 → Network → 任意一条 `/api/` 请求 → **复制整行 Cookie 请求头**发我，我用 `init` 落盘。cookie 失效回 401 时汇总会标注【Loomy失效】，重抓一条即可。

---

## 二、我来自动完成

收到你的整条请求后，我会：
1. 解析其中的凭证字段（token / openId / sessionid 等）；
2. 在 `scripts/` 下生成对应 json 配置（`gr_config.json` / `mt_config.json` / `csair_config.json`）；
3. 立即跑一次验证（查状态 / 试签到 / 试领券），把结果贴给你确认；
4. 确认通过后按你的要求挂上 WorkBuddy 定时任务（如每天清晨自动执行）。

脚本自带幂等：当天已完成会自动跳过，删除对应 `*_state.json` 可重跑。

**每日自动覆盖范围**：
- 美团：福利社券包领取、营销页红包（配了 recallToken 才有）、福利社 H5 活动页（限时抢券 + 天降掉券，活动 ID 自动发现）
- 南航：发现新境签到、营销活动签到领里程（活动 ID 动态探测，过期活动自动跳过）、签到抽奖机会检测与消耗（消耗需新鲜小程序 sessionId，半自动）
- 魔搭：登录魔粒 +250（会话副作用，访问首页自动入账）+ 点赞刷分 +40（star/unstar 循环 20 次）
- WorkBuddy：Buddy 加油站签到 +100/天（连续 7/14/28 天有额外档）+ 派猫猫旅行闭环（先领后派，5~10/天）
- 办公小浣熊：每日 300 积分确认（活跃自动入账）；accessToken 临期自动用 refresh_token 换新
- Loomy：每日积分确认（活跃自动入账）；纯 cookie 鉴权，失效需重抓

---

## 三、排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 南航 `invalid session` / 业务失败 | 凭证过期 | 南航：先跑 `csair_signin.py doctor` 探活；sessionId 只能由小程序内 `wx.login` 换取（无服务端刷新接口），抓 `/mini/api/login/login` **响应体**发我用 `refresh` 更新；GR：重抓签到请求发我重建 |
| 美团 `mtgsig` 失败/被风控 | 抓包设备版本与脚本不符、Node 未装 | 设 `MT_NODE`；把抓包整条发我适配 |
| 美团 H5 页"未登录" | wm_logintoken 过期 | 重抓一条 `listActivityCoupon` 发我，H5 脚本与主领券共用同一 token |
| 美团限时抢总提示"活动太火爆" | 该场次库存=0（秒杀券库存个位数，被别人抢了）或当日已领（subCode 9017） | 属正常，脚本每日新场次自动重试；想抢到需在场次开始（10:00/11:00/17:00）第一时间跑 |
| 美团"百元券包"没自动领 | 天降掉券每日只有 1 次机会，当天已领过则返回"次数已消耗光"；百元券包主力其实是**跨券墙**（页面可同时挂多个，"周末加码"那档面值最大） | 查 `mt_gundam_state.json` 或跑 `mt_gundam_coupon.py status` 看已领记录 |
| 美团跨券墙 fetch 返回 `subcode:12 活动太火爆` | 风控：未带 info 接口下发的 `ta.uuid`/`iuuid` cookie | 已修复——脚本用 cookie jar 先 info 收 cookie 再 fetch；若仍失败说明该活动风控更严或该账号被限 |
| 南航营销签到 `S0023 奖品状态不正确` | 历史过期活动的残留记录 | 忽略（脚本已标跳过） |
| 美团营销页红包总跳过 | 未抓包营销页 | 抓一次 `realTimeMarketingSendCoupon` 发我 |

> 提示：token 都有有效期，长期不用需重新抓包。**不要在对话里粘贴明文 Cookie 口令**——若抓包工具能复制脱敏请求最理想；敏感值请本地处理。拿不准时先把抓包请求发我看看再跑，避免被风控。

---

## 四、导出脚本自用（可选）

如果你想脱离对话、自己在本地或服务器上跑，命令如下。**注意**：配置 json 需与脚本放在同一目录，Node 路径可用 `MT_NODE` 环境变量指定。

```bash

# 美团：领券（幂等）
python scripts/mt_api_coupon.py claim
python scripts/mt_api_coupon.py market # 仅营销页红包
python scripts/mt_api_coupon.py dryrun # 验证签名+请求体（不发网络）
python scripts/mt_gundam_coupon.py     # 福利社 H5 活动页（限时抢+天降，幂等）
python scripts/mt_gundam_coupon.py status  # 查 H5 活动页领取记录

# 南航：签到（幂等）
python scripts/csair_signin.py signin
python scripts/csair_signin.py status
python scripts/csair_signin.py doctor    # 凭证探活（sessionId / H5 signToken 逐一检查）


```

挂定时任务（如每天 08:30 依次跑四条），脚本自带幂等，当天完成后自动跳过；删除对应 `*_state.json` 可重跑。


