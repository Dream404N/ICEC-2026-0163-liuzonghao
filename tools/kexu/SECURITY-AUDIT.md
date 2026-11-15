# 课序（Codex 版）源码安全审计 · 有没有远控/病毒

> 审计时间：2026-11-15 22:4x（北京）
> 对象：使用者本机 `F:/下载/课表提醒/课表提醒/`（Codex 写的「课序」Electron 工程，0.1.3）
> 范围：`electron/`、`src/`、`scripts/`、`tests/`、`index.html`、`vite.config.ts`、
> `capacitor.config.ts`、`package.json`、`.env.example`、`package-lock.json`、
> 以及已构建的 `dist/` 与 `app.asar`。
> 方法：**源码层静态审计**（逐文件读关键实现 + 全量关键词扫描 + 打包产物核对）。
> 未做：动态流量抓包、行为沙箱、Electron 运行时二进制与 `node_modules` 逐个二进制的逆向。
> 所以结论只覆盖「这份源码里有没有后门」，不等于对整机或第三方二进制做杀毒鉴定。

## 结论

**没有发现远控、反向 shell、后门下载器、键盘记录、屏幕/剪贴板采集、隐藏自启或数据外泄通道。**

唯一会出网的两处都可以在源码里指到具体行，且都是用户明确需要的功能：

1. **运行日志自动提交**（本次新增）：只连 `api.github.com:443`，只上传本机真实事件的 JSONL。
2. **账号云同步**（Codex 原版就有）：Supabase 官方 SDK，把课表同步到**使用者自己**的 Supabase 项目；
   当前这台机器**根本没启用**，见下文。

## 逐项证据

| 关注点 | 实际代码 | 判定 |
| --- | --- | --- |
| 日志模块的目标主机 | `electron/log-sync.cjs` 的 `realRequest()`：`https.request({ host: 'api.github.com', port: 443, path: apiPath })`；走代理时 `tls.connect({ socket, servername: 'api.github.com' })`，CONNECT 目标写死 `api.github.com:443` | **主机硬编码**。`validateConfig()` 允许改的只有 `enabled / time / repo / branch / directory / tokenFile / proxy`，**没有任何配置项能把请求改发到别的域名或 IP**；`repo` 还有 `owner/name` 正则约束 |
| 日志模块传什么 | `sync()` 只把 `usage_logs/YYYY-MM-DD.jsonl` 作为 blob 建 tree、commit、update-ref；写入时 `scrub()` 脱敏，提交前 `assert_no_secrets()` 拦截疑似密钥串 | 不含课表内容、账号、密码、token；只记事件名/时间/说明 |
| Supabase 云同步 | `src/data/sync.ts`：`cloudConfigured()` 要求 `VITE_SUPABASE_URL` 与 `VITE_SUPABASE_ANON_KEY` **同时非空**，否则 `initSync()` 直接 `return`，连 60 秒的同步定时器都不会注册。`cloud()` 会抛「请先按 README 配置 Supabase」 | 工程内 `.env` / `.env.local` / `.env.production` **均不存在**，只有空模板 `.env.example`。生产 `dist/assets/*.js` 里 `createClient`、`VITE_SUPABASE`、`schedule_records` **全部零命中**（构建时环境变量为空，Vite 把云同步代码 tree-shake 掉了），前端运行时没有 Supabase 客户端；设置页显示「本地模式，已可使用 · 云服务尚未配置」。**当前安装包不连任何云数据库** |
| CSP（入口 `index.html`） | `default-src 'self'; script-src 'self'; connect-src 'self' https://*.supabase.co wss://*.supabase.co http://127.0.0.1:* ws://127.0.0.1:*; object-src 'none'` | `connect-src` 里的 `*.supabase.co` 是**允许列表**（为将来云同步预留），白名单本身不会发起连接；`script-src 'self'` 禁止加载远程脚本，是安全加分项。日志模块跑在 Electron **主进程（Node）**，不经渲染进程、不受这条 CSP 约束，其目标由代码硬编码为 `api.github.com` |
| asar 里出现 `supabase.co` | 全包搜到 294 处，抽查上下文均为 `node_modules` 内 Supabase SDK 自带的 README / JSDoc 示例文本（如 `createClient('https://xyzcompany.supabase.co', 'your-secret-key')`） | 是**文档字符串**，不是配置、不是密钥、不是运行时请求目标；`app.asar` 里 `VITE_SUPABASE` 与 JWT 形态串 `eyJhbGci` 均零命中 |
| 云同步会传什么（若将来启用） | `syncNow()` 读写 `schedule_records` 表，按 `user_id` 过滤；`tests/sync-database.test.ts` 验证 anon 角色写入被 RLS 拒绝 | 传的是课表条目，到使用者自己创建的项目；需本人登录。不是外发到第三方 |
| PowerShell 子进程 | `electron/main.cjs:95` 只 `spawn('powershell.exe', ['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File', script, ...])`，`script` 固定指向打包内的 `electron/reminders.ps1`，`windowsHide: true` | `reminders.ps1` 全文只有 Windows Toast 通知的排程/查询，以及 `register` 动作写 `HKCU:\Software\Classes\AppUserModelId\<appId>`、`CLSID`（让通知显示应用名和图标）。**无网络、无下载、不写 `Run` 自启键**。`-ExecutionPolicy Bypass` 只是允许执行这个本地脚本 |
| 开机自启 | `electron/main.cjs:122` `app.setLoginItemSettings({ openAtLogin: !!enabled, path: process.execPath })`，由设置面板「开机启动」开关显式调用 | 默认关闭，**不是隐藏服务或计划任务**；11-15 22:31 实测 `HKCU\...\Run` 下无课序项 |
| 窗口与外部链接 | `main.cjs:59` 开发时 `loadURL(VITE_DEV_SERVER_URL)`，正式包 `loadFile(dist/index.html)`；`setWindowOpenHandler` 对页面内跳转一律 `deny`，`https://` 外链交给系统浏览器 | 正式包只加载本地文件，不加载远程页面 |
| 高危 API | **应用自身源码**（`electron/`、`src/`、`scripts/`）扫描：`eval`、`new Function`、`require('vm')`、`child_process.exec` 远程命令、`desktopCapturer`、`clipboard`、`globalShortcut`、`screen` 截图、WebSocket 调用、远程脚本 `src`、下载后执行 —— **零命中**（`screen` 仅用于弹窗定位的 `getPrimaryDisplay().workArea`） | 无键盘钩子、无截屏、无剪贴板读取。边界：`node_modules` 里 Supabase SDK 自带 realtime 模块（`socket.js` / `longpoll.js` 等），但生产 bundle 未包含 SDK 运行代码、客户端未创建，未激活 |
| 依赖 | `package.json` 的 scripts 全是标准构建/测试；`@supabase/supabase-js` 是 Codex 原版账号同步的官方包；`app.asar` 里出现的 `@capacitor/synapse@1.0.4` 是 `@capacitor/core@8.6.2` 的依赖（`package-lock.json` 可查，来自 npmmirror） | 无 `postinstall` 暗钩、无可疑域名包 |
| 打包内容 | `build.files` 只含 `dist/**/*`、`electron/**/*`、`build/icon.png`、`package.json`；CLI 与测试不进 asar | 安装包不含开发脚本 |

### 扫描复现

```powershell
# 工程根目录下
Get-ChildItem .env* -Force                        # 应只有 .env.example
Select-String -Path electron\*,src\**\* -Pattern 'eval\(|new Function|desktopCapturer|clipboard|https?://' -Recurse
Select-String -Path dist\assets\*.js -Pattern 'createClient|VITE_SUPABASE|schedule_records|eyJ' -Recurse  # 应零命中
Get-Content dist\index.html                       # 可见 CSP 的 *.supabase.co 是允许列表，不是请求
```

## 本次重打包产物（0.1.3）

本机路径 `release/课序 Setup 0.1.3.exe`（同等副本在 `release-013/`），
132,215,755 字节，2026-11-15 22:48 生成，
SHA-256 `cfb7d332683875d049361971cb0f2c40df0cfc999eeb074d6a5d2f429b582ce2`。

包内核对：`app.asar` 内 `electron/main.cjs`、`electron/log-sync.cjs`、
`electron/preload.cjs`、`electron/reminders.ps1` 与本机源码**逐字节一致**；
包内 `package.json` 为 `0.1.3`；asar 原始字节中可搜到新增的
「GitHub 凭据文件」「凭据路径已保存」「KEXU_GH_TOKEN」界面文案。
0.1.3 只多了一个「凭据文件路径」设置项，**没有改动任何网络目标或运行行为**。

重打包时遇到本机批量删除保护（打包器想清空旧 `win-unpacked/locales` 的 55 个文件），
处理方式是把输出目录改到全新的 `release-013/`，**不绕过删除保护、不删旧文件**；
打完再把安装包复制到 `release/` 与 0.1.0～0.1.2 旧包并存。

## 真正需要注意的，不是病毒，是权限与信任模型

- 日志功能需要一枚**能写目标仓库**的 GitHub token，以明文存在本机文件里
  （`log-sync.json` 只存**路径**，不存内容）。任何以你身份运行的本机程序都能读它。
  建议用**细粒度 token，只授权 `Dream404N/ICEC-2026-0163-LZH` 一个仓库的 Contents 读写**，
  别用全权限经典 token，也别把该文件放进任何同步盘。
- 若显式配置了 `proxy` / `KEXU_HTTPS_PROXY`，代理能看到「你在访问 api.github.com」这一元数据，
  但隧道内是 TLS 且 `servername` 固定，代理拿不到明文内容，也改不了终点。
- `reminders.ps1` 会写 `HKCU\Software\Classes` 下的通知注册项，这是 Windows Toast 的标准做法，
  卸载软件不会自动清理这些显示名/图标注册项（不影响运行，属常见残留）。
- 开机自启一旦由使用者打开，就是真实自启；本审计只确认**默认是关的、入口是显式的**。

## 与本模块的关系

这份审计针对的是使用者本机 Codex 版工程整体；**11-16 起该工程完整桌面源码已同步到
ICEC 仓库 `tools/kexu/app/`**（65 个文件，见 `SOURCE-SNAPSHOT.md`），`tools/kexu/source/`
仍保留与日志自动提交直接相关的模块快照，便于单独审阅。审计结论同时写进了本机工程 `README.md`。
本次审计**不改变任何运行行为**，也没有新增遥测或上报。
