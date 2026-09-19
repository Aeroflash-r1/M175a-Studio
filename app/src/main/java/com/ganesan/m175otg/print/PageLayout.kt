package com.ganesan.m175otg.print

import com.ganesan.m175otg.usb.UsbPrinterConnection
import java.io.ByteArrayOutputStream

/**
 * Page-order + layout layer shared by N-up, reverse order, odd/even-only
 * and booklet printing.
 *
 * BOOKLET MATH (N = logical page count padded to a multiple of 4):
 *   sheet i (1-indexed) of N/4:
 *     front  = [ N - (i-1)*2 ,  (i-1)*2 + 1 ]   (left | right)
 *     back   = [ (i-1)*2 + 2 , N - (i-1)*2 - 1 ] (left | right)
 *
 *   Example N=8: 1st sheet front [8|1], back [2|7]; 2nd front [6|3],
 *   back [4|5]. Fold the stack once and the pages read 1..8 in order.
 *
 * Sheets are printed in a single manual-duplex-style flow: pass 1 prints
 * all FRONT sides, the user flips, pass 2 prints all BACKs. Reuses the
 * flip-prompt flow the user already knows from duplex.
 */
object PageLayout {

    /** Parse "1-3, 5, 8-10" into a 1-based page list. Open ranges clamp
     *  to the last page ("5-" = 5..total). Returns empty on garbage. */
    fun parseRange(expr: String, totalPages: Int): List<Int> {
        val out = LinkedHashSet<Int>()
        for (part in expr.split(',', ';')) {
            val t = part.trim()
            if (t.isEmpty()) continue
            val m = Regex("(\\d+)?\\s*(-|\\u2013|\\u2014)?\\s*(\\d+)?").find(t)
                ?: continue
            val a = m.groupValues[1].toIntOrNull()
            val dash = m.groupValues[2].isNotEmpty()
            val b = m.groupValues[3].toIntOrNull()
            when {
                a == null && b == null -> continue
                a != null && b != null -> {
                    if (a <= b) out.addAll(a..b) else out.addAll(b..a)
                }
                a != null && dash -> out.addAll(a..totalPages)     // "5-"
                a != null -> out.add(a)                            // "5"
                b != null -> out.addAll(1..b)                      // "-5"
            }
        }
        return out.filter { it in 1..totalPages }
    }

    /** Reduce a full 1..n list according to the odd/even-only toggle. */
    fun filterParity(pages: List<Int>, oddOnly: Boolean?, n: Int): List<Int> =
        when (oddOnly) {
            null -> pages
            true -> pages.filter { it % 2 == 1 }
            false -> pages.filter { it % 2 == 0 }
        }.ifEmpty { emptyList() }.let { if (it.isEmpty() && oddOnly != null && n > 0) it else it }

    /**
     * Booklet imposition: returns the sheet list in print order.
     * Each sheet = Pair(frontPages, backPages), each side = two logical
     * page numbers (left, right) or null for the blanks used as padding.
     */
    fun bookletSheets(totalPages: Int): List<Pair<List<Int?>, List<Int?>>> {
        val n = ((totalPages + 3) / 4) * 4          // pad to multiple of 4
        val sheets = ArrayList<Pair<List<Int?>, List<Int?>>>(n / 4)
        for (i in 1..n / 4) {
            val front = listOf<Int?>(
                if (n - (i - 1) * 2 <= totalPages) n - (i - 1) * 2 else null,
                if ((i - 1) * 2 + 1 <= totalPages) (i - 1) * 2 + 1 else null)
            val back = listOf<Int?>(
                if ((i - 1) * 2 + 2 <= totalPages) (i - 1) * 2 + 2 else null,
                if (n - (i - 1) * 2 - 1 <= totalPages) n - (i - 1) * 2 - 1 else null)
            sheets.add(front to back)
        }
        return sheets
    }

    /**
     * Compose one sheet image: two A4-portrait page JPEGs side by side onto
     * a landscape canvas. Both sides null = blank sheet (booklet padding).
     * Returns the sheet JPEG (2*pageW x pageH pixels).
     */
    fun composeTwoUp(
        left: ByteArray?, right: ByteArray?, dpi: Int,
        grayscale: Boolean, pageW: Int, pageH: Int,
    ): ByteArray {
        val sheetW = pageW * 2
        val sheetH = pageH
        val canvas = android.graphics.Bitmap.createBitmap(
            sheetW, sheetH, android.graphics.Bitmap.Config.RGB_565)
        val c = android.graphics.Canvas(canvas)
        c.drawColor(android.graphics.Color.WHITE)
        var x = 0
        for (src in listOf(left, right)) {
            if (src != null) {
                val page = decode(src, pageW, pageH, dpi)
                if (page != null) {
                    c.drawBitmap(page, x.toFloat(),
                        ((sheetH - page.height) / 2f), null)
                    page.recycle()
                }
            }
            x += pageW
        }
        val baos = ByteArrayOutputStream(sheetW * sheetH / 6 + 64)
        canvas.compress(android.graphics.Bitmap.CompressFormat.JPEG,
            if (grayscale) 75 else 82, baos)
        canvas.recycle()
        return baos.toByteArray()
    }

    /**
     * Compose a 4-up sheet: four A4-portrait pages in a 2x2 grid on ONE
     * portrait A4 canvas, each at 50% scale. Reading order TL, TR, BL, BR.
     * Any null quadrant stays white (odd page counts).
     */
    fun composeFourUp(
        pages: List<ByteArray?>, dpi: Int, grayscale: Boolean,
        pageW: Int, pageH: Int,
    ): ByteArray {
        val sheetW = pageW * 2
        val sheetH = pageH * 2
        val canvas = android.graphics.Bitmap.createBitmap(
            sheetW, sheetH, android.graphics.Bitmap.Config.RGB_565)
        val c = android.graphics.Canvas(canvas)
        c.drawColor(android.graphics.Color.WHITE)
        val positions = listOf(0 to 0, pageW to 0, 0 to pageH, pageW to pageH)
        positions.forEachIndexed { i, (px, py) ->
            val src = pages.getOrNull(i) ?: return@forEachIndexed
            val page = decode(src, pageW, pageH, dpi) ?: return@forEachIndexed
            c.drawBitmap(page, px.toFloat(), py.toFloat(), null)
            page.recycle()
        }
        val baos = ByteArrayOutputStream(sheetW * sheetH / 8 + 64)
        canvas.compress(android.graphics.Bitmap.CompressFormat.JPEG,
            if (grayscale) 75 else 82, baos)
        canvas.recycle()
        return baos.toByteArray()
    }

    /** Decode a page JPEG capped to the sheet's own pageW x pageH. */
    private fun decode(jpeg: ByteArray, pageW: Int, pageH: Int, dpi: Int):
            android.graphics.Bitmap? {
        val bounds = android.graphics.BitmapFactory.Options()
            .apply { inJustDecodeBounds = true }
        android.graphics.BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, bounds)
        if (bounds.outWidth <= 0) return null
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= pageW &&
            bounds.outHeight / (sample * 2) >= pageH) sample *= 2
        return android.graphics.BitmapFactory.decodeByteArray(
            jpeg, 0, jpeg.size,
            android.graphics.BitmapFactory.Options().apply {
                inSampleSize = sample
                inPreferredConfig = android.graphics.Bitmap.Config.RGB_565
            })
    }
}
