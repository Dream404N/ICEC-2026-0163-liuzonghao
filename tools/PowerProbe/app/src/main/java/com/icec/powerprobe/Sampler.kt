package com.icec.powerprobe

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.PowerManager
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 单次采样器。
 *
 * 设计取舍：
 * 1. 电源指标优先走 root 直读 battery 电源节点的 sysfs 文件，因为系统的
 *    BATTERY_CHANGED 广播只在电量整数变化时刷新，30 分钟内可能只触发几次，
 *    无法反映真实放电曲线。
 * 2. 一次 su 调用批量读取全部节点（约 200ms），避免每个字段起一次 su 进程。
 * 3. 所有单位都做量级自适应：不同芯片/ROM 的 sysfs 单位不统一（µA 与 mA、
 *    µV 与 mV、0.1℃ 与 0.001℃），用启发式归一化，解析失败则回退系统 API。
 */
object Sampler {

    private val BATCH_CMD_BODY = """
echo "@@BAT@@"
for n in current_now current_avg voltage_now temp charge_counter capacity status health; do v=${'$'}(cat /sys/class/power_supply/battery/${'$'}n 2>/dev/null); echo "${'$'}n=${'$'}v"; done
echo "@@CPUF@@"
for i in 0 1 2 3 4 5 6 7; do v=${'$'}(cat /sys/devices/system/cpu/cpu${'$'}i/cpufreq/scaling_cur_freq 2>/dev/null); echo "c${'$'}i=${'$'}v"; done
echo "@@GPU@@"
cat /sys/class/kgsl/kgsl-3d0/gpuclk 2>/dev/null
cat /sys/class/misc/mali0/device/clock 2>/dev/null
cat /sys/kernel/gpu/gpu_clock 2>/dev/null
cat /sys/kernel/gpu/gpu_freq 2>/dev/null
cat /sys/class/devfreq/*mali*/cur_freq 2>/dev/null
echo "@@TH@@"
for z in /sys/class/thermal/thermal_zone*; do t=${'$'}(cat ${'$'}z/type 2>/dev/null); v=${'$'}(cat ${'$'}z/temp 2>/dev/null); if [ -n "${'$'}t" ]; then echo "${'$'}t=${'$'}v"; fi; done
echo "@@FG@@"
dumpsys activity activities 2>/dev/null | grep -m1 -E "mResumedActivity|topResumedActivity|ResumedActivity"
echo "@@SC@@"
dumpsys power 2>/dev/null | grep -m1 -E "mWakefulness=|mScreenOn"
echo "@@END@@"
"""

    private val PKG_RE = Regex("([a-zA-Z][a-zA-Z0-9_]*(?:\\.[a-zA-Z0-9_]+){1,6})/")

    fun deviceLine(): String = "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL} " +
        "(Android ${android.os.Build.VERSION.RELEASE}, SDK ${android.os.Build.VERSION.SDK_INT}, " +
        "SoC ${android.os.Build.HARDWARE}, ABI ${android.os.Build.SUPPORTED_ABIS.firstOrNull() ?: "-"})"

    fun collect(ctx: Context, scenario: String, seq: Int, elapsedSec: Long, isFinal: Boolean): Sample {
        val raw = Shell.exec(BATCH_CMD_BODY)
        val rootOk = raw.contains("@@END@@")
        val sec = parseSections(raw)

        val bat = kvOf(sec["BAT"])
        val cpuf = kvOf(sec["CPUF"])
        val thermal = kvOf(sec["TH"])
        val gpuLines = sec["GPU"] ?: emptyList()
        val fgLine = sec["FG"]?.firstOrNull() ?: ""
        val scLine = sec["SC"]?.firstOrNull() ?: ""

        // ---- 系统 API 兜底 ----
        val battIntent: Intent? = try {
            ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        } catch (e: Exception) {
            null
        }
        val lvl = battIntent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battIntent?.getIntExtra(BatteryManager.EXTRA_SCALE, 100) ?: 100
        val sysPct = if (lvl >= 0 && scale > 0) lvl * 100 / scale else -1

        val sysVoltMv = battIntent?.getIntExtra(BatteryManager.EXTRA_VOLTAGE, -1) ?: -1
        val sysTempTenth = battIntent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1
        val statusInt = battIntent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val plugged = battIntent?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0

        val bm = ctx.getSystemService(Context.BATTERY_SERVICE) as? BatteryManager
        val bmCurrentUa = try {
            bm?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_NOW) ?: Int.MIN_VALUE
        } catch (e: Exception) {
            Int.MIN_VALUE
        }

        // ---- 归一化 ----
        val rootCap = num(bat["capacity"])
        val batteryPct = if (!rootCap.isNaN() && rootCap >= 0) rootCap.toInt() else sysPct

        val rootVoltMv = uVtoMv(num(bat["voltage_now"]))
        val voltageMv = if (!rootVoltMv.isNaN() && rootVoltMv > 1000) rootVoltMv.toInt() else sysVoltMv

        val rootCurrentMa = uAtoMa(num(bat["current_now"]))
        val currentMa: Double = when {
            !rootCurrentMa.isNaN() && Math.abs(rootCurrentMa) > 1.0 -> rootCurrentMa
            bmCurrentUa != Int.MIN_VALUE && bmCurrentUa != 0 -> bmCurrentUa / 1000.0
            else -> uAtoMa(num(bat["current_avg"]))
        }

        val rootTemp = rawTempToC(num(bat["temp"]))
        val battTempC = if (!rootTemp.isNaN()) rootTemp else sysTempTenth / 10.0

        val chargeUah = num(bat["charge_counter"]).let {
            if (it.isNaN()) -1L else it.toLong()
        }

        val statusStr = bat["status"]?.takeIf { it.isNotEmpty() } ?: statusName(statusInt)
        val charging = plugged != 0 || statusInt == BatteryManager.BATTERY_STATUS_CHARGING ||
            statusInt == BatteryManager.BATTERY_STATUS_FULL

        // 功率带符号：负值 = 放电，正值 = 充电
        val powerW = (voltageMv / 1000.0) * (currentMa / 1000.0)

        // ---- CPU ----
        var freqSum = 0.0
        var freqCnt = 0
        for ((_, v) in cpuf) {
            val mhz = num(v) / 1000.0
            if (!mhz.isNaN() && mhz > 0) {
                freqSum += mhz
                freqCnt++
            }
        }
        val cpuAvgMhz = if (freqCnt > 0) freqSum / freqCnt else Double.NaN
        val cpuLoad = readCpuLoadPct()

        // ---- GPU ----
        var gpuMhz = Double.NaN
        for (l in gpuLines) {
            val m = freqToMhz(num(l))
            if (!m.isNaN() && m > 0) {
                gpuMhz = m
                break
            }
        }

        // ---- 热区 ----
        var maxC = Double.NaN
        var maxType = ""
        var socC = Double.NaN
        for ((k, v) in thermal) {
            val c = rawTempToC(num(v))
            if (c.isNaN() || c <= 0.0 || c > 150.0) continue
            if (maxC.isNaN() || c > maxC) {
                maxC = c
                maxType = k
            }
            val kl = k.lowercase(Locale.US)
            if (kl.contains("soc") || kl.contains("cpu") || kl.contains("cluster") ||
                kl.contains("gpu") || kl.contains("ap_") || kl.endsWith("_ap")
            ) {
                if (socC.isNaN() || c > socC) socC = c
            }
        }

        // ---- 前台应用（工况真实性证据）----
        var fgPkg = ""
        val m = PKG_RE.find(fgLine)
        if (m != null) {
            fgPkg = m.groupValues[1]
        }

        val pm = ctx.getSystemService(Context.POWER_SERVICE) as? PowerManager
        val screenOn = if (scLine.isNotEmpty()) scLine.contains("Awake") else (pm?.isInteractive ?: false)

        val ts = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date())

        return Sample(
            tsIso = ts,
            elapsedSec = elapsedSec,
            scenario = scenario,
            seq = seq,
            batteryPct = batteryPct,
            voltageMv = voltageMv,
            currentMa = if (currentMa.isNaN()) 0.0 else currentMa,
            battTempC = if (battTempC.isNaN()) 0.0 else battTempC,
            chargeUah = chargeUah,
            status = statusStr,
            powerW = if (powerW.isNaN()) 0.0 else powerW,
            cpuAvgMhz = if (cpuAvgMhz.isNaN()) 0.0 else cpuAvgMhz,
            cpuLoadPct = if (cpuLoad.isNaN()) 0.0 else cpuLoad,
            gpuMhz = if (gpuMhz.isNaN()) 0.0 else gpuMhz,
            thermalMaxC = if (maxC.isNaN()) 0.0 else maxC,
            thermalMaxType = maxType,
            socThermalC = if (socC.isNaN()) 0.0 else socC,
            foregroundPkg = fgPkg,
            screenOn = screenOn,
            charging = charging,
            rootOk = rootOk,
            isFinal = isFinal
        )
    }

    // ---------------- 解析辅助 ----------------

    private fun parseSections(raw: String): Map<String, List<String>> {
        val map = HashMap<String, MutableList<String>>()
        var cur: String? = null
        for (lineRaw in raw.split("\n")) {
            val line = lineRaw.trim()
            if (line.length > 4 && line.startsWith("@@") && line.endsWith("@@")) {
                val name = line.substring(2, line.length - 2)
                cur = name
                if (!map.containsKey(name)) map[name] = ArrayList()
            } else if (cur != null && line.isNotEmpty()) {
                val key: String = cur
                map[key]?.add(line)
            }
        }
        return map
    }

    private fun kvOf(lines: List<String>?): Map<String, String> {
        val m = HashMap<String, String>()
        if (lines != null) {
            for (l in lines) {
                val i = l.indexOf('=')
                if (i > 0) m[l.substring(0, i).trim()] = l.substring(i + 1).trim()
            }
        }
        return m
    }

    private fun num(s: String?): Double {
        if (s == null) return Double.NaN
        val t = s.trim()
        if (t.isEmpty()) return Double.NaN
        return t.toDoubleOrNull() ?: Double.NaN
    }

    private fun uAtoMa(v: Double): Double {
        if (v.isNaN()) return Double.NaN
        return if (Math.abs(v) > 20000.0) v / 1000.0 else v
    }

    private fun uVtoMv(v: Double): Double {
        if (v.isNaN()) return Double.NaN
        return if (Math.abs(v) > 100000.0) v / 1000.0 else v
    }

    /** sysfs 温度可能是 0.1℃ 或 0.001℃，按量级归一化 */
    private fun rawTempToC(v: Double): Double {
        if (v.isNaN()) return Double.NaN
        val a = Math.abs(v)
        return when {
            a > 2000.0 -> v / 1000.0
            a > 200.0 -> v / 10.0
            else -> v
        }
    }

    private fun freqToMhz(v: Double): Double {
        if (v.isNaN()) return Double.NaN
        val a = Math.abs(v)
        return when {
            a > 100000000.0 -> v / 1000000.0
            a > 10000.0 -> v / 1000.0
            else -> v
        }
    }

    private fun statusName(code: Int): String = when (code) {
        BatteryManager.BATTERY_STATUS_CHARGING -> "charging"
        BatteryManager.BATTERY_STATUS_DISCHARGING -> "discharging"
        BatteryManager.BATTERY_STATUS_FULL -> "full"
        BatteryManager.BATTERY_STATUS_NOT_CHARGING -> "not_charging"
        else -> "unknown"
    }

    /** 读 /proc/stat 两次差分，算整机 CPU 占用率 */
    private fun readCpuLoadPct(): Double {
        val a = readCpuStat()
        if (a.isEmpty()) return Double.NaN
        try {
            Thread.sleep(200)
        } catch (e: InterruptedException) {
            return Double.NaN
        }
        val b = readCpuStat()
        if (b.isEmpty() || a.size != b.size) return Double.NaN

        var totalA = 0L
        var totalB = 0L
        for (x in a) totalA += x
        for (x in b) totalB += x
        if (a.size <= 4) return Double.NaN
        val idleA = a[3] + a[4]
        val idleB = b[3] + b[4]
        val dt = totalB - totalA
        if (dt <= 0L) return Double.NaN
        val pct = (1.0 - (idleB - idleA).toDouble() / dt.toDouble()) * 100.0
        return Math.max(0.0, Math.min(100.0, pct))
    }

    private fun readCpuStat(): LongArray {
        return try {
            val f = java.io.File("/proc/stat")
            if (!f.exists() || !f.canRead()) return LongArray(0)
            val line = f.readLines().firstOrNull { it.startsWith("cpu ") } ?: return LongArray(0)
            val parts = line.trim().split(Regex("\\s+"))
            if (parts.size < 2) return LongArray(0)
            LongArray(parts.size - 1) { idx -> parts[idx + 1].toLongOrNull() ?: 0L }
        } catch (e: Exception) {
            LongArray(0)
        }
    }
}
