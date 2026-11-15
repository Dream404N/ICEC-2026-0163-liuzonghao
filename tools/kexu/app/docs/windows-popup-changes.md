# Windows 0.1.1 提醒修正路径

用户要求右下角、类似聊天软件、不干扰正常输入的弹窗。以下为本次相对 0.1.0 的修改路径（其他源码保持原状）：

- `electron/main.cjs`
- `electron/reminder-scheduler.cjs`（新增）
- `electron/popup-manager.cjs`（新增）
- `electron/popup-preload.cjs`（新增）
- `electron/popup.html`（新增）
- `electron/popup.css`（新增）
- `electron/popup.js`（新增）
- `src/platform/notifications.ts`
- `src/ui/Settings.tsx`
- `scripts/smoke-desktop.mjs`
- `tests/desktop-scheduler.test.cjs`（新增）
- `package.json`
- `package-lock.json`
- `README.md`
- `docs/architecture.md`
- `docs/verification.md`
- `docs/artifacts.json`
- `docs/changed-paths.md`
- `docs/windows-popup-changes.md`（本文件，新增）

生成文件：`dist/`、`release/课序 Setup 0.1.1.exe`、`release/win-unpacked/`、`test-results/`。旧版 0.1.0 安装包和安卓 APK 保留。本次不部署云服务，不改系统通知设置，不修改本机登录启动项，也不创建 Git 提交。
