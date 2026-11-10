package com.icec.powerprobe

import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import java.util.Locale

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
    // 历史字段名，现存放「相机应用」包名。不改标识符是为了兼容已采集 CSV 的
    // scenario=NAVCAM 口径与用户设备上已保存的 SharedPreferences，避免升级后配置丢失。
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

    /** 默认游戏：Phigros（官方包名）。渠道包若不同，下面还有按应用名兜底 */
    const val PKG_PHIGROS = "com.PigeonGames.Phigros"

    /**
     * 第四工况（官网口径「导航 / 拍摄」）在本机按**拍摄**部分执行：全程相机录像。
     * 原因：实测高德深链在本机不生效，日志明确记录「非高德地图，跳过深链导航」，
     * 采集下来的前台一直是 com.android.camera。与其留一个跑不起来的导航半程、
     * 让报告名实不符，不如把工况统一成真实发生了的负载。
     */
    const val PKG_CAMERA = "com.android.camera"

    private val CAMERA_CANDIDATES = listOf(
        PKG_CAMERA,                          // AOSP / 小米系统相机（本机实测命中）
        "com.miui.camera",                   // 小米新版相机
        "com.android.camera2",               // 部分 ROM
        "com.oppo.camera",
        "com.vivo.camera",
        "com.huawei.camera"
    )

    /**
     * 游戏候选。Phigros 放在最前：它是音游，高帧率 + 持续 GPU 占用 + 强触控，
     * 是测「热与功耗」最干净的负载——没有网络资源流、没有随机地图加载，
     * 场景重复性远高于开放世界类手游，符合课题要求的「可复现」。
     */
    private val GAME_CANDIDATES = listOf(
        PKG_PHIGROS,
        "com.PigeonGames.Phigros.cc",        // 部分渠道包
        "com.miHoYo.Yuanshen",
        "com.tencent.tmgp.sgame"
    )

    /** 按应用名模糊匹配，兜住渠道包改名的情况 */
    private val GAME_LABEL_HINT = "phigros"

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

    /**
     * 首次运行时自动填一套候选，用户可再改。
     *
     * 顺序刻意做成「显式配置优先 → 指定包名 → 应用名模糊匹配 → 已安装游戏兜底」，
     * 这样本机装了 Phigros 就一定选它，换机也不会因为包名对不上而直接失效。
     */
    fun autofill(ctx: Context): Targets {
        val cur = load(ctx)
        val t = Targets(
            video = cur.video.ifEmpty { firstInstalled(ctx, VIDEO_CANDIDATES) },
            game = cur.game.ifEmpty { resolveGame(ctx) },
            map = cur.map.ifEmpty { firstInstalled(ctx, CAMERA_CANDIDATES) },
            camera = cur.camera
        )
        save(ctx, t)
        return t
    }

    /** Phigros 优先，其次按应用名模糊匹配，最后才是任意已安装游戏 */
    fun resolveGame(ctx: Context): String {
        val hit = firstInstalled(ctx, GAME_CANDIDATES)
        if (hit.isNotEmpty()) return hit
        val byName = firstByLabel(ctx, GAME_LABEL_HINT)
        if (byName.isNotEmpty()) return byName
        return firstGame(ctx)
    }

    /** 应用名包含关键字即可（忽略大小写），用于兜住渠道包 */
    fun firstByLabel(ctx: Context, hint: String): String {
        return try {
            val pm = ctx.packageManager
            val apps = pm.getInstalledApplications(PackageManager.GET_META_DATA)
            apps.asSequence()
                .filter { pm.getLaunchIntentForPackage(it.packageName) != null }
                .filter {
                    try {
                        pm.getApplicationLabel(it).toString().lowercase(Locale.US)
                            .contains(hint.lowercase(Locale.US))
                    } catch (e: Exception) {
                        false
                    }
                }
                .map { it.packageName }
                .firstOrNull() ?: ""
        } catch (e: Exception) {
            ""
        }
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
