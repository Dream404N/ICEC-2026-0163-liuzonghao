package com.icec.powerprobe

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
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
    private lateinit var scenarioContainer: LinearLayout
    private lateinit var artifactContainer: LinearLayout
    private lateinit var logView: TextView

    private lateinit var vStatus: TextView
    private lateinit var vProgress: TextView
    private lateinit var vElapsed: TextView
    private lateinit var vBattery: TextView
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
        scenarioContainer = findViewById(R.id.scenarioContainer)
        artifactContainer = findViewById(R.id.artifactContainer)
        logView = findViewById(R.id.logView)

        buildStatusRows()
        buildScenarioRows()
        buildArtifactRows()

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
        addRow(statusContainer, R.drawable.ic_timer, "当前状态", "空闲时可直接选择下方工况", "空闲", true, null)
            .let { vStatus = it.value }

        addRow(statusContainer, R.drawable.ic_battery, "采样进度", "每 5 分钟一个点，共 6 点", "0 / 6", true, null)
            .let { vProgress = it.value }

        addRow(statusContainer, R.drawable.ic_timer, "已用时长", "", "0 分 00 秒", true, null)
            .let { vElapsed = it.value }

        addRow(statusContainer, R.drawable.ic_thermal, "最新读数", "电量 · 电流 · 温度", "-", false, null)
            .let { vBattery = it.value }
    }

    private fun buildScenarioRows() {
        addRow(scenarioContainer, R.drawable.ic_battery, "待机", "灭屏静置，系统基线", "30 分钟", true) {
            startScenario("IDLE")
        }
        addRow(scenarioContainer, R.drawable.ic_game, "短视频", "连续滚动播放", "30 分钟", true) {
            startScenario("SVIDEO")
        }
        addRow(scenarioContainer, R.drawable.ic_file, "导航 / 拍摄", "前半导航，后半录 4K", "30 分钟", true) {
            startScenario("NAVCAM")
        }
        addRow(scenarioContainer, R.drawable.ic_game, "高帧率游戏", "画质与帧率最高档", "30 分钟", false) {
            startScenario("GAME")
        }
    }

    private fun buildArtifactRows() {
        addRow(artifactContainer, R.drawable.ic_file, "最近 CSV", "raw_data 目录", "-", true, null)
            .let { vCsv = it.value }

        addRow(artifactContainer, R.drawable.ic_file, "最近报告", "设备端自动生成", "-", true, null)
            .let { vReport = it.value }

        addRow(artifactContainer, R.drawable.ic_file, "复制到 Download", "/sdcard/Download/PowerProbe", "", true) {
            val out = Exporter.publishToDownloads(this)
            Toast.makeText(
                this,
                if (out.isNotEmpty()) "已复制" else "还没有产物文件",
                Toast.LENGTH_SHORT
            ).show()
        }

        addRow(artifactContainer, R.drawable.ic_thermal, "提前结束", "保留已采数据并归档", "", false) {
            stopScenario()
        }
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
                "已开始：" + Exporter.scenarioName(code) + " · 30 分钟 6 个点",
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
        if (!::vStatus.isInitialized) return

        val phase = when (CollectorState.phase) {
            CollectorState.PHASE_RUNNING -> "采集中 · " + Exporter.scenarioName(CollectorState.scenario)
            CollectorState.PHASE_DONE -> "已完成"
            else -> "空闲"
        }
        vStatus.text = phase
        vProgress.text = CollectorState.donePoints.toString() + " / " + CollectorState.totalPoints

        val m = CollectorState.elapsedSec / 60
        val s = CollectorState.elapsedSec % 60
        vElapsed.text = String.format(Locale.US, "%d 分 %02d 秒", m, s)

        val latest = CollectorState.latest
        if (latest != null) {
            vBattery.text = String.format(
                Locale.US, "%d%% · %.0f mA · %.1f℃", latest.batteryPct, latest.currentMa, latest.battTempC
            )
        }

        vCsv.text = fileNameOf(CollectorState.lastCsvPath)
        vReport.text = fileNameOf(CollectorState.lastReportPath)

        val t = CollectorState.logText()
        logView.text = if (t.length > 6000) t.substring(t.length - 6000) else t
    }

    private fun fileNameOf(p: String): String {
        if (p.isEmpty()) return "-"
        val n = p.substringAfterLast('/')
        return if (n.length > 26) n.substring(0, 24) + "…" else n
    }
}
