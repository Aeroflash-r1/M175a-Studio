package com.ganesan.m175otg.print

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF

/**
 * PAGE PLACEMENT ENGINE — how a source page lands on the paper.
 *
 * Windows driver parity: these are the four controls every real driver
 * exposes in its "Page Layout" tab.
 *
 *  - fitMode: how the source maps into the printable area
 *      FIT_PAGE     scale to fill the page (may distort if source aspect
 *                   differs — "Fit to page" in HP terms)
 *      ACTUAL_SIZE  print at true size, centered, CROP if larger (100%)
 *      SHRINK_FIT   scale down to fit, never up, centered ("Fit shrinks
 *                   oversized pages only")
 *  - orientation: PORTRAIT / LANDSCAPE (rotates the paper, not the image)
 *  - margins: millimetres on each edge (subset of the printable area)
 *  - position: NUDGE only meaningful for ACTUAL_SIZE — moves the image
 *    inside the area as a fraction of the leftover space (0..1, 0.5 =
 *    centered). Windows calls this "Document position".
 */
object PagePlacement {

    enum class FitMode { FIT_PAGE, ACTUAL_SIZE, SHRINK_FIT }
    enum class Orientation { PORTRAIT, LANDSCAPE }

    data class MarginsMm(
        val left: Int = 0, val top: Int = 0,
        val right: Int = 0, val bottom: Int = 0,
    ) {
        val isZero: Boolean get() = left == 0 && top == 0 && right == 0 && bottom == 0
        companion object {
            val NONE = MarginsMm()
            /** Symmetric shorthand. */
            fun all(mm: Int) = MarginsMm(mm, mm, mm, mm)
        }
    }

    data class Placement(
        val fitMode: FitMode = FitMode.FIT_PAGE,
        val orientation: Orientation = Orientation.PORTRAIT,
        val margins: MarginsMm = MarginsMm.NONE,
        /** 0..1 within leftover space (x, y). Ignored unless ACTUAL_SIZE. */
        val posX: Float = 0.5f,
        val posY: Float = 0.5f,
    )

    /**
     * Draw [src] onto a blank A4 canvas of [pageW]x[pageH] px at [dpi]
     * according to [pl]. Returns the finished page bitmap (RGB_565,
     * ready for the JPEG pipeline). Honour the largeHeap manifest by
     * bounding total pixels at very high dpi.
     */
    fun render(
        src: Bitmap, pageW: Int, pageH: Int, pl: Placement,
        dpi: Int = 300,
    ): Bitmap {
        // margins in px, clamped so the content area can never invert
        // (explicit dpi, NOT inferred from pageW: that assumption only
        // held for A4 and would mis-scale margins on Letter/Legal)
        val dpiAssumed = dpi.toFloat()
        val mL = (pl.margins.left * dpiAssumed / 25.4f).toInt()
            .coerceIn(0, pageW / 3)
        val mR = (pl.margins.right * dpiAssumed / 25.4f).toInt()
            .coerceIn(0, pageW / 3)
        val mT = (pl.margins.top * dpiAssumed / 25.4f).toInt()
            .coerceIn(0, pageH / 3)
        val mB = (pl.margins.bottom * dpiAssumed / 25.4f).toInt()
            .coerceIn(0, pageH / 3)

        val areaW = (pageW - mL - mR).coerceAtLeast(1)
        val areaH = (pageH - mT - mB).coerceAtLeast(1)

        val canvas = Bitmap.createBitmap(pageW, pageH, Bitmap.Config.RGB_565)
        val c = Canvas(canvas)
        c.drawColor(Color.WHITE)

        // compute the drawn rect
        var dw: Float; var dh: Float
        when (pl.fitMode) {
            FitMode.FIT_PAGE -> {
                val s = minOf(areaW.toFloat() / src.width,
                    areaH.toFloat() / src.height)
                dw = src.width * s; dh = src.height * s
            }
            FitMode.ACTUAL_SIZE -> {
                // 1 source px = 1 page px (true size at this dpi); may crop
                dw = src.width.toFloat(); dh = src.height.toFloat()
            }
            FitMode.SHRINK_FIT -> {
                val s = minOf(
                    1.0f,
                    minOf(areaW.toFloat() / src.width,
                        areaH.toFloat() / src.height))
                dw = src.width * s; dh = src.height * s
            }
        }
        // position within the leftover space (0..1), centered by default
        val leftoverX = (areaW - dw).coerceAtLeast(0f)
        val leftoverY = (areaH - dh).coerceAtLeast(0f)
        val dx = mL + leftoverX * pl.posX.coerceIn(0f, 1f)
        val dy = mT + leftoverY * pl.posY.coerceIn(0f, 1f)

        val paint = Paint().apply {
            isAntiAlias = true
            isFilterBitmap = true
        }
        c.drawBitmap(src, null,
            RectF(dx, dy, dx + dw, dy + dh), paint)
        return canvas
    }
}
