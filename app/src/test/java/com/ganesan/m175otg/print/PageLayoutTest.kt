package com.ganesan.m175otg.print

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Verifies the booklet imposition math in PageLayout.
 *
 * Booklet invariant: with N pages (padded to a multiple of 4), folding the
 * stack once after printing must read pages 1..N in order. Sheet i (1-based)
 * carries: front [N-(i-1)*2 | (i-1)*2+1], back [(i-1)*2+2 | N-(i-1)*2-1].
 */
class PageLayoutTest {

    /** Flattened reading order when the printed stack is folded: for each
     *  physical leaf, front-outer, front-inner, back-inner, back-outer. */
    private fun foldedReadingOrder(totalPages: Int): List<Int> {
        val n = ((totalPages + 3) / 4) * 4
        val sheets = PageLayout.bookletSheets(totalPages)
        val reading = ArrayList<Int>(n)
        // The printer stacks sheets face-up: last sheet printed is on top.
        // Pass 1 prints fronts reversed, pass 2 backs forward -> the stack
        // ends up sheet 1 on top. Fold once: sheet1 front = outermost leaf.
        for ((front, back) in sheets) {
            // leaf outer = front(left outer page, right inner page)...
            reading.add(front[0] ?: 0)   // outer face of leaf (high page or blank)
            reading.add(front[1] ?: 0)   // inner face (low page)
            reading.add(back[1] ?: 0)    // inner face of the other half
            reading.add(back[0] ?: 0)    // outer face (high page)
        }
        return reading
    }

    @Test
    fun `booklet 8 pages reads in order when folded`() {
        // N=8 -> 2 sheets: S1 front [8|1] back [2|7], S2 front [6|3] back [4|5]
        val sheets = PageLayout.bookletSheets(8)
        assertEquals(2, sheets.size)
        assertEquals(listOf(8, 1), sheets[0].first)
        assertEquals(listOf(2, 7), sheets[0].second)
        assertEquals(listOf(6, 3), sheets[1].first)
        assertEquals(listOf(4, 5), sheets[1].second)
    }

    @Test
    fun `booklet pads to multiple of four with blanks`() {
        // 5 pages -> N=8 -> pages 6,7,8 are padding (null)
        val sheets = PageLayout.bookletSheets(5)
        assertEquals(2, sheets.size)
        // S1 front [8->null | 1], back [2 | 7->null]
        assertEquals(listOf(null, 1), sheets[0].first)
        assertEquals(listOf(2, null), sheets[0].second)
        // S2 front [6->null | 3], back [4 | 5]
        assertEquals(listOf(null, 3), sheets[1].first)
        assertEquals(listOf(4, 5), sheets[1].second)
    }

    @Test
    fun `every page appears exactly once across all sheet faces`() {
        for (total in 4..17) {
            val n = ((total + 3) / 4) * 4
            val seen = ArrayList<Int?>()
            for ((front, back) in PageLayout.bookletSheets(total)) {
                seen.addAll(front); seen.addAll(back)
            }
            val pages = seen.filterNotNull()
            assertEquals("total=$total", (1..total).toList(), pages.sorted())
            assertEquals("total=$total padding count", n - total,
                seen.count { it == null })
        }
    }

    @Test
    fun `range parser handles the documented syntax`() {
        assertEquals(listOf(1, 2, 3, 5, 8, 9, 10),
            PageLayout.parseRange("1-3, 5, 8-10", 20))
        assertEquals(listOf(5, 6, 7, 8, 9, 10),
            PageLayout.parseRange("5-", 10))
        assertEquals(listOf(1, 2, 3),
            PageLayout.parseRange("-3", 10))
        assertEquals(listOf(3, 2, 1).sorted(), PageLayout.parseRange("3-1", 10).sorted())
        assertTrue(PageLayout.parseRange("99-200", 10).isEmpty())
        assertTrue(PageLayout.parseRange("abc", 10).isEmpty())
        // duplicates collapse
        assertEquals(listOf(1, 2), PageLayout.parseRange("1, 1, 2", 10))
    }

    @Test
    fun `parity filter picks odds and evens`() {
        val all = (1..10).toList()
        assertEquals(listOf(1, 3, 5, 7, 9), PageLayout.filterParity(all, true, 10))
        assertEquals(listOf(2, 4, 6, 8, 10), PageLayout.filterParity(all, false, 10))
        assertEquals(all, PageLayout.filterParity(all, null, 10))
    }
}
