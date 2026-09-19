package com.example.m175print.core.usb

import android.content.Context
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager

/**
 * Finds the HP M175a and classifies its bulk endpoints.
 * VID 03F0 (HP), PID 062A on this machine, but match loosely:
 * vendor HP + composite with printer + bidi interfaces.
 */
data class PrinterEndpoints(
    val device: UsbDevice,
    val bulkOutPrint: Int,   // 0x09 on this unit
    val bulkInStatus: Int,   // 0x89 on this unit (BIDI / LEDM HTTP)
    val bulkInScan: Int      // 0x81 on this unit (still image)
)

class UsbPrinterFinder(private val ctx: Context) {

    fun find(): PrinterEndpoints? {
        val usb = ctx.getSystemService(Context.USB_SERVICE) as UsbManager
        for (dev in usb.deviceList.values) {
            if (dev.vendorId != 0x03F0) continue
            var outPrint = -1; var inStatus = -1; var inScan = -1
            for (i in 0 until dev.interfaceCount) {
                val iface = dev.getInterface(i)
                when (iface.interfaceClass) {
                    7 -> {  // printer
                        for (e in 0 until iface.endpointCount) {
                            val ep = iface.getEndpoint(e)
                            if (ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK &&
                                ep.direction == UsbConstants.USB_DIR_OUT)
                                outPrint = ep.address
                        }
                    }
                    6 -> {  // still image (scan)
                        for (e in 0 until iface.endpointCount) {
                            val ep = iface.getEndpoint(e)
                            if (ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK &&
                                ep.direction == UsbConstants.USB_DIR_IN)
                                inScan = ep.address
                        }
                    }
                    255 -> {  // vendor (BIDI HTTP)
                        for (e in 0 until iface.endpointCount) {
                            val ep = iface.getEndpoint(e)
                            if (ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK &&
                                ep.direction == UsbConstants.USB_DIR_IN)
                                inStatus = ep.address
                        }
                    }
                }
            }
            if (outPrint != -1) {
                if (inStatus == -1) inStatus = 0x89
                if (inScan == -1) inScan = 0x81
                return PrinterEndpoints(dev, outPrint, inStatus, inScan)
            }
        }
        return null
    }

    fun requestPermission(dev: UsbDevice) {
        val usb = ctx.getSystemService(Context.USB_SERVICE) as UsbManager
        val pi = android.app.PendingIntent.getBroadcast(
            ctx, 0, android.content.Intent("com.example.m175print.USB_PERMISSION")
                .setPackage(ctx.packageName),
            android.app.PendingIntent.FLAG_MUTABLE)
        usb.requestPermission(dev, pi)
    }
}
