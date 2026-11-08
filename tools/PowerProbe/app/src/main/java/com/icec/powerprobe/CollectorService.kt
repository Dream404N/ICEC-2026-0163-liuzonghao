package com.icec.powerprobe

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import java.util.Locale

/**
 * 采集前台服务。
 *
 * 为什么要前台服务 + PARTIAL_WAKE_LOCK：
 * 课题 02 的「待机」工况要求灭屏 30 分钟连续采样，普通后台服务会被系统冻结，
 * 定时器随之停摆，最终拿到的时间序列会出现大段空洞。前台服务 + WakeLock 是
 * 保证「t=0/5/10/15/20/25 分钟六个点一个不少」的前提。
 *
 * 为什么用绝对时刻调度而不是 postDelayed(间隔)：
 * 单次采样本身要 200~500ms，若每次只延时固定间隔，误差会累积，30 分钟下来
 * 最后一个点可能漂移到 26 分钟。这里按 startAt + seq*interval 计算绝对时刻。
 */
class CollectorService : Service() {

    companion object {
        const val ACTION_START = "com.icec.powerprobe.action.START"
        const val ACTION_STOP = "com.icec.powerprobe.action.STOP"
        const val EXTRA_SCENARIO = "scenario"
        const val EXTRA_MINUTES = "minutes"
        const val EXTRA_INTERVAL = "interval"
        private const val CHANNEL_ID = "powerprobe_collect"
        private const val NOTIF_ID = 1001
    }

    private var thread: HandlerThread? = null
    private var handler: Handler? = null
    private var wakeLock: PowerManager.WakeLock? = null

    @Volatile
    private var running = false

    override fun onCreate() {
        super.onCreate()
        val t = HandlerThread("powerprobe-sampler")
        t.start()
        thread = t
        handler = Handler(t.looper)
        CollectorState.deviceLine = Sampler.deviceLine()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action ?: ""

        if (action == ACTION_STOP) {
            CollectorState.log("收到停止指令，提前结束并归档已采数据")
            abortCollect()
            return START_NOT_STICKY
        }

        val scenario = intent?.getStringExtra(EXTRA_SCENARIO) ?: "IDLE"
        val minutes = intent?.getIntExtra(EXTRA_MINUTES, 30) ?: 30
        val interval = intent?.getIntExtra(EXTRA_INTERVAL, 5) ?: 5

        startForeground(NOTIF_ID, buildNotification("采集中 · " + Exporter.scenarioName(scenario)))
        acquireWake()
        beginCollect(scenario, minutes, interval)
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        handler?.removeCallbacksAndMessages(null)
        thread?.quitSafely()
        releaseWake()
        super.onDestroy()
    }

    // ---------------- 采集主流程 ----------------

    private fun beginCollect(scenario: String, minutes: Int, intervalMin: Int) {
        if (running) {
            CollectorState.log("已在采集中，忽略本次启动")
            return
        }
        running = true
        CollectorState.reset()
        CollectorState.phase = CollectorState.PHASE_RUNNING
        CollectorState.scenario = scenario
        CollectorState.deviceLine = Sampler.deviceLine()

        val total = if (intervalMin > 0) minutes / intervalMin else 6
        CollectorState.totalPoints = total
        CollectorState.log("设备: " + CollectorState.deviceLine)
        CollectorState.log(
            "开始采集 " + Exporter.scenarioName(scenario) + "：共 " + minutes +
                " 分钟，每 " + intervalMin + " 分钟 1 个采样点，计划 " + total + " 点"
        )

        val startAt = SystemClock.elapsedRealtime()
        val intervalMs = intervalMin * 60000L

        val task = object : Runnable {
            private var seq = 0

            override fun run() {
                if (!running) return
                val elapsedSec = (SystemClock.elapsedRealtime() - startAt) / 1000L
                try {
                    val s = Sampler.collect(this@CollectorService, scenario, seq, elapsedSec, false)
                    CollectorState.addSample(s)
                    CollectorState.latest = s
                    CollectorState.donePoints = seq + 1
                    CollectorState.elapsedSec = elapsedSec
                    CollectorState.log(
                        String.format(
                            Locale.US,
                            "采样 #%d  t=%dmin  电量 %d%%  %.0f mA  %.1f ℃  前台 %s  root=%s",
                            seq + 1, elapsedSec / 60, s.batteryPct, s.currentMa, s.battTempC,
                            if (s.foregroundPkg.isEmpty()) "-" else s.foregroundPkg,
                            if (s.rootOk) "Y" else "N"
                        )
                    )
                } catch (e: Exception) {
                    CollectorState.log("采样异常: " + e.message)
                }

                seq++
                if (seq >= total) {
                    finishCollect(scenario, startAt)
                } else {
                    val dueAt = startAt + seq.toLong() * intervalMs
                    var delay = dueAt - SystemClock.elapsedRealtime()
                    if (delay < 0L) delay = 0L
                    CollectorState.nextSampleInSec = delay / 1000L
                    handler?.postDelayed(this, delay)
                }
            }
        }
        handler?.post(task)
    }

    private fun finishCollect(scenario: String, startAt: Long) {
        running = false
        CollectorState.log("计划采样点已全部完成，补记收尾样本")
        try {
            val tail = Sampler.collect(
                this, scenario, -1,
                (SystemClock.elapsedRealtime() - startAt) / 1000L, true
            )
            CollectorState.addSample(tail)
            CollectorState.latest = tail
        } catch (e: Exception) {
            CollectorState.log("收尾采样异常: " + e.message)
        }
        saveArtifacts(scenario)
        CollectorState.phase = CollectorState.PHASE_DONE
        releaseWake()
        try {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } catch (e: Exception) {
        }
        stopSelf()
    }

    private fun abortCollect() {
        if (!running) {
            stopSelf()
            return
        }
        running = false
        handler?.removeCallbacksAndMessages(null)
        saveArtifacts(CollectorState.scenario)
        CollectorState.phase = CollectorState.PHASE_DONE
        releaseWake()
        try {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } catch (e: Exception) {
        }
        stopSelf()
    }

    private fun saveArtifacts(scenario: String) {
        val samples = CollectorState.snapshot()
        if (samples.isEmpty()) {
            CollectorState.log("没有采样数据，跳过导出")
            return
        }
        try {
            val csv = Exporter.writeCsv(this, scenario, samples)
            val md = Exporter.writeReport(this, scenario, samples)
            CollectorState.lastCsvPath = csv.absolutePath
            CollectorState.lastReportPath = md.absolutePath
            CollectorState.log("CSV  → " + csv.absolutePath)
            CollectorState.log("报告 → " + md.absolutePath)
            val pub = Exporter.publishToDownloads(this)
            if (pub.isNotEmpty()) {
                CollectorState.log("已复制到 /sdcard/Download/PowerProbe/")
            }
        } catch (e: Exception) {
            CollectorState.log("导出失败: " + e.message)
        }
    }

    // ---------------- 系统资源 ----------------

    private fun acquireWake() {
        if (wakeLock?.isHeld == true) return
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            val wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "PowerProbe::collect")
            wl.setReferenceCounted(false)
            wl.acquire(90L * 60L * 1000L)
            wakeLock = wl
        } catch (e: Exception) {
            CollectorState.log("WakeLock 获取失败: " + e.message)
        }
    }

    private fun releaseWake() {
        try {
            val wl = wakeLock
            if (wl != null && wl.isHeld) wl.release()
        } catch (e: Exception) {
        }
        wakeLock = null
    }

    private fun createChannel() {
        try {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val ch = NotificationChannel(
                CHANNEL_ID, "采集服务", NotificationManager.IMPORTANCE_LOW
            )
            ch.setShowBadge(false)
            nm.createNotificationChannel(ch)
        } catch (e: Exception) {
        }
    }

    private fun buildNotification(text: String): Notification {
        return Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("PowerProbe")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .build()
    }
}
