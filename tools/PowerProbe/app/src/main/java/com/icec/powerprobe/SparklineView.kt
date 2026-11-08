package com.icec.powerprobe

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.util.AttributeSet
import android.view.View
import java.util.Locale

/**
 * 双 y 轴实时曲线：电流（mA）与电池温度（℃）。
 *
 * 为什么自己画而不引图表库：MPAndroidChart 会给 APK 增加约 1.2MB 且是 AndroidView 老架构，
 * 而这里只需要两条折线 + 网格 + 轴标，200 行 Canvas 就够，还能完全跟随 Material 动态取色。
 */
class SparklineView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {

    var data: List<Float> = emptyList()
        set(v) {
            field = v
            invalidate()
        }

    var data2: List<Float> = emptyList()
        set(v) {
            field = v
            invalidate()
        }

    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(2f)
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        color = Color.parseColor("#4C8DFF")
    }

    private val linePaint2 = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(2f)
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        color = Color.parseColor("#E0674F")
    }

    private val gridPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(1f)
        color = Color.parseColor("#33808080")
        pathEffect = DashPathEffect(floatArrayOf(dp(4f), dp(4f)), 0f)
    }

    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = dp(10f)
        color = Color.parseColor("#FF8A8F98")
    }

    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.parseColor("#1A4C8DFF")
    }

    private fun dp(v: Float): Float = v * resources.displayMetrics.density

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val h = (dp(132f)).toInt()
        setMeasuredDimension(
            MeasureSpec.getSize(widthMeasureSpec),
            resolveSize(h, heightMeasureSpec)
        )
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val padL = dp(34f)
        val padR = dp(34f)
        val padT = dp(10f)
        val padB = dp(16f)
        val w = width - padL - padR
        val h = height - padT - padB
        if (w <= 0f || h <= 0f) return

        // 网格
        for (i in 0..2) {
            val y = padT + h * i / 2f
            canvas.drawLine(padL, y, padL + w, y, gridPaint)
        }

        if (data.size < 2) {
            textPaint.textAlign = Paint.Align.CENTER
            canvas.drawText("等待采样…", width / 2f, height / 2f, textPaint)
            return
        }

        // ---- 电流（左轴，取绝对值，越大越耗电） ----
        val curMax = maxOf(data.maxOrNull()?.let { Math.abs(it) } ?: 0f, 200f)
        val path = Path()
        val fill = Path()
        for (i in data.indices) {
            val x = padL + w * i / (data.size - 1).toFloat()
            val v = Math.abs(data[i]) / curMax
            val y = padT + h * (1f - v)
            if (i == 0) {
                path.moveTo(x, y)
                fill.moveTo(x, padT + h)
                fill.lineTo(x, y)
            } else {
                path.lineTo(x, y)
                fill.lineTo(x, y)
            }
        }
        fill.lineTo(padL + w, padT + h)
        fill.close()
        canvas.drawPath(fill, fillPaint)
        canvas.drawPath(path, linePaint)

        // ---- 温度（右轴） ----
        if (data2.size >= 2) {
            val tMin = (data2.minOrNull() ?: 25f) - 1f
            val tMax = (data2.maxOrNull() ?: 40f) + 1f
            val range = if (tMax - tMin < 1f) 1f else tMax - tMin
            val p2 = Path()
            for (i in data2.indices) {
                val x = padL + w * i / (data2.size - 1).toFloat()
                val y = padT + h * (1f - (data2[i] - tMin) / range)
                if (i == 0) p2.moveTo(x, y) else p2.lineTo(x, y)
            }
            canvas.drawPath(p2, linePaint2)

            textPaint.textAlign = Paint.Align.LEFT
            canvas.drawText(
                String.format(Locale.US, "%.1f℃", data2.last()), padL + w + dp(4f), padT + dp(9f), textPaint
            )
        }

        // ---- 轴标 ----
        textPaint.textAlign = Paint.Align.LEFT
        canvas.drawText("0", dp(4f), padT + h, textPaint)
        canvas.drawText(
            String.format(Locale.US, "%.0f", curMax), dp(4f), padT + dp(9f), textPaint
        )
        textPaint.textAlign = Paint.Align.RIGHT
        canvas.drawText("mA", padL + w, padT + h + dp(12f), textPaint)
    }
}
