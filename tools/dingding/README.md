# 叮叮课表 · 本地部署版

三个文件，都不联网、不用账号、不用装环境、不用发布到公网。

| 文件 | 用在哪 | 怎么用 |
|---|---|---|
| `windows/叮叮课表.html` | Windows | 双击用浏览器打开，看今天上什么、下一次什么时候提醒 |
| `windows/叮叮课表.ics` | Windows | 双击导入「Windows 日历 / Outlook」，之后系统课前 20 分钟弹通知 |
| `dist/叮叮课表.apk` | 安卓 | 传到手机安装，打开点一次「写入手机日历」，之后系统课前 20 分钟弹通知 |

## 提醒到底怎么来

**不常驻、不自启、不跑定时任务、不联网。**
课表写进各自设备的**系统日历**，每节课带一条「提前 20 分钟」的提醒，由系统负责弹出。
所以关机重启、清后台、断网都不会漏。App / 网页开着时到点会额外弹一次，那只是增强，不是必需。

## 三步就能用

1. **Windows**：双击 `叮叮课表.html` 看课表；双击 `叮叮课表.ics` 导入日历，提醒就开了。
2. **安卓**：装 `叮叮课表.apk` → 打开 → 点「写入手机日历」→ 允许日历权限 → 完成。
   重复点不会产生重复日历项，按钮会回报「新增 X 节、跳过 X 节」。
3. **之后什么都不用做**。周一到周五课前 20 分钟，手机和电脑各自弹。

## 数据从哪来

唯一来源是 `02-20Days-Challenge/src/prebell/schedule.json` 里 **140 条真实有课提醒**，
由 `planner.py` 按周次展开课表生成。本目录不手抄任何一格课程。

改课表后重跑两条命令，Windows 版、安卓版、`.ics` 一起更新：

```
python tools/dingding/build_assets.py     # 三端界面 + ics
python tools/dingding/build_apk.py        # 本机出 APK
```

构建 APK 需要 `ANDROID_HOME`（本机 `I:\android-sdk-windows`）、`platforms/android-29`、
`build-tools/29.0.3` 和 JDK 17。走 `aapt2 → javac → d8 → zipalign → apksigner`，
**不需要 Gradle、不需要下载依赖、不需要 GitHub Actions、不需要网络**。

## 如实边界

- 课表第 1 周周一按 `2026-09-07` **估算，尚未与教务校历核对**；错一周整张日期表会整体平移。
  教师姓名辨读置信度低，故不展示。
- APK 签名复用仓库里已有的固定开发密钥（`tools/PowerProbe/signing/powerprobe.jks`），
  目的是以后每次构建都能直接覆盖安装、不清数据。这是开发密钥，不是账号凭据。
- 已在本机验证：签名可验、`classes.dex` / `resources.arsc` / `assets/index.html` 齐全、
  内嵌 140 条课程、权限只有日历与低版本存储、**没有 INTERNET 权限**。
  **尚未做真机安装与「写入日历」实测** —— 这一步要真人装一次才能确认，不冒充已验证。
- Windows 版是单个 HTML 文件（双击即用），不是 `.exe`；没有做安装器，也没有发布到公网。
