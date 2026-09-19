package com.ganesan.m175otg.usb

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import androidx.core.content.ContextCompat

/**
 * USB host connection to the HP LaserJet 100 color MFP M175a.
 *
 * Endpoint map VERIFIED from real USBPcap captures of this printer
 * (VID 03F0, PID 062A):
 *   EP 0x01 bulk OUT -> raw PJL/PCLXL print stream (NO HTTP wrapping)
 *   EP 0x09 bulk OUT -> HTTP requests  (HP LEDM / BIDI channel)
 *   EP 0x89 bulk IN  -> HTTP responses (toner/status XML)
 *   EP 0x81 bulk IN  -> scanner channel (see ScanProbe)
 */
/** Thrown when a print transfer stops because the user cancelled the job. */
class PrintCancelledException : java.io.IOException("print cancelled")

class UsbPrinterConnection(private val context: Context) {

    companion object {
        const val HP_VENDOR_ID = 0x03F0
        const val ACTION_USB_PERMISSION = "com.ganesan.m175otg.USB_PERMISSION"

        const val EP_PRINT_OUT = 0x01
        const val EP_BIDI_OUT = 0x09
        const val EP_BIDI_IN = 0x89
        const val EP_SCAN_IN = 0x81
        const val EP_SCAN_CMD_OUT = 0x03
        const val EP_SCAN_DATA_IN = 0x83

        const val TIMEOUT_MS = 5000
        const val CHUNK = 16 * 1024 // max bulk transfer size on Android
    }

    private val manager: UsbManager =
        context.getSystemService(Context.USB_SERVICE) as UsbManager

    var connection: UsbDeviceConnection? = null
        private set
    var device: UsbDevice? = null
        private set
    val isOpen: Boolean get() = connection != null

    private val claimed = mutableListOf<UsbInterface>()

    /** The first HP USB device currently attached via OTG. */
    fun findPrinter(): UsbDevice? =
        manager.deviceList.values.firstOrNull { it.vendorId == HP_VENDOR_ID }

    fun requestPermission(device: UsbDevice, onResult: (Boolean) -> Unit) {
        val pi = PendingIntent.getBroadcast(
            context, 0,
            Intent(ACTION_USB_PERMISSION).setPackage(context.packageName),
            PendingIntent.FLAG_MUTABLE
        )
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) {
                if (i.action != ACTION_USB_PERMISSION) return
                val granted =
                    i.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                context.unregisterReceiver(this)
                onResult(granted)
            }
        }
        ContextCompat.registerReceiver(
            context, receiver, IntentFilter(ACTION_USB_PERMISSION),
            ContextCompat.RECEIVER_NOT_EXPORTED
        )
        manager.requestPermission(device, pi)
    }

    /** Opens the device and claims every interface (print + scan + BIDI). */
    fun open(d: UsbDevice): Boolean {
        device = d
        val conn = manager.openDevice(d) ?: return false
        connection = conn
        for (i in 0 until d.interfaceCount) {
            val iface = d.getInterface(i)
            if (conn.claimInterface(iface, true)) claimed.add(iface)
        }
        return claimed.isNotEmpty()
    }

    fun endpoint(address: Int): UsbEndpoint? {
        val d = device ?: return null
        for (i in 0 until d.interfaceCount) {
            val iface = d.getInterface(i)
            for (j in 0 until iface.endpointCount) {
                val ep = iface.getEndpoint(j)
                if (ep.address.toInt() == address) return ep
            }
        }
        return null
    }

    /**
     * Sends one raw print-stream chunk to EP 0x01. Returns bytes written or -1.
     *
     * BLANK-PAGE FIX (v4): the printer STOPS draining this endpoint for
     * many seconds while it renders earlier pages (real 40-60s+ pauses at
     * 600dpi). The Windows driver BLOCKS on the transfer until the printer
     * takes the data. Retrying the same chunk after each timeout risks
     * duplicating bytes (printer accepted PART of a chunk before stalling
     * -> stream shifts -> blank pages mid-job). So now: long single
     * timeouts (10s per call) inside a 5-minute overall budget, then -1.
     */
    /**
     * Set while the user presses Cancel. The print sender checks it between
     * chunks and unwinds, so an abort sequence can then reach the printer
     * cleanly (instead of interleaving with live PCL XL data).
     */
    @Volatile
    var cancelRequested: Boolean = false

    /**
     * Sends one raw print-stream chunk to EP 0x01.
     * Returns bytes written, -1 on failure, or -2 when cancelled.
     */
    fun sendPrint(data: ByteArray, offset: Int = 0, len: Int = data.size): Int {
        val ep = endpoint(EP_PRINT_OUT) ?: return -1
        val deadline = System.currentTimeMillis() + 300_000 // 5 min per chunk worst case
        while (true) {
            if (cancelRequested) return -2
            val w = connection!!.bulkTransfer(ep, data, offset, len, 10_000)
            if (w >= 0) return w
            if (cancelRequested) return -2
            if (System.currentTimeMillis() > deadline) return -1
            Thread.sleep(50) // still back-pressured — keep WAITING, never resend
        }
    }

    /** Sends an HTTP request over the BIDI channel (EP 0x09). */
    fun sendBidi(data: ByteArray): Int {
        val ep = endpoint(EP_BIDI_OUT) ?: return -1
        return connection!!.bulkTransfer(ep, data, data.size, TIMEOUT_MS)
    }

    /** Reads one BIDI response chunk (EP 0x89). Returns bytes read or -1. */
    fun recvBidi(buf: ByteArray): Int {
        val ep = endpoint(EP_BIDI_IN) ?: return -1
        return connection!!.bulkTransfer(ep, buf, buf.size, TIMEOUT_MS)
    }

    /** Sends a raw control line to the print channel (PJL EOJ / RESET rescue). */
    fun sendRawPrint(data: ByteArray): Boolean {
        val ep = endpoint(EP_PRINT_OUT) ?: return false
        return connection!!.bulkTransfer(ep, data, data.size, TIMEOUT_MS) >= 0
    }

    /**
     * Resets the job state the way every driver job ends: @PJL EOJ (close
     * any half-open job), @PJL RESET, then UEL. Use after a failed job or
     * when the LCD is stuck on a dead job/"Cancelling".
     */
    fun resetJobState() {
        val seq = ("\u001B%-12345X@PJL EOJ\r\n" +
                "\u001B%-12345X@PJL RESET\r\n" +
                "\u001B%-12345X\r\n").toByteArray(Charsets.ISO_8859_1)
        sendRawPrint(seq)
    }

    /**
     * An OutputStream over the print channel: every write goes through
     * sendPrint (with its back-pressure retry), so PCL XL page blocks can
     * be streamed to the printer as they are generated.
     */
    fun printStream(): java.io.OutputStream = object : java.io.OutputStream() {
        override fun write(b: Int) =
            throw java.io.IOException("single-byte write not supported")

        override fun write(b: ByteArray, off: Int, len: Int) {
            var o = off
            var remaining = len
            while (remaining > 0) {
                val n = minOf(remaining, CHUNK)
                val w = sendPrint(b, o, n)
                if (w == -2) throw PrintCancelledException()
                if (w < 0) throw java.io.IOException("print write failed at offset $o")
                o += w
                remaining -= w
            }
        }
    }

    /** Reads whatever the scanner channel (EP 0x81) offers. */
    fun recvScan(buf: ByteArray): Int {
        val ep = endpoint(EP_SCAN_IN) ?: return -1
        return connection!!.bulkTransfer(ep, buf, buf.size, TIMEOUT_MS)
    }

    /**
     * Sends scan-command bytes (SOAP) on EP 0x03. The scan SOAP messages are
     * small (~600 B) and the printer accepts them in one bulk transfer, but
     * handle partial writes defensively anyway.
     */
    fun sendScanCmd(data: ByteArray, offset: Int = 0, len: Int = data.size): Int {
        val ep = endpoint(EP_SCAN_CMD_OUT) ?: return -1
        var o = offset
        var remaining = len
        while (remaining > 0) {
            val n = connection!!.bulkTransfer(ep, data, o, remaining, TIMEOUT_MS)
            if (n < 0) return if (o > offset) o - offset else -1
            o += n
            remaining -= n
        }
        return len
    }

    /** Reads scan response data (JPEG/acks) from EP 0x83. Returns bytes read or -1. */
    fun recvScanData(buf: ByteArray, timeoutMs: Int = TIMEOUT_MS): Int {
        val ep = endpoint(EP_SCAN_DATA_IN) ?: return -1
        return connection!!.bulkTransfer(ep, buf, buf.size, timeoutMs)
    }

    /**
     * Clears a HALTED bulk endpoint (USB CLEAR_FEATURE(ENDPOINT_HALT)).
     * After a dead job the printer can leave 0x03/0x83 stalled: every
     * transfer then fails instantly/with timeout until the halt is cleared
     * — exactly the "scan dies in a few seconds with no message" state.
     */
    fun clearHalt(address: Int): Boolean {
        // bmRequestType 0x02 = endpoint recipient, bRequest 0x01 = CLEAR_FEATURE
        val ok = connection!!.controlTransfer(
            0x02, 0x01, 0x0000, address, null, 0, 3000) >= 0
        return ok
    }

    /** Clears halts on all scan-channel endpoints (best-effort). */
    fun recoverScanEndpoints() {
        for (ep in intArrayOf(EP_SCAN_CMD_OUT, EP_SCAN_DATA_IN, EP_SCAN_IN,
                              EP_BIDI_OUT, EP_BIDI_IN)) {
            try { clearHalt(ep) } catch (_: Exception) {}
        }
    }

    /**
     * Last-resort recovery: USB-level device RESET + full re-open.
     * Re-enumerates the printer — clears a scan engine wedged so hard
     * (stuck Processing, dead job) that even CancelJob cannot reach it.
     * Returns true when the printer came back and all interfaces were
     * re-claimed.
     */
    fun resetAndReopen(): Boolean {
        // SET_CONFIGURATION (bmRequestType 0x00, bRequest 0x09, cfg 1):
        // re-initializes every endpoint + data toggle — the closest public-API
        // equivalent to a device reset.
        try {
            connection?.controlTransfer(0x00, 0x09, 0x0001, 0, null, 0, 5000)
        } catch (_: Exception) {}
        try { close() } catch (_: Exception) {}
        Thread.sleep(2500) // let the kernel re-enumerate
        val d = findPrinter() ?: return false
        return open(d)
    }

    fun close() {
        for (iface in claimed) connection?.releaseInterface(iface)
        claimed.clear()
        connection?.close()
        connection = null
        device = null
    }
}
