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
    private var cameraSwitched = false

    fun reset() {
        lastSwipeSec = -999L
        lastGuardSec = -999L
        lastShotSec = -999L
        cameraSwitched = false
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
                val ok = launch(ctx, t.map)
                CollectorState.log(
                    "[自动] 拉起导航 " + label(t.map) + if (ok) " 成功" else " 失败（未选择或未安装）"
                )
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
            Plan.SC_NAVCAM -> {
                // 前 15 分钟导航，后 15 分钟切相机录 4K
                if (!cameraSwitched && elapsedSec >= 900) {
                    cameraSwitched = true
                    if (root) {
                        startVideoCapture()
                        CollectorState.log("[自动] t=15min 切换到相机录像")
                        shot(ctx, "NAVCAM_t0900")
                    } else {
                        CollectorState.log("[自动] 无 root，请手动打开相机开始录像")
                    }
                }
            }
            Plan.SC_GAME -> {
                // 游戏内操作交给玩家/脚本，这里不注入，避免被判违规
            }
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

    private fun componentOf(ctx: Context, pkg: String): String? {
        return try {
            ctx.packageManager.getLaunchIntentForPackage(pkg)?.component?.flattenToShortString()
        } catch (e: Exception) {
            null
        }
    }

    private fun label(pkg: String): String = if (pkg.isEmpty()) "(未选择)" else pkg
}
