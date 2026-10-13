# SignIn-Skill · 签到啦

多平台每日签到 / 领券 / 积分自动化工具集。遵循通用 **Agent Skill** 规范（`SKILL.md` + frontmatter 元数据 + `scripts/` 目录），可安装进任何支持该约定的 AI 编程/办公助手，也可完全脱离 AI 用纯 Python 独立运行。纯接口实现（非 UI 点击），自带幂等（当天重复执行自动跳过）与状态文件，适合挂 cron / 定时任务。

**本仓库收录 16 个稳定入口：**

| 平台 | 脚本 | 每日收益 |
|---|---|---|
| 美团券包（惠省小程序首页红包墙） | `scripts/mt_api_coupon.py` | 每日领券；红包墙当天会刷新批次，按 rightCode 级幂等，新批次也能领到 |
| 美团福利社 H5 | `scripts/mt_gundam_coupon.py` | 跨券墙 / 限时抢 / 天降掉券（福利社 tab 改版后入口可能下线，属服务端变更） |
| 美团分销会场 | `scripts/mt_union_coupon.py` | 会场每日券包 + 分销中心内嵌跨券墙（单日约 ¥180） |
| 南航（小程序） | `scripts/csair_signin.py` | 发现新境签到 + 营销签到领里程 + 抽奖机会检测（sessionId 需抓包 refresh） |
| 魔搭 ModelScope | `scripts/ms_magicube.py` | 魔粒 +290/日（登录 250 + 点赞刷分 40） |
| WorkBuddy 积分 | `scripts/wb_score.py` | 签到 +100/天（连续 7/14/28 天有额外档）+ 派猫猫旅行 5~10 |
| WorkBuddy 成长中心 | `scripts/wb_growth.py` | 盲盒抽奖 / 连登三档兑换 / 断登补签 / 接任务 / 领任务奖 自动补齐 |
| 办公小浣熊（商汤） | `scripts/xhx_office_points.py` | 每日 300 积分确认（会话活跃自动入账，无手动签到接口） |
| Loomy（讯飞） | `scripts/loomy_points.py` | 每日积分确认（活跃自动入账，纯 cookie 鉴权） |
| Loomy 桌面端 | `scripts/loomy_desktop_tasks.py` | 新手任务 8 项共 10000 分（桌面客户端专属，自动读本机登录态） |
| 天翼189云盘 | `scripts/c189_signin.py` | 每日签到领随机空间（实测 +26~50MB，容量前后差做入账判据） |
| 京东京豆 + 互动中心 | `scripts/jd_web_signin.py` | 每日京豆签到 + 天天抽奖（做任务赚机会 → 转盘抽奖） |
| 阿里云盘 | `scripts/aliyun_signin.py` | 每日签到；凭证从浏览器 Local Storage 实时读取，**无需抓包、无需关浏览器** |
| 美团答题领现金 | `scripts/mt_answer.py` | 七日签到奖励 + 每日任务奖励自动领取（MGC Pike WebSocket 协议纯 Python 重放，无需浏览器） |
| 小米商城米金 | `scripts/xm_mijin.py` | 米金签到 +15/日（每日 5 + 连签奖励 10）+ 浏览任务各 +5；venue/page(v1) 拉任务清单，infinite do→done 完成，幂等判据 code:200001 |
| 有品每日签到（红包） | `scripts/yp_rpsign.py` | 全年活动（2026-01~12）：每日随机红包（实测 0.24 元/日）、7 天连签第 7 天 5 元；先 getActInfo 判 signUserInfo.sign 再点击（已签到重复提交会返 500） |

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

之后直接对助手说「签到」「领美团券」「南航签到」等，skill 会被触发并引导你抓包配置。多数平台只需**抓 1 条请求**发给助手；阿里云盘、京东京豆等更省事 —— **只要浏览器里是登录态，脚本会自己从本机读取凭证，不用抓包**。抓法详见 `SKILL.md` 各平台小节。

### 方式二：脱离 AI，纯脚本独立运行

1. 环境要求：**Python 3.10+**（全部脚本仅用标准库）；美团签名需要本机 **Node.js**（可用环境变量 `MT_NODE` 指定路径）；WorkBuddy 积分需要安装 WorkBuddy 客户端。
2. 克隆仓库并进入 `scripts/` 目录。
3. 复制配置模板并填入你的抓包值（抓法见 `SKILL.md`）：
   ```bash
   cp mt_config.example.json mt_config.json   # 然后编辑填入抓包值
   ```
   各平台模板：`mt_config.example.json`、`csair_config.example.json`、`ms_config.example.json`、`xhx_config.example.json`、`loomy_config.example.json`。
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
   python scripts/jd_web_signin.py auto                 # 京东京豆 + 互动中心
   python scripts/jd_web_signin.py interact
   python scripts/aliyun_signin.py auto                 # 阿里云盘
   python scripts/mt_answer.py auto                     # 美团答题领现金
   python scripts/mt_answer.py probe
   python scripts/xm_mijin.py auto                      # 小米商城米金
   python scripts/xm_mijin.py probe
   python scripts/yp_rpsign.py auto                     # 有品每日签到（红包）
   python scripts/yp_rpsign.py probe
   ```
5. 定时：挂 cron / 任务计划程序 / 任意调度器每日一次即可；当天已完成的自动跳过，重跑可删除对应 `*_state.json`。

## 已废弃脚本（保留供参考）

- `jd_signin.py` — 京东京豆（旧 App 端）：signBeanIndex 接口 2026-10-12 起服务端下线
- `jd_login.py` — 京东登录（旧 App 端扫码）：京东新版拒绝 tmauth，改用 Web 端 jd_web_signin.py

## 辅助脚本 / 离线单测

- `browser_cookies.py` — 浏览器 Cookie 提取库：绕 Chromium 独占锁读取并解密 cookie；跨平台 TEMP 整库缓存复用
- `_mishop_client.py` — 小米商城 mtop 客户端库：MiShop 设备头/服务Token/请求封装（xm_mijin.py 的依赖，凭证优先读 xm_mijin_config.json）


## 安全声明

- 本仓库**不含任何账号凭证**，config 全部需要你自己抓包生成（`.gitignore` 已防止误提交）
- 凭证有效期有限（分钟~天级），且部分平台是**服务端轮换制**（不是自然过期），失效后需重新抓包
- 自动化操作可能违反部分平台的服务条款，风险自负；请勿高频调用，接口异常先停手排查
- 仅供学习交流