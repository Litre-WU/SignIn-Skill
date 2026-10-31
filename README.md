# SignIn-Skill · 签到啦

多平台每日签到 / 领券 / 积分自动化工具集。遵循通用 **Agent Skill** 规范（`SKILL.md` + frontmatter 元数据 + `scripts/` 目录），可安装进任何支持该约定的 AI 编程/办公助手，也可完全脱离 AI 用纯 Python 独立运行。纯接口实现（非 UI 点击），自带幂等（当天重复执行自动跳过）与状态文件，适合挂 cron / 定时任务。

**本仓库收录 20 个平台（同一家企业的多个产品已合并为组，组内脚本即总控链内执行顺序）：**

| 平台 | 脚本 | 每日收益 |
|---|---|---|
| 美团系（4 项） | `scripts/mt_api_coupon.py`<br>`scripts/mt_gundam_coupon.py`<br>`scripts/mt_union_coupon.py`<br>`scripts/mt_answer.py` | 红包墙领券 + 福利社 + 分销会场 + 答题现金（总控合并为单一任务，链内串行） |
| 南航（小程序） | `scripts/csair_signin.py` | 发现新境签到 + 营销签到领里程 + 抽奖机会检测（sessionId 需抓包 refresh） |
| 魔搭 ModelScope | `scripts/ms_magicube.py` | 魔粒 +290/日（登录 250 + 点赞刷分 40） |
| WorkBuddy系（3 项） | `scripts/wb_score.py`<br>`scripts/wb_growth.py`<br>`scripts/workbuddy_intl_credits.py` | Buddy 加油站签到 + 派猫猫旅行 + 成长中心 6 项奖励自动补齐 + **国际版**（www.workbuddy.ai）每日签到（★国际版需独立账号 cookie，未配置时链内 skip 退 0；路径不带 /v2、无设备指纹头，重复领取 HTTP 400 + code 10001 属幂等成功）。总控合并为单一任务，链内串行 |
| 办公小浣熊（商汤） | `scripts/xhx_office_points.py` | 每日 300 积分确认（会话活跃自动入账，无手动签到接口） |
| 讯飞Loomy（2 项） | `scripts/loomy_points.py`<br>`scripts/loomy_desktop_tasks.py` | Web 端积分 + 桌面端新手任务（总控合并为单一任务，链内串行） |
| 天翼189云盘 | `scripts/c189_signin.py` | 每日签到领随机空间（实测 +26~50MB，容量前后差做入账判据） |
| 京东京豆 | `scripts/jd_web_signin.py` | 每日京豆签到（Web 端 `pc_interact_sign_execute`，连签有加成；浏览器 PC 登录态实时提取 cookie，无需抓包）。★互动中心天天抽奖已于 2026-10-17 移出每日流程：那组 functionId 是账号/会话级 HTTP 403 风控，且反复探测会让封锁从写扩大到读；`interact`/`interact_status` 子命令保留仅作封锁解除后的复测入口 |
| 京东东东农场 | `scripts/jd_farm.py` | 自动浇水 + 领每日免费水滴（微信小程序 webview H5，`api.m.jd.com/client.action` `appid=signed_farm_mp`，**纯 cookie 无 h5st 签名**）。★自举浇水：`farm_water` 优先快速模式(waterType=2 单次耗 50ml)、普通(=1 耗 10ml)补到底，浇水还会触发回灌奖励(🎁水滴×300)。★领水滴的 16 项任务全是 BROWSE 浏览类，其完成依赖真实点击跳转停留 6s 生成的 `assignmentToken`（`uploadInteractiveAssignment`），**纯 API 无法自动化**——脚本不空打（每次 6002 会累积更宽频控），只如实标注需手动；浇水进度与签到/免费水滴可全自动。凭证是微信小程序登录态(pin/wq_skey/sdtoken+eid)，有效期短需在微信重开农场刷新；farm_home 偶发单接口频控 405 由脚本降级自举，频控软跳过退 0 不报失效 |
| 阿里系（3 项） | `scripts/aliyun_signin.py`<br>`scripts/qwenwork_credits.py`<br>`scripts/qoder_credits.py` | 阿里云盘签到（浏览器 Local Storage 实时取凭证）+ 千问办公每日 100 积分 + Qoder CN 每日 100 Credits（后两者桌面端 v10 信封解密取凭证，排末位规避 10:00 窗口边界），均无需抓包 |
| 小米系（2 项） | `scripts/xm_mijin.py`<br>`scripts/yp_rpsign.py` | 米金签到+做任务 + 有品每日红包签到（总控合并为单一任务，链内串行） |
| 华为码道 CodeArts Doer | `scripts/hw_codearts.py` | 每日签到领 1000 积分（免费额度；delivery 查 claimable → claim → confirm 三步，积分 30 天有效）；★账号状态保持：桌面端临时 AK/SK（约 2h 寿命）过期时，脚本用 session 里的 refresh_token（约 28 天）+ PKCE codeVerifier + DPoP 私钥直接向 STS 离线换新凭证（方法参考 Our Free Model src/oauth.ts 逆向），**无需开着 CodeArts Agent**；刷出的新临时凭证本地缓存 2h 内复用，一天跑多次只消耗一次轮换 |
| TRAE（字节跳动） | `scripts/trae_credits.py` | 每日签到积分（实测单日 150）；Cloud-IDE-JWT 鉴权 + 设备身份按 uid 确定性派生；★claim 幂等但响应不可区分 → status 预检 + 领取后回查积分；错误分类冷却（1005 套餐限/9074 繁忙/401 失效）；★★账号状态保持（2026-10-18）：本机 Trae 存储里**没有 refresh_token**，不能离线续期，但 config 那份 JWT(14 天，签到用) 与 `~/.trae-cn/trae-jwt-token`(7 天，IDE 自用) 是同一次登录发的两种用途——用户在客户端重登一次两份同时刷新，故 config 过期/临期时脚本会自动改用桌面端里更新的一份并回写自己的 config；临期解法是在 TRAE 里重新登录 |
| LobsterAI（有道） | `scripts/lobsterai_credits.py` | 每日签到积分（实测「每日登录奖励」100/天）；三步 slot→context→check_in，纯 Bearer 无签名；客户端幂等键 + claimedToday/actions 双重预检；余额用 profile-summary（quota 端点不含活动积分）；★★账号状态保持（2026-10-18，逆向 Our Free Model lobsterai-oauth）：**免抓包**直读桌面端 `%APPDATA%/LobsterAI/lobsterai.sqlite` 的 kv 表（auth_tokens/keyfrom.attribution.v1/auth_user/installation_uuid，★客户端在跑也能读：先 mode=ro&immutable=1 再退 mode=ro），accessToken 是 JWT(约 30 天)；过期/临期(<1h)时 POST /api/auth/refresh（★匿名头不带 Authorization，body 的 firstKeyfrom/latestKeyfrom 用**存储原值**不取当前时刻，响应可能不返新 refreshToken 必须沿用旧值，同一支只试一次、40100/40101 终态不重试），新凭据只写 lobsterai_live_cache.json 不回写 sqlite；`--auth auto|bearer|cookie`，Web cookie 仅作兜底且服务端只认 lobsterai_web_session 一个键 |
| MiniMax Code | `scripts/minimax_credits.py` | 七日签到积分（实测单日 400/800 档）；timezone_id 必填（IANA）；业务码在 base_resp.status_code；claim_result 幂等；★points 为总数不相加 bonus_points；今日已领判据 is_today && status==3；★★账号状态保持（2026-10-17，参考 Our Free Model 的 minimax-oauth.ts）：access_token 寿命仅约 1 小时且桌面端会自行轮换，故按四级取凭证——直读 `~/.minimax/auth/prod/cn/mcode-public/auth.json` → 本地 session 缓存 → `grant_type=refresh_token` 向 account.minimax.cn 离线换新 → config 手工值兜底；★单次轮换同一支只试一次、不回写客户端文件；判读只看首行 `[鉴权] 来源=`，正常情况**免抓包** |
| ZCode（智谱） | `scripts/zcode_credits.py` | Start Plan 每日额度（zcode.z.ai）；★查可领额度前**必须先补 event/report 激活**，否则 preview 空列表会稳定误报『今日已领』；今日已领判据=可领 plan 数为 0；★code 1003=已领取（属成功）、3007=captcha 无效；★领取端点强制阿里云验证码，无 captcha 时提示人工领取（不算失败）；凭据需抓包 zcode_jwt + device_mid |
| wb_balance.py | `scripts/wb_balance.py` |  |
| 滴滴出行 | `scripts/didi_coupon.py` | 打车/花小猪/加油/货运 4 线自动领券（union.didi.cn reward/receive，按 dsi 幂等）+ 福利中心每日签到领福利金、气泡逐个点、瓜瓜乐报名/领奖（ut.xiaojukeji.com）；★凭证是 **H5 登录票据 token**（`sync` 从本机浏览器登录态自动取：CDP 读 localStorage 为主 + leveldb 兜底，需 Thorium 9222；也可 F12 手取，约 7-30 天有效）。★实证坑：localStorage 值自带引号必须剥、票据键 role 后缀随活动变（实测 role_30004）须前缀匹配；ut/webx 带 wsgsig 签名（md5 盐 + 七元组 + 4 字节掩码 XOR + base64）。失效判据 ut errno=6001 / union errno=1000010005（≥2 线才判失效）；重复签到 errno=40009 算成功 |
| 腾势 DENZA | `scripts/byd_signin.py` | 汽车小程序签到 + 任务中心自动领积分（反编译包逆向）；两套场景：unifie 网关(common-mina-gateway.bydauto.com/denza) 走签到家族 signIn/getSignCalendar/getCardList，normal 场景(service20.denzacloud.com/?s=ForInterfaceMina.forwardInformationFlow) 走任务系统 task/user/tasks + receiveAward；AES-128-CBC-PKCS7 直接密钥(非口令派生)，请求头 Checksum=sha256(appSecret+nonce+curtime)；★凭证=小程序 session_id（真机 Reqable 抓 /?service=mina.decryptCode 响应取），非浏览器 cookie、不依赖 0-sync；★sid 寿命仅约 2h、无离线续期通道，保活=每日跑前 1 小时内 PC 微信打开小程序让 reqable_hunt.py harvest 收割；★任务服务对 session 校验更严，同一 sid 能让签到过不代表任务也能过(ret=401 即需重抓)；未配置账号时 [skip] 退 0 |
| mengshi_signin.py | `scripts/mengshi_signin.py` |  |

## 安装

### 方式一：作为通用 Agent Skill（任意 AI 助手）

本仓库是标准 skill 包：根目录 `SKILL.md` 为入口说明书，`scripts/` 为工具脚本。把仓库放到对应助手的技能目录即可自动发现：

| 宿主 | 放置路径 |
|---|---|
| Claude Code | `~/.claude/skills/SignIn-Skill/` |
| WorkBuddy | `~/.workbuddy/skills/SignIn-Skill/` |
| 其他支持 SKILL.md 约定的 agent | 其 skills/plugins 目录，或在工作目录 `.skills/`、项目根放好并在对话中引用 |

```bash
git clone <本仓库地址> ~/.claude/skills/SignIn-Skill    # 以 Claude Code 为例
```

之后直接对助手说「签到」「领美团券」「南航签到」等，skill 会被触发并引导你配置凭证。装了 Reqable（抓包客户端）时抓包由 agent 自动完成（`scripts/reqable_hunt.py`，你只在小程序/浏览器里**做一次动作**，不用复制任何请求文本，见 `SKILL.md` §〇）；没装就手工复制 1 条请求发给助手（§一）。阿里云盘、京东京豆等更省事 —— **只要浏览器里是登录态，脚本会自己从本机读取凭证，不用抓包**。各平台小节写明要抓哪一条。

### 方式二：脱离 AI，纯脚本独立运行

1. 环境要求：**Python 3.10+**（全部脚本仅用标准库）；美团签名需要本机 **Node.js**（可用环境变量 `MT_NODE` 指定路径）；南航 H5 登录态失效时的自动重登是可选能力，需另装 `playwright`（不装则按小节手工抓包）；WorkBuddy 积分需要安装 WorkBuddy 客户端。
2. 克隆仓库并进入 `scripts/` 目录。
3. 复制配置模板并填入你的抓包值（抓法见 `SKILL.md`；没有模板的平台=免配置或浏览器直取凭证）：
   ```bash
   cp mt_config.example.json mt_config.json   # 然后编辑填入抓包值
   ```
   - `mt_config.example.json` → `mt_config.json` — 美团系 4 个脚本共用
   - `csair_config.example.json` → `csair_config.json` — 南航（小程序）
   - `ms_config.example.json` → `ms_config.json` — 魔搭 ModelScope
   - `xhx_config.example.json` → `xhx_config.json` — 办公小浣熊（商汤）
   - `loomy_config.example.json` → `loomy_config.json` — Loomy（讯飞）
   - `mt_answer_config.example.json` → `mt_answer_config.json` — 美团答题领现金
   - `xm_mijin_config.example.json` → `xm_mijin_config.json` — 小米商城米金
   - `yp_rpsign_config.example.json` → `yp_rpsign_config.json` — 有品每日签到（红包）
   - `hw_codearts_config.example.json` → `hw_codearts_config.json` — 华为码道 CodeArts Doer
   - `qwenwork_config.example.json` → `qwenwork_config.json` — 千问办公（阿里）
   - `qoder_config.example.json` → `qoder_config.json` — Qoder（阿里，双区）
   - `mt_union_config.example.json` → `mt_union_config.json` — 美团分销会场
   - `jd_farm_config.example.json` → `jd_farm_config.json` — 京东东东农场
   - `didi_coupon_config.example.json` → `didi_coupon_config.json` — 滴滴出行
   - `lobsterai_config.example.json` → `lobsterai_config.json` — LobsterAI（有道）
   - `minimax_config.example.json` → `minimax_config.json` — MiniMax Code
   - `qoder_intl_config.example.json` → `qoder_intl_config.json` — Qoder（阿里，双区）
   - `trae_config.example.json` → `trae_config.json` — TRAE（字节跳动）
   - `workbuddy_intl_config.example.json` → `workbuddy_intl_config.json` — WorkBuddy 国际版
   - `zcode_config.example.json` → `zcode_config.json` — ZCode（智谱）
4. 运行（幂等，可重复跑）：
   ```bash
   python scripts/mt_api_coupon.py claim                # 美团券包（惠省小程序首页红包墙）
   python scripts/mt_api_coupon.py probe
   python scripts/mt_gundam_coupon.py                   # 美团福利社 H5
   python scripts/mt_union_coupon.py                    # 美团分销会场
   python scripts/csair_signin.py signin                # 南航（小程序）
   python scripts/csair_signin.py refresh '<login响应JSON>'
   python scripts/ms_magicube.py auto                   # 魔搭 ModelScope
   python scripts/wb_score.py auto                      # WorkBuddy 积分
   python scripts/wb_growth.py auto                     # WorkBuddy 成长中心
   python scripts/xhx_office_points.py auto             # 办公小浣熊（商汤）
   python scripts/loomy_points.py auto                  # Loomy（讯飞）
   python scripts/loomy_desktop_tasks.py run            # Loomy 桌面端
   python scripts/c189_signin.py auto                   # 天翼189云盘
   python scripts/jd_web_signin.py auto                 # 京东京豆
   python scripts/jd_web_signin.py cookie
   python scripts/jd_farm.py auto                       # 京东东东农场
   python scripts/jd_farm.py status
   python scripts/jd_farm.py water
   python scripts/jd_farm.py init '<cookie>'
   python scripts/aliyun_signin.py auto                 # 阿里云盘
   python scripts/mt_answer.py auto                     # 美团答题领现金
   python scripts/mt_answer.py probe
   python scripts/xm_mijin.py auto                      # 小米商城米金
   python scripts/xm_mijin.py probe
   python scripts/yp_rpsign.py auto                     # 有品每日签到（红包）
   python scripts/yp_rpsign.py probe
   python scripts/qwenwork_credits.py auto              # 千问办公（阿里）
   python scripts/qwenwork_credits.py status
   python scripts/hw_codearts.py auto                   # 华为码道 CodeArts Doer
   python scripts/hw_codearts.py init '<cookie>'
   python scripts/hw_codearts.py probe
   python scripts/hw_codearts_refresh.py probe
   python scripts/hw_codearts_refresh.py refresh
   python scripts/qoder_credits.py auto                 # Qoder（阿里，双区）
   python scripts/qoder_credits.py status
   python scripts/qoder_credits.py probe
   python scripts/qoder_credits.py keepalive
   python scripts/trae_credits.py auto                  # TRAE（字节跳动）
   python scripts/trae_credits.py status
   python scripts/trae_credits.py keepalive
   python scripts/trae_credits.py init
   python scripts/lobsterai_credits.py auto             # LobsterAI（有道）
   python scripts/lobsterai_credits.py status
   python scripts/lobsterai_credits.py keepalive
   python scripts/lobsterai_credits.py init
   python scripts/minimax_credits.py auto               # MiniMax Code
   python scripts/minimax_credits.py auth
   python scripts/minimax_credits.py status
   python scripts/minimax_credits.py init
   python scripts/workbuddy_intl_credits.py auto        # WorkBuddy 国际版
   python scripts/workbuddy_intl_credits.py status
   python scripts/workbuddy_intl_credits.py init
   python scripts/zcode_credits.py auto                 # ZCode（智谱）
   python scripts/zcode_credits.py status
   python scripts/zcode_credits.py init
   python scripts/didi_coupon.py auto                   # 滴滴出行
   python scripts/didi_coupon.py sync
   python scripts/didi_coupon.py status
   python scripts/byd_signin.py auto                    # 腾势 DENZA
   python scripts/byd_signin.py status
   python scripts/byd_signin.py init --session <session_id> [--acct 名字]
   ```
5. 定时：挂 cron / 任务计划程序 / 任意调度器每日一次即可；当天已完成的自动跳过，重跑可删除对应 `*_state.json`。

## 已废弃脚本（保留供参考）

- `jd_signin.py` — 京东京豆（旧 App 端）：signBeanIndex 接口 2026-10-12 起服务端下线
- `jd_login.py` — 京东登录（旧 App 端扫码）：京东新版拒绝 tmauth，改用 Web 端 jd_web_signin.py

## 辅助脚本 / 离线单测

- `browser_cookies.py` — 浏览器 Cookie 提取库：绕 Chromium 独占锁读取并解密 cookie；跨平台 TEMP 整库缓存复用
- `credential_core.py` — 账号保活共享层：全平台统一的保活纪律：到期时间只认服务端值(expires_in>expires_at>JWT exp，>1e12 判毫秒)、距过期不足 1h 才续期、同一支 refresh_token 按指纹 6h 内只试一次、终态码(401/403/40100/40101/200003/invalid_grant)判死不重试、新凭据只写自己的 *_live_cache.json 不回写官方客户端；另提供 v10/DPAPI 与 Electron sqlite kv 的通用只读读取、统一 `[鉴权]` 判读行、总控成功心跳记账（★只记 rc 与时间，不存输出原文以免凭证片段落盘）
- `keepalive_status.py` — 全平台保活体检：23 个平台只读体检：根凭证到期(临期≤3天)+成功心跳(上次总控成功距今天数，>1.5 天标心跳陈旧)；派生短效凭证(AT 7200s/约 1h/临时 AK/SK 2h/sdtoken 1800s)不参与临期告警；已挂在 run_all 开头打 2~3 行预警
- `_mishop_client.py` — 小米商城 mtop 客户端库：MiShop 设备头/服务Token/请求封装（xm_mijin.py 的依赖，凭证优先读 xm_mijin_config.json）
- `hw_codearts_refresh.py` — 华为码道凭证离线续期库：refresh_token+PKCE+DPoP(ES256) 向 STS 换新临时 AK/SK（hw_codearts.py 的依赖，方法参考 Our Free Model src/oauth.ts 逆向）
- `reqable_hunt.py` — Reqable 自动抓包入口：抓包前置体检 + 平台注册表 + 「MCP 记录 JSON → 凭证 → 写回 config」：doctor / scan / harvest [--apply] / restore-proxy（关 Reqable 后必跑，否则系统代理残留会让脚本成片假失效）
- `jd_interact_inpage.py` — 京东互动中心页内复测工具：★不进每日流程：互动中心那组 functionId（assign_query / reward_center / assign_execute）是**账号/会话级 HTTP 403 风控**——urllib、headless、以及真浏览器里**页面自己**发的请求都会 403，且反复探测会让封锁从写扩大到读。本脚本只在你带 `--remote-debugging-port=9222` 启动的真浏览器里，用页面自己的 PSign/getJsToken/SHA256 复刻 requestColorEncrypto，供**封锁解除后复测**；check 只读自检、auto 领机会并抽。★会主动拒绝无头 9222（无头测出来的是假结论），永不自启浏览器、永不回收用户实例


## 安全声明

- 本仓库**不含任何账号凭证**，config 全部需要你自己抓包生成（`.gitignore` 已防止误提交）
- 凭证有效期有限（分钟~天级），且部分平台是**服务端轮换制**（不是自然过期），失效后需重新抓包
- 自动化操作可能违反部分平台的服务条款，风险自负；请勿高频调用，接口异常先停手排查
- 仅供学习交流

---

## 我在用的 AI 工具（走我的入口注册有新人积分）

这个仓库的自动化就跑在下面这些工具里，顺手把我的邀请入口放在一起，注册时带上就能领新人礼包：

- **WorkBuddy**（我的 AI 工作搭子，仓库里 `wb_score.py` / `wb_growth.py` 签到链路就是它的）
  注册入口：<https://www.workbuddy.cn/events/invite?inviteCode=thb5u68d9bp6oc>
- **Loomy（讯飞）** — 比龙虾🦞更易上手、更好用。下载安装后输入我的专属邀请码 **`DF9N3T`** 即可开启体验。
  下载：<https://loomy.xunfei.cn/download>
- **TRAE（字节 AI 编程）** — 我用它搞定各类编程任务（仓库里 `trae_credits.py` 每日签到领积分就是给它写的）。
  **通过下面链接注册并登录桌面端，新用户一次性得 5,000 积分**：
  <https://www.trae.cn/events/code-fission/9TBNW7SJTGSW?utm_source=copy_link&utm_medium=code_fission>
- **LobsterAI（有道龙虾）** — 免费体验，我的专属邀请码 **`qm1IRC`**，登录页填入得 **300 积分**新人礼包（`lobsterai_credits.py` 同样是为它写的）。
  1. 点链接下载：<https://lobsterai.youdao.com/#/index?keyfrom=invitation>
  2. 安装后打开应用，点【登录】
  3. 在登录页输入邀请码 `qm1IRC`，领取 300 积分新人礼包

我自己在用，确实好用，所以放这儿了。这些链接与本项目功能无关，纯分享；仓库的自动化能力以上面的小节为准。
