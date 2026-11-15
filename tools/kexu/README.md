# 课序 0.1.4 · 运行日志每天自动提交到 GitHub

> 项目四是「一个自己真能日用的课表软件」。本目录记录 11-15 追加到「课序」的那部分工作：
> **让 Windows 客户端自己把真实使用事件写成本机日志，每天定时 commit 到本仓库。**
> 只写事实：哪些是真的跑通的、哪些还没验证、哪些是修过的坑，都列在下面。

## 版本来源（如实交代）

「课序」是使用者在 `F:/下载/课表提醒/课表提醒` 的 Electron + Capacitor 工程，
由使用者用 Codex 辅助写成，本人对其界面和功能满意。它不是我写的；
**11-16 已把完整桌面工程源码（65 个文件 / 627 KB）同步到本仓库 [`app/`](app/)**，
原工程仍在本机 F 盘作为开发副本。
我这次只加了「每天自动 commit 日志」这条链路并接线到主进程 / 设置面板 / 托盘；
0.1.3 把「凭据文件路径」做进设置面板，让安装包自包含、换电脑不必再跑命令行；
0.1.4 修复启动时 `RangeError: Invalid time value` 并补回归单测（详见下方 11-16 排障）。
本仓库 `source/` 下放**日志模块与本次改动涉及的源码快照**，便于单独审阅；
`app/` 是可 `npm ci && npm run desktop:dist` 复现的完整工程（见
[`app/SOURCE-SNAPSHOT.md`](app/SOURCE-SNAPSHOT.md)），两者重叠的文件内容一致。
**全量源码安全审计（有没有远控 / 后门）见 [`SECURITY-AUDIT.md`](SECURITY-AUDIT.md)。**

| 新增 / 改动 | 位置（本机工程） | 快照 |
| --- | --- | --- |
| 日志同步核心 `LogSync` | `electron/log-sync.cjs` | `source/log-sync.cjs` |
| 命令行排查入口 | `scripts/log-sync-cli.cjs` | `source/log-sync-cli.cjs` |
| 单测（7 个用例） | `tests/log-sync.test.cjs` | `source/log-sync.test.cjs` |
| 主进程接线（启动/退出/提醒/休眠/托盘/IPC） | `electron/main.cjs` | 不复制，见下方差异说明 |
| 设置面板「运行日志 · GitHub」卡片 | `src/ui/Settings.tsx` | 不复制 |
| 窗口 API 声明与 preload 转发 | `src/platform/desktop.d.ts`、`electron/preload.cjs` | 不复制 |
| 版本号 / 使用说明 | `package.json`、`README.md` | 不复制 |

## 可执行文件在哪（哪个才带自动 commit）

**带自动 commit 的是 0.1.2 / 0.1.3 / 0.1.4** —— `log-sync.cjs` 是 11-15 21:24 才新增的，
0.1.0（16:07 打包）、0.1.1（16:47 打包）里根本没有这个模块。

| 用途 | 绝对路径（本机工程 `F:/下载/课表提醒/课表提醒/` 下） | 大小 / SHA-256 |
| --- | --- | --- |
| **当前 · 0.1.4 安装包**（修复启动报错，双击是「安装」） | `release/课序 Setup 0.1.4.exe` | 132,216,066 B · `33481015…bdf5` |
| 同上，构建输出原件 | `release-014/课序 Setup 0.1.4.exe` | 与上者**哈希完全相同** |
| **当前 · 0.1.4 免安装主程序**（已就地换进 `I:\kebiao\classmate-reminder`） | `release-014/win-unpacked/课序.exe` | 250,057,216 B |
| 0.1.3 旧安装包（有启动 `RangeError`，见下方排障） | `release/课序 Setup 0.1.3.exe` | 132,215,755 B · `cfb7d332…b582ce2` |
| 0.1.3 构建输出原件 | `release-013/课序 Setup 0.1.3.exe` | 与上者**哈希完全相同** |
| 0.1.3 免安装主程序 | `release-013/win-unpacked/课序.exe` | 250,057,216 B · `536ba0aa…d0fe0` |
| 0.1.2 旧安装包（有链路，但设置面板没有凭据入口） | `release/课序 Setup 0.1.2.exe` | 132,215,401 B · `4a13bf96…a54ec` |
| 不带自动提交 | `release/课序 Setup 0.1.0.exe`、`…0.1.1.exe` | — |

⚠️ 两个坑：① `release/win-unpacked/` 是 0.1.2 的残缺残留，**主程序 `课序.exe` 已不在**，只剩
`locales/` 和 `resources/`，别去那里双击；② 便携版主程序**必须连同整个 `win-unpacked/` 目录**
一起保留（依赖 `resources/app.asar`、dll、`locales/`），单独拷出 exe 跑不起来。

`package.json` 的 `name` 仍是 `classmate-reminder`，所以装完 / 跑起来后 `userData` 还是
`%APPDATA%\classmate-reminder`，**会直接继承现有 `log-sync.json`**（已开启、23:50、凭据路径有效），
不用再填一次。运行时是 Electron 45.3.2；该版本官方 dist 本身就不含
`libEGL.dll` / `libGLESv2.dll`，便携目录里没有这两个文件属正常，不是打包缺失。

## GitHub 发行版（可直接下载）

11-16 00:5x 发布 Release **`kexu-0.1.3`**：
<https://github.com/Dream404N/ICEC-2026-0163-LZH/releases/tag/kexu-0.1.3>

| 项 | 值 |
| --- | --- |
| 附件名 | `Kexu-Setup-0.1.3.exe`（显示标签「课序 Setup 0.1.3.exe · Windows 安装包（NSIS）」） |
| 大小 / SHA-256 | 132,215,755 B · `cfb7d332683875d049361971cb0f2c40df0cfc999eeb074d6a5d2f429b582ce2` |
| 下载直链 | <https://github.com/Dream404N/ICEC-2026-0163-LZH/releases/download/kexu-0.1.3/Kexu-Setup-0.1.3.exe> |

GitHub 会清洗 asset 名里的中文与空格（首次上传被改名成 `Setup.0.1.3.exe`），所以改用
ASCII 文件名、中文放 label；**附件内容就是本机 `release/课序 Setup 0.1.3.exe`，哈希逐字节相同**。

exe 不进 git 树（单文件 132 MB 超过仓库 100 MB 限制），但 Release 附件上限 2 GB，
因此单独作为发行版发布，评审可直接下载，不必依赖本机路径。仓库目前仍为 **Private**，
下载需要该账户权限；11-20 转公开后链接才对所有人可访问。

**修复版 Release [`kexu-0.1.4`](https://github.com/Dream404N/ICEC-2026-0163-LZH/releases/tag/kexu-0.1.4)**：
附件 `Kexu-Setup-0.1.4.exe`（132,216,066 B，SHA-256 `33481015…bdf5`），
修复下文那个启动 `RangeError`。0.1.4 直接用 ASCII 附件名，中文放在 label，不再被 GitHub 清洗。

已装 0.1.3 的使用者**不必重装**：本次把 0.1.4 构建的整个 `win-unpacked` 运行目录
（227 个有差异的文件 / 327 MB，含带 asar integrity 资源的 `课序.exe`、`app.asar`、
`app.asar.unpacked/`）就地覆盖进 `I:\kebiao\classmate-reminder`，保留卸载程序、
开始菜单快捷方式和已修好的 ACL。 Electron 会把 asar 哈希写进 exe 资源，
所以**不能只换 `app.asar`**，必须连主程序一起换。

0.1.0 / 0.1.1 / 0.1.2 **未作为发行版上传**，只在本机保留安装包与哈希，不冒充已发布。

## 11-16 实机排障：装到 I 盘后双击打不开

使用者 11-16 00:44 把 0.1.3 装到 **`I:\kebiao\classmate-reminder\`**，双击无窗口。
Windows 事件日志出现多条 `Application Error / Id 1000`：`Faulting application 课序.exe 0.1.3.0`、
异常码 `0x80000003`、fault offset 固定为 `0x7564bbe`（确定性崩溃，不是偶发）。

在干净环境捕获 stderr 拿到 Electron 的 FATAL 原文：

```
FATAL: electron\shell\browser\win\install_dir_access.cc:52
Sandboxed processes cannot read I:\kebiao\classmate-reminder:
its ACL has an entry for an AppContainer package SID but none for
ALL APPLICATION PACKAGES, so Windows denies the sandbox token access.
```

**根因**：该目录 ACL 里有两条 AppContainer SID（`S-1-15-3-1024-…` 与
`S-1-15-2-3441000631-…`），却缺 `S-1-15-2-1`（ALL APPLICATION PACKAGES）。
Electron 45 的沙箱进程因此读不到安装目录，启动即触发断点断言。
**不是代码坏了，也不是 0.1.3 安装包缺文件** —— 安装目录的 dll / pak / `app.asar` 经核对齐全
（Electron 45 官方 dist 本就不含 `libEGL.dll` / `libGLESv2.dll`）。

**修复**（Electron 官方给出的命令，只加一条「只读 + 执行」，不改动其它 ACE）：

```powershell
icacls "I:\kebiao\classmate-reminder" /grant "*S-1-15-2-1:(OI)(CI)(RX)"
```

修复后重新在干净环境启动，进程持续运行不再 FATAL，并真实写出
`usage_logs/2026-11-16.jsonl` 两条事件（`app_start`、`reminders_scheduled`，版本 `0.1.3`）。
装到 C 盘默认用户目录一般遇不到这个 ACL；这是 I 盘该目录的既有权限遗留。

⚠️ 排障时还踩过一个**只属于 AI 终端**的干扰：WorkBuddy 的 shell 注入了
`ELECTRON_RUN_AS_NODE=1`，在终端里直接启动 exe 会变成 Node 空跑并报
`bad option: --enable-logging=stderr`，与使用者双击 Explorer 的环境无关。
复现真实启动必须先清掉该变量（`env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS`）。

### 顺带查出的真 bug（0.1.4 修复）

ACL 修好后启动日志里出现 `运行日志启动失败 RangeError: Invalid time value`，
定位到 `log-sync.cjs` 的 `start()`：`writeState` 把 `lastCommitAt` 存成 ISO 字符串，
却直接传给只接受毫秒数的 `beijingDate()`，字符串与 `8*3600000` 相加产生 Invalid Date。
`main.cjs` 用 `.catch()` 吞掉了错误，且 `scheduleNext(cfg)` 在报错**之前**已执行，
所以当天 23:50 的定时器仍会排上；坏的是「今天已提交就不补传」与跨日 catch-up 判断。

0.1.4 改为 `Date.parse()` 归一化并校验 `Number.isFinite`，加了回归单测：
`node --test tests/log-sync.test.cjs` **8/8**、`npm run check` **13/13** 通过。
本次不重装、不改动 I 盘 ACL，直接把 0.1.4 构建产出的 `app.asar` 与
`app.asar.unpacked/` 就地换进已安装目录（含正确的 unpacked 标记，关键文件
`electron/reminders.ps1` 在内）；卸载项仍显示 0.1.3，属如实记录，不影响运行。

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
| 安装包（当前） | `release/课序 Setup 0.1.4.exe`（132,216,066 字节，11-16 01:03，NSIS；SHA-256 `33481015…bdf5`）。修复启动 `RangeError`；0.1.3 曾新增凭据输入，0.1.4 沿用 |
| 旧安装包 | `release/课序 Setup 0.1.2.exe`（132,215,401 字节，11-15 21:49）仍保留，未覆盖 |
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

- **7 天连续日志窗口从 11-16 起算**：11-15 的 6 条是链路验证，不算窗口内日志；
  截至 11-16 00:02 远端**没有 `2026-11-16.jsonl`**。窗口是 11/16～11/22，
  「基于日志迭代」还没有第 2、3 次。这条不能靠补写凑，只能靠后面几天真实使用。
- **定时链路本身已实证，但应用窗口到点运行还没实证**：22:35 那次 `scheduled` 是真实时钟、
  真实网络、真实提交，但宿主是 Node CLI 进程，不是 Electron 窗口。要让「软件自己每天提交」成立，
  必须让课序在 23:50 时处于运行状态。
- **11-15 23:50 的事后核对（11-16 00:00 查）**：11-15 22:31 实测本机课序进程未运行、
  `HKCU\...\Run` 下无自启项，当时预判「当晚 23:50 不会有提交」。跨日后核对远端证实：
  最近一次提交停在 `22a224d`（22:53，人工收尾提交），**23:50 没有任何 scheduled 提交**；
  `2026-11-15.jsonl` 仍是 6 条，`2026-11-16.jsonl` 不存在。原因不是代码失效，是**软件没开**。
  需要本人打开软件，或在设置面板打开「开机自启」（该开关会如实记一条 `autostart_changed` 事件）。
  软件未运行/关机/断网的日子就是没有日志，不补写、不造心跳。
- **本机安装状态审计（11-16 00:02，只读）**：注册表卸载项、开机自启 `Run` 键、计划任务、
  Windows 服务、开始菜单快捷方式、程序安装目录 —— **课序/kexu/classmate 全部零命中**；
  当前也没有课序或 Electron 进程。也就是说**没有在这台电脑上安装任何常驻组件**。
  `%APPDATA%\classmate-reminder\` 是 Electron 运行时自动生成的 `userData`（21:52 曾运行过一次 0.1.2），
  里面只有缓存、一份 246 字节的配置（只含凭据**路径**，不含凭据本身）、真实日志与提交状态；
  `release/` 下 4 个 `课序 Setup *.exe` 是**安装包文件，从未执行安装**。
- 安卓端不产生这类日志（APK 无 INTERNET 权限，也没有放 GitHub 凭据）。
- 客户端日志与 `02-20Days-Challenge/process_logs/` 的云端 Actions 运行日志**分目录、互不冒充**；
  本仓库同步脚本已把本目录列为保护目录，本地不能删、不能用旧快照覆盖远端日志。
- 微信链路（Server酱 / 方糖）、8 位使用者反馈、校历锚点确认属于项目四其它部分，不在本模块范围内。
- **11-16 已实机验证**：0.1.3 与 0.1.4 都在本机真实启动并写出 `2026-11-16.jsonl`
  真实事件（`app_start` / `reminders_scheduled`），0.1.4 主窗口「课序 · 把时间留给学习」实测可见。
  仍未验证的是「在设置面板里真填一次凭据文件路径」与「应用窗口自己在 23:50 到点提交」。
  新机若 `userData` 是全新的，需在「偏好设置 → 运行日志 · GitHub」填一次凭据文件路径。
