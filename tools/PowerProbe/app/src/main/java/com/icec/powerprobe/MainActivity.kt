package com.icec.powerprobe

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.color.DynamicColors
import java.util.Locale

/**
 * 主界面。
 *
 * 布局语言：大标题 + 圆角卡片 + 行内「图标 / 标题 / 副标题 / 右侧值」，
 * 与 KernelSU 一类系统工具页保持一致（Material3 + 动态取色）。
 * 注意这里是「同一套设计语言的自实现」，不是搬运 KernelSU 源码——
 * 其仓库为 GPL-3.0，直接复制会把整个项目传染成 GPL。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var statusContainer: LinearLayout
    private lateinit var automationContainer: LinearLayout
    private lateinit var scenarioContainer: LinearLayout
    private lateinit var permContainer: LinearLayout
    private lateinit var artifactContainer: LinearLayout
    private lateinit var logView: TextView
    private lateinit var spark: SparklineView

    private lateinit var vStop: TextView
    private lateinit var vChain: TextView
    private lateinit var vStatus: TextView
    private lateinit var vProgress: TextView
    private lateinit var vElapsedRow: Row
    private lateinit var vBattery: TextView
    private lateinit var vPerf: TextView
    private lateinit var vRoot: TextView
    private lateinit var vUsage: TextView
    private lateinit var vSource: TextView
    private lateinit var vVideo: TextView
    private lateinit var vGame: TextView
    private lateinit var vMap: TextView
    private lateinit var vCsv: TextView
    private lateinit var vReport: TextView

    private val ui = Handler(Looper.getMainLooper())

    private val ticker = object : Runnable {
        override fun run() {
            render()
            ui.postDelayed(this, 1500L)
        }
    }

    private class Row(val title: TextView, val subtitle: TextView, val value: TextView)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 动态取色：Android 12+ 跟随系统壁纸配色，与系统设置页观感一致。
        // 必须在 super.onCreate 之后、setContentView 之前应用，否则不会生效。
        DynamicColors.applyToActivityIfAvailable(this)
        setContentView(R.layout.activity_main)

        statusContainer = findViewById(R.id.statusContainer)
        automationContainer = findViewById(R.id.automationContainer)
        scenarioContainer = findViewById(R.id.scenarioContainer)
        permContainer = findViewById(R.id.permContainer)
        artifactContainer = findViewById(R.id.artifactContainer)
        logView = findViewById(R.id.logView)
        spark = findViewById(R.id.spark)

        buildStatusRows()
        buildAutomationRows()
        buildScenarioRows()
        buildPermRows()
        buildArtifactRows()

        requestNotificationPermission()
        // 首次启动自动探测本机已安装的候选 App，填好自动化目标
        Plan.autofill(this)
        refreshTargets()
        render()
    }

    override fun onResume() {
        super.onResume()
        ui.removeCallbacks(ticker)
        ui.post(ticker)
        refreshTargets()
    }

    override fun onPause() {
        super.onPause()
        ui.removeCallbacks(ticker)
    }

    // ---------------- 行的构建 ----------------

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density + 0.5f).toInt()

    private fun addRow(
        container: LinearLayout,
        iconRes: Int,
        title: String,
        subtitle: String,
        value: String,
        withDivider: Boolean,
        onClick: (() -> Unit)?
    ): Row {
        val rowView = layoutInflater.inflate(R.layout.item_row, container, false)
        val icon = rowView.findViewById<ImageView>(R.id.rowIcon)
        val t = rowView.findViewById<TextView>(R.id.rowTitle)
        val s = rowView.findViewById<TextView>(R.id.rowSubtitle)
        val v = rowView.findViewById<TextView>(R.id.rowValue)

        icon.setImageResource(iconRes)
        t.text = title
        if (subtitle.isEmpty()) {
            s.visibility = View.GONE
        } else {
            s.visibility = View.VISIBLE
            s.text = subtitle
        }
        if (value.isEmpty()) {
            v.visibility = View.GONE
        } else {
            v.visibility = View.VISIBLE
            v.text = value
        }

        if (onClick != null) {
            rowView.setOnClickListener { onClick() }
        } else {
            rowView.isClickable = false
            rowView.background = null
        }

        container.addView(rowView)

        if (withDivider) {
            val d = View(this)
            d.setBackgroundColor(getColor(R.color.divider))
            val lp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(1))
            lp.setMarginStart(dp(64))
            container.addView(d, lp)
        }

        return Row(t, s, v)
    }

    private fun buildStatusRows() {
        // 第一行就是停止：这是最容易找不到、又最需要一眼可见的操作
        addRow(
            statusContainer, R.drawable.ic_thermal,
            "停止并归档", "立即结束当前工况，已采数据不会丢", "空闲", true
        ) { confirmStop() }.let { vStop = it.value }

        addRow(statusContainer, R.drawable.ic_timer, "当前状态", "等待开始", "空闲", true, null)
            .let { vStatus = it.value }

        addRow(statusContainer, R.drawable.ic_file, "工况进度", "4 工况依次执行", "0 / 4", true, null)
            .let { vChain = it.value }

        addRow(statusContainer, R.drawable.ic_battery, "采样进度", "每 5 分钟一个点，共 6 点", "0 / 6", true, null)
            .let { vProgress = it.value }

        addRow(
            statusContainer, R.drawable.ic_timer, "时间",
            "已用 · 本工况剩余 · 全程剩余", "0:00 · 剩 30 分", true, null
        ).let { vElapsedRow = it }

        addRow(statusContainer, R.drawable.ic_thermal, "最新读数", "电量 · 电流 · 温度", "-", true, null)
            .let { vBattery = it.value }

        addRow(
            statusContainer, R.drawable.ic_game, "被测应用指标",
            "帧率 · 卡顿 · 进程 CPU · PSS", "-", false, null
        ).let { vPerf = it.value }
    }

    private fun buildAutomationRows() {
        addRow(
            automationContainer, R.drawable.ic_game,
            "一键全自动 · 合规", "工况间留 30 分钟冷却，按 protocol 产出可交付数据",
            "约 4 小时", true
        ) { confirmChain(30) }

        addRow(
            automationContainer, R.drawable.ic_timer,
            "一键全自动 · 连续", "4 工况连跑，用于流程验证与连续负载梯度",
            "约 2 小时", true
        ) { confirmChain(0) }

        addRow(
            automationContainer, R.drawable.ic_file,
            "短视频应用", "点按搜索选择 · 自动启动并定时翻页", "-", true
        ) { pickApp(AppPickerActivity.KIND_VIDEO) }.let { vVideo = it.value }

        addRow(
            automationContainer, R.drawable.ic_game,
            "游戏应用", "点按搜索选择 · 默认 Phigros，帧率需手动设最高", "-", true
        ) { pickApp(AppPickerActivity.KIND_GAME) }.let { vGame = it.value }

        addRow(
            automationContainer, R.drawable.ic_file,
            "导航应用", "点按搜索选择 · 默认高德，15 分钟后切相机", "-", false
        ) { pickApp(AppPickerActivity.KIND_MAP) }.let { vMap = it.value }
    }

    private fun buildScenarioRows() {
        addRow(scenarioContainer, R.drawable.ic_battery, "待机", "灭屏静置，系统基线", "30 分钟", true) {
            startScenario(Plan.SC_IDLE, false)
        }
        addRow(scenarioContainer, R.drawable.ic_game, "短视频", "自动启动 App 并翻页", "30 分钟", true) {
            startScenario(Plan.SC_SVIDEO, false)
        }
        addRow(scenarioContainer, R.drawable.ic_file, "导航 / 拍摄", "前 15 分钟导航，后 15 分钟录像", "30 分钟", true) {
            startScenario(Plan.SC_NAVCAM, false)
        }
        addRow(scenarioContainer, R.drawable.ic_game, "高帧率游戏", "自动启动游戏并保持前台", "30 分钟", false) {
            startScenario(Plan.SC_GAME, false)
        }
    }

    private fun buildPermRows() {
        addRow(
            permContainer, R.drawable.ic_battery,
            "root 通道", "只读白名单 · 点击重新探测", "-", true
        ) {
            val ok = Root.reprobe()
            Toast.makeText(
                this,
                if (ok) "root 可用：" + Root.uidLine else "未取得 root，将使用公共 API",
                Toast.LENGTH_LONG
            ).show()
            render()
        }.let { vRoot = it.value }

        addRow(
            permContainer, R.drawable.ic_file,
            "使用情况访问", "前台应用证据 · 点击去系统设置授权", "-", true
        ) { openUsageAccessSettings() }.let { vUsage = it.value }

        addRow(
            permContainer, R.drawable.ic_battery,
            "当前数据来源", "逐点记录在 CSV 的 data_source 列", "-", true, null
        ).let { vSource = it.value }

        addRow(
            permContainer, R.drawable.ic_thermal,
            "通知权限", "前台服务常驻通知，避免被系统冻结", "", false
        ) { requestNotificationPermission() }
    }

    private fun buildArtifactRows() {
        addRow(artifactContainer, R.drawable.ic_file, "最近 CSV", "raw_data 目录", "-", true, null)
            .let { vCsv = it.value }

        addRow(artifactContainer, R.drawable.ic_file, "最近报告", "设备端自动生成", "-", true, null)
            .let { vReport = it.value }

        addRow(artifactContainer, R.drawable.ic_file, "导出到 Download", "Download/PowerProbe", "", true) {
            val d = Exporter.dir(this)
            val files = (d.listFiles() ?: emptyArray()).filter {
                it.isFile && (it.name.endsWith(".csv") || it.name.endsWith(".md"))
            }
            val n = Exporter.publishToDownloads(this, files)
            Toast.makeText(
                this,
                if (n > 0) "已导出 $n 个文件" else "还没有产物文件",
                Toast.LENGTH_SHORT
            ).show()
        }

    }

    // ---------------- 自动化配置 ----------------

    private fun confirmChain(gapMin: Int) {
        val t = Plan.load(this)
        val missing = ArrayList<String>()
        if (t.video.isEmpty()) missing.add("短视频")
        if (t.game.isEmpty()) missing.add("游戏")
        if (t.map.isEmpty()) missing.add("导航")
        val warn = if (missing.isEmpty()) {
            "四个工况按 待机 → 短视频 → 导航拍摄 → 游戏 依次执行。"
        } else {
            "以下目标未选择，对应工况将只记录不加压：" + missing.joinToString("、") + "。"
        }
        val gapText = if (gapMin > 0) {
            "工况之间留 $gapMin 分钟冷却窗口，窗口内请插线充到 80% 后拔线，" +
                "计时结束自动开始下一工况。全程约 4 小时。"
        } else {
            "工况之间无间隔，连续负载。数据不含冷却复位，仅用于流程验证，" +
                "不能当作 protocol 口径的交付数据。全程约 2 小时。"
        }
        AlertDialog.Builder(this)
            .setTitle("开始全自动测试")
            .setMessage(
                warn + "\n\n" + gapText +
                    "\n\n期间不要操作手机、不要充电（冷却窗口除外）。"
            )
            .setPositiveButton("开始") { _, _ -> startScenario(Plan.SC_IDLE, true, gapMin) }
            .setNegativeButton("取消", null)
            .show()
    }

    /**
     * 打开 KSU 风格的应用选择器：常驻搜索栏 + 可搜索的已安装应用列表。
     * 旧版是 AlertDialog 里一列「名称 + 包名」，装了几十个应用就只能靠肉眼翻，
     * 这是用户明确要求改掉的地方。
     */
    private fun pickApp(kind: String) {
        val t = Plan.load(this)
        val i = Intent(this, AppPickerActivity::class.java)
        i.putExtra(AppPickerActivity.EXTRA_KIND, kind)
        i.putExtra(AppPickerActivity.EXTRA_TITLE, when (kind) {
            AppPickerActivity.KIND_VIDEO -> "选择短视频应用"
            AppPickerActivity.KIND_GAME -> "选择游戏应用"
            else -> "选择导航应用"
        })
        i.putExtra(AppPickerActivity.EXTRA_CURRENT, when (kind) {
            AppPickerActivity.KIND_VIDEO -> t.video
            AppPickerActivity.KIND_GAME -> t.game
            else -> t.map
        })
        startActivityForResult(i, REQ_PICK_APP)
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_PICK_APP || resultCode != Activity.RESULT_OK || data == null) return
        val kind = data.getStringExtra(AppPickerActivity.EXTRA_KIND) ?: return
        val pkg = data.getStringExtra(AppPickerActivity.EXTRA_PKG) ?: return
        val label = data.getStringExtra(AppPickerActivity.EXTRA_LABEL) ?: ""
        val nt = Plan.load(this).let { t ->
            when (kind) {
                AppPickerActivity.KIND_VIDEO -> t.copy(video = pkg)
                AppPickerActivity.KIND_GAME -> t.copy(game = pkg)
                AppPickerActivity.KIND_MAP -> t.copy(map = pkg)
                else -> t
            }
        }
        Plan.save(this, nt)
        refreshTargets()
        Toast.makeText(
            this,
            if (pkg.isEmpty()) "已清除选择" else "已选择：$label",
            Toast.LENGTH_SHORT
        ).show()
    }

    private fun refreshTargets() {
        val t = Plan.load(this)
        if (::vVideo.isInitialized) vVideo.text = labelOf(t.video)
        if (::vGame.isInitialized) vGame.text = labelOf(t.game)
        if (::vMap.isInitialized) vMap.text = labelOf(t.map)
    }

    private fun labelOf(pkg: String): String {
        if (pkg.isEmpty()) return "未选择"
        return try {
            val ai = packageManager.getApplicationInfo(pkg, 0)
            packageManager.getApplicationLabel(ai).toString()
        } catch (e: Exception) {
            pkg
        }
    }

    // ---------------- 行为 ----------------

    private fun startScenario(code: String, chain: Boolean, gapMin: Int = 0) {
        val i = Intent(this, CollectorService::class.java)
        i.action = CollectorService.ACTION_START
        i.putExtra(CollectorService.EXTRA_SCENARIO, code)
        i.putExtra(CollectorService.EXTRA_MINUTES, Plan.SCENARIO_MINUTES)
        i.putExtra(CollectorService.EXTRA_INTERVAL, Plan.SAMPLE_INTERVAL_MIN)
        i.putExtra(CollectorService.EXTRA_CHAIN, chain)
        i.putExtra(CollectorService.EXTRA_GAP, gapMin)
        try {
            startForegroundService(i)
            Toast.makeText(
                this,
                when {
                    chain && gapMin > 0 -> "全自动已启动：4 工况 + 冷却窗口"
                    chain -> "全自动已启动：4 工况连续"
                    else -> "已开始：" + Exporter.scenarioName(code) + " · 30 分钟"
                },
                Toast.LENGTH_SHORT
            ).show()
        } catch (e: Exception) {
            Toast.makeText(this, "启动失败：" + e.message, Toast.LENGTH_LONG).show()
        }
    }

    private fun confirmStop() {
        if (CollectorState.phase != CollectorState.PHASE_RUNNING) {
            Toast.makeText(this, "当前没有正在执行的任务", Toast.LENGTH_SHORT).show()
            return
        }
        val n = CollectorState.donePoints
        AlertDialog.Builder(this)
            .setTitle("停止并归档？")
            .setMessage(
                "立即结束当前工况，已采的 " + n + " 个采样点会写入 CSV 与报告，" +
                    "未开始的工况不再执行。"
            )
            .setPositiveButton("停止") { _, _ ->
                stopScenario()
                Toast.makeText(this, "已发送停止指令，正在归档…", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("继续跑", null)
            .show()
    }

    private fun stopScenario() {
        val i = Intent(this, CollectorService::class.java)
        i.action = CollectorService.ACTION_STOP
        try {
            startService(i)
        } catch (e: Exception) {
            Toast.makeText(this, "停止失败：" + e.message, Toast.LENGTH_LONG).show()
        }
    }

    private fun openUsageAccessSettings() {
        try {
            val i = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
            i.data = Uri.parse("package:" + packageName)
            startActivity(i)
        } catch (e: Exception) {
            try {
                startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
            } catch (e2: Exception) {
                Toast.makeText(this, "无法打开系统设置，请手动前往「使用情况访问」", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
            ) {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1001)
            }
        }
    }

    // ---------------- 渲染 ----------------

    private fun render() {
        if (!::vStatus.isInitialized) return

        val phase = when (CollectorState.phase) {
            CollectorState.PHASE_RUNNING -> "采集中 · " + Exporter.scenarioName(CollectorState.scenario)
            CollectorState.PHASE_DONE -> "已完成"
            else -> "空闲"
        }
        vStatus.text = phase
        vProgress.text = CollectorState.donePoints.toString() + " / " + CollectorState.totalPoints

        val runningNow = CollectorState.phase == CollectorState.PHASE_RUNNING
        vStop.text = if (runningNow) "运行中 · 点此停止" else "空闲"
        vStop.setTextColor(
            if (runningNow) getColor(R.color.accent_warn) else getColor(R.color.text_secondary)
        )

        vChain.text = if (CollectorState.chainTotal > 0) {
            CollectorState.chainIndex.toString() + " / " + CollectorState.chainTotal
        } else {
            "0 / 4"
        }

        val series = Live.series()
        spark.data = series.first
        spark.data2 = series.second

        val running = CollectorState.phase == CollectorState.PHASE_RUNNING
        vElapsedRow.subtitle.text = String.format(
            Locale.US, "已用 %s · 本工况 %d 分钟",
            clock(CollectorState.elapsedSec), Plan.SCENARIO_MINUTES
        )
        vElapsedRow.value.text = if (running) {
            "剩 " + span(CollectorState.remainSec) + "\n全程剩 " + clock(CollectorState.totalRemainSec)
        } else {
            "-"
        }

        val latest = CollectorState.latest
        if (latest != null) {
            vBattery.text = String.format(
                Locale.US, "%d%% · %.0f mA · %.1f℃ · %s",
                latest.batteryPct, latest.currentMa, latest.battTempC, latest.thermalStatus
            )
            vPerf.text = perfLine(latest)
        } else {
            vPerf.text = if (CollectorState.targetPkg.isEmpty()) "-" else "等待首个采样点"
        }

        vRoot.text = if (Root.available) "已授权" else "未授权"
        vRoot.setTextColor(
            if (Root.available) getColor(R.color.accent_ok) else getColor(R.color.text_secondary)
        )

        vUsage.text = if (Usage.hasAccess(this)) "已授予" else "未授予"

        val src = CollectorState.latest?.dataSource
        vSource.text = if (src.isNullOrEmpty()) {
            if (Root.available) "root 待采样" else "API 待采样"
        } else {
            shortSource(src)
        }

        vCsv.text = fileNameOf(CollectorState.lastCsvPath)
        vReport.text = fileNameOf(CollectorState.lastReportPath)

        val t = CollectorState.logText()
        logView.text = if (t.length > 6000) t.substring(t.length - 6000) else t
    }

    /** 进程级指标两行：第一行帧率/卡顿，第二行进程 CPU/内存 */
    private fun perfLine(s: Sample): String {
        if (s.appPid <= 0) {
            return if (CollectorState.targetPkg.isEmpty()) "本工况无目标应用" else "进程未运行"
        }
        val l1 = StringBuilder()
        if (s.fps >= 0) l1.append(String.format(Locale.US, "%.0f fps", s.fps)) else l1.append("- fps")
        if (s.jankPct >= 0) l1.append(String.format(Locale.US, " · 卡顿 %.1f%%", s.jankPct))
        val l2 = String.format(Locale.US, "CPU %.0f%% · %.0fMB", s.appCpuPct, s.appPssMb)
        return l1.toString() + "\n" + l2
    }

    private fun clock(sec: Long): String {
        val s = if (sec < 0) 0 else sec
        return String.format(Locale.US, "%d:%02d", s / 60, s % 60)
    }

    private fun span(sec: Long): String {
        val s = if (sec < 0) 0 else sec
        val h = s / 3600
        val m = (s % 3600) / 60
        return when {
            h > 0 -> h.toString() + " 小时 " + m + " 分"
            m > 0 -> m.toString() + " 分"
            else -> (s % 60).toString() + " 秒"
        }
    }

    private fun shortSource(src: String): String {
        // batt=sysfs;thz=sysfs;cpu=sysfs;gpu=none;fg=dumpsys;ch=root → 只显示关键两项
        val batt = partOf(src, "batt")
        val fg = partOf(src, "fg")
        val ch = partOf(src, "ch")
        return "$ch · 电流$batt · 前台$fg"
    }

    private fun partOf(src: String, key: String): String {
        for (seg in src.split(";")) {
            val i = seg.indexOf('=')
            if (i > 0 && seg.substring(0, i) == key) return seg.substring(i + 1)
        }
        return "-"
    }

    private fun fileNameOf(p: String): String {
        if (p.isEmpty()) return "-"
        val n = p.substringAfterLast('/')
        return if (n.length > 26) n.substring(0, 24) + "…" else n
    }

    companion object {
        private const val REQ_PICK_APP = 100
    }
}
