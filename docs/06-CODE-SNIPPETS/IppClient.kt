package com.example.m175print.core.protocol

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

/**
 * Minimal IPP 1.1 client for the PC-bridge transport
 * (http://<pc>:8080/ipp/print). Also works against any network IPP printer.
 */
class IppClient(private val baseUrl: String) {

    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    /** Print a document. format: "application/pdf" or "application/octet-stream" */
    fun printJob(document: ByteArray, format: String,
                 jobName: String = "M175App"): Boolean {
        val body = buildIppPrintJob(document, format, jobName)
        val req = Request.Builder()
            .url(baseUrl.removeSuffix("/") + "/ipp/print")
            .post(body.toRequestBody("application/ipp".toMediaType()))
            .build()
        http.newCall(req).execute().use { resp ->
            return resp.isSuccessful && body.statusOk(resp.body.bytes())
        }
    }

    class IppBuilder {
        val buf = ByteArrayOutputStream()

        fun header(op: Short, reqId: Int = 1) {
            buf.write(byteArrayOf(1, 1))
            buf.write(byteArrayOf((op.toInt() shr 8).toByte(), op.toByte()))
            buf.write(byteArrayOf((reqId shr 24).toByte(), (reqId shr 16).toByte(),
                                  (reqId shr 8).toByte(), reqId.toByte()))
            buf.write(0x01) // operation-attributes-tag
        }

        fun attrString(tag: Byte, name: String, value: String) {
            buf.write(tag.toInt())
            val nb = name.toByteArray(); buf.write((nb.size shr 8).toByte()); buf.write(nb.size)
            buf.write(nb)
            val vb = value.toByteArray(); buf.write((vb.size shr 8).toByte()); buf.write(vb.size)
            buf.write(vb)
        }

        fun end(): ByteArray {
            buf.write(0x03) // end-of-attributes
            return buf.toByteArray()
        }
    }

    private fun buildIppPrintJob(doc: ByteArray, format: String,
                                 jobName: String): ByteArray {
        val b = IppBuilder()
        b.header(0x0002)  // Print-Job
        b.attrString(0x47, "attributes-charset", "utf-8")
        b.attrString(0x48, "attributes-natural-language", "en")
        b.attrString(0x45, "printer-uri", "ipp://printer/ipp/print")
        b.attrString(0x42, "job-name", jobName)
        b.attrString(0x49, "document-format", format)
        b.attrString(0x42, "requesting-user-name", "android")
        val head = b.end()
        return head + doc            // document data directly after attributes
    }

    private fun body.statusOk(resp: ByteArray): Boolean =
        resp.size >= 4 && ((resp[2].toInt() and 0xFF) shl 8 or
                           (resp[3].toInt() and 0xFF)) in 0x0000..0x00FF
}
