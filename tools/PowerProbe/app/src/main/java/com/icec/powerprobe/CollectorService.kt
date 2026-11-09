package com.icec.powerprobe

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
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
 * 线程模型（上一版踩过的坑）：
 * `onStartCommand` 跑在主线程，任何 `su` / `am` 调用都可能被授权弹窗阻塞十几秒。
 * 所以这里 **一进入 onStartCommand 只做状态初始化与 startForeground**，
 * 真正的编排全部 `handler.post` 到后台线程；停止流程同理（先摘定时再后台归档）。
 *
 * 通知栏是「无人值守」的核心交互面：带进度条、两个倒计时（本工况 / 全程）、
 * 采样点数与实时读数，锁屏也能一眼看出还剩多久，不需要点亮屏幕进 App。
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
        private const val CHANNEL_DONE = "powerprobe_done"
        private const val NOTIF_ID = 1001
        private const val NOTIF_DONE_ID = 1002
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

    /** 整轮计划总时长（秒），用于通知栏的总进度条 */
    private var planTotalSec = 0L

    @Volatile
    private var running = false

    /** 停止只能生效一次，避免「停止」被连点或与收尾流程重入 */
    @Volatile
    private var stopped = false

    override fun onCreate() {
        super.onCreate()
        val t = HandlerThread("powerprobe-sampler")
        t.start()
        thread = t
        handler = Handler(t.looper)
        CollectorState.deviceLine = Sampler.deviceLine()
        // 日志即刻落盘：旧版日志只在内存里，杀进程 / 卸载 / 重装一次就全没了
        CollectorState.logSink = { line ->
            Exporter.appendLog(
                this@CollectorService,
                CollectorState.sessionId.ifEmpty { "manual" },
                line
            )
        }
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
        planTotalSec = chainTotal.toLong() * minutes * 60L +
            if (gapMin > 0 && chainTotal > 1) (chainTotal - 1).toLong() * gapMin * 60L else 0L

        CollectorState.reset()
        CollectorState.sessionId = Exporter.newSessionId()
        Live.reset()
        Metrics.resetBaseline("")
        stopped = false
        // 目标应用探测要读 PackageManager，放主线程没问题；但 autofill 里没有 shell 调用
        targets = Plan.autofill(this)
        running = true
        startForeground(
            NOTIF_ID,
            buildNotification(
                "准备开始", "共 " + chainTotal + " 个工况 · 预计 " + fmtSpan(planTotalSec),
                0, listOf("即将开始 " + Exporter.scenarioName(queue.first()))
            )
        )
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
        // 关键：编排整体挪到后台线程，主线程只负责「服务已起来」
        handler?.post { beginNext() }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        handler?.removeCallbacksAndMessages(null)
        thread?.quitSafely()
        releaseWake()
        CollectorState.logSink = null
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
        CollectorState.chainIndex = idx
        CollectorState.chainTotal = chainTotal

        // 本工况的被测应用：待机工况没有前台应用，其余按工况取
        val pkg = when (scenario) {
            Plan.SC_SVIDEO -> targets.video
            Plan.SC_NAVCAM -> targets.map
            Plan.SC_GAME -> targets.game
            else -> ""
        }
        CollectorState.targetPkg = pkg
        // 清 gfxinfo 计数并重置差分基线，让本工况的 FPS/卡顿从零开始统计
        Metrics.resetBaseline(pkg)
        Metrics.lastLaunchMs = 0L

        CollectorState.log(
            "===== [" + idx + "/" + chainTotal + "] 开始 " + Exporter.scenarioName(scenario) +
                " · " + minutes + " 分钟" + if (pkg.isEmpty()) "" else " · 被测 " + lbl(pkg) + " ====="
        )

        Automator.kickoff(this, scenario, targets)

        startAt = SystemClock.elapsedRealtime()
        val st = newSampleTask()
        sampleRunnable = st
        updateEta()
        pushNotification()
        handler?.post(st)
        handler?.post(automationTask)
        handler?.post(liveTask)
        handler?.post(notifTask)
    }

    /** 界面曲线：10 秒一次轻量读取，不写 CSV */
    private val liveTask = object : Runnable {
        override fun run() {
            if (!running) return
            try {
                val p = Sampler.quick(this@CollectorService)
                if (p.first != 0.0 || p.second > 0.0) Live.push(p.first, p.second)
            } catch (e: Exception) {
            }
            handler?.postDelayed(this, 10000L)
        }
    }

    /**
     * 通知栏刷新：5 秒一次。
     *
     * 为什么单独一个任务：采样是 5 分钟一次，如果只在采样时刷通知，用户看到的「剩余时间」
     * 会以 5 分钟为步长跳变，体验很差。倒计时必须连续走，而 notify() 本身几乎无开销。
     */
    private val notifTask = object : Runnable {
        override fun run() {
            if (!running) return
            updateEta()
            pushNotification()
            handler?.postDelayed(this, 5000L)
        }
    }

    private var sampleRunnable: Runnable? = null

    /** 每个工况新建一个采样任务：序号必须从 0 重新计数，不能复用上一工况的实例 */
    private fun newSampleTask(): Runnable = object : Runnable {
        private var seq = 0

        override fun run() {
            if (!running) return
            val elapsedSec = (SystemClock.elapsedRealtime() - startAt) / 1000L
            try {
                val s = Sampler.collect(
                    this@CollectorService, currentScenario, seq, elapsedSec, false,
                    CollectorState.targetPkg
                )
                CollectorState.addSample(s)
                // 即采即落盘 + 镜像到公共 Download：哪怕中途被强杀或卸载，已采的点仍在
                Exporter.appendSample(
                    this@CollectorService, currentScenario,
                    CollectorState.sessionId, s, seq == 0
                )
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
                if (s.appPid > 0) {
                    CollectorState.log(
                        String.format(
                            Locale.US,
                            "     进程 pid=%d cpu=%.0f%% pss=%.0fMB fps=%.0f 卡顿=%.1f%% 流量↓%.0fKB",
                            s.appPid, s.appCpuPct, s.appPssMb, s.fps, s.jankPct, s.netRxKb
                        )
                    )
                }
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
                updateEta()
                pushNotification()
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
        handler?.removeCallbacks(liveTask)
        handler?.removeCallbacks(notifTask)
        sampleRunnable?.let { handler?.removeCallbacks(it) }
        sampleRunnable = null
        running = false
        if (stopped) return

        CollectorState.log("工况 " + Exporter.scenarioName(currentScenario) + " 采样点已全部完成，补记收尾样本")
        try {
            val tail = Sampler.collect(
                this, currentScenario, -1,
                (SystemClock.elapsedRealtime() - startAt) / 1000L, true
            )
            CollectorState.addSample(tail)
            Exporter.appendSample(this, currentScenario, CollectorState.sessionId, tail, false)
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
            CollectorState.gapRemainSec = gapMin * 60L
            startGapCountdown()
            handler?.postDelayed({ beginNext() }, gapMin * 60000L)
        } else {
            handler?.postDelayed({ beginNext() }, 3000L)
        }
    }

    /** 冷却窗口也走同一个通知栏：倒计时 + 提示充电，避免用户不知道下一步做什么 */
    private fun startGapCountdown() {
        val gapTask = object : Runnable {
            override fun run() {
                if (stopped || !running) return
                CollectorState.gapRemainSec -= 5L
                if (CollectorState.gapRemainSec < 0L) CollectorState.gapRemainSec = 0L
                CollectorState.remainSec = CollectorState.gapRemainSec
                CollectorState.totalRemainSec = CollectorState.gapRemainSec +
                    queue.size.toLong() * minutes * 60L
                pushNotification(gapMode = true)
                if (CollectorState.gapRemainSec > 0L) handler?.postDelayed(this, 5000L)
            }
        }
        handler?.post(gapTask)
    }

    private fun finishAll() {
        running = false
        stopped = true
        CollectorState.log("全部工况完成，产物已归档")
        CollectorState.phase = CollectorState.PHASE_DONE
        releaseWake()
        try {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } catch (e: Exception) {
        }
        notifyDone()
        stopSelf()
    }

    /**
     * 停止一律走这里。
     *
     * 两个关键点：
     * 1. 先把所有定时任务摘掉再归档，否则归档期间还会落新的采样点。
     * 2. 归档放到 handler 线程，不在主线程做文件 IO。上一版在主线程里同步写文件 +
     *    起子进程复制，一旦 su 弹窗没响应，onStartCommand 会卡十几秒，
     *    表现就是「点了停止没反应」——这是必须修掉的体验事故。
     */
    private fun abortAll() {
        if (stopped) return
        stopped = true
        running = false
        queue.clear()

        val sc = currentScenario.ifEmpty { CollectorState.scenario }
        val h = handler
        if (h == null) {
            stopSelf()
            return
        }
        h.removeCallbacksAndMessages(null)
        h.post {
            try {
                if (sc.isNotEmpty() && CollectorState.snapshot().isNotEmpty()) {
                    CollectorState.log("停止指令已确认，归档当前工况已采数据")
                    saveArtifacts(sc)
                }
            } catch (e: Exception) {
                CollectorState.log("停止归档异常: " + e.message)
            }
            CollectorState.phase = CollectorState.PHASE_DONE
            releaseWake()
            try {
                stopForeground(STOP_FOREGROUND_REMOVE)
            } catch (e: Exception) {
            }
            notifyDone()
            stopSelf()
        }
    }

    // ---------------- 倒计时与通知 ----------------

    /**
     * 两套剩余时间：
     * - remainSec：本工况还剩多久（用户最关心「这一节什么时候结束」）
     * - totalRemainSec：含后续工况与冷却窗口的整轮剩余（决定「什么时候能去干别的事」）
     */
    private fun updateEta() {
        if (startAt == 0L) return
        val el = (SystemClock.elapsedRealtime() - startAt) / 1000L
        val scTotal = minutes * 60L
        val remain = if (el >= scTotal) 0L else scTotal - el
        CollectorState.remainSec = remain
        var rest = queue.size.toLong() * scTotal
        if (gapMin > 0 && queue.isNotEmpty()) rest += queue.size.toLong() * gapMin * 60L
        CollectorState.totalRemainSec = remain + rest
        CollectorState.elapsedSec = el
    }

    private fun overallPct(): Int {
        if (planTotalSec <= 0L) return 0
        val el = (SystemClock.elapsedRealtime() - startAt) / 1000L
        val doneBefore = (CollectorState.chainIndex - 1).toLong() *
            (minutes * 60L + if (gapMin > 0) gapMin * 60L else 0L)
        val cur = if (el > minutes * 60L) minutes * 60L else el
        val p = (doneBefore + cur) * 100.0 / planTotalSec
        return p.toInt().coerceIn(0, 100)
    }

    private fun pushNotification(gapMode: Boolean = false) {
        try {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.notify(NOTIF_ID, if (gapMode) buildGapNotification() else buildRunNotification())
        } catch (e: Exception) {
        }
    }

    private fun buildRunNotification(): Notification {
        val idx = if (CollectorState.chainIndex > 0) CollectorState.chainIndex else 1
        val total = if (chainTotal > 0) chainTotal else 1
        val name = Exporter.scenarioName(CollectorState.scenario)
        val remain = CollectorState.remainSec
        val pct = overallPct()

        val title = "[" + idx + "/" + total + "] " + name + " · 剩 " + fmtClock(remain)
        val text = "采样 " + CollectorState.donePoints + "/" + CollectorState.totalPoints +
            " · 全程剩 " + fmtSpan(CollectorState.totalRemainSec) + " · " + pct + "%"

        val lines = ArrayList<String>()
        lines.add("工况 " + idx + "/" + total + " " + name + "：剩余 " + fmtSpan(remain))
        lines.add("全程剩余 " + fmtSpan(CollectorState.totalRemainSec) + "，总进度 " + pct + "%")
        lines.add(
            "采样点 " + CollectorState.donePoints + "/" + CollectorState.totalPoints +
                (if (CollectorState.nextSampleInSec > 0) "，下一" + CollectorState.nextSampleInSec / 60 +
                    " 分钟后" else "")
        )
        val s = CollectorState.latest
        if (s != null) {
            lines.add(
                String.format(
                    Locale.US, "%.0f mA · %.2f W · 电池 %.1f℃ · %s",
                    s.currentMa, s.powerW, s.battTempC, s.thermalStatus
                )
            )
            if (s.appPid > 0) {
                lines.add(
                    String.format(
                        Locale.US, "被测应用 pid %d · CPU %.0f%% · %.0fMB · %.0ffps · 卡顿 %.1f%%",
                        s.appPid, s.appCpuPct, s.appPssMb, s.fps, s.jankPct
                    )
                )
            }
        }
        return buildNotification(title, text, pct, lines)
    }

    private fun buildGapNotification(): Notification {
        val idx = CollectorState.chainIndex
        val total = if (chainTotal > 0) chainTotal else 1
        val next = if (queue.isEmpty()) "-" else Exporter.scenarioName(queue.first())
        val title = "冷却中 · 剩 " + fmtClock(CollectorState.gapRemainSec)
        val text = "请充到 80% 后拔线，温度回落后自动开始 " + next
        val lines = listOf(
            "第 " + idx + "/" + total + " 个工况已完成，冷却还剩 " + fmtSpan(CollectorState.gapRemainSec),
            "请插线充到 80% 再拔线；电池温度需回落到 32℃ 以下",
            "冷却结束自动开始：" + next
        )
        return buildNotification(title, text, overallPct(), lines)
    }

    private fun notifyDone() {
        try {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val open = PendingIntent.getActivity(
                this, 3,
                Intent(this, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val n = Notification.Builder(this, CHANNEL_DONE)
                .setContentTitle("测试结束，产物已归档")
                .setContentText(
                    "采样点 " + CollectorState.donePoints + " 组 · 文件在 Download/PowerProbe/"
                )
                .setSmallIcon(R.drawable.ic_stat_probe)
                .setColor(getColor(R.color.accent_ok))
                .setAutoCancel(true)
                .setContentIntent(open)
                .build()
            nm.notify(NOTIF_DONE_ID, n)
        } catch (e: Exception) {
        }
    }

    // ---------------- 归档 ----------------

    /**
     * 归档当前工况：CSV + 设备端 Markdown 报告，并复制一份到 Download/PowerProbe/。
     *
     * 全程在 handler 线程执行（调用方保证），不做任何 shell 调用——
     * 上一版就是在主线程里同步写文件 + `su cp`，su 弹窗一没响应就整个卡死。
     */
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
            CollectorState.log("CSV  → " + csv.name + "（" + samples.size + " 行）")
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
                CHANNEL_ID, "采集与进度", NotificationManager.IMPORTANCE_LOW
            )
            ch.setShowBadge(false)
            // 进度型通知：这条不响不震，但必须一直可见（LOW 级别本身无声无横幅）
            ch.enableVibration(false)
            ch.setSound(null, null)
            nm.createNotificationChannel(ch)

            val done = NotificationChannel(
                CHANNEL_DONE, "完成提醒", NotificationManager.IMPORTANCE_DEFAULT
            )
            done.setShowBadge(true)
            nm.createNotificationChannel(done)
        } catch (e: Exception) {
        }
    }

    /**
     * 通知里必须有「停止」——这是用户在锁屏/其他 App 里唯一能直接停下来的入口。
     * 点通知本体回到 App，点「停止并归档」直接把 ACTION_STOP 投给服务。
     */
    private fun buildNotification(
        title: String,
        text: String,
        pct: Int,
        lines: List<String>
    ): Notification {
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        val b = Notification.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_stat_probe)
            .setColor(getColor(R.color.accent_info))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setCategory(Notification.CATEGORY_PROGRESS)
            .setSubText("PowerProbe · 全自动测试")
            .setProgress(100, pct.coerceIn(0, 100), false)

        try {
            val open = PendingIntent.getActivity(
                this, 2,
                Intent(this, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                flags
            )
            b.setContentIntent(open)

            val stop = Intent(this, CollectorService::class.java).setAction(ACTION_STOP)
            val pi = PendingIntent.getService(this, 1, stop, flags)
            b.addAction(
                Notification.Action.Builder(
                    android.R.drawable.ic_menu_close_clear_cancel, "停止并归档", pi
                ).build()
            )
        } catch (e: Exception) {
        }

        val big = StringBuilder()
        for (l in lines) big.append(l).append("\n")
        b.setStyle(Notification.BigTextStyle().bigText(big.toString().trimEnd()))
        return b.build()
    }

    /** 18:24 这种写法，用于标题（一眼看清，不占宽） */
    private fun fmtClock(sec: Long): String {
        val s = if (sec < 0) 0 else sec
        return String.format(Locale.US, "%d:%02d", s / 60, s % 60)
    }

    /** 1 小时 22 分 / 18 分 24 秒，用于正文 */
    private fun fmtSpan(sec: Long): String {
        val s = if (sec < 0) 0 else sec
        val h = s / 3600
        val m = (s % 3600) / 60
        return when {
            h > 0 -> h.toString() + " 小时 " + m + " 分"
            m > 0 -> if (m >= 5) m.toString() + " 分钟" else m.toString() + " 分 " + (s % 60) + " 秒"
            else -> (s % 60).toString() + " 秒"
        }
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
