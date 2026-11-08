package com.icec.powerprobe

import android.content.Context
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * CSV 与 Markdown 报告导出。
 *
 * 设计取舍：报告在设备端离线生成，不依赖任何网络与后端，保证「数据采集 → 归档」
 * 全链路可复现；图表级分析交给仓库里的 Python 脚本（analysis/），两者共享同一份 CSV。
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
        val last = samples.lastOrNull()
        val f = File(dir(ctx), "T02_${scenario}_${stamp()}_report.md")

        val sb = StringBuilder()
        val start = pts.firstOrNull()
        val end = last ?: pts.lastOrNull()

        val startPct = start?.batteryPct ?: -1
        val endPct = end?.batteryPct ?: -1
        val drop = if (startPct >= 0 && endPct >= 0) startPct - endPct else -1
        val durationMin = if (pts.size >= 2) (pts.last().elapsedSec - pts.first().elapsedSec) / 60.0 else 0.0

        val curAvg = pts.map { it.currentMa }.average()
        val curMin = pts.map { it.currentMa }.minOrNull() ?: 0.0
        val pwrAvg = pts.map { it.powerW }.average()
        val pwrMin = pts.map { it.powerW }.minOrNull() ?: 0.0
        val tStart = pts.firstOrNull()?.battTempC ?: 0.0
        val tMax = pts.map { it.battTempC }.maxOrNull() ?: 0.0
        val tMin = pts.map { it.battTempC }.minOrNull() ?: 0.0
        val socMax = pts.map { it.socThermalC }.maxOrNull() ?: 0.0
        val thermalMax = pts.map { it.thermalMaxC }.maxOrNull() ?: 0.0
        val thermalMaxType = pts.filter { it.thermalMaxC == thermalMax }.map { it.thermalMaxType }.firstOrNull() ?: "-"
        val cpuAvg = pts.map { it.cpuAvgMhz }.average()
        val loadAvg = pts.map { it.cpuLoadPct }.average()
        val gpuMax = pts.map { it.gpuMhz }.maxOrNull() ?: 0.0
        val rootOk = pts.any { it.rootOk }
        val screenOn = pts.any { it.screenOn }
        val charging = pts.any { it.charging }
        val fgCount = pts.map { it.foregroundPkg }.filter { it.isNotEmpty() }.groupingBy { it }.eachCount()
        val fgText = if (fgCount.isEmpty()) "未捕获" else fgCount.entries.sortedByDescending { it.value }
            .joinToString("；") { "${it.key} × ${it.value}" }

        sb.append("# 课题 02 采集报告 · ").append(scenarioName(scenario)).append("\n\n")
        sb.append("> 由 PowerProbe 在设备端自动生成，数据全部来自本机传感器与系统节点，未经人工修改。\n\n")

        sb.append("## 0. 采集条件\n\n")
        sb.append("| 项 | 值 |\n|---|---|\n")
        sb.append("| 设备 | ").append(CollectorState.deviceLine.ifEmpty { Sampler.deviceLine() }).append(" |\n")
        sb.append("| 场景代号 | `").append(scenario).append("` |\n")
        sb.append("| 采集开始 | ").append(start?.tsIso ?: "-").append(" |\n")
        sb.append("| 采集结束 | ").append(end?.tsIso ?: "-").append(" |\n")
        sb.append("| 采样点 | ").append(pts.size).append(" 组，间隔 5 分钟，跨度 ")
            .append(String.format(Locale.US, "%.0f", durationMin)).append(" 分钟 |\n")
        sb.append("| root 直读 sysfs | ").append(if (rootOk) "成功" else "失败（已回退系统 API）").append(" |\n")
        sb.append("| 屏幕状态 | ").append(if (screenOn) "点亮" else "熄灭").append(" |\n")
        sb.append("| 充电状态 | ").append(if (charging) "充电中（数据不可作为放电基线）" else "未充电").append(" |\n")
        sb.append("| 前台应用 | ").append(fgText).append(" |\n\n")

        sb.append("## 1. 时间序列\n\n")
        sb.append("| # | t(min) | 电量% | 电压mV | 电流mA | 功率W | 电池℃ | SoC℃ | 最高温区℃ | CPU MHz | CPU% | GPU MHz |\n")
        sb.append("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
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
                .append(" |\n")
        }
        sb.append("\n")

        sb.append("## 2. 汇总指标\n\n")
        sb.append("| 指标 | 值 | 计算口径 |\n|---|---|---|\n")
        sb.append("| 起始电量 | ").append(startPct).append("% | 首个采样点 |\n")
        sb.append("| 结束电量 | ").append(endPct).append("% | 末次采样点 |\n")
        sb.append("| 掉电幅度 | ").append(if (drop >= 0) "$drop%" else "-").append(" | 起始 − 结束 |\n")
        sb.append("| 平均电流 | ").append(f0(curAvg)).append(" mA | 所有采样点算术平均，负值表示放电 |\n")
        sb.append("| 峰值电流 | ").append(f0(curMin)).append(" mA | 绝对值最大的放电采样 |\n")
        sb.append("| 平均功率 | ").append(f2(pwrAvg)).append(" W | U×I，负值表示放电 |\n")
        sb.append("| 峰值功率 | ").append(f2(pwrMin)).append(" W | 取绝对值最大 |\n")
        sb.append("| 电池温度 | ").append(f1(tStart)).append(" → ").append(f1(tMax))
            .append(" ℃ | 起始 → 峰值 |\n")
        sb.append("| 温度变化 | ").append(f1(tMax - tMin)).append(" ℃ | 峰值 − 最低 |\n")
        sb.append("| SoC 最高温 | ").append(f1(socMax)).append(" ℃ | thermal_zone 中 CPU/GPU/SoC 类 |\n")
        sb.append("| 全场最高温区 | ").append(f1(thermalMax)).append(" ℃（").append(thermalMaxType)
            .append("） | 所有 thermal_zone |\n")
        sb.append("| CPU 平均频率 | ").append(f0(cpuAvg)).append(" MHz | 8 核瞬时频率均值 |\n")
        sb.append("| CPU 平均占用 | ").append(f1(loadAvg)).append(" % | /proc/stat 差分 |\n")
        sb.append("| GPU 峰值频率 | ").append(f0(gpuMax)).append(" MHz | 首个可读 GPU 节点 |\n\n")

        sb.append("## 3. 自动判定\n\n")
        val peakW = String.format(Locale.US, "%.2f", Math.abs(pwrMin))
        val avgW = String.format(Locale.US, "%.2f", Math.abs(pwrAvg))
        sb.append("- 平均耗散功率 **").append(avgW).append(" W**，峰值 **").append(peakW).append(" W**")
        sb.append("，峰值/平均比 ")
            .append(if (Math.abs(pwrAvg) > 0.001) String.format(Locale.US, "%.2f", Math.abs(pwrMin / pwrAvg)) else "-")
            .append(" 倍。\n")
        sb.append("- 电池温升 **").append(f1(tMax - tStart)).append(" ℃**")
        if (socMax > 0) {
            sb.append("，SoC 最高 ").append(f1(socMax)).append(" ℃")
            if (socMax > 55) sb.append("（已进入高温区，注意降频风险）")
        }
        sb.append("。\n")
        if (charging) sb.append("- ⚠ 本次采集检测到充电状态，掉电与功率数据不能作为放电基线使用。\n")
        if (!rootOk) sb.append("- ⚠ 未取得 root，电流与温度来自系统 API，采样粒度较粗，需在报告中说明。\n")
        sb.append("\n")

        sb.append("## 4. 字段来源与单位\n\n")
        sb.append("| 字段 | 来源 | 原始单位 | 归一化 |\n|---|---|---|---|\n")
        sb.append("| current_ma | `/sys/class/power_supply/battery/current_now` | µA 或 mA | 绝对值 >20000 视为 µA，除以 1000 |\n")
        sb.append("| voltage_mv | `.../voltage_now` | µV 或 mV | 绝对值 >100000 视为 µV，除以 1000 |\n")
        sb.append("| batt_temp_c | `.../temp` | 0.1℃ 或 0.001℃ | 按量级归一化 |\n")
        sb.append("| thermal_max_c | `/sys/class/thermal/thermal_zone*/temp` | 同上 | 取全部热区最大值 |\n")
        sb.append("| cpu_avg_mhz | `/sys/devices/system/cpu/cpuN/cpufreq/scaling_cur_freq` | kHz | 除以 1000 |\n")
        sb.append("| cpu_load_pct | `/proc/stat` 两次差分（间隔 200ms） | jiffies | 1 − Δidle/Δtotal |\n")
        sb.append("| foreground_pkg | `dumpsys activity activities` | 文本 | 正则提取包名 |\n")
        sb.append("| power_w | 计算值 | W | U(mV)/1000 × I(mA)/1000，负值 = 放电 |\n\n")

        sb.append("---\n\n")
        sb.append("生成时间：").append(SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())).append("\n")

        f.writeText(sb.toString())
        return f
    }

    /** 把产物复制到 /sdcard/Download/PowerProbe/，方便不用 adb 也能取文件 */
    fun publishToDownloads(ctx: Context): String {
        val d = dir(ctx)
        val p = d.absolutePath
        val cmd = "mkdir -p /sdcard/Download/PowerProbe; " +
            "cp -f \"$p\"/*.csv /sdcard/Download/PowerProbe/ 2>/dev/null; " +
            "cp -f \"$p\"/*.md /sdcard/Download/PowerProbe/ 2>/dev/null; " +
            "ls /sdcard/Download/PowerProbe/"
        return Shell.exec(cmd)
    }

    fun scenarioName(code: String): String = when (code) {
        "IDLE" -> "待机"
        "SVIDEO" -> "短视频"
        "NAVCAM" -> "导航 / 拍摄"
        "GAME" -> "高帧率游戏"
        else -> code
    }

    private fun f1(v: Double): String =
        if (v.isNaN()) "-" else String.format(Locale.US, "%.1f", v)

    private fun f2(v: Double): String =
        if (v.isNaN()) "-" else String.format(Locale.US, "%.2f", v)

    private fun f0(v: Double): String =
        if (v.isNaN()) "-" else String.format(Locale.US, "%.0f", v)
}
