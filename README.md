# ICEC-2026-0163-LZH

2026–2027 智能·创造者创新实验班（ICEC）选拔考核 · 过程仓库

| 项目 | 信息 |
| --- | --- |
| 姓名拼音 | LZH |
| 学号后四位 | 0163 |
| 平台 | GitHub |
| 可见性 | Private |
| 建仓日期 | 2026-11-08 |
| 封仓 | 2026-11-24（官网标注「初定」） |

## 选题

| 阶段 | 选题 | 状态 |
| --- | --- | --- |
| 第一阶段 · 实地测评（10 选 2 · 20 分） | **课题 02：个人手机多工况发热与掉电实测** | ✅ **已按现状如实定稿**。结论稿 `T02-Phone-Power-Thermal/analysis/summary.md`；相机录像工况仅 2 个采样点，按端点实测标注，不补采、不插值，口径见 `DATA_QUALITY.md` |
| 第一阶段 · 第二项 | **课题 09：多模态大模型校园复杂视觉盲区实测** | ✅ 已完成实测与报告 |
| 第二阶段 · 开放式项目（8 选 1 · 60 分） | **预备铃 / PreBell：课表微信提醒** | 3.0 版（11-14）：真实课表数据 + 课前 20 分钟微信提醒 + 全学期课表网页与手机日历；定时直接用 GitHub Actions 的 4 条 cron，用户零配置。用法见 `02-20Days-Challenge/README.md` |
| 第三阶段 · AI 协作 | — | 目录已建，内容未开始 |

**改选题原因（如实记录）**：第二阶段原做「校园节点雷达」（抓公开通知生成日历），
实测发现学校公告标题与正文几乎不写明确截止日，生成的日历事件长期为 0，产品对使用者没有价值。
11-13 改为 PreBell：把课表提醒**主动推送到微信**，而非等人打开日历。
旧方案的日志、迭代记录与源码原样保留、不回填；哪些旧口径作废见
`02-20Days-Challenge/iterations/002-改选题说明.md`。

**11-15 追加 · 叮叮课表（多终端本地版）**：使用者反馈微信链路「看不懂、现在根本用不了」，
于是补了一个能直接双击 / 直接安装的版本，名字就叫「叮叮课表」。
上午版（迭代 007）是单文件网页 + `.ics` + APK，提醒全交给系统日历、**不常驻不自启**；
下午（008）改成「开机自启到点弹窗」「日志每天自动 commit」「即时测试通知」；
傍晚（009）使用者指出「每 15 秒检测课表是什么鬼，病毒吗」，要求编译多功能 EXE。
**007 的「零常驻、不产生日志」和 008 的「每 15 秒查表」口径都已作废**，
以 `tools/dingding/README.md` 为准；变更与勘误见 `iterations/009-单文件EXE与零轮询调度.md`。

现行版：Windows 主程序是单文件 `dist/叮叮课表.exe`（PyInstaller 打包，带图形设置面板：
提前分钟数、开关、静音时段、开机自启、日志时间、自定义课表都能自己调）。
调度改成**事件驱动** —— 启动时读一次课表、单次定时器睡到下一个提醒点，
只保留每 30 分钟一次纯内存校准，**不再每 15 秒扫表**；界面实时显示轮询次数为 0。
安卓是系统日历 + `AlarmManager` 系统闹钟（不需要本 App 后台进程），
客户端真实使用日志每天 23:50 由软件自动推 GitHub，与云端运行日志分目录存放、互不冒充。
APK 仍无 INTERNET 权限、没有发布公网；EXE 是单文件 PyInstaller 程序、不是 MSI 安装包，
开机自启仍由 `安装.cmd` 双击写入，如实标注。
PreBell 的微信链路与 4 条 cron 原样保留，两套并存：微信是增强，本地是兜底。

课题 02 不使用现成的电量监控 App，而是自研采集工具（`tools/PowerProbe/`），
原因是现成工具无法按工况打标签、无法导出原始时序、不记录测试期间的前台应用。
测试条件与作废规则见 `01-Field-Discovery/T02-Phone-Power-Thermal/protocol.md`。

课题 09 把「拍 15 张图、用 2 个模型比一比」做成可复现流水线：18 张实地照片、4 款低价视觉模型、
5 类探针、人工真值表、自动判分与 Markdown/HTML 报告。入口见
`01-Field-Discovery/T09-Multimodal-Visual-Blindspot/README.md`，成品报告在同级 `reports/`。
题目要求 2 款模型，这里做 4 款是为了同时对照参数规模、推理模式、dense/MoE 与厂商；
`guard` 探针还实测了「加拒答提示到底有没有用」，包括个别模型不降反升的反例。

## 目录

```
01-Field-Discovery/          第一阶段 · 实地测评
  T02-Phone-Power-Thermal/     课题 02：原始数据、测试协议、现场照片、分析
    raw_data/                    采集原始 CSV
    photos/                      现场同框照
    reports/                     设备端自动生成的报告
    analysis/                    Python 分析与图表
  T09-Multimodal-Visual-Blindspot/  课题 09：视觉盲区实测
    data/                        人工真值、原图 SHA-256 清单、逐次调用结果、评分表
    photos/                      18 张 2048px 高清副本
    reports/                     自动生成的 md/html 报告、素材联系表
    tools/                       一键测试工具、报告生成器、图像处理（JDK）
02-20Days-Challenge/         第二阶段 · 工坊项目
  process_logs/                每日运行日志
  iterations/                  迭代记录
  feedback/                    用户反馈
  src/                         源码
03-AI-Collaboration/         AI 协作与排障记录（3 张真实排障截图 + 索引，见目录内 README）
tools/PowerProbe/            课题 02 采集 App（Kotlin / Android）
tools/dingding/              叮叮课表：Windows 单文件 EXE + 安卓 APK（均本机构建）
```

## 工程

`tools/PowerProbe/` 的 APK 由 GitHub Actions 云端构建；本机另有 Android SDK
（`I:\android-sdk-windows`），用于 `tools/dingding/` 的 APK 本地构建：

- 工作流 `.github/workflows/build-apk.yml`，JDK 17 / Gradle 8.7 / AGP 8.5.2 / Kotlin 1.9.24
- 产物：Actions Artifacts `PowerProbe-debug-apk`，以及 Release `apk-latest` 下的 `app-debug.apk`
- 依赖仅 AppCompat 与 Material Components（均为 Apache-2.0），界面按 Material3 设计语言自实现

课题 09 的工具链刻意保持零第三方依赖：Python 标准库做 API 调用与判分，JDK 自带 `ImageIO`
做图像缩放与联系表，`python tools/vlm_bench.py all` 一条命令跑完「统一输入 → 4 模型 × 5 探针
实测 → 评分表 → Markdown/HTML 报告」。全量 360 次调用按官方人民币单价估算约 ¥0.81。

## 约定

- 过程数据每日同步，commit 写明当天做了什么。
- 失败、报错、改选题的原因如实记录，不补写、不摆拍。
- 原始数据与照片均为本人采集；使用 AI 辅助会注明。
- **任何 API key / token 不入库**：同步用的 token 只放工作区外的 `.workbuddy/`；
  PreBell 的微信推送 SendKey 只放 GitHub Actions Secrets（变量名 `PREBELL_SENDKEY`），
  代码只读环境变量。`.gitignore` 与同步脚本双重拦截，提交前还会做全仓密钥串扫描，
  详见各课题的 `SECURITY.md`。
