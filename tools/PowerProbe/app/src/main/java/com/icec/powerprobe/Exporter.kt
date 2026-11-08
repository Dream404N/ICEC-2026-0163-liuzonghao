package com.icec.powerprobe

import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * CSV 与 Markdown 报告导出。
 *
 * 设计取舍：
 * 1. 报告在设备端离线生成，不依赖网络与后端，保证「采集 → 归档」全链路可复现；
 *    图表级分析交给仓库里的 Python 脚本，两者共享同一份 CSV。
 * 2. 落地到 Download 用 MediaStore 插入（Android 10+ 的公开目录写入方式），
 *    不需要读写整个存储的权限，也不调用任何 shell 命令。
 */
object Exporter {

    fun dir(ctx: Context): File {
        val base = ctx.getExternalFilesDir(null) ?: File(ctx.filesDir, "external")
        val d = File(base, "PowerProbe")
        if (!d.exists()) d.mkdirs()
        return d
    }

    private fun stamp(): String = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())

    fun writeCsv(ctx: Context, scenario: String, samples: List<Sample>): File {
        val f = File(dir(ctx), "T02_${scenario}_${stamp()}.csv")
        val sb = StringBuilder()
        sb.append(Sample.CSV_HEADER).append("\n")
        for (s in samples) {
            sb.append(s.toCsvLine()).append("\n")
        }
        f.writeText(sb.toString())
        return f
    }

    fun writeReport(ctx: Context, scenario: String, samples: List<Sample>): File {
        val pts = samples.filter { !it.isFinal }
        val f = File(dir(ctx), "T02_${scenario}_${stamp()}_report.md")

        val sb = StringBuilder()
        val start = pts.firstOrNull()
        val end = pts.lastOrNull()

        val startPct = start?.batteryPct ?: -1
        val endPct = end?.batteryPct ?: -1
        val drop = if (startPct >= 0 && endPct >= 0) startPct - endPct else -1
        val durationMin = if (pts.size >= 2) (pts.last().elapsedSec - pts.first().elapsedSec) / 60.0 else 0.0

        val curAvg = pts.map { it.currentMa }.average()
        val curPeak = pts.maxByOrNull { Math.abs(it.currentMa) }?.currentMa ?: 0.0
        val pwrAvg = pts.map { it.powerW }.average()
        val pwrPeak = pts.maxByOrNull { Math.abs(it.powerW) }?.powerW ?: 0.0
        val tStart = pts.firstOrNull()?.battTempC ?: 0.0
        val tMax = pts.map { it.battTempC }.maxOrNull() ?: 0.0
        val tMin = pts.map { it.battTempC }.minOrNull() ?: 0.0
        val socMax = pts.map { it.socThermalC }.maxOrNull() ?: 0.0
        val thermalMax = pts.map { it.thermalMaxC }.maxOrNull() ?: 0.0
        val thermalMaxType = pts.filter { it.thermalMaxC == thermalMax }
            .map { it.thermalMaxType }.firstOrNull() ?: "-"
        val cpuAvg = pts.map { it.cpuAvgMhz }.average()
        val loadAvg = pts.map { it.cpuLoadPct }.average()
        val gpuMax = pts.map { it.gpuMhz }.maxOrNull() ?: 0.0
        val screenOn = pts.any { it.screenOn }
        val charging = pts.any { it.charging }
        val thWorst = pts.map { it.thermalStatus }.maxByOrNull { thermalRank(it) } ?: "NA"

        // 库仑计差分：与电流积分互为交叉校验的第二个口径
        val ccFirst = pts.firstOrNull { it.chargeUah > 0 }?.chargeUah ?: -1L
        val ccLast = pts.lastOrNull { it.chargeUah > 0 }?.chargeUah ?: -1L
        val ccDiffMah = if (ccFirst > 0 && ccLast > 0) (ccFirst - ccLast) / 1000.0 else Double.NaN

        val fgCount = pts.map { it.foregroundPkg }.filter { it.isNotEmpty() }
            .groupingBy { it }.eachCount()
        val fgText = if (fgCount.isEmpty()) "未捕获（未授予使用情况访问）" else
            fgCount.entries.sortedByDescending { it.value }
                .joinToString("；") { "${it.key} × ${it.value}" }

        val fgOk = pts.count { it.dataSource.contains("fg=usage") }
        val thzOk = pts.count { it.dataSource.contains("thz=sysfs") }
        val cpuOk = pts.count { it.dataSource.contains("cpu=sysfs") }
        val gpuOk = pts.count { it.dataSource.contains("gpu=sysfs") }
        val ccOk = pts.count { it.chargeUah > 0 }

        sb.append("# 课题 02 采集报告 · ").append(scenarioName(scenario)).append("\n\n")
        sb.append("> 由 PowerProbe 在设备端自动生成。全部数值取自 Android 公共接口，")
        sb.append("运行过程不需要 root、不执行任何 shell 命令，代码可静态审计。\n\n")

        sb.append("## 0. 采集条件\n\n")
        sb.append("| 项 | 值 |\n|---|---|\n")
        sb.append("| 设备 | ").append(CollectorState.deviceLine.ifEmpty { Sampler.deviceLine() }).append(" |\n")
        sb.append("| 场景代号 | `").append(scenario).append("` |\n")
        sb.append("| 采集开始 | ").append(start?.tsIso ?: "-").append(" |\n")
        sb.append("| 采集结束 | ").append(end?.tsIso ?: "-").append(" |\n")
        sb.append("| 采样点 | ").append(pts.size).append(" 组，跨度 ")
            .append(String.format(Locale.US, "%.0f", durationMin)).append(" 分钟 |\n")
        sb.append("| 屏幕状态 | ").append(if (screenOn) "点亮" else "熄灭").append(" |\n")
        sb.append("| 充电状态 | ").append(if (charging) "充电中（数据不可作为放电基线）" else "未充电").append(" |\n")
        sb.append("| 前台应用 | ").append(fgText).append(" |\n\n")

        sb.append("## 1. 时间序列\n\n")
        sb.append("| # | t(min) | 电量% | 电压mV | 电流mA | 功率W | 电池℃ | SoC℃ | 最高温区℃ | CPU MHz | CPU% | GPU MHz | 热等级 |\n")
        sb.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for (p in pts) {
            val t = p.elapsedSec / 60
            sb.append("| ").append(p.seq + 1)
                .append(" | ").append(t)
                .append(" | ").append(p.batteryPct)
                .append(" | ").append(p.voltageMv)
                .append(" | ").append(f0(p.currentMa))
                .append(" | ").append(f2(p.powerW))
                .append(" | ").append(f1(p.battTempC))
                .append(" | ").append(f1(p.socThermalC))
                .append(" | ").append(f1(p.thermalMaxC))
                .append(" | ").append(f0(p.cpuAvgMhz))
                .append(" | ").append(f1(p.cpuLoadPct))
                .append(" | ").append(f0(p.gpuMhz))
                .append(" | ").append(p.thermalStatus)
                .append(" |\n")
        }
        sb.append("\n")

        sb.append("## 2. 汇总指标\n\n")
        sb.append("| 指标 | 值 | 计算口径 |\n|---|---|---|\n")
        sb.append("| 起始电量 | ").append(startPct).append("% | 首个采样点 |\n")
        sb.append("| 结束电量 | ").append(endPct).append("% | 末次采样点 |\n")
        sb.append("| 掉电幅度 | ").append(if (drop >= 0) "$drop%" else "-").append(" | 起始 − 结束 |\n")
        sb.append("| 平均电流 | ").append(f0(curAvg)).append(" mA | 所有采样点算术平均，负值表示放电 |\n")
        sb.append("| 峰值电流 | ").append(f0(curPeak)).append(" mA | 绝对值最大的采样点（带符号） |\n")
        sb.append("| 平均功率 | ").append(f2(pwrAvg)).append(" W | U×I，负值表示放电 |\n")
        sb.append("| 峰值功率 | ").append(f2(pwrPeak)).append(" W | 取绝对值最大点 |\n")
        sb.append("| 库仑计净放电量 | ").append(if (ccDiffMah.isNaN()) "-" else f1(ccDiffMah))
            .append(" mAh | 首个与末个可读库仑计读数之差 |\n")
        sb.append("| 电池温度 | ").append(f1(tStart)).append(" → ").append(f1(tMax))
            .append(" ℃ | 起始 → 峰值 |\n")
        sb.append("| 温度变化 | ").append(f1(tMax - tMin)).append(" ℃ | 峰值 − 最低 |\n")
        sb.append("| SoC 最高温 | ").append(f1(socMax)).append(" ℃ | sysfs 热区中 CPU/GPU/SoC 类 |\n")
        sb.append("| 全场最高温区 | ").append(f1(thermalMax)).append(" ℃（").append(thermalMaxType)
            .append("） | 所有可读热区 |\n")
        sb.append("| 系统热等级（最严） | ").append(thWorst).append(" | PowerManager.getCurrentThermalStatus |\n")
        sb.append("| CPU 平均频率 | ").append(f0(cpuAvg)).append(" MHz | 各核瞬时频率均值 |\n")
        sb.append("| CPU 平均占用 | ").append(f1(loadAvg)).append(" % | /proc/stat 差分 |\n")
        sb.append("| GPU 峰值频率 | ").append(f0(gpuMax)).append(" MHz | 首个可读 GPU 节点 |\n\n")

        sb.append("## 3. 自动判定\n\n")
        sb.append("- 平均耗散功率 **").append(f2(Math.abs(pwrAvg))).append(" W**，峰值 **")
            .append(f2(Math.abs(pwrPeak))).append(" W**")
        sb.append("，峰值/平均比 ")
            .append(if (Math.abs(pwrAvg) > 0.001) f2(Math.abs(pwrPeak / pwrAvg)) else "-")
            .append(" 倍。\n")
        sb.append("- 电池温升 **").append(f1(tMax - tStart)).append(" ℃**")
        if (socMax > 0) {
            sb.append("，SoC 最高 ").append(f1(socMax)).append(" ℃")
            if (socMax > 55) sb.append("（已进入高温区，存在降频风险）")
        }
        sb.append("。\n")
        if (thermalRank(thWorst) >= thermalRank("MODERATE")) {
            sb.append("- 采集期间系统上报 **").append(thWorst)
                .append("** 级热压力，性能调度可能已介入，横向比较时需注意。\n")
        }
        if (charging) {
            sb.append("- ⚠ 本次采集检测到充电状态，掉电与功率数据不能作为放电基线使用。\n")
        }
        if (ccOk == 0) {
            sb.append("- ⚠ 本机未提供库仑计读数，电量消耗只能依赖电流积分与百分比差分。\n")
        }
        if (fgOk == 0) {
            sb.append("- ⚠ 未授予「使用情况访问」，缺少前台应用证据，本报告的工况真实性仅由日志与录屏佐证。\n")
        }
        sb.append("\n")

        sb.append("## 4. 数据来源与能力边界\n\n")
        sb.append("| 字段 | 接口 | 单位 | 本次可用率 |\n|---|---|---|---|\n")
        sb.append("| current_ma | `BatteryManager.BATTERY_PROPERTY_CURRENT_NOW` / `_AVERAGE` | µA → mA | ")
            .append(pct(pts.size - pts.count { it.dataSource.contains("batt=none") }, pts.size)).append(" |\n")
        sb.append("| charge_uah | `BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER` | µAh | ")
            .append(pct(ccOk, pts.size)).append(" |\n")
        sb.append("| voltage_mv / batt_temp_c | 粘性广播 `ACTION_BATTERY_CHANGED` | mV / 0.1℃ | ")
            .append(pct(pts.count { it.voltageMv > 0 }, pts.size)).append(" |\n")
        sb.append("| thermal_status | `PowerManager.getCurrentThermalStatus()` | 枚举 | ")
            .append(pct(pts.count { it.thermalStatus != "NA" }, pts.size)).append(" |\n")
        sb.append("| thermal_max_c / soc_thermal_c | `/sys/class/thermal/thermal_zone*/temp`（只读） | 按量级归一化 | ")
            .append(pct(thzOk, pts.size)).append(" |\n")
        sb.append("| cpu_avg_mhz | `/sys/.../cpufreq/scaling_cur_freq`（只读） | kHz → MHz | ")
            .append(pct(cpuOk, pts.size)).append(" |\n")
        sb.append("| gpu_mhz | 各家 GPU 频率节点（只读） | 按量级归一化 | ")
            .append(pct(gpuOk, pts.size)).append(" |\n")
        sb.append("| cpu_load_pct | `/proc/stat` 两次差分 | jiffies | 100% |\n")
        sb.append("| foreground_pkg | `UsageStatsManager.queryEvents` | 包名 | ")
            .append(pct(fgOk, pts.size)).append(" |\n")
        sb.append("| power_w | 计算值 | W | U(mV)/1000 × I(mA)/1000，负值 = 放电 |\n\n")
        sb.append("**已知局限（写进正式报告，不藏）**\n\n")
        sb.append("1. 无 root 时读不到 `dumpsys batterystats`，因此拿不到系统级的分应用耗电归因，")
        sb.append("本报告的所有功率都是**整机口径**，不外推到单个 App。\n")
        sb.append("2. 电池驱动上报的电流存在厂商级滤波，稳态工况下可信，")
        sb.append("秒级尖峰（如相机启动）可能被平滑掉，故以 5 分钟为官方口径、不追求秒级分辨率。\n")
        sb.append("3. `thermal_status` 是系统聚合后的分级，粒度粗；")
        sb.append("`thermal_max_c` 依赖机型是否开放 sysfs，两者互补使用。\n\n")

        sb.append("---\n\n")
        sb.append("生成时间：").append(SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())).append("\n")

        f.writeText(sb.toString())
        return f
    }

    /**
     * 把产物复制到系统 Download/PowerProbe/。
     * Android 10+ 走 MediaStore 插入公开下载目录，无需存储权限、无需 shell。
     * Android 8/9 回退到直接写外部存储（清单里已声明 maxSdkVersion=28 的写权限）。
     */
    fun publishToDownloads(ctx: Context, files: List<File>): Int {
        var ok = 0
        for (src in files) {
            if (!src.exists()) continue
            try {
                if (Build.VERSION.SDK_INT >= 29) {
                    val values = ContentValues().apply {
                        put(MediaStore.MediaColumns.DISPLAY_NAME, src.name)
                        put(MediaStore.MediaColumns.MIME_TYPE, mimeOf(src.name))
                        put(
                            MediaStore.MediaColumns.RELATIVE_PATH,
                            Environment.DIRECTORY_DOWNLOADS + "/PowerProbe"
                        )
                        put(MediaStore.MediaColumns.IS_PENDING, 1)
                    }
                    val resolver = ctx.contentResolver
                    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    if (uri != null) {
                        resolver.openOutputStream(uri)?.use { out ->
                            src.inputStream().use { it.copyTo(out) }
                        }
                        values.clear()
                        values.put(MediaStore.MediaColumns.IS_PENDING, 0)
                        resolver.update(uri, values, null, null)
                        ok++
                    }
                } else {
                    @Suppress("DEPRECATION")
                    val pub = Environment.getExternalStoragePublicDirectory(
                        Environment.DIRECTORY_DOWNLOADS
                    )
                    val d = File(pub, "PowerProbe")
                    if (!d.exists()) d.mkdirs()
                    src.copyTo(File(d, src.name), overwrite = true)
                    ok++
                }
            } catch (e: Exception) {
                CollectorState.log("导出到 Download 失败（" + src.name + "）：" + e.message)
            }
        }
        return ok
    }

    private fun mimeOf(name: String): String = when {
        name.endsWith(".csv") -> "text/csv"
        name.endsWith(".md") -> "text/markdown"
        else -> "application/octet-stream"
    }

    private fun pct(n: Int, total: Int): String =
        if (total <= 0) "-" else String.format(Locale.US, "%d/%d", n, total)

    private fun thermalRank(s: String): Int = when (s) {
        "NONE" -> 0
        "LIGHT" -> 1
        "MODERATE" -> 2
        "SEVERE" -> 3
        "CRITICAL" -> 4
        "EMERGENCY" -> 5
        "SHUTDOWN" -> 6
        else -> -1
    }

    fun scenarioName(code: String): String = when (code) {
        "IDLE" -> "待机"
        "SVIDEO" -> "短视频"
        "NAVCAM" -> "导航 / 拍摄"
        "GAME" -> "高帧率游戏"
        else -> code
    }

    private fun f1(v: Double): String =
        if (v.isNaN() || v.isInfinite()) "-" else String.format(Locale.US, "%.1f", v)

    private fun f2(v: Double): String =
        if (v.isNaN() || v.isInfinite()) "-" else String.format(Locale.US, "%.2f", v)

    private fun f0(v: Double): String =
        if (v.isNaN() || v.isInfinite()) "-" else String.format(Locale.US, "%.0f", v)
}
