package com.icec.powerprobe

import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * root shell 执行器。设备已 root（Magisk / KernelSU），通过 su 读取系统节点。
 * 非 root 环境下所有调用返回空串，由上层走 BatteryManager 兜底。
 */
object Shell {

    fun exec(cmd: String, timeoutSec: Long = 25): String {
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
            reader.join(timeoutSec * 1000L)
            try {
                p.destroy()
            } catch (e: Exception) {
            }
            out.toString()
        } catch (e: Exception) {
            ""
        }
    }

    /** 直接读一个可公开访问的节点（无需 root） */
    fun cat(path: String): String {
        return try {
            val f = java.io.File(path)
            if (f.exists() && f.canRead()) f.readText().trim() else ""
        } catch (e: Exception) {
            ""
        }
    }
}
