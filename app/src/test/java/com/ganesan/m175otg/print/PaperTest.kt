package com.ganesan.m175otg.print

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Paper size engine verification.
 *
 * The A4 numbers are LOCKED to the captured Windows-driver stream
 * (DestinationSize 4760 x 6735 printer units at 600 dpi) — if these
 * change, real print output changed and that is a regression.
 * Every other size must be the same physical sheet minus the same
 * hardware margins (0.3344 in width, 0.4679 in height).
 */
class PaperTest {

    @Test
    fun a4_matches_captured_driver_geometry() {
        // Exact captured values — do not "fix" these. NOTE these are the
        // PRINTABLE-AREA units (what the driver sent), smaller than the
        // full-sheet bitmap: the engine scales the page into this rect.
        assertEquals(4760 to 6735, Paper.A4.destUnits(600))
        assertEquals(2380 to 3367, Paper.A4.destUnits(300))
        assertEquals(1190 to 1683, Paper.A4.destUnits(150))
    }

    @Test
    fun other_sizes_keep_the_same_hardware_margins() {
        // Letter 8.5 x 11 in -> printable 8.166 x 10.532 in -> x600 units
        assertEquals(4899, Paper.LETTER.destUnits(600).first)
        assertEquals(6319, Paper.LETTER.destUnits(600).second)
        // Legal is Letter width, 14 in tall
        assertEquals(4899, Paper.LEGAL.destUnits(600).first)
        assertEquals(8119, Paper.LEGAL.destUnits(600).second)
        // Executive 7.25 x 10.5 in
        assertEquals(4149, Paper.EXECUTIVE.destUnits(600).first)
        assertEquals(6019, Paper.EXECUTIVE.destUnits(600).second)
    }

    @Test
    fun printable_area_is_smaller_than_the_sheet_in_both_axes() {
        for (p in Paper.entries) {
            val (wU, hU) = p.destUnits(600)
            assertTrue("$p printable width", wU < p.widthIn * 600)
            assertTrue("$p printable height", hU < p.heightIn * 600)
            assertTrue("$p printable positive", wU > 0 && hU > 0)
        }
    }

    @Test
    fun page_bitmap_is_inches_times_dpi_and_swaps_for_landscape() {
        // bitmap covers the FULL sheet (bigger than the printable area)
        assertEquals(2480 to 3508, Paper.A4.pagePx(300, landscape = false))
        assertEquals(3508 to 2480, Paper.A4.pagePx(300, landscape = true))
        assertEquals(2550 to 3300, Paper.LETTER.pagePx(300, landscape = false))
        assertEquals(3300 to 2550, Paper.LETTER.pagePx(300, landscape = true))
        assertEquals(4961 to 7016, Paper.A4.pagePx(600, landscape = false))
    }

    @Test
    fun sizes_are_ordered_and_distinct() {
        assertTrue(Paper.A5.heightIn < Paper.EXECUTIVE.heightIn)
        assertTrue(Paper.EXECUTIVE.heightIn < Paper.LETTER.heightIn)
        assertTrue(Paper.LETTER.heightIn < Paper.A4.heightIn)
        assertTrue(Paper.A4.heightIn < Paper.LEGAL.heightIn)
        assertEquals(Paper.entries.size,
            Paper.entries.map { it.pclName }.toSet().size)
    }

    /**
     * These strings were read back from the installed HP PCL6 driver's own
     * PCL XL output for THIS printer. They are case-sensitive protocol
     * values — "Letter" instead of "LETTER" is a DIFFERENT, unsupported
     * media name, so this test exists to stop a well-meaning "cleanup"
     * from breaking printing on a paper size.
     */
    @Test
    fun media_names_match_the_hp_driver_verbatim() {
        assertEquals("A4", Paper.A4.pclName)
        assertEquals("LETTER", Paper.LETTER.pclName)
        assertEquals("LEGAL", Paper.LEGAL.pclName)
        assertEquals("EXECUTIVE", Paper.EXECUTIVE.pclName)
        assertEquals("A5", Paper.A5.pclName)
        assertEquals("A6", Paper.A6.pclName)
        // JIS B5 is "JISB5"; the plain "B5" is the B5 *envelope*.
        assertEquals("JISB5", Paper.JIS_B5.pclName)
        assertEquals("B5", Paper.ENV_B5.pclName)
        assertEquals("8.5X13", Paper.FOOLSCAP.pclName)
        assertEquals("COM10", Paper.ENV_COM10.pclName)
        assertEquals("MONARCH", Paper.ENV_MONARCH.pclName)
        assertEquals("JPOST", Paper.POSTCARD.pclName)
        assertEquals("JPOSTD", Paper.POSTCARD_DOUBLE.pclName)
        assertEquals("ROC16K", Paper.ROC_16K_197X273.pclName)
        assertEquals("16K 195X270MM", Paper.PRC_16K_195X270.pclName)
    }

    /** Every option must be a size the printer actually reports to the driver. */
    @Test
    fun option_list_covers_the_printers_own_media_list() {
        assertEquals(20, Paper.entries.size)
        assertEquals(Paper.A4, Paper.entries.first())
    }

    @Test
    fun byIndex_falls_back_to_a4_on_bad_input() {
        assertEquals(Paper.A4, Paper.byIndex(0))
        assertEquals(Paper.LETTER, Paper.byIndex(1))
        assertEquals(Paper.A4, Paper.byIndex(99))
        assertEquals(Paper.A4, Paper.byIndex(-1))
    }
}
