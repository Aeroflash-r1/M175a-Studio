package com.ganesan.m175otg.print

import org.junit.Test
import java.io.File

/**
 * Verification tool (not an assertion suite).
 *
 * Wraps pre-made page JPEGs (one per paper size, at that paper's exact
 * pixel dimensions) in the app's REAL PCL XL stream and writes them to
 * .prn files, so the exact bytes the phone would send can be RAW-printed
 * to the physical printer and checked.
 */
class DumpPaperStreamsTest {

    @Test
    fun dump_streams_for_hardware_check() {
        // Relative defaults resolve to <app-module>/build-tmp — same place as
        // the old absolute D:\ path on Windows, but portable to Linux/CI.
        val dir = File(System.getenv("M175_DUMP_DIR") ?: "build-tmp/prn")
        val jpegDir = File(System.getenv("M175_JPEG_DIR") ?: "build-tmp/jpeg")
        if (!jpegDir.isDirectory) {
            println("SKIP all: ${jpegDir.absolutePath} missing (no page JPEGs)")
            return
        }
        dir.mkdirs()
        val dpi = 300

        for (paper in listOf(Paper.A4, Paper.LETTER, Paper.A5)) {
            val jpegFile = File(jpegDir, "${paper.name}.jpg")
            if (!jpegFile.isFile) {
                println("SKIP ${paper.name}: ${jpegFile.absolutePath} missing")
                continue
            }
            val jpeg = jpegFile.readBytes()
            val (w, h) = paper.pagePx(dpi, landscape = false)
            val stream = PclxlPage.buildStream(
                listOf(jpeg), w, h,
                dpi = dpi, grayscale = false,
                jobName = "PAPER-${paper.name}",
                landscape = false, paper = paper,
            )
            val f = File(dir, "${paper.name}.prn")
            f.writeBytes(stream)
            println("WROTE ${f.absolutePath} ${stream.size} bytes " +
                    "(jpeg ${jpeg.size}, ${w}x${h}, media=${paper.pclName})")
        }
    }
}
