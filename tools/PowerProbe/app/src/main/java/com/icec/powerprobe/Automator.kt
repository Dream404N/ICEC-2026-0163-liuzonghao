package com.icec.powerprobe

import android.content.Context
import android.content.Intent

/**
 * 自动化执行器：把「人工点开抖音、手划、按电源键灭屏」这些动作交给程序做。
 *
 * 分两类动作：
 *   - UI 动作（launch / swipe / keyevent）：需要 root（走 `input`、`am start`）。
 *     没有 root 时退化为 Intent 拉起 App，划动与灭屏改为提示用户手动完成。
 *   - 证据动作（screencap）：只在有 root 时执行，每 10 分钟留一张截图。
 *
 * **功耗测量的自我约束**：本类所有 shell 调用都是低频的（工况开始时 1 次、之后 25 秒
 * 最多 1 次 swipe），绝不在采样点附近跑 dumpsys —— 否则自动化本身会污染被测数据。
 * 这一点写进报告的方法学部分。
 */
object Automator {

    private var lastSwipeSec = -999L
    private var lastGuardSec = -999L
    private var lastShotSec = -999L
    private var lastKeepSec = -999L

    fun reset() {
        lastSwipeSec = -999L
        lastGuardSec = -999L
        lastShotSec = -999L
        lastKeepSec = -999L
    }

    // ---------------- 对外 ----------------

    fun kickoff(ctx: Context, scenario: String, t: Targets) {
        reset()
        when (scenario) {
            Plan.SC_IDLE -> {
                if (Root.ensure()) {
                    screenOff()
                    CollectorState.log("[自动] 已发送休眠指令，进入灭屏待机")
                } else {
                    CollectorState.log("[自动] 无 root，请手动按电源键灭屏")
                }
                shot(ctx, "IDLE_t0000")
            }
            Plan.SC_SVIDEO -> {
                val ok = launch(ctx, t.video)
                CollectorState.log(
                    "[自动] 拉起短视频 " + label(t.video) + if (ok) " 成功" else " 失败（未选择或未安装）"
                )
                shot(ctx, "SVIDEO_t0000")
            }
            Plan.SC_NAVCAM -> {
                // 全程相机录像：开场就拉起相机并触发录制，不再有「前 15 分钟导航」。
                val ok = launch(ctx, t.map)
                CollectorState.log(
                    "[自动] 拉起相机 " + label(t.map) + if (ok) " 成功" else " 失败（未选择或未安装）"
                )
                if (ok) {
                    if (Root.ensure()) {
                        startVideoCapture()
                        CollectorState.log("[自动] 已触发相机录像，全程保持")
                    } else {
                        CollectorState.log("[自动] 无 root，请手动打开相机开始录像")
                    }
                }
                shot(ctx, "NAVCAM_t0000")
            }
            Plan.SC_GAME -> {
                val ok = launch(ctx, t.game)
                CollectorState.log(
                    "[自动] 拉起游戏 " + label(t.game) + if (ok) " 成功" else " 失败（未选择或未安装）"
                )
                shot(ctx, "GAME_t0000")
            }
        }
    }

    /** 每 20 秒由服务调用一次 */
    fun tick(ctx: Context, scenario: String, elapsedSec: Long, t: Targets) {
        val root = Root.ensure()
        when (scenario) {
            Plan.SC_IDLE -> {
                // 防手滑：每 2 分钟确认一次屏幕仍是熄的
                if (root && elapsedSec - lastGuardSec >= 120) {
                    lastGuardSec = elapsedSec
                    screenOff()
                }
            }
            Plan.SC_SVIDEO -> {
                if (root && elapsedSec - lastSwipeSec >= 25) {
                    lastSwipeSec = elapsedSec
                    swipeUp()
                }
            }
            Plan.SC_GAME -> {
                // 游戏内操作交给玩家/脚本，这里不注入，避免被判违规或打断正在打的曲子。
                // 只做「保活」：每 3 分钟确认游戏仍在前台，被系统或误触切走就重新拉起。
                if (root && elapsedSec - lastKeepSec >= 180) {
                    lastKeepSec = elapsedSec
                    keepForeground(ctx, t.game)
                }
            }
        }

        // 短视频与相机录像同理：长时间运行可能被后台清理，静默拉回前台，日志留痕。
        // 频率压到 5 分钟一次，避免自动化本身成为被测负载。
        // 相机录像工况绝不在这里重复调用 startVideoCapture()：KEYCODE_CAMERA 是
        // 「开始/停止」切换，再按一次会把录制停掉；录制只由 kickoff 触发一次。
        val keepPkg = when (scenario) {
            Plan.SC_SVIDEO -> t.video
            Plan.SC_NAVCAM -> t.map
            else -> ""
        }
        if (keepPkg.isNotEmpty() && root && elapsedSec - lastKeepSec >= 300) {
            lastKeepSec = elapsedSec
            keepForeground(ctx, keepPkg)
        }
        if (root && elapsedSec - lastShotSec >= 600) {
            lastShotSec = elapsedSec
            shot(ctx, scenario + "_t" + elapsedSec)
        }
    }

    fun teardown(ctx: Context, t: Targets) {
        for (p in listOf(t.video, t.game, t.map)) {
            if (p.isNotEmpty()) forceStop(p)
        }
        if (Root.ensure()) screenOn()
        CollectorState.log("[自动] 已结束目标应用并 wakeup 屏幕")
    }

    // ---------------- 基础动作 ----------------

    fun launch(ctx: Context, pkg: String): Boolean {
        if (pkg.isEmpty() || !Plan.isInstalled(ctx, pkg)) return false

        if (Root.ensure()) {
            val comp = componentOf(ctx, pkg)
            val cmd = if (comp != null) {
                "am start -W -n " + comp
            } else {
                "monkey -p " + pkg + " -c android.intent.category.LAUNCHER 1"
            }
            val out = Root.exec(cmd, 20000)
            if (!Root.wasRefused(out) && !out.contains("Error") && !out.contains("Exception")) {
                // `am start -W` 会打印 TotalTime（冷/热启动总耗时），直接当性能指标收下
                val ms = totalTimeOf(out)
                if (ms > 0) Metrics.lastLaunchMs = ms
                return true
            }
        }

        return try {
            val i = ctx.packageManager.getLaunchIntentForPackage(pkg) ?: return false
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
            ctx.startActivity(i)
            true
        } catch (e: Exception) {
            false
        }
    }

    fun swipeUp(): Boolean {
        if (!Root.ensure()) return false
        Root.exec("input swipe 540 1900 540 600 250", 8000)
        return true
    }

    fun screenOff(): Boolean {
        if (!Root.ensure()) return false
        Root.exec("input keyevent 223", 6000)
        return true
    }

    fun screenOn(): Boolean {
        if (!Root.ensure()) return false
        Root.exec("input keyevent 224", 6000)
        return true
    }

    fun forceStop(pkg: String): Boolean {
        if (!Root.ensure() || pkg.isEmpty()) return false
        Root.exec("am force-stop " + pkg, 10000)
        return true
    }

    /** 系统相机录像 Intent（不指定包名，交给系统默认相机） */
    fun startVideoCapture(): Boolean {
        if (!Root.ensure()) return false
        Root.exec("am start -a android.media.action.VIDEO_CAPTURE", 15000)
        // 多数相机 App 用 KEYCODE_CAMERA 开始/停止录制
        Root.exec("input keyevent 27", 6000)
        return true
    }

    /** 截图存证（防摆拍）：落到 Download/PowerProbe/shots/ */
    fun shot(ctx: Context, tag: String) {
        if (!Root.ensure()) return
        val safe = tag.replace(Regex("[^A-Za-z0-9_\\-]"), "_")
        Root.exec("mkdir -p /sdcard/Download/PowerProbe/shots", 8000)
        Root.exec(
            "screencap -p /sdcard/Download/PowerProbe/shots/" + System.currentTimeMillis() + "_" + safe + ".png",
            15000
        )
    }

    /**
     * 目标应用保活：读一次当前前台包名，不是目标就重新拉起。
     * 只在「应保持前台」的工况调用，频率压到 3~5 分钟一次，避免自动化自己成为负载。
     */
    fun keepForeground(ctx: Context, pkg: String) {
        if (pkg.isEmpty() || !Root.ensure()) return
        val fg = foregroundPkg()
        if (fg.isEmpty() || fg == pkg) return
        if (fg.startsWith("com.icec.powerprobe")) return
        CollectorState.log("[自动] 前台变为 " + fg + "，重新拉起 " + label(pkg))
        launch(ctx, pkg)
    }

    fun foregroundPkg(): String {
        val out = Root.exec(
            "dumpsys activity activities 2>/dev/null | grep -m1 -E 'mResumedActivity|topResumedActivity'",
            8000
        )
        return PKG_RE.find(out)?.groupValues?.get(1) ?: ""
    }

    /** 从 `am start -W` 的输出里取 TotalTime */
    private fun totalTimeOf(out: String): Long {
        for (line in out.split("\n")) {
            val t = line.trim()
            if (t.startsWith("TotalTime:")) {
                return t.substringAfter(':').trim().toLongOrNull() ?: 0L
            }
        }
        return 0L
    }

    private val PKG_RE = Regex("([a-zA-Z][a-zA-Z0-9_]*(?:\\.[a-zA-Z0-9_]+){1,6})/")

    private fun componentOf(ctx: Context, pkg: String): String? {
        return try {
            ctx.packageManager.getLaunchIntentForPackage(pkg)?.component?.flattenToShortString()
        } catch (e: Exception) {
            null
        }
    }

    private fun label(pkg: String): String = if (pkg.isEmpty()) "(未选择)" else pkg
}
