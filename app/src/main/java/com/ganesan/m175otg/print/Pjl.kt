package com.ganesan.m175otg.print

/**
 * PJL job wrapper — byte-for-byte matching the command sequence captured
 * from the real printer (print-session-173348.pcap, EP 0x01):
 *
 *   ESC%-12345X
 *   @PJL JOB NAME="..."            <- job start
 *   @PJL SET STRINGCODESET=UTF8
 *   @PJL SET RESOLUTION=600        <- 300/600 verified
 *   @PJL SET GRAYSCALE=OFF|ON      <- the mono/color switch
 *   @PJL SET BITSPERPIXEL=8
 *   @PJL ENTER LANGUAGE=PCLXL      <- payload language
 *   ... raster payload ...
 *   ESC%-12345X @PJL EOJ           <- job stop (also what a cancel sends)
 */
object Pjl {

    fun jobHeader(
        jobName: String,
        resolution: Int = 600,
        grayscale: Boolean = false,
        copies: Int = 1,
        language: String = "PCLXL",
    ): ByteArray = buildString {
        append("\u001B%-12345X")
        append("@PJL JOB NAME=\"$jobName\"\r\n")
        append("@PJL SET STRINGCODESET=UTF8\r\n")
        append("@PJL SET RESOLUTION=$resolution\r\n")
        append("@PJL SET GRAYSCALE=${if (grayscale) "ON" else "OFF"}\r\n")
        append("@PJL SET BITSPERPIXEL=8\r\n")
        if (copies > 1) append("@PJL SET COPIES=$copies\r\n")
        append("@PJL ENTER LANGUAGE=$language\r\n")
    }.toByteArray(Charsets.ISO_8859_1)

    fun jobTrailer(jobName: String): ByteArray =
        ("\u001B%-12345X@PJL EOJ NAME=\"$jobName\"\r\n\u001B%-12345X\r\n")
            .toByteArray(Charsets.ISO_8859_1)
}
