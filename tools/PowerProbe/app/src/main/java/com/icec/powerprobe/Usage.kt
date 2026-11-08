package com.icec.powerprobe

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.Build
import android.os.Process

/**
 * 前台应用识别（工况真实性证据链）。
 *
 * 为什么不用 `dumpsys activity`：那需要 shell 或 root 权限。这里改走
 * `UsageStatsManager.queryEvents()` —— 数据由系统 UsageStats 服务维护，写入者是
 * system_server，第三方 App 既改不了也删不掉，比自己截图「我确实在玩游戏」更硬。
 *
 * 权限：`android.permission.PACKAGE_USAGE_STATS` 是「签名/特权」级权限，
 * 普通 App 声明它不会被自动授予，必须由用户在「设置 → 应用 → 特殊权限 → 使用情况访问」
 * 里手动打开。未授权时 queryEvents 返回空集，本类返回空串，不影响其余采样。
 */
object Usage {

    /** 用户是否已在系统设置里打开「使用情况访问」 */
    @Suppress("DEPRECATION")
    fun hasAccess(ctx: Context): Boolean {
        return try {
            val ops = ctx.getSystemService(Context.APP_OPS_SERVICE) as? AppOpsManager
                ?: return false
            val mode = if (Build.VERSION.SDK_INT >= 29) {
                ops.unsafeCheckOpNoThrow(
                    AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName
                )
            } else {
                ops.checkOpNoThrow(
                    AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName
                )
            }
            mode == AppOpsManager.MODE_ALLOWED
        } catch (e: Exception) {
            false
        }
    }

    /**
     * 回看窗口内最后一次「切到前台」的包名。
     * 用回看而不是只看本次采样瞬间：5 分钟内用户可能短暂切出去，取最后一次
     * 前台事件比取「此刻」更稳定，也不会因为在桌面停留而记成 launcher。
     */
    fun lastForegroundPkg(ctx: Context, lookbackMs: Long = 5 * 60 * 1000L): String {
        if (!hasAccess(ctx)) return ""
        return try {
            val usm = ctx.getSystemService(Context.USAGE_STATS_SERVICE) as? UsageStatsManager
                ?: return ""
            val now = System.currentTimeMillis()
            val events = usm.queryEvents(now - lookbackMs, now) ?: return ""
            var pkg = ""
            val e = UsageEvents.Event()
            while (events.hasNextEvent()) {
                events.getNextEvent(e)
                // MOVE_TO_FOREGROUND(1) 在 API 29 起更名为 ACTIVITY_RESUMED(1)，常量值相同
                if (e.eventType == UsageEvents.Event.MOVE_TO_FOREGROUND) {
                    val p = e.packageName
                    if (!p.isNullOrEmpty() && p != ctx.packageName) pkg = p
                }
            }
            pkg
        } catch (e: Exception) {
            ""
        }
    }
}
