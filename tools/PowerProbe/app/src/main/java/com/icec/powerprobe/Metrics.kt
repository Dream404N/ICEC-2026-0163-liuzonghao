package com.icec.powerprobe

import android.os.SystemClock
import java.util.Locale

/**
 * 被测应用自身的性能指标。
 *
 * 为什么需要这一层：只测「整机电流 + 温度」只能回答「这台手机跑这个场景多耗电」，
 * 回答不了「这个场景到底有没有把机器压满」。行业里 Emmagee（网易）、GT（腾讯）、
 * SoloPi（阿里）都是靠「进程级 + 帧级」指标做归因的，口径可以完全对齐：
 *
 * | 指标 | 数据源 | 与开源工具的一致性 |
 * |---|---|---|
 * | app_cpu_pct | `/proc/<pid>/stat` 第 14、15 列差分（jiffies） | 与 Emmagee `CpuInfo` 同源 |
 * | app_pss_mb  | `/proc/<pid>/smaps_rollup` 的 `Pss:` | 与 GT/Emmagee 取 PSS 一致 |
 * | fps / jank  | `dumpsys gfxinfo <pkg>` 的累计帧数与 Janky 帧数差分 | 与 PerfDog 类工具的 FPS/卡顿口径同源 |
 * | net_rx/tx   | `/sys/class/net/<iface>/statistics` 累计字节差分 | 整机口径，绕过已废弃的 `uid_stat` |
 * | cpu_max_mhz | 各核 `scaling_cur_freq` 的最大值 | 用于识别热降频 |
 *
 * **差分而非瞬时**：所有计数都是累计值，必须两次读取相减才是区间均值。
 * 这也是本类保存 `last*` 状态的原因——采样间隔是 5 分钟，算出来正好是这 5 分钟的均值，
 * 与电流采样点的时间窗完全对齐，可以直接做相关性分析。
 *
 * 全部读取放在**一次** su 调用里（脚本内用 `sleep 0.9` 制造差分窗口），
 * 避免每次采样 fork 多次 su 造成进程风暴，也避免把自动化自身开销算进被测功耗。
 */
data class AppMetrics(
    val pid: Int,
    /** 目标进程 CPU，相对单核 100%（多线程可 > 100） */
    val appCpuPct: Double,
    val appPssMb: Double,
    val fps: Double,
    val jankPct: Double,
    val frameP99Ms: Double,
    val netRxKb: Double,
    val netTxKb: Double,
    val cpuMaxMhz: Double
) {
    val usable: Boolean get() = pid > 0

    companion object {
        /** 无 root / 进程未运行时的占位值，CSV 中写作 -1 以便下游识别「未采到」而非 0 */
        val NONE = AppMetrics(-1, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0)
    }
}

object Metrics {

    /** USER_HZ：Android 内核固定为 100，即 1 jiffy = 10 ms */
    private const val HZ = 100.0

    /** 低于这个窗口不做 FPS/CPU 差分：窗口太短时数字全是噪声 */
    private const val MIN_WINDOW_MS = 15000L

    private var lastTicks = -1L
    private var lastAt = 0L
    private var lastFrames = -1L
    private var lastJanky = -1L
    private var lastNetRx = -1.0
    private var lastNetTx = -1.0
    private var lastName = ""

    /** 最近一次冷启动耗时（ms），由 Automator 在 `am start -W` 后写入 */
    @Volatile
    var lastLaunchMs: Long = 0L

    /**
     * 工况开始时调用：把 gfxinfo 的累计帧数清零，让本工况的 FPS/卡顿统计从零开始。
     * 不清零的话，「自开机以来」的帧数会把上一工况的负载带进来，跨工况不可比。
     */
    fun resetBaseline(pkg: String) {
        lastTicks = -1L
        lastAt = 0L
        lastFrames = -1L
        lastJanky = -1L
        lastNetRx = -1.0
        lastNetTx = -1.0
        lastName = pkg
        if (pkg.isNotEmpty() && Root.ensure()) {
            // 只清该包的帧统计，不触碰任何用户数据
            Root.exec("dumpsys gfxinfo " + pkg + " reset", 8000)
        }
    }

    fun probe(pkg: String): AppMetrics {
        if (pkg.isEmpty() || !Root.ensure()) return AppMetrics.NONE

        val raw = Root.exec(buildScript(pkg), 15000)
        if (!raw.contains("@@END@@")) return AppMetrics.NONE
        val now = SystemClock.elapsedRealtime()
        val sec = parseSections(raw)

        val pid = sec["PID"]?.firstOrNull()?.trim()?.toIntOrNull() ?: -1
        val pss = parsePss(sec["MEM"])
        val freqs = (sec["FRQ"] ?: emptyList()).mapNotNull { it.trim().toDoubleOrNull() }
            .filter { it > 0 }
            .map { it / 1000.0 }

        // ---- 进程 CPU：两次 /proc/<pid>/stat 的 utime+stime 之差 ----
        val t1 = sumTicks(sec["T1"])
        val t2 = sumTicks(sec["T2"])
        var cpuPct = -1.0
        val dtMs = if (lastAt > 0L) now - lastAt else 0L
        if (t1 >= 0 && t2 >= 0 && t2 >= t1 && dtMs >= MIN_WINDOW_MS) {
            cpuPct = (t2 - t1).toDouble() / HZ / (dtMs / 1000.0) * 100.0
        }
        if (t2 >= 0) lastTicks = t2
        lastAt = now

        // ---- 帧率与卡顿：gfxinfo 累计计数差分 ----
        val g = parseGfx(sec["GX"])
        var fps = -1.0
        var jankPct = -1.0
        val p99 = g.third
        if (g.first >= 0) {
            if (lastFrames >= 0 && dtMs >= MIN_WINDOW_MS && g.first > lastFrames) {
                val dFrames = g.first - lastFrames
                val dJanky = if (g.second >= 0 && lastJanky >= 0) {
                    (g.second - lastJanky).coerceAtLeast(0)
                } else {
                    -1
                }
                if (dFrames >= 5) {
                    fps = dFrames.toDouble() * 1000.0 / dtMs.toDouble()
                    if (dJanky >= 0) jankPct = dJanky.toDouble() * 100.0 / dFrames.toDouble()
                }
            }
            lastFrames = g.first
            lastJanky = g.second
        }

        // ---- 网络：整机累计字节差分 ----
        val net = parseNet(sec["NET"])
        var rxKb = -1.0
        var txKb = -1.0
        if (net.first >= 0) {
            if (lastNetRx >= 0 && net.first >= lastNetRx) {
                rxKb = (net.first - lastNetRx) / 1024.0
                txKb = (net.second - lastNetTx) / 1024.0
            }
            lastNetRx = net.first
            lastNetTx = net.second
        }

        return AppMetrics(
            pid = pid,
            appCpuPct = if (cpuPct < 0) -1.0 else clip(cpuPct, 0.0, 2000.0),
            appPssMb = pss,
            fps = fps,
            jankPct = if (jankPct < 0) -1.0 else clip(jankPct, 0.0, 100.0),
            frameP99Ms = p99,
            netRxKb = rxKb,
            netTxKb = txKb,
            cpuMaxMhz = if (freqs.isEmpty()) -1.0 else freqs.maxOrNull() ?: -1.0
        )
    }

    // ---------------- 脚本 ----------------

    private fun buildScript(pkg: String): String = """
P=${'$'}(pidof $pkg 2>/dev/null)
if [ -z "${'$'}P" ]; then P=${'$'}(ps -A 2>/dev/null | grep -m1 "$pkg" | awk '{print ${'$'}2}'); fi
echo "@@PID@@"
echo "${'$'}P" | tr ' ' '\n' | grep -v '^${'$'}' | head -1
echo "@@T1@@"
for p in ${'$'}P; do awk '{print ${'$'}14+${'$'}15}' /proc/${'$'}p/stat 2>/dev/null; done
echo "@@MEM@@"
for p in ${'$'}P; do grep -m1 '^Pss:' /proc/${'$'}p/smaps_rollup 2>/dev/null; done
echo "@@GX@@"
dumpsys gfxinfo $pkg 2>/dev/null | grep -E "Total frames rendered|Janky frames:|99th percentile"
echo "@@NET@@"
for d in /sys/class/net/*; do n=${'$'}(basename ${'$'}d 2>/dev/null); if [ "${'$'}n" != "lo" ]; then r=${'$'}(cat ${'$'}d/statistics/rx_bytes 2>/dev/null); t=${'$'}(cat ${'$'}d/statistics/tx_bytes 2>/dev/null); echo "${'$'}n ${'$'}r ${'$'}t"; fi; done
echo "@@FRQ@@"
for c in 7 6 5 4 3; do cat /sys/devices/system/cpu/cpu${'$'}c/cpufreq/scaling_cur_freq 2>/dev/null; done
echo "@@SLP@@"
sleep 0.9
echo "@@T2@@"
for p in ${'$'}P; do awk '{print ${'$'}14+${'$'}15}' /proc/${'$'}p/stat 2>/dev/null; done
echo "@@END@@"
"""

    // ---------------- 解析 ----------------

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

    /** 多进程（如带子进程的 App）把 ticks 相加 */
    private fun sumTicks(lines: List<String>?): Long {
        if (lines.isNullOrEmpty()) return -1L
        var sum = 0L
        var any = false
        for (l in lines) {
            val v = l.trim().toLongOrNull() ?: continue
            sum += v
            any = true
        }
        return if (any) sum else -1L
    }

    private fun parsePss(lines: List<String>?): Double {
        if (lines.isNullOrEmpty()) return -1.0
        var kb = 0.0
        var any = false
        for (l in lines) {
            // 形如 "Pss:              123456 kB"
            val parts = l.split(Regex("\\s+"))
            for (i in parts.indices) {
                if (parts[i].equals("Pss:", ignoreCase = true)) {
                    val v = parts.getOrNull(i + 1)?.toDoubleOrNull()
                    if (v != null && v > 0) {
                        kb += v
                        any = true
                    }
                    break
                }
            }
        }
        return if (any) kb / 1024.0 else -1.0
    }

    /** @return (总帧数, 卡顿帧数, p99ms)，读不到给 -1 */
    private fun parseGfx(lines: List<String>?): Triple<Long, Long, Double> {
        var total = -1L
        var janky = -1L
        var p99 = -1.0
        if (lines != null) {
            for (l in lines) {
                val n = firstNumber(l)
                when {
                    l.contains("Total frames rendered", true) -> total = n.toLong()
                    l.contains("Janky frames", true) -> janky = n.toLong()
                    l.contains("99th percentile", true) -> p99 = n
                }
            }
        }
        return Triple(total, janky, p99)
    }

    /** @return (rxBytes, txBytes)，累加全部非 lo 接口 */
    private fun parseNet(lines: List<String>?): Pair<Double, Double> {
        if (lines.isNullOrEmpty()) return Pair(-1.0, -1.0)
        var rx = 0.0
        var tx = 0.0
        var any = false
        for (l in lines) {
            val parts = l.split(Regex("\\s+"))
            if (parts.size < 3) continue
            val r = parts[1].toDoubleOrNull() ?: continue
            val t = parts[2].toDoubleOrNull() ?: continue
            rx += r
            tx += t
            any = true
        }
        return if (any) Pair(rx, tx) else Pair(-1.0, -1.0)
    }

    /** 取一行里第一个数字（兼容 "Janky frames: 56 (4.54%)" / "99th percentile: 18ms"） */
    private fun firstNumber(line: String): Double {
        val m = Regex("-?\\d+(?:\\.\\d+)?").find(line.substringAfter(':', ""))
            ?: Regex("-?\\d+(?:\\.\\d+)?").find(line)
        return m?.value?.toDoubleOrNull() ?: -1.0
    }

    private fun clip(v: Double, lo: Double, hi: Double): Double =
        Math.max(lo, Math.min(hi, v))

    fun format(m: AppMetrics): String {
        if (!m.usable) return "-"
        val sb = StringBuilder()
        sb.append(String.format(Locale.US, "PID %d", m.pid))
        if (m.appCpuPct >= 0) sb.append(String.format(Locale.US, " · CPU %.0f%%", m.appCpuPct))
        if (m.appPssMb >= 0) sb.append(String.format(Locale.US, " · %.0fMB", m.appPssMb))
        if (m.fps >= 0) sb.append(String.format(Locale.US, " · %.0ffps", m.fps))
        return sb.toString()
    }
}
