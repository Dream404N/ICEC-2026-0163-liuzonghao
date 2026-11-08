package com.icec.powerprobe

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 单次采样器 —— 双通道：root 直读优先，公共 API 兜底。
 *
 * 通道 A（root 可用时）：一次 su 调用批量只读 sysfs / dumpsys，拿到电流、电压、温度、
 *   各核频率、GPU 频率、全部热区、真实前台 Activity。单次约 200~500ms。
 * 通道 B（无 root / su 被拒）：BatteryManager + 粘性广播 + /proc/stat + UsageStatsManager，
 *   全部为官方公共接口，零权限风险。
 *
 * 两条通道写进同一份 CSV，`data_source` 列逐点记录来源，报告里给出各字段可用率。
 * 这样即使中途换通道（比如授权失效），数据仍然可解释，不会出现「数值变了但不知道
 * 为什么变」的黑箱。
 */
object Sampler {

    /** 一次性批量只读脚本。全部是 cat / grep / dumpsys，不含任何写操作。 */
    private val BATCH_READ = """
echo "@@BAT@@"
for n in current_now current_avg voltage_now temp charge_counter capacity status health; do v=${'$'}(cat /sys/class/power_supply/battery/${'$'}n 2>/dev/null); echo "${'$'}n=${'$'}v"; done
echo "@@CPUF@@"
for i in 0 1 2 3 4 5 6 7; do v=${'$'}(cat /sys/devices/system/cpu/cpu${'$'}i/cpufreq/scaling_cur_freq 2>/dev/null); echo "c${'$'}i=${'$'}v"; done
echo "@@GPU@@"
cat /sys/class/kgsl/kgsl-3d0/gpuclk 2>/dev/null
cat /sys/class/kgsl/kgsl-3d0/devfreq/cur_freq 2>/dev/null
cat /sys/class/misc/mali0/device/clock 2>/dev/null
cat /sys/class/misc/mali0/device/devfreq/cur_freq 2>/dev/null
cat /sys/kernel/gpu/gpu_clock 2>/dev/null
cat /sys/kernel/gpu/gpu_freq 2>/dev/null
cat /proc/gpufreq/gpufreq_opp_freq 2>/dev/null
cat /sys/kernel/ged/hal/current_freqency 2>/dev/null
echo "@@TH@@"
for z in /sys/class/thermal/thermal_zone*; do t=${'$'}(cat ${'$'}z/type 2>/dev/null); v=${'$'}(cat ${'$'}z/temp 2>/dev/null); if [ -n "${'$'}t" ]; then echo "${'$'}t=${'$'}v"; fi; done
echo "@@FG@@"
dumpsys activity activities 2>/dev/null | grep -m1 -E "mResumedActivity|topResumedActivity|ResumedActivity"
echo "@@SC@@"
dumpsys power 2>/dev/null | grep -m1 -E "mWakefulness=|mScreenOn"
echo "@@END@@"
"""

    private val PKG_RE = Regex("([a-zA-Z][a-zA-Z0-9_]*(?:\\.[a-zA-Z0-9_]+){1,6})/")

    fun deviceLine(): String = "${Build.MANUFACTURER} ${Build.MODEL} " +
        "(Android ${Build.VERSION.RELEASE}, SDK ${Build.VERSION.SDK_INT}, " +
        "SoC ${Build.HARDWARE}, ABI ${Build.SUPPORTED_ABIS.firstOrNull() ?: "-"})"

    /**
     * 轻量读取：只问 BatteryManager 要电流与温度，用于界面曲线。
     * 不写 CSV、不开子进程、不碰 sysfs，10 秒一次的开销可忽略。
     */
    fun quick(ctx: Context): Pair<Double, Double> {
        val bm = ctx.getSystemService(Context.BATTERY_SERVICE) as? BatteryManager
        var ma = 0.0
        val cur = intProp(bm, BatteryManager.BATTERY_PROPERTY_CURRENT_NOW)
        if (cur != Int.MIN_VALUE && cur != 0) {
            ma = cur / 1000.0
        } else {
            val avg = intProp(bm, BatteryManager.BATTERY_PROPERTY_CURRENT_AVERAGE)
            if (avg != Int.MIN_VALUE && avg != 0) ma = avg / 1000.0
        }
        val bi: Intent? = try {
            ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        } catch (e: Exception) {
            null
        }
        val t = bi?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE) ?: Int.MIN_VALUE
        val tc = if (t != Int.MIN_VALUE && t > 0) t / 10.0 else 0.0
        return Pair(ma, tc)
    }

    fun collect(ctx: Context, scenario: String, seq: Int, elapsedSec: Long, isFinal: Boolean): Sample {
        val bm = ctx.getSystemService(Context.BATTERY_SERVICE) as? BatteryManager
        val pm = ctx.getSystemService(Context.POWER_SERVICE) as? PowerManager

        // ---------- 通道 A：root 批量直读 ----------
        val rootOk = Root.ensure()
        var sec: Map<String, List<String>> = HashMap()
        if (rootOk) {
            val raw = Root.exec(BATCH_READ, 12000)
            if (raw.contains("@@END@@")) {
                sec = parseSections(raw)
            }
        }
        val bat = kvOf(sec["BAT"])
        val cpuf = kvOf(sec["CPUF"])
        val thermalRoot = kvOf(sec["TH"])
        val gpuLines = sec["GPU"] ?: emptyList()
        val fgLine = sec["FG"]?.firstOrNull() ?: ""
        val scLine = sec["SC"]?.firstOrNull() ?: ""

        // ---------- 通道 B：公共 API ----------
        val bi: Intent? = try {
            ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        } catch (e: Exception) {
            null
        }
        val lvl = bi?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = bi?.getIntExtra(BatteryManager.EXTRA_SCALE, 100) ?: 100
        val capProp = intProp(bm, BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val sysPct = when {
            capProp != Int.MIN_VALUE -> capProp
            lvl >= 0 && scale > 0 -> lvl * 100 / scale
            else -> -1
        }
        val sysVoltMv = bi?.getIntExtra(BatteryManager.EXTRA_VOLTAGE, -1) ?: -1
        val sysTempTenth = bi?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
            ?: Int.MIN_VALUE
        val statusInt = bi?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val plugged = bi?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0

        // ---------- 电量 ----------
        val rootCap = num(bat["capacity"])
        val batteryPct = if (!rootCap.isNaN() && rootCap >= 0) rootCap.toInt() else sysPct

        // ---------- 电压 ----------
        val rootVoltMv = uVtoMv(num(bat["voltage_now"]))
        val voltageMv = if (!rootVoltMv.isNaN() && rootVoltMv > 1000) rootVoltMv.toInt() else sysVoltMv

        // ---------- 电流 ----------
        val rootCurMa = uAtoMa(num(bat["current_now"]))
        val apiCurUa = intProp(bm, BatteryManager.BATTERY_PROPERTY_CURRENT_NOW)
        val apiCurAvgUa = intProp(bm, BatteryManager.BATTERY_PROPERTY_CURRENT_AVERAGE)
        val rootCurAvgMa = uAtoMa(num(bat["current_avg"]))
        val currentMa: Double
        val battSrc: String
        when {
            !rootCurMa.isNaN() && Math.abs(rootCurMa) > 1.0 -> {
                currentMa = rootCurMa; battSrc = "sysfs"
            }
            apiCurUa != Int.MIN_VALUE && apiCurUa != 0 -> {
                currentMa = apiCurUa / 1000.0; battSrc = "api_now"
            }
            apiCurAvgUa != Int.MIN_VALUE && apiCurAvgUa != 0 -> {
                currentMa = apiCurAvgUa / 1000.0; battSrc = "api_avg"
            }
            !rootCurAvgMa.isNaN() && Math.abs(rootCurAvgMa) > 0.1 -> {
                currentMa = rootCurAvgMa; battSrc = "sysfs_avg"
            }
            else -> {
                currentMa = 0.0; battSrc = "none"
            }
        }

        // ---------- 库仑计 ----------
        val rootCc = num(bat["charge_counter"])
        val apiCc = intProp(bm, BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER)
        val chargeUah = when {
            !rootCc.isNaN() -> rootCc.toLong()
            apiCc != Int.MIN_VALUE -> apiCc.toLong()
            else -> -1L
        }

        // ---------- 温度 ----------
        val rootTemp = rawTempToC(num(bat["temp"]))
        val battTempC = when {
            !rootTemp.isNaN() && rootTemp > 0 -> rootTemp
            sysTempTenth != Int.MIN_VALUE && sysTempTenth > 0 -> sysTempTenth / 10.0
            else -> Double.NaN
        }

        val statusStr = bat["status"]?.takeIf { it.isNotEmpty() } ?: statusName(statusInt)
        val charging = plugged != 0 || statusInt == BatteryManager.BATTERY_STATUS_CHARGING ||
            statusInt == BatteryManager.BATTERY_STATUS_FULL

        // 功率带符号：负值 = 放电，正值 = 充电
        val powerW = (voltageMv / 1000.0) * (currentMa / 1000.0)

        // ---------- CPU 频率 ----------
        var cpuAvgMhz = Double.NaN
        var cpuSrc = "none"
        val rootFreqs = cpuf.values.map { num(it) / 1000.0 }.filter { !it.isNaN() && it > 0 }
        if (rootFreqs.isNotEmpty()) {
            cpuAvgMhz = rootFreqs.average(); cpuSrc = "sysfs"
        } else {
            val f = Sysfs.cpuFreqMhz()
            if (f.isNotEmpty()) {
                cpuAvgMhz = f.average(); cpuSrc = "sysfs_file"
            }
        }

        // ---------- GPU 频率 ----------
        var gpuMhz = Double.NaN
        for (l in gpuLines) {
            val m = freqToMhz(num(l))
            if (!m.isNaN() && m > 0) {
                gpuMhz = m
                break
            }
        }
        if (gpuMhz.isNaN()) gpuMhz = Sysfs.gpuMhz()

        // ---------- 热区 ----------
        var maxC = Double.NaN
        var maxType = ""
        var socC = Double.NaN
        var thzCount = 0
        if (thermalRoot.isNotEmpty()) {
            for ((k, v) in thermalRoot) {
                val c = rawTempToC(num(v))
                if (c.isNaN() || c <= 0.0 || c > 150.0) continue
                thzCount++
                if (maxC.isNaN() || c > maxC) {
                    maxC = c
                    maxType = k
                }
                if (isSocZone(k)) {
                    if (socC.isNaN() || c > socC) socC = c
                }
            }
        }
        if (thzCount == 0) {
            val zones = Sysfs.thermalZones()
            thzCount = zones.size
            for (z in zones) {
                val c = z.second
                if (maxC.isNaN() || c > maxC) {
                    maxC = c
                    maxType = z.first
                }
                if (isSocZone(z.first)) {
                    if (socC.isNaN() || c > socC) socC = c
                }
            }
        }

        // ---------- 热状态（官方分级） ----------
        val thStatus = if (Build.VERSION.SDK_INT >= 29) {
            try {
                pm?.currentThermalStatus ?: -1
            } catch (e: Exception) {
                -1
            }
        } else {
            -1
        }

        // ---------- 前台应用 ----------
        var fgPkg = ""
        var fgSrc = "none"
        val m = PKG_RE.find(fgLine)
        if (m != null) {
            fgPkg = m.groupValues[1]
            fgSrc = "dumpsys"
        } else {
            val u = Usage.lastForegroundPkg(ctx)
            if (u.isNotEmpty()) {
                fgPkg = u
                fgSrc = "usage"
            }
        }

        // ---------- 屏幕 ----------
        val screenOn = if (scLine.isNotEmpty()) {
            scLine.contains("Awake") || scLine.contains("true")
        } else {
            try {
                pm?.isInteractive ?: false
            } catch (e: Exception) {
                false
            }
        }

        val cpuLoad = readCpuLoadPct()

        // ---------- 来源标记 ----------
        val src = StringBuilder("batt=").append(battSrc)
        src.append(";thz=").append(if (thzCount > 0) "sysfs" else "none")
        src.append(";cpu=").append(cpuSrc)
        src.append(";gpu=").append(if (gpuMhz.isNaN()) "none" else "sysfs")
        src.append(";fg=").append(fgSrc)
        src.append(";ch=").append(if (rootOk) "root" else "api")

        val ts = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date())

        return Sample(
            tsIso = ts,
            elapsedSec = elapsedSec,
            scenario = scenario,
            seq = seq,
            batteryPct = batteryPct,
            voltageMv = voltageMv,
            currentMa = nz(currentMa),
            battTempC = nz(battTempC),
            chargeUah = chargeUah,
            status = statusStr,
            powerW = nz(powerW),
            cpuAvgMhz = nz(cpuAvgMhz),
            cpuLoadPct = nz(cpuLoad),
            gpuMhz = nz(gpuMhz),
            thermalMaxC = nz(maxC),
            thermalMaxType = maxType,
            socThermalC = nz(socC),
            foregroundPkg = fgPkg,
            screenOn = screenOn,
            charging = charging,
            dataSource = src.toString(),
            thermalStatus = thermalStatusName(thStatus),
            isFinal = isFinal
        )
    }

    // ---------------- 解析辅助 ----------------

    private fun isSocZone(name: String): Boolean {
        val k = name.lowercase(Locale.US)
        return k.contains("soc") || k.contains("cpu") || k.contains("cluster") ||
            k.contains("gpu") || k.contains("ap_") || k.endsWith("_ap")
    }

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
                map[cur]?.add(line)
            }
        }
        return map
    }

    private fun kvOf(lines: List<String>?): Map<String, String> {
        val map = HashMap<String, String>()
        if (lines != null) {
            for (l in lines) {
                val i = l.indexOf('=')
                if (i > 0) map[l.substring(0, i).trim()] = l.substring(i + 1).trim()
            }
        }
        return map
    }

    private fun intProp(bm: BatteryManager?, prop: Int): Int {
        if (bm == null) return Int.MIN_VALUE
        return try {
            bm.getIntProperty(prop)
        } catch (e: Exception) {
            Int.MIN_VALUE
        }
    }

    private fun num(s: String?): Double {
        if (s == null) return Double.NaN
        val t = s.trim()
        if (t.isEmpty()) return Double.NaN
        return t.toDoubleOrNull() ?: Double.NaN
    }

    private fun nz(v: Double): Double = if (v.isNaN() || v.isInfinite()) 0.0 else v

    private fun uAtoMa(v: Double): Double {
        if (v.isNaN()) return Double.NaN
        return if (Math.abs(v) > 20000.0) v / 1000.0 else v
    }

    private fun uVtoMv(v: Double): Double {
        if (v.isNaN()) return Double.NaN
        return if (Math.abs(v) > 100000.0) v / 1000.0 else v
    }

    private fun rawTempToC(v: Double): Double = Sysfs.rawTempToC(v)

    private fun freqToMhz(v: Double): Double = Sysfs.freqToMhz(v)

    private fun statusName(code: Int): String = when (code) {
        BatteryManager.BATTERY_STATUS_CHARGING -> "charging"
        BatteryManager.BATTERY_STATUS_DISCHARGING -> "discharging"
        BatteryManager.BATTERY_STATUS_FULL -> "full"
        BatteryManager.BATTERY_STATUS_NOT_CHARGING -> "not_charging"
        else -> "unknown"
    }

    private fun thermalStatusName(code: Int): String = when (code) {
        0 -> "NONE"
        1 -> "LIGHT"
        2 -> "MODERATE"
        3 -> "SEVERE"
        4 -> "CRITICAL"
        5 -> "EMERGENCY"
        6 -> "SHUTDOWN"
        else -> "NA"
    }

    /**
     * 整机 CPU 占用率：读 /proc/stat（全局可读）两次差分。
     * 100ms 间隔是精度与采样耗时的折中，太短噪声大，太长会拖慢采样节奏。
     */
    private fun readCpuLoadPct(): Double {
        val a = readCpuStat()
        if (a.isEmpty()) return Double.NaN
        try {
            Thread.sleep(100)
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
            val f = File("/proc/stat")
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
