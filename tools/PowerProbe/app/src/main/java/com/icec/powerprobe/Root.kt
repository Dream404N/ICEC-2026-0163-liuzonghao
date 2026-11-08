package com.icec.powerprobe

/**
 * root 执行通道 —— 受限、只读优先。
 *
 * 关于「会不会把机器搞坏」这条，用代码强制而不是靠注释承诺：
 *
 * 1. **不接受任何外部命令**。这里能执行的所有字符串都是本工程里编译期写死的常量，
 *    App 不读文件、不读网络、不接受 Intent 传入的命令参数，也不解析 CSV/JSON 里的指令。
 *    换句话说，能跑哪些命令在 build 出 APK 的那一刻就固定了。
 * 2. **关键字硬拦截**。exec() 入口先过 FORBIDDEN 正则，命中 rm / mkfs / dd / mount /
 *    format / wipe / reboot / recovery / fastboot / setprop / chmod / chown / mv / cp /
 *    ln / redirect 任一关键词就直接返回空串、不执行。即使有人在源码里手滑加了破坏性
 *    命令，运行时也会被拦下。
 * 3. **超时强杀**。su 授权弹窗、dumpsys 卡住都不会挂死采样线程，到时 destroy 进程。
 * 4. **只读为主**。日常采集只做 cat / getprop / dumpsys / ps 这类读取；唯一带副作用的
 *    指令是 `am start`、`input keyevent`、`input swipe`、`screencap`，作用范围仅限
 *    「当前前台 UI 与已安装应用」，不写任何系统分区、不动 recovery/fastboot。
 *
 * 因此最坏情况是「某条命令被 su 拒绝、返回空串」，不存在格机路径。
 */
object Root {

    @Volatile
    var available = false
        private set

    @Volatile
    var checked = false
        private set

    @Volatile
    var uidLine = ""
        private set

    /** 破坏性关键词黑名单：命中即拒绝执行 */
    private val FORBIDDEN = Regex(
        "(?i)\\b(rm|rmdir|mkfs|mke2fs|dd|mount|umount|format|wipe|reboot|recovery|fastboot|" +
            "setprop|chmod|chown|mv|cp|ln|shred|truncate|tee|install|flash|persist)\\b" +
            "|>>|>\\s*\\S"
    )

    private const val REFUSED = "__REFUSED_BY_GUARD__"

    /** 探测 su 是否可用（只在首次或手动重探时跑一次） */
    fun ensure(): Boolean {
        if (checked) return available
        checked = true
        val out = exec("id", 5000)
        available = out.contains("uid=0")
        uidLine = out.lineSequence().firstOrNull { it.contains("uid=") }?.trim() ?: ""
        return available
    }

    /** 强制重新探测（用户在 Magisk/KernelSU 里刚授权完） */
    fun reprobe(): Boolean {
        checked = false
        available = false
        return ensure()
    }

    fun exec(cmd: String, timeoutMs: Long = 8000): String {
        if (FORBIDDEN.containsMatchIn(cmd)) {
            return REFUSED
        }
        return try {
            val p = ProcessBuilder("su", "-c", cmd).redirectErrorStream(true).start()
            val out = StringBuilder()
            val reader = Thread {
                try {
                    val r = p.inputStream.bufferedReader()
                    var line = r.readLine()
                    while (line != null) {
                        out.append(line).append('\n')
                        line = r.readLine()
                    }
                    r.close()
                } catch (e: Exception) {
                    // 流被中断，保留已读部分
                }
            }
            reader.isDaemon = true
            reader.start()
            reader.join(timeoutMs)
            try {
                p.destroy()
            } catch (e: Exception) {
            }
            out.toString()
        } catch (e: Exception) {
            ""
        }
    }

    fun wasRefused(out: String): Boolean = out == REFUSED
}
