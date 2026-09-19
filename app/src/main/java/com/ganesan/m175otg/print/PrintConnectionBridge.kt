package com.ganesan.m175otg.print

import android.content.Context
import com.ganesan.m175otg.usb.UsbPrinterConnection
import java.util.Collections

/**
 * Hands the system PrintService a UsbPrinterConnection WITHOUT fighting
 * the app for the USB interface claim.
 *
 * Android allows only ONE UsbDeviceConnection per interface claim. The
 * MainActivity normally holds the claim for its whole lifetime, so a
 * service-side claimInterface() either fails (old behaviour: "printing
 * from other apps never worked") or steals the claim and wedges the app.
 *
 * Policy:
 *  - acquire(): if the app's registered connection is already OPEN, it is
 *    handed over as SHARED (the app keeps it after the job). Otherwise the
 *    bridge creates an OWNED connection for the service (app is dead —
 *    safe to claim and close later).
 *  - release(conn): closes OWNED connections; SHARED ones are left intact.
 */
object PrintConnectionBridge {

    @Volatile private var appConnection: UsbPrinterConnection? = null
    private val owned = Collections.synchronizedSet(HashSet<UsbPrinterConnection>())

    /** The app calls this once when its connection is created. */
    fun registerAppConnection(conn: UsbPrinterConnection) {
        appConnection = conn
    }

    /** The app calls this when its connection closes. */
    fun unregisterAppConnection(conn: UsbPrinterConnection) {
        if (appConnection === conn) appConnection = null
        owned.remove(conn)
    }

    /**
     * Service side: get a usable connection. [open] it with the device
     * afterwards; the bridge only decides ownership.
     */
    fun acquire(context: Context): UsbPrinterConnection {
        appConnection?.let { existing ->
            if (existing.isOpen) return existing
        }
        val fresh = UsbPrinterConnection(context.applicationContext)
        owned.add(fresh)
        return fresh
    }

    /** Service side: end of job — close only connections the bridge created. */
    fun release(conn: UsbPrinterConnection?) {
        conn ?: return
        if (owned.remove(conn)) {
            try { conn.close() } catch (_: Exception) {}
        }
    }
}
