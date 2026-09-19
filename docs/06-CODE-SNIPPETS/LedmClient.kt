package com.example.m175print.core.protocol

import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint

/**
 * Speaks HTTP/1.1 to the printer's embedded LEDM server OVER USB BULK PIPES.
 * Verified against this M175a: gSOAP/2.7 answers on the BIDI endpoint (0x89).
 *
 * Usage:
 *   val ledm = LedmClient(connection, epOut, epIn)
 *   val toner = ledm.tonerLevels()   // {black:81, cyan:9, magenta:9, yellow:11}
 */
class LedmClient(
    private val conn: UsbDeviceConnection,
    private val epOut: UsbEndpoint,
    private val epIn: UsbEndpoint
) {
    /** Minimal HTTP-over-USB request/response. */
    fun http(method: String, path: String, body: String = "",
             contentType: String = "text/xml; charset=utf-8"): String {
        val req = buildString {
            append("$method $path HTTP/1.1\r\n")
            append("HOST: localhost\r\n")
            if (body.isNotEmpty()) {
                append("Content-Type: $contentType\r\n")
                append("Content-Length: ${body.toByteArray().size}\r\n")
            }
            append("Connection: close\r\n\r\n")
            append(body)
        }.toByteArray(Charsets.ISO_8859_1)

        var sent = 0
        while (sent < req.size) {
            val n = conn.bulkTransfer(epOut, req, sent, req.size - sent, 5000)
            if (n < 0) throw IOException("USB write failed at $sent")
            sent += n
        }

        val buf = ByteArray(64 * 1024)
        val out = StringBuilder()
        var contentLength = -1
        var headerDone = false
        var received = 0
        val deadline = System.currentTimeMillis() + 10_000
        while (System.currentTimeMillis() < deadline) {
            val n = conn.bulkTransfer(epIn, buf, buf.size, 3000)
            if (n < 0) { if (headerDone && received >= contentLength) break else continue }
            out.append(String(buf, 0, n, Charsets.ISO_8859_1))
            received += n
            if (!headerDone) {
                val s = out.toString()
                val idx = s.indexOf("\r\n\r\n")
                if (idx > 0) {
                    headerDone = true
                    contentLength = Regex("Content-Length: (\\d+)", RegexOption.IGNORE_CASE)
                        .find(s)?.groupValues?.get(1)?.toInt() ?: -1
                    if (contentLength == -1) break   // connection: close → read till EOF
                }
            }
            if (contentLength > 0) {
                val idx = out.indexOf("\r\n\r\n")
                if (idx > 0 && out.length - idx - 4 >= contentLength) break
            }
        }
        val idx = out.indexOf("\r\n\r\n")
        return if (idx > 0) out.substring(idx + 4) else out.toString()
    }

    /** Real toner percentages. 255/absent = cartridge missing. */
    fun tonerLevels(): Map<String, Int> {
        val xml = http("GET", "/DevMgmt/ProductUsageDyn.xml")
        val map = mutableMapOf<String, Int>()
        Regex("<pudyn:Consumable>(.*?)</pudyn:Consumable>", RegexOption.DOT_MATCHES_ALL)
            .findAll(xml).forEach { blk ->
                val b = blk.groupValues[1]
                val color = Regex("<dd:MarkerColor>(\\w+)</dd:MarkerColor>")
                    .find(b)?.groupValues?.get(1)?.lowercase() ?: return@forEach
                val type = Regex("<dd:ConsumableTypeEnum>(\\w+)</dd:ConsumableTypeEnum>")
                    .find(b)?.groupValues?.get(1)?.lowercase() ?: ""
                val lvl = Regex("<dd:ConsumableRawPercentageLevelRemaining>(\\d+)</dd:ConsumableRawPercentageLevelRemaining>")
                    .find(b)?.groupValues?.get(1)?.toIntOrNull() ?: return@forEach
                if (lvl != 255) map["${type}_$color"] = lvl
            }
        return map
    }

    fun printerStatus(): String =
        Regex("<Status>([^<]+)</Status>")
            .find(http("GET", "/DevMgmt/ProductStatusDyn.xml"))
            ?.groupValues?.get(1) ?: "Unknown"

    fun capabilities(): String = http("GET", "/DevMgmt/ProductConfigDyn.xml")

    class IOException(msg: String) : Exception(msg)
}
