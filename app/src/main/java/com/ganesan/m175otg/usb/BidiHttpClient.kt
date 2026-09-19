package com.ganesan.m175otg.usb

import java.io.ByteArrayOutputStream

/**
 * HTTP/1.1 client that runs over the printer's USB BIDI bulk channel.
 *
 * Framing VERIFIED byte-exact from the Windows driver capture
 * (print-session-162140.pcap, frame 2263):
 *
 *   OUT (63 B): "GET /DevMgmt/ProductStatusDyn.xml HTTP/1.1\r\n
 *                HOST: localhost\r\n\r\n"          <- NO Connection: close!
 *
 *   IN  (EP 0x89): "HTTP/1.1 200 OK ... Content-Length: 1428\r\n\r\n<body>"
 *   plain Content-Length, NOT chunked. The reader must stop exactly at
 *   headerEnd + 4 + contentLength, or it swallows the NEXT response.
 *
 * The driver also keeps EP 0x89 permanently pumped (319k tiny reads in one
 * capture = status-event stream). We mirror that serialization WITHOUT a
 * background thread (it would race get() for frames): every conversation
 * starts with drainStale(), and all requests run one-at-a-time on the
 * caller's thread — the same discipline the driver's client uses.
 */
class BidiHttpClient(private val usb: UsbPrinterConnection) {

    /** One captured request+reply conversation. */
    fun get(path: String): String? {
        drainStale()
        val req = "GET $path HTTP/1.1\r\nHOST: localhost\r\n\r\n"
        if (usb.sendBidi(req.toByteArray(Charsets.ISO_8859_1)) < 0) return null
        val raw = readResponse() ?: return null
        val text = String(raw, Charsets.ISO_8859_1)
        val idx = text.indexOf("\r\n\r\n")
        if (idx < 0) return null
        val headers = text.substring(0, idx)
        val body = text.substring(idx + 4)
        val isChunked = headers.lowercase().contains("transfer-encoding: chunked")
        return if (isChunked) dechunk(body) else body
    }

    /**
     * Reads one complete response: waits for \r\n\r\n (headers), then until
     * Content-Length bytes of body have arrived. Falls back to a short
     * idle-gap stop when the printer omits the length.
     */
    private fun readResponse(): ByteArray? {
        val buf = ByteArray(16 * 1024)
        val out = ByteArrayOutputStream()
        var headerEnd = -1
        var contentLength = -1L
        val deadline = System.currentTimeMillis() + 15_000

        while (System.currentTimeMillis() < deadline) {
            val n = usb.recvBidi(buf)
            if (n <= 0) {
                // idle tick: only length-less replies may end here
                if (headerEnd >= 0 && contentLength < 0 &&
                    out.size() > headerEnd + 4) break
                continue
            }
            out.write(buf, 0, n)

            if (headerEnd < 0) {
                val all = out.toByteArray()
                val idx = indexOfDoubleCrlf(all)
                if (idx >= 0) {
                    headerEnd = idx
                    contentLength = parseContentLength(
                        String(all, 0, idx, Charsets.ISO_8859_1))
                }
            }
            if (headerEnd >= 0 && contentLength >= 0 &&
                out.size() >= headerEnd + 4 + contentLength) {
                break // COMPLETE — exact end of this response
            }
        }
        return if (out.size() == 0) null else out.toByteArray()
    }

    /** Clears any queued status frames so a new GET gets ITS OWN reply. */
    private fun drainStale() {
        val junk = ByteArray(4096)
        while (usb.recvBidi(junk) > 0) { /* keep pumping */ }
    }

    private fun indexOfDoubleCrlf(b: ByteArray): Int {
        for (i in 0 until b.size - 3) {
            if (b[i] == 0x0D.toByte() && b[i + 1] == 0x0A.toByte() &&
                b[i + 2] == 0x0D.toByte() && b[i + 3] == 0x0A.toByte()) return i
        }
        return -1
    }

    private fun parseContentLength(headers: String): Long =
        Regex("(?i)content-length:\\s*(\\d+)").find(headers)
            ?.groupValues?.get(1)?.toLong() ?: -1L

    private fun dechunk(body: String): String {
        val sb = StringBuilder()
        var i = 0
        while (i < body.length) {
            val eol = body.indexOf("\r\n", i)
            if (eol < 0) break
            val len = body.substring(i, eol).trim().split(";")[0]
                .toIntOrNull(16) ?: break
            if (len == 0) break
            sb.append(body, eol + 2, minOf(eol + 2 + len, body.length))
            i = eol + 2 + len + 2
        }
        return sb.toString()
    }

    /** Live toner levels, same endpoint Windows uses. E.g. {black:81, cyan:9}. */
    fun readToner(): Map<String, Int> {
        val xml = get("/DevMgmt/ProductUsageDyn.xml") ?: return emptyMap()
        return TonerParser.parse(xml)
    }

    /** Full consumable detail incl. image drum + pages-left estimates. */
    fun readConsumables(): List<TonerParser.Detailed> {
        val xml = get("/DevMgmt/ProductUsageDyn.xml") ?: return emptyList()
        return TonerParser.parseDetailed(xml)
    }

    data class Usage(val total: Int?, val color: Int?, val mono: Int?)

    /** Lifetime page counters (printer-level totals = first match in doc). */
    fun readUsage(): Usage {
        val xml = get("/DevMgmt/ProductUsageDyn.xml") ?: return Usage(null, null, null)
        fun t(tag: String) =
            Regex("<[\\w-]*:?$tag>(\\d+)</").find(xml)
                ?.groupValues?.get(1)?.toIntOrNull()
        return Usage(t("TotalImpressions"), t("ColorImpressions"),
            t("MonochromeImpressions"))
    }

    /** Printer status line text (what shows on its LCD). */
    fun readStatus(): String? {
        val xml = get("/DevMgmt/ProductStatusDyn.xml") ?: return null
        val m = Regex("<[^>]*LocString[^>]*>([^<]+)<").find(xml) ?: return null
        return m.groupValues[1]
    }
}

/**
 * Parser for HP LEDM consumable XML - all tags verified against this
 * printer's captured ProductUsageDyn.xml:
 *   <dd:MarkerColor>Black</dd:MarkerColor>
 *   <dd:ConsumableTypeEnum>toner|imageDrum</dd:ConsumableTypeEnum>
 *   <dd:ConsumableRawPercentageLevelRemaining>80</dd:...>
 *   <dd:EstimatedPagesRemaining>800</dd:...>
 */
object TonerParser {

    data class Consumable(val name: String, val percent: Int)

    data class Detailed(
        val name: String,
        val type: String,      // "toner" | "imageDrum"
        val percent: Int,
        val pagesLeft: Int?,   // printer's own estimate (null if absent)
    )

    private val block = Regex(
        "<[\\w-]*:?Consumable\\b[\\s\\S]*?</[\\w-]*:?Consumable>"
    )
    private val pct =
        Regex("ConsumableRawPercentageLevelRemaining>(-?\\d+)<")

    private fun g(t: String, b: String): String? =
        Regex("<[\\w-]*:?$t>([^<]*)</").find(b)?.groupValues?.get(1)

    private fun name(b: String): String? =
        g("MarkerColor", b) ?: g("MarkerColorName", b)
            ?: g("ConsumableLabel", b)

    fun parse(xml: String): Map<String, Int> {
        val map = LinkedHashMap<String, Int>()
        for (m in block.findAll(xml)) {
            val b = m.value
            val p = pct.find(b)?.groupValues?.get(1)?.toIntOrNull() ?: continue
            map[(name(b) ?: "consumable").lowercase()] = p
        }
        return map
    }

    /** Full detail incl. the image drum + pages-left estimates. */
    fun parseDetailed(xml: String): List<Detailed> {
        val out = mutableListOf<Detailed>()
        for (m in block.findAll(xml)) {
            val b = m.value
            val level = g("ConsumableRawPercentageLevelRemaining", b)
                ?.toIntOrNull() ?: continue
            val type = g("ConsumableTypeEnum", b) ?: "toner"
            out.add(
                Detailed(
                    (name(b) ?: type).lowercase(), type, level,
                    g("EstimatedPagesRemaining", b)?.toIntOrNull()
                )
            )
        }
        return out
    }
}
