package com.ganesan.m175otg.print

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Byte-level verification that the PCL XL stream declares the SELECTED
 * paper size and the matching printable-area geometry.
 *
 * PclxlPage is plain JVM code, so the real stream the printer receives can
 * be built and inspected here without hardware.
 *
 * Encoding reminders: every attribute is [type][value...][0xF8][attrId].
 *  - MediaSize: 0xC8 (ubyte array) [len] [bytes] 0xF8 0x25
 *  - DestinationSize: 0xD1 (uint16 xy) [w u16][h u16] 0xF8 0x67
 *  - Orientation: 0xC0 [0|1] 0xF8 0x28
 */
class PclxlPaperTest {

    private val jpeg = ByteArray(64) { it.toByte() }

    private fun stream(paper: Paper, landscape: Boolean = false) =
        PclxlPage.buildStream(
            listOf(jpeg), 100, 100, dpi = 300, grayscale = false,
            jobName = "TEST", landscape = landscape, paper = paper,
        )

    /** Reads the uint16 xy value of attribute [attrId]. */
    private fun uint16xy(bytes: ByteArray, attrId: Int): Pair<Int, Int>? {
        for (i in 0 until bytes.size - 6) {
            if (bytes[i] == 0xD1.toByte() &&
                bytes[i + 5] == 0xF8.toByte() &&
                bytes[i + 6] == attrId.toByte()
            ) {
                val w = (bytes[i + 1].toInt() and 0xFF) or
                        ((bytes[i + 2].toInt() and 0xFF) shl 8)
                val h = (bytes[i + 3].toInt() and 0xFF) or
                        ((bytes[i + 4].toInt() and 0xFF) shl 8)
                return w to h
            }
        }
        return null
    }

    /**
     * Reads the ubyte-array value of attribute [attrId] as text.
     * Layout is [0xC8 array][0xC0|0xC1 lengthType][len][data...][0xF8][id].
     */
    private fun ubyteArray(bytes: ByteArray, attrId: Int): String? {
        for (i in 0 until bytes.size - 5) {
            if (bytes[i] != 0xC8.toByte()) continue
            val lenType = bytes[i + 1].toInt() and 0xFF
            val len: Int
            val dataAt: Int
            when (lenType) {
                0xC0 -> { len = bytes[i + 2].toInt() and 0xFF; dataAt = i + 3 }
                0xC1 -> {
                    len = (bytes[i + 2].toInt() and 0xFF) or
                            ((bytes[i + 3].toInt() and 0xFF) shl 8)
                    dataAt = i + 4
                }
                else -> continue
            }
            if (dataAt + len + 1 < bytes.size &&
                bytes[dataAt + len] == 0xF8.toByte() &&
                bytes[dataAt + len + 1] == attrId.toByte()
            ) {
                return String(bytes, dataAt, len, Charsets.ISO_8859_1)
            }
        }
        return null
    }

    @Test
    fun default_stream_declares_a4_and_sends_no_media_name_other_than_a4() {
        val s = stream(Paper.A4)
        assertEquals("A4", ubyteArray(s, 0x25))
    }

    @Test
    fun each_paper_size_sends_its_own_media_name() {
        for (p in Paper.entries) {
            val s = stream(p)
            assertEquals("media name for $p", p.pclName, ubyteArray(s, 0x25))
        }
    }

    @Test
    fun destination_size_matches_the_paper_printable_area() {
        for (p in Paper.entries) {
            val s = stream(p)
            val (w, h) = uint16xy(s, 0x67)
                ?: error("no DestinationSize in ${p} stream")
            val (ew, eh) = p.destUnits(300)
            assertEquals("$p destW", ew, w)
            assertEquals("$p destH", eh, h)
        }
    }

    @Test
    fun landscape_swaps_geometry_and_sets_orientation() {
        val portrait = stream(Paper.LETTER)
        val landscape = stream(Paper.LETTER, landscape = true)
        val (pw, ph) = uint16xy(portrait, 0x67)!!
        val (lw, lh) = uint16xy(landscape, 0x67)!!
        assertEquals(pw, lh)
        assertEquals(ph, lw)
        assertNotEquals(pw, lw)   // Letter is not square, so this is meaningful

        // orientation attribute: 0xC0 0x00 0xF8 0x28 (portrait)
        //                      0xC0 0x01 0xF8 0x28 (landscape)
        fun orientation(b: ByteArray): Int {
            for (i in 0 until b.size - 3) {
                if (b[i] == 0xC0.toByte() &&
                    b[i + 2] == 0xF8.toByte() && b[i + 3] == 0x28.toByte()
                ) return b[i + 1].toInt() and 0xFF
            }
            return -1
        }
        assertEquals(0, orientation(portrait))
        assertEquals(1, orientation(landscape))
    }

    @Test
    fun stream_still_opens_and_closes_a_valid_session() {
        val s = stream(Paper.LETTER)
        val text = String(s, Charsets.ISO_8859_1)
        assertTrue(text.startsWith("\u001B%-12345X@PJL"))
        assertTrue(text.contains("ENTER LANGUAGE=PCLXL"))
        assertTrue(text.contains("HP-PCL XL"))
        assertTrue(text.contains("@PJL EOJ"))
        assertTrue(s.size > jpeg.size)
    }
}
