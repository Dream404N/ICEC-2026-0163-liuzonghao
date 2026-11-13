# PreBell（预备铃）· 使用与口径

每天上课前 20 分钟，往你的微信推一条「下一大节上什么课、在哪个教室、这周到底有没有这节课」。
没课或这周不上就不打扰；微信发不出去就退回 `.ics` 日历订阅和网页，并把每轮跑没跑、推没推成功如实记成一条改不动的账。

## 你要做的一件事

1. 打开 <https://sct.ftqq.com/>，用微信扫码登录，关注「方糖」服务号，复制 **SendKey**。
2. 进本仓库 **Settings → Secrets and variables → Actions**，新建 Secret：
   - Name：`PREBELL_SENDKEY`
   - Value：粘贴刚才复制的 SendKey（只在网页表单里出现一次）
3. 在 Actions 里手动跑一次 `prebell.yml`（`workflow_dispatch`），先做连通性探测，再发一条真实测试消息；**你确认微信真的收到**才算通道打通。失败会记 HTTP 状态与 8 位错误指纹，并自动降级，绝不写「推送成功」。

SendKey 只存在于 GitHub Secrets。代码只读 `os.environ`，不写进 `state/`、`process_logs/`、`public/`、commit message 或任何文档；异常里的 URL 会被 `chain.scrub()` 抹成 `[url]`。

## 本机可以跑什么（不会推送、不会写云端目录）

```bash
cd 02-20Days-Challenge
python src/weeks.py                 # 六个周次表达式的解析样例
python src/prebell.py --dry-run     # 本机预览，产物写到 src/out/
```

`--dry-run` 只算课表、生成本地静态预览，**不推送、不写** `process_logs/` `state/` `public/`。
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
这次校对就是三次真实迭代的第 1 次，diff 会留痕。校对前程序仍会推送，但**每条消息和网页都会带「课表未校对」声明**。

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

## 五条/天怎么不超

4 大节 × 各 1 条 = 4 条，免费额度 5 条，余 1 条给测试消息。
同一大节多门课**合并成一条**；本周无课不推；`state/pushed.json` 按 `日期 + 大节` 去重；
达到上限记 `throttled` 跳过；**推送失败标记 `attempted` 后不再重发**（仅 5xx/网络重试一次），
避免重试打爆额度。任何失败都写 `push.status=failed` + HTTP 状态 + 8 位指纹，不写 `ok`、不补记、不删。

## 日志与证据链

复用 `src/chain.py`：每轮 `append_round()` 追加到 `process_logs/YYYY-MM-DD.jsonl`，
带 `prev_hash` 与 `hash`，每轮滚动重算当日 Merkle root 写进 `*.summary.json` 和 commit message；
`src/verify.py` 一键验真。日志字段含 `task`、`phase`、`course_hit`、`conflicts`、
`parse_unknown`、`push`、`channel_state`、`planned_slot_5m`（近似）、`actual_minute`。

**诚实边界**：
- `planned_slot_5m` 是按实际时刻向下对齐的近似值，GitHub 不暴露精确计划时刻，**不假装知道**；
- cron 排队延迟、丢轮如实记 `missed_no_backfill`，**不补推、不补写日志**；
- 周末心跳只写一条真实日志、不推微信；
- 11-10～11-16 的日志是旧「校园节点雷达」产生的，不是 PreBell 的；PreBell 的连续 7 天窗口从 11-17 起算，不拿前面凑数。

## 合规边界

只调用 Server酱**官方公开 HTTPS 接口**，消息发到你本人扫码关注的「方糖」服务号。
**不读微信本地数据库、聊天记录、群消息，不逆向微信客户端，不登录微信，不碰学习通/教务登录态，不采集个人信息。**
腾讯 2026-01 的 DMCA 下架针对的是「逆向客户端 + 破解本地数据库密钥」，与本程序走官方接口推送不是一回事。

## 依赖

零第三方 Python 依赖，标准库即可（`urllib` 发 POST、`json` 读写、`datetime` 算周次）。
所有重复执行在 GitHub Actions；本机只需写文件与一次性预览。
