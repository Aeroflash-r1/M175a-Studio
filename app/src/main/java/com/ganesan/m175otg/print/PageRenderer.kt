package com.ganesan.m175otg.print

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.pdf.PdfRenderer
import android.os.ParcelFileDescriptor
import com.ganesan.m175otg.usb.UsbPrinterConnection
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.InputStream
import java.util.concurrent.TimeUnit
import kotlin.math.roundToInt

/**
 * Renders documents to page bitmaps at the chosen DPI, then JPEG-encodes
 * them for the PCL XL image operator (CompressMode=2 - printer decompresses).
 *
 * DPI notes (verified on the M175a):
 *  - 300 dpi: fast, good for text        (A4 = 2480x3508 px)
 *  - 600 dpi: driver default, sharpest   (A4 = 4961x7016 px)
 * Paper size / printable area come from [Paper] (A4 printable area at
 * 600 dpi = 4760x6735 printer units, captured from the Windows driver).
 */
object PageRenderer {

    data class RenderedPage(val jpeg: ByteArray, val width: Int, val height: Int)

    /** Renders each PDF page to JPEG at [dpi] (used by duplex: needs all pages). */
    fun renderPdf(pdf: File, dpi: Int, grayscale: Boolean): List<RenderedPage> {
        val scale = dpi / 72f
        val pages = mutableListOf<RenderedPage>()
        ParcelFileDescriptor.open(pdf, ParcelFileDescriptor.MODE_READ_ONLY)
            .use { fd ->
                PdfRenderer(fd).use { renderer ->
                    for (i in 0 until renderer.pageCount) {
                        renderer.openPage(i).use { page ->
                            pages.add(renderPageToJpeg(page, scale, grayscale))
                        }
                    }
                }
            }
        return pages
    }

    /**
     * STREAMING PDF print: renders one page at a time and transmits it as
     * part of a single PCL XL session. Only ONE page bitmap + ONE JPEG is
     * alive at any moment — safe for any page count.
     */
    fun streamPdfJob(
        usb: UsbPrinterConnection,
        pdf: File,
        dpi: Int,
        grayscale: Boolean,
        jobName: String = "OTG-PDF",
        onStatus: (String) -> Unit = {},
    ): PrintTransmitter.Result {
        val scale = dpi / 72f
        ParcelFileDescriptor.open(pdf, ParcelFileDescriptor.MODE_READ_ONLY)
            .use { fd ->
                PdfRenderer(fd).use { renderer ->
                    val total = renderer.pageCount
                    if (total <= 0) return PrintTransmitter.Result.Failed(0, "no pages")

                    // ---- RENDER-AHEAD PIPELINE -------------------------------
                    // The printer pulls data slowly (its engine is the real
                    // limit), so while page N is being transmitted the phone
                    // should already be rendering page N+1. Rendering and
                    // sending therefore run on two threads with a 1-page
                    // buffer: render/JPEG time disappears from the critical
                    // path instead of adding to every page.
                    val queue = java.util.concurrent.ArrayBlockingQueue<Any>(2)
                    val end = Any()
                    val renderError = java.util.concurrent.atomic
                        .AtomicReference<Throwable?>()

                    val producer = Thread({
                        try {
                            for (i in 0 until total) {
                                if (JobControl.isCancelled) break
                                val t0 = System.currentTimeMillis()
                                val page = renderer.openPage(i)
                                val rp = try {
                                    renderPageToJpeg(page, scale, grayscale)
                                } finally {
                                    page.close()
                                }
                                android.util.Log.d("M175",
                                    "render page ${i + 1}/$total: " +
                                            "${System.currentTimeMillis() - t0}ms, " +
                                            "${rp.jpeg.size / 1024}KB @${rp.width}x${rp.height}")
                                queue.put(PrintTransmitter.RenderedPage(
                                    rp.jpeg, rp.width, rp.height, i + 1, total))
                            }
                        } catch (_: InterruptedException) {
                            // consumer went away (cancel) — stop rendering
                        } catch (t: Throwable) {
                            renderError.set(t)
                        } finally {
                            queue.clear()
                            runCatching { queue.offer(end, 200, TimeUnit.MILLISECONDS) }
                        }
                    }, "m175-render")
                    producer.isDaemon = true
                    producer.start()

                    try {
                        val res = PrintTransmitter.sendPages(
                            usb, dpi, grayscale, jobName,
                            source = { _ ->
                                val item: Any? = try {
                                    queue.take()
                                } catch (_: InterruptedException) {
                                    null
                                }
                                if (item == null || item === end) null
                                else item as PrintTransmitter.RenderedPage
                            },
                            onStatus = onStatus,
                        )
                        if (res is PrintTransmitter.Result.Failed) {
                            renderError.get()?.let {
                                return PrintTransmitter.Result.Failed(
                                    0, "render failed: ${it.message}")
                            }
                        }
                        return res
                    } finally {
                        // never leave the render thread holding PdfRenderer
                        producer.interrupt()
                        producer.join(4_000)
                    }
                }
            }
    }

    /**
     * Rasterizes a PDF page at [scale] px/point into a white-backed bitmap.
     *
     * MUST be ARGB_8888: PdfRenderer.Page.render() throws
     * IllegalArgumentException("Unsupported pixel format") for anything
     * else (RGB_565 broke real prints with 'Print error: Unsupported pixel
     * format'). The JPEG encoder right after us reclaims the memory.
     */
    fun renderPageBitmap(page: PdfRenderer.Page, scale: Float): Bitmap {
        val w = (page.width * scale).roundToInt()
        val h = (page.height * scale).roundToInt()
        val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        Canvas(bmp).drawColor(Color.WHITE)
        page.render(bmp, null, null, PdfRenderer.Page.RENDER_MODE_FOR_PRINT)
        return bmp
    }

    /** Raster + JPEG in one step (the normal print pipeline). */
    fun renderPageToJpeg(page: PdfRenderer.Page, scale: Float,
                         grayscale: Boolean): RenderedPage {
        val bmp = renderPageBitmap(page, scale)
        return toJpegPage(bmp, grayscale)
    }

    /** Renders a single image file (JPEG/PNG from gallery) to one page. */
    fun renderImage(src: Bitmap, dpi: Int, grayscale: Boolean,
                    paper: Paper = Paper.A4): RenderedPage {
        // center-fit onto a full sheet canvas of the selected paper
        val (w, h) = paper.pagePx(dpi, landscape = false)
        val page = Bitmap.createBitmap(w, h, Bitmap.Config.RGB_565)
        val c = Canvas(page)
        c.drawColor(Color.WHITE)
        val s = minOf(
            w.toFloat() / src.width,
            h.toFloat() / src.height
        )
        val dw = (src.width * s).toInt()
        val dh = (src.height * s).toInt()
        c.drawBitmap(
            src, null,
            android.graphics.RectF((w - dw) / 2f, (h - dh) / 2f,
                (w - dw) / 2f + dw, (h - dh) / 2f + dh),
            null
        )
        return toJpegPage(page, grayscale)
    }

    /** JPEG-encodes an already-composed page bitmap (PagePlacement path). */
    fun finishPlacedPage(placed: Bitmap, grayscale: Boolean): RenderedPage =
        toJpegPage(placed, grayscale)

    /**
     * Payload size drives two real costs: USB time AND the printer's own JPEG
     * decode (it decodes every page before printing). 90 was wasteful — at
     * these resolutions 82 (colour) / 70 (greyscale) is visually identical on
     * paper while cutting bytes by roughly a third.
     */
    private fun jpegQuality(grayscale: Boolean, width: Int): Int = when {
        grayscale -> 70
        width > 4000 -> 85   // 600 dpi colour keeps detail
        else -> 82
    }

    private fun toJpegPage(bmp: Bitmap, grayscale: Boolean): RenderedPage {
        val use = if (grayscale) {
            // luminance conversion -> smaller JPEG, printer eGray colorspace
            val g = Bitmap.createBitmap(bmp.width, bmp.height, Bitmap.Config.RGB_565)
            val cm = android.graphics.ColorMatrixColorFilter(
                android.graphics.ColorMatrix().apply { setSaturation(0f) })
            val p = android.graphics.Paint()
            p.colorFilter = cm
            val c = Canvas(g)
            c.drawColor(Color.WHITE)
            c.drawBitmap(bmp, 0f, 0f, p)
            g
        } else bmp

        val outW = use.width
        val outH = use.height
        val baos = ByteArrayOutputStream(bmp.byteCount / 3 + 64 * 1024)
        use.compress(Bitmap.CompressFormat.JPEG, jpegQuality(grayscale, outW), baos)
        val jpeg = baos.toByteArray()
        if (use !== bmp) use.recycle()
        bmp.recycle()
        return RenderedPage(jpeg, outW, outH)
    }

    /** Streams bytes through the USB print endpoint with progress. */
    fun transmit(
        usb: UsbPrinterConnection,
        data: ByteArray,
        onProgress: (Long, Long) -> Unit = { _, _ -> },
    ): PrintTransmitter.Result =
        PrintTransmitter.send(usb, data.inputStream(), data.size.toLong(), onProgress)
}
