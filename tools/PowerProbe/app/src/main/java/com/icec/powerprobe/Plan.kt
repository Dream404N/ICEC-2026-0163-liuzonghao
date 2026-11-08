package com.icec.powerprobe

import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager

/**
 * 自动化测试计划：四个工况的顺序、时长、以及每个工况要自动拉起的 App。
 *
 * 为什么把「目标应用」做成配置而不是写死包名：
 * 换机、换 ROM、换账号之后 App 包名会变（尤其国内商店渠道包），写死会导致 automation
 * 在别人机器上直接失效。这里在首次启动时自动探测本机已安装的候选 App，探测不到就让
 * 用户从已安装列表里点一个，保证「换台机器也能跑」。
 */
data class Targets(
    val video: String = "",
    val game: String = "",
    val map: String = "",
    val camera: String = ""
)

object Plan {

    const val SC_IDLE = "IDLE"
    const val SC_SVIDEO = "SVIDEO"
    const val SC_NAVCAM = "NAVCAM"
    const val SC_GAME = "GAME"

    /** 单工况时长（分钟） */
    const val SCENARIO_MINUTES = 30

    /**
     * 采样间隔（分钟）。取 5 分钟是为了对齐官网「30 分钟内每 5 分钟」的口径：
     * 4 工况 × 6 点 = 24 组时间序列，正好是交付要求里的「24 组」。
     * 想做更细的曲线可以把这里改成 1，但那属于补充材料，不能替换官方口径的数据。
     */
    const val SAMPLE_INTERVAL_MIN = 5

    val queue: List<String> = listOf(SC_IDLE, SC_SVIDEO, SC_NAVCAM, SC_GAME)

    private const val PREF = "powerprobe_plan"

    private val VIDEO_CANDIDATES = listOf(
        "com.ss.android.ugc.aweme",          // 抖音
        "com.ss.android.ugc.aweme.lite",     // 抖音极速版
        "com.smile.gifmaker",                // 快手
        "com.kuaishou.nebula",               // 快手极速版
        "tv.danmaku.bili"                    // 哔哩哔哩
    )

    private val MAP_CANDIDATES = listOf(
        "com.baidu.BaiduMap",                // 百度地图
        "com.autonavi.minimap",              // 高德地图
        "com.tencent.map"                    // 腾讯地图
    )

    fun load(ctx: Context): Targets {
        val sp = ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        return Targets(
            video = sp.getString("video", "") ?: "",
            game = sp.getString("game", "") ?: "",
            map = sp.getString("map", "") ?: "",
            camera = sp.getString("camera", "") ?: ""
        )
    }

    fun save(ctx: Context, t: Targets) {
        ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE).edit()
            .putString("video", t.video)
            .putString("game", t.game)
            .putString("map", t.map)
            .putString("camera", t.camera)
            .apply()
    }

    /** 首次运行时自动填一套候选，用户可再改 */
    fun autofill(ctx: Context): Targets {
        val cur = load(ctx)
        val t = Targets(
            video = cur.video.ifEmpty { firstInstalled(ctx, VIDEO_CANDIDATES) },
            game = cur.game.ifEmpty { firstGame(ctx) },
            map = cur.map.ifEmpty { firstInstalled(ctx, MAP_CANDIDATES) },
            camera = cur.camera
        )
        save(ctx, t)
        return t
    }

    fun firstInstalled(ctx: Context, pkgs: List<String>): String {
        for (p in pkgs) {
            if (isInstalled(ctx, p)) return p
        }
        return ""
    }

    fun isInstalled(ctx: Context, pkg: String): Boolean {
        if (pkg.isEmpty()) return false
        return try {
            ctx.packageManager.getApplicationInfo(pkg, 0)
            true
        } catch (e: Exception) {
            false
        }
    }

    /** 已安装游戏：取 category == GAME 的可见应用 */
    fun firstGame(ctx: Context): String {
        return try {
            val pm = ctx.packageManager
            val apps = pm.getInstalledApplications(PackageManager.GET_META_DATA)
            apps.asSequence()
                .filter { it.category == ApplicationInfo.CATEGORY_GAME }
                .filter { pm.getLaunchIntentForPackage(it.packageName) != null }
                .map { it.packageName }
                .firstOrNull() ?: ""
        } catch (e: Exception) {
            ""
        }
    }

    /** 可选的启动器应用（用于让用户挑） */
    fun launcherApps(ctx: Context): List<Pair<String, String>> {
        val out = ArrayList<Pair<String, String>>()
        try {
            val pm = ctx.packageManager
            val intent = android.content.Intent(android.content.Intent.ACTION_MAIN)
                .addCategory(android.content.Intent.CATEGORY_LAUNCHER)
            val list = pm.queryIntentActivities(intent, 0)
            for (ri in list) {
                val pkg = ri.activityInfo.packageName
                if (pkg == ctx.packageName) continue
                val label = try {
                    ri.loadLabel(pm).toString()
                } catch (e: Exception) {
                    pkg
                }
                out.add(Pair(label, pkg))
            }
        } catch (e: Exception) {
        }
        return out.distinctBy { it.second }.sortedBy { it.first }
    }
}
