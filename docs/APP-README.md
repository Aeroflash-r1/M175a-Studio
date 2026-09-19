# M175 OTG Print — Android app for HP LaserJet 100 MFP M175a (USB OTG)

**Phone → OTG cable → printer. No PC, no Wi-Fi, no Mopria, no HP app.**

Every protocol byte in this project was captured from the real printer
(VID `03F0` / PID `062A`) and disassembled with HP's own PCL XL
disassembler. Nothing is guessed — see
`../M175-Android-DevKit/09-OTG-PROTOCOL-VERIFIED.md`.

## What works

| Feature | Status |
|---|---|
| Print PDFs from phone (300 / 600 dpi) | ✅ code ready — protocol encoder machine-verified |
| Color or greyscale (`@PJL SET GRAYSCALE=OFF/ON`) | ✅ verified on wire |
| Manual duplex (evens-reversed → flip prompt → odds) | ✅ order physically verified; flip dialog built in |
| Toner % + status via HTTP-over-USB (LEDM) | ✅ endpoints captured; parser written |
| Cancel job (`@PJL EOJ`) | ✅ verified pattern |
| Test page with color chips + 600dpi lines | ✅ built in |
| Auto-launch when printer plugged in | ✅ manifest intent filter (HP 03F0) |
| **Scan over OTG** (flatbed, 75-600 dpi, color/gray/lineart) | ✅ **DECODED & IMPLEMENTED** — LEDM SOAP on EP 0x03/0x83, template byte-verified vs capture |

## Build it

1. Install **Android Studio** (set its SDK/AVD paths to D: to save C:).
2. **File → Open** → select `D:\M175-Android-App` (the Gradle project).
3. Let it sync (downloads Gradle 8.7 + dependencies automatically).
4. Enable **Developer options → USB debugging** on the phone, connect phone,
   press **Run ▶**. Or **Build → Build APK(s)** and sideload the APK.

## Test it

1. Connect phone → printer with a **USB OTG adapter**.
2. App auto-opens → allow the USB permission dialog.
3. Status line shows `CONNECTED (03F0:062A)`; toner percentages appear.
4. Tap **Print test page** — page comes out with CMY chips + fine lines.
5. Tap **Manual duplex** on a 2+ page PDF — follow the flip dialog exactly
   (whole stack flipped like a book page, blank sides up, same edge on top).

## Project layout

```
app/src/main/java/com/ganesan/m175otg/
  MainActivity.kt               UI: status, print, duplex wizard, scan, probes
  usb/UsbPrinterConnection.kt   endpoints 0x01 print / 0x09+0x89 BIDI / 0x03+0x83 scan
  usb/BidiHttpClient.kt         HTTP-over-USB + chunked decode + LEDM toner parser
  print/PclxlPage.kt            VERIFIED PCL XL encoder (JPEG page payloads)
  print/Pjl.kt                  PJL job wrapper
  print/PageRenderer.kt         PDF/image → JPEG pages at 300/600 dpi
  print/PrintTransmitter.kt     16KB chunked bulk transfers + progress
  print/ManualDuplexPlanner.kt  evens-reversed/odds-forward 2-pass engine
  scan/LedmScanClient.kt        scan over OTG: CreateScanJob → RetrieveImage → JPEG
  scan/ScanProbe.kt             scanner channel listener (diagnostics)
reference/                       captured streams (print + scan), real HTTP
                                 commands, HP pxldis.py
```

## Verify the encoder yourself (no phone needed)

```
cd D:\M175Bridge
venv\Scripts\python tools\validate_pclxl_encoder.py     # regenerates + checks
venv\Scripts\python reference\pxldis.py D:\M175-Android-App\reference\otg-test-stream.bin
```

The disassembly must show the operator sequence:
`BeginSession → OpenDataSource → BeginPage → ... → BeginImage → ReadImage →
EndImage → EndPage → CloseDataSource → EndSession` (it does).

## Honest limitations

- Scan saves to `Pictures/M175Scans` via direct file write — on Android 10+
  scoped storage may require adding `MediaStore` insertion on some devices
  (one small TODO if your phone blocks the direct path).
- Only A4 portrait is pre-wired; other sizes = change the `MediaSize`
  ubyte-array (`"A4"` → `"LETTER"` etc.) and DestinationSize.
- JPEG quality 90 balances quality/size; drop to 75 for faster transfers.

## Key protocol facts (all captured)

- Print = raw PJL+PCLXL on **EP 0x01**, no HTTP wrapping.
- Status/toner = plain HTTP GET on **EP 0x09 → 0x89** (chunked responses).
- The printer **accepts JPEG page images directly**
  (`ReadImage CompressMode=2`) — the app uses `Bitmap.compress(JPEG)`.
- PCL XL protocol **3**, `)` = little-endian binding; **value bytes precede
  their `attr_ubyte` selector** (two real bugs our validator caught).
- Toner: `GET /DevMgmt/ProductUsageDyn.xml` → live K/C/M/Y percentages.
- Scan = **LEDM/WS-Scan SOAP over USB**: `CreateScanJobRequest` → 202 +
  `<JobId>N` → `RetrieveImageRequest` → 200 + JPEG (EP 0x03 out, 0x83 in).
  Glass size in 1/1000 inch: 8500×11690. See
  `../M175-Android-DevKit/10-SCAN-OTG-VERIFIED.md`.
