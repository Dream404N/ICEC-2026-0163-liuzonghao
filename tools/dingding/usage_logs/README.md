# 这是什么日志（别和 `process_logs/` 搞混）

这里放的是 **「叮叮课表」Windows 客户端在本机真实产生的事件**：
安装、常驻启动、到点弹窗、用户手动测试通知、每天 23:50 的提交结果。
由 `tools/dingding/windows/dingding_win.py` 追加，字段是
`ts`（真实本地时间）/ `event` / `detail` / `ok` / `source`。

**它不是官网项目四要求的「程序自动化运行日志」。**
那一份在 `02-20Days-Challenge/process_logs/`，只由云端 GitHub Actions
（`prebell-remind.yml` / `prebell-daily.yml`，提交者 `prebell-bot`）生成，
本地既不能写也不能删，口径见 `02-20Days-Challenge/process_logs/README.md`。
两个目录**互不替代、互不混入**：把本机点击记录冒充云端无人值守证据，就是造假。

## 谁在提交

`tools/dingding/commit_usage_logs.py` 由常驻程序每天 23:50 调用一次，
只推本目录下的 `YYYY-MM-DD.jsonl` 和这个 `README.md`，提交信息固定带
「本机真实事件，非云端运行日志」。
凭据只从工作区外 `.workbuddy/.gh_token` 读取，**不写进客户端、不进日志、不入库**。
提交前会机械扫描疑似密钥串，命中即中止；只增改、不删远端任何文件。

## 什么时候是空的

- 电脑没开机、常驻程序被结束、当天没触发任何事件 → 那天没有 jsonl，**不补写**。
- 断网或 GitHub API 失败 → 提交结果如实记 `ok:false`，不重试到伪造成功，
  日志留在本地，下次启动后由下一次提交带上。
- 周末没课 → 可能有 `daemon_start`，但不会有 `reminder_fired`，这是正常的。

## 怎么核对

```bash
python tools/dingding/windows/dingding_win.py --status
python tools/dingding/windows/dingding_win.py --selftest
python tools/dingding/commit_usage_logs.py          # 手动补提交当天日志
```

在 GitHub 上看提交者：客户端日志由「本机推送」产生，提交信息带「叮叮课表 客户端使用日志」；
云端运行日志由 `prebell-bot` 产生，提交信息带「实测日志」。两者一眼可分。
