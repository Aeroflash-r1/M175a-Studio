package com.ganesan.m175otg.print

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.pdf.PdfRenderer
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.ParcelFileDescriptor
import android.print.PrintAttributes
import android.print.PrintJobInfo
import android.print.PrinterId
import android.print.PrinterCapabilitiesInfo
import android.print.PrinterInfo
import android.printservice.PrintDocument
import android.printservice.PrintJob
import android.printservice.PrintService
import android.printservice.PrinterDiscoverySession
import com.ganesan.m175otg.usb.UsbPrinterConnection
import java.io.File
import kotlin.concurrent.thread
import kotlin.math.roundToInt

/**
 * System PrintService — makes the M175a appear in Android's NATIVE print
 * dialog (Chrome, Gmail, Docs, any app with a Print option). This is the
 * Windows-driver parity feature: every app can print without opening this
 * app.
 *
 * The framework hands us a finished PDF (already paginated, page ranges
 * applied). We render at 300 dpi and stream PCL XL over the same USB path
 * the app uses. Copies are repeated page sequences (collated).
 */
class M175PrintService : PrintService() {

    companion object {
        /** Set while a system print job streams — the app defers to it. */
        @Volatile var serviceBusy: Boolean = false
            private set

        private const val RENDER_DPI = 300
    }

    @Volatile private var cancelled = false

    /**
     * SHARED CONNECTION: the app process owns the USB interface claim.
     * Opening a second UsbDeviceConnection while the app is alive makes the
     * service-side claim fail (or steal it and wedge the app) — the classic
     * 'printing from other apps does not work' bug. The bridge hands over
     * the app's live connection, or opens a fresh one when the app is dead.
     */
    private var sharedConn: UsbPrinterConnection? = null

    override fun onRequestCancelPrintJob(job: PrintJob) {
        cancelled = true
        JobControl.requestCancel()
    }

    override fun onPrintJobQueued(job: PrintJob) {
        serviceBusy = true
        thread(name = "m175-printjob") {
            try {
                runJob(job)
            } finally {
                serviceBusy = false
            }
        }
    }

    // ----------------------------------------------------------- discovery

    override fun onCreatePrinterDiscoverySession(): PrinterDiscoverySession =
        M175DiscoverySession(this)

    /** Static single printer announced the moment discovery starts. */
    private class M175DiscoverySession(private val svc: M175PrintService) :
        PrinterDiscoverySession() {

        private fun printerCaps(id: PrinterId): PrinterCapabilitiesInfo =
            PrinterCapabilitiesInfo.Builder(id)
                .addMediaSize(PrintAttributes.MediaSize.ISO_A4, true)
                .addMediaSize(PrintAttributes.MediaSize.NA_LETTER, false)
                .addResolution(PrintAttributes.Resolution(
                    "r300", "300 dpi", RENDER_DPI, RENDER_DPI), true)
                .setColorModes(
                    PrintAttributes.COLOR_MODE_COLOR or
                            PrintAttributes.COLOR_MODE_MONOCHROME,
                    PrintAttributes.COLOR_MODE_COLOR)
                .setMinMargins(PrintAttributes.Margins(0, 0, 0, 0))
                .build()

        override fun onStartPrinterDiscovery(priorityList: List<PrinterId>) {
            val id = svc.generatePrinterId("M175a-OTG")
            addPrinters(listOf(PrinterInfo.Builder(
                id, "HP M175a (USB OTG)", PrinterInfo.STATUS_IDLE)
                .setCapabilities(printerCaps(id))
                .build()))
        }

        override fun onStopPrinterDiscovery() {}
        override fun onValidatePrinters(p: List<PrinterId>) {}
        override fun onStartPrinterStateTracking(id: PrinterId) {}
        override fun onStopPrinterStateTracking(id: PrinterId) {}
        override fun onDestroy() {}
    }

    // ------------------------------------------------------------- the job

    private fun runJob(job: PrintJob) {
        cancelled = false
        var docFile: File? = null
        try {
            if (!job.isQueued) return
            job.start()

            val info = job.info
            val ranges = info.pages?.takeIf { arr ->
                arr.isNotEmpty() && arr[0] != android.print.PageRange.ALL_PAGES
            }
            val copies = info.copies.coerceAtLeast(1)
            val mono = info.attributes?.colorMode ==
                    PrintAttributes.COLOR_MODE_MONOCHROME

            if (JobControl.active) {
                job.fail("the M175 app is printing - try again when it finishes")
                return
            }

            val dev = findPrinter() ?: run {
                job.fail("printer not connected via OTG"); return
            }
            if (!ensurePermission(dev)) {
                job.fail("USB permission not granted"); return
            }
            val conn = PrintConnectionBridge.acquire(this)
            sharedConn = conn
            if (!conn.open(dev)) {
                job.fail("could not open USB device"); return
            }

            // The framework may hand the document as a PIPE fd — copy it to
            // a seekable file or PdfRenderer will fail.
            val doc: PrintDocument = job.document
            val f = File(cacheDir, "system-print-${System.currentTimeMillis()}.pdf")
            ParcelFileDescriptor.AutoCloseInputStream(doc.data).use { ins ->
                f.outputStream().use { ins.copyTo(it) }
            }
            docFile = f

            // Paper size from the system print dialog (A4/Letter/Legal/A5/
            // Executive); pages are fitted onto that sheet, aspect kept.
            val paper = paperFor(info.attributes)
            val (sheetW, sheetH) = paper.pagePx(RENDER_DPI, false)

            // Flatten selected pages x copies into the ordered page plan.
            data class Plan(val pageInDoc: Int, val w: Int, val h: Int)
            val plan = ArrayList<Plan>()
            ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY).use { fd ->
                PdfRenderer(fd).use { r ->
                    for (p in 0 until r.pageCount) {
                        val selected = ranges == null || ranges.any { rg ->
                            p + 1 >= rg.start && p + 1 <= rg.end
                        }
                        if (selected) {
                            r.openPage(p).use { pg ->
                                repeat(copies) {
                                    plan.add(Plan(p, sheetW, sheetH))
                                }
                            }
                        }
                    }
                }
            }
            if (plan.isEmpty()) { job.fail("no pages selected"); return }

            JobControl.begin()
            val total = plan.size
            var idx = 0
            val res = PrintTransmitter.sendPages(
                conn, RENDER_DPI, mono, "SYSTEM-PRINT",
                paper = paper,
                source = { _ ->
                    if (cancelled || JobControl.isCancelled) null
                    else {
                        val p = plan.getOrNull(idx++)
                        if (p == null) null
                        else PrintTransmitter.RenderedPage(
                            renderOne(f, p.pageInDoc, p.w, p.h, mono),
                            p.w, p.h, idx, total)
                    }
                },
                onStatus = {
                    android.util.Log.d("M175", "service: $it")
                    job.setProgress(idx / total.toFloat())
                },
            )
            JobControl.end()
            f.delete()
            when (res) {
                is PrintTransmitter.Result.Ok -> job.complete()
                is PrintTransmitter.Result.Cancelled -> job.cancel()
                is PrintTransmitter.Result.Failed -> job.fail(res.reason)
            }
        } catch (e: Exception) {
            android.util.Log.d("M175", "service job failed: ${e.message}")
            try { job.fail(e.message ?: "error") } catch (_: Exception) {}
        } finally {
            docFile?.delete()
            PrintConnectionBridge.release(sharedConn)
            sharedConn = null
        }
    }

    /** Render one page of the copied document to JPEG at service resolution. */
    private fun renderOne(doc: File, pageNo: Int, w: Int, h: Int,
                          grayscale: Boolean): ByteArray {
        ParcelFileDescriptor.open(doc, ParcelFileDescriptor.MODE_READ_ONLY).use { fd ->
            PdfRenderer(fd).use { r ->
                r.openPage(pageNo).use { page ->
                    // ARGB_8888 required: PdfRenderer rejects RGB_565 with
                    // IllegalArgumentException("Unsupported pixel format")
                    val sw = (page.width * RENDER_DPI / 72f).roundToInt()
                    val sh = (page.height * RENDER_DPI / 72f).roundToInt()
                    val bmp = Bitmap.createBitmap(sw, sh, Bitmap.Config.ARGB_8888)
                    Canvas(bmp).drawColor(Color.WHITE)
                    page.render(bmp, null, null,
                        PdfRenderer.Page.RENDER_MODE_FOR_PRINT)
                    // fit onto the selected sheet (centered, aspect preserved)
                    // instead of stretching it to the chosen paper
                    val fitted = if (sw != w || sh != h) {
                        PagePlacement.render(bmp, w, h,
                            PagePlacement.Placement(), RENDER_DPI).also {
                            bmp.recycle()
                        }
                    } else bmp
                    val use = if (grayscale) {
                        val g = Bitmap.createBitmap(w, h, Bitmap.Config.RGB_565)
                        val c = Canvas(g); c.drawColor(Color.WHITE)
                        c.drawBitmap(fitted, 0f, 0f, android.graphics.Paint().apply {
                            colorFilter = android.graphics.ColorMatrixColorFilter(
                                android.graphics.ColorMatrix()
                                    .apply { setSaturation(0f) })
                        })
                        g
                    } else fitted
                    val out = java.io.ByteArrayOutputStream(w * h / 4)
                    use.compress(Bitmap.CompressFormat.JPEG, 82, out)
                    if (use !== fitted) use.recycle()
                    fitted.recycle()
                    return out.toByteArray()
                }
            }
        }
    }

    /** Map the system print dialog's paper choice onto our [Paper] sizes. */
    private fun paperFor(a: PrintAttributes?): Paper {
        val m = a?.mediaSize ?: return Paper.A4
        val short = minOf(m.widthMils, m.heightMils)
        val long = maxOf(m.widthMils, m.heightMils)
        fun near(v: Int, ref: Int) = kotlin.math.abs(v - ref) <= 200
        return when {
            near(short, 8268) && near(long, 11693) -> Paper.A4
            near(short, 8500) && near(long, 11000) -> Paper.LETTER
            near(short, 8500) && near(long, 14000) -> Paper.LEGAL
            near(short, 5827) && near(long, 8268) -> Paper.A5
            near(short, 7250) && near(long, 10500) -> Paper.EXECUTIVE
            else -> Paper.A4
        }
    }

    // ------------------------------------------------------------------ usb

    private fun findPrinter(): UsbDevice? {
        val um = getSystemService(Context.USB_SERVICE) as UsbManager
        return um.deviceList.values.firstOrNull {
            it.vendorId == UsbPrinterConnection.HP_VENDOR_ID
        }
    }

    /** Blocks until USB permission exists (already granted or user OKs). */
    private fun ensurePermission(dev: UsbDevice): Boolean {
        val um = getSystemService(Context.USB_SERVICE) as UsbManager
        if (um.hasPermission(dev)) return true
        val granted = java.util.concurrent.atomic.AtomicBoolean(false)
        val latch = java.util.concurrent.CountDownLatch(1)
        val rx = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, i: Intent?) {
                granted.set(
                    UsbPrinterConnection.ACTION_USB_PERMISSION == i?.action &&
                            i.getBooleanExtra(
                                UsbManager.EXTRA_PERMISSION_GRANTED, false))
                latch.countDown()
            }
        }
        androidx.core.content.ContextCompat.registerReceiver(
            this, rx, IntentFilter(UsbPrinterConnection.ACTION_USB_PERMISSION),
            androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED)
        val pi = android.app.PendingIntent.getBroadcast(
            this, 7001,
            Intent(UsbPrinterConnection.ACTION_USB_PERMISSION)
                .setPackage(packageName),
            android.app.PendingIntent.FLAG_MUTABLE)
        um.requestPermission(dev, pi)
        latch.await(90, java.util.concurrent.TimeUnit.SECONDS)
        try { unregisterReceiver(rx) } catch (_: Exception) {}
        return granted.get()
    }
}
