package com.icec.powerprobe

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.util.Locale

/**
 * 唯一界面。四个工况按钮各启动一次 30 分钟采集，进度与日志实时刷新。
 * 不引入任何 UI 框架（AppCompat / Compose），减少依赖面，CI 编译更稳。
 */
class MainActivity : Activity() {

    private lateinit var statusView: TextView
    private lateinit var logView: TextView
    private lateinit var scroll: ScrollView
    private val ui = Handler(Looper.getMainLooper())

    private val ticker = object : Runnable {
        override fun run() {
            render()
            ui.postDelayed(this, 1500L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildUi())
        requestNotificationPermission()
        render()
    }

    override fun onResume() {
        super.onResume()
        ui.removeCallbacks(ticker)
        ui.post(ticker)
    }

    override fun onPause() {
        super.onPause()
        ui.removeCallbacks(ticker)
    }

    // ---------------- UI ----------------

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density + 0.5f).toInt()

    private fun tv(text: String, sizeSp: Float, color: Int, bold: Boolean): TextView {
        val t = TextView(this)
        t.text = text
        t.setTextSize(sizeSp)
        t.setTextColor(color)
        if (bold) t.setTypeface(t.typeface, Typeface.BOLD)
        return t
    }

    private fun buildUi(): ScrollView {
        val root = LinearLayout(this)
        root.orientation = LinearLayout.VERTICAL
        root.setBackgroundColor(Color.parseColor("#FFFFFF"))
        root.setPadding(dp(18), dp(24), dp(18), dp(40))

        root.addView(tv("PowerProbe", 26f, Color.parseColor("#111827"), true))
        val sub = tv("课题 02 · 4 工况 × 30 分钟 × 每 5 分钟 1 个采样点", 12f, Color.parseColor("#6B7280"), false)
        sub.setPadding(0, dp(4), 0, 0)
        root.addView(sub)

        // 状态卡
        val card = LinearLayout(this)
        card.orientation = LinearLayout.VERTICAL
        card.setBackgroundColor(Color.parseColor("#F3F4F6"))
        card.setPadding(dp(14), dp(12), dp(14), dp(12))
        statusView = tv("", 13f, Color.parseColor("#111827"), false)
        statusView.setLineSpacing(dp(3), 1.0f)
        card.addView(statusView)
        val cardLp = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        )
        cardLp.topMargin = dp(18)
        root.addView(card, cardLp)

        // 工况标题
        val sec1 = tv("① 选择工况并开始采集", 13f, Color.parseColor("#374151"), true)
        sec1.setPadding(0, dp(22), 0, dp(8))
        root.addView(sec1)

        root.addView(buttonRow(
            scenarioButton("待机 30min", "IDLE"),
            scenarioButton("短视频 30min", "SVIDEO")
        ))
        root.addView(buttonRow(
            scenarioButton("导航/拍摄", "NAVCAM"),
            scenarioButton("高帧率游戏", "GAME")
        ))

        // 控制
        val sec2 = tv("② 控制与归档", 13f, Color.parseColor("#374151"), true)
        sec2.setPadding(0, dp(20), 0, dp(8))
        root.addView(sec2)

        val stop = Button(this)
        stop.text = "提前结束（自动归档已采数据）"
        stop.isAllCaps = false
        stop.setTextColor(Color.parseColor("#B91C1C"))
        stop.setBackgroundColor(Color.parseColor("#FEE2E2"))
        stop.setOnClickListener { stopScenario() }
        root.addView(stop, fullWidth(dp(8)))

        val publish = Button(this)
        publish.text = "再次复制产物到 /sdcard/Download/PowerProbe"
        publish.isAllCaps = false
        publish.setTextColor(Color.parseColor("#1F2937"))
        publish.setBackgroundColor(Color.parseColor("#E5E7EB"))
        publish.setOnClickListener {
            val out = Exporter.publishToDownloads(this)
            Toast.makeText(
                this,
                if (out.isNotEmpty()) "已复制" else "未找到产物文件",
                Toast.LENGTH_SHORT
            ).show()
        }
        root.addView(publish, fullWidth(dp(4)))

        // 日志
        val sec3 = tv("③ 运行日志", 13f, Color.parseColor("#374151"), true)
        sec3.setPadding(0, dp(20), 0, dp(8))
        root.addView(sec3)

        logView = tv("", 11f, Color.parseColor("#4B5563"), false)
        logView.setLineSpacing(dp(2), 1.0f)
        logView.setPadding(dp(10), dp(10), dp(10), dp(10))
        logView.setBackgroundColor(Color.parseColor("#0B1020"))
        logView.setTextColor(Color.parseColor("#D1D5DB"))
        logView.setTypeface(Typeface.MONOSPACE)
        root.addView(logView, fullWidth(dp(12)))

        // 说明
        val note = tv(
            "数据落点：\n" +
                "/sdcard/Android/data/com.icec.powerprobe/files/PowerProbe/ （原始目录）\n" +
                "/sdcard/Download/PowerProbe/ （root 复制，便于用文件管理器取出）\n\n" +
                "采集期间请保持本应用在前台服务运行状态，不要手动清理后台；\n" +
                "「待机」工况请灭屏放置，「游戏」工况请保持游戏在前台，\n" +
                "前台包名会写入 CSV，作为工况真实性的客观证据。",
            11f, Color.parseColor("#6B7280"), false
        )
        note.setLineSpacing(dp(3), 1.0f)
        note.setPadding(0, dp(20), 0, 0)
        root.addView(note)

        scroll = ScrollView(this)
        scroll.addView(root)
        return scroll
    }

    private fun fullWidth(topMarginDp: Int): LinearLayout.LayoutParams {
        val lp = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        )
        lp.topMargin = dp(topMarginDp)
        return lp
    }

    private fun buttonRow(vararg buttons: Button): LinearLayout {
        val row = LinearLayout(this)
        row.orientation = LinearLayout.HORIZONTAL
        val rowLp = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        )
        rowLp.topMargin = dp(6)
        row.layoutParams = rowLp
        for (b in buttons) {
            val lp = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            lp.rightMargin = dp(6)
            row.addView(b, lp)
        }
        return row
    }

    private fun scenarioButton(label: String, code: String): Button {
        val b = Button(this)
        b.text = label
        b.isAllCaps = false
        b.setTextSize(13f)
        b.setTextColor(Color.WHITE)
        b.setBackgroundColor(Color.parseColor("#1F2937"))
        b.setOnClickListener { startScenario(code) }
        return b
    }

    // ---------------- 行为 ----------------

    private fun startScenario(code: String) {
        val i = Intent(this, CollectorService::class.java)
        i.action = CollectorService.ACTION_START
        i.putExtra(CollectorService.EXTRA_SCENARIO, code)
        i.putExtra(CollectorService.EXTRA_MINUTES, 30)
        i.putExtra(CollectorService.EXTRA_INTERVAL, 5)
        try {
            startForegroundService(i)
            Toast.makeText(
                this,
                "已开始：" + Exporter.scenarioName(code) + "，30 分钟 6 个采样点",
                Toast.LENGTH_SHORT
            ).show()
        } catch (e: Exception) {
            Toast.makeText(this, "启动失败：" + e.message, Toast.LENGTH_LONG).show()
        }
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
        if (!::statusView.isInitialized) return

        val phase = when (CollectorState.phase) {
            CollectorState.PHASE_RUNNING -> "采集中"
            CollectorState.PHASE_DONE -> "已完成"
            else -> "空闲"
        }

        val sb = StringBuilder()
        sb.append("阶段　").append(phase)
        if (CollectorState.scenario.isNotEmpty()) {
            sb.append("　·　").append(Exporter.scenarioName(CollectorState.scenario))
        }
        sb.append("\n")

        if (CollectorState.phase == CollectorState.PHASE_RUNNING) {
            sb.append("进度　").append(CollectorState.donePoints)
                .append(" / ").append(CollectorState.totalPoints).append(" 个采样点\n")
            val m = CollectorState.elapsedSec / 60
            val s = CollectorState.elapsedSec % 60
            sb.append("已用　").append(String.format(Locale.US, "%d 分 %02d 秒", m, s))
            if (CollectorState.nextSampleInSec > 0) {
                val nm = CollectorState.nextSampleInSec / 60
                val ns = CollectorState.nextSampleInSec % 60
                sb.append("　下一个点 ").append(String.format(Locale.US, "%d:%02d", nm, ns))
            }
            sb.append("\n")
        }

        val latest = CollectorState.latest
        if (latest != null) {
            sb.append("最新　").append(latest.batteryPct).append("%")
                .append("　").append(String.format(Locale.US, "%.0f mA", latest.currentMa))
                .append("　").append(String.format(Locale.US, "%.1f ℃", latest.battTempC))
                .append("　").append(String.format(Locale.US, "%.2f W", latest.powerW))
                .append("\n")
            sb.append("前台　").append(if (latest.foregroundPkg.isEmpty()) "未捕获" else latest.foregroundPkg)
                .append("　root ").append(if (latest.rootOk) "OK" else "不可用")
                .append("\n")
        }

        if (CollectorState.lastCsvPath.isNotEmpty()) {
            sb.append("\nCSV：").append(shortPath(CollectorState.lastCsvPath)).append("\n")
            sb.append("报告：").append(shortPath(CollectorState.lastReportPath))
        }

        statusView.text = sb.toString()

        val t = CollectorState.logText()
        logView.text = if (t.length > 6000) t.substring(t.length - 6000) else t
    }

    private fun shortPath(p: String): String {
        val name = p.substringAfterLast('/')
        return name.ifEmpty { p }
    }
}
