package com.example.m175print.core.protocol

import java.io.ByteArrayOutputStream
import java.io.OutputStream

/**
 * Mono (1-bit) PCL5 raster writer — the simplest reliable print path for
 * the M175a. Render each page as a Bitmap, feed rows here, done.
 *
 * Default 600 dpi matches the engine. Use 300 for fast drafts.
 */
class Pcl5MonoWriter(private val out: OutputStream, private val dpi: Int = 600) {

    private fun cmd(s: String) = out.write(s.toByteArray(Charsets.US_ASCII))

    fun beginJob() {
        cmd("\u001bE")                          // printer reset
        cmd("\u001b&l0O")                       // portrait
        cmd("\u001b&l1S")                       // simplex (this model has no duplex)
        cmd("\u001b*t${dpi}R")                  // resolution
    }

    /** A4/Letter page size: 0=letter 26=A4 — call before startPage if needed. */
    fun setPaperA4() = cmd("\u001b&l26A\u001b&l0O")

    fun startPage() = cmd("\u001b*r0F")         // start graphics, left offset 0

    /**
     * Write one page. bitmap must be 1bpp-equivalent: we read pixel==dark.
     * Rows are sent with the PCL5 row protocol; compression = RLE (method 2).
     */
    fun writePage(bitmap: android.graphics.Bitmap) {
        val w = bitmap.width
        val h = bitmap.height
        val rowBytes = (w + 7) / 8
        val px = IntArray(w)
        val row = ByteArray(rowBytes)

        for (y in 0 until h) {
            bitmap.getPixels(px, 0, w, 0, y, w, 1)
            java.util.Arrays.fill(row, 0)
            var b = 0; var bi = 7
            var any = false
            for (x in 0 until w) {
                if ((px[x] and 0xFF) < 128) {          // luminance → dark bit
                    row[b] = (row[b].toInt() or (1 shl bi)).toByte()
                    any = true
                }
                if (--bi < 0) { bi = 7; b++ }
            }
            cmd("\u001b*a${y}Y")                       // move to row y
            if (!any) {
                cmd("\u001b*b0W")                      // blank row, skip data
            } else {
                cmd("\u001b*b${rowBytes}W")            // uncompressed row
                out.write(row)
            }
        }
    }

    fun endPage() = cmd("\u001b*rC")            // end raster
    fun formFeed() = cmd("\u000c")
    fun endJob() { cmd("\u001bE"); out.flush() }
}
```

### PCL6 (PCL XL) color note
For color, prefer generating PCL XL with RLE planes (Y,M,C,K). It is
substantially more work; a pragmatic v1 ships mono PCL5 + color via IPP
`application/pdf` (the printer's own interpreter renders it). Test with a
1-page colored PDF over the bridge first — if firmware renders it, your
color path is trivial: `Print-Job{document-format: application/pdf}`.
