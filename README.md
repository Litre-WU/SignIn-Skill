# SignIn-Skill · 签到啦

多平台每日签到 / 领券 / 积分自动化工具集。遵循通用 **Agent Skill** 规范（`SKILL.md` + frontmatter 元数据 + `scripts/` 目录），可安装进任何支持该约定的 AI 编程/办公助手，也可完全脱离 AI 用纯 Python 独立运行。纯接口实现（非 UI 点击），自带幂等（当天重复执行自动跳过）与状态文件，适合挂 cron / 定时任务。

**本仓库收录 7 个稳定入口：**

| 平台 | 脚本 | 每日收益 |
|---|---|---|
| 美团券包 | `scripts/mt_api_coupon.py` | 每日领券 + 营销页红包 |
| 美团福利社 H5 | `scripts/mt_gundam_coupon.py` | 跨券墙 / 限时抢 / 天降掉券 |
| 南航小程序 | `scripts/csair_signin.py` | 签到 + 营销领里程 + 抽奖机会检测 |
| 魔搭 ModelScope | `scripts/ms_magicube.py` | 魔粒 +290/日 |
| WorkBuddy 积分 | `scripts/wb_score.py` | 签到 +100 + 派猫猫旅行 5~10 |
| 办公小浣熊（商汤） | `scripts/xhx_office_points.py` | 每日 300 积分确认 |
| Loomy（讯飞） | `scripts/loomy_points.py` | 每日积分确认 |

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

之后直接对助手说「签到」「领美团券」「南航签到」等，skill 会被触发并引导你抓包配置。每个平台只需**抓 1 条请求**发给助手，它会自动生成 `scripts/<平台>_config.json` 并试跑（抓法详见 `SKILL.md` 各平台小节）。

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
   python scripts/mt_api_coupon.py claim        # 美团领券
   python scripts/mt_gundam_coupon.py           # 美团福利社 H5
   python scripts/csair_signin.py signin        # 南航签到
   python scripts/ms_magicube.py auto           # 魔搭魔粒
   python scripts/wb_score.py auto              # WorkBuddy 积分
   python scripts/xhx_office_points.py auto     # 办公小浣熊
   python scripts/loomy_points.py auto          # Loomy
   ```
5. 定时：挂 cron / 任务计划程序 / 任意调度器每日一次即可；当天已完成的自动跳过，重跑可删除对应 `*_state.json`。

## 安全声明

- 本仓库**不含任何账号凭证**，config 全部需要你自己抓包生成（`.gitignore` 已防止误提交）
- 凭证有效期有限（分钟~天级），失效后需重新抓包
- 自动化操作可能违反部分平台的服务条款，风险自负；请勿高频调用，接口异常先停手排查
- 仅供学习交流


---

https://www.workbuddy.cn/events/invite?inviteCode=thb5u68d9bp6oc

快来认识我的工作好搭子 Loomy，比龙虾🦞更易上手、更好用！快去 https://loomy.xunfei.cn/download 下载安装，输入我的专属邀请码 DF9N3T 即可开启体验～
