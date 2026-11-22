# 源码快照说明（课序 0.1.4）

本目录是「课序」Windows 客户端**完整、可构建的桌面工程源码**，2026-11-16 00:20 从本机
`F:/下载/课表提醒/课表提醒` 原样复制：**65 个文件 / 627 KB**。
本目录的 `README.md` 是原工程自带的使用说明，未改动。

原工程由使用者用 Codex 辅助写成，本人对其界面和功能满意；11-15 由本次选拔任务追加了
「运行日志每天自动 commit 到 GitHub」链路（`electron/log-sync.cjs` 等）并升级到 0.1.4（0.1.4 修复 `log-sync.cjs` 启动时 ISO 字符串日期解析的 `RangeError`）。

- 这是**静态源码快照**，不是那个工程的 git 仓库本体；本机 F 盘工程仍是活的开发副本。
- 与上层 [`../source/`](../source/) 的关系：`source/` 只放本次新增/改动模块的逐字节快照，
  便于单独审阅与审计；本目录是**整个工程**。两者重叠的文件内容一致。

## 2026-11-21 增量（0.1.5-dev，未发版）

为修 [`../../02-20Days-Challenge/iterations/011-提交文案的条数口径.md`](../../02-20Days-Challenge/iterations/011-提交文案的条数口径.md)
记录的提交文案口径错误，改了本目录两个文件（本机 F 盘工程同步改动，两处逐字节一致）：

| 文件 | 改动 |
| --- | --- |
| `electron/log-sync.cjs` | 提交信息由「真实事件 N 条」（实为全部分片累计行数）改为「当日 N 条 / 累计 M 条」 |
| `tests/log-sync.test.cjs` | 旧断言同步更新，并新增 1 项回归：两分片 → 断言「当日 3 条 / 累计 5 条」 |

验证：`node --test tests/log-sync.test.cjs` **9/9 通过**。

边界：`../source/log-sync.cjs` 仍是 0.1.4 的逐字节快照，**未覆盖**；
运行中的 0.1.4 安装包 asar 内仍是旧文案，需重新打包发版才生效。
- 设计与实证见 [`../README.md`](../README.md)，全量源码安全审计见
  [`../SECURITY-AUDIT.md`](../SECURITY-AUDIT.md)。

## 复现构建（Windows）

```powershell
npm ci                    # 依赖由 package-lock.json 锁定
npm run check             # tsc + vitest + node --test
npm run build             # tsc -b && vite build → dist/
npm run desktop:dist      # electron-builder --win nsis → release/课序 Setup 0.1.4.exe
```

CI 见 `.github/workflows/check.yml`（Node 24，含 UI 测试、Windows 安装包与安卓壳构建）。
`npm run desktop:dev` 需要本机有 Electron；`scripts/ensure-electron.mjs` 会检查并提示。

## 目录结构

| 路径 | 作用 |
| --- | --- |
| `electron/` | Electron 主进程：`main.cjs`（窗口/托盘/IPC）、`log-sync.cjs`（日志定时提交）、`reminder-scheduler.cjs`、`popup-*`（右下角提醒弹窗）、`reminders.ps1`（Windows Toast）、`preload.cjs` |
| `src/` | React + TypeScript 界面与领域逻辑：`ui/`（课表、周视图、设置、导入导出）、`domain/`（校历周次、课程计算）、`data/`（本地存储、Supabase 可选云同步）、`platform/` |
| `scripts/` | 构建与排查工具，含 `log-sync-cli.cjs` |
| `tests/` | 单测与 Playwright 端到端用例 |
| `docs/` | 工程自带设计/验证文档 |
| `public/`、`build/` | 图标资源（`build/icon.ico` 是 electron-builder 的安装包图标） |
| `supabase/migrations/` | 可选云同步的数据库建表 SQL |
| `package.json` / `package-lock.json` | 依赖与构建脚本；`build` 段含 NSIS 配置 |
| `env.example.txt` | **原工程里的 `.env.example`**，内容只有两行空的 `VITE_SUPABASE_URL=` / `VITE_SUPABASE_ANON_KEY=` |

## 如实交代：改了什么、没放什么

- **改名一处**：`.env.example` → `env.example.txt`。本仓库的 `.gitignore` 和同步脚本的
  `assert_no_secrets()` 都会拦截 `.env*` 文件名（防止真凭据误入库），内容**逐字节未改**。
  本机工程里没有 `.env` / `.env.local` / `.env.production`，当前安装包不连任何云数据库。
- **未纳入**（都是可再生成或体积过大的产物，不是源码）：
  `node_modules/`（729 MB）、`release/` 与 `release-013/`（共 1.2 GB 安装包与便携版）、
  `dist/`（构建产物）、`test-results/`、`.git/`、`tsconfig.tsbuildinfo`、
  `android/`（Capacitor 生成的壳 + 本机 Android SDK 构建中间产物，25 MB；
  本仓库 `tools/dingding/android/` 另有完整安卓源码）、根目录那份重复的 `log-sync.cjs` 副本。
- **安装包 exe 不进 git 树，但已作为 GitHub 发行版发布**：`课序 Setup 0.1.4.exe` 为
  132,216,066 字节，超过仓库单文件 100 MB 限制；Release 附件上限 2 GB，故发布在
  [`kexu-0.1.4`](https://github.com/Dream404N/ICEC-2026-0163-liuzonghao/releases/tag/kexu-0.1.4)
  （附件名 `Kexu-Setup-0.1.4.exe`，中文放 label）。0.1.3 的发行版见
  [`kexu-0.1.3`](https://github.com/Dream404N/ICEC-2026-0163-liuzonghao/releases/tag/kexu-0.1.3)。SHA-256 与本机路径记在
  [`../README.md`](../README.md)，可逐字节核对。仓库仍 Private，下载需账户权限。
- `docs/artifacts.json` 是工程自带的**历史**产物清单，停在 0.1.1；当前版本以上层 README 为准。
- **不含任何 token / SendKey / 云数据库凭据**。日志提交所需凭据只在运行时从本机环境变量
  或本机文件读取，运行配置 `log-sync.json` 是应用自动生成的，不在源码里。
- `package-lock.json` 里有一处 npm `integrity` 的 sha512 哈希碰巧含连续字符 `SCT2I…`，
  是 base64 随机字节，不是 Server酱 SendKey；仓库同步脚本拦截的是 `sk-` 形态密钥串，未触发。
