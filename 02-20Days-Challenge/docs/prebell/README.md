# 预备铃 · 课表微信提醒（从零重写版）

上课前 **30 分钟**推「准备好东西、可以出发」，上课前 **5 分钟**推「进入教室」。
按课表每天定时，消息经 **Server酱 Turbo 微信服务号 1:1 通知**送达，备用 **WxPusher SPT 1:1 通知**兜住周一第 6 条。两条都不是群消息。纯 Python 标准库，零第三方依赖。

- 程序源码：`02-20Days-Challenge/src/prebell/`
- 部署与排期：`docs/prebell/RUNBOOK.md`
- 密钥与脱敏：`docs/prebell/PRIVACY.md`

## 一、官网规则 → 程序契约

出处：`https://icec.openkub.com/assessment.html`（本机快照 `icec_assessment.html`，行号同文件）。

| 官网条款 | 逐字要点 | 程序自动产出 | 落盘 | 评委怎么核 |
|---|---|---|---|---|
| L375 ① 25 分 | 连续不少于 7 天的程序自动化运行日志，含脱敏时间戳、调用频次、耗时与报错记录，每日同步至 `process_logs/` | `ledger.py` 写 JSONL + 哈希链；`prebell-daily.yml` 每日汇总并提交 | `process_logs/`（protected） | 日期无缺口 + 四类字段齐全 + 哈希链自洽 |
| L645（英文版） | `JSONL/CSV` 与 `committed daily` | 同上，每日 commit `实测日志 YYYY-MM-DD` | 同上 | `git log` 每日一条 |
| L375 ② 20 分 | 基于日志的至少 3 次 Git 迭代 Diff 记录 | `verify.py` 暴露问题 → 改码 → commit | `iterations/prebell/` + git log | ≥3 条 diff 能对上日志异常 |
| L375 ③ 15 分 | 完整源码与 8 位真实用户使用反馈 | `src/prebell/*`、`feedback/` | `src/prebell/`、`feedback/` | 源码可运行 + 8 份真实反馈 |
| L433 / L438 / L440 | 面试基于个人仓库代码与过程数据动态追问「采样边界、异常数据原因、排障细节」 | `run.py` 的 `source` / `skipped_*` / `error` / `latency_ms` 字段 | `process_logs/`、`iterations/` | 能回溯为何跳过、为何改码 |
| L202 / L205–209 / L222–227 | 公开仓库、4 项标准目录、6 条 Git 命令 | 沿用仓库既有结构 | 顶层 4 项 | 目录结构与 `git commit -m "实测日志"` 口径 |
| L159 | 鼓励合理使用 AI 工具，重点凭实测数据、运行日志与版本记录核验能力 | 全链路如实留痕 | 全仓库 | 数据自洽 |
| L326 / L327 | 8 选 1 · 60 分 · 初定 10/23~11/24；强制跨多日连续过程数据 | 7 天窗口设计 | `process_logs/` | 连续性 |

**品行底线**（出处为 `admissions.html`，**不在考核页**）：`如实提交原始数据，严禁造假或代做`、`一票否决项`。
程序侧对应：迟到/失败一律写 `skipped_*` / `error` 明细，不补推、不回填、不编造时间戳；课表估算与未核对字段原样保留。

### 出处勘误（写文档时必须分开）
- 考核页 HTML 内**没有**「封仓 / 诚信 / 造假 / 代做 / 一票否决 / 严禁 / 如实 / 可能调整」字样。
- 「封仓 2026-11-24」出自仓库顶层 `README.md:12`；品行底线出自 `admissions.html`。
- 「初定」仅见 L326、L432；`JSONL/CSV` 与 `committed daily` 仅见英文版 L645。
- 时间 banner L168：10/15 宣传 → 10/28 说明会 → 10/23 启动工坊 → 11/24 工坊结束并启动面试 → 12/01 公布名单。

## 二、官网规则 vs 工程自选（不要混写）

| 官网规则 | 工程自选（官网未提） |
|---|---|
| 公开仓库、命名格式、4 项标准目录、6 条 Git 命令 | Server酱 Turbo + WxPusher SPT 双 1:1 通道、GitHub Secrets |
| 项目四三项必交、7 天日志、3 次迭代、8 位反馈 | 任何 token / SendKey / SPT / GitHub Secrets |
| 面试溯源、品行底线 | 外部 cron、`workflow_dispatch`、30/5 分钟双时点 |
| 「初定」时间节点 | `state/`、`public/`、哈希链、ICS/网页兜底、`max_push_per_day` |

## 三、当前交付状态（如实）

- ✅ 源码、静态提醒表（360 条 / 20 条·周）、两个 workflow、文档模板 —— 已完成，11 项本地自检全绿。
- ⬜ **7 天真实运行日志尚未起跑**：`process_logs/`、`state/`、`public/` 是 protected 目录，只由云端 Actions 生成，本地不写、不伪造。
- ⬜ **8 位真实用户反馈**：`feedback/` 只提供 `TEMPLATE.md`，8 份内容必须由真实用户填写，**不预写、不代填**。
- ⬜ **3 次 Git 迭代**：`iterations/prebell/` 只提供说明，011–013 必须由真实日志观察驱动后再创建，**不预写**。
- ⬜ 开工前置（用户侧外部动作）：官网要求公开仓库 + 姓名拼音全拼，现状顶层 README 声明 `Private` + 缩写名 `LZH`。
