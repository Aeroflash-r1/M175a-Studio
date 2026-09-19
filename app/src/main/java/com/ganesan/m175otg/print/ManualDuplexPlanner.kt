package com.ganesan.m175otg.print

import com.ganesan.m175otg.usb.UsbPrinterConnection

/**
 * Manual duplex planner — the SAME order HP's Windows driver uses
 * (verified by physical test with chip-marked pages, 2026-09-14):
 *
 *   PASS 1: EVEN pages, REVERSED   (8,6,4,2)   <- printed first
 *   user flips the whole stack like a book page (blank sides up)
 *   PASS 2: ODD pages, FORWARD     (1,3,5,7)   <- onto the backs
 *
 * Result: the stack comes out collated 1|2, 3|4, 5|6…
 *
 * LCD PROMPT (fixed): the flip instruction is pushed to the printer's own
 * display **after pass 1 finishes and before pass 2 starts** — as its own
 * standalone PJL `RDYMSG` job. The old code embedded it in pass 1's PCL XL
 * session, so it (a) appeared while side 1 was still printing and (b) was
 * wiped by that session's own close — the panel therefore never showed it
 * at the moment the user had to flip.
 */
object ManualDuplexPlanner {

    /** Page numbers (1-based) for each pass. */
    data class Plan(val pass1: List<Int>, val pass2: List<Int>)

    fun plan(totalPages: Int): Plan {
        val odds = (1..totalPages).filter { it % 2 == 1 }
        val evens = (2..totalPages).filter { it % 2 == 0 }
        return Plan(evens.reversed(), odds)
    }

    /** Panel text while waiting for the flip (2 x 16 chars on the M175a). */
    const val LCD_FLIP = "FLIP STACK AND RELOAD"

    /**
     * Full two-pass duplex job over USB. Between passes [onFlipPrompt] is
     * called and must suspend until the user confirms the reinsert.
     * Returns the transmit result of the last pass (Cancelled if the user
     * pressed Cancel at any point).
     */
    suspend fun execute(
        usb: UsbPrinterConnection,
        pagesJpeg: List<ByteArray>,
        pageW: Int,
        pageH: Int,
        grayscale: Boolean,
        dpi: Int,
        onProgress: (String) -> Unit,
        onFlipPrompt: suspend () -> Unit,
        paper: Paper = Paper.A4,
    ): PrintTransmitter.Result {
        val p = plan(pagesJpeg.size)

        // PASS 1 — even pages, reversed (nothing on the LCD yet: the panel
        // should show the normal job/Ready screen while side 1 prints).
        onProgress("Side 1: even pages ${p.pass1.joinToString()}")
        val s1 = PclxlPage.buildStream(
            pick(p.pass1, pagesJpeg), pageW, pageH, dpi = dpi, grayscale = grayscale,
            jobName = "DUPLEX-S1", paper = paper,
        )
        val r1 = transmit(usb, s1)
        if (r1 is PrintTransmitter.Result.Cancelled) return r1
        if (r1 is PrintTransmitter.Result.Failed) return r1

        // Now the paper is in the tray and the user must flip it: light the
        // printer's own display BEFORE asking, so the panel and the phone
        // both give the same instruction at the same moment.
        runCatching { transmit(usb, PclxlPage.lcdMessageBytes(LCD_FLIP)) }

        onFlipPrompt() // app shows the FLIP screen; resumes on user confirm

        if (JobControl.isCancelled) {
            runCatching { transmit(usb, PclxlPage.lcdMessageBytes("")) }
            return PrintTransmitter.Result.Cancelled(0)
        }

        // PASS 2 — odd pages, forward, onto the flipped backs.
        onProgress("Side 2: odd pages ${p.pass2.joinToString()}")
        val s2 = PclxlPage.buildStream(
            pick(p.pass2, pagesJpeg), pageW, pageH, dpi = dpi, grayscale = grayscale,
            jobName = "DUPLEX-S2", paper = paper,
        )
        val r2 = transmit(usb, s2)

        // job over -> back to the normal Ready screen
        runCatching { transmit(usb, PclxlPage.lcdMessageBytes("")) }
        return r2
    }

    private fun pick(nums: List<Int>, pages: List<ByteArray>) =
        nums.map { pages[it - 1] }

    /**
     * BOOKLET print: imposes pages as 2-up landscape sheets (booklet math
     * in PageLayout.bookletSheets), prints all FRONTS pass 1, flip, all
     * BACKS pass 2 — the same two-pass flow the user knows from duplex.
     * Fold + staple by hand afterwards; the page order comes out correct.
     */
    suspend fun executeBooklet(
        usb: UsbPrinterConnection,
        pagesJpeg: List<ByteArray>,
        pageW: Int,
        pageH: Int,
        grayscale: Boolean,
        dpi: Int,
        onProgress: (String) -> Unit,
        onFlipPrompt: suspend () -> Unit,
        paper: Paper = Paper.A4,
    ): PrintTransmitter.Result {
        val sheets = PageLayout.bookletSheets(pagesJpeg.size)

        // compose every sheet face once (2-up landscape JPEGs)
        val fronts = ArrayList<ByteArray>(sheets.size)
        val backs = ArrayList<ByteArray>(sheets.size)
        sheets.forEachIndexed { i, (front, back) ->
            val fl = front[0]?.let { pagesJpeg[it - 1] }
            val fr = front[1]?.let { pagesJpeg[it - 1] }
            val bl = back[0]?.let { pagesJpeg[it - 1] }
            val br = back[1]?.let { pagesJpeg[it - 1] }
            fronts.add(PageLayout.composeTwoUp(fl, fr, dpi, grayscale, pageW, pageH))
            backs.add(PageLayout.composeTwoUp(bl, br, dpi, grayscale, pageW, pageH))
            onProgress("Imposing sheet $i of ${sheets.size}...")
        }

        // PASS 1 — fronts in REVERSED sheet order. This mirrors the verified
        // duplex structure exactly (pass 1 = reversed, pass 2 = forward), so
        // the physical face-up stacking + whole-stack flip behaves the same:
        // the k-th sheet printed in pass 1 receives the (n-k+1)-th back.
        onProgress("Side 1: sheet fronts (${sheets.size} sheets, 2-up)")
        val s1 = PclxlPage.buildStream(
            fronts.reversed(), pageW * 2, pageH, dpi = dpi, grayscale = grayscale,
            jobName = "BOOKLET-S1", landscape = true, paper = paper,
        )
        val r1 = transmit(usb, s1)
        if (r1 !is PrintTransmitter.Result.Ok) return r1

        runCatching { transmit(usb, PclxlPage.lcdMessageBytes(LCD_FLIP)) }
        onFlipPrompt()
        if (JobControl.isCancelled) {
            runCatching { transmit(usb, PclxlPage.lcdMessageBytes("")) }
            return PrintTransmitter.Result.Cancelled(0)
        }

        // PASS 2 — backs in FORWARD sheet order (same as duplex's odds go
        // forward): pairing pass2[k] <-> pass1[n-k+1] puts each back on its
        // own front.
        onProgress("Side 2: sheet backs (${sheets.size} sheets, 2-up)")
        val s2 = PclxlPage.buildStream(
            backs, pageW * 2, pageH, dpi = dpi, grayscale = grayscale,
            jobName = "BOOKLET-S2", landscape = true, paper = paper,
        )
        val r2 = transmit(usb, s2)
        runCatching { transmit(usb, PclxlPage.lcdMessageBytes("")) }
        return r2
    }

    private fun transmit(
        usb: UsbPrinterConnection,
        data: ByteArray,
    ): PrintTransmitter.Result =
        PrintTransmitter.send(usb, data.inputStream(), data.size.toLong())
}
