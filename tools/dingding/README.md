# 叮叮课表 · 多终端本地版

> **2026-11-15 需求变更**：使用者要求「做一个能开机自启、到点就弹的 Windows 程序」，
> 并要求「日志每天自动 commit 到 GitHub」「能即时测试通知」。
> 这推翻了 11-15 上午「不常驻、不自启、不产生日志」的旧口径。旧版文件仍保留，
> 但**以本文件为准**；变更理由见
`02-20Days-Challenge/iterations/008-开机自启多终端与客户端日志自动提交.md`。

## 有哪些东西

| 文件 | 用在哪 | 怎么用 |
|---|---|---|
| `windows/安装.cmd` | Windows | **双击安装**：复制程序、写开机自启、启动常驻、放桌面测试入口、当场弹一条测试通知 |
| `windows/卸载.cmd` | Windows | 双击取消开机自启 |
| `windows/dingding_win.py` | Windows | 安装版主程序（Python 3 标准库，零第三方依赖） |
| `windows/测试通知.cmd` | Windows | 双击立即弹一条测试通知（不安装也能测）；安装后桌面会另外生成一个入口 |
| `windows/叮叮课表.html` | Windows | 不安装也能双击看课表的单文件网页 |
| `windows/叮叮课表.ics` | Windows | 双击导入「Windows 日历 / Outlook」，系统级兜底提醒 |
| `windows/courses.json` | Windows | 140 条精简课表，由 `build_assets.py` 生成 |
| `dist/叮叮课表.apk` | 安卓 | 装完点「写入手机日历」+「开启后台提醒」 |
| `commit_usage_logs.py` | 两端 | 把客户端真实使用日志提交到 GitHub |
| `usage_logs/` | 两端 | 客户端真实事件日志（**不是**云端自动化运行日志） |

## 提醒到底怎么来（分设备说清）

**安卓：不需要本 App 的后台进程。** 两层都由系统持有：

1. **系统日历**（最稳）：`writeCalendar()` 把 140 节课写进手机自带日历，每节附提前 20 分钟
   系统提醒。App 卸载了都还在。
2. **系统闹钟**：`RemindReceiver` 用 `AlarmManager` 注册未来 7 天的提醒点，到点由系统拉起
   广播发通知；`BOOT_COMPLETED` / 应用更新后会自动重排。没有 Service、没有轮询、没有常驻进程。
   **实测入口**：点「测试 10 秒后闹钟」→ 退出 App → 10 秒后看通知栏，出来就说明链路通。

   可靠边界（不吹）：Android 12+ 用户可在设置里关掉「精确闹钟」（关了会退化成可能晚几分钟的
   普通闹钟）、Android 13+ 需要通知运行时权限、部分国产 ROM 会冻结开机广播或在「强停」后不唤醒。
   所以系统日历那层不能省。APK 仍然**没有 INTERNET 权限**。

**Windows：靠开机自启的常驻小程序。** `dingding_win.py --daemon` 由
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 拉起，每 15 秒查一次表，到点用
`MessageBoxW` 置顶弹窗 + 提示音。进程被结束就不会弹 —— 这一层**不是**「无进程也能响」；
不依赖任何进程的那层是 `.ics` 导入 Windows 日历后的系统提醒。
本机 `schtasks.exe` 被安全策略禁用，所以没有注册系统计划任务，这一条如实写明。

## 即时测试通知

- Windows：桌面「叮叮课表-测试通知.cmd」双击，或 `python dingding_win.py --test`。
  弹窗 5 秒自动关闭，不会卡住安装流程。也可 `python dingding_win.py --selftest`
  做不弹窗、不写注册表、不启动常驻的自检。
- 安卓：App 里「立即测试通知」当场弹；「测试 10 秒后闹钟」验证退出 App 后还能不能弹。
- 浏览器网页版：`叮叮课表.html` 的「立即测试通知」按钮（需先允许浏览器通知）。

## 客户端日志：每天自动 commit

常驻程序每天 **23:50** 调 `commit_usage_logs.py`，把 `usage_logs/` 下的
`YYYY-MM-DD.jsonl` 推到 GitHub。只记真实事件（安装、常驻启动、到点弹窗、手动测试、提交结果）；
关机、没启动、断网那天就是空白，**不补写、不造空文件凑连续天数**。

凭据只从工作区外 `.workbuddy/.gh_token` 读，**不写进客户端、不进日志、不入库**；
提交前机械扫描疑似密钥串；只增改、不删远端文件。

**关键区分**：`tools/dingding/usage_logs/` 是本机客户端使用记录，
`02-20Days-Challenge/process_logs/` 是云端 Actions 产生的自动化运行日志证据，
提交者分别是「本机推送」和 `prebell-bot`，**互不替代、互不冒充**。
两个目录各自的 `README.md` 写了完整口径。

## 三步就能用

1. **Windows**：双击 `windows/安装.cmd`（会当场弹一条测试通知）；再双击
   `windows/叮叮课表.ics` 导入日历作为兜底。
2. **安卓**：装 `dist/叮叮课表.apk` → 打开 → 点「写入手机日历」→ 点「开启后台提醒」
   → 点「测试 10 秒后闹钟」验证一次。
3. **之后什么都不用做**：课前 20 分钟各自弹；每天 23:50 客户端日志自动进 GitHub。

## 数据从哪来

唯一来源是 `02-20Days-Challenge/src/prebell/schedule.json` 的 **140 条真实有课提醒**，
由 `planner.py` 按周次展开。本目录不手抄任何一格课程。

改课表后重跑，五份产物一起更新：

```
python tools/dingding/build_assets.py     # 网页 + ics + courses.json（Win/安卓共用）
python tools/dingding/build_apk.py        # 本机出 APK
```

构建 APK 用本机 `ANDROID_HOME`（`I:\android-sdk-windows`）、`platforms/android-29`、
`build-tools/29.0.3`、JDK 17，走 `aapt2 → javac → d8 → zipalign → apksigner`，
**不需要 Gradle、不需要下载依赖、不需要 GitHub Actions、不需要网络**。

## 如实边界

- 课表第 1 周周一按 `2026-09-07` **估算，尚未与教务校历核对**；错一周整张日期表会整体平移。
  教师姓名辨读置信度低，故不展示。
- **安装包是双击即装的 `.cmd` 安装器，不是 `.exe` 安装包**。本机没有可用的 exe 打包工具，
  程序本体是标准库 Python + `pythonw.exe`（无黑框），安装动作是复制文件 + 写自启 +
  启动常驻 + 建桌面入口。不冒充做了 Windows Installer 包。
- APK 签名复用固定开发密钥（`tools/PowerProbe/signing/powerprobe.jks`），可直接覆盖安装。
- 已在本机验证：签名可验、`classes.dex` / `resources.arsc` / `assets/index.html` /
  `assets/courses.json` 齐全、内嵌 140 条课程、`RemindReceiver` 已编译进 DEX、
  有开机广播权限、**没有 INTERNET 权限**；Windows 程序 140 条自检通过、
  通知 API 可用、日志提交链路真实跑通（`1395795` / `5a50d2c`）。
- **尚未验证**：真机装 APK、真机写入日历、退出 App 后系统闹钟是否真弹、Windows 常驻进程
  到点是否真弹窗。这些只能真人装一次确认，不冒充已验证。
