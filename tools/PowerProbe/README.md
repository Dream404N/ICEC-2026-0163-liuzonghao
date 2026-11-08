# PowerProbe

课题 02（手机多工况发热与掉电实测）的专用采集工具。用于在一台已 root 的 Redmi K60 Ultra 上，
按 4 个工况各自采集 30 分钟、每 5 分钟一个点的电量 / 电流 / 温度 / CPU / GPU 时序，并自动生成
CSV 与 Markdown 报告。

## 为什么不用现成 App

见 [`../../01-Field-Discovery/T02-Phone-Power-Thermal/README.md`](../../01-Field-Discovery/T02-Phone-Power-Thermal/README.md#1-为什么自研采集工具)
第 1 节。核心原因：现成工具不能按工况打标签、不能导出原始时序、不记录前台应用。

## 架构

| 文件 | 职责 | 关键点 |
|---|---|---|
| `MainActivity.kt` | 唯一界面 | 纯代码构建 View，不使用 layout XML 与任何 UI 框架 |
| `CollectorService.kt` | 前台服务 + 定时调度 | `PARTIAL_WAKE_LOCK` 防冻结；按绝对时刻 `startAt + seq×5min` 调度，避免误差累积 |
| `Sampler.kt` | 单次采样 | 一次 `su` 调用批量读取全部 sysfs 节点（约 200ms），单位量级自适应归一化 |
| `Shell.kt` | root 执行器 | 带超时的子进程读取，避免 `su` 授权弹窗把采样线程永久挂住 |
| `Exporter.kt` | CSV + 报告 | 设备端离线生成，root 复制到 `/sdcard/Download/PowerProbe/` |
| `Model.kt` | 数据结构 + 进程内状态 | CSV 列顺序与 `Sample.CSV_HEADER` 严格绑定 |

## 关键设计取舍

**零第三方依赖。** 不用 AppCompat、不用 Compose、不用 Room。全部走 Android SDK 原生 API
（`android.app.Activity`、`Notification.Builder`、`Activity.requestPermissions`）。
理由：一是减小 CI 编译失败面，二是面试被问到「这个依赖解决了什么问题」时不会答不上来。

**用 root 直读而不是 `BatteryManager`。** 系统的 `ACTION_BATTERY_CHANGED` 广播只在电量整数变化时
才可靠刷新，30 分钟内可能只触发几次，做不出曲线。`/sys/class/power_supply/battery/current_now`
给的是 PMIC 的瞬时电流，粒度足够。

**一次 `su` 读全部节点。** 每个字段单独起一次 `su` 进程要 200ms 以上，十几个字段就是 3 秒，
而且会让采样时刻彼此错开。这里把 6 类节点写进一个 shell 脚本，用 `@@SECTION@@` 标记分段，
一次调用取回全部。

**启发式单位归一化。** 不同芯片/ROM 的 sysfs 单位不统一：电流可能是 µA 或 mA，电压可能是 µV 或 mV，
温度可能是 0.1℃ 或 0.001℃。`Sampler` 用数量级判断（见下表），拿不到的字段回退系统 API，
并在报告里标注 `root 直读 sysfs：失败`，不假装拿到了。

## CSV 字段字典

共 22 列，顺序即 `Sample.CSV_HEADER`。

| # | 字段 | 含义 | 来源 | 归一化规则 |
|---|---|---|---|---|
| 1 | `timestamp_iso` | 采样时刻（ISO 8601，含时区） | 设备系统时钟 | — |
| 2 | `elapsed_s` | 距会话开始的秒数 | `SystemClock.elapsedRealtime()` | 不受用户改系统时间影响 |
| 3 | `scenario` | 工况代号 | 会话参数 | `IDLE` / `SVIDEO` / `NAVCAM` / `GAME` |
| 4 | `seq` | 采样点序号，0 起；收尾行为 -1 | 调度器 | — |
| 5 | `battery_pct` | 电量百分比 | `battery/capacity` → 回退 `EXTRA_LEVEL` | — |
| 6 | `voltage_mv` | 电池电压 | `battery/voltage_now` | 绝对值 >100000 视为 µV，÷1000 |
| 7 | `current_ma` | 瞬时电流，**负值 = 放电** | `battery/current_now` | 绝对值 >20000 视为 µA，÷1000；回退 `BATTERY_PROPERTY_CURRENT_NOW` |
| 8 | `batt_temp_c` | 电池温度 | `battery/temp` | 绝对值 >2000 视为 0.001℃，>200 视为 0.1℃，否则按 ℃ |
| 9 | `charge_uah` | 剩余电荷量 | `battery/charge_counter` | µAh；不可读时为 -1 |
| 10 | `status` | 充放电状态 | `battery/status` / `EXTRA_STATUS` | 文本枚举 |
| 11 | `power_w` | 功率 | 计算 | `voltage_mv/1000 × current_ma/1000`，负值 = 放电 |
| 12 | `cpu_avg_mhz` | 8 核平均瞬时频率 | `cpuN/cpufreq/scaling_cur_freq` | kHz ÷1000 |
| 13 | `cpu_load_pct` | 整机 CPU 占用 | `/proc/stat` 两次差分（间隔 200ms） | `1 − Δidle/Δtotal` |
| 14 | `gpu_mhz` | GPU 瞬时频率 | 依次尝试 kgsl / mali0 / gpu_clock / devfreq | 数量级判断 Hz/kHz/MHz |
| 15 | `thermal_max_c` | 全部热区最高温 | `/sys/class/thermal/thermal_zone*/temp` | 同字段 8；过滤 ≤0 与 >150 的异常值 |
| 16 | `thermal_max_type` | 最高温热区的名称 | 同目录 `type` | 直接取字符串 |
| 17 | `soc_thermal_c` | SoC 类热区最高温 | 同上，按名称过滤 | 名称含 `soc`/`cpu`/`cluster`/`gpu`/`ap` |
| 18 | `foreground_pkg` | 采样瞬间的前台应用包名 | `dumpsys activity activities` | 正则提取 `包名/` 前缀 |
| 19 | `screen_on` | 屏幕是否点亮 | `dumpsys power` → 回退 `PowerManager.isInteractive` | 1/0 |
| 20 | `charging` | 是否在充电 | `EXTRA_PLUGGED` / `EXTRA_STATUS` | 1/0；为 1 时该会话不可作放电基线 |
| 21 | `root_ok` | 本次采样是否成功走 root 直读 | 脚本是否输出 `@@END@@` | 1/0；连续为 0 说明授权失败 |
| 22 | `is_final` | 是否为会话收尾校验行 | 调度器 | 1 表示 `elapsed_s` 应接近 1800 |

## 构建

APK 由 GitHub Actions 构建，不在本地编译（本地无 Android SDK）：

- 工作流：`.github/workflows/build-apk.yml`
- 触发：推送到 `main` 且改动 `tools/PowerProbe/**`，或手动 `workflow_dispatch`
- 产物：Actions Artifacts 里的 `PowerProbe-debug-apk`，以及 Release `apk-latest` 下的 `app-debug.apk`

工具链：JDK 17 / Gradle 8.7 / AGP 8.5.2 / Kotlin 1.9.24 / compileSdk 34 / minSdk 26 / targetSdk 33。

## 安装与使用

1. 下载 `app-debug.apk`，在测试机上安装（debug 签名，需允许「安装未知来源应用」）。
2. 首次运行授予通知权限；首次采集时 Magisk 会弹 root 授权，选「允许」并记住。
3. 按 `protocol.md` 完成前置锁定后，点对应工况按钮。
4. 30 分钟后自动停止并导出，产物在
   `/sdcard/Android/data/com.icec.powerprobe/files/PowerProbe/`，
   同时被复制到 `/sdcard/Download/PowerProbe/`。
5. 用数据线或文件管理器把 CSV / MD 取到仓库 `raw_data/` 与 `reports/`。

## 已知限制

- **`current_now` 的符号约定因厂商而异**，有的是放电为正。本项目按「负值 = 放电」处理，
  首次采集后需核对一次：若 `current_ma` 在明显耗电场景下为正，说明该机型符号相反，
  分析脚本里会做符号翻转（不修改原始 CSV）。
- **天玑平台的 GPU 频率节点不一定可读**，读不到时 `gpu_mhz = 0`，报告中会体现为 0 而非异常。
- **`dumpsys` 输出格式随 Android 版本变化**，前台包名正则在 HyperOS 上已实测，其他 ROM 可能需调整。
- **不做数据分析**。本工具只负责采集与初版报告，跨工况对比、图表、归因由
  `analysis/` 下的 Python 脚本完成，两者共用同一份 CSV，保证可复现。
