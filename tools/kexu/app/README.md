# 课序 · Windows / 安卓课表提醒

个人课表工具：按教学周查看课程，提前提醒，手动或 Excel / CSV 维护课表。React + TypeScript 共用逻辑，Electron 提供 Windows 应用，Capacitor 提供安卓应用，Supabase 提供可选账号同步。

## 先用起来

Windows 最新安装包在 `release/课序 Setup 0.1.3.exe`；安卓 APK 在 `android/app/build/outputs/apk/debug/app-debug.apk`。本地功能无需账号或云配置。0.1.1 修正 Windows 提醒：采用类似聊天软件的右下角独立弹窗；0.1.2 新增「运行日志每天自动提交到 GitHub」；**0.1.3 把凭据配置做进设置面板**（换电脑安装后不必再跑命令行），并补了一份源码安全审计说明。见下方专节。

1. 打开「偏好设置」，填写**第一周的周一日期**，保存学期设置。
2. 「课程管理」中已录入截图的 9 门课程。逐门核对教师、教室、周次，然后取消「待校对」。图片文字较小，转录信息不能视为学校确认数据。
3. 「本设备提醒」检查通知权限，发送测试提醒。默认提前 15 分钟，可填 `15,5`。
4. 日常在课程详情选择「只修改这一次」进行调课、换教室或停课；常规排课在「修改整条规则」中编辑。补课入口在课程管理，调整记录可恢复原安排。
5. 「导入与备份」下载模板，按每行一条规则维护课程。替换和恢复会先导出安全备份。

已归档学期保留课程、停止提醒；所有未归档学期均参与提醒计算。本机通知开关、提示音、提前时间及开机启动独立保存，不上传云端。

## 从源码运行

需要 Node.js 22.12+（本次使用 24）。在项目目录运行：

```powershell
npm.cmd ci
npm.cmd run dev
```

浏览器预览地址为 `http://127.0.0.1:5173`。浏览器需要保持页面运行才能提醒；后台提醒请使用原生安装包。

Windows 开发与打包：

```powershell
npm.cmd run desktop:dev
npm.cmd run desktop:dist
```

如果 Electron 二进制或打包组件下载超时，可仅为当前终端指定镜像：

```powershell
$env:ELECTRON_MIRROR='https://npmmirror.com/mirrors/electron/'
$env:ELECTRON_BUILDER_BINARIES_MIRROR='https://npmmirror.com/mirrors/electron-builder-binaries/'
npm.cmd run desktop:dist
```

安装包当前未配置代码签名。Windows 开机启动需安装打包后的应用再启用。

Windows 提醒为右下角小卡片，弹出时不抢焦点、不激活主窗口，最多叠放 3 条。12 秒后自动收起；鼠标悬停暂停；可关闭、选择 5 分钟后提醒，或点击课程内容主动打开主窗口。提示音可单独关闭。

**关闭主窗口进入托盘后继续提醒；右键托盘选择「退出课序（停止提醒）」才彻底退出。** 无需开启 Windows 系统通知权限。提醒计划和去重状态由主进程写入本机文件，重启应用后恢复。休眠恢复仅补发最近 10 分钟且尚未上课的提醒，过时课程不刷屏；锁屏、关机或彻底退出期间无法显示卡片。请在「偏好设置 → 发送测试提醒」实测，约 5 秒后出现。

## 构建安卓 APK

需要 **JDK 21、Android SDK 36、Build Tools 36.0.0**。可以配置 `JAVA_HOME` 和 `ANDROID_HOME`，或在 Windows 下载项目内工具链（不会替换系统 JDK）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap-android.ps1
npm.cmd run android:build
```

也可使用 `npm.cmd run android:open` 在 Android Studio 中构建。SDK 下载及 Gradle 首次解析依赖需要网络。当前目录含中文，因此项目启用了 `android.overridePathCheck=true`；若其他工具拒绝中文路径，可将项目复制到英文目录后再构建。

支持 Android 7.0+，系统 WebView 应保持更新。APK 为调试签名，供个人安装测试；正式发布需配置你自己的签名密钥，不能将私钥提交仓库。

安卓需允许通知；Android 12+ 还需在应用设置中允许准时提醒。系统强制停止、厂商省电策略、免打扰可能阻止或延迟提醒。插件已声明开机恢复接收器。最多安排最近 450 条提醒，超过时界面明确提示定期打开应用补充。稍后提醒会打开应用并安排 5 分钟后的本地通知。

## 开启两端云同步

代码已接入 Supabase；未填写配置时明确使用本地模式。需要你自己的免费项目，本仓库不含服务密钥。

1. 创建 Supabase 项目，在 SQL Editor 执行 [数据库迁移](supabase/migrations/001_schedule.sql)。
2. 在 Authentication 中启用 Email / Password。开启邮件确认时，注册后先确认邮件，再回应用登录。
3. 将 `.env.example` 复制为 `.env.local`，填写项目 URL 和 **anon / publishable key**。不要使用 `service_role` 或数据库密码。
4. Windows 与安卓用同一套配置重新构建、安装，在设置中注册 / 登录同一账号。

首次登录时，空云账号接收本地课表；已有云课表时，新设备未编辑的内置截图数据让位于账号课表，登录前主动编辑的数据仍保留。编辑后自动同步，另以 60 秒间隔拉取远端修改；恢复联网立即尝试同步。离线修改保留至联网。同步失败显示原因，不伪装成成功。

每条记录用服务端版本号比较后写入；并发修改显示本地、云端两个版本，选择后继续同步。远端删除与本地子规则修改会保留冲突；采用云端删除时会一并删除关联规则与调整。删除采用墓碑，避免离线设备复活旧记录。

退出账号会保留离线课表。更换账号前使用「账号数据：备份并清空本地」，防止把上个账号的数据同步到新账号。清空本地不会删除云端记录。

## 表格与备份格式

Excel 为 `.xlsx`，CSV 使用 UTF-8。表头顺序：

```text
课程名称,星期,开始时间,结束时间,上课周次,教室,教师,备注
```

前五列必填；星期支持 `1`–`7` 或「星期一」至「星期日」；时间为 `HH:mm`；周次如 `3-13,16-18`、`1-18单周`、`双周`、`每周`。同名课程合并为多条排课规则，各行教师、教室允许不同。跨两个大节直接填完整起止时间。

导入先预览：非法行或冲突行修正后重新选择文件；重复规则跳过。默认追加导入。「替换当前学期」同时删除该学期旧规则和临时调整，先导出备份。表格不包含停课 / 补课记录；跨设备迁移全部内容请用 JSON 备份。恢复 JSON 保留当前账号归属及本机提醒设置，并作为修改同步。

本地数据保存在 IndexedDB；不清除应用数据即可离线使用。替换或恢复前还会将安全副本写入本机存储，可在「本机安全副本」中恢复。文件导出在 Windows 通过下载、安卓通过系统分享 / 文件保存窗口完成；请实际保存文件，才能在清除应用数据后找回。

## 运行日志每天自动提交到 GitHub

0.1.2 起，Windows 应用自己把**真实使用事件**写成本机 JSONL，并在每天固定时间（默认本机 23:50）通过 GitHub Git Data API 提交到仓库。安卓端不产生这类日志。

**记什么**：启动、退出、提醒实际弹出、测试提醒、提醒计划变更、开机启动开关、休眠恢复、手动同步、同步失败。每条带 UTC 时间、北京时间、事件名、说明、来源 `kexu-desktop` 与应用版本。**不记**：课表内容、账号邮箱、任何凭据。

**首次配置（只做一次）**：本机准备一个 GitHub token（只需能写目标仓库），用下面任一方式提供，应用只读不写：

- **方式 A（0.1.3 起推荐，安装包自带）**：「偏好设置 → 运行日志 · GitHub → GitHub 凭据文件」填 token 文件的**绝对路径**。界面只保存路径、不保存内容；保存后状态会变成「凭据已配置」。换电脑重装只需在这里再填一次。
- **方式 B**：设环境变量 `KEXU_GH_TOKEN`（只对从该终端启动的应用生效）。
- **方式 C**：命令行 `node scripts/log-sync-cli.cjs token "C:\某处\.gh_token"`（开发排查用，CLI 不打包进安装包）。

```powershell
# 方式 B / C 示例
$env:KEXU_GH_TOKEN='你的 token'
node scripts/log-sync-cli.cjs token "C:\某处\.gh_token"
```

**配置文件在 `%APPDATA%\classmate-reminder\log-sync.json`**，不是 `%APPDATA%\课序`：
安装版 Electron 的 `userData` 目录名取自 `package.json` 的 `name`（`classmate-reminder`），
只有早期开发版才叫「课序」。命令行按同一规则探测，两个目录都在时以安装版为准。
首次启动自动生成配置，可改 `enabled`、`time`（HH:mm）、`repo`（owner/name）、`branch`、
`directory`、`tokenFile`。**配置文件、日志、源码都不含 token**；没配凭据时日志只留本机，
界面明确显示「未配置凭据」，不会伪装成成功。

**在哪操作**：「偏好设置 → 运行日志 · GitHub」可开关、改时间、**配置/清除凭据路径**、看下一次提交时刻与今日事件数、点「立即同步」「打开日志目录」；托盘右键也有「立即同步运行日志」。命令行排查：

```powershell
node scripts/log-sync-cli.cjs status
node scripts/log-sync-cli.cjs sync
node scripts/log-sync-cli.cjs time 23:50
node scripts/log-sync-cli.cjs token "C:\某处\.gh_token"
```

11-15 实测：把 token 路径写进安装版配置后，命令行 `sync` 真实提交
`ff77158`（`tools/kexu/usage_logs/2026-11-15.jsonl`，当日 5 条真实事件）；
修这个之前，安装版因找不到凭据只会静默跳过自动提交。
另做了一次**定时器真实触发验证**：把当日时刻临时改成 22:35、只排 `scheduleNext()`、不手动调 `sync()`，
22:35:00 定时器自行唤醒产生 `7334429`（`真实事件 6 条，scheduled`），验完已改回 23:50。
该次宿主是 Node CLI 进程（与软件内同一个 `LogSync` 类、同一配置与提交链路），
**不是 Electron 窗口自己到点触发**；应用窗口要自己提交，需在 23:50 时保持软件运行
（打开软件或在设置里开「开机启动」）。关机/断网/没打开的那天不补写。

**实现边界（别被日志表面骗了）**：

- 每天**一个** `setTimeout` 睡到提交时刻，触发后再排下一天；不轮询、不扫课表、不联网探测。休眠恢复只重排定时器，不补写事件。
- 关机、彻底退出、断网、没打开应用的那天**就是没有日志**，不补写、不造心跳、不生成空提交。
- 启动时若发现已过今天的提交点且今天还没提交过，只把**本机已经真实存在**的日志补传一次，不新建记录。
- 提交基于远端最新 commit 建 tree，**只增改自己的目录**（默认 `tools/kexu/usage_logs/`），不删除仓库里任何其他文件；内容没变化时不重复提交；遇到并发冲突自动取最新 head 重试一次。
- 提交前会机械拦截疑似密钥串，命中即中止；日志写入时也会脱敏。凭据不进仓库，客户端日志与云端自动化运行日志分目录、互不冒充。
- 默认目标仓库 `Dream404N/ICEC-2026-0163-LZH`；换仓库改 `repo` 一项即可。

## 安全说明（11-15 全量源码审计）

**结论：没有远控、反向 shell、后门下载器、键盘/屏幕/剪贴板采集，也没有隐藏的开机自启。**
逐项依据：

| 关注点 | 代码里实际是什么 |
| --- | --- |
| 日志模块联网 | `electron/log-sync.cjs` 的 `realRequest()` 把 host **硬编码**成 `api.github.com:443`，TLS `servername` 也是 `api.github.com`。可配置项只有 `repo` / `directory` / `time` / `tokenFile` / `proxy`，**没有任何一项能把数据改发到别的主机**；`proxy` 只是 HTTP CONNECT 隧道，隧道终点仍固定为 `api.github.com:443` |
| 其它外发 | `src/data/sync.ts` 用 Supabase 官方 SDK 做「账号 + 课表云同步」，但 `cloudConfigured()` 要求同时有 `VITE_SUPABASE_URL` 与 `VITE_SUPABASE_ANON_KEY`，否则 `initSync()` 直接返回。本工程没有 `.env`（只有空模板 `.env.example`），`dist/` 里扫描不到任何 Supabase 地址或密钥，安装包界面显示「本地模式，云服务尚未配置」——**当前安装包不会连任何云数据库** |
| 本地子进程 | `electron/main.cjs` 只 `spawn` 同目录下的 `electron/reminders.ps1`，参数是固定的 `replace/append/status/register` + 本机数据文件。`-ExecutionPolicy Bypass` 只是允许运行这个本地脚本；脚本内容只有 Windows Toast 通知与 `HKCU\Software\Classes\AppUserModelId\...` 注册（让通知显示应用名/图标），无网络、无下载、不写 Run 自启键 |
| 开机自启 | `app.setLoginItemSettings` 由「偏好设置 → 开机启动」显式开关触发，默认关闭；不是隐藏服务 |
| 高危 API | 全源码扫描无 `eval` / `new Function` / 远程脚本加载 / `shell.openExternal` 执行外部程序 / `desktopCapturer` / `clipboard` / 全局键盘钩子；`setWindowOpenHandler` 对页面内跳转一律 deny，https 外链交系统浏览器打开 |
| 依赖 | `@supabase/supabase-js` 是 Codex 原版账号同步用的官方包；`@capacitor/synapse@1.0.4` 是 `@capacitor/core@8.6.2` 的依赖（见 `package-lock.json`），不是额外注入 |

**真正需要注意的权限，不是病毒而是信任模型**：日志功能需要一个能写目标仓库的 GitHub token，
该 token 以明文放在本机文件里（配置只存路径，不存内容）。任何以你身份运行的本机程序都能读它 ——
建议用**细粒度 token，只授权这一个仓库的 Contents 读写**，别用全权限经典 token。
界面、日志、源码、仓库里都不含 token；提交前还会机械拦截疑似密钥串。

**关于 0.1.3 安装包**：已核对 `app.asar` 内 `main.cjs` / `log-sync.cjs` / `preload.cjs` /
`reminders.ps1` 与源码逐字节一致、包内版本为 0.1.3、新界面文案已入包，
SHA-256 `cfb7d332683875d049361971cb0f2c40df0cfc999eeb074d6a5d2f429b582ce2`，
但**尚未实机安装运行**。打包时本机批量删除保护不允许清空旧 `win-unpacked/locales`，
因此先输出到全新的 `release-013/`，再复制到 `release/`；`package.json` 的 `output` 仍是 `release`。
若你以后重新打包又遇到同一拦截，把输出目录临时改成一个全新空目录即可，不必删旧文件。

## 验证与实现资料

```powershell
npm.cmd run check
npx.cmd playwright install chromium
npm.cmd run test:ui
npm.cmd run build
node scripts/smoke-desktop.mjs
```

最后一项仅 Windows，使用独立临时测试目录，实际触发右下角卡片，检查位置、不抢焦点和继续输入、稍后提醒、托盘后台触发、悬停暂停、自动收起及取消。会短暂显示测试窗口，不修改日常课表或个人提醒计划。设置 `KEXU_EXECUTABLE` 可对打包后的 EXE 运行同样的测试。

- [架构与接口](docs/architecture.md)
- [实现与验收记录](docs/verification.md)
- [全部新增文件清单](docs/changed-paths.md)

Windows 弹窗展示与后台触发已实测，物理提示音、多显示器 / DPI、系统休眠和安卓 / 真实云项目两端联测仍按验收记录检查。构建或单元测试通过不代表这些场景已经验证。
