---
name: qiandao-la
slug: signin-skill
displayName: 签到啦
description: 一站式签到/领券综合工具，整合19个已抓包验证的自动化入口：美团惠省小程序首页红包墙每日领券+营销页红包+分销会场券包、南航（中国南方航空小程序）双链路签到+签到抽奖、魔搭 ModelScope 每日魔粒、WorkBuddy 积分签到+派猫猫旅行、办公小浣熊（商汤 xiaohuanxiong）每日积分、Loomy（讯飞）每日积分、天翼189云盘每日签到领空间、京东京豆每日签到+互动中心天天抽奖（做任务赚抽奖机会→转盘抽奖）、阿里云盘每日签到（浏览器已登录即全自动，脚本直接读本机 Local Storage，无需抓包）、美团答题领现金、小米商城米金+有品红包签到、千问办公每日100积分、华为码道每日签到1000积分、Qoder CN 每日100 Credits（免抓包，桌面端凭证自解密）。纯接口自动化（非 UI 点击），支持幂等与定时任务。当用户要求"签到"、"领券"、"打卡"、"每天签到"、"美团领券"、"美团红包墙"、"惠省领券"、"南航签到"、"魔搭魔粒"、"WorkBuddy积分"、"小浣熊积分"、"Loomy积分"、"天翼云盘"、"京东京豆"、"京东抽奖"、"阿里云盘"、"阿里网盘"、美团答题"、"米金"、"有品签到"、"小米签到"、"千问办公"、"华为码道"、"码道"、"CodeArts"、"Qoder"、"Qoder CN"、"领积分"、"领Credits"、或提及这些平台时使用。配置只需抓 1 条请求发给我即可，方法见 SKILL.md。
---

# 签到啦 · 一键签到/领券合集

整合十九个**已抓包验证**的自动化入口（19 个脚本，按「同一家企业产品合并」原则收敛为 15 个平台组，与 README 口径一致），全部纯接口实现，自带幂等（当天不重复执行）与状态文件。各平台按需运行对应脚本，命令见「四、导出脚本自用」。

> **★生效目录（2026-10-15 从 WorkBuddy 迁到 Qoder）**：脚本与配置现在放在
> `<本机路径>` 与 `<本机路径>`
> **两处保持一致**。旧位置 `<本机路径>` 是**只读历史**，
> 不要在那里改代码、也不要再改回 `skills`（每日总控任务的 `DIR` 必须指向新目录）。
> 解释器/Node 仍复用 `~/.workbuddy/binaries/`（那份没动），可用 `WB_PY` / `MT_NODE` / `SIGNIN_SCRIPTS_DIR` /
> `THORIUM_EXE` 覆盖，脚本内部不再钉死用户名与版本号。GR 的「第二份 config 镜像」路径改放本地
> `gr_config.json` 的 `workdir_cfg` 键（该文件不入库），代码里不留机器路径。

| 平台 | 脚本 | 作用 | 依赖 |
|---|---|---|---|
| 南航（中国南方航空小程序） | `scripts/csair_signin.py` | 发现新境签到 + 营销签到领里程 + 签到抽奖机会检测（抽奖消耗半自动） | Python 标准库（H5 重登需 Playwright） |
| **美团系（4 项，总控链内串行）** | `scripts/mt_api_coupon.py`<br>`scripts/mt_gundam_coupon.py`<br>`scripts/mt_union_coupon.py`<br>`scripts/mt_answer.py` | ①红包墙每日领券+营销页红包（rightCode 级幂等）②福利社跨券墙+限时抢+天降掉券 ③分销会场券包+内嵌跨券墙（单日约 ¥180）④答题七日签到+每日任务现金（WebSocket 重放） | Python + Node（mtgsig/H5 签名沙箱） |
| 魔搭（ModelScope） | `scripts/ms_magicube.py` | 每日登录魔粒 +250 + 点赞刷分 +40（会话副作用 + star/unstar 循环） | Python 标准库 |
| **WorkBuddy（2 项，链内串行）** | `scripts/wb_score.py`<br>`scripts/wb_growth.py` | ①Buddy 加油站签到 +100/天 + 派猫猫旅行闭环（先领后派，5~10/天）②成长中心 6 项奖励补齐（盲盒/连登兑换/断登补签/接任务/领任务奖，全幂等） | Python 标准库（底层调 totorosir-workbuddy-score skill） |
| 办公小浣熊（商汤 xiaohuanxiong） | `scripts/xhx_office_points.py` | 每日积分确认（免费版每日送 300，会话活跃自动入账；refresh_token 自动续 accessToken） | Python 标准库 |
| **讯飞Loomy（2 项，链内串行）** | `scripts/loomy_points.py`<br>`scripts/loomy_desktop_tasks.py` | ①Web 端每日积分确认（活跃自动入账，纯 cookie 鉴权）②桌面端新手任务 8 项共 10000 分（Electron 客户端专属，自动读本机登录态；已纳入总控每日检测，满额零副作用跳过） | Python 标准库 |
| 天翼云盘（cloud.189.cn） | `scripts/c189_signin.py` | 每日个人签到领随机空间（SSON 登录 cookie → getSessionForPC 换 sessionKey → `/mkt/userSign.action`；幂等，isSign=true 时零副作用） | Python 标准库 |
| 京东京豆 + 互动中心 | `scripts/jd_web_signin.py` | 每日京豆签到（Web 端 `pc_interact_sign_execute`，+N 京豆/日，连签有加成）+ **互动中心天天抽奖**（`interact` 子命令：做任务赚抽奖机会→转盘抽奖，红包/优惠券/京豆；幂等，已签/已抽跳过） | Python + Node（京东官方 js_security_v3 签名器沙箱） |
| **阿里系（3 项，总控链内串行）** | `scripts/aliyun_signin.py`<br>`scripts/qwenwork_credits.py`<br>`scripts/qoder_credits.py` | ①阿里云盘每日签到：★凭证在浏览器 **Local Storage**（Cookies 库被独占锁，但 leveldb 可读）；★按**值**搜索 `"refresh_token":"<32位hex>"` 再扩 JSON；refresh 不使旧 token 失效→不踢浏览器 ②千问办公每日 100 积分：★凭证在桌面端 `auth-v2.dat`（Chromium **v10 加密信封**，DPAPI+AES-GCM，与浏览器 cookie 同一套解密链），脚本实时解密读取，**免抓包、免登录维持**；免费版积分当日有效 ③Qoder CN 每日 100 Credits（30 天有效）：★凭证在桌面端 `auth.v1.dat`（**同一套 v10 解密链**）；campaigns 动态发现 + claim，服务端幂等 | Python 标准库（+cryptography 解 v10 信封） |
| **小米系（2 项，链内串行）** | `scripts/xm_mijin.py`<br>`scripts/yp_rpsign.py` | ①小米商城米金签到 +15/日 + 浏览任务各 +5（venue/page v1 + infinite do/done；幂等 code:200001）②有品每日红包签到（全年活动，实测 0.24 元/日，连签 7 天第 7 天 5 元；先 getActInfo 判状态再点击） | Python 标准库 |
| 华为码道（CodeArts Doer） | `scripts/hw_codearts.py` | 每日签到领 **1000 积分**（30 天有效）。三步链路：`ops/delivery` 查 `claimable` → `ops/claim`（idempotentKey `claim_<id>_<ms>`）→ `ops/confirm`（积分入账）。幂等：已领时 `claimable=false` + `status=CONFIRMED`，硬提交返 `code:40001 尚未到达权益刷新时间` | Python 标准库 |
| 通用浏览器 Cookie 提取 | `scripts/browser_cookies.py` | 从本机 Chromium/Thorium 的 Cookies 库按域取**已解密** cookie（绕独占锁直读 → TEMP 整库副本 → CDP 9222 三级回退）。`extract()` 给 `{name: value}`，`extract_full()` 额外保留 `host_key/path/secure`（往浏览器**注入**登录态必须用它）。京东/阿里云盘/千问办公/Qoder/掘金救援共用这套解密链 | Python 标准库 +cryptography |

> **工作方式**：你抓包、发我请求，我来分析、生成配置、自动执行。你不需要记命令、不需要懂字段，脚本命令只在「导出脚本自用」时才需要（见文末）。

> **同一家企业的多个产品已合并为一组**（美团系 / 小米系 / 讯飞Loomy / WorkBuddy / 阿里系 / 利宝）：上面表格中同组脚本按所列顺序依次执行即可，等价于总控的链内串行；各组共享一份配置、各写独立 state，互不影响。

---

## 一、你要做的：抓 1 条请求发我

> 准备：电脑/手机微信挂 **Reqable / mitmproxy / Charles** 代理，正常打开对应小程序操作一次，把下面这条请求「整条复制」（抓包工具里选该请求 → 复制 Request）发给我即可。

### 1) 美团福利社 H5 活动页（美团系）

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

### 4) Loomy（讯飞 loomy.xunfei.cn｜讯飞Loomy组）

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

### 11) 美团答题领现金（美团系，2026-10-13 建成）

抓包：美团答题活动任意 `/mtop/mf/act/infinite/*` 请求（Cookie 入 `mt_answer_config.json`）。

- ★协议：**MGC Pike WebSocket**（非 HTTP）——帧 `42["pike",{v,c,d}]`，d 双重 JSON 编码；响应 type = 请求 type-10000
- ★服务端 type 是**字符串**，必须 `int()` 强转（直接比较会全军覆没）
- 鉴权签名 = `base64(md5(bizId+"browser"+random+SALT))`，SALT=`5d6db287-84b8-46a7-9bcf-14242de3c139`
- 幂等判据 = **服务端 status**（0 未完成 / 1 待领 / 2 已领），不依赖本地标记

### 12) 小米商城米金（小米系，2026-10-14 建成）

抓包：小米商城 App 任意 `shop-api.retail.mi.com` 请求的 Cookie（serviceToken/userId/xmUuid，入 `xm_mijin_config.json`）。

- ★★米金页是 RN 页：`venue/v2/page` 对它**恒 404「apiInfo is null」**，必须用 **v1 `/mtop/navi/venue/page?page_id&pdl&sign`**；sign 从 `personalHome` 的 `miGoldRemindInfos.jumpUrl` 实时提取（不过期）
- 任务链路：`POST /mtop/mf/act/infinite/do` body `[{},{actId,taskId}]` → taskToken → `POST /mtop/mf/act/infinite/done` body `[{},{taskToken,actId,taskType,extra}]` → `awardList` 真实入账
- 收益：米金签到 +15/日（每日 5 + 连签奖励 10）、浏览任务各 +5；type 211（下载/打开 App）无法纯脚本完成，跳过
- 幂等：done 返 `code:200001「达到任务上限」`；过期 `code:200006「任务已结束」`

### 13) 有品每日签到·红包签到（小米系，2026-10-14 建成）

抓包：有品 App「积分中心 → 每日签到」页（`hd/checkInsignIn`）任意请求的整行 Cookie（入 `yp_rpsign_config.json`）。

- host=`m.xiaomiyoupin.com`；actId=`686b76a6ac546f0001b930c5`（**全年活动** 2026-01-05~12-31，奖池 1 万元剩 9678.89，7 天连签第 7 天 5 元）
- ★★`clickSign` 对已签到返 `code:500「failed to get dubbo response」`（**非标准幂等文案**，曾误导判断为活动下线）→ 必须先 `getActInfo` 判 `signUserInfo.sign` 再决定点击
- ★10-13「请登录」卡点根因 = **host 用错**：有品 App serviceToken 在 `m.xiaomiyoupin.com` 域直接 code 0（10-13 误试 shopapi.io.mi.com + passportapi token，双重错误）
- 接口族：getActInfo / clickSign / getFetchRecord / shareOrLike / remind + `/mtop/coupon/redpacket/get_user_balance`（红包余额），body 均 `params:[{}, X]`

### 14) 千问办公（阿里系，2026-10-14 建成）

**免抓包**：安装并登录「千问办公」桌面端即可，脚本实时解密 `%APPDATA%/QwenWorkCN/auth-v2.dat`。

- ★凭证机制：`auth-v2.dat` 是 Chromium **v10 加密信封**（`{"schemaVersion":2,"token":"<JWT>","refreshToken":"ory_rt_..."}`），解密链与浏览器 cookie 完全一致 —— `Local State` 的 `os_crypt.encrypted_key` 去 `DPAPI` 5B 头 → `CryptUnprotectData` → 32B AES key → `AESGCM(nonce=ev[3:15]).decrypt(ev[15:])`
- ★**优先实时读客户端文件**（桌面端自己会续期），`qwenwork_config.json` 只作兜底 → **永不与客户端抢 refresh_token 轮换、不踢下线**
- 接口：BASE=`https://gateway.qwenwork.cn`；`GET /api/v1/adapter/user/wallets`（日包/月包/长期余额）、`GET /api/v1/adapter/user/account-context?include=user,plan,quota`、`POST /api/v1/deviceToken/refresh` `{refresh_token,target:"c"}`
- ★实测结论：免费版每日 100 积分是**服务端自动发放**（当日有效，`valid_to`=次日 00:00），桌面端无手动领取动作；前端 bundle 里的 `/sash/api/v1/me/daily-check-in/{status,claim}` 在**生产网关未路由（404）**，脚本探测到 404 自动跳过、走钱包核对
- 断线症状：`auth-v2.dat` 缺失或 token 过期 → 提示重新安装/登录桌面端

### 15) 华为码道 CodeArts Doer（2026-10-14 建成）

抓包：浏览器登录 `devcloud.cn-north-4.huaweicloud.com/chat/home` → F12 → Network 任意 `PromptCenterService` 请求 → 复制**整行 cookie 头** → `python scripts/hw_codearts.py init '<cookie>'`。

- ★必须先去掉 `x-requested-with: XMLHttpRequest` 才能拿到 `/chat/home` 页面（带该头网关一律按 API 路由 → 404）
- 接口族（从前端 `index.js` + `DefaultLayout` chunk 反查）：`GET ops/delivery?channel=WEB`、`POST ops/claim`、`POST ops/confirm`、`POST ops/invite/generate`、`POST ops/invite/confirm-by-code?inviteCode=`、`GET ops/tasks/conversation`、`POST ops/events/conversation`
- `cftk` 头 = cookie 里的 `devclouddevuibjtcftk`（`home.html` 明示 `app_cookie_prefix=cftk`），脚本自动提取
- 活动清单：id=1 每日签到 1000 积分（`USER_LOGIN`）、id=2 学生认证 4000（需先认证，直领返 40001「需要先通过触发接口激活」）、id=3 邀请 1000/人、id=4 新用户注册 4000（`AUTO_GRANT`）
- ★两步不可省：`claim` → `CLAIMED`，`confirm` → `CONFIRMED`（积分才入账），confirm 返回 `totalAmount/remainingAmount/expireAt`（30 天有效）
- 幂等：`claimable=false` + `status=CONFIRMED` = 今日已领；硬提交返 HTTP200 + `code:40001「尚未到达权益刷新时间，暂时无法领取」`

### 16) Qoder CN（阿里系，2026-10-15 建成）

**免抓包**：安装并登录「Qoder CN」桌面端即可，脚本实时解密 `%APPDATA%/com.qodercn.app.stable/auth.v1.dat`。

- ★凭证机制：`auth.v1.dat` 是 Chromium **v10 加密信封**（`{"schemaVersion":1,"token":"dt-...","refreshToken":"drt-...","expiresAt":...,"user":{...}}`），解密链与浏览器 cookie / 千问办公 `auth-v2.dat` **完全一致**；`auth.machine-id` 是明文（机器码，抓包里的 `cosy-machineid` 即它），`auth-profile-overlays.v1.dat` 也是 v10 信封但内容无用
- ★**优先实时读客户端文件**（桌面端自己会续期）→ **永不与客户端抢 refresh_token 轮换、不踢下线**；`qoder_config.json` 只作兜底
- 接口：HOST=`https://openapi.qoder.com.cn`；`GET /sash/api/v1/me/campaigns`（活动清单）、`POST /sash/api/v1/me/campaigns/{campaignId}/claim`（body 空，`content-length:0`）
- ★**必需请求头只有 2 个**（二分实测）：`authorization: Bearer <dt-token>` + `cosy-clienttype: 10`。其余全装饰：`cosy-version/machineos/machinehostname/machineid/machinetoken/machinecode/machinetype`、`bx-v`、`sec-*`、`origin`、`referer`、**cookie** 缺了照样 200
- ★但**不能完全没有 cosy-\* 头**：缺时服务端返 `{"showCampaign":false,"claimable":false,"campaigns":[]}` —— 不报错但拿不到活动（按客户端类型过滤），脚本对此有明确诊断分支
- ★**活动每日一期**：窗口 = 北京时间当日 **10:00 ~ 次日 09:59**，每期 `campaignId` 是新的 UUIDv7 → **绝不能硬编码**，必须每次 GET campaigns 动态取；`campaignKey`（如 `act-20261013-847`）是模板 key，不随期变
- 挑选：`actionType=="CLAIM_BENEFIT"` 且 `benefit.kind=="CREDITS"`（每日 100 那期；另有 REDEMPTION_CODE 需达成成就、VIEW_DETAILS 无权益，自动忽略）
- ★幂等铁证：`claimStatus=="CLAIMED"` 直接跳过；重复 claim 返**同一 grantId** 且 `replayed=true`，服务端不重复发放 —— 可安全每天跑
- ★★**窗口切换边界（2026-10-15 修的静默漏领坑）**：总控 10:00 跑与窗口开场几乎重合，此刻列表里可能**同时存在刚过期的旧一期（已 CLAIMED）与新一期**，若按返回顺序取首个匹配就会误判「今日已领」而漏领整天。脚本已改为**优先挑「窗口覆盖当前时刻」的那期**，选中的若仍是刚过期一期则等 20s 重取一次。故排「阿里系」链**最后**（链内串行天然延迟，双重保险）
- 断线症状：`auth.v1.dat` 缺失或 token 过期 → 提示重新安装/登录桌面端

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
- 千问办公：每日 100 积分核对（`qwenwork_credits.py auto`；凭证实时解密桌面端 `auth-v2.dat`，免抓包；免费版积分**服务端自动发放、当日有效**，脚本核对日包余额 + 尝试签到接口）
- Qoder CN：每日 100 Credits 领取（`qoder_credits.py auto`；凭证实时解密桌面端 `auth.v1.dat`，免抓包；campaigns 动态发现 → claim，30 天有效；服务端幂等，重复提交 `replayed=true` 不重复发放；排在阿里系链末位，规避每日 10:00 窗口边界）
- 华为码道：每日签到领 1000 积分（`hw_codearts.py auto`；`delivery` 判 `claimable` → `claim` → `confirm`；已领时 `claimable=false`，脚本跳过并打印积分桶余额）

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
| ★WorkBuddy 报「未找到 buddy_station.py（skill 未安装？）」 | 2026-10-15 目录收敛把 `~/.workbuddy/skills` 整体改名 `skills_deprecated_20261015`，而 `wb_score.py`/`wb_growth.py` 只搜老路径找官方 skill `totorosir-workbuddy-score` | 已修复：两处都改为按 `~/.qoder-cn/skills` → `~/.agents/skills` → `~/.workbuddy/skills` 顺序搜索。若仍找不到，说明该 skill 真被卸载，重装后无需改脚本 |
| WorkBuddy 报「[x] 无法解析输出」+ `UnicodeDecodeError: 'gbk' codec can't decode` | 父进程按本地 GBK 解 `buddy_station.py` 的 UTF-8 中文输出，reader 线程崩掉 → 表现为**假失效**（路径修好后才暴露） | 已修复：`run_bs()` 显式 `encoding="utf-8", errors="replace"` 并给子进程 `PYTHONIOENCODING=utf-8` |
| 编排器打印「headless 浏览器就绪」，cookie_sync 却报 `[中断] cookie 读取失败: WinError 10061` | 拉起的 headless 实例在「就绪」之后**中途退出**（`/json/version` 曾短暂可达）。旧版一次失败就 rc=2 | 已修复两层：`_wait_online()` 现在校验 9222 的 LISTEN 确属本次拉起的进程（psutil `net_connections`），且要求 Popen 仍存活；`cookie_sync` 读 cookie 失败会收掉死壳**重试一次** |
| 京东签到 `code:3` 请先登录 | 浏览器里京东登录态失效/被服务端轮换（`order.jd.com` 也会退回欢迎登录页） | 在 Thorium 里打开 jd.com 重新登录；脚本下次运行自动读新 cookie，无需改配置 |
| 京东签到 `DG-9999 系统异常` | 走的是**已下线的旧接口** `signBeanIndex`（App 端链路，2026-10-12 起不可用） | 改用 Web 端 `jd_web_signin.py`（`pc_interact_sign_execute`）；旧 `jd_signin.py`/`jd_login.py` 已废弃 |
| 京东互动中心接口返回 HTTP 403（空 body） | WAF 按端点频率限制（与 thor/eid 会话绑定，可持续 40 分钟以上） | 脚本已内置 4s 节流 + 403 优雅降级（不中断）；当日勿再手动连打同端点，等次日任务自动换新 cookie 会话即恢复 |
| 京东互动中心 `code:3` 请先登录 | 浏览器京东登录态失效/被轮换 | 同签到：Thorium 重新登录 jd.com，下次运行自动读新 cookie |
| 阿里云盘「今日已签」却记成首次 | `signInLogs` 的中文月份/字符串日解析失败会判不到今日 | 已修（`_cn2int` 支持「十月」/"12"）；核对用 `aliyun_signin.py status` |
| 千问办公/Qoder CN 提示【失效】未找到凭证 | 桌面端未安装/未登录，或 `auth-v2.dat` / `auth.v1.dat` 缺失 | 安装并登录对应桌面端一次；两家的凭证文件都是 Chromium v10 信封，脚本实时解密、不写回客户端 |
| Qoder CN 提示「服务端返回空活动列表」 | `cosy-clienttype` 头缺失时服务端按客户端类型过滤活动（不报错但 `campaigns:[]`） | 脚本已固定发送 `cosy-clienttype: 10`；若仍空列表，检查是否到了每日 10:00 窗口、或活动是否下线 |
| Qoder CN「已领取」但积分没到账 | 服务端 `claimStatus=CLAIMED` 即已发放；重复 claim 返同一 grantId + `replayed=true` | 正常幂等；去 Qoder CN 活动页核对，或用 `probe` 强制提交看服务端原文 |
| ★凭证同步 `[中断] 浏览器启动失败或 9222 不可达`（rc=2）、同轮**掘金也跟着失败** | 你自己的 Thorium 正开着但没带 `--remote-debugging-port`。Chromium 的 profile 是**单例**的：用同一个 `User Data` 再起 headless，新进程只会把启动请求移交给已运行实例后退出，9222 永远不监听（2026-10-15 实测第 0/8 步双双超时） | 已修复——`headless_browser.py` 检测到实例在跑就改用**独立临时 profile**（`%TEMP%\wb_th_*`）并从磁盘 Cookie 库注入登录态；收尾按临时 profile 精准回收，不碰你的窗口 |
| 临时 profile 兜底时只有 2/3 同步成功，**办公小浣熊报 `raccoon_token` 缺失** | `raccoon_token` / `raccoon_refresh_token` 是**会话级 cookie**（Chromium 不落盘），磁盘 Cookie 库里根本没有，临时 profile 注入不到 | 非「用户没登录」。要同步小浣熊必须让浏览器**带着 9222 启动**（`thorium.exe --remote-debugging-port=9222`）再跑 `cookie_sync.py`；否则该家沿用 config 里的旧 token，到期才需处理 |
| 华为码道 `[失败] delivery HTTP 200 但空响应体` | 华为云网关/WAF 在**登录态失效**时就回 200 + 零字节（不是 JSON、也不是 401），旧版只说「HTTP 200」等于没法定位 | 已修复：`fail_reason()` 区分「明确拒绝 / 业务码 401 / 空响应体 / HTML 跳转登录页」；空 body 一律按 cookie 失效处理，F12 重抓 `PromptCenterService` 请求的整行 cookie 跑 `init` |
| 华为码道「今日不可领」`claimable=false` 且 status 非已领 | 权益刷新周期**不是自然日**（实测 confirm 显示 claimedAt=09-27 后长期不可领） | 业务态不是失效，脚本已返回 0 并标注【今日不可领】，别再当日误报异常；`probe` 可看服务端 40001 原文 |
| 京东明明重新登录了，仍持续 `login_expired`（曾连挡两天） | 两个旧缺陷：① 新版 Chromium **稳定独占** `Cookies` 库，`CreateFileW(SHARE_ALL)` 也读不到；② `manual=true` 配置一旦写入就短路整条提取链（TEMP 缓存只在直读成功时刷新，而直读被短路永不执行） | 已修复（2026-10-14）：直读失败转 **`esentutl.exe /y <Cookies> /d <副本> /o`** 拿完整快照；`manual` 加 **6h TTL** 后回落正常提取链。核对跑 `jd_web_signin.py cookie` 看「磁盘直读 OK」 |

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

# 千问办公（安装并登录桌面端 QwenWorkCN，脚本解密 auth-v2.dat，免抓包）
python scripts/qwenwork_credits.py auto                 # 签到探测 + 钱包核对（定时任务用这个）
python scripts/qwenwork_credits.py status               # 只读：日包/月包/长期余额 + 额度
python scripts/qwenwork_credits.py init                 # 把客户端凭证导出到 qwenwork_config.json 兜底
python scripts/qwenwork_credits.py refresh              # 手动续期（会轮换 refresh_token，非必要别跑）

# 华为码道（登录 devcloud.cn-north-4.huaweicloud.com/chat/home 后 F12 抓一条）
python scripts/hw_codearts.py init "<整行cookie>"        # 落盘凭证并校验（cftk 自动从 cookie 提取）
python scripts/hw_codearts.py auto                      # delivery → claim → confirm（定时任务用这个）
python scripts/hw_codearts.py status                    # 只读：活动状态 + 积分桶
python scripts/hw_codearts.py probe                     # 不可领时硬提交一次，拿到服务端原文定位刷新时间

# Qoder CN（安装并登录桌面端 Qoder CN，脚本解密 auth.v1.dat，免抓包）
python scripts/qoder_credits.py auto                    # campaigns 动态发现 → 领取每日 100 Credits（定时任务用这个）
python scripts/qoder_credits.py status                  # 只读：活动清单 + 今日是否已领
python scripts/qoder_credits.py probe                   # 强制领取一次（验证服务端幂等 replayed）
python scripts/qoder_credits.py init                    # 把客户端凭证导出到 qoder_config.json 兜底

# 凭证同步：魔搭/小浣熊/Loomy 轮换制凭证从浏览器自动取新写回（每日任务第 0 步）
# 阿里云盘不走 cookie（凭证在 Local Storage），不在此列
```

挂定时任务（如每天 08:30 依次跑四条），脚本自带幂等，当天完成后自动跳过；删除对应 `*_state.json` 可重跑。


