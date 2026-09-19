# 03 — Printing Guide (render → wire)

## The pipeline your app needs
```
User picks document/photo
   ↓
[Render]  PDF/Office/RAW → bitmaps at chosen DPI (600 native, 300 fast)
   ↓
[Raster]  Android Canvas/Bitmap → mono or CMYK-ish rows
   ↓
[PCL wrap] seed rows into PCL6 raster stream (or PJL+PCL5 for mono)
   ↓
[Transport] USB OTG bulk OUT  (or HTTP POST /ipp/print via bridge)
   ↓
[Track]   LEDM JobStatusDyn.xml / USB BIDI for progress + errors
```

## DPI — what this printer really supports
| DPI | Use | Notes |
|---|---|---|
| 300×300 | Draft/fast text | smallest raster, fastest phone→printer transfer |
| 600×600 | **Native engine** — best quality | default for text+graphics |
| 1200×1200 effective | photos | driver interpolates 600→1200; heavy: A4@1200 CMYK ≈ 100 MB/page |

**A4 @ 600 dpi math:** 4961 × 7016 px = 34.8 Mpx mono = 4.35 MB/page raw;
with RLE (PCL6) typically 0.3–1.5 MB. Photos stay big — chunk your USB
writes (16–32 KB per bulkTransfer is the sweet spot on Android).

## Rendering with Android APIs
```kotlin
// PDF (local or via PdfRenderer — no internet needed)
val fd = ParcelFileDescriptor.open(pdfFile, MODE_READ_ONLY)
val renderer = PdfRenderer(fd)
for (page in renderer) {
    val bitmap = Bitmap.createBitmap(
        (page.width / 72f * dpi).toInt(),
        (page.height / 72f * dpi).toInt(), ARGB_8888)
    page.render(Canvas(bitmap), null, null, RENDER_MODE_FOR_PRINT)
    // → feed to PCL raster writer (06-CODE-SNIPPETS/PclRasterWriter.kt)
}
```
- Images: decode with `BitmapFactory`, scale to target px at print DPI.
- Office docs: render via `androidx.print` helpers or convert to PDF first.

## Color strategy
The engine is laser CMYK but accepts raster as RGB (it converts internally).
Keep bitmaps in RGB_888; force `MONO` (1-bit, G4-ish RLE) for text jobs —
6× smaller and crisp.

## PCL6 (PCL XL) raster — the language this printer eats natively
Minimal stream that prints one bitmap page:
```
=UEL @PJL ENTER LANGUAGE=PCLXL          ← PJL switch
) HP-PCL XL;3;Comment...               ← header
[protocol: binary 2-byte]
BeginPage, cursor 0,0
SetSourceRenderingIntent, ColorDepth...
ReadImage → compressed rows (RLE)
EndPage, EndSession
```
**Shortcut:** a *PCL5* mono path is far easier to hand-write
(`*t600R *r0F *b#W` row protocol, guide 06) and is perfect for documents.
Do PCL5 mono v1 → add PCL6 color v2.

## ✅ VERIFIED job control — exact commands this printer accepts
(captured from its own USB wire — full evidence in 07-TEST-DATA)
```
ESC%-12345X                      job/language separator (UEL)
@PJL JOB NAME="MyJob"            START
@PJL SET RESOLUTION=600          DPI (300 or 600 verified)
@PJL SET GRAYSCALE=OFF           OFF=color, ON=grayscale
@PJL SET BITSPERPIXEL=8
@PJL ENTER LANGUAGE=PCLXL        raster data follows (PCL XL)
@PJL EOJ                         END
ESC%-12345X
```
Cancel = send `@PJL EOJ` + UEL and stop writing data.
These PJL vars were accepted and honored by this firmware — verified by
capturing a real Windows-driver job and replaying structure.

## Manual duplex (no auto-duplexer in this model!) — see 06 snippet
App flow: render all pages → split odd/even → print evens reversed
→ prompt "flip & reinsert" → print odds. Calibration: after page 1 the
engine may skew ±2 mm; store a per-paper offset in app settings.

## Job tracking
After submit, poll (1 s): `GET /DevMgmt/JobStatusDyn.xml` (bridge/USB LEDM).
States: Processing → Printing → Completed / Aborted (with reason).
Parse `PrinterStatusGroup`/`EventCode` for out-of-paper/jam — map to
user-friendly strings in your UI.

## Cancel
USB: send PJL `@PJL EOJ` / flush bulk OUT + `UsbRequest.close()`.
Bridge: `DELETE` the IPP job, or kill the spool entry server-side.
