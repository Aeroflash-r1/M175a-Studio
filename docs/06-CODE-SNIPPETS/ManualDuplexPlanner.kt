package com.example.m175print.core.render

/**
 * Manual duplex planner for the M175a (no auto-duplex hardware).
 *
 * Strategy: print EVEN pages first, in REVERSE order. When the stack is
 * reinserted blank-side-up, the printer then prints ODD pages on the backs
 * in forward order — pages come out correctly collated.
 *
 * For long-edge flip vs short-edge flip, offset calibration knobs handle
 * the ±2mm skew of re-fed sheets on this engine.
 */
data class DuplexPlan(
    val firstPass: List<Int>,    // page numbers, print order
    val secondPass: List<Int>,
    val flipInstruction: String  // shown to the user between passes
)

class ManualDuplexPlanner(
    private val totalPages: Int,
    private val flipLongEdge: Boolean = true,   // portrait docs: usually long
    private val backOffsetXMm: Float = 0f,      // calibrate in Settings
    private val backOffsetYMm: Float = 0f
) {
    fun plan(): DuplexPlan {
        val evens = (2..totalPages step 2).toList().reversed()
        val odds = (1..totalPages step 2).toList()
        val flip = if (flipLongEdge)
            "Take the stack, keep the SAME edge at the top, flip it over like a book page (blank side up) and reinsert."
        else
            "Take the stack, ROTATE it 180°, then flip over (blank side up) and reinsert."
        return DuplexPlan(evens, odds, flip)
    }

    /** Apply user calibration to second-pass pages (shift render, not data). */
    fun applyBackOffset(bitmap: android.graphics.Bitmap,
                        dpi: Int): android.graphics.Bitmap {
        val dx = (backOffsetXMm / 25.4f * dpi).toInt()
        val dy = (backOffsetYMm / 25.4f * dpi).toInt()
        if (dx == 0 && dy == 0) return bitmap
        val out = android.graphics.Bitmap.createBitmap(
            bitmap.width, bitmap.height, android.graphics.Bitmap.Config.ARGB_8888)
        val c = android.graphics.Canvas(out)
        c.drawBitmap(bitmap, dx.toFloat(), dy.toFloat(), null)
        return out
    }
}
