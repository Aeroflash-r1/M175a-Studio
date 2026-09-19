package com.ganesan.m175otg.scan

import java.io.ByteArrayOutputStream

/**
 * HTTP chunked-transfer framing walker — SINGLE SOURCE OF TRUTH.
 *
 * Used by BOTH scan transports (LEDM and HP wscn). Until Sept 2026 each
 * client carried its own copy of this logic; two copies meant two places
 * for bugs, and one regression shipped (an unclamped backward search that
 * threw ArrayIndexOutOfBounds on the first partial read of a streamed
 * response — the phone's "scan failed length=2165"). Now there is one
 * implementation, covered by JVM unit tests that run against REAL captured
 * wire bytes (ChunkedFramingTest).
 *
 * Rules — every one of them wire-proven, not guessed:
 *  - A size line is "1-6 hex digits + CRLF". A candidate found by SEARCH is
 *    validated by CHAINING into a further valid boundary, which rejects
 *    coincidental hex runs inside JPEG entropy data (the intermittent
 *    "clean top, then rainbow" corruption class).
 *  - A resync target must start at a TRUE line boundary (buffer start or
 *    right after a chunk's data-terminating CRLF). This rejects the
 *    "0\r\n" INSIDE a real "800\r\n" (mid-line pseudo-terminator that
 *    truncated images).
 *  - SHORT chunks: the real next boundary sits BEHIND the declared end
 *    (capture-proven 26-48 B shorts at the 64 KB boundary) -> backward
 *    search (64 B window) first, then forward (512 B).
 *  - ALL indexing is bounds-safe: this runs on PARTIAL buffers while the
 *    image streams in, and declared ends routinely exceed the bytes
 *    received so far.
 */
internal object ChunkedFraming {

    /**
     * Walks chunk boundaries with forward/backward resync.
     * Returns the index of the 0-terminator size line, or -1 when the body
     * is incomplete. When [emit] is non-null, de-chunked payload bytes are
     * appended to it. [note] receives one line per resync fallback firing
     * (byte offset + variant) for corruption correlation.
     */
    fun walk(
        b: ByteArray,
        start: Int,
        emit: ByteArrayOutputStream?,
        note: ((String) -> Unit)? = null,
    ): Int {
        var pos = start
        var guard = 0
        while (pos < b.size && guard++ < 2_000_000) {
            val m = matchSizeLine(b, pos)
            if (m == null) {
                // not a size line here: scan forward for the next one
                note?.invoke("resync @byte $pos: forward-search — declared boundary missing")
                val next = findSizeLine(b, pos, 512) ?: return -1
                pos = next
                continue
            }
            val sz = m[1]
            if (sz == 0) return pos                       // real terminator
            val ds = m[0]
            val declaredEnd = ds + sz
            // does a size line follow directly (short-by-2) ...?
            if (matchSizeLine(b, declaredEnd) != null) {
                emit?.write(b, ds, sz)
                pos = declaredEnd
                continue
            }
            // ...or after the standard CRLF that closes chunk data?
            if (declaredEnd + 2 <= b.size && b[declaredEnd] == 13.toByte() &&
                b[declaredEnd + 1] == 10.toByte() &&
                matchSizeLine(b, declaredEnd + 2) != null
            ) {
                // standard framing — fires on every chunk, so no telemetry
                emit?.write(b, ds, sz)
                pos = declaredEnd + 2
                continue
            }
            // SHORT/LONG CHUNK (printer gSOAP glitch): backward first (the
            // observed short case), then forward. BOTH directions use the
            // chained matcher + true-boundary guard.
            val back = findSizeLineBackward(b, declaredEnd, 64)
            val resync = back ?: findSizeLine(b, declaredEnd, 512)
            if (resync == null) {
                // maybe the tail hasn't arrived yet — keep reading
                return -1
            }
            note?.invoke("resync @byte $declaredEnd: " + if (back != null)
                "SHORT chunk: backward resync @$resync — byte-exact recovery"
            else
                "long chunk: forward resync target @$resync")
            if (resync - 2 > ds) emit?.write(b, ds, resync - 2 - ds)
            pos = resync
        }
        return -1
    }

    /** Returns [dataStart, size] if a hex size line starts exactly at [pos]. */
    fun matchSizeLine(b: ByteArray, pos: Int): IntArray? {
        var i = pos
        var digits = 0
        var v = 0
        while (i < b.size && digits <= 6) {
            val c = b[i].toInt() and 0xFF
            val d = when (c) {
                in 48..57 -> c - 48
                in 97..102 -> c - 87
                in 65..70 -> c - 55
                13 -> break
                else -> return null
            }
            v = v * 16 + d
            digits++
            i++
        }
        if (digits == 0 || digits > 6 || i + 1 >= b.size) return null
        if (b[i] == 13.toByte() && b[i + 1] == 10.toByte())
            return intArrayOf(i + 2, v)
        return null
    }

    /**
     * Like [matchSizeLine], but also requires the chunk it introduces to
     * chain into ANOTHER valid boundary (a further size line, or the
     * terminator) — rejects a match that is just a coincidental hex run
     * inside JPEG data. A false positive now needs two independent
     * coincidences instead of one.
     */
    fun matchSizeLineChained(b: ByteArray, pos: Int): IntArray? {
        val m = matchSizeLine(b, pos) ?: return null
        val ds = m[0]
        val sz = m[1]
        if (sz == 0) return m   // the terminator needs no further chaining
        val declaredEnd = ds + sz
        if (matchSizeLine(b, declaredEnd) != null) return m
        if (declaredEnd + 2 <= b.size &&
            b[declaredEnd] == 13.toByte() && b[declaredEnd + 1] == 10.toByte() &&
            matchSizeLine(b, declaredEnd + 2) != null
        ) return m
        return null
    }

    /**
     * BOUNDS-SAFE true-line-boundary guard: a resync target must start
     * where a size line can legitimately start — buffer start, or right
     * after the previous chunk's data-terminating CRLF. Indexing past the
     * buffer is impossible by construction (partial-stream safety).
     */
    fun atTrueBoundary(b: ByteArray, i: Int): Boolean {
        if (i < 0 || i >= b.size) return false
        if (i == 0) return true
        return i >= 2 && b[i - 2] == 13.toByte() && b[i - 1] == 10.toByte()
    }

    /** Forward search for a chained-valid size line within [window]. */
    fun findSizeLine(b: ByteArray, pos: Int, window: Int): Int? {
        val limit = minOf(b.size, pos + window)
        var i = maxOf(0, pos)
        while (i < limit) {
            if (atTrueBoundary(b, i) && matchSizeLineChained(b, i) != null) return i
            i++
        }
        return null
    }

    /** Backward search for a chained-valid size line within [window]. */
    fun findSizeLineBackward(b: ByteArray, pos: Int, window: Int): Int? {
        if (b.isEmpty()) return null
        var i = minOf(pos - 1, b.size - 1)   // clamp to the REAL buffer
        val limit = maxOf(0, pos - window)
        while (i >= limit) {
            if (atTrueBoundary(b, i) && matchSizeLineChained(b, i) != null) return i
            i--
        }
        return null
    }
}
