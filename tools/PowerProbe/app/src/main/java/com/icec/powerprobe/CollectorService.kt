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
import java.io.File
import java.util.Locale

/**
 * 采集 + 自动化编排的前台服务。
 *
 * 为什么必须前台服务 + PARTIAL_WAKE_LOCK：
 * 「待机」工况要求灭屏 30 分钟连续采样，普通后台服务会被系统冻结，定时器停摆，
 * 时间序列出现大段空洞。前台服务 + WakeLock 是「30 个采样点一个不少」的前提。
 *
 * 为什么按绝对时刻调度：
 * 单次采样本身要 200~500ms，若每次只延时固定间隔，误差会累积到分钟级。
 * 这里按 startAt + seq*interval 计算绝对时刻。
 *
 * 与上一版的差别：支持「工况队列」，一次启动可以连续跑完 IDLE → SVIDEO → NAVCAM → GAME，
 * 每个工况开始时自动拉起对应 App、结束时自动 force-stop 并归档，中间不需要人干预。
 */
class CollectorService : Service() {

    companion object {
        const val ACTION_START = "com.icec.powerprobe.action.START"
        const val ACTION_STOP = "com.icec.powerprobe.action.STOP"
        const val EXTRA_SCENARIO = "scenario"
        const val EXTRA_MINUTES = "minutes"
        const val EXTRA_INTERVAL = "interval"
        const val EXTRA_CHAIN = "chain"
        const val EXTRA_GAP = "gap_min"
        private const val CHANNEL_ID = "powerprobe_collect"
        private const val NOTIF_ID = 1001
    }

    private var thread: HandlerThread? = null
    private var handler: Handler? = null
    private var wakeLock: PowerManager.WakeLock? = null

    private val queue = ArrayList<String>()
    private var chainTotal = 1
    private var gapMin = 0
    private var targets = Targets()

    private var currentScenario = ""
    private var startAt = 0L
    private var minutes = Plan.SCENARIO_MINUTES
    private var intervalMin = Plan.SAMPLE_INTERVAL_MIN

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
            abortAll()
            return START_NOT_STICKY
        }

        val chain = intent?.getBooleanExtra(EXTRA_CHAIN, false) ?: false
        gapMin = intent?.getIntExtra(EXTRA_GAP, 0) ?: 0
        val scenario = intent?.getStringExtra(EXTRA_SCENARIO) ?: Plan.SC_IDLE
        minutes = intent?.getIntExtra(EXTRA_MINUTES, Plan.SCENARIO_MINUTES) ?: Plan.SCENARIO_MINUTES
        intervalMin = intent?.getIntExtra(EXTRA_INTERVAL, Plan.SAMPLE_INTERVAL_MIN)
            ?: Plan.SAMPLE_INTERVAL_MIN

        if (running) {
            CollectorState.log("已有任务在执行，忽略本次启动")
            return START_NOT_STICKY
        }

        queue.clear()
        if (chain) queue.addAll(Plan.queue) else queue.add(scenario)
        chainTotal = queue.size

        CollectorState.reset()
        targets = Plan.autofill(this)
        running = true
        startForeground(NOTIF_ID, buildNotification("准备开始 · 共 " + chainTotal + " 个工况"))
        acquireWake()
        CollectorState.log("设备: " + CollectorState.deviceLine)
        CollectorState.log(
            "执行通道: " + if (Root.ensure()) "root 只读直读（系统节点 + dumpsys）" else "公共 API（无 root）"
        )
        CollectorState.log(
            "目标应用: 视频=" + lbl(targets.video) + " 游戏=" + lbl(targets.game) +
                " 导航=" + lbl(targets.map)
        )
        CollectorState.log(
            "计划: " + queue.joinToString(" → ") + "，每工况 " + minutes + " 分钟，每 " +
                intervalMin + " 分钟采样"
        )
        beginNext()
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        handler?.removeCallbacksAndMessages(null)
        thread?.quitSafely()
        releaseWake()
        super.onDestroy()
    }

    // ---------------- 编排 ----------------

    private fun beginNext() {
        if (queue.isEmpty()) {
            finishAll()
            return
        }
        val sc = queue.removeAt(0)
        beginScenario(sc)
    }

    private fun beginScenario(scenario: String) {
        currentScenario = scenario
        CollectorState.clearSamples()
        CollectorState.scenario = scenario
        CollectorState.phase = CollectorState.PHASE_RUNNING
        CollectorState.totalPoints = if (intervalMin > 0) minutes / intervalMin else 1
        CollectorState.donePoints = 0
        CollectorState.elapsedSec = 0L

        val idx = chainTotal - queue.size
        CollectorState.log(
            "===== [" + idx + "/" + chainTotal + "] 开始 " + Exporter.scenarioName(scenario) +
                " · " + minutes + " 分钟 ====="
        )
        updateNotification(idx, chainTotal, scenario)

        Automator.kickoff(this, scenario, targets)

        startAt = SystemClock.elapsedRealtime()
        val st = newSampleTask()
        sampleRunnable = st
        handler?.post(st)
        handler?.post(automationTask)
    }

    private var sampleRunnable: Runnable? = null

    /** 每个工况新建一个采样任务：序号必须从 0 重新计数，不能复用上一工况的实例 */
    private fun newSampleTask(): Runnable = object : Runnable {
        private var seq = 0

        override fun run() {
            if (!running) return
            val elapsedSec = (SystemClock.elapsedRealtime() - startAt) / 1000L
            try {
                val s = Sampler.collect(this@CollectorService, currentScenario, seq, elapsedSec, false)
                CollectorState.addSample(s)
                CollectorState.latest = s
                CollectorState.donePoints = seq + 1
                CollectorState.elapsedSec = elapsedSec
                CollectorState.log(
                    String.format(
                        Locale.US,
                        "采样 #%d  t=%dmin  电量 %d%%  %.0f mA  %.1f ℃  前台 %s",
                        seq + 1, elapsedSec / 60, s.batteryPct, s.currentMa, s.battTempC,
                        if (s.foregroundPkg.isEmpty()) "-" else s.foregroundPkg
                    )
                )
            } catch (e: Exception) {
                CollectorState.log("采样异常: " + e.message)
            }

            seq++
            val total = CollectorState.totalPoints
            if (seq >= total) {
                completeScenario()
            } else {
                val intervalMs = intervalMin * 60000L
                val dueAt = startAt + seq * intervalMs
                var delay = dueAt - SystemClock.elapsedRealtime()
                if (delay < 0L) delay = 0L
                CollectorState.nextSampleInSec = delay / 1000L
                handler?.postDelayed(this, delay)
            }
        }
    }

    private val automationTask = object : Runnable {
        override fun run() {
            if (!running) return
            val el = (SystemClock.elapsedRealtime() - startAt) / 1000L
            try {
                Automator.tick(this@CollectorService, currentScenario, el, targets)
            } catch (e: Exception) {
                CollectorState.log("自动化动作异常: " + e.message)
            }
            handler?.postDelayed(this, 20000L)
        }
    }

    private fun completeScenario() {
        handler?.removeCallbacks(automationTask)
        sampleRunnable?.let { handler?.removeCallbacks(it) }
        sampleRunnable = null
        running = false

        CollectorState.log("工况 " + Exporter.scenarioName(currentScenario) + " 采样点已全部完成，补记收尾样本")
        try {
            val tail = Sampler.collect(
                this, currentScenario, -1,
                (SystemClock.elapsedRealtime() - startAt) / 1000L, true
            )
            CollectorState.addSample(tail)
            CollectorState.latest = tail
        } catch (e: Exception) {
            CollectorState.log("收尾采样异常: " + e.message)
        }

        Automator.teardown(this, targets)
        saveArtifacts(currentScenario)

        running = true
        if (queue.isEmpty()) {
            handler?.postDelayed({ beginNext() }, 3000L)
        } else if (gapMin > 0) {
            // 合规模式：工况之间留出冷却窗口。充电仍需人工插线，但冷却计时与
            // 下一工况的启动不再需要人盯着。
            CollectorState.log(
                "进入冷却窗口 " + gapMin + " 分钟：请插线充到 80% 后拔线，" +
                    "电池温度回落到 32℃ 以下后下一工况将自动开始"
            )
            try {
                val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
                nm.notify(
                    NOTIF_ID,
                    buildNotification("冷却中 " + gapMin + " 分钟 · 请充电至 80% 并拔线")
                )
            } catch (e: Exception) {
            }
            handler?.postDelayed({ beginNext() }, gapMin * 60000L)
        } else {
            handler?.postDelayed({ beginNext() }, 3000L)
        }
    }

    private fun finishAll() {
        running = false
        CollectorState.log("全部工况完成，产物已归档")
        CollectorState.phase = CollectorState.PHASE_DONE
        releaseWake()
        try {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } catch (e: Exception) {
        }
        stopSelf()
    }

    private fun abortAll() {
        handler?.removeCallbacksAndMessages(null)
        if (running && currentScenario.isNotEmpty()) {
            saveArtifacts(currentScenario)
        }
        running = false
        queue.clear()
        CollectorState.phase = CollectorState.PHASE_DONE
        releaseWake()
        try {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } catch (e: Exception) {
        }
        stopSelf()
    }

    // ---------------- 归档 ----------------

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
            CollectorState.log("CSV  → " + csv.name)
            CollectorState.log("报告 → " + md.name)
            val n = Exporter.publishToDownloads(this, listOf(csv, md))
            if (n > 0) {
                CollectorState.log("已导出 " + n + " 个文件到 Download/PowerProbe/")
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
            // 四工况连续跑最多 4 小时，留 5 小时余量
            wl.acquire(5L * 60L * 60L * 1000L)
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

    private fun updateNotification(idx: Int, total: Int, scenario: String) {
        try {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.notify(
                NOTIF_ID,
                buildNotification(
                    "[" + idx + "/" + total + "] " + Exporter.scenarioName(scenario) + " 采集中"
                )
            )
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

    private fun lbl(pkg: String): String {
        if (pkg.isEmpty()) return "(未选择)"
        return try {
            val ai = packageManager.getApplicationInfo(pkg, 0)
            packageManager.getApplicationLabel(ai).toString()
        } catch (e: Exception) {
            pkg
        }
    }
}
