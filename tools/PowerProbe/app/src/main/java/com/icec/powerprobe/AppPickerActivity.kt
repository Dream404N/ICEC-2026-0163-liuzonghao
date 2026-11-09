package com.icec.powerprobe

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.graphics.drawable.Drawable
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.util.LruCache
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.BaseAdapter
import android.widget.EditText
import android.widget.ImageView
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import com.google.android.material.color.DynamicColors
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * 目标应用选择器。
 *
 * 交互参照 KernelSU Manager 的应用列表：大标题 + pill 形常驻搜索栏 + 应用图标/名称/包名
 * 三列信息 + 「显示系统应用」开关 + 即时过滤。这里是同一套设计语言的自实现，
 * 不是搬运 KSU 源码（KSU 为 GPL-3.0，直接复制会传染整个项目的许可证）。
 *
 * 与旧版 AlertDialog 列表的区别：
 * - 输入即过滤，同时匹配「应用名」和「包名」，不用在几百行里翻；
 * - 当前选中项与推荐项置顶并打标签，换机时也能一眼找到 Phigros / 高德；
 * - 应用图标异步加载并缓存，ListView 复用视图，滚动不会掉帧；
 * - 支持显示无桌面图标的系统应用，也支持一键清除选择。
 */
class AppPickerActivity : AppCompatActivity() {

    private data class Entry(
        val label: String,
        val pkg: String,
        val system: Boolean,
        /** 0 = 当前选中，1 = 推荐，2 = 普通；用于置顶排序 */
        val rank: Int
    )

    private class Holder(
        val icon: ImageView,
        val label: TextView,
        val pkg: TextView,
        val badge: TextView,
        val check: ImageView
    )

    companion object {
        const val EXTRA_KIND = "kind"
        const val EXTRA_TITLE = "title"
        const val EXTRA_CURRENT = "current"
        const val EXTRA_PKG = "pkg"
        const val EXTRA_LABEL = "label"

        const val KIND_VIDEO = "video"
        const val KIND_GAME = "game"
        const val KIND_MAP = "map"

        private fun recommendOf(kind: String): Set<String> = when (kind) {
            KIND_GAME -> setOf(
                Plan.PKG_PHIGROS, "com.PigeonGames.Phigros.cc",
                "com.miHoYo.Yuanshen", "com.tencent.tmgp.sgame"
            )
            KIND_MAP -> setOf(Plan.PKG_AMAP, "com.baidu.BaiduMap", "com.tencent.map")
            else -> setOf(
                "com.ss.android.ugc.aweme", "com.ss.android.ugc.aweme.lite",
                "com.smile.gifmaker", "tv.danmaku.bili"
            )
        }
    }

    private lateinit var searchEdit: EditText
    private lateinit var btnClear: ImageView
    private lateinit var countText: TextView
    private lateinit var emptyText: TextView
    private lateinit var listView: ListView

    private val adapter = AppAdapter()
    private val iconCache = LruCache<String, Drawable>(120)
    private val iconPool: ExecutorService = Executors.newFixedThreadPool(3)

    private var kind: String = KIND_VIDEO
    private var current: String = ""
    private var showSystem = false
    private var ready = false
    private var userList: List<Entry> = emptyList()
    private var fullList: List<Entry> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        DynamicColors.applyToActivityIfAvailable(this)
        setContentView(R.layout.activity_app_picker)

        kind = intent.getStringExtra(EXTRA_KIND) ?: KIND_VIDEO
        current = intent.getStringExtra(EXTRA_CURRENT) ?: ""

        val title = findViewById<TextView>(R.id.pickerTitle)
        val hint = findViewById<TextView>(R.id.pickerHint)
        title.text = intent.getStringExtra(EXTRA_TITLE) ?: "选择应用"
        hint.text = when (kind) {
            KIND_GAME -> "推荐 Phigros · 点按选中 · 长按复制包名"
            KIND_MAP -> "推荐 高德地图 · 点按选中 · 长按复制包名"
            else -> "输入即筛选 · 点按选中 · 长按复制包名"
        }

        findViewById<ImageView>(R.id.btnBack).setOnClickListener { finish() }
        findViewById<TextView>(R.id.btnClearSelection).setOnClickListener { select("", "") }

        searchEdit = findViewById(R.id.searchEdit)
        btnClear = findViewById(R.id.btnClear)
        countText = findViewById(R.id.countText)
        emptyText = findViewById(R.id.emptyText)
        listView = findViewById(R.id.appList)

        listView.adapter = adapter
        listView.setEmptyView(emptyText)
        listView.setOnItemClickListener { _, _, pos, _ ->
            val e = adapter.getItem(pos) as? Entry ?: return@setOnItemClickListener
            select(e.pkg, e.label)
        }
        // 长按复制包名：核对渠道包、写报告时经常要贴准确包名
        listView.setOnItemLongClickListener { _, _, pos, _ ->
            val e = adapter.getItem(pos) as? Entry
            if (e != null) {
                val cm = getSystemService(CLIPBOARD_SERVICE) as? ClipboardManager
                cm?.setPrimaryClip(ClipData.newPlainText("package", e.pkg))
                Toast.makeText(this, "已复制 " + e.pkg, Toast.LENGTH_SHORT).show()
            }
            true
        }

        searchEdit.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun afterTextChanged(s: Editable?) {
                btnClear.visibility = if (s.isNullOrEmpty()) View.GONE else View.VISIBLE
                applyFilter()
            }
        })
        btnClear.setOnClickListener { searchEdit.setText("") }
        searchEdit.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                hideKeyboard()
                true
            } else {
                false
            }
        }

        findViewById<SwitchCompat>(R.id.switchSystem).setOnCheckedChangeListener { _, checked ->
            showSystem = checked
            applyFilter()
        }

        loadAsync()
    }

    override fun onDestroy() {
        super.onDestroy()
        iconPool.shutdownNow()
    }

    // ---------------- 应用列表 ----------------

    /**
     * 列表加载放后台：PackageManager 查询 + 取应用名在装了几百个应用的机器上要几百毫秒，
     * 放主线程会让页面打开时白一下。图标不在这里取，改为列表滚动时按需异步加载。
     */
    private fun loadAsync() {
        Thread {
            val pm = packageManager
            val launcher = ArrayList<Entry>()
            try {
                val i = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
                for (ri in pm.queryIntentActivities(i, 0)) {
                    val pkg = ri.activityInfo.packageName
                    if (pkg == packageName) continue
                    val label = try {
                        ri.loadLabel(pm).toString()
                    } catch (e: Exception) {
                        pkg
                    }
                    launcher.add(Entry(label, pkg, isSystem(pm, pkg), rankOf(pkg)))
                }
            } catch (e: Exception) {
                // 查询失败时保留空列表，由空态文案提示打开系统应用开关
            }

            val all = LinkedHashMap<String, Entry>()
            for (e in launcher) all[e.pkg] = e

            // 无桌面图标的系统应用（相机、下载管理等）。
            // Android 11 起应用可见性受 manifest 的 queries 限制，能读到多少列多少，
            // 失败不影响主列表——这里不做 QUERY_ALL_PACKAGES 声明，保持权限范围最小。
            try {
                for (ai in pm.getInstalledApplications(0)) {
                    val pkg = ai.packageName
                    if (pkg == packageName || all.containsKey(pkg)) continue
                    val label = try {
                        pm.getApplicationLabel(ai).toString()
                    } catch (e: Exception) {
                        pkg
                    }
                    all[pkg] = Entry(label, pkg, true, rankOf(pkg))
                }
            } catch (e: Exception) {
                // 同上
            }

            val cmp = compareBy<Entry> { it.rank }.thenBy { it.label.lowercase(Locale.US) }
            val users = launcher.distinctBy { it.pkg }.filter { !it.system }.sortedWith(cmp)
            val full = all.values.sortedWith(cmp)

            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                userList = users
                fullList = full
                ready = true
                applyFilter()
            }
        }.start()
    }

    private fun isSystem(pm: PackageManager, pkg: String): Boolean {
        return try {
            (pm.getApplicationInfo(pkg, 0).flags and ApplicationInfo.FLAG_SYSTEM) != 0
        } catch (e: Exception) {
            false
        }
    }

    private fun rankOf(pkg: String): Int = when {
        pkg.isNotEmpty() && pkg == current -> 0
        recommendOf(kind).contains(pkg) -> 1
        else -> 2
    }

    // ---------------- 过滤 ----------------

    private fun applyFilter() {
        if (!ready) return
        val base = if (showSystem) fullList else userList
        val q = searchEdit.text.toString().trim().lowercase(Locale.US)
        val items = if (q.isEmpty()) {
            base
        } else {
            base.filter {
                it.label.lowercase(Locale.US).contains(q) ||
                    it.pkg.lowercase(Locale.US).contains(q)
            }
        }
        adapter.submit(items)

        countText.text = "共 " + items.size + " 个应用" +
            if (showSystem) " · 含系统应用" else ""
        emptyText.text = if (q.isEmpty()) {
            "没有可用的应用\n可打开上方「显示系统应用」"
        } else {
            "没有找到「" + q + "」\n换个关键词、试试包名，或打开「显示系统应用」"
        }
    }

    private fun hideKeyboard() {
        try {
            val imm = getSystemService(INPUT_METHOD_SERVICE) as? InputMethodManager
            imm?.hideSoftInputFromWindow(searchEdit.windowToken, 0)
        } catch (e: Exception) {
        }
    }

    /** 选中 / 清除都走这里：MainActivity 收到 RESULT_OK 后写回 Plan */
    private fun select(pkg: String, label: String) {
        val i = Intent()
        i.putExtra(EXTRA_KIND, kind)
        i.putExtra(EXTRA_PKG, pkg)
        i.putExtra(EXTRA_LABEL, label)
        setResult(Activity.RESULT_OK, i)
        finish()
    }

    // ---------------- 列表适配器 ----------------

    private inner class AppAdapter : BaseAdapter() {

        private var shown: List<Entry> = emptyList()

        fun submit(items: List<Entry>) {
            shown = items
            notifyDataSetChanged()
        }

        override fun getCount(): Int = shown.size
        override fun getItem(pos: Int): Any = shown[pos]
        override fun getItemId(pos: Int): Long = pos.toLong()

        override fun getView(pos: Int, convertView: View?, parent: ViewGroup): View {
            val v = convertView
                ?: layoutInflater.inflate(R.layout.item_app, parent, false)
            val h = (v.tag as? Holder) ?: Holder(
                v.findViewById(R.id.appIcon),
                v.findViewById(R.id.appLabel),
                v.findViewById(R.id.appPkg),
                v.findViewById(R.id.appBadge),
                v.findViewById(R.id.appCheck)
            ).also { v.tag = it }

            val e = shown[pos]
            h.label.text = e.label
            h.pkg.text = e.pkg

            val badge = when {
                e.pkg == current && current.isNotEmpty() -> "当前"
                e.rank == 1 -> "推荐"
                else -> ""
            }
            h.badge.text = badge
            h.badge.visibility = if (badge.isEmpty()) View.GONE else View.VISIBLE
            h.check.visibility = if (e.pkg == current && current.isNotEmpty()) {
                View.VISIBLE
            } else {
                View.GONE
            }

            // 图标：命中缓存直接用，未命中就先占位再异步取。
            // 用 ImageView 的 tag 记住当前包名，加载回来时校验，防止视图复用后贴错图标。
            h.icon.tag = e.pkg
            val cached = iconCache.get(e.pkg)
            if (cached != null) {
                h.icon.setImageDrawable(cached)
            } else {
                h.icon.setImageResource(R.drawable.ic_app_placeholder)
                iconPool.execute {
                    val d = try {
                        packageManager.getApplicationIcon(e.pkg)
                    } catch (ex: Exception) {
                        null
                    }
                    if (d != null) {
                        iconCache.put(e.pkg, d)
                        runOnUiThread {
                            if (!isFinishing && !isDestroyed && h.icon.tag == e.pkg) {
                                h.icon.setImageDrawable(d)
                            }
                        }
                    }
                }
            }
            return v
        }
    }
}
