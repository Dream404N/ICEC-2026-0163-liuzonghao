# 这个目录里的日志从哪来

**结论：运行日志是 GitHub Actions 在云端跑完当场自己 `git commit + push` 回 `main` 的，
不需要任何人手动提交，也不允许从本机提交。** 提交者固定为 `prebell-bot`。

## 谁在写

| 工作流 | 北京时间 | 写入内容 |
|---|---|---|
| `.github/workflows/prebell-remind.yml` | 周一至周五 08:20 / 10:00 / 13:10 / 15:10 | 每轮一条 `YYYY-MM-DD.jsonl`（含 `prev_hash` 哈希链） |
| `.github/workflows/prebell-daily.yml` | 每天 23:55 | 当天 `YYYY-MM-DD.summary.json` + `public/prebell-verify.json` |

两条工作流都带 `permissions: contents: write`，最后一格会 `git add` 本目录后
`git commit` / `git pull --rebase` / `git push origin HEAD:main`。
本机同步脚本 `.workbuddy/sync_to_github.py` 把 `process_logs/` 和 `state/` 列为保护目录：
本地既不能覆盖、也不能删除、更不能新写日志文件。**唯一例外是本文件（口径说明）**。
这样设计是为了让「日志只能由云端真实运行产生」在机制上成立，不是靠人自觉。

## 什么时候有、什么时候没有

- 上课日的四个提醒点各有一条明细；那一节没课会写一条 `action: no_schedule`，也算真实运行。
- 周末和假期：四个提醒 cron 不跑，**没有明细 jsonl**；23:55 的汇总任务仍会真实运行并产出 summary。
- 汇总文件里的 `heartbeat: true` 只表示「当天 23:55 汇总任务确实跑过」，
  **不是一条提醒事件，也不会往 jsonl 里补任何东西**。旧版曾拿它凑连续天数，那个用法已废止。
- 迟到、推送失败、上课后才醒一律写 `skipped_late` / `error` / `skipped_after_class` 明细，
  不补推、不回填、不编造时间戳。手工预览（`--preview`）只发消息，不写本目录。

## 历史遗留：11-10 ~ 11-14 不是课表提醒的证据

目录里 `2026-11-10` 至 `2026-11-14` 的 jsonl / summary，来自**已停用定时的旧「校园节点雷达」**
（`probe.yml`，提交者 `ICEC Radar Bot`）。它们是旧项目真实留下的日志，**保留不删、不改写**，
但不能当成本项目的课表提醒证据。

一眼区分：

| | 旧雷达日志 | 现行课表提醒日志 |
|---|---|---|
| 字段 | `slot_3h` `sources` `filtered_total` `minute` | `period` `action` `key` `result` `source` |
| `hash` | 64 位完整 SHA-256 | 16 位截断哈希链，带 `prev_hash` |
| 日期 | 2026-11-10 ~ 2026-11-14 | 2026-11-16 起 |

特别注意 `2026-11-14.summary.json` 里的 `chain_len: 8`、`expected: 0`：
那 8 条是雷达当天的 8 次网页探测，**不是 8 次上课提醒**。
本项目 7 天窗口按 `11-16 ～ 11-22` 计算，从 11-16 周一开始。

## 怎么核对

```bash
cd 02-20Days-Challenge/src
python prebell/verify.py --date 2026-11-16            # 验单日明细与期望轮次
python prebell/verify.py --date 2026-11-22 --window 7  # 验 7 天窗口与哈希链
```

也可以在 GitHub 仓库页看 `prebell-bot` 的提交历史：每次真实运行都会留下
一条 `实测日志 YYYY-MM-DD ...` 的 commit，日志内容与 commit 一一对应。
