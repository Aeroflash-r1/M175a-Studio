package com.ganesan.m175otg.scan

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.Canvas
import android.graphics.Paint
import java.io.ByteArrayOutputStream

/**
 * Client-side auto-levels for scans — the same trick HP's own Windows
 * driver plays (measured: native sensor output 127/255 brightness vs
 * 238/255 after the driver's correction).
 *
 * Strategy: decode at reduced size, measure the 1st percentile (black
 * point) and 99th percentile (white point) of luminance. Only if the
 * image actually measures dark (white point < 210) do we apply a
 * ColorMatrix scale — otherwise the JPEG is returned untouched, so good
 * scans never get degraded.
 */
object ScanAutoLevels {

    private const val WHITE_POINT_TRIGGER = 210   // below this = "dim scan"
    private const val BLACK_TRIGGER = 40          // below this = "black scan"
    private const val SAMPLE_DIM = 128            // analysis bitmap size

    /** What the last fix() did — surfaced in the UI to explain odd output. */
    @Volatile var lastAction: String = ""
        private set

    /** Channel spread of the last scan (max-min of R/G/B means). >=60 = rainbow signature. */
    @Volatile var lastSpread: Int = 0
        private set

    /**
     * True when the last scan FAILED the integrity gate — unreadable JPEG,
     * a truncated decode, rainbow channels, or flat saturated bands (the
     * DC-desync signature). The UI auto-retries once on this flag instead
     * of silently saving a corrupt page.
     */
    @Volatile var lastCorrupt: Boolean = false
        private set

    /** How many flat bands the last scan had (0-8). */
    @Volatile var lastFlatBands: Int = 0
        private set

    /** Pixels at/above which Bitmap ops need sub-sampled decoding (a full
     *  1200 dpi A4 page is 9921x14032 ARGB = ~530 MB — will OOM the app). */
    private const val BIG_PIXELS = 16_000_000L

    /** Decode a possibly-huge scan without OOM. Powers of two only — a full
     *  bilinear resample of a 30 MB bitmap can itself OOM, so scale first
     *  via inSampleSize then bilinear. */
    private fun decodeScaled(jpeg: ByteArray, targetW: Int, targetH: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while ((bounds.outWidth / (sample * 2).toLong()) >= targetW &&
               (bounds.outHeight / (sample * 2).toLong()) >= targetH) sample *= 2
        val opts = BitmapFactory.Options().apply {
            inSampleSize = sample
            inPreferredConfig = Bitmap.Config.RGB_565
        }
        return BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, opts)
    }

    /** Recompress a bitmap to JPEG, capping quality so huge pages stay
     *  storable (1200 dpi at q92 would be ~15 MB; q85 keeps it ~6-8 MB). */
    private fun encodeJpeg(bmp: Bitmap, quality: Int): ByteArray {
        val q = if (bmp.width * bmp.height.toLong() > BIG_PIXELS) minOf(quality, 85) else quality
        val baos = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, q, baos)
        return baos.toByteArray()
    }

    /**
     * Resample a scan to the user-requested dpi.
     *
     * PROVEN (Sept 2026, both LEDM and HP's own wscn protocol): the M175a
     * CCD delivers coherent data ONLY at its native 300 dpi lattice — at
     * 150/200 the engine's line decimation mangles RGB channels (spread
     * 94-143) on EVERY transport. HP's Windows driver repairs non-native
     * resolutions in software by resampling the native stream.
     *
     * 600 and 1200 dpi are REAL engine steps (600 = CCD sub-step, 1200 =
     * PlatenOpticalResolution from the printer's own ScannerConfiguration)
     * so they pass through untouched. Only downsampling happens here:
     * 150 = 300x0.5, 200 = 300x2/3.
     */
    fun downsampleToDpi(jpeg: ByteArray, requestedDpi: Int, nativeDpi: Int): ByteArray {
        if (requestedDpi >= nativeDpi) return jpeg
        val src = decodeScaled(jpeg, 1, 1) ?: return jpeg
        val w = (src.width.toLong() * requestedDpi / nativeDpi).toInt()
            .coerceIn(1, src.width)
        val h = (src.height.toLong() * requestedDpi / nativeDpi).toInt()
            .coerceIn(1, src.height)
        val out = Bitmap.createScaledBitmap(src, w, h, true)
        val bytes = encodeJpeg(out, 92)
        if (out !== src) out.recycle()
        src.recycle()
        lastAction = "native ${nativeDpi}dpi → resampled to ${requestedDpi}dpi (${w}x$h)"
        return bytes
    }

    /**
     * True lineart: adaptive threshold to pure 1-bit-style B/W. The scanner
     * emits greyscale; a fixed global threshold breaks on uneven lighting,
     * so the threshold adapts to the page's own background level (measured
     * from the histogram). Text = black, paper = white, no grey haze.
     */
    fun toLineart(jpeg: ByteArray): ByteArray {
        val src = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)
            ?: return jpeg
        val w = src.width; val h = src.height
        // background = 90th percentile luminance (paper level)
        val small = Bitmap.createScaledBitmap(src, 128, 128, true)
        val px = IntArray(128 * 128)
        small.getPixels(px, 0, 128, 0, 0, 128, 128)
        small.recycle()
        val lum = IntArray(px.size)
        for (i in px.indices) {
            val p = px[i]
            lum[i] = (0.299f * Color.red(p) + 0.587f * Color.green(p)
                    + 0.114f * Color.blue(p)).toInt().coerceIn(0, 255)
        }
        lum.sort()
        val bg = lum[(lum.size * 0.9f).toInt().coerceAtMost(lum.size - 1)]
        // threshold just below paper white so light grey text survives
        val thr = (bg * 0.72f).toInt().coerceIn(60, 200)

        val out = Bitmap.createBitmap(w, h, Bitmap.Config.RGB_565)
        val row = IntArray(w)
        for (y in 0 until h) {
            src.getPixels(row, 0, w, 0, y, w, 1)
            for (x in 0 until w) {
                val p = row[x]
                val l = (0.299f * Color.red(p) + 0.587f * Color.green(p)
                        + 0.114f * Color.blue(p)).toInt()
                row[x] = if (l < thr) Color.BLACK else Color.WHITE
            }
            out.setPixels(row, 0, w, 0, y, w, 1)
        }
        src.recycle()
        val baos = ByteArrayOutputStream()
        out.compress(Bitmap.CompressFormat.JPEG, 90, baos)
        out.recycle()
        lastAction = "lineart (threshold $thr from bg $bg)"
        return baos.toByteArray()
    }

    fun fix(jpeg: ByteArray): ByteArray {
        // ---- INTEGRITY GATE (no silent corrupt output) -------------------
        // 1. decode check: a stream that will not decode at all is corrupt
        //    (previously this returned the raw bytes and the gallery showed
        //    garbage — the "rainbow file" class of failure).
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, bounds)
        // Huge scans (600/1200 dpi) are decoded SUB-SAMPLED so measurement
        // never allocates a 500 MB bitmap. Sample=1 keeps the exact historic
        // behaviour for 150/200/300 dpi scans.
        var sample = 1
        if (bounds.outWidth > 0 && bounds.outHeight > 0 &&
            bounds.outWidth.toLong() * bounds.outHeight > BIG_PIXELS) {
            while (bounds.outWidth / (sample * 2).toLong() * (bounds.outHeight / (sample * 2).toLong())
                   > BIG_PIXELS / 2) sample *= 2
        }
        val probe = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size,
            BitmapFactory.Options().apply {
                inSampleSize = sample
                if (sample > 1) inPreferredConfig = Bitmap.Config.RGB_565
            })
        if (probe == null) {
            lastCorrupt = true
            lastFlatBands = 0
            lastSpread = 0
            lastAction = "CORRUPT: stream will not decode (${jpeg.size / 1024}KB)"
            return jpeg
        }
        // 2. truncation check: decoder produced fewer rows than the header
        //    declares (accounting for sub-sampling) = the stream was cut.
        val expW = (bounds.outWidth + sample - 1) / sample
        val expH = (bounds.outHeight + sample - 1) / sample
        if (bounds.outWidth > 0 && bounds.outHeight > 0 &&
            (probe.width < expW || probe.height < expH)) {
            lastCorrupt = true
            lastFlatBands = 0
            lastAction = "CORRUPT: truncated decode ${probe.width}x${probe.height} " +
                    "of ${bounds.outWidth}x${bounds.outHeight}"
            probe.recycle()
            return jpeg
 }
        // 3. big scans are already sub-sampled here — every later step works
        //    on `probe` only, so peak memory stays bounded.
        val bigPixels = sample > 1
        val small = Bitmap.createScaledBitmap(
            probe, SAMPLE_DIM, SAMPLE_DIM, true)

        // luminance histogram + per-channel means (rainbow detector:
        // a white page must have R≈G≈B; spread >=60 = channel damage)
        val hist = IntArray(256)
        var rSum = 0L; var gSum = 0L; var bSum = 0L
        val px = IntArray(SAMPLE_DIM * SAMPLE_DIM)
        small.getPixels(px, 0, SAMPLE_DIM, 0, 0, SAMPLE_DIM, SAMPLE_DIM)
        for (p in px) {
            val r = Color.red(p); val g = Color.green(p); val b = Color.blue(p)
            rSum += r; gSum += g; bSum += b
            val l = (0.299f * r + 0.587f * g + 0.114f * b).toInt().coerceIn(0, 255)
            hist[l]++
        }
        val rMean = (rSum / px.size).toInt()
        val gMean = (gSum / px.size).toInt()
        val bMean = (bSum / px.size).toInt()
        lastSpread = maxOf(rMean, gMean, bMean) - minOf(rMean, gMean, bMean)

        // FLAT-BAND scan: entropy desync shows up as whole bands of uniform
        // colour (DC drift / decoder fill). Blank PAGE areas are also flat
        // but NOT saturated, so the corrupt rule requires both.
        var flat = 0
        val bandRows = SAMPLE_DIM / 8
        val n = bandRows * SAMPLE_DIM
        for (band in 0 until 8) {
            val start = band * n
            var mr = 0L; var mg = 0L; var mb = 0L
            for (k in 0 until n) {
                val p = px[start + k]
                mr += Color.red(p); mg += Color.green(p); mb += Color.blue(p)
            }
            val ar = (mr / n).toInt(); val ag = (mg / n).toInt(); val ab = (mb / n).toInt()
            var v = 0.0
            for (k in 0 until n) {
                val p = px[start + k]
                val dr = (Color.red(p) - ar).toDouble()
                val dg = (Color.green(p) - ag).toDouble()
                val db = (Color.blue(p) - ab).toDouble()
                v += dr * dr + dg * dg + db * db
            }
            if (v / n < 50.0) flat++
        }
        lastFlatBands = flat
        lastCorrupt = lastSpread >= 60 || (flat >= 2 && lastSpread >= 35)
        val chan = "[R%d G%d B%d spread%d flat%d]".format(rMean, gMean, bMean, lastSpread, flat)

        val total = px.size
        fun percentile(f: Float): Int {
            var acc = 0
            val target = (total * f).toInt()
            for (i in 0..255) {
                acc += hist[i]
                if (acc >= target) return i
            }
            return 255
        }

        val low = percentile(0.01f)
        val high = percentile(0.99f)
        if (probe !== small) small.recycle()

        // virtually black? the glass is probably empty / lid open /
        // page face-up. Tell the user instead of saving a black page.
        if (high < BLACK_TRIGGER) {
            probe.recycle()
            lastAction = "BLACK (p99=$high) $chan — check page face-down on glass + lid closed"
            return jpeg
        }

        // bright enough? leave the scan untouched — but still report the
        // channel spread so a rainbow scan identifies itself in the log.
        if (high >= WHITE_POINT_TRIGGER) {
            probe.recycle()
            lastAction = if (lastCorrupt)
                "RAINBOW/CORRUPT (spread=$lastSpread flat=$flat) $chan — integrity gate will retry"
            else
                "bright — saved untouched $chan"
            return jpeg
        }

        // stretch [low, high] -> [0, 255] via ColorMatrix
        val range = (high - low).coerceAtLeast(1)
        val scale = 255f / range
        val cm = ColorMatrix(floatArrayOf(
            scale, 0f, 0f, 0f, -low * scale,
            0f, scale, 0f, 0f, -low * scale,
            0f, 0f, scale, 0f, -low * scale,
            0f, 0f, 0f, 1f, 0f,
        ))

        // probe is already sub-sampled for huge scans, so the leveled output
        // is written at the sampled resolution — never a second full-size ARGB.
        val outCfg = if (bigPixels) Bitmap.Config.RGB_565 else Bitmap.Config.ARGB_8888
        val out = Bitmap.createBitmap(probe.width, probe.height, outCfg)
        Canvas(out).drawBitmap(
            probe, 0f, 0f,
            Paint().apply { colorFilter = ColorMatrixColorFilter(cm) })
        probe.recycle()

        val bytes = encodeJpeg(out, 92)
        out.recycle()
        lastAction = "dim (p99=$high) — auto-leveled $chan"
        if (lastCorrupt) lastAction += " — CORRUPT (will retry)"
        return bytes
    }
}
