package com.ganesan.m175otg.print

import java.io.ByteArrayOutputStream
import java.io.OutputStream

/**
 * Builds a PCL XL (protocol 3, little-endian `)` binding) print stream.
 *
 * V3 — byte-faithful to the Windows driver stream. History of the two
 * hardware-proven fixes baked in here:
 *   v1 -> PCL XL ERROR subsystem=IMAGE currentCursorUnified
 *         (missing 3x SetNeutralAxis unified-cursor ops)
 *   v2 -> PCL XL ERROR subsystem=KERNEL ILLEGALATTRIBUTE kerlib.c 9282
 *         (SetHalftoneMethod must carry per-class attrs 30/31/32=2,
 *          not a single AllObjectTypes)
 *   v2 printed CLEAN on the real M175a (340,122 bytes, no error text on
 *   any back-channel, queue drained) — this v3 keeps those bytes EXACTLY
 *   and only SPLITS the builder into stages so multi-page jobs can be
 *   streamed page-by-page (12-page RAM fix).
 *
 * Full verified op order (pxldis on the captured driver stream):
 *   BeginSession / OpenDataSource / [BeginPage ... EndPage] x N /
 *   CloseDataSource EndSession
 */
object PclxlPage {

    // ---- low-level writers (value bytes BEFORE selector, little-endian) ----

    private fun u8(v: Int) = byteArrayOf(v.toByte())

    private fun u16(v: Int) =
        byteArrayOf((v and 0xFF).toByte(), (v shr 8).toByte())

    private fun u32(v: Int) = byteArrayOf(
        (v and 0xFF).toByte(), ((v shr 8) and 0xFF).toByte(),
        ((v shr 16) and 0xFF).toByte(), ((v shr 24) and 0xFF).toByte()
    )

    private fun sel(name: Int) = byteArrayOf(0xF8.toByte(), name.toByte())

    private const val T_UBYTE = 0xC0
    private const val T_UINT16 = 0xC1
    private const val T_REAL32 = 0xC5
    private const val T_UBYTE_ARRAY = 0xC8
    private const val T_SINT16_XY = 0xD3
    private const val T_UINT16_XY = 0xD1
    private const val T_REAL32_XY = 0xD5

    private fun ubyteAttr(n: Int, v: Int) = u8(T_UBYTE) + u8(v) + sel(n)
    private fun uint16Attr(n: Int, v: Int) = u8(T_UINT16) + u16(v) + sel(n)

    private fun real32xyAttr(n: Int, x: Float, y: Float) =
        u8(T_REAL32_XY) + u32(java.lang.Float.floatToIntBits(x)) +
                u32(java.lang.Float.floatToIntBits(y)) + sel(n)

    private fun uint16xyAttr(n: Int, x: Int, y: Int) =
        u8(T_UINT16_XY) + u16(x) + u16(y) + sel(n)

    private fun sint16xyAttr(n: Int, x: Int, y: Int) =
        u8(T_SINT16_XY) + u16(x and 0xFFFF) + u16(y and 0xFFFF) + sel(n)

    private fun ubyteArrayAttr(n: Int, data: ByteArray): ByteArray {
        val lenVal = if (data.size < 256) u8(T_UBYTE) + u8(data.size)
        else u8(T_UINT16) + u16(data.size)
        return u8(T_UBYTE_ARRAY) + lenVal + data + sel(n)
    }

    // attribute numbers (HP table, verified via pxldis on the real capture)
    private const val A_UNITS_PER_MEASURE = 137
    private const val A_MEASURE = 134
    private const val A_ERROR_REPORT = 143
    private const val A_SOURCE_TYPE = 136
    private const val A_DATA_ORG = 130
    private const val A_MEDIA_SOURCE = 38
    private const val A_ORIENTATION = 40
    private const val A_MEDIA_SIZE = 37
    private const val A_PAGE_ORIGIN = 42
    private const val A_PAGE_SCALE = 43
    private const val A_COLOR_SPACE = 3
    private const val A_TX_MODE = 45
    private const val A_ROP3 = 44
    private const val A_COLOR_MAPPING = 100
    private const val A_COLOR_DEPTH = 98
    private const val A_SOURCE_WIDTH = 108
    private const val A_SOURCE_HEIGHT = 107
    private const val A_DESTINATION_SIZE = 103
    private const val A_START_LINE = 109
    private const val A_BLOCK_HEIGHT = 99
    private const val A_COMPRESS_MODE = 101
    private const val A_TEXT_OBJECTS = 30
    private const val A_RASTER_OBJECTS = 32
    private const val A_VECTOR_OBJECTS = 31
    private const val A_ALL_OBJECT_TYPES = 29
    private const val A_COLOR_TREATMENT = 120
    private const val A_POINT = 76

    // operators
    private const val OP_BEGIN_SESSION = 0x41
    private const val OP_END_SESSION = 0x42
    private const val OP_BEGIN_PAGE = 0x43
    private const val OP_END_PAGE = 0x44
    private const val OP_OPEN_DATASOURCE = 0x48
    private const val OP_CLOSE_DATASOURCE = 0x49
    private const val OP_SET_PAGE_ORIGIN = 0x75
    private const val OP_SET_PAGE_SCALE = 0x77
    private const val OP_SET_COLOR_SPACE = 0x6A
    private const val OP_SET_SOURCE_TX_MODE = 0x7C
    private const val OP_SET_PATTERN_TX_MODE = 0x78
    private const val OP_SET_ROP = 0x7B
    private const val OP_PUSH_GS = 0x61
    private const val OP_POP_GS = 0x60
    private const val OP_SET_CLIP_TO_PAGE = 0x69
    private const val OP_SET_CURSOR = 0x6B
    private const val OP_SET_NEUTRAL_AXIS = 0x7E
    private const val OP_SET_HALFTONE_METHOD = 0x6D
    private const val OP_SET_ADAPTIVE_HALFTONING = 0x94
    private const val OP_SET_COLOR_TRAPPING = 0x92
    private const val OP_SET_COLOR_TREATMENT = 0x58
    private const val OP_BEGIN_IMAGE = 0xB0
    private const val OP_READ_IMAGE = 0xB1
    private const val OP_END_IMAGE = 0xB2

    private const val COMPRESS_JPEG = 2
    private const val COLORSPACE_GRAY = 1
    private const val COLORSPACE_RGB = 2

    /**
     * Per-page geometry resolved from dpi + paper (printer units).
     * Destinations come from [Paper], whose printable areas are derived
     * from the captured A4 driver geometry (4760 x 6735 at 600 dpi).
     */
    data class Geometry(val dpi: Int, val destW: Int, val destH: Int) {
        companion object {
            fun of(dpi: Int, paper: Paper = Paper.A4): Geometry {
                val (w, h) = paper.destUnits(dpi)
                return Geometry(dpi, w, h)
            }
        }
    }

    // ---- staged API (streaming) -------------------------------------------

    /**
     * Standalone PJL ready-message: paints [text] on the printer's LCD
     * (2 x 16 chars on the M175a) and leaves it there — this is how the
     * manual-duplex flip prompt is shown between passes, exactly like HP's
     * Windows driver leaves an instruction on the panel.
     *
     * Sent as its own tiny PJL job so it is NOT cleared when a print
     * session ends. Pass "" to restore the normal Ready screen.
     */
    fun lcdMessageBytes(text: String): ByteArray {
        val body = "@PJL RDYMSG DISPLAY = \"${text.take(32)}\"\r\n"
        return ("\u001B%-12345X" + body + "\u001B%-12345X")
            .toByteArray(Charsets.ISO_8859_1)
    }

    /** @PJL wrapper + PCL XL binding + BeginSession + OpenDataSource. */
    fun writeSessionOpen(out: OutputStream, dpi: Int, grayscale: Boolean,
                         jobName: String, lcdMessage: String? = null,
                         resetFirst: Boolean = false) {
        val w = ByteArrayOutputStream(512)
        // RESET is only for RECOVERY (a printer left in a PCLXL error state).
        // Windows does not send it at the start of a normal job, and it makes
        // the engine re-initialize — so it is off by default here.
        if (resetFirst) {
            w.write("\u001B%-12345X@PJL RESET\r\n".toByteArray(Charsets.ISO_8859_1))
        }
        w.write("\u001B%-12345X@PJL SET RET=ON\r\n".toByteArray(Charsets.ISO_8859_1))
        w.write("@PJL JOB NAME=\"$jobName\"\r\n".toByteArray(Charsets.ISO_8859_1))
        w.write("@PJL SET STRINGCODESET=UTF8\r\n".toByteArray(Charsets.ISO_8859_1))
        w.write("@PJL SET RESOLUTION=$dpi\r\n".toByteArray(Charsets.ISO_8859_1))
        w.write("@PJL SET GRAYSCALE=${if (grayscale) "ON" else "OFF"}\r\n"
            .toByteArray(Charsets.ISO_8859_1))
        w.write("@PJL SET BITSPERPIXEL=8\r\n".toByteArray(Charsets.ISO_8859_1))
        w.write("@PJL ENTER LANGUAGE=PCLXL\r\n".toByteArray(Charsets.ISO_8859_1))

        w.write(") HP-PCL XL;3;0;Comment M175-OTG-Android\r\n"
            .toByteArray(Charsets.ISO_8859_1))

        // BeginSession — verified attrs
        w.write(uint16xyAttr(A_UNITS_PER_MEASURE, dpi, dpi))
        w.write(ubyteAttr(A_MEASURE, 0))          // eInch
        w.write(ubyteAttr(A_ERROR_REPORT, 3))     // eBackChAndErrPage
        w.write(u8(OP_BEGIN_SESSION))

        w.write(ubyteAttr(A_SOURCE_TYPE, 0))
        w.write(ubyteAttr(A_DATA_ORG, 1))         // eBinaryLowByteFirst
        w.write(u8(OP_OPEN_DATASOURCE))

        out.write(w.toByteArray())
    }

    /** CloseDataSource + EndSession + PJL EOJ. */
    fun writeSessionClose(out: OutputStream, jobName: String,
                          clearLcd: Boolean = false) {
        val w = ByteArrayOutputStream(64)
        w.write(u8(OP_CLOSE_DATASOURCE))
        w.write(u8(OP_END_SESSION))
        if (clearLcd) {
            w.write("\u001B%-12345X@PJL RDYMSG DISPLAY = \"\"\r\n"
                .toByteArray(Charsets.ISO_8859_1))
        }
        w.write("\u001B%-12345X@PJL EOJ NAME=\"$jobName\"\r\n"
            .toByteArray(Charsets.ISO_8859_1))
        w.write("\u001B%-12345X\r\n".toByteArray(Charsets.ISO_8859_1))
        out.write(w.toByteArray())
    }

    /** One complete BeginPage..EndPage block (the exact v2 op sequence).
     *  Landscape: the engine rotates the coordinate system 90°, so a wide
     *  image with swapped destination units fills the portrait A4 sheet
     *  sideways (2-up / booklet sheets). Orientation 1 = eLandscape. */
    fun writePage(out: OutputStream, jpeg: ByteArray, srcW: Int, srcH: Int,
                  geom: Geometry, grayscale: Boolean, landscape: Boolean = false,
                  mediaName: String = "A4") {
        val w = ByteArrayOutputStream(jpeg.size + 512)
        val cs = if (grayscale) COLORSPACE_GRAY else COLORSPACE_RGB
        val destW = if (landscape) geom.destH else geom.destW
        val destH = if (landscape) geom.destW else geom.destH

        // BeginPage — verified attrs
        w.write(ubyteAttr(A_MEDIA_SOURCE, 1))     // eAutoSelect
        w.write(ubyteAttr(A_ORIENTATION, if (landscape) 1 else 0))
        w.write(ubyteArrayAttr(A_MEDIA_SIZE,
            mediaName.toByteArray(Charsets.ISO_8859_1)))
        w.write(u8(OP_BEGIN_PAGE))

        w.write(sint16xyAttr(A_PAGE_ORIGIN, 100, 100))
        w.write(u8(OP_SET_PAGE_ORIGIN))

        // ops 5-7: UNIFIED CURSOR — required before images (IMAGE error fix)
        w.write(ubyteAttr(A_TEXT_OBJECTS, 0))
        w.write(u8(OP_SET_NEUTRAL_AXIS))
        w.write(ubyteAttr(A_RASTER_OBJECTS, 1))
        w.write(u8(OP_SET_NEUTRAL_AXIS))
        w.write(ubyteAttr(A_VECTOR_OBJECTS, 0))
        w.write(u8(OP_SET_NEUTRAL_AXIS))

        // op 8: SetHalftoneMethod — driver sends PER-CLASS attrs 30/31/32=2
        // (NOT AllObjectTypes — that was the KERNEL ILLEGALATTRIBUTE error)
        w.write(ubyteAttr(A_TEXT_OBJECTS, 2))
        w.write(ubyteAttr(A_VECTOR_OBJECTS, 2))
        w.write(ubyteAttr(A_RASTER_OBJECTS, 2))
        w.write(u8(OP_SET_HALFTONE_METHOD))
        w.write(ubyteAttr(A_ALL_OBJECT_TYPES, 1))
        w.write(u8(OP_SET_ADAPTIVE_HALFTONING))
        w.write(ubyteAttr(A_ALL_OBJECT_TYPES, 2))
        w.write(u8(OP_SET_COLOR_TRAPPING))
        w.write(ubyteAttr(A_COLOR_TREATMENT, 1))  // eScreenMatch
        w.write(u8(OP_SET_COLOR_TREATMENT))

        w.write(real32xyAttr(A_PAGE_SCALE, 1.0f, 1.0f))
        w.write(u8(OP_SET_PAGE_SCALE))

        w.write(ubyteAttr(A_COLOR_SPACE, cs))
        w.write(u8(OP_SET_COLOR_SPACE))
        w.write(ubyteAttr(A_TX_MODE, 0))          // eOpaque
        w.write(u8(OP_SET_PATTERN_TX_MODE))
        w.write(ubyteAttr(A_TX_MODE, 0))
        w.write(u8(OP_SET_SOURCE_TX_MODE))
        w.write(ubyteAttr(A_ROP3, 204))
        w.write(u8(OP_SET_ROP))

        w.write(u8(OP_PUSH_GS))
        w.write(u8(OP_SET_CLIP_TO_PAGE))

        // ops 19-23: in-context paint setup + cursor (driver-exact)
        w.write(sint16xyAttr(A_POINT, 0, 40))
        w.write(u8(OP_SET_CURSOR))
        w.write(ubyteAttr(A_TX_MODE, 0))
        w.write(u8(OP_SET_PATTERN_TX_MODE))
        w.write(ubyteAttr(A_TX_MODE, 0))
        w.write(u8(OP_SET_SOURCE_TX_MODE))
        w.write(ubyteAttr(A_ROP3, 204))
        w.write(u8(OP_SET_ROP))
        w.write(ubyteAttr(A_COLOR_SPACE, cs))
        w.write(u8(OP_SET_COLOR_SPACE))

        // image with JPEG payload (CompressMode=2 — printer decompresses)
        w.write(ubyteAttr(A_COLOR_MAPPING, 0))    // eDirectPixel
        w.write(ubyteAttr(A_COLOR_DEPTH, 2))      // e8Bit
        w.write(uint16Attr(A_SOURCE_WIDTH, srcW))
        w.write(uint16Attr(A_SOURCE_HEIGHT, srcH))
        w.write(uint16xyAttr(A_DESTINATION_SIZE, destW, destH))
        w.write(u8(OP_BEGIN_IMAGE))

        w.write(uint16Attr(A_START_LINE, 0))
        w.write(uint16Attr(A_BLOCK_HEIGHT, srcH))
        w.write(ubyteAttr(A_COMPRESS_MODE, COMPRESS_JPEG))
        w.write(u8(OP_READ_IMAGE))

        w.write(byteArrayOf(0xFA.toByte()))       // embedded_data
        w.write(u32(jpeg.size))
        w.write(jpeg)

        w.write(u8(OP_END_IMAGE))
        w.write(u8(OP_POP_GS))
        w.write(u8(OP_END_PAGE))

        out.write(w.toByteArray())
    }

    // ---- convenience whole-job API (small jobs / test page / duplex pass) --

    fun buildStream(
        pagesJpeg: List<ByteArray>,
        pageW: Int,
        pageH: Int,
        dpi: Int = 600,
        grayscale: Boolean = false,
        jobName: String = "M175-OTG",
        landscape: Boolean = false,
        paper: Paper = Paper.A4,
    ): ByteArray {
        val out = ByteArrayOutputStream(maxOf(1 shl 20, pagesJpeg.size * 64))
        val geom = Geometry.of(dpi, paper)
        writeSessionOpen(out, dpi, grayscale, jobName)
        for (jpeg in pagesJpeg) {
            writePage(out, jpeg, pageW, pageH, geom, grayscale, landscape,
                mediaName = paper.pclName)
        }
        writeSessionClose(out, jobName)
        return out.toByteArray()
    }
}
