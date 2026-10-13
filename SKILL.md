---
name: 签到啦
slug: signin-skill
displayName: 签到啦
description: 一站式签到/领券综合工具，整合13个已抓包验证的自动化入口：美团惠省小程序首页红包墙每日领券+营销页红包+分销会场券包、南航（中国南方航空小程序）双链路签到+签到抽奖、魔搭 ModelScope 每日魔粒、WorkBuddy 积分签到+派猫猫旅行、办公小浣熊（商汤 xiaohuanxiong）每日积分、Loomy（讯飞）每日积分、天翼189云盘每日签到领空间、京东京豆每日签到+互动中心天天抽奖（做任务赚抽奖机会→转盘抽奖）、阿里云盘每日签到（浏览器已登录即全自动，脚本直接读本机 Local Storage，无需抓包）。纯接口自动化（非 UI 点击），支持幂等与定时任务。当用户要求"签到"、"领券"、"打卡"、"每天签到"、"美团领券"、"美团红包墙"、"惠省领券"、"南航签到"、"魔搭魔粒"、"WorkBuddy积分"、"小浣熊积分"、"Loomy积分"、"天翼云盘"、"京东京豆"、"京东抽奖"、"阿里云盘"、"阿里网盘"、或提及这些平台时使用。配置只需抓 1 条请求发给我即可，方法见 SKILL.md。
---

# 签到啦 · 一键签到/领券合集

整合十三**已抓包验证**的自动化入口，全部纯接口实现，自带幂等（当天不重复执行）与状态文件。各平台按需运行对应脚本，命令见「四、导出脚本自用」。

| 平台 | 脚本 | 作用 | 依赖 |
|---|---|---|---|
| 南航（中国南方航空小程序） | `scripts/csair_signin.py` | 发现新境签到 + 营销签到领里程 + 签到抽奖机会检测（抽奖消耗半自动） | Python 标准库（H5 重登需 Playwright） |
| 美团券包（惠省小程序首页红包墙） | `scripts/mt_api_coupon.py` | 每日领券 + 营销页红包（可选）。★2026-10-12 起：列表体改 JSON、幂等改 **rightCode 级**（当天后出现的新批次也能领到）、新增 `probe`/`share` 子命令 | Python + Node（mtgsig 签名沙箱） |
| 美团福利社 H5 活动页 | `scripts/mt_gundam_coupon.py` | 福利社 tab 的 gundam 活动页（"周末加码必得百元券包"）：跨券墙(百元券包主力) + 限时抢券 + 天降掉券，全自动发现活动 ID | Python + Node |
| 美团分销会场 | `scripts/mt_union_coupon.py` | 「美团分销小程序」分销会场每日券包（list→grant 链路）+ 分销中心内嵌跨券墙，单日 ¥180+ | Python + Node（H5 签名） |
| 魔搭（ModelScope） | `scripts/ms_magicube.py` | 每日登录魔粒 +250 + 点赞刷分 +40（会话副作用 + star/unstar 循环） | Python 标准库 |
| WorkBuddy 积分 | `scripts/wb_score.py` | Buddy 加油站签到 +100/天 + 派猫猫旅行闭环（先领后派，5~10/天） | Python 标准库（底层调 totorosir-workbuddy-score skill） |
| WorkBuddy 成长中心 | `scripts/wb_growth.py` | 补齐成长中心 6 项奖励：盲盒抽奖 / 连登三档兑换 / 断登补签 / 接任务 / 领任务奖 / 能量开 Buddy 盲盒（先只读判有无资源→没有跳过、有就补齐，全幂等；凭证复用 totorosir 三通道，无需额外配置） | Python 标准库（复用 totorosir skill 取凭据） |
| 办公小浣熊（商汤 xiaohuanxiong） | `scripts/xhx_office_points.py` | 每日积分确认（免费版每日送 300，会话活跃自动入账；refresh_token 自动续 accessToken） | Python 标准库 |
| Loomy（讯飞 loomy.xunfei.cn） | `scripts/loomy_points.py` | 每日积分确认（站点活跃自动入账，纯 cookie 鉴权） | Python 标准库 |
| Loomy 桌面端（Electron 客户端，账号体系独立） | `scripts/loomy_desktop_tasks.py` | 新手任务 8 项共 10000 分（客户端专属；自动读本机登录态 token 头鉴权，换号=桌面端重登一次；每日检测，未完成自动补齐、满额零副作用跳过） | Python 标准库 |
| 天翼云盘（cloud.189.cn） | `scripts/c189_signin.py` | 每日个人签到领随机空间（SSON 登录 cookie → getSessionForPC 换 sessionKey → `/mkt/userSign.action`；幂等，isSign=true 时零副作用） | Python 标准库 |
| 京东京豆 | `scripts/jd_web_signin.py` | 每日京豆签到（Web 端 `pc_interact_sign_execute`，+N 京豆/日，连签有加成）+ **互动中心天天抽奖**（`interact` 子命令：做任务赚抽奖机会→转盘抽奖，红包/优惠券/京豆；幂等，已签/已抽跳过） | Python + Node（京东官方 js_security_v3 签名器沙箱） |
| 阿里云盘（www.aliyundrive.com） | `scripts/aliyun_signin.py` | 每日签到。★凭证在浏览器 **Local Storage**（Cookies 库被独占锁，但 leveldb 可读）；★按**值**搜索 `"refresh_token":"<32位hex>"` 再扩 JSON；refresh 不使旧 token 失效→不踢浏览器 | Python 标准库 |

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

> **分销会场（"美团分销"小程序的会场券包）**：脚本 `mt_union_coupon.py`。链路 `listActivityCoupon/distributionVenue`（拉当日券列表 + recallToken）→ `grantActivityCoupon/distributionVenue`（H5 签名领取）。**复用同一条福利社抓包的 wm_logintoken 即可，无需额外抓包**（分销接口认账号级 token）。若想顺带领分销中心内嵌的跨券墙，需在 `scripts/mt_union_config.json` 配 `gdId/pageId/activityViewId/instanceId`（从分销中心页抓包取），不配则自动跳过。
>
> 关键点：① grant 必须用 **H5 签名**（`yodaReady=h5&csecplatform=4`），小程序签名会被拒 `code:30001`；② `recallToken` 含时间戳、时效极短，每次必须现拉列表，不能复用存盘响应；③ 幂等按 rightCode 记录（grant 返回 code:200 即视为该批已处理，含互斥未发放的券），新批次 rightCode 变化时自动跟进。

> **★惠省小程序首页「红包墙」（2026-10-12 补充定案）**：就是上面「美团券包」覆盖的活动，`activityName=惠省红包墙活动配置`、`activityCode=101357000`，路径 `fulishemini/couponActivity/listActivityCoupon|grantActivityCoupon`（**无** `/distributionVenue` 中缀，签名用小程序 mp 签名 `csecplatform=3`）。三个容易踩的点：
> 1. **`couponViewId` 是"是否已在卡包"的权威判据**：`couponViewId==null` = 可领；带值 = 已拥有，别再发。★注意本端点 `status` 语义与分销会场**相反**（这里 `status==1` 才是可领，实测 21/21、22/22 完全相关），但那只是一种巧合对齐、不是服务端契约——**勿照搬分销会场的 `status==0` 过滤**，也不要把 `status==1` 当硬条件，否则服务端一旦省略/改动 status 就会漏券。误发已拥有券由服务端幂等兜底（grant 照样回 code:200、不再发放）。
> 2. **幂等必须是 rightCode 级，不能是日级**：红包墙当天会刷新批次（实测 `totalCouponValue` 从 ¥222 涨到 ¥412），日级标记（`state[今天]=="done"` 整日跳过）会把后出现的新批次全部挡掉，表现为"当天的活动没领"。已改为按 grant 实际发送过的 rightCode 记录，只领新出现的券；旧日级状态自动迁移。
> 3. **`querySharePopWindow`（分享弹窗查询）是只读空操作**：form 体 + `scene=1`，实测返回 `{"code":0,"data":null}` = 无弹窗、无待领分享奖励。用 `python scripts/mt_api_coupon.py share` 可随时复查；哪天真返回非 null data，再按其中的分享任务补实现。
>
> 诊断"今天怎么没领"的标准动作：`python scripts/mt_api_coupon.py probe`（只拉列表不领取）→ 看「可领 N / 已在卡包 M」两个数。可领=0 即已领完（不是失效）；可领>0 而本地已记录该 rightCode，才是幂等记录异常。

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

**桌面端（Electron 客户端，账号体系独立）**：`scripts/loomy_desktop_tasks.py` 完成新手任务（8 项共 10000 分，客户端专属，web 端无此任务接口）。登录态自动从本机 `<本机路径>` 读取（`token` 头鉴权，32 位讯飞 passport session，与 web cookie 不同载体、无需配置）。**每个账号需在桌面端登录一次后跑 `run` 领取**（换号=桌面端重登，脚本自动识别）；session 寿命 14 天固定无续期。生产接口 host 固定 `loomyad.xunfei.cn`（客户端本机残留测试地址会全程 100002，脚本已规避）。用法：`status` 查进度 / `run` 补齐未完成项（服务端幂等）。2026-10-12 两个账号均已满额。**已纳入每日总控任务第【12】步**：每天跑 `run` 做「检测+未完成自动补齐」——满额时零副作用跳过，服务端新增任务或换登录账号时自动跟进入账；100002（约每 14 天 session 到期）标注【Loomy桌面登录失效】提醒在桌面端重登一次即恢复。

### 5) 天翼云盘（cloud.189.cn）

浏览器登录 [cloud.189.cn](https://cloud.189.cn) 后，把**任意一条 cloud.189.cn 请求的整行 Cookie** 发我（或直接告诉我"浏览器已登录天翼189"，我用 CDP 自动抓，无需手抓）。核心凭证是 `SSON`（httpOnly 单点登录 cookie），脚本链路：`SSON → unifyLoginForPC（收服务端会话 cookie）→ POST api.cloud.189.cn/getSessionForPC.action 换 sessionKey/accessToken/refreshToken → GET /mkt/userSign.action?sessionKey=...` 签到领随机空间。

- 每日个人签到：随机 +几 MB ~ 几十 MB 空间（实测 2026-10-12 +26MB，服务端 totalSize 对账一致）；`isSign=true` 时当天重复跑零副作用
- 凭证寿命：accessToken/refreshToken 由 getSessionForPC 下发（sdk 标称 7 天），SSON 本身长期有效；配置存 `c189_config.json`（sson / accessToken / refreshToken / sessionKey / loginName）
- 失效表现：`getSessionForPC` 返回非 0 res_code 或 HTTP 400 → 标注【天翼189失效】，重抓一条 SSON cookie 即可

---

### 6) 京东京豆（Web 端，2026-10-12 自行逆向）

**无需扫码、无需抓包**：直接用 Thorium 浏览器里已登录的京东 PC 账号（`.jd.com` 域 cookie）。
脚本每次运行都从浏览器磁盘 Cookies 库**实时提取最新 cookie**，所以只要浏览器里京东是登录态，签到就全自动。

- 页面：`https://bean.jd.com/myJingBean/list`（SPA；老的 `/bean/index`、`/bean/signIndex.action` 已 404 下线）
- 查询：`GET api.m.jd.com/?functionId=pc_interact_sign_query&type=1` → 拿 `eaId`/`activityId`/连签天数/今日是否已签
- 签到：`POST api.m.jd.com/` `functionId=pc_interact_sign_execute`，业务体 `{type:5, eaId, itemId:"1", extraType:"sign"}`
- 挂载任务：`POST` 同接口 `{type:0, eaId:"task"}`（幂等，可能送豆）
- 奖励解析：`assignmentRewardInfo.jingDouRewards[].quantity` 求和 = 京豆数

**签名（h5st）是自己逆向还原的，未用任何第三方仓库实现**：
- 页面 `global.js`（gzip 伪装）解出 `window.MYBEAN` → APPID `73c2f` → 签到主包 `index-legacy-BldL61M_.js`
- 该包内请求构造器：`u={appid:"asset-h5",clientVersion:"1.0.0",client:"pc",t:Date.now(),body:window.SHA256(JSON.stringify(业务体)),functionId}` → `window.PSign.sign(u)`
- `PSign` = 页面里 `new ParamsSign({appId:'73c2f',...})`，签名器本体是 `js_security_v3_0.1.4.js`（gzip 78KB → 235KB，`_4vve5` XOR-5 字符串层 + 三层字节码 VM）
- **实现方式**：不重写算法，直接在下发的官方签名器外套一层 Node 沙箱 + 最小 DOM shim（`_jd_node_harness.js`）运行它，输出与浏览器逐位同构（10 段分号 h5st）
- 三件套参数全部由本地 cookie 构造：`uuid`=`__jda` 第二段、`area`=`ipLoc-djd`（`-`→`_`）、`x-api-eid-token`=cookie `3AB9D23F7A4B3CSS`（本身就是 `jdd03...` 开头）
- ⚠️ Node 沙箱坑：**不要把 JS 内置对象（Object/Array/RegExp/Date...）传进 vm context**，否则 vm realm 的正则字面量与外部 `RegExp.$1` 错位，h5st 首段时间戳会退化成字面量 `yyyy`

- 失效判定：`{"code":"3"}` = 请先登录 → 标注【京东登录失效】，去浏览器重新登录 jd.com 即可（下次运行自动读新 cookie）
- 幂等：`errCode:302 任务已完成`；已签判定 = `assignment.completionFlag` / `signDetail.status==2` / 今日日期在 `signList`

#### 9b) 互动中心「天天抽奖」转盘（2026-10-12 自行逆向，已实测抽中 6 元红包）

京东首页宝箱入口 → `https://interact.jd.com/`（标题「我的京东-互动中心」）。**与京豆是两套 appid，切勿混用**：

| | 京豆签到 | 互动中心 |
|---|---|---|
| 请求参数 appid | `asset-h5` | **`pc_interact_center`** |
| PSign appId（h5st 第3段） | `73c2f` | **`9a92f`** |
| Referer | bean.jd.com | interact.jd.com |

接口链路（前端包 `storage.360buyimg.com/channel2022/jd-interactive-center/index-legacy-*.js` 还原）：
- 奖励查询 `GET pc_interact_reward_query` body `{type:0, rk:false}` → `data.{total,used,usable}`（usable=可抽奖次数）
- 任务列表 `GET pc_interact_assign_query` body `{type:1}` → `data.assignmentInfoList[]`（id/type/extraType/completionFlag/signDetail/productList/...）
- 抽奖信息 `GET pc_interact_assign_query` body `{type:0}` → `data.lotteryDrawInfo` / `initCompletionInfo`
- 做任务 `POST pc_interact_assign_execute` body `{eaId, type, itemId, extraType, rk, actionType}` → `data.assignmentRewardInfo.virtualPointReward.quantity`（抽奖机会+N）
- 抽奖 `POST pc_interact_assign_execute` body `{rk:false, eaId, type:30}` → `data.assignmentRewardInfo.couponRewards[]`（红包/优惠券，quota/usageThreshold/useTimeRange）

自动化的任务范围：`sign`/`followShop`/`productsInfo`/`shoppingActivity`（浏览类 actionType=0，其余=1）；**`order`（需真实下单）跳过**。itemId 复刻前端 `x(task)`：signDetail→productList/activityChannelList/shopList 取 status=1→orderDetail，兜底 "1"。

★★ **WAF 按端点频率限制（实测同一端点连打即 HTTP 403 空响应，且与 thor/eid 会话绑定、可持续 40 分钟以上）**——已内置 4s 节流 + 403 优雅降级（不中断、不重试轰炸，换端点或等次日）。每日任务每次重新提取浏览器 cookie = 新会话 = 天然规避。eaId 缓存 `jd_interact_state.json`，任务列表被限流时用缓存/内置签到任务兜底。

---

### 10) 阿里云盘（www.aliyundrive.com，2026-10-12 建成）

**无需抓包、无需 CDP、无需关浏览器**：凭证在浏览器 **Local Storage** 里，脚本直接读磁盘。

- ★关键机制：Chromium 的 **Cookies 库被运行中的浏览器独占锁**（26 次重试也读不出），但 **Local Storage 的 `.ldb`/`.log` 不被锁**，随时可读 → 这是阿里云盘能全自动的原因
- ★★leveldb 坑：完整 key（`<origin>\x00\x01<keyname>`）因**前缀压缩**在 `.ldb` 里不一定连续出现，按 key 正则搜索会 **0 命中** → 改为**按值搜索**：搜 `"refresh_token":"<32位hex>"` 指纹，再用括号配对向两侧扩出完整 token JSON
- ★refresh_token **不会因刷新而失效**（2026-10-12 实测：同一代连刷两次、两代并存均 200）→ 与浏览器 Web 端**不互斥**，不会把浏览器踢下线
- 链路：refresh_token → `POST auth.aliyundrive.com/v2/account/token`（`grant_type=refresh_token`）换 access_token（7200s）→ `POST member.aliyundrive.com/v1/activity/sign_in_list`（body `{"_rx-s":"mobile"}`，Bearer 鉴权）**兼做签到与查状态**
- ★★`signInLogs` 判读坑：`calendarMonth` 是**中文**（`"十月"`）、`calendarDay` 是**字符串**（`"12"`）——直接 `int()` 会全军覆没；且"今天未签"也会出现在 logs 里（`status:"miss"`），必须同时排除 miss
- 已知限制：领奖端点 `sign_in_reward` 被客户端版本门控返回 **403「请升级最新客户端访问」**。签到本身不受影响，仅在 `isReward=true` 时尝试；403 记为受限、不算失败

---

## 二、我来自动完成

收到你的整条请求后，我会：
1. 解析其中的凭证字段（token / openId / sessionid 等）；
2. 在 `scripts/` 下生成对应 json 配置（`gr_config.json` / `mt_config.json` / `csair_config.json`）；
3. 立即跑一次验证（查状态 / 试签到 / 试领券），把结果贴给你确认；
4. 确认通过后按你的要求挂上 WorkBuddy 定时任务（如每天清晨自动执行）。

脚本自带幂等：当天已完成会自动跳过，删除对应 `*_state.json` 可重跑。



**每日自动覆盖范围**：
- 美团：惠省小程序首页红包墙领券（`couponViewId` 判可领、rightCode 级幂等，当天后出现的新批次也能领到）+ 营销页红包（配了 recallToken 才有）+ 福利社 H5 活动页（限时抢券 + 天降掉券，活动 ID 自动发现）+ 分销会场每日券包（grant 链路，单日 ¥180+）+ 分销中心跨券墙
- 南航：发现新境签到、营销活动签到领里程（活动 ID 动态探测，过期活动自动跳过）、签到抽奖机会检测与消耗（消耗需新鲜小程序 sessionId，半自动）
- 魔搭：登录魔粒 +250（会话副作用，访问首页自动入账）+ 点赞刷分 +40（star/unstar 循环 20 次）
- WorkBuddy：Buddy 加油站签到 +100/天（连续 7/14/28 天有额外档）+ 派猫猫旅行闭环（先领后派，5~10/天）+ **成长中心 6 项补齐**（`wb_growth.py`：盲盒抽奖 / 连登三档兑换 / 断登补签 / 接任务 / 领任务奖 / 能量开 Buddy 盲盒，先只读判有无资源、没有就跳过，全幂等；第 2 个子步骤）
- 办公小浣熊：每日 300 积分确认（活跃自动入账）；accessToken 临期自动用 refresh_token 换新
- Loomy：每日积分确认（活跃自动入账）；纯 cookie 鉴权，失效需重抓。桌面端新手任务线（`loomy_desktop_tasks.py`，8 项共 10000 分，账号体系独立）每日检测——未完成自动补齐、满额零副作用跳过、session 到期（14 天）标注【Loomy桌面登录失效】提醒重登
- 天翼189云盘：每日个人签到领随机空间（`c189_signin.py`，实测 +26MB/天；SSON cookie 鉴权，sessionKey 由 getSessionForPC 换取；幂等，当天重复跑零副作用）
- 京东京豆：每日京豆签到（`jd_web_signin.py auto`，+N 京豆/日 + 连签加成；浏览器 PC 登录态，脚本实时提取 cookie；幂等，已签跳过）+ **互动中心天天抽奖**（`jd_web_signin.py interact`：查抽奖机会→转盘抽奖→做任务（签到/关注店铺/浏览商品/浏览活动，下单类跳过）赚机会→再抽；红包/优惠券/京豆落袋；第 2 个子步骤）
- 阿里云盘：每日签到（`aliyun_signin.py auto`；凭证从浏览器 Local Storage 实时提取，无需 cookie/CDP；`sign_in_list` 兼做签到与查状态，幂等）

---

## 三、排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 南航 `invalid session` / 业务失败 | 凭证过期 | 南航：先跑 `csair_signin.py doctor` 探活；sessionId 只能由小程序内 `wx.login` 换取（无服务端刷新接口），抓 `/mini/api/login/login` **响应体**发我用 `refresh` 更新 |
| 美团 `mtgsig` 失败/被风控 | 抓包设备版本与脚本不符、Node 未装 | 设 `MT_NODE`；把抓包整条发我适配 |
| 美团 H5 页"未登录" | wm_logintoken 过期 | 重抓一条 `listActivityCoupon` 发我，H5 脚本与主领券共用同一 token |
| 美团限时抢总提示"活动太火爆" | 该场次库存=0（秒杀券库存个位数，被别人抢了）或当日已领（subCode 9017） | 属正常，脚本每日新场次自动重试；想抢到需在场次开始（10:00/11:00/17:00）第一时间跑 |
| 美团"百元券包"没自动领 | 天降掉券每日只有 1 次机会，当天已领过则返回"次数已消耗光"；百元券包主力其实是**跨券墙**（页面可同时挂多个，"周末加码"那档面值最大） | 查 `mt_gundam_state.json` 或跑 `mt_gundam_coupon.py status` 看已领记录 |
| 美团跨券墙 fetch 返回 `subcode:12 活动太火爆` | 风控：未带 info 接口下发的 `ta.uuid`/`iuuid` cookie | 已修复——脚本用 cookie jar 先 info 收 cookie 再 fetch；若仍失败说明该活动风控更严或该账号被限 |
| 南航营销签到 `S0023 奖品状态不正确` | 历史过期活动的残留记录 | 忽略（脚本已标跳过） |
| 美团营销页红包总跳过 | 未抓包营销页 | 抓一次 `realTimeMarketingSendCoupon` 发我 |
| ★美团惠省红包墙「今天的活动没领」 | 两种可能：① **其实已领完**（跑 `mt_api_coupon.py probe` 看「可领 N / 已在卡包 M」，可领=0 即领完，曾在 00:58 手动跑过并标记过当日）；② 旧版**日级幂等**把当天后出现的新批次挡掉了（红包墙当天会刷新，实测墙总额 ¥222→¥412） | 已修复为 rightCode 级幂等（2026-10-12），只领新出现的券；仍异常就跑 `probe` 对比「可领数」与 `mt_claim_state.json` 里当日 `granted_rc` 数量 |
| 美团惠省红包墙 probe 显示「可领 0 / 已在卡包 38」但记得没领过 | 之前某次运行（含手动测试）已领，`couponViewId` 有值即代表在卡包 | 正常；想核对去美团小程序「我的→红包/卡包」按日期看 |
| 美团 `querySharePopWindow` 返回 `data:null` | 无分享弹窗、无待领分享奖励 | 正常空操作；哪天真返回非 null data 再补分享任务实现 |
| 京东签到 `code:3` 请先登录 | 浏览器里京东登录态失效/被服务端轮换（`order.jd.com` 也会退回欢迎登录页） | 在 Thorium 里打开 jd.com 重新登录；脚本下次运行自动读新 cookie，无需改配置 |
| 京东签到 `DG-9999 系统异常` | 走的是**已下线的旧接口** `signBeanIndex`（App 端链路，2026-10-12 起不可用） | 改用 Web 端 `jd_web_signin.py`（`pc_interact_sign_execute`）；旧 `jd_signin.py`/`jd_login.py` 已废弃 |
| 京东互动中心接口返回 HTTP 403（空 body） | WAF 按端点频率限制（与 thor/eid 会话绑定，可持续 40 分钟以上） | 脚本已内置 4s 节流 + 403 优雅降级（不中断）；当日勿再手动连打同端点，等次日任务自动换新 cookie 会话即恢复 |
| 京东互动中心 `code:3` 请先登录 | 浏览器京东登录态失效/被轮换 | 同签到：Thorium 重新登录 jd.com，下次运行自动读新 cookie |
| 阿里云盘「今日已签」却记成首次 | `signInLogs` 的中文月份/字符串日解析失败会判不到今日 | 已修（`_cn2int` 支持「十月」/"12"）；核对用 `aliyun_signin.py status` |

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
python scripts/mt_union_coupon.py         # 分销会场券包 + 分销中心跨券墙（幂等）
python scripts/mt_union_coupon.py probe   # 只拉列表看可领券，不领取
python scripts/mt_union_coupon.py status  # 查领取记录

# 美团惠省红包墙（首页领券）：领券 / 只读诊断 / 分享弹窗只读复查
python scripts/mt_api_coupon.py claim     # 领券（rightCode 级幂等）
python scripts/mt_api_coupon.py probe     # 只拉列表看「可领 N / 已在卡包 M」，不领取
python scripts/mt_api_coupon.py share     # 只读查分享弹窗（data=null = 无待领分享奖励）
python scripts/mt_api_coupon.py status    # 查领取记录（rightCode 累计 + 墙总额）

# 南航：签到（幂等）
python scripts/csair_signin.py signin
python scripts/csair_signin.py status
python scripts/csair_signin.py doctor    # 凭证探活（sessionId / H5 signToken 逐一检查）


# 利宝推荐有礼（转介绍活动，复用 libao_config.json，非每日必做，可随时查进度/尝试领取）


# 魔搭：登录魔粒 + 点赞刷分（auto=全部 290/日；需 ms_config.json 整行 cookie）
python scripts/ms_magicube.py auto
python scripts/ms_magicube.py status

# WorkBuddy：签到 + 派猫猫旅行（auto=全部；凭证走本地 atrest.key 解密）
python scripts/wb_score.py auto
python scripts/wb_score.py status

# WorkBuddy 成长中心：补齐 6 项奖励（盲盒/连登兑换/断登补签/接任务/领任务奖/能量开Buddy）
# 先只读判有无可领资源→没有就跳过、有就补齐，全幂等；凭证复用 totorosir skill 三通道
python scripts/wb_growth.py auto           # 补齐全部成长中心可领项（定时任务用这个）
python scripts/wb_growth.py status         # 只读播报 6 项可领/可补/可兑状态（不发写请求）
python scripts/wb_growth.py probe          # 逐接口连通/数据探测（调试）

# 办公小浣熊：每日积分确认（auto=refresh+查余额；refresh_token 自动轮换回存）
python scripts/xhx_office_points.py auto
python scripts/xhx_office_points.py status

python scripts/loomy_points.py auto
python scripts/loomy_points.py status

# Loomy 桌面端：新手任务（账号体系独立；桌面端登录哪个账号就领哪个）
python scripts/loomy_desktop_tasks.py status          # 查身份与 8 项进度
python scripts/loomy_desktop_tasks.py run             # 补齐全部未完成项（服务端幂等）
python scripts/loomy_desktop_tasks.py probe           # 只测连通/鉴权

# 天翼189云盘：每日签到领随机空间（SSON cookie 鉴权；auto=签到+容量播报）
python scripts/c189_signin.py auto                    # 签到 + 容量变化播报（定时任务用这个）
python scripts/c189_signin.py status                  # 只读：容量/登录态
python scripts/c189_signin.py init "<整行cookie或SSON值>"   # 落盘凭证并立即校验

# 京东京豆（Web 端，浏览器 PC 登录态，脚本自动提取 cookie）
python scripts/jd_web_signin.py cookie                # 手动重提取浏览器京东 cookie → jd_web_config.json
python scripts/jd_web_signin.py auto                  # 京豆签到：查询→未签到则签到 + JSON 结果（定时任务用这个）
python scripts/jd_web_signin.py status                # 只读：今日是否已签/连签天数
python scripts/jd_web_signin.py sign                  # 强制签到（调试用）
python scripts/jd_web_signin.py interact              # 互动中心：抽奖机会→抽奖→做任务赚机会→再抽（定时任务用这个）
python scripts/jd_web_signin.py interact_status       # 只读：抽奖机会 + 任务完成情况

# 阿里云盘（浏览器登录 www.aliyundrive.com，脚本读 Local Storage，无需 cookie）
python scripts/aliyun_signin.py auto                   # 签到 + 判读今日记录（定时任务用这个）
python scripts/aliyun_signin.py status                 # 只读：累计天数/今日是否已签
python scripts/aliyun_signin.py probe                  # 探凭证来源 + 原始签到响应
python scripts/aliyun_signin.py init <32位refresh_token>  # 手动兜底；init auto = 强制从浏览器重提

# 凭证同步：魔搭/小浣熊/Loomy 轮换制凭证从浏览器自动取新写回（每日任务第 0 步）
# 阿里云盘不走 cookie（凭证在 Local Storage），不在此列
```

挂定时任务（如每天 08:30 依次跑四条），脚本自带幂等，当天完成后自动跳过；删除对应 `*_state.json` 可重跑。


