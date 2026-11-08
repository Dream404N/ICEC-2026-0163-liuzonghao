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
| 第一阶段 · 实地测评（10 选 2 · 20 分） | **课题 02：个人手机多工况发热与掉电实测** | 进行中 |
| 第一阶段 · 第二项 | 待定 | — |
| 第二阶段 · 开放式项目（8 选 1 · 60 分） | 待定 | — |

课题 02 不使用现成的电量监控 App，而是自研采集工具（`tools/PowerProbe/`），
原因是现成工具无法按工况打标签、无法导出原始时序、不记录测试期间的前台应用。
测试条件与作废规则见 `01-Field-Discovery/T02-Phone-Power-Thermal/protocol.md`。

## 目录

```
01-Field-Discovery/          第一阶段 · 实地测评
  T02-Phone-Power-Thermal/     课题 02：原始数据、测试协议、现场照片、分析
    raw_data/                    采集原始 CSV
    photos/                      现场同框照
    reports/                     设备端自动生成的报告
    analysis/                    Python 分析与图表
02-20Days-Challenge/         第二阶段 · 工坊项目
  process_logs/                每日运行日志
  iterations/                  迭代记录
  feedback/                    用户反馈
  src/                         源码
03-AI-Collaboration/         AI 协作与排障记录
tools/PowerProbe/            课题 02 采集 App（Kotlin / Android）
```

## 工程

`tools/PowerProbe/` 的 APK 由 GitHub Actions 云端构建（本地无 Android SDK）：

- 工作流 `.github/workflows/build-apk.yml`，JDK 17 / Gradle 8.7 / AGP 8.5.2 / Kotlin 1.9.24
- 产物：Actions Artifacts `PowerProbe-debug-apk`，以及 Release `apk-latest` 下的 `app-debug.apk`
- 依赖仅 AppCompat 与 Material Components（均为 Apache-2.0），界面按 Material3 设计语言自实现

## 约定

- 过程数据每日同步，commit 写明当天做了什么。
- 失败、报错、改选题的原因如实记录，不补写、不摆拍。
- 原始数据与照片均为本人采集；使用 AI 辅助会注明。
