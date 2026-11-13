# 预备铃 / PreBell · 项目四

每天上课前 20 分钟往微信推一条「下一大节上什么课、在哪个教室、这周到底有没有这节课」；
没课或这周不上就不打扰。微信发不出去就退回日历和网页，并把每轮跑没跑、推没推成功如实记成一条改不动的账。

**先看样张**：`preview.html`（双击即可打开，数据是示例，已标注）。
**看真实产物**：`public/index.html`、`public/calendar.ics`（由 GitHub Actions 生成，仅作推送失败时的兜底）。
**看字段与配置**：`src/PREBELL.md`。

## 你要做的一件事

微信扫码登录 <https://sct.ftqq.com/> → 关注「方糖」服务号 → 复制 SendKey →
在本仓库 **Settings → Secrets and variables → Actions** 新建 `PREBELL_SENDKEY` 并粘贴。
然后手动跑一次 `prebell.yml` 做连通性探测与一条真实测试消息，确认微信真的收到。
**SendKey 只存在于 Secrets**，代码只读环境变量，绝不入库。

## 本机可以跑什么

```bash
cd 02-20Days-Challenge
python src/weeks.py                 # 六个周次表达式的解析样例
python src/prebell.py --dry-run     # 本机预览，产物写到 src/out/
python src/verify.py                # 一键验真（需 clone 后已有云端日志）
```

`--dry-run` 不推送、不写 `process_logs/` `state/` `public/`。正常轮、连通性探测、测试消息
都由 GitHub Actions 在云端执行；本机不跑常驻程序、不自启、不建定时任务。

## 课表数据

只有一张 Excel 截图（已归档 `src/timetable-source.png`），**没有 .xlsx 原文件**。
内容人工逐格转录成 `src/timetable.json`：每格保留 `raw_text`；看不清的字段一律 `null` + `unclear`，
不猜、不填占位值。这是初稿，`review.status = "unverified"`，请对照原图校对一次（迭代 #1）。
校对前程序仍会推送，但每条消息与网页都带「课表未校对」声明。

学期第 1 周周一按 **2026-09-07 估算**、`verified: false`。推送文案、网页横幅、ICS 的
`CATEGORIES:ESTIMATED-ANCHOR`、反馈表四处统一写「核对前请勿当作真实提醒使用」。
核对只改这一个字段，全链标注自动消失。

## 周次解析为什么是核心

课表把「哪几周上课」塞在单元格文字里，写法混杂：`3-13周,16-18周(混合)`、
`4-7周,12-13周,16周(讲课)`、`3周,6周,9周,12周,17周(实践)`。
`src/weeks.py` 用确定性正则展开，范围 / 单周 / 逗号混排统一处理；括注教学形式只展示不推断；
解析不了的片段进 `unknown` 并写进日志，不静默丢弃。一格多课按周号分流，
同周撞车记 `conflicts` 显式上报；跨行合并单元格（`span:2`）按一条连续日程处理。

## 目录

| 路径 | 内容 |
|---|---|
| `src/timetable.json` | 人工转录的真实课表（初稿，含 `unclear` 与 `review.changes`） |
| `src/timetable-source.png` | 课表原图，校对依据 |
| `src/weeks.py` | 周次表达式解析 + 六个样例自检 |
| `src/prebell.py` | 单轮入口：算周次 → 判重 → 推送 → 记日志 → 生成兜底 |
| `src/config.example.json` | 非敏感默认值模板（**不叫 config.json**，避免被机械拦截） |
| `src/PREBELL.md` | 字段说明、校对流程、SendKey 配置步骤、合规边界 |
| `src/chain.py` | 哈希链、Merkle root、脱敏、每日汇总（PreBell 与旧雷达共用） |
| `src/verify.py` | 一键验真，按日期分段取期望轮次、汇总漏轮与格内偏移 |
| `state/` | 跨轮状态：`pushed.json` 去重、`channel.json` 连通性 |
| `process_logs/` | 每天一个 `.jsonl` + 一个 `.summary.json`，只追加不回填 |
| `public/` | 兜底产物 `.ics` 与网页 |
| `iterations/` | 三次由真实事件触发的迭代记录 |
| `feedback/` | 8 位同学的脱敏反馈 |
| `../.github/workflows/prebell.yml` | 新调度（11-17 前仅手动触发） |
| `../.github/workflows/probe.yml` | 旧雷达调度，11-17 后停用 schedule、文件保留 |

### 历史资产（雷达阶段，原样保留）

`src/probe.py`、`src/sources.json`、`src/interests.json`、`iterations/001-降频与订阅范围.md`
以及 11-10～11-16 的全部日志，都是上一版「校园节点雷达」的真实过程数据，
**不删、不改、不回填**。它们与 PreBell 共用同一条哈希链，但不计入 PreBell 的 7 天窗口。

## 日志里记什么

每轮一条 JSON：日期与分钟、5 分钟格近似槽位、格内偏移、与上一轮间隔、星期与估算周次、
阶段（`before` / `in_window` / `after` / `weekend` / `out_of_term`）、命中的课程、
周次冲突、解析未识别片段、推送状态（HTTP / 耗时 / 8 位错误指纹）、当日已推条数、
上一轮哈希与本轮哈希。

**不记**：IP、主机名、绝对路径、请求正文、SendKey、任何个人标识符、精确毫秒。
报错只留脱敏后的 8 位指纹；含 SendKey 的 URL 会被 `chain.scrub()` 抹成 `[url]`。

## 证据链怎么闭合

- 每条记录带 `prev_hash`，改任意一行，后面全部对不上；
- 每轮滚动重算当日 Merkle root，写进 `*.summary.json` 与 commit message；
- `verify.py` 重算全链，精确报出断在第几天第几条，并汇总 `漏轮` 与格内偏移。

缺勤不补写。cron 排队延迟造成的缺口会如实显示，这本身就是真实性的佐证。
`planned_slot_5m` 是按实际时刻向下对齐的**近似值**，GitHub 不暴露精确计划时刻，不假装知道。

## 依赖

零第三方 Python 依赖，Python 3.8+ 标准库即可（`urllib` 发 POST）。
所有重复执行都在 GitHub Actions 上，本机不需要运行任何东西。
