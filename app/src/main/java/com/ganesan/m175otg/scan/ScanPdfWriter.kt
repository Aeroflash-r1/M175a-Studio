package com.ganesan.m175otg.scan

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.pdf.PdfDocument
import java.io.File
import java.io.OutputStream

/**
 * Multi-page scan → single PDF. Page size = the scan's true physical size
 * (pixels ÷ scan dpi), so a 300 dpi scan of A4 produces a real A4 PDF.
 * Greyscale/colour preserved as encoded by the scanner.
 */
object ScanPdfWriter {

    /**
     * @param jpegs   scan JPEGs in page order
     * @param scanDpi the dpi the scans were REQUESTED at (page sizing) —
     *                the engine may deliver a different native size, so the
     *                page rect is derived from the bitmap's aspect + dpi and
     *                the bitmap is SCALED into that rect (drawing at pixel
     *                size caused the 'cut-off page' PDF bug: a 5100px-wide
     *                bitmap on a 612pt page spills 63% off the right edge).
     * @param out     destination stream (MediaStore or file)
     */
    fun writePdf(jpegs: List<ByteArray>, scanDpi: Int, out: OutputStream) {
        val doc = PdfDocument()
        try {
            for ((i, jpeg) in jpegs.withIndex()) {
                val bmp = decode(jpeg) ?: continue
                // TRUE page size from the requested dpi (A4-ish aspect comes
                // out automatically; letter scans produce letter pages).
                val pw = (bmp.width * 72f / scanDpi).toInt().coerceAtLeast(1)
                val ph = (bmp.height * 72f / scanDpi).toInt().coerceAtLeast(1)
                val info = PdfDocument.PageInfo.Builder(pw, ph, i + 1).create()
                val page = doc.startPage(info)
                val c = page.canvas
                c.drawColor(Color.WHITE)
                // Scale the WHOLE bitmap into the page rect — never crop.
                val paint = android.graphics.Paint().apply {
                    isAntiAlias = true
                    isFilterBitmap = true
                }
                c.drawBitmap(bmp, null,
                    android.graphics.RectF(0f, 0f, pw.toFloat(), ph.toFloat()),
                    paint)
                doc.finishPage(page)
                bmp.recycle()
            }
            doc.writeTo(out)
        } finally {
            doc.close()
        }
    }

    /** Sub-sampled decode — a 1200 dpi scan must not OOM the PDF writer. */
    private fun decode(jpeg: ByteArray): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (bounds.outWidth / (sample * 2).toLong() *
            bounds.outHeight / (sample * 2).toLong() > 24_000_000) sample *= 2
        return BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size,
            BitmapFactory.Options().apply {
                inSampleSize = sample
                inPreferredConfig = Bitmap.Config.RGB_565
            })
    }

    /** Convenience for cache-dir staging. */
    fun toFile(jpegs: List<ByteArray>, scanDpi: Int, file: File): File {
        file.outputStream().use { writePdf(jpegs, scanDpi, it) }
        return file
    }
}
