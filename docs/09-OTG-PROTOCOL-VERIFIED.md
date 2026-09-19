# 🔌 M175a OTG Protocol — VERIFIED from the real wire (Sept 2026)

Every byte below was either captured from your printer (VID 03F0 / PID 062A)
or disassembled from the captured stream with HP's own PCL XL disassembler
(`pxldis.py` from ghostscript). Nothing is guessed.

---

## 1. USB endpoint map (captured)

| Endpoint | Direction | Use |
|---|---|---|
| `0x01` | OUT | **Print** — raw PJL + PCL XL stream (NO HTTP wrapping) |
| `0x09` | OUT | **HTTP requests** — HP LEDM/BIDI channel |
| `0x89` | IN | **HTTP responses** — toner/status XML comes back here |
| `0x81` | IN | Scanner channel (binary; scan work is ongoing) |

Interfaces: 3 (scanner MI_00, printer MI_01, BIDI MI_02). An Android app
claims all of them.

## 2. Print job = PJL wrapper + PCL XL (protocol 3, little-endian `)` binding)

Captured start of the stream (EP 0x01):

```
ESC%-12345X
@PJL SET RET=ON
@PJL JOB NAME="CAPTURE-JOB"
@PJL SET STRINGCODESET=UTF8
@PJL SET JOBATTR="..."          (accounting, optional)
@PJL SET RESOLUTION=600
@PJL SET GRAYSCALE=OFF          <- ON = greyscale, OFF = color (verified both)
@PJL SET BITSPERPIXEL=8
@PJL ENTER LANGUAGE=PCLXL
```

## 3. The PCL XL page recipe (disassembled, operator-exact)

Header text line (note the `)` binding = little-endian!):

```
) HP-PCL XL;3;0;Comment Copyright(c) 1999 Microsoft Corporation
```

Then binary operators, in this order (attribute values come BEFORE the
`attr_ubyte` selector, then the operator byte):

| # | Attributes sent | Operator |
|---|---|---|
| 1 | `uint16_xy 600 600 UnitsPerMeasure`, `ubyte 0 Measure (inch)`, `ubyte 3 ErrorReport` | `BeginSession 0x41` |
| 2 | `ubyte 0 SourceType`, `ubyte 1 DataOrg (LowByteFirst)` | `OpenDataSource 0x48` |
| 3 | `ubyte 1 MediaSource (AutoSelect)`, `ubyte 0 Orientation`, `ubyte_array "A4" MediaSize` | `BeginPage 0x43` |
| 4 | `sint16_xy 100 100 PageOrigin` | `SetPageOrigin 0x75` |
| 5-7 | `ubyte 0/1/2 TextObjects|RasterObjects|VectorObjects` | `SetNeutralAxis 0x7E` ×3 |
| 8 | `ubyte 2 AllObjectTypes` | `SetHalftoneMethod 0x6D` |
| 9 | `ubyte 1 AllObjectTypes` | `SetAdaptiveHalftoning 0x94` |
| 10 | `ubyte 2 AllObjectTypes` | `SetColorTrapping 0x92` |
| 11 | `ubyte 1 ColorTreatment (eScreenMatch)` | `SetColorTreatment 0x58` |
| 12 | `real32_xy 1.0 1.0 PageScale` | `SetPageScale 0x77` |
| 13 | `ubyte 2 ColorSpace (eRGB)` — **`ubyte 1` = eGray for mono** | `SetColorSpace 0x6A` |
| 14-15 | `ubyte 0 TxMode (eOpaque)` | `SetPatternTxMode 0x78`, `SetSourceTxMode 0x7C` |
| 16 | `ubyte 204 ROP3` | `SetROP 0x7B` |
| 17 | — | `PushGS 0x61` |
| 18 | — | `SetClipToPage 0x69` |
| 19-23 | pen/brush colors, tx modes | `SetCursor 0x6B` + paint setup |
| 24 | `ubyte 0 ColorMapping (eDirectPixel)`, `ubyte 2 ColorDepth (e8Bit)`, `uint16 SourceWidth`, `uint16 SourceHeight`, `uint16_xy DestinationSize` | `BeginImage 0xB0` |
| 25 | `uint16 0 StartLine`, `uint16 BlockHeight`, `ubyte 2 CompressMode (eJPEG!)` | `ReadImage 0xB1` |
| 26 | `uint32 length` + raw **JPEG bytes** (`FF D8 ...`) | `embedded_data 0xFA` |
| 27 | — | `EndImage 0xB2` |
| 28 | — | `EndPage 0x44` |
| 29 | — | `PopGS 0x60`, `EndSession 0x42` |

Trailer:
```
ESC%-12345X@PJL EOJ NAME="..."
ESC%-12345X
```

## 4. 🔑 The killer simplification (verified!)

**CompressMode = 2 means the printer accepts plain JPEG data as the image
payload.** Windows renders at 600 dpi, JPEG-compresses the bitmap, and ships
it. Your Android app does exactly:

```kotlin
val bmp = renderPage(...)                 // Bitmap at chosen DPI
val baos = ByteArrayOutputStream()
bmp.compress(Bitmap.CompressFormat.JPEG, 90, baos)   // Android built-in!
val jpeg = baos.toByteArray()
// -> BeginImage(SourceWidth=bmp.width, SourceHeight=bmp.height,
//               DestinationSize=(4760,6735), ColorSpace=eRGB)
// -> ReadImage(CompressMode=2) + embedded_data(jpeg)
```

No raster row encoding, no delta compression, no palette code needed.
The printer decompresses internally.

Verified numbers from the capture: 600 dpi A4 →
`SourceWidth=2380, SourceHeight=3368, DestinationSize=(4760,6735)`
(DestinationSize is in UnitsPerMeasure units = 600dpi here, and equals the
printable area 7.93×11.22in — A4 minus the hardware margins).

⚠️ **Endianness**: the header line `) HP-PCL XL;3;0` declares the `)`
binding = **little-endian** for all multi-byte values (600 = `58 02` on the
wire — verified by disassembling the capture). Image data order is declared
separately via `DataOrg = eBinaryLowByteFirst`.

## 5. Toner / status over the BIDI channel (captured HTTP)

Plain HTTP/1.1 requests to EP 0x09, responses from EP 0x89:

```
GET /DevMgmt/ProductUsageDyn.xml   -> consumable % levels (verified live)
GET /DevMgmt/ProductStatusDyn.xml  -> LCD status string ("Printing document")
GET /DevMgmt/ProductConfigDyn.xml
GET /cdm/system/v1/identity        -> serial/model JSON
POST /ipp/print                    -> printer also accepts IPP over USB!
```

Response is chunked HTTP — dechunk before XML parsing (the app's
`BidiHttpClient` does this).

## 6. Cancelling

Send the PJL trailer mid-job on EP 0x01:
`ESC%-12345X@PJL EOJ` — the printer aborts the current page (same pattern
Windows uses to stop a job). Then optionally `@PJL RESET`.

## 7. Reference files on this PC

- `D:\M175Bridge\devkit-reference\otg-print-stream.bin` — 131KB known-good job
- `D:\M175Bridge\devkit-reference\otg-bidi-http-requests.txt` — all 11 real HTTP commands
- `D:\M175Bridge\captures\print-session-173348.pcap` — full wire capture (Wireshark)
- `D:\M175Bridge\tmp\pxldis.py` — HP's disassembler (rerun anytime)
