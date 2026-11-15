# 课序 0.1.2 · 运行日志每天自动提交到 GitHub

> 项目四是「一个自己真能日用的课表软件」。本目录记录 11-15 追加到「课序」的那部分工作：
> **让 Windows 客户端自己把真实使用事件写成本机日志，每天定时 commit 到本仓库。**
> 只写事实：哪些是真的跑通的、哪些还没验证、哪些是修过的坑，都列在下面。

## 版本来源（如实交代）

「课序」是使用者在 `F:/下载/课表提醒/课表提醒` 的 Electron + Capacitor 工程，
由使用者用 Codex 辅助写成，本人对其界面和功能满意。它不是我写的，完整源码也**不在本仓库内**；
我这次只加了「每天自动 commit 日志」这条链路并接线到主进程 / 设置面板 / 托盘。
本仓库 `source/` 下只放**这次新增模块的源码快照**，便于评阅与复现，不冒充整个应用的源码。

| 新增 / 改动 | 位置（本机工程） | 快照 |
| --- | --- | --- |
| 日志同步核心 `LogSync` | `electron/log-sync.cjs` | `source/log-sync.cjs` |
| 命令行排查入口 | `scripts/log-sync-cli.cjs` | `source/log-sync-cli.cjs` |
| 单测（7 个用例） | `tests/log-sync.test.cjs` | `source/log-sync.test.cjs` |
| 主进程接线（启动/退出/提醒/休眠/托盘/IPC） | `electron/main.cjs` | 不复制，见下方差异说明 |
| 设置面板「运行日志 · GitHub」卡片 | `src/ui/Settings.tsx` | 不复制 |
| 窗口 API 声明与 preload 转发 | `src/platform/desktop.d.ts`、`electron/preload.cjs` | 不复制 |
| 版本号 / 使用说明 | `package.json`、`README.md` | 不复制 |

## 它是怎么跑的

- **只记真实事件**：启动、退出、提醒弹出、测试提醒、提醒计划变更、开机启动开关、休眠恢复、
  手动同步、同步失败。每条带 UTC 时间、北京时间、事件名、说明、`source: kexu-desktop` 和版本号。
  不记课表内容、账号、任何凭据；写日志时脱敏，提交前再用正则机械拦截疑似密钥串，命中即中止。
- **按北京日期分片**：本机 `%APPDATA%\classmate-reminder\usage_logs\YYYY-MM-DD.jsonl`。
- **零轮询**：每天只用一个 `setTimeout` 睡到 23:50（本机时间，可在设置面板改），
  触发后再排下一天；不扫课表、不联网探测。休眠恢复只重排定时器。
- **提交方式**：Node 标准库直连 GitHub Git Data API（blob → tree → commit → update-ref），
  基于远端最新 commit 建 tree，**只增改 `tools/kexu/usage_logs/`**，不删仓库里任何其他文件；
  内容没变化不重复提交；并发冲突取最新 head 重试一次。
- **凭据**：只读 `KEXU_GH_TOKEN` / `ICEC_GH_TOKEN` 环境变量或本机 `tokenFile`。
  配置文件里只有**路径**，没有 token；token 本身放在工作区外 `.workbuddy/.gh_token`，
  不进配置、不进日志、不进仓库。没配凭据时日志只留本机，写一条 `log_sync_skipped`，
  界面显示「未配置凭据」，**不会伪装成提交成功**。
- **不补写**：关机、彻底退出、断网、没打开应用的那天就是没有日志，不造心跳、不生成空提交。
  启动时若已过当天提交点且当天没提交过，只补传**本机已经真实存在**的日志，不新建记录。

## 本机目录的坑（11-15 修过，写清楚免得再踩）

安装版 Electron 的 `userData` 目录名取自 `package.json` 的 `name`，即
`%APPDATA%\classmate-reminder`；只有早期开发版才落在 `%APPDATA%\课序`。
修之前命令行按「课序」优先探测，看到的是另一份日志，而且安装版配置里 `tokenFile` 为空、
回退的 `~/.workbuddy/.gh_token` 并不存在 —— 也就是说**每天 23:50 只会静默跳过，功能等于没生效**。

修法：命令行改为「安装版目录优先」并新增 `token <绝对路径>` 子命令；
用该命令把凭据路径写进安装版配置；再把早期开发版目录里 2 条真实事件按整行去重合并进权威目录
（**只是把同一批真实事件换个存放位置，没有新建、补写或改写任何事件内容**）。

## 实证（可以逐条核）

| 项 | 结果 |
| --- | --- |
| 单测 | `node --test tests/log-sync.test.cjs` → 7/7 通过（含密钥拦截、配置校验、定时计算、脱敏、无空提交） |
| 远端提交 1 | `f0f707a` 课序运行日志 2026-11-15（真实事件 2 条，manual）—— 命令行验证链路 |
| 远端提交 2 | `ff77158` 课序运行日志 2026-11-15（真实事件 5 条，manual）—— 修好安装版凭据与目录后，从 `classmate-reminder` 目录同步 |
| **远端提交 3 · 定时触发** | `733442974e65e6ffa6583e4140e7280b4d5ee86e`：`课序运行日志 2026-11-15（真实事件 6 条，scheduled）`，提交者 `Dream404N`，22:35:06 北京时间。**这一次没有任何手动 `sync` 调用**，是 `scheduleNext()` 的单次定时器按真实时钟自己醒来后提交的 |
| 远端日志 | `tools/kexu/usage_logs/2026-11-15.jsonl` 6 条：21:28 验证 / 21:28 手动同步 / 21:52 应用启动 / 21:52 安排提醒 / 22:06 手动同步 / 22:33 `timer_probe`（同步动作自己也是一条真实事件） |
| 安装包 | `release/课序 Setup 0.1.2.exe`（132,215,401 字节，11-15 21:49，NSIS） |
| 包内核对 | `app.asar` 内 `electron/log-sync.cjs`、`electron/preload.cjs` 与源码逐字节一致；`electron/main.cjs` 只差打包后补的 2 行注释，`new LogSync({ userDataDir: app.getPath('userData') })` 与 `logSync.start()` 两行在包内都在；CLI 不打包进 asar |
| 客户端状态 | `node scripts/log-sync-cli.cjs status` → 目录 `classmate-reminder`、开启 23:50、凭据已配置、今日 6 条、最近提交 `7334429` |

### 定时触发是怎么验的（11-15 22:33～22:35）

把配置里的每日时刻**临时**改成 22:35，用一个 Node 宿主进程 `new LogSync(...)` 后只调用
`scheduleNext(cfg)`，然后让进程保活等着；期间不调用 `sync()`、`configure()` 或任何提交函数。
22:35:00 定时器自行唤醒 → `sync('scheduled')` → 真实走 GitHub API → 产生 `7334429`。
验完立即把时刻改回 **23:50**，状态命令可复核。

为了让提交有真实内容可提交，事先写了一条 `timer_probe` 事件，`detail` 明写
「真实时钟定时触发验证：本进程只排定时器，不手动调用 sync」，`app` 标为 `cli-timer-check`
—— **如实标注，不冒充一次用户启动或使用**。

⚠️ 边界说清楚：这次定时触发的宿主是 **Node CLI 进程**，用的是与软件内**同一个 `LogSync` 类、
同一份配置、同一个目录、同一条提交链路**，但**不是 Electron 应用窗口自己到点触发**。
Electron 那条路径要求应用在 23:50 时正在运行（见下节）。

`source/log-sync.test.cjs` 里用于测试密钥拦截的假密钥改成运行时拼接，
避免被本仓库同步脚本的「疑似密钥串」扫描当成真凭据误拦；测试断言与覆盖范围没变，仍是 7/7。

复现命令（本机工程目录下）：

```powershell
node --test tests/log-sync.test.cjs
node scripts/log-sync-cli.cjs status
node scripts/log-sync-cli.cjs token "C:\某处\.gh_token"   # 只写路径
node scripts/log-sync-cli.cjs sync                          # 真实提交一次
```

## 还没验证 / 不做的事

- **7 天连续日志才刚起跑**：今天是第一天，只有 1 个日期分片；「基于日志迭代」还没有第 2、3 次。
  这条不能靠补写凑，只能靠后面几天真实使用。
- **定时链路本身已实证，但应用窗口到点运行还没实证**：22:35 那次 `scheduled` 是真实时钟、
  真实网络、真实提交，但宿主是 Node CLI 进程，不是 Electron 窗口。要让「软件自己每天提交」成立，
  必须让课序在 23:50 时处于运行状态。11-15 22:31 实测本机**课序进程未运行、
  `HKCU\...\Run` 下也没有自启项**，所以当晚 23:50 不会有应用窗口触发的提交；
  需要本人打开软件，或在设置面板打开「开机自启」（该开关会如实记一条 `autostart_changed` 事件）。
  软件未运行/关机/断网的日子就是没有日志，不补写、不造心跳。
- 安卓端不产生这类日志（APK 无 INTERNET 权限，也没有放 GitHub 凭据）。
- 客户端日志与 `02-20Days-Challenge/process_logs/` 的云端 Actions 运行日志**分目录、互不冒充**；
  本仓库同步脚本已把本目录列为保护目录，本地不能删、不能用旧快照覆盖远端日志。
- 微信链路（Server酱 / 方糖）、8 位使用者反馈、校历锚点确认属于项目四其它部分，不在本模块范围内。
