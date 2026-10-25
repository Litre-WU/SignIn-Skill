---
name: qiandao-la
slug: signin-skill
displayName: 签到啦
description: 一站式签到/领券综合工具，整合26个已抓包验证的自动化入口：美团惠省小程序首页红包墙每日领券+营销页红包+分销会场券包、南航（中国南方航空小程序）双链路签到+签到抽奖、魔搭 ModelScope 每日魔粒、WorkBuddy 积分签到+派猫猫旅行、办公小浣熊（商汤 xiaohuanxiong）每日积分、Loomy（讯飞）每日积分、天翼189云盘每日签到领空间、京东京豆每日签到（互动中心天天抽奖因京东账号/会话级 403 风控已移出总控，仅留复测入口）、阿里云盘每日签到（浏览器已登录即全自动，脚本直接读本机 Local Storage，无需抓包）、美团答题领现金、小米商城米金+有品红包签到、千问办公每日100积分、华为码道每日签到1000积分（免抓包，直接复用 CodeArts Agent 桌面端登录态的 IAM 临时 AK/SK 签名）、Qoder CN 每日100 Credits（免抓包，桌面端凭证自解密）、字节TRAE每日签到积分、有道LobsterAI每日签到积分（免抓包，直读桌面端 lobsterai.sqlite 的 JWT 凭证 + /api/auth/refresh 离线续期）、MiniMax Code七日签到积分（免抓包，直读桌面端 auth.json 活凭证 + refresh_token 离线续期）、WorkBuddy 国际版每日签到积分（www.workbuddy.ai，需国际版独立账号）、Qoder 国际版每日 100 Credits（并入 Qoder 脚本双区串行）、ZCode 智谱每日额度（领取需阿里云验证码）、滴滴出行自动领券+福利中心签到（打车/花小猪/加油/货运，H5 登录票据鉴权+wsgsig 签名）。纯接口自动化（非 UI 点击），支持幂等与定时任务。当用户要求"签到"、"领券"、"打卡"、"每天签到"、"美团领券"、"美团红包墙"、"惠省领券"、"南航签到"、"魔搭魔粒"、"WorkBuddy积分"、"小浣熊积分"、"Loomy积分"、"天翼云盘"、"京东京豆"、"京东抽奖"、"阿里云盘"、"阿里网盘"、美团答题"、"米金"、"有品签到"、"小米签到"、"千问办公"、"华为码道"、"码道"、"CodeArts"、"Qoder"、"Qoder CN"、"领积分"、"领Credits"、"TRAE签到"、"LobsterAI签到"、"MiniMax签到"、"WorkBuddy国际版"、"Qoder国际版"、"ZCode"、"滴滴领券"、"打车领券"、"滴滴签到"、或提及这些平台时使用。凭证更新优先走 **Reqable MCP 自动抓包**（agent 过滤记录 + `reqable_hunt.py harvest` 落地，用户只在客户端做一次动作即可，不用复制请求文本），MCP 不可用时才手工抓 1 条请求。方法见 SKILL.md。
---

# 签到啦 · 一键签到/领券合集

整合二十六个**已抓包验证**的自动化入口（脚本按「同一家企业产品合并」原则收敛为 18 个平台组，与 README 平台表口径一致），全部纯接口实现，自带幂等（当天不重复执行）与状态文件。各平台按需运行对应脚本，命令见「四、导出脚本自用」。

| 平台 | 脚本 | 作用 | 依赖 |
|---|---|---|---|
| 南航（中国南方航空小程序） | `scripts/csair_signin.py` | 发现新境签到 + 营销签到领里程 + 签到抽奖机会检测（抽奖消耗半自动） | Python 标准库（H5 重登需 Playwright） |
| **美团系（4 项，总控链内串行）** | `scripts/mt_api_coupon.py`<br>`scripts/mt_gundam_coupon.py`<br>`scripts/mt_union_coupon.py`<br>`scripts/mt_answer.py` | ①红包墙每日领券+营销页红包（rightCode 级幂等）②福利社跨券墙+限时抢+天降掉券 ③分销会场券包+内嵌跨券墙（单日约 ¥180）④答题七日签到+每日任务现金（WebSocket 重放） | Python + Node（mtgsig/H5 签名沙箱） |
| 魔搭（ModelScope） | `scripts/ms_magicube.py` | 每日登录魔粒 +250 + 点赞刷分 +40（会话副作用 + star/unstar 循环） | Python 标准库 |
| **WorkBuddy系（4 项，链内串行）** | `scripts/wb_score.py`<br>`scripts/wb_growth.py`<br>`scripts/workbuddy_intl_credits.py`<br>`scripts/wb_balance.py` | ①Buddy 加油站签到 +100/天 + 派猫猫旅行闭环（先领后派，5~10/天）②成长中心 6 项奖励补齐（盲盒/连登兑换/断登补签/接任务/领任务奖，全幂等）③**国际版**（www.workbuddy.ai）每日签到积分：★路径**不带 `/v2`**、**不带**设备指纹头；★判定只看响应体 `code`（重复领取 HTTP 400 + code 10001）；★★**需国际版独立账号**（国内 .cn 态在 .ai 域被 APISIX 网关 401，网关认 session cookie 不认 Bearer）；未配置时 `[skip]` 退 0 ④★**账户真实积分**（2026-10-23 逆向，与客户端用量页同一个数）：`POST /billing/meter/get-user-resource-summary`（**不带 /v2**）+ `X-Device-Token`，缺该头 → `403 code=10085 请求不合法`；令牌由客户端自带 N-API 原生桥 `app.asar.unpacked/native/turing-sdk`（腾讯 T-Sec TuringShield）现取，`channelId` 读 `app.asar.unpacked/cli/product.json` 的 `config.turingSdk`（本机 109144）；★★**令牌只在取它的那个进程活着时有效**，跨进程复用必 10085 → 故取令牌与发请求都在同一个 node 进程里（`wb_balance_query.js`，Bearer 走 stdin 不入 argv）。⚠️ 判读禁忌：`wb_score.py` 的 `total_credits` 是**加油站本期累计签到积分**（恒＝连签天数×daily_credit），**不是余额**，别再写成「余额」 | ①②底层调 totorosir-workbuddy-score skill；③标准库；④标准库 + node（客户端自带） |
| 办公小浣熊（商汤 xiaohuanxiong） | `scripts/xhx_office_points.py` | 每日积分确认（免费版每日送 300，会话活跃自动入账；refresh_token 自动续 accessToken） | Python 标准库 |
| **讯飞Loomy（2 项，链内串行）** | `scripts/loomy_points.py`<br>`scripts/loomy_desktop_tasks.py` | ①Web 端每日积分确认（活跃自动入账，纯 cookie 鉴权）②桌面端新手任务 8 项共 10000 分（Electron 客户端专属，自动读本机登录态；已纳入总控每日检测，满额零副作用跳过） | Python 标准库 |
| 天翼云盘（cloud.189.cn） | `scripts/c189_signin.py` | 每日个人签到领随机空间（SSON 登录 cookie → getSessionForPC 换 sessionKey → `/mkt/userSign.action`；幂等，isSign=true 时零副作用） | Python 标准库 |
| 京东京豆 | `scripts/jd_web_signin.py` | 每日京豆签到（Web 端 `pc_interact_sign_execute`，+N 京豆/日，连签有加成）。★★**互动中心天天抽奖已于 2026-10-17 移出总控**（那组 functionId 是账号/会话级 403 风控，越打越宽；`interact`/`interact_status` 子命令仍保留在脚本里，仅供封锁解除后复测，见 §9b 与 `jd_interact_inpage.py`） | Python + Node（京东官方 js_security_v3 签名器沙箱） |
| **阿里系（3 项，总控链内串行）** | `scripts/aliyun_signin.py`<br>`scripts/qwenwork_credits.py`<br>`scripts/qoder_credits.py` | ①阿里云盘每日签到：★凭证在浏览器 **Local Storage**（Cookies 库被独占锁，但 leveldb 可读）；★按**值**搜索 `"refresh_token":"<32位hex>"` 再扩 JSON；refresh 不使旧 token 失效→不踢浏览器 ②千问办公每日 100 积分：★凭证在桌面端 `auth-v2.dat`（Chromium **v10 加密信封**，DPAPI+AES-GCM，与浏览器 cookie 同一套解密链），脚本实时解密读取，**免抓包、免登录维持**；免费版积分当日有效 ③Qoder CN 每日 100 Credits（30 天有效）：★凭证在桌面端 `auth.v1.dat`（**同一套 v10 解密链**）；campaigns 动态发现 + claim，服务端幂等 | Python 标准库（+cryptography 解 v10 信封） |
| **小米系（2 项，链内串行）** | `scripts/xm_mijin.py`<br>`scripts/yp_rpsign.py` | ①小米商城米金签到 +15/日 + 浏览任务各 +5（venue/page v1 + infinite do/done；幂等 code:200001）②有品每日红包签到（全年活动，实测 0.24 元/日，连签 7 天第 7 天 5 元；先 getActInfo 判状态再点击） | Python 标准库 |
| 华为码道（CodeArts Doer） | `scripts/hw_codearts.py`<br>`scripts/hw_codearts_refresh.py` | 每日签到领 **1000 积分**（30 天有效）。★**免抓包**：直接解密 CodeArts Agent 桌面端 `state.vscdb` 里的 IAM 临时 AK/SK，按 `SDK-HMAC-SHA256` 签名打 `snap-access…/v1/ops/{delivery,claim,confirm}`（`channel=IDE`）；★★**账号状态保持（2026-10-16）**：临时 AK/SK（约 2h 寿命）过期时，`hw_codearts_refresh.py` 用 session 里的 `refresh_token`（约 28 天）+ PKCE codeVerifier + DPoP 私钥签 ES256 proof 直接向 STS 离线换新凭证（参考 Our Free Model `src/oauth.ts` 逆向）——**无需开着客户端**；刷出的新凭证缓存 2h 内复用（refresh_token 单次轮换，一天多跑只烧一次）；refresh_token 也终态失效才提示重开客户端登录。三步链路：`delivery` 查 `claimable` → `claim`（idempotentKey `claim_<id>_<ms>`）→ `confirm`（积分入账）。幂等：已领时 `claimable=false` + `status=CONFIRMED`，硬提交返 `code:40001 尚未到达权益刷新时间` | Python 标准库 +cryptography（复用 `browser_cookies` 的 v10/DPAPI 解密链） |
| 字节 TRAE | `scripts/trae_credits.py` | 每日签到积分（实测单日 150）。`Cloud-IDE-JWT` 鉴权 + 设备身份按 uid 确定性派生（15 位数字/UUIDv4/64hex，SHA256 种子流）。★claim 幂等但响应与成功**不可区分** → 必须先查 status.checked_in，领取后回查 status 取积分。错误冷却：1005 套餐限 / 9074 繁忙 / 401 失效 | Python 标准库 |
| 有道 LobsterAI | `scripts/lobsterai_credits.py` | 每日签到积分（实测「每日登录奖励」100/天）。三步：slot（placement=desktop_sidebar 固定参数）→ context（claimedToday + actions 双预检）→ check_in（客户端 uuid4 幂等键）。纯 Bearer 无签名。余额用 profile-summary（quota 端点不含活动积分）。★★**2026-10-18 起首选「免抓包」链路**：直接只读桌面端 `%APPDATA%/LobsterAI/lobsterai.sqlite` 的 `kv` 表拿 `auth_tokens{accessToken,refreshToken}` + `keyfrom.attribution.v1` + `auth_user` + `installation_uuid`（accessToken 是 **JWT，exp 约 30 天**）；配 `/api/auth/refresh`（★匿名头、无 Authorization）离线续期，`REFRESH_LEAD=1h` 内才动手、同一支只试一次、终态码 `40100/40101/token rejected` 不重试、新凭证只写 `lobsterai_live_cache.json` **不回写 sqlite**。`--auth auto\|bearer\|cookie` | Python 标准库 |
| MiniMax Code | `scripts/minimax_credits.py` | 七日签到积分（实测单日 400/800 档）。`timezone_id`（IANA）必填；业务码在 `base_resp.status_code`；幂等判据 `claim_result`（1 领 / 2 已领）；★`points` 为总数不相加 `bonus_points`；今日已领判据 `is_today && status==3`。★★**已免抓包（2026-10-17 保活改造）**：直读桌面端 `~/.minimax/auth/prod/cn/mcode-public/auth.json` 的活 token，过期再用 `refresh_token` 离线刷（见 §19） | Python 标准库 |
| ZCode（智谱） | `scripts/zcode_credits.py` | Start Plan 每日额度（`zcode.z.ai`）。★查额度前**必须先补 `event/report` 激活**（app_launch + app_daily_active），否则 preview 空列表 → **稳定误报「今日已领」**；今日已领判据 = 可领 plan 数为 0。★`code 1003`=已领取（**属成功**）、`3007`=captcha 无效。★★**领取端点强制阿里云验证码**（不带/非法都 400/3007，且校验前置于 plan 校验）→ 无 captcha 时提示人工领取，不算失败 | Python 标准库 |
| 滴滴出行 | `scripts/didi_coupon.py` | 打车/花小猪/加油/货运 4 线自动领券 + 福利中心每日签到领福利金、气泡逐个点、瓜瓜乐报名/领奖。★凭证是 **H5 登录票据 token**（`sync` 命令从本机浏览器登录态自动取，CDP+leveldb 双通道；或 F12 手取 localStorage，约 7-30 天有效）；`ut.xiaojukeji.com`/`api.didi.cn` 接口带 **wsgsig 签名**（md5 盐 `R4doMFFeMNlliIWMq` + ts/v/os/av/kv/vl/sig 七元组 + 4 字节掩码 XOR + base64）；`union.didi.cn` 领券无签名。同企合并为单链 | Python 标准库 |
| 京东互动中心（页内复测工具，**不进总控**） | `scripts/jd_interact_inpage.py` | ★互动中心那组 functionId（`assign_query`/`reward_center`/`assign_execute`）是**账号/会话级 403 风控**，urllib、headless、以及**真浏览器里页面自己发的请求**都会 403（详见 §14）。本工具用页面自己的 `PSign`/`getJsToken`/`SHA256` 复刻 `requestColorEncrypto`，**只用于封锁解除后复测**；`check` 只读自检、`auto` 领机会并抽。★会主动拒绝无头 9222（无头结论是假的），永不自启浏览器、永不回收用户实例 | Python 标准库 + websocket-client |
| 通用浏览器 Cookie 提取 | `scripts/browser_cookies.py` | 从本机 Chromium/Thorium 的 Cookies 库按域取**已解密** cookie（绕独占锁直读 → TEMP 整库副本 → CDP 9222 三级回退）。`extract()` 给 `{name: value}`，`extract_full()` 额外保留 `host_key/path/secure`（往浏览器**注入**登录态必须用它）。京东/阿里云盘/千问办公/Qoder/掘金救援共用这套解密链 | Python 标准库 +cryptography |

| **自动抓包入口（配合 reqable MCP）** | `scripts/reqable_hunt.py` | `doctor [--launch]` 体检 Reqable 进程/系统代理/根证书并给出下一步；`scan` 打印「平台→要抓哪个接口→提哪个字段→落到哪条命令」注册表；`harvest --file rec.json [--apply]` 吃 MCP `capture_live_get_by_id` 的记录原文，自动认平台、抽凭证、备份 config 再写回；`restore-proxy` 撤系统代理（关 Reqable 后必做，否则签到脚本成片假失效） | Python 标准库 + winreg（仅 Windows） |

> **工作方式（2026-10-16 更新）**：抓包不再要求用户「复制整条请求粘过来」——agent 直接用 reqable MCP 过滤并取记录，再用 `reqable_hunt.py harvest` 落地。**用户只需要在小程序/浏览器里做一次动作**。MCP 不可用时才退回第一节的手工抓包。你不需要记命令、不需要懂字段，脚本命令只在「导出脚本自用」时才需要（见文末）。

> **同一家企业的多个产品已合并为一组**（美团系 / 小米系 / 讯飞Loomy / WorkBuddy系 / 阿里系 / 利宝）：上面表格中同组脚本按所列顺序依次执行即可，等价于总控的链内串行；各组共享一份配置、各写独立 state，互不影响。

---

## 〇、抓包优先走 Reqable MCP（用户不用复制任何文本）

> 2026-10-16 起本 skill 的抓包默认由 **agent 通过 reqable MCP 自动完成**：用户只要在小程序/浏览器里**做一次动作**，agent 负责过滤记录、取响应原文、把凭证落到对应 config。旧的「抓 1 条请求粘给我」退为手工兜底（见第一节）。

**分工边界（重要）**：Reqable 本地 9000/9016 只有 `Hello Reqable!`，**没有可供 Python 直读的 REST 路由**（`/api` `/capture` `/mcp` 全 404）。所以「读抓包记录」这一步只能走 MCP；Python 侧的 [`scripts/reqable_hunt.py`](scripts/reqable_hunt.py) 负责前置体检与「记录 JSON → 凭证 → 写回 config」。

### agent 标准流程（5 步）

1. 体检：Reqable 是否在跑、系统代理、根证书；没跑就拉起
   ```bash
   python scripts/reqable_hunt.py doctor --launch
   ```
2. `mcp__reqable__capture_live_set_enabled{enabled:true}` 开抓（Reqable 一启动就会自行接管系统代理）
3. **让用户做一次动作**（照 `scan` 的「你要做的」列，例如：打开南航小程序首页 / 在 GR 小程序里手动分享一篇）
4. `mcp__reqable__capture_live_filter{filters:[…]}` → 用 `scan <平台>` 打印的 pattern 拿到记录 id → `mcp__reqable__capture_live_get_by_id{id:N}` 取整条记录
5. 把记录原文存成 TEMP 下的 `rec.json`（**别放会被发布的目录**），再
   ```bash
   python scripts/reqable_hunt.py harvest --file /tmp/rec.json          # 先演练，看提取到什么、将执行什么
   python scripts/reqable_hunt.py harvest --file /tmp/rec.json --apply  # 确认后落地（写前自动备份 config.bak-<ts>）
   ```
   `harvest` 会按 host/path 自动认平台，不用指定；认不出来就打印「注册表里没有匹配项」，说明抓到了同域的别的请求，换 pattern 再抓。

### 注册表（`python scripts/reqable_hunt.py scan` 的摘要）

| 平台 | 用户要做的一次动作 | MCP 过滤 pattern | 提取 | 落地 |
|---|---|---|---|---|
| `csair` | 打开 PC 微信南航小程序首页 | `mini/api/login/login` | 响应体 `{sessionId,openId,unionId}` | `csair_signin.py refresh` |
| `modelscope` | 浏览器打开 modelscope.cn（已登录） | host `www.modelscope.cn` | 请求头 `cookie`（含 m_session_id） | `ms_magicube.py init` |
| `libao` | 小程序进任意页 | host `cs.libao.cn` | 请求头 `authorization` | `libao_integral.py init --auth` |
| `gr` | **在小程序里手动分享一次文章**（定性接口改版 vs 限流的唯一对照样本） | `shareArticle` / `user/acquisition` | body 的 `openId`+`token` | `gr_signin.py init --token --openid` |
| `huawei` | 优先**打开 CodeArts Agent 并登录**（免抓包）；否则开 devcloud 页面 | `PromptCenterService` | 请求头 `cookie`（含 `devclouddevuibjtcftk`） | `hw_codearts.py init` |

### 三条必须知道的坑

1. **系统代理副作用**：`ProxyEnable=1 / ProxyServer=127.0.0.1:9000` 而 Reqable 没在跑时，本机所有走系统代理的 HTTPS 都会 connection refused → **签到脚本会成片假失效**（我们的 urllib 脚本会读系统代理，实测已被抓到）。抓包结束跑 `python scripts/reqable_hunt.py restore-proxy`，或让 agent 调 `proxy_set{overrideSystem:false}`。
2. **抓包记录里全是真凭证**（cookie / token / 手机号 / 身份证号密文）。`rec.json` 只放 TEMP；`harvest` 打印一律掩码；`config.bak-*` 与 `run_all_bench.json` 属本机运行物，**不要进发布目录或外传**。
3. **有些动作 Python 替不了**：阿里云 WAF 按路径的 JS 挑战（南航 `mileagegift/draw` 抽奖消耗）、真机分享上报（GR）等，必须用户在客户端里点；抓包在这里的价值是**取证与定性**，不是绕过。

---

## 一、手工兜底：抓 1 条请求发我

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

> **分销会场（"美团分销"小程序的会场券包）**：脚本 `mt_union_coupon.py`。链路 `listActivityCoupon/distributionVenue`（拉当日券列表 + recallToken）→ `grantActivityCoupon/distributionVenue`（H5 签名领取）。**复用同一条福利社抓包的 wm_logintoken 即可，无需额外抓包**（分销接口认账号级 token）。若想顺带领分销中心内嵌的跨券墙，复制 `scripts/mt_union_config.example.json` 为 `scripts/mt_union_config.json` 并填 `gdId/pageId/activityViewId/instanceId` 四个字段（从分销中心页抓包取，或走 §〇 让 agent 抓），不配则自动跳过。
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
脚本按**新鲜度**四级取 cookie：① CDP 9222 实时读（浏览器开着时唯一能拿到"刚刚登录"的新值）→ ② 磁盘直读（浏览器没在跑时）→ ③ **superpowers-chrome 持久 profile 磁盘直读**（2026-10-23 新增，★必须排在 TEMP 快照之前：9222 浏览器平时就是 superpowers 实例，用户在浏览器里"登录京东"大多发生在这个窗口；run_all 收尾回收 9222 后该库无锁可复制，而主 Thorium 的 User Data 还开着永远拷不动——旧代码先撞 10-21 的 TEMP 陈旧快照，把 16:26 的新鲜登录态盖成假 login_expired，即本次事故根因）→ ④ TEMP 快照（可能陈旧，脚本会打印它多少分钟前、并在 `login_expired` 里带纠正提示）。
★防回退（2026-10-23）：`ensure_cookies` 里若本次来源是 temp_cache 且已存 `jd_web_config.json` 比那份快照**更年轻**，直接沿用配置、**不覆写**——杜绝"新登录态被旧快照回填"。
★★**「浏览器开着就拷不动」这条 2026-10-15 的结论已在 2026-10-17 复测收窄——只适用于"整库复制"，不适用于脚本的取数路径**：
- 仍然成立的：`esentutl /y`（`-1032 JET_errFileAccessDenied`）、`robocopy /B`、`cmd copy`、Python `open()` 这些**要写句柄或整文件独占**的复制手段，Thorium 在跑时确实失败。
- **不成立**：脚本实际走的是 `CreateFileW(GENERIC_READ=0x80000000, FILE_SHARE_READ|WRITE|DELETE)` **只读直开 + 自己解析 SQLite**，2026-10-17 在「Thorium 正在运行、没开 9222」下实测成功（读到 1,114,112 字节正本、提出 45 个 cookie，且是重登后的新值：`flash` 已变、条数从 38→45）。所以**别一遇"浏览器开着"就叫用户关浏览器或加 9222** —— 先直接跑 `jd_web_signin.py cookie` 看它报的哪一级源。
- ⚠️ 自己写探测时**千万别带 `GENERIC_WRITE`**（`0xC0000000` 含写）：那样必得 `err=32`，会把"只读其实可用"误判成"库被独占"，进而误报【京东登录失效】或误让用户重开浏览器（本次实踩）。
- 因此「刚重新登录却仍 login_expired」两种成因都要查：①确实读到旧快照（脚本会在 msg 里带"N 分钟前的磁盘快照"）；②**会话被服务端整体作废**——见下条鉴别诊断。

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

★★**2026-10-17 定案：本节接口全部不再纳入每日总控**（总控的京东链只剩 `jd_web_signin.py auto` 一步）。那组 functionId 目前是**账号/会话级 403 风控**，而且**探测本身会让封锁从"只拒写"扩大到"读写都拒、连真人浏览器里页面自己发的请求也拒"**；协议细节保留在此供封锁解除后复测，复测请按 §14 的保守顺序（先只读观测，写请求最多 1 次）。

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

★★ **互动中心写接口（`pc_interact_assign_execute`）的 HTTP 403 空 body 不是"频率限流"**（2026-10-17 全量复测推翻旧结论）。当日**第一条** POST 即 403、同批 GET 全部正常，"连打才限流"根本不成立；旧文档写的「换日自动恢复」会让人白等。已逐项排除：
- **频率** → 单次即 403；**登录态** → 同日京豆 `pc_interact_sign_execute`（同一 `_req`/同一 TLS 栈）POST 成功 +2 京豆；
- **host** → 前端 bundle 里 `VITE_GATEWAY_DOMAIN:"api.m.jd.com"`，与我们一致，不是页面主机；
- **签名 body 口径** → 前端 `body:SHA256(JSON.stringify(o))` 而请求发原始 JSON，`_jd_node_harness.js` 早已同口径实现（`createHash('sha256')`），非差异点；
- **Origin 格式** → 脚本曾把 `INTERACT_REFERER`("https://interact.jd.com/") 原样当 Origin 发（畸形），已改 `_origin_of()` 归一为 `https://interact.jd.com`，**修好仍 403**；
- **sdtoken 缺失** → 403 响应头带 `X-Rp-Sdtoken: set;1800;<值>`（京东风控握手，浏览器 JS 会写成 cookie 再发；它寿命仅 1800s 且由 JS 运行时写入，**浏览器 Cookie 库里根本没有**）。已实现 `_sd_capture()` 自动握手并落 `jd_sdtoken.json` 带上重发——**仍 403，且每次响应都回一支新的**（即服务端从不认可我们回带的这支）；
- **eid** → 去掉 `x-api-eid-token` 仍 403；**body 形状** → `{eaId,type:5,itemId,extraType,rk,actionType}` 与前端的 `{eaId,type:0,rk}` 精简形都 403。
~~唯一剩下的差别是「这份 POST 要浏览器内的京东风控 SDK 会话」~~ → **该假设已推翻**（见下「真浏览器同样 403」）。
★★**无头也不行**（2026-10-17）：headless 实例注入完整 `.jd.com` cookie（83 条，页面确认已登录 `pin/unick` 齐全、`PSign/getJsToken/SHA256/_JdJrTdRiskFpInfo` 全在）后，**连页面自己**发的请求按 functionId 分化：`pc_interact_assign_query` GET / `pc_interact_reward_center` GET / `pc_interact_sign_execute` POST **全 403**，而同页 `pc_interact_kit_query`、`pc_interact_game_query`、`BEAN_*` 是 200。
★★**真浏览器同样 403 → 定性收口：封锁是账号/会话级、而且会升级**（不是客户端类型问题）：
- 早先 urllib 的 `pc_interact_assign_query` GET 还能 **200**（能列出「领取今日免费抽奖机会」等待做任务）；
- 反复诊断（约 7 条被拒 POST + 若干 GET）之后，**用户真实浏览器**（非 headless、日常 profile、已登录、SDK 齐全）里**页面自己**发的同 functionId 也变 403：`assign_query` GET、`reward_center` GET、页面自发的 `sign_execute` POST 全 403，同期 `kit_query`/`game_query`/`BEAN_*` 仍 200，且 DOM 已渲染不出任何任务项。
- → 两条同时成立：**「首次 403 不是频率限流」**（第一条 POST 就 403、同批 GET 全通）＋**「反复探测会把封锁从写扩大到读、连真浏览器一起拒」**。
- ★教训（写给未来的自己）：**诊断期同样要按最保守口径控制写请求**。逐变量 A/B 看着严谨，实际是在往风控计数器上加数。正确顺序：先只读观测（听页面自己发请求、看 DOM 渲染），确需写请求时**最多 1 次**，被拒即停手。
- ★老规则 `绝不可重试轰炸` **不是过时，而是比原先更重要**。判读：出现这类 403 → 当日不再打该 functionId 族；次日**先看页面自身请求是否恢复**（不主动发写请求），恢复了再谈自动化。
→ 已落地 `scripts/jd_interact_inpage.py`（页内执行版，用页面自己的 `PSign`/`getJsToken`/`SHA256` 复刻 `requestColorEncrypto`；`check` 只读自检、`auto` 领机会并抽）。它**只连你带 `--remote-debugging-port=9222` 启动的真浏览器**，且会**主动拒绝无头的 9222**（无头测出来的 403 是假结论，本人实踩）。★**封锁期间它打出的 403 不能用来证明「页内方案无效」**——真浏览器正被封时它必然同样 403，要等页面自身请求恢复后再复测才有意义。
现状处置（保留）：4s 节流 + 403 优雅降级（不中断、**绝不重试轰炸**）；`_is_waf_blocked()` 文案已改为「风控拦截」而非「限流」，判读时**不要再写"换日自动恢复"**。
★顺带暴露一个编排器缺陷：`headless_browser.instance_running()` 在你的 Thorium 明明在跑（14 个进程）时判成「无实例在跑」，于是**用真实 profile** 起了 headless；这种模式下 `cleanup(proc, tag=...)` **收不掉**（tag 只匹配临时 profile），会留下挂着 9222 的僵尸实例。手工精准回收口径：按 cmdline 含 `--headless` 过滤再 terminate，**绝不要** `taskkill //IM thorium.exe`（会误杀用户窗口）。

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

### 15) 华为码道 CodeArts Doer（2026-10-14 建成，2026-10-15 改为免抓包）

**★首选：读 CodeArts 桌面端登录态，不需要抓包、也不会再因 cookie 过期而失效。**
本机装了 CodeArts（Agent 插件版或 IDE 版）并处于已登录状态时，`hw_codearts.py` 会自动（★2026-10-16 双源）：
- **Agent 版**：`%APPDATA%\codearts-agent\User\globalStorage\state.vscdb` 取
  `secret://{"extensionId":"huaweicloud.authentication","key":"HuaweiCloudSession"}`
  → 外层是 VS Code 的 `{"type":"Buffer","data":[…]}`，内层是 Chromium **v10** 信封
- **IDE 版**（Roaming\codearts，字段命名不同）：`secretStorage/<sha256(key)>.enc` —— 内容是**整串 base64**，解码后才是 v10 信封；结构是 `{session:{accessKey,secretKey,securityToken,refreshToken,expiresAt(★毫秒整数),…}, loginContext:{pkcePair, dpopKeyPair:{privateKey/publicKey ★JSON 字符串}}}`，`hw_codearts_refresh._normalize_ide()` 归一成 Agent 版扁平结构。★**client_id 从 refresh_token 的 JWT 载荷取**（Agent=codearts-agent，IDE=codearts）——用错 STS 直接拒
- 主密钥都在 `<userData>\Local State` 的 `os_crypt.encrypted_key`（去 DPAPI 5B 头），两条链同一套解密
换机器/换用户名无需改代码：`HW_CODEARTS_UD` 可覆盖 userData 路径。

- 桌面端用的网关**不是** devcloud：`https://snap-access.cn-north-4.myhuaweicloud.com/v1/ops/{delivery,claim,confirm,invite/generate,tasks/conversation,events/conversation}`，`channel=IDE`（实测 IDE 与 WEB 两个 channel 的 delivery 返回完全一致）
- ★签名两个必须照抄的细节（错一个就 401/400）：`X-Sdk-Date` 要**先放进参与签名的 header 集合**再算 SignedHeaders（漏了 APIG 报 `401 APIG.0301 header x-sdk-date not signed`）；canonicalURI 按 `/` 分段转义后**末尾补一个 `/`**（`/v1/ops/delivery` → `/v1/ops/delivery/`）
- ★`channel` 只在 GET 进 query、在 POST 进 body：**claim 的 body 带 channel，confirm 的不带**；给 confirm 硬塞 channel 会 `HTTP 400 HDN.1000 "channel : unknown exception"`；给 POST 再挂 `?channel=` 同样 400
- 凭证寿命：`expires_at` 实测约 2 小时，客户端在跑就会自动续（`safelyRenewTokenInterval`≈1 小时）
- ★★**账号状态保持（2026-10-16 新增，参考 Our Free Model `src/oauth.ts` 逆向落地）**：客户端没开着时临时 AK/SK 会过期，此前脚本回退 devcloud cookie（几天必失效）→ 天天误报【华为码道失效】。现在 `hw_codearts.py` 过期时改调 `hw_codearts_refresh.get_valid_credential()`，**无需客户端在前台**直接离线换新凭证：
  - 用 session 里的 `refresh_token`（约 28 天）+ PKCE `codeVerifier` + DPoP 私钥（P-256）签 **ES256 DPoP proof**（`{alg:ES256,typ:dpop+jwt,jwk:公钥}` / `{htm:POST,htu:<STS端点>,iat,jti}`），`POST https://sts.cn-north-4.myhuaweicloud.com/v1/oauth2/tokens`（`grant_type=refresh_token`、`client_id=codearts-agent`、`application/x-www-form-urlencoded`）→ 拿回 `{credentials:{access_key_id,secret_access_key,security_token,expiration}, refresh_token:新值}`
  - ★**refresh_token 单次轮换**：每刷一次服务端下发新值、旧值作废。所以刷出的新临时 AK/SK 也**写进本地缓存 `hw_codearts_session.json`，2 小时有效期内复用**（一天跑多次只消耗一次轮换）；缓存的 refresh 三元组作为首选候选、vscdb 那份作次选（vscdb 可能落后于本地轮换）
  - ★终态判据（同一候选只试一次，绝不重试，防重放检测烧掉整条 token 家族）：`error=="invalid_grant"` / `error_code` 含 `ExpiredRefreshToken` / **实测 `error_code=="STS5.1806"` 且 `error_msg` 含 `invalid refresh token`**（旧值已被消费）→ 抛 `RefreshTerminal`，提示【重开 CodeArts Agent 登录】
  - DPoP proof 的 ES256 用 `cryptography`（DER 签名要转成 JOSE 的 `r‖s` 定长 64B）；本模块对外的 credential 同时给 camelCase（`accessKey/secretKey/securitytoken/expires_at`，兼容旧脚本）与 snake_case
  - 调试：`python hw_codearts_refresh.py probe`（看 session 结构+有效期，脱敏）、`refresh`（实刷一次）、`verify`（刷完立刻打 delivery 验真）
- 客户端登录链路（逆向留档，`resources/app` 未打包可直接读）：`extensions/huaweicloud.authentication/dist/plugin.js` 走 PKCE OAuth —— `https://codearts.huaweicloud.com/portal/authorize?...&uri_scheme=codearts-agent&port=<本地端口>`，`auth.huaweicloud.com/authui/login.html` 联邦登录，本地 `http://127.0.0.1:<10000+/oauth/callback>` 接 code，再 `POST https://sts.cn-north-4.myhuaweicloud.com/v1/oauth2/tokens`（带 **DPoP** JWE，EC P-256 密钥对存在 session 的 `loginContext.dpopKeyPair`）换 AK/SK/SecurityToken；`refresh_token` 用于 `grant_type=refresh_token`。会话结构字段：`account{id,label} / accessKey / secretKey / securitytoken / expires_at / domainId / refresh_token / loginContext{pkcePair,dpopKeyPair}`，`accessToken` 为空（HC 场景不靠 Bearer）
- **兜底（没装客户端才用）**：抓 `devcloud.cn-north-4.huaweicloud.com` 的 `PromptCenterService` 请求整行 cookie → `python scripts/hw_codearts.py init '<cookie>'`，走 `/chat/PromptCenterService/v1/ops` + `cftk` 头。★抓页面必须先去掉 `x-requested-with: XMLHttpRequest`（带着它网关一律按 API 路由 → 404）；`cftk` = cookie 里的 `devclouddevuibjtcftk`，脚本自动提取
- 活动清单：id=1 每日签到 1000 积分（`USER_LOGIN`）、id=2 学生认证 4000（需先认证，直领返 40001「需要先通过触发接口激活」）、id=3 邀请 1000/人、id=4 新用户注册 4000（`AUTO_GRANT`）
- ★两步不可省：`claim` → `CLAIMED`，`confirm` → `CONFIRMED`（积分才入账），confirm 返回 `totalAmount/remainingAmount/expireAt`（30 天有效）
- 幂等：`claimable=false` + `status=CONFIRMED` = 今日已领；硬提交返 HTTP200 + `code:40001「尚未到达权益刷新时间，暂时无法领取」`
- 脚本每次会打印 `[鉴权] snap-access + 桌面端 AK/SK（免抓包·可能来源 client-fresh/cache-live/refreshed）expires_at=…` 或 `[鉴权] devcloud cookie/cftk（抓包）`，据此判断走的哪条链路

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

### 17) 字节 TRAE（2026-10-16 建成）

协议来自 GitHub 开源项目 **Ebony-Vinyl/dsh-our-free-model**（`vendor/channel-pack/src/trae-credits.ts`，其重构自 trae-mate 参考实现）的分析移植。电脑打开 trae.ai 登录后，用 Reqable/mitmproxy 抓任意一条 `api.trae.cn` 请求发我：

- `Authorization` 头 = `Cloud-IDE-JWT <access_token>`（★不是 Bearer）
- `X-Uid` 头 = 账号 user_id

- ★接口：`POST /trae/api/v2/ug/checkin_credits/status`（body `{}`，返 `checked_in/credits/enable`）、`POST /trae/api/v2/ug/checkin_credits/claim`（body `{}`）、`POST /trae/api/v2/pay/ide_user_ent_usage`（余额，body `{"require_usage":true,"req_source":2}`）
- ★★**claim 幂等但不可区分**：已签到账号重复领取同样返回 `{code:0,message:"success"}`，与真正成功无法分辨 → 脚本**必须先查 status.checked_in**；且 claim 响应**不含积分数**，领取成功后**回查 status.credits**（实测单日 150）
- ★设备身份按 uid **确定性派生**（对齐 trae-mate `device_map.rs`）：15 位数字 device_id / UUIDv4 market_user_id / 64hex session_id，算法为 SHA256(`salt:uid` + counterBE32) 种子流 → 多账号各自独立设备配额，脚本已完整移植
- ★错误冷却（对齐 trae-mate `cooldown.rs`）：`code 1005`=套餐不含签到（12h）、`code 9074`=签到人数过多（300s）、HTTP 401=会话失效（需重新登录）、429=软限流（60s）
- 断线症状：401 → 重新登录 TRAE 桌面端重新抓包

### 18) 有道 LobsterAI（2026-10-16 建成，★★2026-10-18 起免抓包）

协议来源同上（`lobsterai-credits.ts`，重构自 lobsterai2api/sigin.py）。★★**现在优先用桌面端本地凭证，不用抓包**：本机装了并登录过 LobsterAI 桌面客户端即可，脚本只读它的 `lobsterai.sqlite`。手工抓 `Authorization: Bearer <access_token>` 或 Web 门户 cookie 只剩兜底（`--auth bearer|cookie`）。

- ★三步签到：①`GET /api/client-activities/slot?placement=desktop_sidebar&clientVersion=<动态版本号>&containerApiVersion=2&platform=win32`（槽位参数为固定值，照抄客户端，改了可能拿不到活动）→ ②`GET /api/client-activities/{activityCode}/context?configRevision=<N>`（`state.claimedToday` + `actions[]` 双重预检）→ ③`POST /api/client-activities/{activityCode}/actions/check_in`（body `{configRevision, idempotencyKey:uuid4, payload:{}}`，**客户端幂等键**）
- 版本号从 `api-overmind.youdao.com/openapi/get/luna/hardware/lobsterai/prod/update` 动态取（★非统一信封：外层 code/msg，载荷在 `data.value.version`），失败兜底 `2026.9.4`；★桌面端 sqlite 的 `client_sidebar_banner.schedule.desktop_sidebar.v2` 里也存了一份 `clientVersion`（本机实测 `2026.10.13`，比硬编码兜底新），优先用它
- ★余额用 `GET /api/user/profile-summary`（`creditItems[]` + `totalCreditsRemaining`）——**不是** `/api/user/quota`（后者只显示 freeCreditsTotal=300，不含活动积分；实测 profile-summary 5297.72 vs quota 300）
- 断线症状：`data 为空（accessToken 可能已失效）` / HTTP 401·403 → 走下面的续期，而不是叫用户抓包

#### ★★账号状态保持（2026-10-18 改造，逆向 Our Free Model `lobsterai.ts` + `lobsterai-oauth` 的 refresh 调用点）

**为什么必须改**：2026-10-18 实报【LobsterAI登录失效】根因是 `lobsterai_config.json` 里的 `lobsterai_web_session` 被服务端重建后变陈旧，而本平台**不在第 0 步 `cookie_sync` 名单里**（只有魔搭/小浣熊/Loomy 会每天自动轮换）——靠浏览器 cookie 就必然周期性烂掉。桌面端本地凭证则稳得多：实测 `accessToken` 是 **JWT**（payload `accountMode/exp/iat/sub/type/yid`），`exp` 距签发约 **30 天**。

- 凭证来源（只读，客户端在跑也能读）：`%APPDATA%/LobsterAI/lobsterai.sqlite` → 表 `kv`
  | kv key | 给的字段 |
  |---|---|
  | `auth_tokens` | `accessToken` / `refreshToken` |
  | `keyfrom.attribution.v1` | `firstKeyfrom` / `latestKeyfrom`（★续期要带） |
  | `auth_user` | `userId` / `yid` / `nickname`（手机号自动脱敏） |
  | `installation_uuid` | `uuid` |
  | `client_sidebar_banner.schedule.*` | `clientVersion` |
  打开方式先 `mode=ro&immutable=1` 再回退 `mode=ro`（Electron userData 有两个写法 `LobsterAI`/`lobsterai`，逐个试）
- 续期：`POST /api/auth/refresh`，★**匿名头**（只带 Accept/Content-Type/User-Agent，**不带 Authorization**）；body `{firstKeyfrom, latestKeyfrom, version, uuid, userId, refreshToken}`
  - ★`latestKeyfrom` 用**存储的原值**、不取当前时刻——官方客户端的 RefreshToken 分支从不更新该字段，每次发的都是登录那一刻的值（照抄，别"优化"成 `Date.now()`）
  - 响应 `{code:0,data:{accessToken, refreshToken, expiresIn, user{...}}}`；★`refreshToken` **可能不在响应里**，必须沿用旧值（覆盖成空串＝亲手废掉续期能力）
  - 过期时间**只由 `expiresIn` 或新 JWT 的 `exp` 算**，解不出就当作未知（不刷、等真失效再说）
  - 实测错误形态：伪造 refreshToken 打过去 → `HTTP 401 {"code":40100,"message":"登录已过期，请重新登录","data":null}`；`40100/40101/token rejected/refresh token was rejected` 与 401/403 一律当**终态**，★绝不重试（refresh_token 是轮换制，同一支只试一次）
  - ★新凭证只写 `lobsterai_live_cache.json`，**绝不回写 sqlite**（客户端持有同一支，回写会争抢）
- 触发时机：`REFRESH_LEAD=1h`——距过期不足 1 小时才刷（OFM 的 `REFRESH_LEAD_MS` 同语义；早期"每次跑都全量刷"会把轮换凭证烧光）。日常 `auto` 若被服务端判过期，会自动续一次再重试
- 命令：`lobsterai_credits.py keepalive`（只报有效期与是否该刷）；`--auth cookie` 可强制回退旧链路
- ⚠️ 未验证项：`/api/auth/refresh` 的**成功**分支本机还没真跑过（跑一次就会作废桌面端那支 refresh_token，而现凭证还剩 30 天，不值得拿用户的登录态做实验）。终态/错误分支已实测。真要启用时先看 `keepalive` 输出、首次手动盯结果

### 19) MiniMax Code（2026-10-16 建成）

协议来源同上（`minimax-credits.ts`，端点来自 asar UI chunk 直读+实测）。★★**2026-10-17 起已免抓包**，见下节「账号状态保持」；手工抓 `Authorization: Bearer <access_token>`（前缀 `mmoat_`，60 字符，非 JWT）只剩兜底用途。

- ★接口：`GET /minimax-cloud/api/v1/signin/status?timezone_id=Asia/Shanghai`（七日面板）、`POST /minimax-cloud/api/v1/signin/claim?timezone_id=...`（body `{}`）、`GET /minimax-cloud/api/v1/credit/details`（余额）
- ★四个实测结论：①`timezone_id` 必填且为**客户端 IANA 时区名**（不带/非法都报 `invalid timezone_id`，且那是 HTTP 200）；②业务码在 **`base_resp.status_code`**（不是 `code`）；③`points` 是总数、`bonus_points` 是其中「额外」部分，**不得相加**（实测 800 档日 bonus 400，按钮就是「签到得 800」+「额外400」角标）；④今日已领判据 = **`is_today && status==3`**
- ★幂等：`claim_result`（1=本次真领取 / 2=已领过），重复领取同样 HTTP 200
- 断线症状：`base_resp.status_code` 非 0 → 按 status_msg 处置；401/403 且首行 `[鉴权]` 已写明四级用尽 → 叫用户**打开 MiniMax Code 重登一次**（不要再让人抓包）

#### ★★账号状态保持（2026-10-17 改造，参考 Our Free Model `vendor/channel-pack/src/minimax-oauth.ts`）

**为什么必须改**：`access_token` 寿命**只有约 1 小时**（`expiresAtMs` 距签发实测 ≈3600s），而 MiniMax Code 桌面端**自己每 ~50 分钟就续期并轮换**它。所以手工抓包写进 `minimax_config.json` 的那份必然几天后 401 —— 2026-10-17 实报【MiniMax失效】就是这个原因：config 里那份早被轮换掉，而 `auth.json` 里的活 token 一打就通（HTTP 200、`base_resp.status_code:0`）。

- **四级凭证解析顺序**（`minimax_credits.py` 的 `Session.resolve()`，首行 `[鉴权] 来源=…` 会写明走了哪一级）：
  1. 桌面端 `~/.minimax/auth/prod/cn/mcode-public/auth.json` → `records` 是**以 `com.minimax.mcode.oauth.prod.cn\0<随机前缀>` 为键**的字典，字段 `accessToken/refreshToken/tokenType/clientId/scopes/audience/expiresAtMs/generation`（★键里带 `\u0000`，别按名字匹配，按 `clientId=="mcode-public"` 挑）。客户端在跑着即未过期 → **直接白嫖它的自动续期，一次刷新都不发**
  2. 本地缓存 `minimax_session.json`（我们自己刷出来的那份，可能**领先**于桌面端）
  3. 两份都过期 → 离线刷新：`POST https://account.minimax.cn/oauth2/token`，body `grant_type=refresh_token&refresh_token=<mmort_ 前缀 60 字符>&client_id=mcode-public&scope=agent.default&audience=agent-backend`（`application/x-www-form-urlencoded`）
  4. 兜底 `minimax_config.json` 里手工抓的 `access_token`
- ★**单次轮换 + 不回写桌面端**：刷新得到的新 `refresh_token` 只写我们自己的 `minimax_session.json`，**绝不写回 `auth.json`**（客户端在跑会与我们争抢同一支，写回去是把用户的 IDE 往死里整）。候选顺序固定「缓存 → 桌面端 → config」，**同一支只试一次**；`invalid_grant/expired/revoked` 视为**终态**直接断（防重放烧掉整条 token 家族），网络类异常才继续试下一支
- ★令牌响应硬校验照抄客户端 `parseMinimaxTokenGrant`：`token_type` 必须 `Bearer`、`scope` 必须含 `agent.default`、`expires_in` 必须为正数。★**过期时间只能由 `expires_in` 算** —— `mmoat_` 不是 JWT（0 个点），别去解 payload；若改成「优先解 JWT、解不出就不写 expires_at」，有效期会彻底丢失、账号永远显示「未知」
- ★`Session.request()` 在业务接口遇 401/403 时**强制刷新并重试恰好一次**（`_retried_401` 防成环），且 force 分支**不回退 config 旧 token**（它刚刚才 401 过）
- 自检命令：`python minimax_credits.py auth`（只读，报来源/各级 refresh_token **有无**——永不打印值/长度不外泄，并实打一次接口验真）；`auth --force` 强制刷一次
- ⚠️ **`auth --force` 别在 MiniMax Code 开着的时候随手打**：它会真消耗一次 refresh 轮换，客户端那份随即落后。桌面端在跑时走第 1 级即可，刷新分支只在「两份都过期=客户端没续期（多半是没开）」时才触发——这正是我们把优先级排成「新鲜 token 先于刷新」的原因
- 判读铁律：首行 `[鉴权] 来源=桌面端 auth.json` = 保活正常；`= 离线刷新 refresh_token` = 客户端没跑、已自动续上；`= config 手工凭证` = 桌面端未装/未登录且无 refresh 可用，才需要人工介入

### 20) WorkBuddy 国际版（2026-10-16 建成；已并入总控 9-wb「WorkBuddy系」单链第 3 步）

协议来源：**本机 WorkBuddyAI 5.8.3 的 `resources/app.asar` 逆向**（不是 dsh 项目——dsh 对 5.5.2 的判断"国际版无签到接口"在 5.8.3 已被推翻，见下）。

- ★国际版与国内版**只有两处差异**（同一套 `CloudAccountRepo` / `DesktopAccountRepo`）：
  - 国际版 `billingPrefix=""` → **路径不带 `/v2` 前缀**；国内版是 `/v2`
  - 国际版 `getCheckinRequestHeaders()` 是空实现 → **不带** Turing Shield 设备指纹头
- 接口（域 `www.workbuddy.ai`）：`POST /billing/meter/checkin-activity-status`（状态，body `{}`）、`POST /billing/meter/daily-checkin`（领取，body `{}`）、`POST /billing/meter/get-user-resource-summary`（余额）
- ★**判定只看响应体 `code`，不能看 HTTP 状态**：重复领取是 **HTTP 400 + code 10001**（"今天已签到"），属幂等成功
- ★★**国内版登录态在国际版域无效**：实测拿 `www.workbuddy.cn` 的 token 打 `www.workbuddy.ai`，带 token / 带垃圾 token / 不带 token 都返回同一个 **APISIX 3.12.0 网关 401**（openresty HTML，不是业务 JSON），且响应带 `Set-Cookie: session=; Expires=Thu, 01 Jan 1970`（清 session）→ 是**网关层拦截**，换国内 token 重试没用；同域 `/v3/config` 却 200 `code:0`，说明站点可达、被挡的只是 `/billing/meter/*`
- ★**401 的头号原因其实是 User-Agent，不是 cookie**（2026-10-16 对照取证）：同一个**有效** `session` cookie，UA 用客户端串 `WorkBuddyAI/5.8.3` 或留空 → `401` openresty HTML；UA 换成浏览器串（Chrome/122）→ `200 {"code":0,…}`。脚本已默认发浏览器 UA（可用 config 的 `user_agent` 覆盖）；上面那条「带/不带 token 都 401」的国内 token 对照实验若也是用客户端 UA 做的，结论**需按 UA 复测**
- ★因此鉴权材料是 **www.workbuddy.ai 的 session cookie**（`session` / `session_2`，浏览器登录后 Chromium 会落盘，可直读），脚本 `cookie` 优先、`access_token` 兜底。**需要国际版独立账号**
- 未配置登录态时脚本输出 `[skip]` 并退出 0 —— **不是失效**，别误标【XX失效】；`active=false` 输出「活动未开启」同样退 0（服务端按账号开关，非失效）
- 抓包：浏览器登录 `https://www.workbuddy.ai` 后随便点一下触发 API，过滤 `www.workbuddy.ai`
- 断线症状：出现"网关拦截 HTTP 401…" → 先确认发的是浏览器 UA，**再**怀疑 session 是否失效（顺序反了会让人白抓一次 cookie）

### 21) Qoder 国际版（2026-10-16 建成，并入既有 Qoder 脚本）

逆向来源同上（`business.mjs` 的 `src/qoder-product.ts`）。Qoder 是**两个 product**：

| | id | openApiBase | authBase |
|---|---|---|---|
| 中国版 | `qodercn` | `https://openapi.qoder.com.cn` | `https://qoder.cn` |
| 国际版 | `qoder` | `https://openapi.qoder.sh` | `https://qoder.com` |

- 签到端点两区**同形**（`/sash/api/v1/me/campaigns` + `/{id}/claim`），头也同为 `cosy-clienttype: 10`（★缺任何 cosy-* 头，服务端返回 `{"showCampaign":false,"campaigns":[]}`，不报错但拿不到活动）
- ★按「同企合并」原则已并入 `qoder_credits.py`，用 `--variant cn|intl|all`（默认 all 两区串行），**不新增任务**；国际版未安装时静默跳过（不是失效）
- 国际版 user-data 目录给候选 `%APPDATA%/com.qoder.app.stable` 与 `%APPDATA%/Qoder`（本机未装国际版，未实测到真实目录名）；凭据解密链与 CN 完全相同（Chromium v10 信封）
- ★★**领取逻辑 2026-10-18 按 OFM `qoder-credits.ts` 校正三处**（都属"静默漏领/误报失效"类）：
  - **全领而非领一个**：官方对**所有** `actionType==CLAIM_BENEFIT && claimStatus==CLAIMABLE` 逐个 claim 再累加，**不看 `benefit.kind`**；旧版只领挑中的那一期，服务端若同挂多个可领活动就会漏
  - **每日 10:00（UTC+8）换期**：`campaign_refreshed_today()` = 北京时间小时数 ≥10。10 点前即使列表里有 `CLAIMED`，那也是**昨天那轮** → 报「今日尚未刷新」而不是「今日已领」（`QODER_CAMPAIGN_REFRESH_HOUR_UTC8`）
  - **「空列表」≠「失效」，要先鉴别账号未开通**：`campaigns` 里没有任何 `CLAIM_BENEFIT` **且** `GET /sash/api/v2/me/usage` 的 `qoderUsage.addOnQuota` 字段缺失 ⇒ 该账号**从没在 Qoder 侧开通过每日 100**，唯一解法是**用官方桌面客户端登录一次该账号**（照 OFM `isQoderNotActivated`）；旧版一律甩锅给"cosy-clienttype 头缺失"，会让人白折腾
- #### ★账号状态保持（2026-10-18 移植 OFM `qoder-oauth.ts`，但★默认不动手）
  `POST /api/v1/deviceToken/refresh`，body `{refresh_token, machine_id}`；响应键按别名取 `token|device_token|access_token` + `refresh_token` + `expires_at|expiresAt` + `refresh_token_expires_at` + `user_id` + `user_name`；★响应**可能不带新 refresh_token**（沿用旧的，不能覆盖成空）；HTTP 401/403 或 `invalid_grant/expired/revoked` 当**终态**、同一支只试一次；新凭证只写 `qoder_<variant>_live_cache.json`，★绝不回写 `auth.v1.dat`。
  ⚠️ **两条本机实况让这条路暂时不能用**：① 桌面端 `auth.v1.dat` 只有 `schemaVersion/token/refreshToken/expiresAt/refreshTokenExpiresAt/user{}`，**没有 `machine_id`**，`%APPDATA%/Qoder CN/SharedClientCache/cache/machine_token.json` 也不存在 → 取不到就不猜、不发；② 客户端持有**同一支** refresh_token，我们刷一次就把它作废，它会在下一次自续期时被拒而被迫重登（★本机这个 Qoder 就是当前正在用的 IDE）。故 `keepalive` 只在**已过期/临期(<1h)** 且显式 `--force` 时才发请求。
  现值实测：CN token 到期 2026-11-13（剩 ~26 天）、refreshToken 到期 2027-10-09 —— 离需要保活还远，先按"到期再说"处理。
  另有 `Cosy-MachineToken` / `Cosy-MachineType` 两个头（OFM 从 `machine_token.json` 或 `%USERPROFILE%\.qoder-cn\.bin\umid-*\runtime-info.exe 3 --account-stdin` 现取）——本机 2026-10-15 二分实测**缺了照样 200**，属可选补齐，不作为前置条件。

### 22) ZCode（智谱，2026-10-16 建成）

- 端点（origin `https://zcode.z.ai`）：`GET /api/v1/zcode-plan/billing/balance`、`GET /api/v1/zcode-plan/billing/preview?app_version=&platform=win32`、`POST /api/v1/zcode-plan/billing/claim`（body `{plan_id}`）、`POST /api/v1/event/report`、`GET /api/v1/client/configs`
- ★**必须先补激活上报**（`app_launch` + `app_daily_active`）再查 preview —— 服务端不主动推送活动，不补就会拿到空列表 → **稳定误报「今日已领」**（与 Qoder 那次「按返回顺序取首个 → 静默漏领」同类坑）
- ★今日已领判据 = **可领 plan 数为 0**（不是「列表为空」，因为空列表也可能只是没补激活）
- ★`code 1003` = 已领取，**属成功**（当失败会让定时任务反复误报）；`3007` = captcha 无效
- ★★领取端点**始终强制索要阿里云验证码**（不带/带非法都 `400/3007`，且校验前置于 plan 校验），每个 plan 都要**重新 mint** param（复用得 3007）⇒ `status` 全自动，`claim` 需注入 `captcha_param`
- ★`captcha_region` 由**服务端下发**（`client/configs`，cn / sgp），**不能写死**——写死则非 cn 区 100% 领不到；脚本留空时自动拉取
- ⚠ 凭据：读官方客户端 `~/.zcode/v2/credentials.json` 的免抓包能力**已被上游 2026-10-05 删除**
- ★★**但网页登录态仍可免抓包取**（2026-10-16 从其前端 bundle 反查出存储键并实测通）：`zcode_jwt` = Thorium `zcode.z.ai` 源 localStorage 的 **`zcodejwttoken`** 键（leveldb 明文，可像阿里云盘那样按值搜 `eyJ…`）；`device_mid` = 同域 cookie **`visitor_id`**。★`X-Device-Mid` 是**必填**：只带 Bearer 打 `billing/balance` 返 `400 {"code":3001,"msg":"parameter error"}`，带上 `visitor_id` 即 `200 code:0`
- 前置条件：在浏览器里登录过一次 zcode.z.ai（走 `oauth` 后 JWT 才写进 localStorage）

### 23) 滴滴出行（2026-10-23 建成，契约静态还原自 GitHub `hudiemon/didi`）

- 两个请求实例（抄自客户端，别混）：
  - **领券** `https://union.didi.cn`：`POST /api/v1.0/reward/receive`，**无 wsgsig**，body 带 `token` + `env` 对象（isOpenWeb/isHitButton/dchn/newAppid/newTicket/fromChannel/xAxes/yAxes/timeCost/userAgent）
  - **福利中心** `https://ut.xiaojukeji.com`：POST + `params.wsgsig`，body 带 `token` + `env`（**JSON 字符串**，不是对象！）+ Origin/Referer 均 `https://page.udache.com`
  - **活动初始化** `https://api.didi.cn/webx/chapter/product/init`：`prod_key=welfare-center`，wsgsig 签的是 **body 本身**（此 body 不含 token）；响应 data 的键要**增量合并进后续请求的 defaultPayload**
- 接口清单：`/api/v1.0/reward/receive`（4 业务线：ut-dunion-wyc 打车 / ut-dunion-car 加油 / ut-dunion-kf 花小猪 / ut-dunion-freight 货运，各带固定 dsi）、`/ut/welfare/api/home/getBubble`、`/ut/welfare/api/action/clickBubble`、`/ut/welfare/api/action/dailySign`、`/ut/welfare/api/home/divideData`、`/ut/welfare/api/action/joinDivide`、`/ut/welfare/api/action/divideReward`
- ★**wsgsig 算法**（已与 Node 原版字节级比对一致）：`sig=md5('R4doMFFeMNlliIWMq'+payload)` → `ts={unix}&v=1&os=web&av=02&kv=0000010001&vl={UTF8字节数}&sig={sig}` → 4 随机字节做掩码逐字节 XOR → `'dd03-'+base64(掩码+混淆后).rstrip('=')`。★`Buffer.from(String.fromCharCode(...))` 按 **UTF-8** 编码（码元≥128 膨胀 2 字节），Python 侧必须照搬（`chr(b)…encode('utf-8')`），用 latin1 会错
- 响应约定：`errno==0` 成功；领券 rewards 在 `data.rewards[].coupon`（name/max_benefit_capacity/usage_limit）；签到福利金在 `data.subsidy_state.subsidy_amount`；瓜瓜乐 `data.divide_data.divide['YYYY-MM-DD']`（**明日**的 reward.type/activity_id 用于报名，**今日**的 task_id/activity_id 用于领奖）
- ★**失效判据**（2026-10-23 无效 token 冒烟实测，三接口均按契约响应）：ut 侧 `errno=6001`「登录信息失效，请重新登录」；union 侧 `errno=1000010005`「登录失败」。★`product/init` **不校验 token**（无效 token 也返 `errno 0 success`，且响应 data 的键要增量合并进 defaultPayload）——init 只负责灌会话字段（xpsid/xpsid_root 等），**验 token 必须用 getBubble**
- 凭证获取（**不是抓包，是浏览器控制台**）：打开领券页 `https://vv.didi.cn/a8ZdG0j` → 点「立即领取」登录 → F12 控制台 `localStorage.getItem('didih5_trinity_login_ticket_role_121230').replace(/"/g,'')` → `didi_coupon.py init '<token>'`（多账号 `;` 分隔）。约 7-30 天有效
- ★★**`sync` 命令（2026-10-23 实跑验证）**：Thorium 开 9222 后 `python didi_coupon.py sync` 自动从浏览器登录态取票（CDP Runtime.evaluate 读 localStorage 为主 + leveldb 兜底），不用手抄。★三个实证坑：①localStorage 的值**自带双引号**（JSON 字符串化），不剥会被服务端判 6001——官方 README 的 `.replace(/"/g,'')` 就是干这个的；②票据键的 **role 后缀随活动变**（本账号实测是 `role_30004` 不是 `role_121230`），必须用**前缀匹配** `didih5_trinity_login_ticket`；③CDP 连接要 `suppress_origin=True`，否则 WS 握手 403
- ★**失效判据**（2026-10-23 无效 token 冒烟实测，三接口均按契约响应）：ut 侧 `errno=6001`「登录信息失效，请重新登录」；union 侧 `errno=1000010005`「登录失败」。★`product/init` **不校验 token**（无效 token 也返 `errno 0 success`，且响应 data 的键要增量合并进 defaultPayload）——init 只负责灌会话字段（xpsid/xpsid_root 等），**验 token 必须用 getBubble**
- ★**幂等态**：签到重复返 `errno=40009`「重复签到」= 今日已签（算成功）；领券侧 auth 判失效加**阈值 ≥2 线**同时 1000010005——实测有效 token 也会单线返登录失败（花小猪 kf 线活动后端更严）
- ⚠ **领券 campaign 状态（2026-10-23 真账号实测）**：4 条业务线（wyc/car/kf/freight）对本账号返「当前城市无活动」（kf 线单返登录失败）——上游 hudiemon/didi 2025-04 停更，硬编码的 dsi campaign 大概率已轮换；页面（ut-dunion-coupon-bag，走 `webx/v3/productInit`）自身不加载这 4 个 prod_key 的数据。**签到/气泡/福利金链路完全正常**（实测签到 +1 福利金）。要修领券需在页面上做一次真实领取动作抓当前 campaign 结构
- ⚠ 上游仓库 2025-04 停更，接口可能已变迁——整体 errno 非 0 时先按「接口变迁」排查，别急着重抓 token

---

## 二、我来自动完成

拿到凭证后（来源不管是 §〇 的 Reqable 自动抓包，还是 §一 的手工粘贴），我会：
1. 解析其中的凭证字段（token / openId / sessionid 等）；
2. 在 `scripts/` 下生成对应 json 配置（`gr_config.json` / `mt_config.json` / `csair_config.json`），写前自动备份旧值；
3. 立即跑一次验证（查状态 / 试签到 / 试领券），把结果贴给你确认；
4. 确认通过后按你的要求挂上定时任务（如每天清晨自动执行全平台）。

脚本自带幂等：当天已完成会自动跳过，删除对应 `*_state.json` 可重跑。



**每日自动覆盖范围**：
- 美团：惠省小程序首页红包墙领券（`couponViewId` 判可领、rightCode 级幂等，当天后出现的新批次也能领到）+ 营销页红包（配了 recallToken 才有）+ 福利社 H5 活动页（限时抢券 + 天降掉券，活动 ID 自动发现）+ 分销会场每日券包（grant 链路，单日 ¥180+）+ 分销中心跨券墙
- 南航：发现新境签到、营销活动签到领里程（活动 ID 动态探测，过期活动自动跳过）、签到抽奖机会检测与消耗（消耗需新鲜小程序 sessionId，半自动）
- ~~利宝：阅读文章积分 3 篇（每篇 +20，当日幂等）、做任务领积分（完成后自动送抽奖机会）、每日抽奖 1 次（幂等）~~ **★2026-10-25 起移出每日自动覆盖**（服务端风控未解除，本人修复后按 `scripts/cron_prompt_2-libao_removed.txt` 恢复；脚本能力本身不变）
- 魔搭：登录魔粒 +250（会话副作用，访问首页自动入账）+ 点赞刷分 +40（star/unstar 循环 20 次）
- WorkBuddy：Buddy 加油站签到 +100/天（连续 7/14/28 天有额外档）+ 派猫猫旅行闭环（先领后派，5~10/天）+ **成长中心 6 项补齐**（`wb_growth.py`：盲盒抽奖 / 连登三档兑换 / 断登补签 / 接任务 / 领任务奖 / 能量开 Buddy 盲盒，先只读判有无资源、没有就跳过，全幂等；第 2 个子步骤）
- 办公小浣熊：每日 300 积分确认（活跃自动入账）；accessToken 临期自动用 refresh_token 换新
- Loomy：每日积分确认（活跃自动入账）；纯 cookie 鉴权，失效需重抓。桌面端新手任务线（`loomy_desktop_tasks.py`，8 项共 10000 分，账号体系独立）每日检测——未完成自动补齐、满额零副作用跳过、session 到期（14 天）标注【Loomy桌面登录失效】提醒重登
- 天翼189云盘：每日个人签到领随机空间（`c189_signin.py`，实测 +26MB/天；SSON cookie 鉴权，sessionKey 由 getSessionForPC 换取；幂等，当天重复跑零副作用）
- 京东京豆：每日京豆签到（`jd_web_signin.py auto`，+N 京豆/日 + 连签加成；浏览器 PC 登录态，脚本实时提取 cookie；幂等，已签跳过）。★互动中心天天抽奖**已移出总控**（账号/会话级 403 风控，见 §9b/§14），`interact` 子命令仅留作封锁解除后的复测入口
- 阿里云盘：每日签到（`aliyun_signin.py auto`；凭证从浏览器 Local Storage 实时提取，无需 cookie/CDP；`sign_in_list` 兼做签到与查状态，幂等）
- 千问办公：每日 100 积分核对（`qwenwork_credits.py auto`；凭证实时解密桌面端 `auth-v2.dat`，免抓包；免费版积分**服务端自动发放、当日有效**，脚本核对日包余额 + 尝试签到接口）
- Qoder CN：每日 100 Credits 领取（`qoder_credits.py auto`；凭证实时解密桌面端 `auth.v1.dat`，免抓包；campaigns 动态发现 → **领取全部 CLAIMABLE 活动**并累加，30 天有效；服务端幂等，重复提交 `replayed=true` 不重复发放；★10:00 换期前跑会区分「今日已领 / 今日尚未刷新 / 账号未开通」三种情形，不再笼统报失效；`keepalive` 子命令报有效期，续期默认不动手；排在阿里系链末位，规避每日 10:00 窗口边界）
- 华为码道：每日签到领 1000 积分（`hw_codearts.py auto`；`delivery` 判 `claimable` → `claim` → `confirm`；已领时 `claimable=false`，脚本跳过并打印积分桶余额）

---

## 二·五、账号保活统一层（2026-10-18 改造）

保活失败的形态高度重复（凭证到期 → 401 → 叫用户重抓包），但原来 20 多个脚本各自实现解密、
过期计算、终态判断、输出措辞，于是同一支单次轮换的 refresh_token 会被两处同刷互相作废、
临期预警全靠猜、401 与业务码非 0 混成同一种"失效"。现在**判据只有一份出处**：

### `scripts/credential_core.py`（共享纪律层，不含平台知识）

| 函数 | 干什么 | 为什么必须有 |
|---|---|---|
| `expiry_ms(expires_in=, expires_at=, token=)` | ★**唯一**的到期时间入口：相对值 > 绝对值 > JWT exp > None | 旧代码各处按"感觉"猜寿命，临期预警全是噪声；Qoder 的尺度判据（`>1e12` 当毫秒，否则当秒）也在这里 |
| `needs_refresh(exp, lead=3600s)` | 距过期不足 1h 才续期；**解不出到期一律返回 False** | OFM 早期"每 30 分钟全量刷"会把轮换凭证烧光（其 issue !IKIRTT） |
| `refresh_allowed / mark_refresh_attempt` | 按 **RT 指纹**记账，同支 6h 内拒发第二次 | 两个脚本同天各刷一次会互相把对方的 refresh_token 作废——这是跨进程问题，单个脚本自己防不住 |
| `is_terminal(status, text)` | 401/403 + 各平台终态码（`40100/40101`、`200003`、`invalid_grant/expired/revoked`…）判死 | 终态继续重试只会彻底烧掉 token 家族；京东那类风控还会把封锁越打越宽 |
| `RefreshTokenExpired` | 终态异常类，★`name` 固定这个字符串 | 调度按**名字**识别终态，改名会静默退化成无限重试 |
| `record_ok / days_since_ok_any` | 成功心跳（总控统一记，不在各脚本埋点） | 美团/利宝/小米/南航的凭证**没有到期字段**，心跳是失效前最早可观测的信号 |
| `read_v10_json / read_sqlite_kv / find_first` | 官方客户端存储的通用读法（DPAPI+v10 信封 / Electron sqlite kv） | 原来 5 处各写一份解密，任一处改法会让其余几处静默退化 |
| `auth_line(...)` | 统一 `[鉴权][平台] 来源/到期/剩余/续期能力` 首行 | 判读口径统一。**只做加法**：原有 `【XX失效】`/`login_expired` 措辞全部保留，日报判读靠它们 |

### `scripts/keepalive_status.py`（全平台体检，★已挂在总控最前面）

```
python scripts/keepalive_status.py           # 单独跑全表
python scripts/keepalive_status.py --warn    # 只看需要动作的
```
体检**只读本地文件/config/sqlite，不发业务请求、不启动浏览器**，异常也只降级成一行提示——
它挂在编排开始前但**不属于任务图**：不占 `max_workers`、不进逐任务耗时表、不影响总控退出码。
退出码 0 无需动作 / 2 需盯 / 1 会直接领不到。

表里两列是关键：

- **根凭证到期**：只有"坏了必须用户重登"那一层参与临期(≤3天)/过期判定。
  派生短效凭证（阿里云盘 AT 7200s、MiniMax AT 约 1h、华为临时 AK/SK 约 2h、京东 sdtoken 1800s、
  天翼 sessionKey）**寿命短是设计如此**，按 3 天阈值报它们等于天天误报——已按 `root=False` 排除。
- **心跳天**：该平台在总控里上次成功的距今天数；>1.5 天即标「心跳陈旧」。
  这是"服务端不给到期时间"那批平台（美团/利宝/小米/南航/掘金/农场）唯一的衰减信号。

★判读规则：**「无到期值」「未安装」「自动轮换」都不等于失效**，别写进【XX失效】；
只有「已过期 / 缺凭证 / 读取异常 / 心跳陈旧 / 临期」才是要处理项。

### 第 0 步凭证同步：从 3 家扩到 5 家

`cookie_sync.py` 名单新增 **天翼189（SSON，`mode=value` 传裸值）** 与 **WorkBuddy 国际版
（`session`/`KEYCLOAK_SESSION`，`mode=cookie_flag`）**；两家的键名是从本机现有 config 实解出来的。

★★**同步的第一铁律：不能让凭证越同步越坏**（2026-10-18 实踩——临时 profile 只注入到 90 个
cookie，写回的 WorkBuddy 国际版 cookie 校验 401，而旧那份本来是可用的：它返回过 `active=false`
这种业务应答。事故催生下面两条）：

1. **先验证再算成功**：所有平台的 `init` 必须在写完后真发一次只读请求。`workbuddy_intl_credits.py
   init` 原来只打「已写入」就返回 0，现改为打 `[ok] 凭证已写入并校验通过` / `[x] …校验失败`——
   cookie_sync 靠这行判成败。**写盘成功 ≠ 凭证有效**，否则日报会把没验证过的凭证报成 ✅。
2. **失败即回滚**：PLATFORMS 每项带 `cfg`（配置文件名），sync 前快照、init 判失败就恢复原文件。
3. **无人值守壳的覆盖度问题不算失败**：headless（真实 profile 或临时壳）拿到的 cookie 是天然
   不完整的子集（会话级必丢；临时壳实测只有 849 里的 90 个），所以 headless 模式下的差异一律
   退 0 + 打「沿用各平台 config 旧凭证」说明。**只有用户自己带 9222 的浏览器里缺键才叫真问题。**
4. **可选平台**（`optional: True`，如 WorkBuddy 国际版＝独立账号体系）未命中不计失败。

★新增平台根凭证若是浏览器 cookie，必须**同时**做两件事：进 `cookie_sync.PLATFORMS` **且**在
`run_all.py` 的该任务上列 `deps:["0-sync"]`。只做一半等于没做——只进名单会并发读写（一边写 config
一边读 config 签到），只列 deps 则同步根本不覆盖它。

### 各平台保活现状（该谁做什么）

| 类别 | 平台 | 机制 |
|---|---|---|
| **可离线续期（有 RT，已接线）** | MiniMax、华为码道、办公小浣熊、阿里云盘、天翼189、有道LobsterAI | lead 1h + 单次轮换守卫 + 终态不重试 + 新值只写自己的 cache |
| **靠第 0 步浏览器轮换** | 魔搭、Loomy(web)、天翼189 SSON、WorkBuddy国际版 | cookie_sync 每天重取（先验证后落盘、失败回滚） |
| **靠桌面端自续（每次实读）** | Qoder CN/国际版、千问办公、Loomy桌面、TRAE(旁证) | 用户在客户端里登录即刷新；★Qoder 离线续期要 `machine_id`，本机拿不到 → 不做死代码 |
| **只能重登/重抓（无 grant）** | 利宝、美团四件套、南航小程序 sessionId、东东农场、小米系、ZCode、TRAE、掘金(依赖 9222 登录态) | 体检里标「无到期值」+ 心跳观察；★别写【失效】除非当天真报错 |
| **结构性半自动** | 南航抽奖（sessionId 绑小程序、寿命数小时） | 每天提醒有几次机会待人工抽 |

★**不要主动做的三件事**（都是实测换来的）：① 在桌面端在跑时替它刷 refresh_token（会把它踢下线）；
② 打京东互动中心那组 functionId（账号/会话级 403，探测会扩大封锁）；③ 用 headless 临时壳做需要
bdms 滑块的掘金签到（必拦，脚本已改快速失败）。

---

## 三、排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 南航 `invalid session` / 业务失败 | 凭证过期 | 南航：先跑 `csair_signin.py doctor` 探活；sessionId 只能由小程序内 `wx.login` 换取（无服务端刷新接口），抓 `/mini/api/login/login` **响应体**发我用 `refresh` 更新 |
| ★`cookie_sync` 报某家 ❌（如「浏览器缺少 SSON（未登录？）」「浏览器缺少 session」）**但该平台当天签到正常** | 无人值守壳拿到的 cookie 是**天然不完整的子集**：会话级必然没有；临时 profile 实测只注入到 90 个（用户真浏览器有 849 个）。这是**覆盖度问题，不是用户没登录** | 脚本已按此把 headless 模式的差异退 rc=0 并打 `[说明]`。汇总照抄说明行，**别报【凭证同步失败】**。要全量同步只能让用户带 `thorium.exe --remote-debugging-port=9222` 开自己的浏览器再跑 |
| ★同步跑完后某平台**从正常变成 401/失效**（2026-10-18 真实事故：WorkBuddy 国际版旧 cookie 本可用、返回过 `active=false`，被临时壳的 90 个 cookie 覆盖后 401） | 早期 `cookie_sync` 是"先写后判"，坏凭证会顶掉好凭证；且部分平台 `init` 只打「已写入」不验证，成功判据等于没验 | 已修两条：①PLATFORMS 每项带 `cfg`，**init 判失败立即回滚原 config**；②所有平台 `init` 必须真发一次只读校验后才打 `[ok] …校验通过`（`workbuddy_intl_credits.py` 本次补上）。已被清掉的凭证无法找回——把 config 里 cookie 清空即可回到 `[skip] 未配置 退0` 的确定状态，等用户在对应域登录后由第 0 步重新同步 |
| `keepalive_status.py` 里某平台标「无到期值」 | 服务端**从来不给**到期时间（美团 wm_logintoken、利宝 authorization、小米 serviceToken、南航 sessionId、ZCode JWT 无 exp 等）——不是坏了 | 看「心跳天」列（上次总控成功距今）；>1.5 天标「心跳陈旧」才是真信号。★「无到期值」「未安装」「自动轮换」一律**不写进【XX失效】** |
| 体检把阿里云盘/MiniMax 标成「临期 0.0 天」 | 报的是**派生短效凭证**（AT 7200s / AT 约 1h），寿命短是设计如此；根凭证其实是 RT 或浏览器 Local Storage | 已按 `root=False` 排除告警。只有"坏了必须用户重登"那一层才参与临期判定（TRAE 7 天 JWT、Qoder 30 天、LobsterAI 30 天、华为 rt_exp_ms、小浣熊 token_exp） |
| 美团 `mtgsig` 失败/被风控 | 抓包设备版本与脚本不符、Node 未装 | 设 `MT_NODE`；把抓包整条发我适配 |
| 美团 H5 页"未登录" | wm_logintoken 过期 | 重抓一条 `listActivityCoupon` 发我，H5 脚本与主领券共用同一 token |
| 美团限时抢总提示"活动太火爆" | 该场次库存=0（秒杀券库存个位数，被别人抢了）或当日已领（subCode 9017） | 属正常，脚本每日新场次自动重试；想抢到需在场次开始（10:00/11:00/17:00）第一时间跑 |
| 美团"百元券包"没自动领 | 天降掉券每日只有 1 次机会，当天已领过则返回"次数已消耗光"；百元券包主力其实是**跨券墙**（页面可同时挂多个，"周末加码"那档面值最大） | 查 `mt_gundam_state.json` 或跑 `mt_gundam_coupon.py status` 看已领记录 |
| 美团跨券墙 fetch 返回 `subcode:12 活动太火爆` | 风控：未带 info 接口下发的 `ta.uuid`/`iuuid` cookie | 已修复——脚本用 cookie jar 先 info 收 cookie 再 fetch；若仍失败说明该活动风控更严或该账号被限 |
| 南航营销签到 `S0023 奖品状态不正确` | 2026-10-16 Reqable 抓包实证：`award/getAward` 对**已经是 `received` 的 `mileageAward`** 回这句，即「重复领取」，不是活动结束、也没有损失 | 已修正措辞（旧版写「活动可能已结束」会误导汇总）；核对用 awardList 里该项的 `awardStatus` |
| ★南航「当前无待消耗的抽奖机会」但小程序里明明能看到机会 | **两个叠加的假阴性**：① `awardList` 回 `S00011 获取用户登录信息失败` 时旧版 `find_lottery_chances` 直接返回空列表，把「鉴权失败」当成「没机会」；② `draw_all` 在入口就缓存 H5 token，而它常在 `signin_all` 之后跑——链路里的 Playwright 重登**已经换掉了 token**，缓存的旧值一路用到 S00011 | 已修（2026-10-16）：`find_lottery_chances` 改返回 `(chances, err)`，非 `0000` 一律报 err 并入口重读 `csair_h5_auth.json` 的新 token 再判失败；`draw` 报 rc=7 明确写「这是鉴权/网关问题，不是没有机会」。判读口径：**看不到机会先分清是查询失败还是真没有** |
| ★南航抽奖机会「莫名其妙少了一个」 | 旧版 `do_draw` **无论成败都写 state**（`state["draw\|%s"] = code\|txt`），而 `todo` 过滤掉任何有记录的 rewardId → 一次阿里云 WAF 拦截（`WAF\|被阿里云滑块拦截`）就把一个从未真正消耗的机会永久标成「已处理」 | 已修：只有服务端给出**终局结果**（中奖 / `W11000` 已消耗）才记账，`WAF/W00000/W403` 等未消耗情形下轮自动重试。历史脏数据已清（`csair_state.json.bak-20261016` 留档） |
| 南航 `mileagegift/draw` 回阿里云 WAF 挑战页（`meta name="aliyun_waf_aa"`，"请滑动滑块完成验证"） | ★2026-10-16 抓包**订正前一版结论**：不是「Python 过不去、真客户端能过」——**真小程序客户端同样被拦**（同一批 6 次 draw 里前几次都拿到挑战页），必须用户在小程序里**人工滑一次**。过完之后客户端把挑战页 `renderData` 里的 `token`/`traceid` 当 `u_atoken`/`u_asig` 附到重试 URL 上、再带 `u_aref=wxCaptcha` 与新的 `acw_tc` | 属平台反滥用，**不做自动化绕过**（单补 `acw_tc` 实测无效）。脚本遇 WAF 判「未消耗、不记账」，下轮自动重试 |
| 南航抽奖**明明抽中了却被脚本判成失败** | 中奖码是 **`W200`**，响应为**平铺字段**（`giftName`/`mileage`/`winnerId`/`giftId`），**没有 `data` 包装**；旧版成功码表只有 `W0000/0000/0/200` 且只读 `data` | 已修：`W200` 入成功码表并按平铺字段取 `giftName`；补 **`W45005 抽奖次数已用完`** 为**终局码**（记账不再空跑），`WAF/W00000/W403` 才留待重试 |
| 南航 `awardList` 有 N 条 `lotteryAward/received`，脚本就天天报「有 N 个机会」 | 那只是**发放台账**；抽奖次数记在抽奖池自己身上（按 `randomId`，本例 `0fLJsD`）。实证：两条至今 `received`，而 `draw` 已回 `W45005 次数已用完` | 真判据是 **draw 的返回码**，不是台账条数。另：奖池实测**几乎只有 1 里程、偶尔 2 里程**（`getWinnerList` 的 `luckWinnerList` 为空），期望 ≈1~2 里程/次——值不值得为它人工过滑块，自行权衡 |
| 小程序类 `sessionId` 想免手工获取 | PC 微信小程序的流量在系统代理开着时会全进 Reqable | 用 Reqable MCP：`capture_live_filter` 关键词 `mini/api/login/login` → `capture_live_get_by_id` 取**响应体** → 直接喂 `csair_signin.py refresh '<JSON>'`（2026-10-16 实测一次通过，签到链路随之恢复） |
| ★有道 LobsterAI 报 `[auto] 领取失败：请先登录`（服务端原文，不是脚本自创措辞） | ★**2026-10-18 起不该再默认发生**：脚本首选桌面端本地 Bearer（读 `lobsterai.sqlite` 里的 JWT，约 30 天有效）。出现这句说明走的是**陈旧 cookie**——`lobsterai_web_session` 被服务端重建过，而本平台**不在第 0 步 `cookie_sync` 名单里**（只有魔搭/小浣熊/Loomy 每天自动轮换），手工 cookie 不会自己更新 | 依次判：①看 `status` 首行 `[鉴权]` 走的是哪条链路——装了桌面端就该显示「桌面端 Bearer（免抓包）」；②只有桌面端确实没装/没登录才回退 cookie，重取用 `browser_cookies.extract_full(['youdao.com','163.com','netease.com','lobsterai'], tag='lobster')` 磁盘只读直开（浏览器开着也能读）→ `init --cookie '<拼好的 line>'`；③`keepalive` 看 JWT 到期。★关键口径：库里只捞到 `lobsterai_web_session`（host_key 是 `lobsterai-server.youdao.com`）、**`NTES_YD_SESS`/`DICT_SESS` 根本不在盘上，服务端照样认**——别把这两个键当硬前提去判"没登录" |
| LobsterAI 重建凭证后 `auto` 直接说「今日已签到，幂等跳过」 | Web 门户**登录本身**就触发「每日登录奖励 100」（同魔搭 +250 的会话副作用），用户在浏览器里登一次已经入账了；`status` 里 `claimedToday=True` + 余额出现一笔新的「每日登录奖励 100」即实证 | 算正常，不是漏领。核对用 `lobsterai_credits.py status`（看 `claimedToday`、各笔奖励的 `到期` 时间反推发放日） |
| 美团营销页红包总跳过 | 未抓包营销页 | 抓一次 `realTimeMarketingSendCoupon` 发我 |
| ★美团分销会场 grant 行报「已发放 17 张 ¥25000」，面额大得离谱 | `mt_union_coupon.py` 会场分支直接 sum 响应里的 `couponValue`（**单位是分**）后原样打印，而同一脚本的分销中心跨券墙分支是**元**口径 → 汇总里两行不能直接相加 | 判读口径：**会场行 ÷100**（¥25000 = ¥250.0），跨券墙行按原值；已在 2026-10-18 汇总中按此换算。要改就把 `count_granted` 的 value 统一 ÷100 |
| ★美团福利社报「底部 tab 已无福利社(fls) gundam 入口…入口已下线」 | 2026-10-12~10-15 连续四天如此，当时写成"服务端改版"；**2026-10-18 实测同一账号同一脚本自动发现 `gid=4TtwZI`、跨券墙 8 grabs + 天降 1 falls 正常入账** → 该 tab 下发是**灰度/周期性**的，不是永久下线 | 别把"入口已下线"当终局结论写进汇总；按当日实跑结果判，抓到 gid 就正常计入，抓不到就写"本次入口未下发，跳过" |
| ★美团惠省红包墙「今天的活动没领」 | 两种可能：① **其实已领完**（跑 `mt_api_coupon.py probe` 看「可领 N / 已在卡包 M」，可领=0 即领完，曾在 00:58 手动跑过并标记过当日）；② 旧版**日级幂等**把当天后出现的新批次挡掉了（红包墙当天会刷新，实测墙总额 ¥222→¥412） | 已修复为 rightCode 级幂等（2026-10-12），只领新出现的券；仍异常就跑 `probe` 对比「可领数」与 `mt_claim_state.json` 里当日 `granted_rc` 数量 |
| 美团惠省红包墙 probe 显示「可领 0 / 已在卡包 38」但记得没领过 | 之前某次运行（含手动测试）已领，`couponViewId` 有值即代表在卡包 | 正常；想核对去美团小程序「我的→红包/卡包」按日期看 |
| 美团 `querySharePopWindow` 返回 `data:null` | 无分享弹窗、无待领分享奖励 | 正常空操作；哪天真返回非 null data 再补分享任务实现 |
| ★WorkBuddy 报「未找到 buddy_station.py（skill 未安装？）」 | 官方 skill `totorosir-workbuddy-score` 没装，或装在了脚本搜索范围之外的目录 | 脚本按 `~/.qoder-cn/skills` → `~/.agents/skills` → `~/.workbuddy/skills` 顺序查找，装到任一处即可；三处都没有才是真没装，重装后无需改脚本 |
| WorkBuddy 报「[x] 无法解析输出」+ `UnicodeDecodeError: 'gbk' codec can't decode` | 父进程按本地 GBK 解 `buddy_station.py` 的 UTF-8 中文输出，reader 线程崩掉 → 表现为**假失效**（路径修好后才暴露） | 已修复：`run_bs()` 显式 `encoding="utf-8", errors="replace"` 并给子进程 `PYTHONIOENCODING=utf-8` |
| ★编排器里某平台 **rc=1、`out` 在某一行戛然而止、`err` 只有半截 `Traceback`**，而该平台单独重跑一切正常（2026-10-16 魔搭实测，同轮 WorkBuddy 也跟着 rc=1） | 反向的 GBK 问题：子进程 stdout 是**管道**时 Python 用本地 cp936 编码，脚本 `print("✅/ℹ️")` 直接抛 `UnicodeEncodeError` → 崩在打 emoji 那一行，前面已入账的动作看不见了。父进程再按 UTF-8 解码，bench 里中文全是乱码 | 已两层修复：①`run_all.py` 新增 `CHILD_ENV = dict(os.environ, PYTHONIOENCODING="utf-8")`，thread/process 的 `subprocess.run` 与 async 的 `create_subprocess_exec` 都带上它（一处覆盖全部任务，乱码同消）；②缺守卫的脚本补 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`——`ms_magicube.py`/`libao_integral.py` 原无，`mt_api_coupon/c189_signin/hw_codearts` 早有。**判读口径：见 rc=1+截断+Traceback 先怀疑这条，别急着报【平台失效】** |
| ★华为码道报 `[鉴权] devcloud cookie/cftk（抓包）` + `delivery HTTP 200 但空响应体`，而用户说「浏览器已重新登录」 | 两条链路都补不上：①snap 链路要的是 **CodeArts Agent 桌面端**的 IAM 临时 AK/SK（`expires_at` 约 2h，客户端不跑就不过期续期，2026-10-16 实测卡在 10-15 13:03 签发、15:03 到期）；②浏览器重登也没用——`devclouddevuibjtcftk` 等 devcloud 鉴权键是**会话级 cookie 不落盘**，磁盘直读只捞到 21 个营销/统计 cookie，`init` 里那份 cookie 仍是手工 F12 抓的旧值 | **正确解法是打开 CodeArts Agent 并登录一次**（自动续上免抓包链路），不是让用户重登浏览器、也不是 F12 抓 cookie。只有确实没有该客户端时，才走「带 9222 开浏览器 + F12 抓 `PromptCenterService` 整行 cookie 跑 `init`」 |
| 编排器打印「headless 浏览器就绪」，cookie_sync 却报 `[中断] cookie 读取失败: WinError 10061` | 拉起的 headless 实例在「就绪」之后**中途退出**（`/json/version` 曾短暂可达）。旧版一次失败就 rc=2 | 已修复两层：`_wait_online()` 现在校验 9222 的 LISTEN 确属本次拉起的进程（psutil `net_connections`），且要求 Popen 仍存活；`cookie_sync` 读 cookie 失败会收掉死壳**重试一次** |
| 京东签到 `code:3` 请先登录 | 浏览器里京东登录态失效/被服务端轮换（`order.jd.com` 也会退回欢迎登录页） | 在 Thorium 里打开 jd.com 重新登录；脚本下次运行自动读新 cookie，无需改配置 |
| 京东签到 `DG-9999 系统异常` | 走的是**已下线的旧接口** `signBeanIndex`（App 端链路，2026-10-12 起不可用） | 改用 Web 端 `jd_web_signin.py`（`pc_interact_sign_execute`）；旧 `jd_signin.py`/`jd_login.py` 已废弃 |
| 京东互动中心 `pc_interact_assign_query`/`reward_center`/`assign_execute` 返回 HTTP 403（零字节，响应头带 `X-Rp-Sdtoken: set;…`、`Server: jfe`、`Connection: close`） | ★**首次 403 不是频率限流**（当日第一条 POST 即 403、同批 GET 全通、同日京豆 POST 正常），但**封锁会升级**：反复探测之后连**真实浏览器里页面自己**发的同 functionId GET 也 403（同期 `kit_query`/`game_query` 仍 200，DOM 渲染不出任务列表）→ 属**账号/会话级风控**，与客户端类型、参数写法、sdtoken 握手都无关 | **立即停手**：当日不再打该 functionId 族（写读都别打）。次日**只观测页面自身请求**是否恢复，别主动发写请求。恢复后再用 `jd_interact_inpage.py check` 复测（页内真浏览器版）。**汇报口径**：「互动中心被京东风控封锁（账号/会话级，探测会加重），当日不做；京豆签到不受影响」——**不要**写"换日自动恢复"，也**不要**写"非账号问题" |
| 京东互动中心 `code:3` 请先登录 | 浏览器京东登录态失效/被轮换 | 同签到：Thorium 重新登录 jd.com，下次运行自动读新 cookie |
| 阿里云盘「今日已签」却记成首次 | `signInLogs` 的中文月份/字符串日解析失败会判不到今日 | 已修（`_cn2int` 支持「十月」/"12"）；核对用 `aliyun_signin.py status` |
| 千问办公/Qoder CN 提示【失效】未找到凭证 | 桌面端未安装/未登录，或 `auth-v2.dat` / `auth.v1.dat` 缺失 | 安装并登录对应桌面端一次；两家的凭证文件都是 Chromium v10 信封，脚本实时解密、不写回客户端 |
| Qoder CN 提示「服务端返回空活动列表」 | `cosy-clienttype` 头缺失时服务端按客户端类型过滤活动（不报错但 `campaigns:[]`） | 脚本已固定发送 `cosy-clienttype: 10`；若仍空列表，检查是否到了每日 10:00 窗口、或活动是否下线 |
| Qoder CN「已领取」但积分没到账 | 服务端 `claimStatus=CLAIMED` 即已发放；重复 claim 返同一 grantId + `replayed=true` | 正常幂等；去 Qoder CN 活动页核对，或用 `probe` 强制提交看服务端原文 |
| ★凭证同步 `[中断] 浏览器启动失败或 9222 不可达`（rc=2）、同轮**掘金也跟着失败** | 你自己的 Thorium 正开着但没带 `--remote-debugging-port`。Chromium 的 profile 是**单例**的：用同一个 `User Data` 再起 headless，新进程只会把启动请求移交给已运行实例后退出，9222 永远不监听（2026-10-15 实测第 0/8 步双双超时） | 已修复——`headless_browser.py` 检测到实例在跑就改用**独立临时 profile**（`%TEMP%\wb_th_*`）并从磁盘 Cookie 库注入登录态；收尾按临时 profile 精准回收，不碰你的窗口 |
| `headless-shell` 模式下只有 2/3 同步成功，**办公小浣熊报 `raccoon_token` 缺失**（真实 profile 的 headless 也一样） | `raccoon_token` / `raccoon_refresh_token` 是**会话级 cookie**（Chromium 不落盘），磁盘 Cookie 库里根本没有，临时 profile 注入不到 | 非「用户没登录」。脚本已按结构性限制返回 rc=0 + `[说明]`。要真正同步小浣熊，必须**你自己用 `thorium.exe --remote-debugging-port=9222` 开着浏览器**再跑 `cookie_sync.py`；否则该家沿用 config 里的旧 token，到期才需处理 |
| ★小浣熊明明属于上面那条结构性限制，`cookie_sync` 却报成 `浏览器缺少 raccoon_token（未登录？）` 并整步 **rc=3**（2026-10-16 编排器实测） | 豁免判定看 `mode.startswith("headless")`，而 `mode` 来自 `WB_BROWSER_HEADLESS_SHELL` 环境变量——**它只在拉起壳的那个进程里有**。编排器先拉起壳、`cookie_sync` 作为子进程只是「复用已在线的 9222」，env 丢了 → 被判成「用户自己的窗口」→ 会话级 cookie 缺失被当成未登录 | 已修：`headless_browser.is_headless_endpoint()` 直接问 CDP `/json/version`。★注意本机 Thorium 122 的 **`Browser` 字段写的是 `Chrome/122…`，只有 `User-Agent` 里带 `HeadlessChrome`**，只查 Browser 会永远判否。**判读口径：复用日志会写明「headless 无人值守壳」还是「用户自己开的窗口」，先按这句定性** |
| MiniMax Code 报 `面板解析失败（响应形状不符硬约束）` | 真相通常是 **HTTP 401 `{"error":"invalid access token"}`**（token 过期），错误体没有 `base_resp`，被 `parse_panel` 的 asar 硬约束兜成"形状不符"，看不出该重抓凭证（2026-10-16 实测） | 已加 `_auth_err()`：401/403 与纯错误体会单独识别并打**【MiniMax 登录态失效】**。**★★2026-10-17 起指引已改**：过期根因是手工抓包那份 `access_token` 寿命仅约 1 小时、而桌面端会自行轮换，故脚本改成四级保活直读 `~/.minimax/auth/.../auth.json` + `refresh_token` 离线刷新（见 §MiniMax「账号状态保持」）。现在再报失效 = 四级全断，**唯一解法是让用户打开 MiniMax Code 重登一次**，别再叫人生成抓包指引。真「形状不符」才是接口改版 |
| 京东 `login_expired` 但该不该叫用户重登，一眼判不准 | `thor/pin/_pst/unick` **全都在**cookie 里、`manual=false`、快照也是磁盘直读的新鲜的，服务端仍回 `code=3` —— 这是**会话被服务端整体作废**（改密/异地登录/超时都会这样），不是缺 cookie、也不是快照陈旧 | **鉴别诊断**（同一份 cookie，不吃 h5st）：`GET https://me-api.jd.com/user_new/info/GetJDUserInfoUnion`（Referer `https://home.jd.com/`）回 `{"msg":"not login","retcode":"1001"}` → 会话真死，只能重登 `passport.jd.com/new/login.aspx`；若它回正常用户信息而签到接口仍报错，才去查 h5st/风控参数而不是怀疑登录态 |
| ★WorkBuddy 国际版报「网关拦截 HTTP 401（返回 HTML 不是业务 JSON）」，且明明刚在浏览器登录过 `www.workbuddy.ai` | **APISIX 网关按 User-Agent 拦**：同一个有效 session cookie，UA=`WorkBuddyAI/5.8.3` 或空 UA → 401；UA 换浏览器串 → 200 `code:0`（2026-10-16 A/B 实测）。旧文案直接指向「cookie 过期」，会让人白抓一次 | 已修：脚本默认发浏览器 UA（config `user_agent` 可覆盖），失败文案改成「先确认 UA、再怀疑 session」。**判读顺序：见 401+HTML 先想 UA，别先叫用户重登** |
| ZCode 打 `billing/balance` 返 `400 {"code":3001,"msg":"parameter error"}` | 缺 **`X-Device-Mid`** 请求头（必填，不是可选装饰）。凭证本身是好的 | `device_mid` 就填同域 cookie `visitor_id`；`zcode_jwt` 取 `zcode.z.ai` 源 localStorage 的 `zcodejwttoken` 键 → 两者齐了即 `200 code:0`（可完全不抓包，只要浏览器登录过一次） |
| 华为码道 `[失败] delivery HTTP 200 但空响应体` | 华为云网关/WAF 在**登录态失效**时就回 200 + 零字节（不是 JSON、也不是 401），旧版只说「HTTP 200」等于没法定位 | `fail_reason()` 已能区分「明确拒绝 / 业务码 401 / 空响应体 / HTML 跳登录页」。装了 CodeArts Agent 的正常机器**不会再走 cookie 链路**（脚本首行 `[鉴权]` 会写明用的哪条）；★2026-10-16 起回退链路的失败行会**直接带上读不到桌面端凭证的具体原因**（`_CRED["why"]`，如「客户端凭证已过期 expires_at=… → 打开 CodeArts Agent 让它续期」），**先按它让用户打开并登录 CodeArts Agent**，只有确实没有该客户端才提 F12 重抓 `PromptCenterService` cookie |
| 华为码道 `[失败] 读不到 CodeArts Agent 桌面端凭证（…）` | 三种原因：没装该客户端（没有 `%APPDATA%\codearts-agent\User\globalStorage\state.vscdb`）／客户端未登录（没有 `HuaweiCloudSession` 条目）／IAM 临时凭证 `expires_at` 已过期（约 2 小时，客户端在跑才自动续） | 打开 CodeArts Agent 登录一次即可（客户端运行中会把 `state.vscdb` 独占锁住，脚本走 `CreateFileW` 共享读复制，不需要你关窗口）；换机器用 `HW_CODEARTS_UD` 指到实际 userData；实在没有客户端就回退 `hw_codearts.py init '<cookie>'` |
| 华为码道 claim/confirm `HTTP 400 HDN.1000 "channel : unknown exception"` | 服务端按 DTO 逐字段校验：`claim` 的 body **要** `channel`，`confirm` 的 body **不能带** `channel`；反过来给 POST 再挂 `?channel=` query 也会 400 | 已按客户端两处实现校准：GET 只放 query、POST 只放 body 且仅 claim 带 channel |
| 华为码道签名报 `401 APIG.0301 header x-sdk-date not signed` | `X-Sdk-Date` 没进参与签名的 header 集合（signer.js 是先写 header 再算 SignedHeaders） | 已修复；另注意 canonicalURI 末尾必须补 `/` |
| 华为码道「今日不可领」`claimable=false` 且 status 非已领 | 权益刷新周期**不是自然日**（实测 confirm 显示 claimedAt=09-27 后长期不可领） | 业务态不是失效，脚本已返回 0 并标注【今日不可领】，别再当日误报异常；`probe` 可看服务端 40001 原文 |
| 京东明明重新登录了，仍持续 `login_expired`（曾连挡两天） | ① `manual=true` 配置一旦写入就**永久短路**整条提取链（TEMP 缓存只在直读成功时刷新，而直读被短路永不执行）；② ~~Thorium 在跑时读不出库~~ **此因已于 2026-10-17/18 两次证伪**：脚本走的 `CreateFileW` **只读**直开 + 自解析 SQLite 在浏览器运行中照样成功（2026-10-18 实测提出 42 个 cookie、`flash` 已是重登后的新值）。真正会失败的只有"整库复制"类手段（esentutl/robocopy/copy/open）；③ 旧版 esentutl 静默失败还等满 120s | 已修（2026-10-15）：`manual` 加 **6h TTL**；取源按新鲜度排序；esentutl 超时降到 20s 并打印原文；用陈旧快照时 `login_expired` 自带"N 分钟前的磁盘快照"提示。**判读顺序**：先跑 `jd_web_signin.py cookie` 看它报的哪一级源＋条数有无变化 → 直读成功且是新鲜值仍 `code=3`，才是**会话被服务端整体作废**（见上条鉴别诊断），此时唯一解法是真重登；只有源是 TEMP 陈旧快照时才需要关浏览器或加 9222。**别一上来就叫用户关浏览器** |

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
python scripts/jd_web_signin.py interact              # ★已移出总控，仅封锁解除后复测用（互动中心：抽奖机会→抽奖→做任务赚机会→再抽）
python scripts/jd_web_signin.py interact_status       # ★同上，只读复测：抽奖机会 + 任务完成情况
python scripts/jd_interact_inpage.py check            # ★只读自检：在真浏览器(9222)页内看那组 functionId 是否已恢复 200

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
python scripts/qoder_credits.py auto                    # campaigns 动态发现 → 领取**全部** CLAIMABLE 活动（定时任务用这个）
python scripts/qoder_credits.py status                  # 只读：活动清单 + 今日是否已领
python scripts/qoder_credits.py probe                   # 强制领取一次（验证服务端幂等 replayed）
python scripts/qoder_credits.py keepalive               # 保活体检（只报有效期；★默认不发续期请求）
python scripts/qoder_credits.py init                    # 把客户端凭证导出到 qoder_config.json 兜底

# 凭证同步：魔搭/小浣熊/Loomy 轮换制凭证从浏览器自动取新写回（每日任务第 0 步）
# 阿里云盘不走 cookie（凭证在 Local Storage），不在此列
python scripts/keepalive_status.py                     # ★全平台保活体检（只读；根凭证到期 + 成功心跳）
python scripts/keepalive_status.py --warn              # 只看需要动作的行
python scripts/lobsterai_credits.py keepalive          # 单平台保活体检（TRAE/Qoder/LobsterAI 均有此子命令）
```

挂定时任务（如每天 08:30 依次跑四条），脚本自带幂等，当天完成后自动跳过；删除对应 `*_state.json` 可重跑。


