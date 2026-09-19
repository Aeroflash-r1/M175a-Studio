package com.ganesan.m175otg.scan

import java.io.ByteArrayOutputStream

/**
 * DIME record-chain assembly — SINGLE SOURCE OF TRUTH for both scan transports.
 *
 * WIRE-PROVEN (Sept 2026, real 300 dpi colour scan off this printer):
 *
 * This printer sends the scanned image as a DIME record CHAIN on both the
 * HP-wscn and LEDM transports. Each record carries 2048 payload bytes, so a
 * record HEADER (12 bytes) is embedded *inside the image* every 2048 bytes:
 *
 *      [SOAP record][img rec hdr][2048 B][hdr][2048 B][hdr][2048 B]...
 *
 * Slicing SOI..EOI straight out of the RAW response therefore injects a
 * 12-byte non-image header into the JPEG entropy stream every 2048 bytes.
 * Huffman decoding loses sync at the first injection and everything after it
 * decodes as noise — exactly the reported symptom ("top of the page readable,
 * then rainbow / flat colour bands"), and why the failure point moved from
 * scan to scan.
 *
 * Measured on the real capture: **259 interleaved headers** across a
 * 536,513-byte SOI..EOI slice. Removing them makes those SAME bytes decode
 * perfectly (2550x3507, whole page). Hence the rule:
 *
 *      assemble the DIME payload FIRST, then slice the JPEG.
 *
 * Header layout used by the printer (HP gSOAP; note the version field is 0,
 * which is why the old `version == 1` check never matched and the DIME walk
 * silently bailed out):
 *
 *      [0]    version(5b) | MB | ME | CF | 2 reserved bits
 *      [2:4]  option length      [4:6] id length     [6:8] type length
 *      [8:12] data length (big-endian)
 *
 * Payload starts at 12 + pad4(opt) + pad4(id) + pad4(type); the next record
 * starts at payload + pad4(dataLen).
 */
internal object DimeFraming {

    data class Result(val payload: ByteArray, val records: Int)

    /**
     * Concatenates the payloads of every non-XML DIME record. The leading
     * record is the SOAP envelope and is skipped. Returns null when the bytes
     * are not a DIME chain at all (e.g. a bare JPEG), so callers can fall back
     * to slicing the body directly.
     */
    fun assemblePayload(b: ByteArray): Result? {
        var i = 0
        var records = 0
        var kept = 0
        val out = ByteArrayOutputStream()
        while (i + 12 <= b.size) {
            val version = (b[i].toInt() and 0xFF) ushr 5
            if (version > 1) break                    // not a DIME header
            val optLen = u16(b, i + 2)
            val idLen = u16(b, i + 4)
            val tyLen = u16(b, i + 6)
            val dataLen = i32(b, i + 8)
            if (dataLen <= 0) break
            val ds = i + 12 + pad4(optLen) + pad4(idLen) + pad4(tyLen)
            if (ds < 0 || ds + dataLen > b.size) break // tail still in flight
            val isXml = dataLen >= 2 && b[ds] == '<'.code.toByte() &&
                    b[ds + 1] == '?'.code.toByte()
            if (!isXml) {
                out.write(b, ds, dataLen)
                kept++
            }
            records++
            i = ds + pad4(dataLen)
        }
        if (kept == 0) return null
        return Result(out.toByteArray(), records)
    }

    /** Counts interleaved record headers inside a slice (diagnostics only). */
    fun countInterleavedHeaders(image: ByteArray): Int {
        var n = 0
        var i = 0
        while (i + 12 <= image.size) {
            if (image[i] == 0x09.toByte() && image[i + 1] == 0x00.toByte() &&
                image[i + 2] == 0x00.toByte() && image[i + 3] == 0x00.toByte() &&
                image[i + 4] == 0x00.toByte() && image[i + 5] == 0x00.toByte() &&
                image[i + 6] == 0x00.toByte() && image[i + 7] == 0x00.toByte() &&
                image[i + 8] == 0x00.toByte() && image[i + 9] == 0x00.toByte() &&
                image[i + 10] == 0x08.toByte() && image[i + 11] == 0x00.toByte()
            ) {
                n++
            }
            i++
        }
        return n
    }

    private fun pad4(n: Int) = (n + 3) and 0x7FFFFFFC

    private fun u16(b: ByteArray, p: Int) =
        ((b[p].toInt() and 0xFF) shl 8) or (b[p + 1].toInt() and 0xFF)

    private fun i32(b: ByteArray, p: Int): Int {
        val v = ((b[p].toInt() and 0xFF).toLong() shl 24) or
                ((b[p + 1].toInt() and 0xFF).toLong() shl 16) or
                ((b[p + 2].toInt() and 0xFF).toLong() shl 8) or
                (b[p + 3].toInt() and 0xFF).toLong()
        return if (v > Int.MAX_VALUE) -1 else v.toInt()
    }
}
