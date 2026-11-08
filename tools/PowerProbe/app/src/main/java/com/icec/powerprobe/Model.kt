package com.icec.powerprobe

import java.util.Locale

/**
 * 单次采样点。字段顺序与 CSV 表头严格一致，改动任一列必须同步改 CSV_HEADER。
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
    val rootOk: Boolean,
    val isFinal: Boolean
) {
    fun toCsvLine(): String = String.format(
        Locale.US,
        "%s,%d,%s,%d,%d,%d,%.1f,%.1f,%d,%s,%.3f,%.0f,%.1f,%.0f,%.1f,%s,%.1f,%s,%d,%d,%d,%d",
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
        if (rootOk) 1 else 0,
        if (isFinal) 1 else 0
    )

    companion object {
        const val CSV_HEADER =
            "timestamp_iso,elapsed_s,scenario,seq,battery_pct,voltage_mv,current_ma,batt_temp_c," +
                "charge_uah,status,power_w,cpu_avg_mhz,cpu_load_pct,gpu_mhz,thermal_max_c," +
                "thermal_max_type,soc_thermal_c,foreground_pkg,screen_on,charging,root_ok,is_final"
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
    }
}
