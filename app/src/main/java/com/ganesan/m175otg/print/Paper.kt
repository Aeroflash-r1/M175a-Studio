package com.ganesan.m175otg.print

import kotlin.math.roundToInt

/**
 * PAPER SIZE engine.
 *
 * Every `pclName` below is the EXACT string the installed HP PCL6 driver
 * (v0.3.1544.10073) writes into the PCL XL BeginPage `MediaSize` attribute
 * for this printer. They were read back from the driver's own rendered
 * output (`M175Bridge/tmp/probe_mediasize.ps1`, 21 sizes), not guessed —
 * so Letter is "LETTER", Legal is "LEGAL", JIS B5 is "JISB5" while the
 * B5 *envelope* is "B5".
 *
 * The option list matches both that driver enumeration and the printer's
 * own IPP `media-supported` reply captured from its BIDI channel, and the
 * sheet sizes are the exact physical dimensions those IPP names state
 * (e.g. `jis_b5_182x257mm`, `na_number-10_4.125x9.5in`).
 *
 * PRINTABLE AREA: the physically verified A4 job sends DestinationSize
 * 4760 x 6735 printer units at 600 dpi on an 8.2677 x 11.6929 in sheet,
 * i.e. the engine steals 0.3344 in across the width and 0.4679 in down
 * the height. Those margins are a property of the engine, so every other
 * size subtracts the same values. A4 keeps 4760 x 6735 verbatim so A4
 * jobs stay byte-identical to the build verified on the printer.
 */
enum class Paper(
    val label: String,
    /** Exact MediaSize string the HP driver sends (verified on this unit). */
    val pclName: String,
    /** Sheet width in inches — the true physical size. */
    val widthIn: Float,
    /** Sheet height in inches — the true physical size. */
    val heightIn: Float,
    private val destW600: Int,
    private val destH600: Int,
) {
    A4("A4", "A4", 210 / MM, 297 / MM, 4760, 6735),
    LETTER("Letter", "LETTER", 8.5f, 11f, destW(8.5f), destH(11f)),
    LEGAL("Legal", "LEGAL", 8.5f, 14f, destW(8.5f), destH(14f)),
    EXECUTIVE("Executive", "EXECUTIVE", 7.25f, 10.5f, destW(7.25f), destH(10.5f)),
    A5("A5", "A5", 148 / MM, 210 / MM, destW(148 / MM), destH(210 / MM)),
    A6("A6", "A6", 105 / MM, 148 / MM, destW(105 / MM), destH(148 / MM)),
    JIS_B5("B5 (JIS)", "JISB5", 182 / MM, 257 / MM,
        destW(182 / MM), destH(257 / MM)),
    FOOLSCAP("8.5x13", "8.5X13", 8.5f, 13f, destW(8.5f), destH(13f)),
    PHOTO_4X6("Photo 4x6", "4x6", 4f, 6f, destW(4f), destH(6f)),
    PHOTO_5X8("Photo 5x8", "5x8", 5f, 8f, destW(5f), destH(8f)),
    ENV_COM10("#10 envelope", "COM10", 4.125f, 9.5f, destW(4.125f), destH(9.5f)),
    ENV_DL("DL envelope", "DL", 110 / MM, 220 / MM,
        destW(110 / MM), destH(220 / MM)),
    ENV_C5("C5 envelope", "C5", 162 / MM, 229 / MM,
        destW(162 / MM), destH(229 / MM)),
    ENV_MONARCH("Monarch env", "MONARCH", 3.875f, 7.5f,
        destW(3.875f), destH(7.5f)),
    ENV_B5("B5 envelope", "B5", 176 / MM, 250 / MM,
        destW(176 / MM), destH(250 / MM)),
    POSTCARD("Postcard", "JPOST", 100 / MM, 148 / MM,
        destW(100 / MM), destH(148 / MM)),
    POSTCARD_DOUBLE("Postcard 2x", "JPOSTD", 148 / MM, 200 / MM,
        destW(148 / MM), destH(200 / MM)),
    PRC_16K_195X270("16K 195x270", "16K 195X270MM", 195 / MM, 270 / MM,
        destW(195 / MM), destH(270 / MM)),
    PRC_16K_184X260("16K 184x260", "16K 184X260MM", 184 / MM, 260 / MM,
        destW(184 / MM), destH(260 / MM)),
    ROC_16K_197X273("16K 197x273", "ROC16K", 197 / MM, 273 / MM,
        destW(197 / MM), destH(273 / MM));

    /**
     * DestinationSize in printer units at [dpi] (the same integer math the
     * captured A4 driver stream used).
     */
    fun destUnits(dpi: Int): Pair<Int, Int> =
        (destW600 * dpi / 600) to (destH600 * dpi / 600)

    /**
     * Full-page bitmap pixel size at [dpi] for this media.
     * [landscape] swaps the axes (the engine rotates the sheet, so the
     * image must be sent wide).
     */
    fun pagePx(dpi: Int, landscape: Boolean): Pair<Int, Int> {
        val w = (widthIn * dpi).roundToInt()
        val h = (heightIn * dpi).roundToInt()
        return if (landscape) h to w else w to h
    }

    companion object {
        fun byIndex(i: Int): Paper = entries.getOrElse(i) { A4 }

        /** Restores the persisted choice by name, tolerating older index values. */
        fun fromSaved(saved: String?): Paper =
            saved?.let { s -> entries.firstOrNull { it.name == s } }
                ?: saved?.toIntOrNull()?.let { byIndex(it) }
                ?: A4
    }
}

/** Millimetres -> inches, for the ISO/JIS sizes the printer reports in mm. */
private const val MM = 25.4f

// Engine margins measured from the verified A4 job:
// 8.2677 - 4760/600 = 0.3344 in across the width,
// 11.6929 - 6735/600 = 0.4679 in down the height.
private const val MARGIN_X_IN = 0.3344f
private const val MARGIN_Y_IN = 0.4679f

/** Printable width in printer units at 600 dpi. */
private fun destW(widthIn: Float) = ((widthIn - MARGIN_X_IN) * 600f).roundToInt()

/** Printable height in printer units at 600 dpi. */
private fun destH(heightIn: Float) = ((heightIn - MARGIN_Y_IN) * 600f).roundToInt()
