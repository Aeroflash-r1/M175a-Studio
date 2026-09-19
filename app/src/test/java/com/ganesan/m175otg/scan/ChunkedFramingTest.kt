package com.ganesan.m175otg.scan

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream

/**
 * Unit tests for the chunked-transfer framing walker — the app's single
 * source of truth for reading scanner image streams.
 *
 * Every failure shape here was seen on the real printer:
 *  - clean streams
 *  - SHORT chunks (26-48 B short at the 64 KB boundary, captured)
 *  - over-long chunks with a hex lookalike inside entropy data
 *  - mid-line pseudo-terminators ("0\r\n" inside a real "800\r\n")
 *  - PARTIAL buffers while the image streams in (the "length=2165" crash)
 *  - a REAL captured wire body shipped as a test resource
 */
class ChunkedFramingTest {

    // ---------------------------------------------------------------- helpers

    private fun deterministicData(len: Int, seed: Int): ByteArray {
        val out = ByteArray(len)
        for (i in 0 until len) out[i] = (((i * 37 + seed * 11) % 251) + 1).toByte()
        return out
    }

    private class Framed(val body: ByteArray, val payload: ByteArray, val terminatorAt: Int)

    /** [parts] = declared size -> delivered bytes (they may differ: the glitch). */
    private fun frame(parts: List<Pair<Int, ByteArray>>): Framed {
        val body = ByteArrayOutputStream()
        val payload = ByteArrayOutputStream()
        var termAt = -1
        for ((declared, data) in parts) {
            body.write(Integer.toHexString(declared).toByteArray(Charsets.ISO_8859_1))
            body.write("\r\n".toByteArray(Charsets.ISO_8859_1))
            body.write(data)
            body.write("\r\n".toByteArray(Charsets.ISO_8859_1))
            payload.write(data)
        }
        termAt = body.size()
        body.write("0\r\n\r\n".toByteArray(Charsets.ISO_8859_1))
        return Framed(body.toByteArray(), payload.toByteArray(), termAt)
    }

    private fun walk(body: ByteArray): Pair<Int, ByteArray> {
        val out = ByteArrayOutputStream()
        val term = ChunkedFraming.walk(body, 0, out)
        return term to out.toByteArray()
    }

    // ------------------------------------------------------------------ tests

    @Test
    fun cleanStream_isByteIdentical() {
        val parts = (0 until 20).map { 2048 to deterministicData(2048, it) }
        val f = frame(parts)
        val (term, got) = walk(f.body)
        assertTrue("terminator must be found", term >= 0)
        assertEquals(f.terminatorAt, term)
        assertTrue("payload must be byte-identical", f.payload.contentEquals(got))
    }

    @Test
    fun shortChunk_backwardResync_isByteExact() {
        // capture-proven glitch: chunk 7 declares 2048 but delivers 2022
        val parts = (0 until 12).map { idx ->
            if (idx == 7) 2048 to deterministicData(2022, idx)
            else 2048 to deterministicData(2048, idx)
        }
        val f = frame(parts)
        val (term, got) = walk(f.body)
        assertTrue("short chunk must still complete", term >= 0)
        assertTrue("short chunk must recover BYTE-EXACT",
            f.payload.contentEquals(got))
    }

    @Test
    fun overLongChunk_rejectsEntropyLookalike() {
        // chunk 1 delivers 6 bytes MORE than declared, and those delivered
        // bytes contain a hex+CRLF pattern that looks like a chunk size line
        val data1 = deterministicData(2054, 1)
        "1a2\r\n".toByteArray(Charsets.ISO_8859_1).copyInto(data1, 2049)
        val parts = listOf(
            2048 to deterministicData(2048, 0),
            2048 to data1,
            2048 to deterministicData(2048, 2),
        )
        val f = frame(parts)
        val (term, got) = walk(f.body)
        assertTrue(term >= 0)
        assertTrue("lookalike must be rejected -> byte-identical output",
            f.payload.contentEquals(got))
    }

    @Test
    fun midLinePseudoTerminator_isIgnored() {
        // a fake "CRLF 0 CRLF CRLF" planted INSIDE chunk data must not end
        // the stream — the real terminator is the only valid one
        val data0 = deterministicData(2048, 0)
        "\r\n0\r\n\r\n".toByteArray(Charsets.ISO_8859_1).copyInto(data0, 100)
        val parts = listOf(
            2048 to data0,
            2048 to deterministicData(2048, 1),
        )
        val f = frame(parts)
        val (term, got) = walk(f.body)
        assertEquals("real terminator only", f.terminatorAt, term)
        assertTrue(f.payload.contentEquals(got))
    }

    @Test
    fun partialBuffers_neverThrow_including2165() {
        // REGRESSION GUARD for the shipped crash: the walker runs on partial
        // buffers while the image streams in, and a chunk's DECLARED end
        // routinely sits beyond the bytes received so far.
        // "scan failed length=2165" = ArrayIndexOutOfBounds at that size.
        val parts = (0 until 12).map { idx ->
            if (idx == 7) 2048 to deterministicData(2022, idx)
            else 2048 to deterministicData(2048, idx)
        }
        val f = frame(parts)
        val sizes = intArrayOf(1, 2, 3, 64, 512, 2054, 2055, 2165, 4096, 8192,
            65536, f.body.size / 2, f.body.size - 1)
        for (n in sizes) {
            val slice = f.body.copyOfRange(0, minOf(n, f.body.size))
            // must not throw; result is either "incomplete" (-1) or a terminator
            val term = ChunkedFraming.walk(slice, 0, null)
            assertTrue("prefix $n returned $term (allowed: -1 or >=0)", term >= -1)
        }
    }

    @Test
    fun realWireVector_completesWithExpectedImage() {
        // the REAL chunked body captured from this printer (300 dpi session),
        // shipped as a test resource. Proves the shipped walker handles real
        // wire data, not just synthetic streams.
        val body = javaClass.getResourceAsStream("/wire-body-300.bin")!!
            .use { it.readBytes() }
        assertTrue("resource present", body.size > 500_000)
        val (term, got) = walk(body)
        assertTrue("real stream must complete (terminator found)", term >= 0)
        assertEquals("de-chunked payload size", 540_936, got.size)
        // payload must start with the HP DIME record header of the real capture
        assertEquals(0x0c.toByte(), got[0])
        assertEquals(0x20.toByte(), got[1])
        val soi = indexOfSeq(got, byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte()))
        val eoi = lastIndexOfSeq(got, byteArrayOf(0xFF.toByte(), 0xD9.toByte()))
        assertTrue("exactly one JPEG SOI", soi >= 0 && indexOfSeqFrom(got, soi + 1,
            byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte())) < 0)
        assertTrue("EOI present near the end", eoi > 500_000)
    }

    // --------------------------------------------------------- byte searching

    private fun indexOfSeq(b: ByteArray, pat: ByteArray, from: Int = 0): Int {
        outer@ for (i in from..b.size - pat.size) {
            for (j in pat.indices) if (b[i + j] != pat[j]) continue@outer
            return i
        }
        return -1
    }

    private fun indexOfSeqFrom(b: ByteArray, from: Int, pat: ByteArray): Int =
        indexOfSeq(b, pat, from)

    private fun lastIndexOfSeq(b: ByteArray, pat: ByteArray): Int {
        outer@ for (i in b.size - pat.size downTo 0) {
            for (j in pat.indices) if (b[i + j] != pat[j]) continue@outer
            return i
        }
        return -1
    }
}
