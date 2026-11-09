# 安全说明（可审计）

这个 App 会用到 root，所以把「它能做什么、不能做什么」写成一份可逐条核对的清单。
所有结论都对应到具体文件与函数，评审时可以直接打开源码对照。

## 1. 权限清单

| 权限 | 用途 | 是否危险 |
|---|---|---|
| `WAKE_LOCK` | 灭屏采集时不中断定时器 | 否，仅阻止 CPU 休眠 |
| `FOREGROUND_SERVICE` | 常驻通知栏的采集服务 | 否 |
| `POST_NOTIFICATIONS` | 前台服务的通知 | 否 |
| `READ/WRITE_EXTERNAL_STORAGE`（`maxSdkVersion=28`） | 仅 Android 8/9 导出文件用 | 否，且 Android 10+ 完全不申请 |
| `PACKAGE_USAGE_STATS` | 读前台应用事件，作为工况证据 | 中：需用户在系统设置手动开启，只读已使用记录 |

**没有申请**：`QUERY_ALL_PACKAGES`（应用可见性走 `<queries>` 的 launcher intent 过滤）、
任何存储全盘权限、`SYSTEM_ALERT_WINDOW`、`REQUEST_INSTALL_PACKAGES`、设备管理器。

## 2. root 能执行的命令全集

`Root.exec()` 是唯一出口。调用它的地方都在下表，参数全部是常量字符串：

| 位置 | 命令 | 性质 |
|---|---|---|
| `Root.ensure()` | `id` | 只读 |
| `Sampler.collect()` | 批量脚本：`cat` 电池/CPU/GPU/热区节点、`dumpsys activity`、`dumpsys power`、`grep` | 只读 |
| `Metrics.probe()` | 批量脚本：`pidof`、`awk /proc/<pid>/stat`、`grep Pss: /proc/<pid>/smaps_rollup`、`dumpsys gfxinfo`、`cat /sys/class/net/*/statistics` | 只读 |
| `Metrics.resetBaseline()` | `dumpsys gfxinfo <包名> reset` | 仅清空该应用的帧统计计数，不动任何用户数据 |
| `Automator.startNavigation()` | `am start -a VIEW -d amapuri://route/plan/?…` | 仅向高德投一个深链，未安装则报错退出 |
| `Automator.launch()` | `am start -W -n <组件>` 或 `monkey -p <包名> … 1` | 仅启动应用 |
| `Automator.swipeUp()` / `screenOff()` / `screenOn()` | `input swipe` / `input keyevent 223` / `224` | 仅注入 UI 事件 |
| `Automator.forceStop()` / `startVideoCapture()` | `am force-stop <包名>` / `am start -a …VIDEO_CAPTURE` + `input keyevent 27` | 仅作用于应用 |
| `Automator.shot()` | `mkdir -p` + `screencap -p` | 仅写 `/sdcard/Download/PowerProbe/shots/` |

**没有** `su -c sh`、没有交互式 shell、没有命令拼接用户输入、没有脚本下载执行。

## 3. 运行时黑名单

`Root.kt` 里的 `FORBIDDEN` 正则在每次执行前拦截：

```
rm rmdir mkfs mke2fs dd mount umount format wipe reboot recovery fastboot
setprop chmod chown mv cp ln shred truncate tee install flash persist
>> 以及任何输出重定向
```

命中即返回 `__REFUSED_BY_GUARD__`，子进程都不创建。即使将来有人在源码里手滑加了破坏性命令，
运行时也执行不了。这是「纵深防御」，不是替代代码审查。

**一个已修的真实缺陷**：旧版把「输出重定向」整体拦掉，结果 `2>/dev/null` 也被判为危险重定向，
所有带它的批量只读脚本（电池、热区、gfxinfo）全部被拒，root 通道静默降级成公共 API。
现在 `HARMLESS_REDIRECT` 先剥掉 `2>/dev/null`、`2>&1`、`&>/dev/null` 这三种「丢弃输出」写法，
再跑黑名单；`> /sdcard/x`、`>>` 这类真正写文件的仍然拦。

## 4. 为什么不可能格机

- 格机（变砖）通常来自写错分区、改 `boot`/`system`、动 `recovery`/`fastboot`、
  或 `wipe data`。上面的命令全集里**没有一条**能触碰这些路径，黑名单也堵死了相关命令。
- 未申请设备管理器，App 在权限层面就不具备 `wipeData()` 能力。
- root 授权由 Magisk / KernelSU 管理，随时可在管理器里撤销；撤销后 App 自动退回公共 API，
  只是数据变粗，不会崩溃。

## 5. 数据流向

全部本地：采样 →（v1.5.0 起）每 5 分钟即采即写 → 镜像到公共 `Download/PowerProbe/`；工况结束时再出正式 CSV 与报告。应用私有目录也会被卸载清除，所以公共 Download 是唯一的持久副本。
**没有任何网络请求**，没有 `INTERNET` 权限，APK 里也没有 HTTP 客户端依赖。

## 6. 复现审计

```bash
# 1. 确认没有网络权限
aapt dump permissions app-debug.apk

# 2. 确认唯一的子进程出口，且除 Root.kt 外没有第二处
grep -rn "ProcessBuilder\|Runtime.getRuntime" tools/PowerProbe/app/src/main/java

# 3. 确认命令黑名单存在
grep -n "FORBIDDEN" tools/PowerProbe/app/src/main/java/com/icec/powerprobe/Root.kt
```

## 7. 开发签名密钥（v1.5.0 起）

`signing/powerprobe.jks` 是为「每次 CI 构建签名一致、可直接覆盖安装」放进仓库的**开发密钥**，
口令明文写在 `build.gradle`。它不是发布密钥，不用于任何正式分发，也不接触用户数据：
App 不申请 `INTERNET` 权限，密钥只在构建机上被 Gradle 读取，运行时完全不参与。

为什么必须固定：v1.4.0 之前，Actions 每次在全新 runner 上临时生成 `debug.keystore`，
三次构建的证书 SHA-256 各不相同，手机上只能卸载重装，卸载又会连应用私有目录一起删，
导致未归档的采样与日志丢失。固定签名后可直接覆盖安装，数据保留。

风险与边界：
- 仓库当前为私有。若仓库转为公开，任何拿到这把密钥的人都能给 `com.icec.powerprobe`
  签同名包；Android 仍会要求用户确认安装，但同签名允许覆盖升级。
- 转公开前应删除该文件，改为在 GitHub Actions Secrets 里存 keystore 的 base64 与口令，
  workflow 解码到构建机临时文件，`build.gradle` 从环境变量读取。
- 这把密钥与 root 通道无关：不参与任何运行时命令，不写入设备。
