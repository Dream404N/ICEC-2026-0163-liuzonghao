# 实现与验收记录

更新日期：2026-11-15。状态用 `[V]` 表示本机工具直接验证，`[T]` 表示尚待设备或服务验证。以下为当前执行者自测记录，不是多人评审或已运行的远端 CI。

## 已实现的主线

- M-1：共享课表逻辑、图片初始数据、学期 / 作息、周课表和今日 / 下一节课页面。
- M-2：Windows 0.1.1 改为右下角独立轻提醒、主进程计时、托盘、开机启动入口；安卓本地提醒、精确提醒权限检查、通知渠道与开机恢复声明。
- M-3：课程规则、调课 / 停课 / 换教室 / 补课、调整恢复、XLSX / CSV 预览与导出、完整备份与本机安全副本。
- M-4：Supabase 登录 / 注册、版本比较写入、离线队列、冲突展示与选择、账号隔离保护。

## 验证证据

| 证据 | 命令 / 文件 | 结果或边界 |
|---|---|---|
| E-1 | `npm run check`；`tests/domain.test.ts`、`tests/sync-database.test.ts`、`tests/desktop-scheduler.test.cjs` | `[V]` 28 项核心 / PostgreSQL 测试与 5 项桌面计时、持久化、取消、稍后提醒、去重测试通过。 |
| E-2 | `npm run test:ui`；`tests/e2e/app.spec.ts` | `[V]` 4 项 Playwright 场景通过：桌面 / 手机布局、课程管理、调课、导入、备份与恢复。截图位于 `test-results/`。 |
| E-3 | `npm run build` | `[V]` TypeScript 严格检查与 Vite 生产构建通过。 |
| E-4 | `node scripts/smoke-desktop.mjs`；设置 `KEXU_EXECUTABLE` 指向最终 `release/win-unpacked/课序.exe` 重测 | `[V]` 0.1.1 开发运行器与最终打包程序均实际显示独立卡片，检查工作区右下角位置、可见 / 置顶 / 不可聚焦、主窗口继续输入、5 分钟稍后提醒写盘、主窗口隐藏后投递、悬停暂停和自动消失、取消。使用隔离临时目录。最终打包窗口截图 `test-results/windows-popup.png`。两次均输出完整 PASS。 |
| E-5 | `npx electron-builder --win nsis` | `[V]` 0.1.1 Windows x64 NSIS 构建成功，产物 `release/课序 Setup 0.1.1.exe`，SHA256 已记录。未配置签名证书，安装过程未实测。 |
| E-6 | 最终 `cap sync android` 后 `node scripts/build-android.mjs` | `[V]` JDK 21 / SDK 36 增量构建 `BUILD SUCCESSFUL`，APK 位于 `android/app/build/outputs/apk/debug/app-debug.apk`。已核对 min SDK 24、target SDK 36、通知 / 精确闹钟 / 开机权限、开机接收器及内嵌网页与 dist 一致；调试签名，未连接真机。 |
| E-7 | `npm audit --omit=dev --registry=https://registry.npmjs.org` | `[V]` 运行依赖审计为 0 个已知漏洞；ExcelJS 的 uuid 传递依赖已升级并补测真实 XLSX 读写。 |
| E-8 | `.tools/android-sdk/platform-tools/adb.exe devices` | 本机无已连接安卓设备，因此不声称已在安卓真机运行。 |

安装包大小与 SHA256 见 [产物清单](artifacts.json)，全部新增源码路径见 [变更清单](changed-paths.md)。安卓原生模板 versionName 为 `1.0`、versionCode 为 `1`，本次未重建 APK；Windows / npm 产品版本为 `0.1.1`。E-6 的资源一致性为此前 0.1.0 APK 构建时核对结果。

## 已纠正的问题

- BF-1：数据库删除参数在 JSONB `null` 与 SQL NULL 间存在差异；服务端统一归一化，并通过版本写入 / 删除 / 墓碑测试。
- BF-2：开发服务器监听下载中的工具链文件会遇到 EBUSY；排除 `.tools`、安卓构建和发布输出目录。
- BF-3：Windows PowerShell 5 对 UTF-8 无 BOM 的脚本解析导致 XML 构造未执行；原生 helper 改为 ASCII 源码，通过 UTF-8 JSON 传中文数据，再验证实际系统安排与取消。
- BF-4：Windows 首次通知权限查询可能返回 0x80070490；仅此错误记为“权限未知”，仍验证计划接口可用，界面提示测试提醒。其他系统错误不吞掉。空通知列表显式数组化，返回 0 而非 null。
- BF-5：云端删课与本地子规则修改不能直接隐藏本地改动；提升为父记录冲突，由用户选择后再级联删除。
- BF-6：导入查重原先可能跨学期误判；限定当前学期，并加入回归测试。
- BF-7：替换 / 恢复不能仅依赖文件下载是否保存；先写入本机安全副本，再导出文件和实施变更。
- BF-8：同时运行原生构建时 XLSX 集成测试偶发超过默认 5 秒；该真实文件读写测试单独采用 30 秒超时，保留全部断言。
- BF-9：新设备连接已有账号时，未编辑的内置课表应采用云数据，而不是制造初始版本冲突；空云账号仍接收初始课表，登录前的主动编辑及关联排课保留，已加入回归测试。
- BF-10：安卓 7 不支持通知渠道 API；渠道统一由 MainActivity 按系统版本创建，JS 不再无条件调用渠道接口。旧版实际投递仍待设备测试。

### BF-11：Windows 已排入提醒但未弹出

- 问题：用户反馈 0.1.0 Windows 根本不通知，希望使用类似 Telegram 的右下角、不打断操作的卡片。
- 根因边界：此前测试仅验证系统计划接口创建 / 回读 / 取消，未验证可见通知，无法据此认定展示可靠。具体系统 Toast 未展示原因尚未确定。0.1.1 改为应用独立窗口，不再依赖其投递展示。
- 修改：`electron/main.cjs`；新增 `electron/reminder-scheduler.cjs`、`electron/popup-manager.cjs`、`electron/popup-preload.cjs`、`electron/popup.html`、`electron/popup.css`、`electron/popup.js`；`src/platform/notifications.ts`、`src/ui/Settings.tsx`；`scripts/smoke-desktop.mjs`；新增 `tests/desktop-scheduler.test.cjs`；`package.json` / lock 与说明文档。
- 验证：E-1、E-4，卡片窗口截图已目视检查；未把测试接口调用成功代替弹窗出现。
- 风险：独立卡片需托盘运行，不能在锁屏安全桌面显示；物理声音、多屏 / DPI、睡眠恢复尚待实机场景检查。
- 审查 / 快照：执行者自审，未创建提交或多人签收。可用保留的 0.1.0 安装包回退，但该包仍存在本条用户反馈问题。升级与回退前可先导出课表 JSON。

## 待实际设备验收

- `[T]` Windows 物理提示音、多屏 / DPI、真实系统睡眠恢复；主进程计划重载已单测，不能替代系统重启测试。独立卡片设计上不在锁屏显示，彻底退出后不提醒。
- `[T]` Windows 安装流程与用户登录后的开机启动；已有安装包，未更改本机登录启动项。
- `[T]` 安卓安装、前台 / 后台 / 锁屏提醒、通知拒绝与重新授权、精确闹钟权限撤销、重启恢复、省电策略、文件分享。
- `[T]` 真实 Supabase 邮件注册、登录与 Windows / 安卓互改。没有项目 URL / public key，未创建账号或部署远端数据库。
- `[T]` GitHub Actions 工作流已写入，尚未推送或运行远端 CI。

## 自审边界

源代码具备两端适配和云同步接口；本地功能无需云服务。图片初始数据全部标记待校对，第一周日期为空，不凭标题推算日期。未验证的设备 / 服务场景按上表保留，不以浏览器截图、代码存在或构建成功代替实测。

全部源码新增，初始仓库没有文件或提交，没有覆盖既有用户代码。未创建 Git 提交。构建缓存、依赖和本项目下载的工具链保留，未执行清理或删除用户文件。

0.1.0 原生测试曾为本应用注册当前用户的开始菜单 `课序.lnk`、`HKCU\Software\Classes\AppUserModelId\cn.kexu.schedule` 及对应通知 CLSID。0.1.1 改为独立卡片，不再注册这些标识；仅在旧用户配置存在时清除本应用遗留 Toast。没有改变系统通知服务、系统 Java 配置、其他应用的通知或登录启动项。工具下载位于 `.tools/`，Gradle / npm 使用各自正常缓存目录。

本次 Windows 修正的逐文件列表见 [Windows 0.1.1 修改路径](windows-popup-changes.md)。
