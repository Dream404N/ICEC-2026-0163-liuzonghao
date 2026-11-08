package com.icec.powerprobe

import java.io.File

/**
 * 只读节点读取器。
 *
 * 明确边界：这里**没有任何** ProcessBuilder / Runtime.exec / su 调用。
 * 只是用 java.io.File 去 open() 几个系统导出的只读文本节点，能在 SELinux 策略允许的
 * 范围内读到就返回内容，被拒绝就返回空串，绝不尝试提权、绝不写任何节点。
 *
 * 之所以保留这一层：`thermal_zoneN/temp` 与部分 GPU 频率节点
 * 在很多机型上是 `0444` 全局可读的，白拿一个更细的温度源；读不到也不影响主流程，
 * 因为电池温度 / 电流 / 电量全部走 BatteryManager 的官方接口。
 */
object Sysfs {

    fun read(path: String): String {
        return try {
            val f = File(path)
            if (!f.exists() || !f.canRead() || !f.isFile) return ""
            val t = f.readText().trim()
            if (t.length > 64) t.substring(0, 64) else t
        } catch (e: Exception) {
            ""
        }
    }

    fun readNum(path: String): Double {
        val s = read(path)
        if (s.isEmpty()) return Double.NaN
        return s.toDoubleOrNull() ?: Double.NaN
    }

    /** 列出某目录下的条目名（只读目录索引，不做递归） */
    fun list(dir: String): List<String> {
        return try {
            val d = File(dir)
            if (!d.exists() || !d.isDirectory) return emptyList()
            d.list()?.toList() ?: emptyList()
        } catch (e: Exception) {
            emptyList()
        }
    }

    // ---------------- 热区 ----------------

    /** 全部热区，返回 (名称, 摄氏度) 列表；读不到返回空列表 */
    fun thermalZones(): List<Pair<String, Double>> {
        val out = ArrayList<Pair<String, Double>>()
        val names = list("/sys/class/thermal").filter { it.startsWith("thermal_zone") }
        for (n in names) {
            val base = "/sys/class/thermal/" + n
            val type = read(base + "/type").ifEmpty { n }
            val c = rawTempToC(readNum(base + "/temp"))
            if (!c.isNaN() && c > 0.0 && c < 150.0) {
                out.add(Pair(type, c))
            }
            if (out.size >= 40) break
        }
        return out
    }

    // ---------------- CPU / GPU ----------------

    /** 各核当前频率（MHz），读不到返回空列表 */
    fun cpuFreqMhz(): List<Double> {
        val out = ArrayList<Double>()
        val cpus = list("/sys/devices/system/cpu").filter { Regex("cpu\\d+").matches(it) }
        for (c in cpus.sorted()) {
            val khz = readNum("/sys/devices/system/cpu/" + c + "/cpufreq/scaling_cur_freq")
            if (!khz.isNaN() && khz > 0) {
                out.add(khz / 1000.0)
            }
        }
        return out
    }

    /** GPU 当前频率（MHz）。不同 SoC 节点路径完全不同，逐个试，读不到就 NaN */
    fun gpuMhz(): Double {
        val candidates = listOf(
            // 高通 Adreno
            "/sys/class/kgsl/kgsl-3d0/gpuclk",
            "/sys/class/kgsl/kgsl-3d0/devfreq/cur_freq",
            // ARM Mali
            "/sys/class/misc/mali0/device/clock",
            "/sys/class/misc/mali0/device/devfreq/cur_freq",
            // 部分平台通用
            "/sys/kernel/gpu/gpu_clock",
            "/sys/kernel/gpu/gpu_freq",
            "/proc/gpufreq/gpufreq_opp_freq",
            "/proc/gpufreqv2/stack_working_opp",
            // 联发科
            "/sys/kernel/ged/hal/current_freqency"
        )
        for (p in candidates) {
            val m = freqToMhz(readNum(p))
            if (!m.isNaN() && m > 0) return m
        }
        // devfreq 下名字各异的 mali / gpu 设备
        for (d in list("/sys/class/devfreq")) {
            val low = d.lowercase()
            if (low.contains("mali") || low.contains("gpu")) {
                val m = freqToMhz(readNum("/sys/class/devfreq/" + d + "/cur_freq"))
                if (!m.isNaN() && m > 0) return m
            }
        }
        return Double.NaN
    }

    // ---------------- 归一化 ----------------

    /** sysfs 温度可能是 0.1℃ 或 0.001℃，按量级归一化 */
    fun rawTempToC(v: Double): Double {
        if (v.isNaN()) return Double.NaN
        val a = Math.abs(v)
        return when {
            a > 2000.0 -> v / 1000.0
            a > 200.0 -> v / 10.0
            else -> v
        }
    }

    /** 频率可能是 Hz / kHz / MHz，按量级归一化到 MHz */
    fun freqToMhz(v: Double): Double {
        if (v.isNaN()) return Double.NaN
        val a = Math.abs(v)
        return when {
            a > 100000000.0 -> v / 1000000.0
            a > 10000.0 -> v / 1000.0
            else -> v
        }
    }
}
