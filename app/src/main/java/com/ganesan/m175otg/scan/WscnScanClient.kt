package com.ganesan.m175otg.scan

import com.ganesan.m175otg.usb.UsbPrinterConnection

/**
 * HP wscn scan transport — the protocol HP's OWN closed-source Linux scan
 * driver (`bb_soapht.so`, plugin-reason=SCANNING_SUPPORT) uses for this
 * printer family (scan-type=5 SOAPHT). Recovered verbatim from the ARM64
 * plugin binary (see M175-Android-DevKit/devkit-reference/bb_soapht/).
 *
 *   - SOAP namespace http://tempuri.org/wscn.xsd (HP flavor of WS-Scan)
 *   - HTTP "POST /" with "Host: http:0", gSOAP user-agent, chunked
 *   - Response image arrives as a DIME attachment (see DimeFraming — the
 *     record headers interleave INSIDE the image and MUST be stripped)
 *   - Formats: jfif / hpraw; modes: RGB24 / GrayScale8 / BlackandWhite1
 */
class WscnScanClient(private val usb: UsbPrinterConnection) {

    companion object {
        private const val ENV_HDR =
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>" +
            "<SOAP-ENV:Envelope xmlns:SOAP-ENV=\"http://www.w3.org/2003/05/soap-envelope\" " +
            "xmlns:SOAP-ENC=\"http://www.w3.org/2003/05/soap-encoding\" " +
            "xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" " +
            "xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\" " +
            "xmlns:wscn=\"http://tempuri.org/wscn.xsd\"><SOAP-ENV:Body>"

        private const val ENV_FTR = "</SOAP-ENV:Body></SOAP-ENV:Envelope>"

        /** Verbatim from bb_soapht.c (CreateScanJobRequest template). */
        private const val CREATE_JOB =
            ENV_HDR +
            "<wscn:CreateScanJobRequest><ScanIdentifier></ScanIdentifier><ScanTicket>" +
            "<JobDescription></JobDescription><DocumentParameters>" +
            // CompressionQualityFactor OMITTED: the printer's own capabilities
            // reply says QualityFactorSupported=false, so sending it is out of
            // spec and may drive its encoder into the corrupt-JPEG path.
            "<Format>%s</Format>" +
            "<ImagesToTransfer>%d</ImagesToTransfer>" +
            "<InputSource>%s</InputSource>" +
            "<ContentType>Auto</ContentType>" +
            "<InputSize><InputMediaSize><Width>%d</Width><Height>%d</Height>" +
            "</InputMediaSize><DocumentSizeAutoDetect>false</DocumentSizeAutoDetect></InputSize>" +
            "<Exposure><AutoExposure>false</AutoExposure><ExposureSettings>" +
            "<Contrast>%d</Contrast><Brightness>%d</Brightness>" +
            "</ExposureSettings></Exposure>" +
            "<MediaSides><MediaFront><ScanRegion>" +
            "<ScanRegionXOffset>%d</ScanRegionXOffset><ScanRegionYOffset>%d</ScanRegionYOffset>" +
            "<ScanRegionWidth>%d</ScanRegionWidth><ScanRegionHeight>%d</ScanRegionHeight>" +
            "</ScanRegion><ColorProcessing>%s</ColorProcessing>" +
            "<Resolution><Width>%d</Width><Height>%d</Height></Resolution>" +
            "</MediaFront></MediaSides>" +
            "</DocumentParameters>" +
            "<RetrieveImageTimeout>%d</RetrieveImageTimeout>" +
            "</ScanTicket></wscn:CreateScanJobRequest>" + ENV_FTR

        /** Verbatim from bb_soapht.c (RetrieveImageRequest template). */
        private const val RETRIEVE_IMAGE =
            ENV_HDR +
            "<wscn:RetrieveImageRequest><JobId>%d</JobId><JobToken></JobToken>" +
            "<DocumentDescription></DocumentDescription>" +
            "</wscn:RetrieveImageRequest>" + ENV_FTR

        /** Verbatim from bb_soapht.c (CancelJobRequest template). */
        private const val CANCEL_JOB =
            ENV_HDR +
            "<wscn:CancelJobRequest><JobId>%d</JobId><JobToken></JobToken>" +
            "<DocumentDescription></DocumentDescription>" +
            "</wscn:CancelJobRequest>" + ENV_FTR

        // ---- session CLOSE, Windows-driver-exact (captured WIA sequence).
        // The service stays "blocked / not accepting jobs" when a job is
        // dropped without this handshake, so every successful scan must end
        // with these two follow-ups — not a CancelJob.
        private const val GET_JOB_INFO =
            ENV_HDR + "<wscn:GetJobInfo><jobId>%d</jobId></wscn:GetJobInfo>" + ENV_FTR

        private const val GET_PAD_INFO =
            ENV_HDR +
            "<wscn:GetPreviousImagePadInfo><jobId>%d</jobId>" +
            "</wscn:GetPreviousImagePadInfo>" + ENV_FTR

        /** Fault subcode the printer returns while its scan service is blocked. */
        const val NOT_ACCEPTING = "ServerErrorNotAcceptingJobs"

        private const val GET_ELEMENTS =
            ENV_HDR + "<wscn:GetScannerElements></wscn:GetScannerElements>" + ENV_FTR

        /** Verbatim HTTP request head from bb_soapht.c. */
        private const val HTTP_HEAD =
            "POST / HTTP/1.1\r\n" +
            "Host: http:0\r\n" +
            "User-Agent: gSOAP/2.7\r\n" +
            "Content-Type: application/soap+xml; charset=utf-8\r\n" +
            "Transfer-Encoding: chunked\r\n" +
            "Connection: close\r\n\r\n"

        private const val READ_MS = 10_000
        // A 300 dpi colour page arrives in ~80 s on this engine. 180 s leaves
        // headroom without making a printer stall cost the user 5 minutes.
        // 600 dpi is the CCD sub-step (~4x the pixels, ~5 min real) and
        // 1200 dpi is the optical max (PlatenOpticalResolution=1200 from the
        // printer's own ScannerConfiguration) - those pass a larger budget
        // per call via scanFlatbed(budgetMs).
        private const val IMAGE_BUDGET_MS = 180_000L

        /**
         * FORENSIC dump dir (set by the UI). When non-null, the FAILURE path
         * of an image retrieve writes the RAW pre-dechunk response so the exact
         * chunk stream is auditable off-device. Successful scans do not dump.
         */
        var dumpDir: java.io.File? = null
    }

    data class WscnCaps(
        val rawXml: String,
        val formats: List<String>,
        val colorModes: List<String>,
        val resolutions: List<Int>,
        val flatbed: Boolean,
        val adf: Boolean
    )

    /**
     * Quick feeder check: reads ScannerStatus.ScanToStatus.PaperInADF from
     * the printer's status XML. Drives the multi-page ADF loop — no scanning
     * into an empty feeder (which would hang until the image budget dies).
     */
    fun adfHasPaper(log: (String) -> Unit = {}): Boolean {
        return try {
            val xml = String(transact(GET_ELEMENTS, log), Charsets.UTF_8)
            val blk = xml.substringAfter("<ScanToStatus>", "</ScanToStatus>")
                .substringBefore("</ScanToStatus>")
            blk.contains("<PaperInADF>true</PaperInADF>")
        } catch (e: Exception) {
            log("ADF paper check failed: ${e.message}")
            false
        }
    }

    /**
     * One flatbed/ADF scan. Returns JPEG bytes (DIME payload assembled, then
     * sliced — see extractJpeg).
     *
     * @param dpi  requested resolution — sent to the printer verbatim.
     *             Verified engine steps on this unit: 300 (native), 600
     *             (CCD sub-step), 1200 (optical max, flatbed only - the ADF
     *             tops out at 300 per its own configuration).
     * @param budgetMs  per-call timeout override for slow high-dpi scans
     */
    fun scanFlatbed(
        dpi: Int = 300,
        colorMode: String = "RGB24",       // RGB24 | GrayScale8
        inputSource: String = "Platen",    // Platen | ADF
        log: (String) -> Unit = {},
        budgetMs: Long = 0L
    ): ByteArray {
        logSink = log
        // Step 0: capabilities probe (bb_open equivalent) — also proves the
        // raw HTTP-over-EP0x03 channel answers at all.
        val capsXml = try {
            String(transact(GET_ELEMENTS, log), Charsets.UTF_8)
        } catch (e: Exception) {
            throw Exception("GetScannerElements: ${e.message}")
        }

        // Step 1: create the job. ImagesToTransfer=1 — multi-page ADF is
        // implemented as one job per page in the app (feeder state is checked
        // between pages), which is simpler and matches the wire traces.
        val createXml = String(transact(
            String.format(
                CREATE_JOB, "jfif", 1, inputSource,
                8500, 11690,                    // full glass, hundredths of an inch
                0, 0,                           // contrast, brightness
                0, 0, 8500, 11690,              // scan region
                colorMode,
                dpi, dpi,
                60                              // RetrieveImageTimeout
            ), log
        ), Charsets.UTF_8)
        log("wscn create response: " + createXml.replace('\n', ' ').take(900))
        if (createXml.contains(NOT_ACCEPTING)) {
            // VERIFIED wire fault: "The service is temporarily blocked and
            // can't accept new job or document requests."
            throw ScannerBlockedException()
        }
        val jobId = Regex("JobId[^0-9]{0,8}(\\d+)").find(createXml)?.groupValues?.get(1)?.toIntOrNull()
            ?: throw Exception("no JobId in create response: ${createXml.take(900)}")
        activeJobId = jobId
        log("wscn JobId=$jobId")

        val ppx = intTag(createXml, "PixelsPerLine")
        val ppy = intTag(createXml, "NumberOfLines")
        if (ppx != null && ppy != null) log("wscn image will be ${ppx}x$ppy")

        // Step 2: retrieve the image (DIME payload).
        // bb_soapht.c semantics: RetrieveImage is REPEATED until an image
        // actually arrives. Early in a job the printer answers with a small
        // "not ready" response (552B observed live on the first 1200 dpi
        // attempt) — throwing there killed every big-page scan. Big pages
        // (600/1200 dpi) take minutes before the first usable response.
        val imgDeadline = System.currentTimeMillis() +
                (if (budgetMs > 0) budgetMs else IMAGE_BUDGET_MS)
        var jpeg: ByteArray? = null
        var attemptNo = 0
        while (jpeg == null) {
            if (ScanControl.isCancelled) throw ScanCancelledException()
            if (System.currentTimeMillis() > imgDeadline)
                throw Exception("no image within ${imgDeadline / 1000}s (job $jobId)")
            attemptNo++
            val dime = transact(String.format(RETRIEVE_IMAGE, jobId), log,
                imageBudget = true, budgetMs = budgetMs)
            jpeg = extractJpeg(dime)
            if (jpeg == null) {
                if (dime.size < 4096) {
                    val t = String(dime, Charsets.UTF_8)
                    if (t.contains(NOT_ACCEPTING)) throw ScannerBlockedException()
                    if (t.contains("ClientErrorJobIdUnknown") ||
                        (t.contains("ClientErrorNoImagesAvailable") && attemptNo > 40))
                        throw Exception("job $jobId rejected: ${t.take(200)}")
                    log("retrieve attempt $attemptNo: printer not ready " +
                            "(${dime.size}B) - retrying in 5s")
                } else {
                    log("retrieve attempt $attemptNo: ${dime.size}B payload " +
                            "without JPEG - retrying in 5s")
                }
                Thread.sleep(5_000)
            }
        }
        log("wscn image received: ${jpeg.size}B, SOF=${lastSofWidth}x$lastSofHeight")

        // CLEAN SESSION CLOSE — the Windows WIA driver's exact follow-ups.
        // Ending the job this way is what keeps the printer's scan service
        // from going "blocked / not accepting jobs".
        activeJobId = null
        try { transact(String.format(GET_JOB_INFO, jobId), log, deadlineMs = 8_000L) } catch (_: Exception) {}
        try { transact(String.format(GET_PAD_INFO, jobId), log, deadlineMs = 8_000L) } catch (_: Exception) {}
        log("wscn session closed cleanly (GetJobInfo + GetPreviousImagePadInfo)")
        return jpeg
    }

    private var activeJobId: Int? = null

    /** Best-effort cancel of the active job (error path + post-scan cleanup). */
    fun cancelActive(log: (String) -> Unit = {}) {
        val id = activeJobId ?: return
        activeJobId = null
        cancel(id, log)
    }

    /** Best-effort cancel (bb_end_scan error path equivalent). */
    fun cancel(jobId: Int, log: (String) -> Unit = {}) {
        try {
            transact(String.format(CANCEL_JOB, jobId), log)
            log("wscn job $jobId cancelled")
        } catch (_: Exception) {
        }
    }

    /**
     * SOFT recovery — halted endpoint / stale bytes in the channel.
     * Cheap, non-destructive, safe to run automatically after a failure.
     */
    fun softRecover(log: (String) -> Unit = {}) {
        log("softRecover: clearing endpoint halts + draining")
        usb.recoverScanEndpoints()
        val buf = ByteArray(64 * 1024)
        var silent = 0
        while (silent < 3) {
            val n = try { usb.recvScanData(buf, 800) } catch (_: Exception) { -1 }
            if (n > 0) silent = 0 else silent++
        }
    }

    /**
     * FULL scan-engine rescue — call when scans fail instantly or the
     * printer's ScannerStatus reports Processing forever.
     *
     * 1. USB CLEAR_FEATURE(ENDPOINT_HALT) on the scan/BIDI endpoints —
     *    a stalled EP makes every transfer fail in milliseconds.
     * 2. CancelJob for a small range of JobIds — the wedged job (if any)
     *    is almost always one of the last few the printer handed out;
     *    CancelJob on an unknown/expired id is answered with a harmless
     *    SOAP fault, so this is safe.
     * 3. Drain EP 0x83 until silent — drops any stale response bytes.
     * 4. Confirm via GetScannerElements that ScannerStatus is Idle again.
     */
    fun rescueEngine(usb: com.ganesan.m175otg.usb.UsbPrinterConnection,
                     log: (String) -> Unit = {}) {
        log("rescue: clearing endpoint halts")
        usb.recoverScanEndpoints()

        log("rescue: draining scan channel")
        val buf = ByteArray(64 * 1024)
        var silent = 0
        while (silent < 3) {
            val n = try { usb.recvScanData(buf, 800) } catch (_: Exception) { -1 }
            if (n > 0) silent = 0 else silent++
        }

        // PROBE the channel with a short deadline — on a wedged engine every
        // SOAP call would otherwise eat the full 45 s timeout (40 x 45 s =
        // the hang seen in the field).
        val alive = try {
            transact(GET_ELEMENTS, log, deadlineMs = 6_000L)
            true
        } catch (e: Exception) {
            log("rescue: channel dead (${e.message?.take(60) ?: "?"}) - going straight to USB reset")
            false
        }

        if (alive) {
            log("rescue: cancelling stale jobs (short deadline)")
            for (id in 1..40) {
                try {
                    transact(String.format(CANCEL_JOB, id), log, deadlineMs = 3_000L)
                } catch (_: Exception) {}
            }
        }

        // verify the engine left Processing
        val idle = try {
            val xml = String(transact(GET_ELEMENTS, log, deadlineMs = 8_000L), Charsets.UTF_8)
            val blk = xml.substringAfter("<ScannerStatus>", "</ScannerStatus>")
                .substringBefore("</ScannerStatus>")
            val st = blk.substringAfter("<ScannerState>", "</ScannerState>")
                .substringBefore("</ScannerState>")
            val reason = blk.substringAfter("<ScannerStateReason>", "</ScannerStateReason>")
                .substringBefore("</ScannerStateReason>")
            log("rescue: scanner state now '$st' reason='$reason'")
            st.contains("Idle", true)
        } catch (e: Exception) {
            log("rescue: state check failed: ${e.message}")
            false
        }
        if (!idle) {
            log("rescue: still busy - USB SET_CONFIGURATION reset")
            val reopened = usb.resetAndReopen()
            log("rescue: device reset " + if (reopened) "OK, re-claimed" else "FAILED to re-open")
            if (reopened) {
                val st2 = try {
                    val xml = String(transact(GET_ELEMENTS, log, deadlineMs = 8_000L), Charsets.UTF_8)
                    val st = xml.substringAfter("<ScannerState>", "</ScannerState>")
                        .substringBefore("</ScannerState>")
                    val rs = xml.substringAfter("<ScannerStateReason>", "</ScannerStateReason>")
                        .substringBefore("</ScannerStateReason>")
                    "$st (reason='$rs', raw=${xml.replace('\n', ' ').take(400)})"
                } catch (_: Exception) { "?" }
                log("rescue: scanner state after reset '$st2'")
            }
        }
    }

    // ------------------------------------------------------------ transport

    /**
     * Leftover bytes of the NEXT response (one USB read can span two
     * responses). Dropping these made every later transact start mid-garbage.
     */
    private val carry = java.io.ByteArrayOutputStream()

    /** One HTTP/SOAP round trip on EP 0x03/0x83. Returns the body bytes. */
    private fun transact(xml: String, log: (String) -> Unit, imageBudget: Boolean = false,
                         deadlineMs: Long = 45_000L, budgetMs: Long = 0L): ByteArray {
        logSink = log
        // chunked request, exactly as gSOAP sends it
        val payload = xml.toByteArray(Charsets.UTF_8)
        val head = HTTP_HEAD.toByteArray(Charsets.ISO_8859_1)
        val chunk = "%x\r\n".format(payload.size).toByteArray(Charsets.ISO_8859_1)
        val tail = "\r\n0\r\n\r\n".toByteArray(Charsets.ISO_8859_1)
        val req = ByteArray(head.size + chunk.size + payload.size + tail.size)
        var p0 = 0
        System.arraycopy(head, 0, req, p0, head.size); p0 += head.size
        System.arraycopy(chunk, 0, req, p0, chunk.size); p0 += chunk.size
        System.arraycopy(payload, 0, req, p0, payload.size); p0 += payload.size
        System.arraycopy(tail, 0, req, p0, tail.size)

        val wrote = usb.sendScanCmd(req)
        if (wrote < 0) throw Exception("EP 0x03 write failed (channel not answering)")

        val imageDeadline = if (imageBudget && budgetMs > 0) budgetMs else IMAGE_BUDGET_MS
        val deadline = System.currentTimeMillis() +
                (if (imageBudget) imageDeadline else deadlineMs)
        val buf = ByteArray(64 * 1024)
        var all = ByteArray(0)
        // seed with leftovers from the previous response (coalesced reads)
        val seeded = carry.toByteArray()
        carry.reset()
        if (seeded.isNotEmpty()) {
            all = seeded
            if (responseComplete(all, imageBudget)) return finish(all, imageBudget)
        }
        // NO idle-count shortcut: only a PARSED-COMPLETE response ends the loop.
        while (System.currentTimeMillis() < deadline) {
            if (ScanControl.isCancelled) throw ScanCancelledException()
            val n = usb.recvScanData(buf)
            if (n > 0) {
                val merged = ByteArray(all.size + n)
                System.arraycopy(all, 0, merged, 0, all.size)
                System.arraycopy(buf, 0, merged, all.size, n)
                all = merged
                if (responseComplete(all, imageBudget)) return finish(all, imageBudget)
            }
            // while waiting for the lamp/engine, just keep polling
        }
        if (all.isEmpty()) throw Exception("no response on EP 0x83 (timeout after ${if (imageBudget) "${imageDeadline / 1000}s image" else "${deadlineMs / 1000}s"})")
        // forensic: the FAILURE path is exactly where the chunk chain diverges
        // — dump the partial raw stream so the framing can be audited.
        if (imageBudget) dumpRawResponse(all, body(all))
        // NOTE: Byte must be widened for %x — "%02x".format(byte) throws
        // IllegalFormatConversionException and would mask the real error.
        throw Exception("response incomplete after ${all.size}B (timeout) — first 60B: " +
                all.take(60).joinToString("") { "%02x".format(it.toInt() and 0xFF) })
    }

    /** Park any next-response bytes into carry, then return this body. */
    private fun finish(all: ByteArray, imageBudget: Boolean): ByteArray {
        val end = responseEndIndex(all)
        if (end in 1 until all.size) carry.write(all, end, all.size - end)
        val scoped = if (end > 0) all.copyOf(end) else all
        val b = body(scoped)
        return b
    }

    /**
     * FORENSIC: writes the untouched pre-dechunk response + chunk-size
     * telemetry on the FAILURE path only.
     */
    private fun dumpRawResponse(raw: ByteArray, dechunked: ByteArray) {
        val dir = dumpDir
        val tag = "${System.currentTimeMillis()}-${dechunked.size}"
        if (dir != null) try {
            dir.mkdirs()
            java.io.File(dir, "wscn-raw-$tag.bin").writeBytes(raw)
            java.io.File(dir, "wscn-dechunked-$tag.bin").writeBytes(dechunked)
            pruneForensicDumps(dir)
        } catch (_: Exception) {
        }
        try {
            val hdrEnd = findDoubleCrlf(raw) ?: -1
            if (hdrEnd > 0 && containsIgnoreCase(raw, 0, hdrEnd, "Transfer-Encoding: chunked")) {
                val sizes = ArrayList<Int>()
                var i = hdrEnd + 4
                var diverged = -1
                var guard = 0
                while (i < raw.size && guard++ < 200_000) {
                    var j = i
                    while (j + 1 < raw.size &&
                        !(raw[j] == 13.toByte() && raw[j + 1] == 10.toByte())) j++
                    if (j + 1 >= raw.size) { diverged = i; break }
                    val sz = parseHex(raw, i, j)
                    if (sz < 0) { diverged = i; break }
                    sizes.add(sz)
                    if (sz == 0) break
                    if (j + 2 + sz + 2 > raw.size) { diverged = i; break }
                    i = j + 2 + sz + 2
                }
                val dups = sizes.groupingBy { it }.eachCount().entries
                    .sortedByDescending { it.value }.take(4)
                    .joinToString(",") { "${it.key}x${it.value}" }
                logSink?.invoke(
                    "wscn RAW: ${raw.size}B hdrEnd=$hdrEnd chunks=${sizes.size} " +
                        "sizes[$dups] divergedAt=$diverged dechunked=${dechunked.size}B")
            } else {
                logSink?.invoke("wscn RAW: ${raw.size}B not-chunked hdrEnd=$hdrEnd " +
                        "dechunked=${dechunked.size}B")
            }
        } catch (_: Exception) {
        }
    }

    /** Keeps only the newest 6 raw+dechunked dump pairs (they can be large). */
    private fun pruneForensicDumps(dir: java.io.File) {
        val dumps = dir.listFiles { f ->
            f.name.startsWith("wscn-raw-") || f.name.startsWith("wscn-dechunked-")
        }?.sortedByDescending { it.lastModified() } ?: return
        dumps.drop(12).forEach { it.delete() }
    }

    /** Byte index just past the completed response, or -1 if unknown. */
    private fun responseEndIndex(b: ByteArray): Int {
        val hdrEnd = findDoubleCrlf(b) ?: return -1
        val chunked = containsIgnoreCase(b, 0, hdrEnd, "Transfer-Encoding: chunked")
        if (chunked) {
            val term = resyncChunkWalk(b, hdrEnd + 4, null)
            if (term < 0) return -1
            val end = findDoubleCrlf(b, term) ?: return b.size
            return end + 4
        }
        val cl = Regex("Content-Length:\\s*(\\d+)", RegexOption.IGNORE_CASE)
            .find(String(b, 0, hdrEnd, Charsets.ISO_8859_1))
            ?.groupValues?.get(1)?.toIntOrNull()
        if (cl != null && cl > 0 && hdrEnd + 4 + cl <= b.size) return hdrEnd + 4 + cl
        // close-delimited SOAP: end just past the envelope close. The
        // printer's gSOAP emits "</SOAP-ENV:Envelope>" — match the tag SUFFIX
        // ("Envelope>") so any namespace prefix works.
        val env = lastIndexOfSeq(b, "Envelope>".toByteArray(Charsets.ISO_8859_1))
        if (env >= 0) return env + "Envelope>".length
        return b.size
    }

    private fun lastIndexOfSeq(b: ByteArray, pat: ByteArray): Int {
        outer@ for (i in b.size - pat.size downTo 0) {
            for (j in pat.indices) if (b[i + j] != pat[j]) continue@outer
            return i
        }
        return -1
    }

    /**
     * RESYNC chunked-completeness — the HP-Windows-driver strategy.
     * Completion = real 0-chunk terminator found (with forward/backward
     * resync when the printer's declared sizes drift).
     */
    private fun responseComplete(b: ByteArray, wantImage: Boolean): Boolean {
        // safety cap. A 1200 dpi colour page is ~8-10 MB of jfif - the cap
        // must never bite a legitimate image (6 MB cut real 600 dpi scans).
        if (b.size > 30_000_000) return true
        val hdrEnd = findDoubleCrlf(b) ?: return false
        val isChunked = containsIgnoreCase(b, 0, hdrEnd, "Transfer-Encoding: chunked")
        if (isChunked) {
            return resyncChunkWalk(b, hdrEnd + 4, emit = null) >= 0
        }
        if (wantImage) {
            if (dimeLooksComplete(b)) return true
            return findSeq(b, 0xFFD8) >= 0 && endsWithEoi(b)
        }
        // non-chunked small SOAP ack: honor Content-Length framing when
        // present; otherwise complete only when the SOAP envelope close
        // has actually arrived (never 'first read = whole thing').
        val cl = Regex("Content-Length:\\s*(\\d+)", RegexOption.IGNORE_CASE)
            .find(String(b, 0, hdrEnd, Charsets.ISO_8859_1))
            ?.groupValues?.get(1)?.toIntOrNull()
        if (cl != null && cl > 0) return b.size >= hdrEnd + 4 + cl
        // gSOAP closes with "</SOAP-ENV:Envelope>" — match the suffix
        return containsIgnoreCase(b, hdrEnd, b.size, "Envelope>")
    }

    /** Resync telemetry — every fallback firing is logged with its byte offset. */
    private var logSink: ((String) -> Unit)? = null

    /**
     * Chunked-transfer framing walker — delegated to the single shared
     * implementation (ChunkedFraming) and covered by JVM unit tests that
     * run against real captured wire bytes.
     */
    private fun resyncChunkWalk(b: ByteArray, start: Int, emit: java.io.ByteArrayOutputStream?): Int =
        ChunkedFraming.walk(b, start, emit) { logSink?.invoke(it) }

    private fun endsWithEoi(b: ByteArray): Boolean {
        for (k in b.size - 1 downTo maxOf(0, b.size - 8)) {
            if ((b[k].toInt() and 0xFF) == 0xD9 &&
                k > 0 && (b[k - 1].toInt() and 0xFF) == 0xFF) return true
        }
        return false
    }

    /** True if the buffer parses as DIME records whose chain reaches ME=1. */
    private fun dimeLooksComplete(b: ByteArray): Boolean {
        var i = 0
        var guard = 0
        while (i + 12 <= b.size && guard++ < 10_000) {
            val b0 = b[i].toInt() and 0xFF
            if ((b0 shr 5) != 1) return false
            val me = (b0 and 0x08) != 0
            val optLen = ((b[i + 2].toInt() and 0xFF) shl 8) or (b[i + 3].toInt() and 0xFF)
            val idLen = ((b[i + 4].toInt() and 0xFF) shl 8) or (b[i + 5].toInt() and 0xFF)
            val tyLen = ((b[i + 6].toInt() and 0xFF) shl 8) or (b[i + 7].toInt() and 0xFF)
            val dataLen = ((b[i + 8].toInt() and 0xFF) shl 24) or ((b[i + 9].toInt() and 0xFF) shl 16) or
                    ((b[i + 10].toInt() and 0xFF) shl 8) or (b[i + 11].toInt() and 0xFF)
            var p = i + 12 + pad4(optLen) + pad4(idLen) + pad4(tyLen)
            if (p + dataLen > b.size) return false
            i = p + pad4(dataLen)
            if (me) return true
        }
        return false
    }

    /** Finds "\r\n\r\n" at/after [from]. Returns index of the first CR or null. */
    private fun findDoubleCrlf(b: ByteArray, from: Int = 0): Int? {
        var i = from
        while (i + 3 < b.size) {
            if (b[i] == 13.toByte() && b[i + 1] == 10.toByte() && b[i + 2] == 13.toByte() && b[i + 3] == 10.toByte()) return i
            i++
        }
        return null
    }

    private fun containsIgnoreCase(b: ByteArray, from: Int, to: Int, s: String): Boolean {
        val pat = s.toByteArray(Charsets.ISO_8859_1)
        var i = from
        outer@ while (i + pat.size <= to) {
            for (j in pat.indices) {
                val c1 = b[i + j].toInt() and 0xFF
                val c2 = pat[j].toInt() and 0xFF
                val d = if (c1 in 65..90) c1 + 32 else c1
                val e = if (c2 in 65..90) c2 + 32 else c2
                if (d != e) { i++; continue@outer }
            }
            return true
        }
        return false
    }

    private fun parseHex(b: ByteArray, s: Int, e: Int): Int {
        var v = 0
        for (k in s until e) {
            val c = b[k].toInt() and 0xFF
            val d = when (c) {
                in 48..57 -> c - 48
                in 97..102 -> c - 87
                in 65..70 -> c - 55
                else -> return -1
            }
            v = v * 16 + d
        }
        return v
    }

    /** Strips HTTP headers and de-chunks using the resync walker. */
    private fun body(b: ByteArray): ByteArray {
        val hdrEnd = findDoubleCrlf(b) ?: return b
        val isChunked = containsIgnoreCase(b, 0, hdrEnd, "Transfer-Encoding: chunked")
        if (!isChunked) return b.copyOfRange(hdrEnd + 4, b.size)
        val out = java.io.ByteArrayOutputStream(maxOf(64 * 1024, b.size))
        resyncChunkWalk(b, hdrEnd + 4, emit = out)
        return out.toByteArray()
    }

    // ------------------------------------------------------------ DIME

        var lastSofWidth = 0
        var lastSofHeight = 0

        /**
         * Assembles the image payload, THEN slices the JPEG.
         *
         * Order matters and is wire-proven: the printer wraps the image in a
         * DIME record chain whose 12-byte headers sit INSIDE the image every
         * 2048 bytes. Slicing SOI..EOI out of the RAW body embeds a header in
         * the JPEG entropy stream every 2048 bytes, which desyncs Huffman
         * decoding -> the "clean top then rainbow" page.
         */
        private fun extractJpeg(b: ByteArray): ByteArray? {
        val dime = DimeFraming.assemblePayload(b)
        if (dime != null) {
            return sliceJpeg(dime.payload)
        }
        // Not a DIME chain (bare JPEG body) — slice it directly.
        return sliceJpeg(b)
    }

    private fun pad4(n: Int) = (n + 3) and 0x7FFFFFFC.toInt()

    /** SOI..LAST-EOI slice; also records SOF0 dimensions for diagnostics. */
    private fun sliceJpeg(b: ByteArray): ByteArray? {
        val soi = findSeq(b, 0xFFD8)
        if (soi < 0) return null
        // LAST EOI, not first: entropy data can contain FF D9 pairs, and
        // slicing at the first one is exactly the 'top of page' bug class.
        var eoi = -1
        var k = soi + 2
        while (true) {
            val hit = findSeq(b, 0xFFD9, k)
            if (hit < 0) break
            eoi = hit
            k = hit + 2
        }
        if (eoi < 0) return null
        sofDims(b, soi, eoi)
        return b.copyOfRange(soi, eoi + 2)
    }

    /** Parses SOF0/1/2 for WxH so truncation vs engine issues are separable. */
    private fun sofDims(b: ByteArray, soi: Int, eoi: Int) {
        lastSofWidth = 0; lastSofHeight = 0
        var i = soi + 2
        while (i + 3 < eoi) {
            if ((b[i].toInt() and 0xFF) != 0xFF) { i++; continue }
            val m = b[i + 1].toInt() and 0xFF
            if (m == 0xC0 || m == 0xC1 || m == 0xC2) {
                if (i + 8 < b.size) {
                    lastSofHeight = ((b[i + 5].toInt() and 0xFF) shl 8) or (b[i + 6].toInt() and 0xFF)
                    lastSofWidth = ((b[i + 7].toInt() and 0xFF) shl 8) or (b[i + 8].toInt() and 0xFF)
                }
                return
            }
            if (m == 0xD8 || m == 0x01 || m in 0xD0..0xD7) { i += 2; continue }
            val len = ((b[i + 2].toInt() and 0xFF) shl 8) or (b[i + 3].toInt() and 0xFF)
            if (len <= 0) return
            i += 2 + len
        }
    }

    private fun findSeq(b: ByteArray, seq: Int, from: Int = 0): Int {
        val hi = (seq shr 8) and 0xFF
        val lo = seq and 0xFF
        var i = from
        while (i + 1 < b.size) {
            if ((b[i].toInt() and 0xFF) == hi && (b[i + 1].toInt() and 0xFF) == lo) return i
            i++
        }
        return -1
    }

    // ------------------------------------------------------------ XML bits

    private fun intTag(xml: String, tag: String): Int? =
        Regex("<$tag>\\s*(\\d+)\\s*</$tag>").find(xml)?.groupValues?.get(1)?.toIntOrNull()

    private fun listTag(xml: String, tag: String): List<String> =
        Regex("<$tag>(.*?)</$tag>", RegexOption.DOT_MATCHES_ALL)
            .findAll(xml).map { it.groupValues[1].trim() }.toList()
}
