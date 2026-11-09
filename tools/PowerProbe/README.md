# PowerProbe

课题 02（手机多工况发热与掉电实测）的采集 + 自动化执行工具。

它做两件事：

1. **自动跑工况**：一次启动，按「待机 → 短视频 → 导航拍摄 → 高帧率游戏」的顺序连跑 4 个工况，
   每个工况自动拉起对应 App、自动灭屏、自动在短视频里翻页、15 分钟时自动切相机，
   到点自动 `force-stop`、自动归档，全程不用人守着。
2. **自动出数据**：每 5 分钟落一个采样点（对齐官网「30 分钟内每 5 分钟」的 24 组口径），
   写 CSV（33 列：整机功耗/热力 + 被测应用的进程级性能）+ 设备端 Markdown 报告；
   有 root 时每 10 分钟还会 `screencap` 留一张截图作为工况存证，防摆拍。

## v1.5.0：固定签名与数据不丢

**问题**：v1.4.0 及更早版本由 GitHub Actions 构建，每台 runner 都会临时生成自己的
`debug.keystore`，导致**每次 APK 签名证书都不同**。手机上只能先卸载再装，而卸载会把
`Android/data/com.icec.powerprobe/` 一起删掉；再加上旧版 CSV 只在工况结束时才落盘、
运行日志只存在内存里，于是「一强制安装，之前的日志就没了」。

**修复**：

| 措施 | 做法 | 效果 |
|---|---|---|
| 固定签名 | 仓库内 `signing/powerprobe.jks` + `build.gradle` 显式 `signingConfigs.probe`，debug/release 共用 | 任意两次 CI 产物签名证书一致，可直接覆盖安装 |
| 采样点即采即落盘 | 每采一个点 `append` 到 `T02_<工况>_<会话>_live.csv`，随后镜像到 `Download/PowerProbe/` | 中途强杀、卸载、断电都不丢已采数据 |
| 日志持久化 | `CollectorState.log()` 每行同步写入 `T02_<会话>_log.txt` 并镜像到公共目录 | 重装后主界面自动读回上次日志 |
| 公共目录镜像 | MediaStore 同名覆盖（`openOutputStream(uri, "wt")`），不设 `IS_PENDING` | 卸载不会删除，也不会堆出一堆 `(1)` 副本 |

⚠ **只需卸载一次**：已安装 v1.4.0 及更早版本时，新旧签名不兼容，必须先手动卸载再装 v1.5.0。
从 v1.5.0 起所有版本都能直接覆盖安装，`Download/PowerProbe/` 里的历史 CSV、日志和报告都在。

正式产物（工况结束时的 `T02_<工况>_<时间戳>.csv` + `_report.md`）仍照常生成，
与实时文件并存：实时文件用于兜底，正式文件用于交付。

## 随时可停

停止有三条独立入口，任何一条都能立即生效：

1. **状态卡首行「停止并归档」**（运行中会变成醒目的强调色）；
2. **通知栏按钮「停止并归档」**——锁屏或其他 App 前台时也能停；
3. App 内二次确认后投递 `ACTION_STOP` 给服务。

服务侧做了三件事保证「说停就停」：先 `removeCallbacksAndMessages(null)` 摘掉采样/自动化/
曲线三类定时任务，再在后台线程归档已采数据，最后 `releaseWake` + `stopForeground` + `stopSelf`。
上一版把归档放在主线程且要起 `su` 子进程，su 弹窗一没响应就会卡十几秒，表现是「点了没反应」，
这一版已经去掉全部 shell 依赖并把 IO 移出主线程。

## 实时曲线

状态卡下方是自绘的双 y 轴曲线（`SparklineView`，Canvas 实现，不引图表库）：
蓝色电流、橙色电池温度。曲线数据 10 秒一点、**只用于显示**，不写进 CSV——
归档数据仍然严格按「30 分钟 / 每 5 分钟」的官方口径，两者不混。

## 通知栏：无人值守时唯一需要看的地方

前台服务的通知不是「有个图标就行」，它是整套工具的主控面板：

- **标题**：`[2/4] 短视频 · 剩 18:24` —— 当前第几个工况、还剩多久
- **进度条**：整轮（含工况间冷却）的总进度百分比，不是当前工况的
- **正文**：采样点 `4/6` · 全程剩 `1 小时 22 分` · 总进度 `41%`
- **展开**：当前工况剩余、全程剩余、下一次采样倒计时、实时电流/功率/电池温度/热等级，
  取到进程指标时再加一行 `pid · CPU% · PSS MB · fps · 卡顿%`
- **按钮**：`停止并归档`（锁屏也能按），点通知本体回到 App
- **冷却窗口**：同一个通知切成 `冷却中 · 剩 12:30`，并提示「充到 80% 后拔线」
- **结束**：另一条「测试结束，产物已归档」，带采到多少采样点

刷新频率 5 秒（`notify()` 开销可忽略），但**采样仍然 5 分钟一次**——倒计时连续走，
数据口径没有被偷偷改密。

## 应用选择器（KernelSU 风格）

三个目标应用（短视频 / 游戏 / 导航）不再是「弹一个长列表靠肉眼翻」，而是独立页面：

- **常驻 pill 搜索栏**：输入即过滤，同时匹配应用名与包名，忽略大小写、自动去空格；
  清空按钮一键复位，软键盘的「搜索」键收起键盘。
- **真实应用图标**：`PackageManager.getApplicationIcon` 异步加载 + `LruCache` 缓存，
  `ListView` 复用视图并用 tag 校验包名，快速滚动不会贴错图标或掉帧。
- **置顶与标签**：当前选中项标「当前」并打勾，推荐项（Phigros / 高德 / 抖音等）标「推荐」，
  其余按名称排序；换机、渠道包改名也能一眼找到目标。
- **显示系统应用**开关：默认只列用户安装的、有桌面图标的应用；打开后补列无图标的系统应用
  （相机、下载管理等）。受 Android 11 应用可见性限制，这里只声明 launcher intent 的 `queries`，
  不申请 `QUERY_ALL_PACKAGES`。
- **长按复制包名**，底部「清除当前选择」可把目标恢复为空（该工况只记录不加压）。
- 列表为空时给出可操作的空态提示，而不是一片空白。

交互与版式参照 KernelSU Manager 的应用页，但代码是自实现的 Material3 布局——
KSU 是 GPL-3.0，直接复制会把本项目一并传染。

## 进程级性能指标（与 Emmagee / GT 对齐）

只测整机电流只能回答「多耗电」，回答不了「有没有把机器压满」。v1.3 起补上行业通用的
进程级/帧级指标，口径与网易 Emmagee、腾讯 GT 这类开源工具一致：

| 指标 | 数据源 | 口径 |
|---|---|---|
| `app_cpu_pct` | `/proc/<pid>/stat` 第 14、15 列差分 | jiffies / 间隔，单核 100% 基准 |
| `app_pss_mb` | `/proc/<pid>/smaps_rollup` 的 `Pss:` | 多进程 App 累加 |
| `fps` | `dumpsys gfxinfo <pkg>` 累计帧数差分 | 区间平均帧率 |
| `jank_pct` | 同上，Janky 帧数差分 / 帧数 | 区间卡顿率 |
| `frame_p99_ms` | gfxinfo 的 99th percentile | 自工况起（每工况 reset 一次） |
| `net_rx_kb` / `net_tx_kb` | `/sys/class/net/*/statistics` 累计差分 | 非 lo 网卡求和 |
| `cpu_max_mhz` | 各核 `scaling_cur_freq` 取最大 | 观察热降频 |
| `launch_ms` | `am start -W` 的 `TotalTime` | 冷/热启动耗时 |

两个刻意的设计：

- **全部用差分**，不用瞬时值。采样间隔 5 分钟，算出来的就是这 5 分钟的均值，
  与电流采样点的时间窗严格对齐，可以直接做相关性分析。
- **一次 su 调用拿全部**（脚本内 `sleep 0.9` 制造差分窗口），不做「每项一个进程」，
  避免自动化自己变成被测负载。

`fps` 在窗口 < 15 秒或帧数 < 5 时写 `-1`（未采到），不写 0——0 会被下游当成「真的 0 帧」。

## 双通道设计

| 通道 | 触发条件 | 能拿到什么 | 拿不到什么 |
|---|---|---|---|
| A · root 只读直读 | `su` 可用且已授权 | PMIC 瞬时电流、电压、电池温度、库仑计、8 核频率、GPU 频率、全部热区、`dumpsys` 真实前台 Activity | — |
| B · 公共 API | 没有 root，或 su 被拒 | `BatteryManager` 电流/库仑计/电量、粘性广播电压与温度、`/proc/stat` CPU 占用、`UsageStatsManager` 前台应用 | 分应用耗电归因、秒级尖峰 |

每个采样点都在 CSV 的 `data_source` 列记录**这一行具体走的哪条通道**，例如
`batt=sysfs;thz=sysfs;cpu=sysfs;gpu=none;fg=dumpsys;ch=root`。中途授权失效也不会出现
「数值突变但不知道原因」的黑箱，报告里会给出每个字段的可用率。

## root 会不会失控

不会，而且这件事是**用代码强制**的，不是注释里写写：

1. **不接受任何外部命令**。所有能执行的字符串都是本工程编译期写死的常量，App 不读文件、
   不读网络、不接受 Intent 传入的命令，能跑什么在 build 完的那一刻就固定了。
2. **关键字硬拦截**。`Root.exec()` 入口先过黑名单正则，命中
   `rm / mkfs / dd / mount / format / wipe / reboot / recovery / fastboot / setprop /
   chmod / chown / mv / cp / ln / shred / truncate / tee / install / flash / 重定向`
   任一就直接返回、不执行。
3. **只读为主**。日常采集只有 `cat` / `getprop` / `dumpsys` / `grep`；
   唯一带副作用的是 `am start`、`am force-stop`、`input keyevent`、`input swipe`、`screencap`，
   作用范围仅限「当前前台 UI 与已安装应用」，不写任何系统分区，不碰 recovery / fastboot。
4. **超时强杀**。su 弹窗卡住、`dumpsys` 卡住都不会挂死采样线程。
5. **不申请设备管理器**。没有 `DeviceAdminReceiver`，从权限层面就不具备 `wipeData` 的能力。

最坏情况是「某条命令被 su 拒绝、返回空串」，不存在格机路径。完整的可审计点见
[`SECURITY.md`](SECURITY.md)。

## 架构

| 文件 | 职责 | 关键点 |
|---|---|---|
| `MainActivity.kt` | 界面 | Material3 卡片行；一键全自动入口；跳转到可搜索的应用选择器 |
| `AppPickerActivity.kt` | 目标应用选择 | KSU 风格常驻搜索栏、名称/包名即时过滤、系统应用开关、图标异步缓存、长按复制包名 |
| `CollectorService.kt` | 前台服务 + 工况队列 | `PARTIAL_WAKE_LOCK` 防冻结；按绝对时刻 `startAt + seq×5min` 调度；工况间自动接力 |
| `Automator.kt` | 自动化执行器 | 拉起 App、翻页、灭屏/唤醒、切相机、截图存证 |
| `Plan.kt` | 测试计划与目标应用 | 默认 Phigros + 高德；包名对不上时按应用名模糊匹配，换机器也能跑 |
| `Sampler.kt` | 单次采样 | A/B 双通道，字段级降级，单位量级自适应 |
| `Metrics.kt` | 进程级性能 | CPU/PSS/FPS/卡顿/流量/大核频率，全部差分口径 |
| `Root.kt` | root 受限执行器 | 黑名单拦截 + 超时强杀 |
| `Sysfs.kt` | 只读节点读取 | 纯 `java.io.File`，不 fork 进程 |
| `Usage.kt` | 前台应用证据 | `UsageStatsManager` 事件流，数据由 system_server 写入、第三方改不了 |
| `Exporter.kt` | CSV + 报告 + 实时落盘 | 设备端离线生成；采样点/日志即采即写并镜像到公共 Download；MediaStore 同名覆盖 |
| `Model.kt` | 数据结构 + 进程内状态 | CSV 列顺序与 `Sample.CSV_HEADER` 严格绑定 |

## 关键设计取舍

**自动化动作必须低频。** 自动化本身会耗电，如果每分钟都跑 `dumpsys` 去确认前台应用，
测出来的就不是 App 的功耗而是 PowerProbe 的功耗。所以：工况开始时只跑 1 次校验，
之后翻页 25 秒一次、截图 10 分钟一次，采样点附近不做任何 shell 调用。这条写进报告的方法学。

**按绝对时刻调度而不是累加延时。** 单次采样 200~500ms，6 个点累加下来尾点会漂移到 31 分钟。
用 `startAt + seq×interval` 计算绝对时刻，超时就立刻补，保证 `elapsed_s` 与计划一致。

**MediaStore 而不是 shell cp。** Android 10+ 直接写 `/sdcard/Download` 需要 `WRITE_EXTERNAL_STORAGE`，
已被废弃且要用户授权；`MediaStore.Downloads.insert` 是官方推荐路径，无权限、无 shell。

**启发式单位归一化。** 不同芯片/ROM 的 sysfs 单位不统一：电流可能是 µA 或 mA，电压 µV 或 mV，
温度 0.1℃ 或 0.001℃。按数量级判断（见字段字典），判断不了就退到公共 API，不猜。

## CSV 字段字典

共 33 列，顺序即 `Sample.CSV_HEADER`。

| # | 字段 | 含义 | 来源（A 通道 / B 通道） | 归一化 |
|---|---|---|---|---|
| 1 | `timestamp_iso` | 采样时刻（ISO 8601，含时区） | 系统时钟 | — |
| 2 | `elapsed_s` | 距本工况开始的秒数 | `SystemClock.elapsedRealtime()` | 不受用户改时间影响 |
| 3 | `scenario` | 工况代号 | 会话参数 | `IDLE`/`SVIDEO`/`NAVCAM`/`GAME` |
| 4 | `seq` | 采样点序号，0 起；收尾行 -1 | 调度器 | — |
| 5 | `battery_pct` | 电量百分比 | `battery/capacity` / `BATTERY_PROPERTY_CAPACITY` | — |
| 6 | `voltage_mv` | 电池电压 | `battery/voltage_now` / `EXTRA_VOLTAGE` | \|v\|>1e5 视为 µV，÷1000 |
| 7 | `current_ma` | 电流，**负值 = 放电** | `current_now` / `BATTERY_PROPERTY_CURRENT_NOW` | \|v\|>20000 视为 µA，÷1000 |
| 8 | `batt_temp_c` | 电池温度 | `battery/temp` / `EXTRA_TEMPERATURE` | >2000 视为 0.001℃，>200 视为 0.1℃ |
| 9 | `charge_uah` | 库仑计剩余电量 | `charge_counter` / `BATTERY_PROPERTY_CHARGE_COUNTER` | µAh；不可读 -1 |
| 10 | `status` | 充放电状态 | `battery/status` / `EXTRA_STATUS` | 文本枚举 |
| 11 | `power_w` | 功率 | 计算 | `mV/1000 × mA/1000`，负值 = 放电 |
| 12 | `cpu_avg_mhz` | 各核平均瞬时频率 | `cpuN/cpufreq/scaling_cur_freq` | kHz ÷1000 |
| 13 | `cpu_load_pct` | 整机 CPU 占用 | `/proc/stat` 两次差分（100ms） | `1 − Δidle/Δtotal` |
| 14 | `gpu_mhz` | GPU 瞬时频率 | kgsl / mali0 / gpu_clock / ged / devfreq 逐个试 | 数量级判断 Hz/kHz/MHz |
| 15 | `thermal_max_c` | 全部热区最高温 | `thermal_zone*/temp` | 同字段 8；过滤 ≤0 与 >150 |
| 16 | `thermal_max_type` | 最高温热区名称 | 同目录 `type` | 字符串 |
| 17 | `soc_thermal_c` | SoC 类热区最高温 | 同上按名称过滤 | 含 `soc`/`cpu`/`cluster`/`gpu`/`ap` |
| 18 | `foreground_pkg` | 前台应用包名 | `dumpsys activity activities` / `UsageStatsManager` | 正则提包名 |
| 19 | `screen_on` | 屏幕是否点亮 | `dumpsys power` / `PowerManager.isInteractive` | 1/0 |
| 20 | `charging` | 是否充电 | `EXTRA_PLUGGED` / `EXTRA_STATUS` | 1/0；为 1 时不可作放电基线 |
| 21 | `data_source` | 本行字段来源 | 运行时探测 | `batt=…;thz=…;cpu=…;gpu=…;fg=…;ch=root\|api` |
| 22 | `thermal_status` | 系统热压力等级 | `PowerManager.getCurrentThermalStatus()` | `NONE`…`SHUTDOWN`，读不到 `NA` |
| 23 | `app_pid` | 被测应用进程 pid | `pidof` | -1 = 进程未运行或本工况无目标 |
| 24 | `app_cpu_pct` | 被测应用进程 CPU | `/proc/<pid>/stat` 第 14、15 列差分 | 单核 100% 基准，多线程可 >100 |
| 25 | `app_pss_mb` | 被测应用 PSS 内存 | `/proc/<pid>/smaps_rollup` | 多进程 App 累加 |
| 26 | `fps` | 区间平均帧率 | `dumpsys gfxinfo` 累计帧数差分 | -1 = 未采到，不写 0 |
| 27 | `jank_pct` | 区间卡顿帧占比 | gfxinfo Janky 帧差分 / 总帧 | % |
| 28 | `frame_p99_ms` | 99 分位帧耗时 | gfxinfo 99th percentile | ms |
| 29 | `net_rx_kb` | 区间下行流量 | 非 lo 网卡 `<iface>/statistics/rx_bytes` 差分 | KB / 区间 |
| 30 | `net_tx_kb` | 区间上行流量 | 非 lo 网卡 `<iface>/statistics/tx_bytes` 差分 | KB / 区间 |
| 31 | `cpu_max_mhz` | 大核当前最高频率 | 各核 `scaling_cur_freq` 取最大 | 观察热降频 |
| 32 | `launch_ms` | 冷 / 热启动耗时 | `am start -W` 的 `TotalTime` | 只挂在工况首点，其余写 0 |
| 33 | `is_final` | 是否为收尾校验行 | 调度器 | 1 表示 `elapsed_s` 应接近 1800 |

## 构建

APK 由 GitHub Actions 构建，不在本地编译（本地无 Android SDK）：

- 工作流：`.github/workflows/build-apk.yml`
- 触发：推送到 `main` 且改动 `tools/PowerProbe/**`，或手动 `workflow_dispatch`
- 产物：Actions Artifacts 的 `PowerProbe-debug-apk`，以及 Release `apk-latest` 下的 `app-debug.apk`

工具链：JDK 17 / Gradle 8.7 / AGP 8.2 / Kotlin 1.9.24 / compileSdk 34 / minSdk 26 / targetSdk 33。

**签名**：`signing/powerprobe.jks` 是仅用于保证覆盖安装一致性的开发密钥（口令 `powerprobe`，
非发布密钥，也不用于任何正式分发）。CI 每次构建都会打印证书 SHA-256 以便核对；
v1.4.0 之前三次历史构建的指纹互不相同，正是这一版要修的问题。仓库转为公开前，
建议把这把密钥移出仓库、改用 GitHub Actions Secrets 注入，避免他人用同一签名覆盖安装同名包。

## 安装与使用

1. 下载 `app-debug.apk` 安装（固定开发签名，需允许「安装未知来源应用」）。若已装 v1.4.0 或更早版本，先卸载一次；之后升级直接覆盖安装即可。
2. 首次运行授予通知权限；进「权限与数据源」点 **使用情况访问** 去系统设置打开；
   点 **root 通道** 触发一次 su 授权并确认显示「已授权」。
3. 在「自动化测试」里确认短视频 / 游戏 / 导航三个目标 App（已自动探测为 Phigros / 高德等）。
   点任意一行进入应用选择器，可直接输入名称或包名搜索，点一下即完成更换。
4. 点 **一键全自动**，确认后把手机放桌上（别充电、别动）。约 2 小时后自动结束。
5. 产物在 `Download/PowerProbe/`（卸载也不会被删除）：实时 `*_live.csv` 与 `*_log.txt`
   每 5 分钟更新一次，工况结束时另出正式 CSV 与 Markdown 报告；截图在
   `Download/PowerProbe/shots/`。应用专属目录里另有一份镜像，但那个目录会在卸载时被
   系统清掉，取数据一律以 `Download/` 为准。
6. 把 CSV / MD 取回仓库 `raw_data/` 与 `reports/`，跑 `analysis/analyze_t02.py`。

## 已知限制

- **`current_now` 符号约定因厂商而异**，有的机型放电为正。首次采集后核对一次：
  若 `current_ma` 在明显耗电场景下为正，说明符号相反，分析脚本里做翻转（不改原始 CSV）。
- **天玑平台的 GPU 频率节点常常不可读**，读不到时 `gpu_mhz = 0`，报告中体现为 0 而非编造值。
- **`dumpsys` 输出格式随 Android 版本变化**，前台包名正则在 HyperOS 上实测，其他 ROM 可能需调整；
  调整不了时自动落回 `UsageStatsManager`。
- **无 root 时灭屏、翻页、切相机需要手动**，App 只能自动拉起 App 并继续采样，报告里会标注。
- **不做跨工况统计分析**。工具只负责采集与初版报告，对比、图表、显著性检验由
  `analysis/` 下的 Python 脚本完成，两者共用同一份 CSV。
