# PreBell（预备铃）· 使用与口径

每天上课前 20 分钟，往你的微信推一条「下一大节上什么课、在哪个教室、这周到底有没有这节课」。
没课或这周不上就不打扰；微信发不出去就退回 `.ics` 日历订阅和网页，并把每轮跑没跑、推没推成功如实记成一条改不动的账。

## 定时不在 GitHub，在 cron-job.org

GitHub 的 `schedule` 最小粒度 5 分钟、高峰期排队能晚十几分钟。拿它当闹钟，只能靠
「每 5 分钟醒一次看看该不该发」来凑精度——那是拿看板对付日历，一周白烧七十多次，
而且每次都在重算一个学期都不会变的课表。

现在的分工：

```
cron-job.org（3 个 job，到点 POST workflow_dispatch，把大节号踢进来）
      ↓
GitHub Actions（只执行：查表 → 推微信 → 写哈希链 → 出 .ics / 网页）
      ↓
Server酱 → 微信
```

本课程表只有 3 个大节有课，所以一周只醒 10 次（周一 3、周二 2、周三 2、周四 2、周五 1）：

| job | 北京推送 | cron（UTC） | 涵盖 |
|---|---|---|---|
| `period=1` | 08:20 | `20 0 * * 1,4` | 周一、周四 |
| `period=3` | 13:10 | `10 5 * * 1,2,3,5` | 周一、二、三、五 |
| `period=4` | 14:50 | `50 6 * * 1,2,3,4` | 周一、二、三、四 |

这三行由 `src/resolve.py` 从课表反推，落在 `src/out/cron-hints.txt`。
**课表改了先重跑 `resolve.py`，再照抄那个文件改 cron-job.org**，别凭记忆改。

### 建 job 的参数（三个 job 除了 cron 和 period 号都一样）

- `POST https://api.github.com/repos/Dream404N/ICEC-2026-0163-LZH/actions/workflows/prebell.yml/dispatches`
- Headers：`Accept: application/vnd.github+json`、`Authorization: Bearer <token>`、`X-GitHub-Api-Version: 2022-11-28`
- Body（JSON 类型）：`{"ref":"main","inputs":{"period":"3","source":"cronjob"}}`
  （分支必须是 **`main`**——仓库默认分支是 main，填 `master` 会直接 422 `No ref found`）
- 时区保持 **UTC**，表达式按上表填

token 用 fine-grained PAT，只给这一个仓库的 `Actions: Read and write`，其余全 No access。
这个权限只能触发工作流，**读不了代码、改不了仓库**；即使泄露，上限是「别人帮你点一次运行」。
有效期设到学期末之后。

cron-job.org 免费、无 SLA。它的执行历史同时记录「计划时刻」和「实际执行时刻」（保留最近 50 次），
这是外部第三方独立留的时间证据——比我们自己写的任何字段都硬。

## 你要先做这几件事

**已完成（11-13 深夜，有日志可查）**：

1. ~~扫码注册 Server酱、拿 SendKey~~ —— 已配好，存在仓库 Secrets `PREBELL_SENDKEY`（只在此表单出现一次，不入库）。
2. ~~跑一次连通性探测~~ —— Actions 从境外 runner 探到 `sctapi.ftqq.com` **HTTP 200 / reachable**
   （`state/channel.json`）。这条推翻了本仓库此前「Actions 连不上国内站点」的悲观预期。
3. ~~发一条真实测试消息~~ —— `process_logs/2026-11-13.jsonl` 里 `event=test_push`、
   `push.status=ok`、`http=200`、`biz_code=0`、`attempts=1`、`ms=3989`。

**还差你来做**：

4. 按上面那张表在 cron-job.org 建 3 个 job，各点一次「Test run」：确认返回 204、Actions 里多出一个 run、日志里 `trigger_source` 是 `cronjob`。
   **branch 填 `main`**（填 `master` 会 422，仓库默认分支是 main）。
5. 对照 `src/timetable-source.png` 逐格核对 `src/timetable.json`。**闹钟按这张表准时响，表错了就准时推错课。**

SendKey 只存在于 GitHub Secrets。代码只读 `os.environ`，不写进 `state/`、`process_logs/`、`public/`、commit message 或任何文档；异常里的 URL 会被 `chain.scrub()` 抹成 `[url]`。

## 本机可以跑什么（不会推送、不会写云端目录）

```bash
cd 02-20Days-Challenge
python src/weeks.py                 # 六个周次表达式的解析样例
python src/resolve.py --check       # 只读：课表与已生成的 schedule.json 是否同步
python src/prebell.py --dry-run     # 本机预览，产物写到 src/out/
python src/prebell.py --dry-run --period 3 --source cronjob   # 模拟闹钟踢一脚
```

`--dry-run` 只算表、生成本地静态预览，**不推送、不写** `process_logs/` `state/` `public/`。
`resolve.py` 不带 `--check` 时会**重写** `src/schedule.json`、`src/schedule.md` 和
`src/out/cron-hints.txt`——只在课表真改了的时候跑它。
正常轮、连通性探测、测试消息都由 GitHub Actions 在云端执行；本机不跑常驻程序、不自启、不建定时任务。

## 课表数据从哪来

**只有一张 Excel 截图，没有 .xlsx 原文件**。截图已归档为 `src/timetable-source.png`，
内容由人工逐格转录成 `src/timetable.json`：

- 每格保留 `raw_text`（截图可见部分原文）与 `raw_text_note`；
- 看不清的字段一律 `null` + `unclear` 标记，**不猜、不填占位值**；
- `confidence` 分字段标注 high / medium / low；
- `review.pending_cells` 列出还需要你确认的格子。

这是**初稿**，`review.status = "unverified"`。请对照原图逐格核对，把结果写进 `review.changes`
（每条记 `cell_id`、字段、原值、改为、依据），再把 `status` 改为 `verified`、`meta.proofread` 改为 `true`。
这次校对会作为一次真实迭代留痕（已在 `iterations/` 的 `003`、`004` 之后）。校对前程序仍会推送，但**每条消息和网页都会带「课表未校对」声明**。

## 周次怎么算

`src/weeks.py` 用确定性正则展开，不用大模型：

| 原文 | 展开 |
|---|---|
| `3-13周,16-18周(混合)` | 3–13、16–18 周，形式「混合」 |
| `4-7周,12-13周,16周(讲课)` | 4,5,6,7,12,13,16 周 |
| `3周,6周,9周,12周,17周(实践)` | 3,6,9,12,17 周 |
| `18周(实践)` / `10周(讲课)` / `3-11周(理论)` | 单周或闭区间 |

解析不了的片段进 `unknown`，日志里记 `parse_unknown`，不静默丢弃。
同一格多门课按各自周号分流；同一周命中多门课记 `conflicts` 显式上报，不静默挑一门。
`span: 2` 表示截图里跨行合并单元格（周一第一+第二大节连上 4 节），按一条连续日程处理。

## 估算锚点（重要）

`anchor.first_monday = 2026-09-07` 是你 2026-11-13 说的「先估一个」，`status = "estimated" / verified: false`，
**未与教务校历核对**。所有由它推导出的「第几周 / 具体日期」都是推导值，不是事实。
推送文案、网页横幅、ICS 的 `DESCRIPTION` / `CATEGORIES:ESTIMATED-ANCHOR`、反馈表四处统一写：

> 学期第 1 周按 2026-09-07 估算、尚未核对；核对前请勿当作真实提醒使用。

核对后只需把 `verified` 改成 `true`、填 `verified_at` / `verified_by`，全链标注自动消失，diff 干净可审计。
**绝不把估算包装成事实。**

## 一天推几条、超了怎么办

本课表一天最多 3 个大节有课 = 最多 3 条，免费额度 5 条，余量留给测试消息。
同一大节多门课**合并成一条**；本周无课不推（记 `no_class_this_week`，留日志但不打扰）；
`state/pushed.json` 按 `日期 + 大节` 去重；达到上限记 `throttled` 跳过；
**推送失败标记 `attempted` 后不再重发**（仅 5xx/网络重试一次），避免重试打爆额度。
任何失败都写 `push.status=failed` + HTTP 状态 + 8 位指纹，不写 `ok`、不补记、不删。

比计划推送时刻晚超过 15 分钟就不发，记 `missed_too_late`——课已经上一半了，再推是噪音。
没超阈值的照发，但文案与日志都标实际送达时刻。阈值在 `config.example.json` 的
`late_limit_minutes`，改它不用改代码。

## 日志与证据链

复用 `src/chain.py`：每轮 `append_round()` 追加到 `process_logs/YYYY-MM-DD.jsonl`，
带 `prev_hash` 与 `hash`，每轮滚动重算当日 Merkle root 写进 `*.summary.json` 和 commit message；
`src/verify.py` 一键验真。日志字段含 `task`、`trigger_source`（cronjob/manual）、
`planned_push_at`、`actual_minute`、`late_by_min`、`schedule_slot`、`phase`、`course_hit`、
`push`、`channel_state`。

验真查两件事，缺一不可：**该响的有没有响**（课表里有这一节却没有对应记录 → `该响没响`），
**响了有没有真推成功**（有记录但 `push.status != ok` → `响了但没推成功`，附带原因）。
只查前者会把「推送失败 / 迟到超阈值放弃 / 渠道降级 / 额度用尽」统统算成齐，等于假报通过。

**诚实边界**：
- 计划时刻不是猜的：它来自课表算出的 `src/schedule.json`（96 条，整学期一次性展开），
  不是「按实际时刻向下对齐到 5 分钟格的近似值」；
- 迟到多少分钟如实记 `late_by_min`，超阈值记 `missed_too_late`，**不补推、不补写日志**；
- 无课的日子没有记录，这是设计：`verify.py` 的期望值从课表推导，不是写死的常量；
- 周末没课，所以 11-21、11-22 没有日志，也不拿别的日子凑「连续 7 天」；
- 11-10～11-16 的日志是旧「校园节点雷达」产生的，不是 PreBell 的；PreBell 的连续 7 天窗口从 11-17 起算。

## 合规边界

只调用 Server酱**官方公开 HTTPS 接口**，消息发到你本人扫码关注的「方糖」服务号。
**不读微信本地数据库、聊天记录、群消息，不逆向微信客户端，不登录微信，不碰学习通/教务登录态，不采集个人信息。**
腾讯 2026-01 的 DMCA 下架针对的是「逆向客户端 + 破解本地数据库密钥」，与本程序走官方接口推送不是一回事。

## 依赖

零第三方 Python 依赖，标准库即可（`urllib` 发 POST、`json` 读写、`datetime` 算周次）。
所有重复执行在 GitHub Actions；本机只需写文件与一次性预览。
