package com.example.m175print.core.protocol

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/**
 * eSCL scan client for the bridge transport (http://<pc>:8080/eSCL).
 * Standard eSCL — also works with any network AirScan scanner.
 */
class EsclScanClient(baseUrl: String) {

    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS)   // 600dpi scans are slow
        .build()
    private val base = baseUrl.removeSuffix("/")

    fun capabilities(): String =
        http.newCall(Request.Builder().url("$base/eSCL/ScannerCapabilities").build())
            .execute().use { it.body.string() }

    /** dpi: 75/100/150/200/300/600 · color: RGB24/Grayscale8/BlackAndWhite1 */
    fun scanPlaten(dpi: Int = 300, color: String = "RGB24"): ByteArray {
        val regionW = if (dpi >= 600) 5100 else if (dpi >= 300) 2550 else 1275
        val regionH = if (dpi >= 600) 7016 else if (dpi >= 300) 3508 else 1754
        val settings = """
<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05"
 xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
 <scan:InputSource>Platen</scan:InputSource>
 <scan:ScanRegions><scan:ScanRegion>
  <scan:ContentRegionUnits>escl:ThreeHundredthsOfInches</scan:ContentRegionUnits>
  <scan:Width>$regionW</scan:Width><scan:Height>$regionH</scan:Height>
  <scan:XOffset>0</scan:XOffset><scan:YOffset>0</scan:YOffset>
 </scan:ScanRegion></scan:ScanRegions>
 <scan:DocumentFormat>image/jpeg</scan:DocumentFormat>
 <scan:XResolution>$dpi</scan:XResolution>
 <scan:YResolution>$dpi</scan:YResolution>
 <scan:ColorMode>$color</scan:ColorMode>
</scan:ScanSettings>"""
        val create = Request.Builder()
            .url("$base/eSCL/ScanJobs")
            .post(settings.trimIndent().toRequestBody("text/xml".toMediaType()))
            .build()
        http.newCall(create).execute().use { resp ->
            check(resp.code == 201) { "Scan job refused: ${resp.code}" }
            val loc = resp.header("Location")
                ?: throw IllegalStateException("no job location")
            val docUrl = base + (if (loc.startsWith("/")) loc else "/" + loc)
                .replace(Regex("/\$"), "") + "/NextDocument"

            // poll: job may take a few seconds (glass scan)
            repeat(60) {
                http.newCall(Request.Builder().url(docUrl).build()).execute().use { g ->
                    when {
                        g.code == 200 -> return g.body.bytes()
                        g.code == 404 || g.code == 503 -> Thread.sleep(1000)
                        else -> Thread.sleep(500)
                    }
                }
            }
            error("scanner did not deliver image in time")
        }
    }

    fun cleanup(jobPath: String) {
        http.newCall(Request.Builder().url(base + jobPath).delete().build())
            .execute().close()
    }
}
