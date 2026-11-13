# 本机 dry-run 预览产物（示例性质，不是订阅源）

由 `python src/prebell.py --dry-run` 在 2026-11-13 一次性生成，用于确认程序能跑通、
网页长什么样。**不要导入这里的 `calendar.ics` 当真实课表**，理由：

- 课表 `timetable.json` 还是初稿，10 格里有 9 格带 `unclear` 待核对；
- 学期第 1 周周一 `2026-09-07` 是估算、未与校历核对；
- 这里没有微信推送，`push.status = skipped`。

真实的订阅源由 GitHub Actions 在推送失败时生成到 `02-20Days-Challenge/public/`。
本目录不受 `PROTECT_PREFIXES` 保护，随源码一起入库，仅为留一份可复现的预览快照。

复现：

```bash
cd 02-20Days-Challenge
python src/prebell.py --dry-run
```
