package com.icec.powerprobe

import java.util.Locale

/**
 * 单次采样点。字段顺序与 CSV 表头严格一致，改动任一列必须同步改 CSV_HEADER。
 *
 * 设计前提：本 App 不申请 root、不 fork 任何子进程，全部数据来自 Android 公共 API。
 * 因此每个字段都可能是「读不到」，用 -1 / 0 / 空串表示不可用，由下游脚本判定，
 * 不在这里编造数值。
 */
data class Sample(
    val tsIso: String,
    val elapsedSec: Long,
    val scenario: String,
    val seq: Int,
    val batteryPct: Int,
    val voltageMv: Int,
    val currentMa: Double,
    val battTempC: Double,
    val chargeUah: Long,
    val status: String,
    val powerW: Double,
    val cpuAvgMhz: Double,
    val cpuLoadPct: Double,
    val gpuMhz: Double,
    val thermalMaxC: Double,
    val thermalMaxType: String,
    val socThermalC: Double,
    val foregroundPkg: String,
    val screenOn: Boolean,
    val charging: Boolean,
    /** 本次采样的字段来源，形如 `batt=now;thz=sysfs;fg=usage`，便于审计数据可信度 */
    val dataSource: String,
    /** PowerManager 热状态等级 NONE/LIGHT/MODERATE/SEVERE/CRITICAL/EMERGENCY/SHUTDOWN/NA */
    val thermalStatus: String,
    val isFinal: Boolean
) {
    fun toCsvLine(): String = String.format(
        Locale.US,
        "%s,%d,%s,%d,%d,%d,%.1f,%.1f,%d,%s,%.3f,%.0f,%.1f,%.0f,%.1f,%s,%.1f,%s,%d,%d,%s,%s,%d",
        tsIso,
        elapsedSec,
        scenario,
        seq,
        batteryPct,
        voltageMv,
        currentMa,
        battTempC,
        chargeUah,
        status,
        powerW,
        cpuAvgMhz,
        cpuLoadPct,
        gpuMhz,
        thermalMaxC,
        thermalMaxType,
        socThermalC,
        foregroundPkg,
        if (screenOn) 1 else 0,
        if (charging) 1 else 0,
        dataSource,
        thermalStatus,
        if (isFinal) 1 else 0
    )

    companion object {
        const val CSV_HEADER =
            "timestamp_iso,elapsed_s,scenario,seq,battery_pct,voltage_mv,current_ma,batt_temp_c," +
                "charge_uah,status,power_w,cpu_avg_mhz,cpu_load_pct,gpu_mhz,thermal_max_c," +
                "thermal_max_type,soc_thermal_c,foreground_pkg,screen_on,charging,data_source," +
                "thermal_status,is_final"
    }
}

/**
 * 进程内的采集中间状态。CollectorService 写，MainActivity 读。
 */
object CollectorState {

    const val PHASE_IDLE = "idle"
    const val PHASE_RUNNING = "running"
    const val PHASE_DONE = "done"

    @Volatile var phase: String = PHASE_IDLE
    @Volatile var scenario: String = ""
    @Volatile var totalPoints: Int = 0
    @Volatile var donePoints: Int = 0
    @Volatile var elapsedSec: Long = 0L
    @Volatile var nextSampleInSec: Long = 0L
    @Volatile var lastCsvPath: String = ""
    @Volatile var lastReportPath: String = ""
    @Volatile var latest: Sample? = null
    @Volatile var deviceLine: String = ""

    /** 工况队列进度：第几个 / 共几个 */
    @Volatile var chainIndex: Int = 0
    @Volatile var chainTotal: Int = 0
    @Volatile var gapRemainSec: Long = 0L

    private val logBuffer = StringBuilder()
    private val samples = ArrayList<Sample>()
    private val timeFmt = java.text.SimpleDateFormat("HH:mm:ss", Locale.US)

    @Synchronized
    fun log(msg: String) {
        val t = timeFmt.format(java.util.Date())
        logBuffer.append("[").append(t).append("] ").append(msg).append("\n")
        if (logBuffer.length > 12000) {
            logBuffer.delete(0, logBuffer.length - 12000)
        }
    }

    @Synchronized
    fun logText(): String = logBuffer.toString()

    @Synchronized
    fun addSample(s: Sample) {
        samples.add(s)
    }

    /** 只清样本，保留日志：多工况串联时日志要连贯，样本按工况分段 */
    @Synchronized
    fun clearSamples() {
        samples.clear()
    }

    @Synchronized
    fun snapshot(): List<Sample> = ArrayList(samples)

    @Synchronized
    fun reset() {
        samples.clear()
        logBuffer.setLength(0)
        phase = PHASE_IDLE
        scenario = ""
        totalPoints = 0
        donePoints = 0
        elapsedSec = 0L
        nextSampleInSec = 0L
        lastCsvPath = ""
        lastReportPath = ""
        latest = null
        chainIndex = 0
        chainTotal = 0
        gapRemainSec = 0L
    }
}

/**
 * 界面曲线用的瞬时缓冲。
 *
 * 与 CSV 归档严格分离：CSV 每 5 分钟一个点（对齐官网 24 组口径），
 * 这里是每 10 秒读一次电池电流/温度，**只用于画图**，不写进 CSV。
 * 这样界面有平滑曲线，但交付数据的采样口径没有被悄悄改掉。
 */
object Live {

    private const val CAP = 180  // 10 秒 × 180 = 30 分钟

    private val current = ArrayList<Float>()
    private val temp = ArrayList<Float>()

    @Synchronized
    fun push(mA: Double, tempC: Double) {
        current.add(mA.toFloat())
        temp.add(tempC.toFloat())
        while (current.size > CAP) current.removeAt(0)
        while (temp.size > CAP) temp.removeAt(0)
    }

    @Synchronized
    fun series(): Pair<List<Float>, List<Float>> = Pair(ArrayList(current), ArrayList(temp))

    @Synchronized
    fun reset() {
        current.clear()
        temp.clear()
    }
}
