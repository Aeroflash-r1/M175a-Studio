package com.ganesan.m175otg.scan

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream

/**
 * Regression tests for the ROOT CAUSE of the corrupt ("rainbow") scans.
 *
 * The printer wraps the scanned image in a DIME record CHAIN whose 12-byte
 * headers sit INSIDE the image every 2048 bytes. Slicing SOI..EOI out of the
 * raw response therefore injects a header into the JPEG entropy stream every
 * 2048 bytes; Huffman decoding loses sync at the first one and the rest of the
 * page decodes as noise.
 *
 * These tests run against the REAL captured response body from the unit
 * (dime-body-300.bin, 300 dpi colour, 537,068 bytes), so they fail if the
 * assembler regresses.
 */
class DimeFramingTest {

    private fun res(name: String): ByteArray =
        javaClass.classLoader!!.getResourceAsStream(name)!!.readBytes()

    private fun findFrom(b: ByteArray, a: Int, c: Int, from: Int): Int {
        var i = from
        while (i + 1 < b.size) {
            if ((b[i].toInt() and 0xFF) == a && (b[i + 1].toInt() and 0xFF) == c) return i
            i++
        }
        return -1
    }

    @Test
    fun realBody_assemblesToACompleteJpeg() {
        val body = res("dime-body-300.bin")
        val r = DimeFraming.assemblePayload(body)
        assertNotNull("the real DIME body must assemble", r)
        val rr = r!!

        // 262 records walked (the first is the SOAP envelope, which is skipped).
        assertEquals(262, rr.records)
        assertEquals(533393, rr.payload.size)

        // the assembled payload IS a standalone JPEG
        assertEquals(0xFF, rr.payload[0].toInt() and 0xFF)
        assertEquals(0xD8, rr.payload[1].toInt() and 0xFF)
        assertEquals(0xE0, rr.payload[3].toInt() and 0xFF)   // APP0 follows SOI
        assertEquals(0xFF, rr.payload[rr.payload.size - 2].toInt() and 0xFF)
        assertEquals(0xD9, rr.payload[rr.payload.size - 1].toInt() and 0xFF)
    }

    @Test
    fun assemblyRemovesExactlyTheHeadersThatCorruptedTheImage() {
        val body = res("dime-body-300.bin")

        // What the OLD code fed the JPEG decoder: SOI..last-EOI of the RAW body.
        val soi = findFrom(body, 0xFF, 0xD8, 0)
        assertTrue("SOI must exist", soi >= 0)
        var eoi = -1
        var k = soi
        while (true) {
            val h = findFrom(body, 0xFF, 0xD9, k)
            if (h < 0) break
            eoi = h
            k = h + 2
        }
        val rawSlice = body.copyOfRange(soi, eoi + 2)
        assertEquals(536513, rawSlice.size)

        // 259 headers inside the image declare 2048; the FINAL record of the
        // chain declares a shorter length (913 B here), which is why a fixed
        // 12-byte pattern scan finds 259 while the chain walk strips 260.
        val headers = DimeFraming.countInterleavedHeaders(rawSlice)
        assertEquals("2048-declaring headers inside the raw slice", 259, headers)

        val payload = DimeFraming.assemblePayload(body)!!.payload
        assertEquals("the assembled payload must contain no record headers",
            0, DimeFraming.countInterleavedHeaders(payload))
        assertEquals("assembly strips one 12-byte header per interleaved record",
            rawSlice.size - 260 * 12, payload.size)
    }

    @Test
    fun theChainConsumesTheWholeBodyWithoutInventingBytes() {
        // The chain walk must consume the body exactly and the assembled
        // payload must be SHORTER than the raw slice (headers removed, nothing
        // added). Sizes are the measured values from the real capture.
        val body = res("dime-body-300.bin")
        val r = DimeFraming.assemblePayload(body)!!
        assertEquals(262, r.records)
        assertEquals(533393, r.payload.size)
        assertTrue("assembly must not add bytes", r.payload.size < 536513)
    }

    @Test
    fun bareJpegIsNotTreatedAsDime() {
        val body = res("dime-body-300.bin")
        val fragment = body.copyOfRange(552, 1200)   // starts with FFD8 (SOI)
        assertNull("a bare JPEG fragment must not parse as DIME",
            DimeFraming.assemblePayload(fragment))
    }

    @Test
    fun nonDimeBodyFallsBackCleanly() {
        // random-ish bytes that cannot be a DIME header (version 7)
        val b = ByteArrayOutputStream()
        for (i in 0 until 4096) b.write((i * 37 + 0xFF) and 0xFF)
        assertNull(DimeFraming.assemblePayload(b.toByteArray()))
    }
}
