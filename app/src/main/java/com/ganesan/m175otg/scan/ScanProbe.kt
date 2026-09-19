package com.ganesan.m175otg.scan

import com.ganesan.m175otg.usb.UsbPrinterConnection

/**
 * EXPERIMENTAL: scanner channel probe (EP 0x81).
 *
 * What is PROVEN from captures:
 *  - EP 0x81 carries continuous scanner status chatter (27-byte frames)
 *  - the scanner interface (MI_00) exists and Windows drives it via
 *    hpwia2_lj100m175.dll (WIA)
 *  - 150dpi requests are silently quantized to 200dpi; true engine steps
 *    are 75/200/300/600 (verified over eSCL on the PC bridge)
 *  - RESOLUTION COHERENCE (measured Sept 2026 from native JPEGs): raw
 *    RGB24 output is only structurally coherent at 300 dpi (channel
 *    spread 0-23). At 150/200 dpi the engine decimates RGB lines with
 *    misregistration -> "rainbow stripes" (spread 94-143). HP's Windows
 *    driver repairs this in software. The app therefore scans at 300 dpi.
 *
 * What is NOT yet decoded: the full eSCL-over-USB framing Windows uses.
 * Plan: run a USBPcap capture during a scan session and mirror it here -
 * the bridge tools (tools/auto_capture.py + analyze_pcap.py) already do
 * the capture+decode; the results plug into this class.
 *
 * Meanwhile, full scanning WORKS through the Wi-Fi path (eSCL on the PC
 * bridge at /eSCL) - see 04-SCANNING-GUIDE.md.
 */
class ScanProbe(private val usb: UsbPrinterConnection) {

    data class ScanFrame(val raw: ByteArray)

    /** Non-blocking read of whatever the scanner channel offers. */
    fun poll(): ScanFrame? {
        val buf = ByteArray(64 * 1024)
        val n = usb.recvScan(buf)
        return if (n > 0) ScanFrame(buf.copyOf(n)) else null
    }

    /**
     * Collects scanner chatter for [ms] - used by the diagnostics screen
     * to prove the scanner interface is alive before a decode session.
     */
    fun listen(ms: Long, onFrame: (ScanFrame) -> Unit) {
        val deadline = System.currentTimeMillis() + ms
        while (System.currentTimeMillis() < deadline) {
            poll()?.let(onFrame)
            Thread.sleep(5)
        }
    }
}
