package com.ganesan.m175otg.scan

import com.ganesan.m175otg.usb.UsbPrinterConnection
import java.io.ByteArrayOutputStream

/**
 * Scan over USB OTG — HP LEDM / WS-Scan SOAP over the bulk channel.
 *
 * VERIFIED from real captures (scan-otg-235137.pcap + scan-otg-195230.pcap):
 *
 *   EP 0x03 OUT : HTTP POST (chunked, WITH "\r\n0\r\n\r\n" terminator) — SOAP
 *   EP 0x83 IN  : HTTP responses; the scanned JPEG arrives here (chunked DIME)
 *
 * Exact driver sequence:
 *   1) POST GetScannerElements   x3 -> 3x HTTP 202        (ARMING handshake)
 *   2) POST CreateScanJobRequest    -> HTTP 202 + <JobId>N</JobId>
 *   3) POST RetrieveImageRequest    -> HTTP 200 + chunked DIME JPEG
 *   4) POST GetJobInfo              -> 202
 *   5) POST GetPreviousImagePadInfo -> 202
 *
 * DESYNC-PROOF READER (v5 — fixes the "random corrupted scan"):
 * The printer's image response is CHUNKED — "800\r\n<data 2048B>\r\n" x N +
 * "0\r\n\r\n". USB reads can coalesce several frames into one bulkTransfer
 * (happens whenever the app reads late — queued frames are delivered to a
 * single URB), so completion CANNOT be detected by looking at the tail of
 * the buffer: the terminator may be buried mid-buffer. v4 did exactly that
 * and merged all 7 responses into one blob on the phone.
 *
 * v5 walks the chunk-size chain from the header end (a real transfer-layer
 * parser): completion = terminal 0-chunk found, regardless of how USB
 * framed the bytes. The body is then DECHUNKED before JPEG extraction, so
 * the interwoven "800\r\n" framing bytes never reach the decoder.
 */
class LedmScanClient(private val usb: UsbPrinterConnection) {

    companion object {
        // 1/1000-inch glass size for A4/Letter flatbed (captured values)
        const val GLASS_W = 8500
        const val GLASS_H = 11690

        private val HDR =
            "POST / HTTP/1.1\r\n" +
                    "Host: http:0\r\n" +
                    "User-Agent: gSOAP/2.7\r\n" +
                    "Content-Type: application/soap+xml; charset=utf-8\r\n" +
                    "Transfer-Encoding: chunked\r\n" +
                    "Connection: close\r\n\r\n"

        private val ENV_OPEN =
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" +   // \n — wire-exact!
                    "<SOAP-ENV:Envelope " +
                    "xmlns:SOAP-ENV=\"http://www.w3.org/2003/05/soap-envelope\" " +
                    "xmlns:SOAP-ENC=\"http://www.w3.org/2003/05/soap-encoding\" " +
                    "xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" " +
                    "xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\" " +
                    "xmlns:wscn=\"http://tempuri.org/wscn.xsd\">" +
                    "<SOAP-ENV:Body>"

        private val ENV_CLOSE = "</SOAP-ENV:Body></SOAP-ENV:Envelope>"
    }

    /** Scanner self-description parsed from GetScannerElementsResponse. */
    data class ScannerCaps(
        val colorModes: List<String>,
        val opticalDpi: Int,
        val platenMaxW: Int,
        val platenMaxH: Int,
        val adfSupported: Boolean,
        val adfDuplex: Boolean,
        val adfFeederCapacity: Int,
        val adfMaxW: Int,
        val adfMaxH: Int,
        val scannerState: String,
        val stateReason: String,
        val modelNumber: String,
    )

    /**
     * Asks the printer to describe its scanner (the SAME command the
     * Windows driver uses for arming — we keep the 2.1 KB XML answer).
     */
    fun getScannerCapabilities(): ScannerCaps {
        val resp = command(ENV_OPEN + "<wscn:GetScannerElements>" +
                "</wscn:GetScannerElements>" + ENV_CLOSE)
        if (resp.status != "202") throw IllegalStateException(
            "GetScannerElements: HTTP ${resp.status}")
        val xml = resp.bodyText()

        fun items(tag: String): List<String> {
            val block = Regex("<$tag[^>]*>(.*?)</$tag>")
                .find(xml)?.groupValues?.get(1) ?: return emptyList()
            return Regex("<item>([^<]*)</item>").findAll(block)
                .map { it.groupValues[1] }.toList()
        }

        fun g(t: String): String? =
            Regex("<$t>(-?\\d+)").find(xml)?.groupValues?.get(1)

        val platen = xml.substringAfter("<Platen>", "")
            .substringBefore("</Platen>")
        val adf = xml.substringAfter("<ADF>", "").substringBefore("</ADF>")
        fun gi(src: String, t: String): Int? =
            Regex("<$t>(-?\\d+)</$t>").find(src)?.groupValues?.get(1)?.toIntOrNull()

        // Width/Height appear in Minimum AND Maximum blocks — parse inside
        // *MaximumSize (mirror-tested against the real 2168-byte response).
        val platenMax = platen.substringAfter("<PlatenMaximumSize>", "")
            .substringBefore("</PlatenMaximumSize>")
        val adfMax = adf.substringAfter("<ADFMaximumSize>", "")
            .substringBefore("</ADFMaximumSize>")

        return ScannerCaps(
            colorModes = items("ColorSupported"),
            opticalDpi = Regex("<PlatenOpticalResolution><Width>(\\d+)")
                .find(platen)?.groupValues?.get(1)?.toIntOrNull() ?: 0,
            platenMaxW = gi(platenMax, "Width") ?: 8500,
            platenMaxH = gi(platenMax, "Height") ?: 11690,
            adfSupported = adf.contains("<ADFSupported>true</ADFSupported>"),
            adfDuplex = adf.contains("<ADFSupportsDuplex>true</ADFSupportsDuplex>"),
            adfFeederCapacity = g("FeederCapacity")?.toIntOrNull() ?: 0,
            adfMaxW = gi(adfMax, "Width") ?: 0,
            adfMaxH = gi(adfMax, "Height") ?: 0,
            scannerState = Regex("<ScannerState>([^<]+)").find(xml)
                ?.groupValues?.get(1) ?: "?",
            stateReason = Regex("<ScannerStateReason>([^<]+)").find(xml)
                ?.groupValues?.get(1) ?: "?",
            modelNumber = Regex("<ModelNumber>([^<]+)").find(xml)
                ?.groupValues?.get(1) ?: "?",
        )
    }

    /**
     * One full flatbed/ADF scan. Returns JPEG bytes.
     *
     * @param dpi 75 / 200 / 300 / 600 (true engine steps on this model)
     * @param colorMode RGB24 | Grayscale | BlackPixel1
     * @param inputSource Platen (glass) | Feeder (ADF)
     */
    fun scanFlatbed(dpi: Int = 300, colorMode: String = "RGB24",
                    inputSource: String = "Platen",
                    log: (String) -> Unit = {},
                    budgetMs: Long = 0L): ByteArray {
        resyncLog = log
        overallBudgetMs = budgetMs
        log("ledm: start dpi=$dpi $colorMode $inputSource")
        // flush anything stale queued on 0x83 from earlier sessions.
        // 800ms timeout: the default 5s turn-around added a visible delay to
        // every scan start.
        run { val junk = ByteArray(4096); while (usb.recvScanData(junk, 800) > 0) {} }
        carry.reset()

        try {
            // ---- 0. GetScannerElements x3 — the ARMING handshake ----------
            repeat(3) {
                val ack = command(ENV_OPEN + "<wscn:GetScannerElements>" +
                        "</wscn:GetScannerElements>" + ENV_CLOSE)
                log("ledm: GetScannerElements -> HTTP ${ack.status}")
                if (ack.status != "202") throw IllegalStateException(
                    "GetScannerElements: HTTP ${ack.status}")
            }

            // ---- 1. CreateScanJobRequest ------------------------------------
            val resp1 = command(ENV_OPEN + createScanJobXml(dpi, colorMode, inputSource) +
                    ENV_CLOSE)
            if (resp1.bodyText().contains(WscnScanClient.NOT_ACCEPTING)) {
                throw ScannerBlockedException()
            }
            val jobId = Regex("<JobId>(\\d+)</JobId>")
                .find(resp1.bodyText())?.groupValues?.get(1)
                ?: throw IllegalStateException(
                    "CreateScanJob failed: HTTP ${resp1.status}: ${resp1.bodyText().take(300)}")
            log("ledm: CreateScanJob -> HTTP ${resp1.status} JobId=$jobId")

            // ---- 2. RetrieveImageRequest (the JPEG) -------------------------
            val image = command(ENV_OPEN +
                    "<wscn:RetrieveImageRequest><JobId>$jobId</JobId>" +
                    "<JobToken></JobToken><DocumentDescription></DocumentDescription>" +
                    "</wscn:RetrieveImageRequest>" + ENV_CLOSE)
            if (image.status != "200") {
                throw IllegalStateException("RetrieveImage: HTTP ${image.status}")
            }
            val jpeg = extractJpeg(image.bodyBytes)
                ?: throw IllegalStateException("No JPEG found in image response")
            resyncLog?.invoke("ledm image ${jpeg.size}B — DIME headers stripped=" +
                    "$lastDimeHeadersStripped")

            // ---- 3. cleanup, driver-exact (LCD "Scanning to PC" fix) --------
            runCatching {
                command(ENV_OPEN +
                        "<wscn:GetJobInfo><jobId>$jobId</jobId></wscn:GetJobInfo>" +
                        ENV_CLOSE)
            }
            runCatching {
                command(ENV_OPEN +
                        "<wscn:GetPreviousImagePadInfo><jobId>$jobId</jobId>" +
                        "</wscn:GetPreviousImagePadInfo>" + ENV_CLOSE)
            }

            return jpeg
        } catch (e: Exception) {
            // unwind any half-open LEDM job so the printer returns to idle
            runCatching { usb.resetJobState() }
            throw e
        }
    }

    // ---------------------------------------------------------------- xml

    private fun createScanJobXml(dpi: Int, colorMode: String,
                                 inputSource: String = "Platen"): String =
        "<wscn:CreateScanJobRequest><ScanIdentifier></ScanIdentifier>" +
                "<ScanTicket><JobDescription></JobDescription>" +
                "<DocumentParameters>" +
                "<Format>jfif</Format>" +
                "<CompressionQualityFactor>0</CompressionQualityFactor>" +
                "<ImagesToTransfer>0</ImagesToTransfer>" +
                "<InputSource>$inputSource</InputSource>" +
                "<ContentType>Auto</ContentType>" +
                "<InputSize><InputMediaSize>" +
                "<Width>$GLASS_W</Width><Height>$GLASS_H</Height>" +
                "</InputMediaSize>" +
                "<DocumentSizeAutoDetect>false</DocumentSizeAutoDetect>" +
                "</InputSize>" +
                // REVERTED to driver-exact false: true produced BLACK images
                // on the real phone (unproven firmware path). The false-ticket
                // is wire-proven to yield a VALID (dim) image; brightness is
                // fixed client-side by ScanAutoLevels.
                "<Exposure><AutoExposure>false</AutoExposure>" +
                "<ExposureSettings><Contrast>0</Contrast></ExposureSettings>" +
                "</Exposure>" +
                "<MediaSides><MediaFront>" +
                "<ScanRegion>" +
                "<ScanRegionXOffset>0</ScanRegionXOffset>" +
                "<ScanRegionYOffset>0</ScanRegionYOffset>" +
                "<ScanRegionWidth>$GLASS_W</ScanRegionWidth>" +
                "<ScanRegionHeight>$GLASS_H</ScanRegionHeight>" +
                "</ScanRegion>" +
                "<ColorProcessing>$colorMode</ColorProcessing>" +
                "<Resolution><Width>$dpi</Width><Height>$dpi</Height>" +
                "</Resolution>" +
                "</MediaFront></MediaSides>" +
                "</DocumentParameters>" +
                "<RetrieveImageTimeout>300</RetrieveImageTimeout>" +
                "<ScanManufacturingParameters>" +
                "<DisableImageProcessing>false</DisableImageProcessing>" +
                "</ScanManufacturingParameters>" +
                "</ScanTicket></wscn:CreateScanJobRequest>"

    // ------------------------------------------------------------ transport

    /**
     * Sends one SOAP command and reads exactly one response.
     * Framing byte-exact from the capture: headers + "<hex-size>\r\n" +
     * body + "\r\n0\r\n\r\n" terminator (the terminator is on the wire as
     * its own 7-byte USB frame — omitting it means the printer never
     * parses the command at all).
     */
    private fun command(payloadXml: String): Response {
        val payload = payloadXml.toByteArray(Charsets.UTF_8)
        val out = ByteArrayOutputStream(payload.size + 64)
        out.write(HDR.toByteArray(Charsets.ISO_8859_1))
        out.write(("${payload.size.toString(16).uppercase()}\r\n")
            .toByteArray(Charsets.ISO_8859_1))
        out.write(payload)
        out.write("\r\n0\r\n\r\n".toByteArray(Charsets.ISO_8859_1))

        val data = out.toByteArray()
        var off = 0
        while (off < data.size) {
            val n = usb.sendScanCmd(data, off, data.size - off)
            if (n < 0) throw IllegalStateException("scan cmd write failed at $off")
            off += n
        }
        return readResponse()
    }

    data class Response(val status: String, val raw: ByteArray,
                        val bodyBytes: ByteArray) {
        fun bodyText(): String = String(bodyBytes, Charsets.UTF_8)
    }

    private fun readResponse(): Response {
        val raw = drainInbound()
        val text = String(raw, Charsets.ISO_8859_1)
        val status = Regex("HTTP/1\\.1 (\\d+)").find(text)
            ?.groupValues?.get(1) ?: "?"
        val he = text.indexOf("\r\n\r\n")
        if (he < 0) return Response(status, raw, ByteArray(0))
        val headers = text.substring(0, he)
        val bodyStart = he + 4

        val body: ByteArray = if (headers.lowercase()
                .contains("transfer-encoding: chunked")) {
            val end = chunkedEnd(raw, bodyStart)
            if (end > 0) dechunkBody(raw, bodyStart, end)
            else raw.copyOfRange(bodyStart, raw.size) // defensive fallback
        } else {
            val m = Regex("(?i)content-length:\\s*(\\d+)").find(headers)
            val cl = m?.groupValues?.get(1)?.toLong()?.toInt() ?: -1
            if (cl > 0 && raw.size >= bodyStart + cl)
                raw.copyOfRange(bodyStart, bodyStart + cl)
            else raw.copyOfRange(bodyStart, raw.size)
        }
        return Response(status, raw, body)
    }

    /**
     * Reads a complete response. Completion is determined by an
     * incremental CHUNK-CHAIN walk from the header end — immune to USB
     * read coalescing.
     *
     * COALESCING-CARRY FIX (the real corruption bug): one bulkTransfer
     * read can span TWO responses (phone reads late → host controller
     * dumps queued frames into one URB). On completion, any bytes beyond
     * this response's boundary are CARRIED into the next read cycle —
     * v5 discarded them, so the next response lost its header and the
     * whole session merged into one garbage blob (200/200 adversarial
     * failures; carry fix -> 0/200).
     * QUEUED-ACK FIX: one read can complete SEVERAL responses at once
     * (the carry arrives pre-loaded with a full 202) — a complete
     * buffered response returns IMMEDIATELY instead of idling to the
     * 8 s grace timeout.
     * Warm-up tolerant: the scanner may take ~40 s to emit the first
     * byte after RetrieveImage (lamp wake + travel).
     */
    private val carry = java.io.ByteArrayOutputStream()

    /** Per-call image budget override (600/1200 dpi scans are far slower
     *  than the 180 s default — set from scanFlatbed). */
    @Volatile private var overallBudgetMs: Long = 0L

    private fun drainInbound(): ByteArray {
        val buf = ByteArray(16 * 1024)
        val out = ByteArrayOutputStream(1 shl 20)
        var contentLength = -1L
        var headerEnd = -1
        val start = System.currentTimeMillis()
        val firstByteDeadline = start + 40_000
        val overallDeadline = start +
                (if (overallBudgetMs > 0) overallBudgetMs else 180_000)
        var lastData = 0L

        // Completion index of the buffered stream, or -1/0 when incomplete.
        // (-1 = header not yet found, 0 = header found, body pending.)
        fun completionEnd(all: ByteArray): Int {
            if (headerEnd < 0) {
                val idx = indexOfDoubleCrlf(all)
                if (idx < 0) return -1
                headerEnd = idx
                contentLength = Regex("(?i)content-length:\\s*(\\d+)")
                    .find(String(all, 0, idx, Charsets.ISO_8859_1))
                    ?.groupValues?.get(1)?.toLong() ?: -1L
            }
            return if (contentLength >= 0) {
                val want = (headerEnd + 4 + contentLength).toInt()
                if (all.size >= want) want else 0
            } else {
                chunkedEnd(all, headerEnd + 4)
            }
        }

        fun emit(all: ByteArray, end: Int): ByteArray {
            // keep the tail that belongs to the NEXT response
            if (all.size > end) carry.write(all, end, all.size - end)
            return all.copyOf(end)
        }

        // seed with leftover bytes from the previous response's read
        val seeded = carry.toByteArray()
        carry.reset()
        if (seeded.isNotEmpty()) {
            out.write(seeded)
            // QUEUED-ACK FIX: the carry may already contain a COMPLETE
            // response (big read delivered several queued acks at once).
            // Return it immediately instead of waiting for more USB data.
            val all = out.toByteArray()
            val end = completionEnd(all)
            if (end > 0) return emit(all, end)
        }

        while (System.currentTimeMillis() < overallDeadline) {
            val n = usb.recvScanData(buf)
            if (n > 0) {
                out.write(buf, 0, n)
                lastData = System.currentTimeMillis()
                val all = out.toByteArray()
                val end = completionEnd(all)
                if (end > 0) return emit(all, end)
            } else {
                if (out.size() == 0) {
                    if (System.currentTimeMillis() > firstByteDeadline) {
                        break // scanner never answered
                    }
                } else if (System.currentTimeMillis() - lastData > 45_000) {
                    // MID-STREAM STALL FIX (proven from saved phone files:
                    // 521-1943 KB truncations = the old 8 s one-shot grace
                    // gave up while the engine recalibrated mid-image —
                    // 600 dpi pauses exceed 40 s). The engine may pause
                    // MULTIPLE times per page; only the overall budget
                    // ends a truly dead stream.
                    val all = out.toByteArray()
                    val end = completionEnd(all)
                    if (end > 0) return emit(all, end)
                    lastData = System.currentTimeMillis() // keep waiting
                }
            }
        }
        return out.toByteArray()
    }

    // ---- chunked-transfer-encoding parser (wire-framing-proper) ----

    /** Index of "\r\n" at/after [from], or -1. */
    private fun indexOfCrlf(b: ByteArray, from: Int): Int {
        var i = from
        val limit = b.size - 1
        while (i < limit) {
            if (b[i] == 0x0D.toByte() && b[i + 1] == 0x0A.toByte()) return i
            i++
        }
        return -1
    }

    /**
     * RESYNC chunk-chain walker — the HP-Windows-driver strategy.
     *
     * PROVEN from the live laptop capture (scan-otg-110452, Sept 2026): the
     * printer's gSOAP stream can deliver a chunk SHORT of its declared size
     * (26 bytes short at the 64 KB boundary in our capture; intermittent —
     * other sessions were clean). A strict walker desyncs there and the
     * rest of the image becomes entropy garbage ('rainbow'). Driver-grade
     * behavior: when the declared boundary doesn't validate, scan forward
     * (512 B window) for the next size line and continue. Data between the
     * declared end and the real boundary is kept (JPEG restart markers let
     * decoders mask the tiny hole).
     */
    private fun chunkedEnd(b: ByteArray, start: Int): Int {
        val t = resyncChunkWalk(b, start, null)
        if (t < 0) return -1
        // terminator "0\r\n" + closing "\r\n" must be fully present
        return if (b.size >= t + 5) t + 5 else -1
    }

    /** Reassembles the chunked body [start, end) into raw data bytes. */
    private fun dechunkBody(b: ByteArray, start: Int, end: Int): ByteArray {
        val out = ByteArrayOutputStream(maxOf(64 * 1024, end - start))
        resyncChunkWalk(b, start, out)
        return out.toByteArray()
    }

    /** Resync telemetry — every fallback firing is logged with its byte
     *  offset (MainActivity wires this in; correlates wire events with the
     *  visible corruption point). */
    var resyncLog: ((String) -> Unit)? = null

    /**
     * Chunked-transfer framing walker — delegated to the single shared
     * implementation (ChunkedFraming) and covered by JVM unit tests that
     * run against real captured wire bytes.
     * Returns the index of the 0-terminator size line, or -1 if incomplete.
     */
    private fun resyncChunkWalk(b: ByteArray, start: Int, emit: ByteArrayOutputStream?): Int =
        ChunkedFraming.walk(b, start, emit, resyncLog)

    private fun indexOfDoubleCrlf(b: ByteArray): Int {
        for (i in 0 until b.size - 3) {
            if (b[i] == 0x0D.toByte() && b[i + 1] == 0x0A.toByte() &&
                b[i + 2] == 0x0D.toByte() && b[i + 3] == 0x0A.toByte()) return i
        }
        return -1
    }

    /** Interleaved DIME record headers removed from the last image (diagnostics). */
    private var lastDimeHeadersStripped = 0

    private fun extractJpeg(raw: ByteArray): ByteArray? {
        // CRITICAL ORDER (wire-proven): the printer weaves DIME record headers
        // (12 B) through the image every 2048 bytes, so the payload must be
        // assembled BEFORE slicing SOI..EOI. Slicing the raw body embeds those
        // headers inside the JPEG entropy stream and desyncs Huffman decoding
        // — the "top of page readable, then rainbow/flat bands" symptom.
        val dime = DimeFraming.assemblePayload(raw)
        lastDimeHeadersStripped =
            dime?.let { DimeFraming.countInterleavedHeaders(it.payload) } ?: 0
        val b = dime?.payload ?: raw
        val start = b.indexOf(0xFF); if (start < 0) return null
        var i = start
        while (i < b.size - 2) {
            if (b[i] == 0xFF.toByte() && b[i + 1] == 0xD8.toByte() &&
                b[i + 2] == 0xFF.toByte()) break
            i++
        }
        if (i >= b.size - 2) return null
        // LAST proper FF-D9 pair (a stray D9 byte without FF is not an EOI).
        var end = -1
        var k = b.size - 1
        while (k > i + 1) {
            if (b[k] == 0xD9.toByte() && b[k - 1] == 0xFF.toByte()) { end = k; break }
            k--
        }
        if (end <= i) return null
        return b.copyOfRange(i, end + 1)
    }

    private fun ByteArray.indexOf(b: Int): Int {
        for (i in indices) if (this[i] == b.toByte()) return i
        return -1
    }
}
