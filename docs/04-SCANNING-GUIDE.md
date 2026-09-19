# 04 — Scanning Guide

## Two paths to scan from the phone

### Path A — via the PC bridge (works TODAY, zero extra code)
The bridge already exposes **eSCL** (`http://<pc>:8080/eSCL`):
```
GET  /eSCL/ScannerCapabilities          → XML (resolutions, color modes)
POST /eSCL/ScanJobs  <ScanSettings>     → 201 + Location header
GET  /eSCL/ScanJobs/<id>/NextDocument   → image/jpeg bytes
DELETE /eSCL/ScanJobs/<id>              → cleanup
```
The bridge drives WIA on the PC; the phone just speaks standard eSCL.
**Sample XML to POST** (75/150/200/300/600 dpi supported):
```xml
<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05"
                   xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
 <scan:InputSource>Platen</scan:InputSource>
 <scan:ScanRegions><scan:ScanRegion>
   <scan:Height>3300</scan:Height><scan:Width>2550</scan:Width>
   <scan:XOffset>0</scan:XOffset><scan:YOffset>0</scan:YOffset>
 </scan:ScanRegion></scan:ScanRegions>
 <scan:DocumentFormat>image/jpeg</scan:DocumentFormat>
 <scan:XResolution>300</scan:XResolution>
 <scan:YResolution>300</scan:YResolution>
 <scan:ColorMode>RGB24</scan:ColorMode>
</scan:ScanSettings>
```
Kotlin: OkHttp POST → 201 → read `Location` header → GET it → JPEG bytes.

### Path B — USB OTG direct (advanced, no PC)
This model's scan interface is **USB still-image class (MI_00)**. Options:
1. **PTP/MTP route (easiest):** Android has `UsbManager` + PTP support;
   MFPs of this era often expose PTP on the scan interface. Try
   `UsbDeviceConnection` with class 6/1 — if `Still image` shows, use
   PTP `InitiateCapture`/`GetObject`.
2. **HP's own scan protocol (eSCL-over-USB):** newer HP firmware serves
   `GET /eSCL/ScannerCapabilities` **on the BIDI HTTP pipe**. Cheap to
   test: send `GET /eSCL/ScannerCapabilities HTTP/1.1\r\nHOST: localhost\r\n\r\n`
   to ep 0x89. If it 200s → your app speaks eSCL over USB identical to Path A.
3. **Vendor eSCL-over-WSD:** legacy; skip unless 1+2 fail.

### Resolutions / modes (VERIFIED matrix, 8/8 passed on this unit)
| DPI | Color | Typical A4 size |
|---|---|---|
| 75–150 | RGB24 | 0.1–0.5 MB jpeg |
| 200 | RGB24 / Grayscale8 | ~1 MB |
| 300 | RGB24 | ~2–3 MB (recommended docs) |
| 600 | RGB24 | ~8–12 MB (photos, slow) |

ColorModes: `RGB24`, `Grayscale8`, `BlackAndWhite1`.
Platen max region ≈ 2550×3508 px @300 dpi (A4).

> ⚠️ **REAL FINDING:** 150 dpi is NOT a native step — the engine silently
> quantizes it to 200 (verified: requested 150 → output 1700×2338 px =
> exactly 200 dpi). Offer users only **75 / 200 / 300 / 600** in your UI.
> 600 dpi RGB JPEG ≈ 7.3 MB per A4 page; allow ~8 s per page + transfer time.

### Document-feed UX (high-quality app feel)
- Auto-crop + deskew: use `mlkit document-scanner` (free, on-device) or
  OpenCV `findContours` on the bitmap.
- Multi-page: keep job id, `NextDocument` until 404/empty, then `DELETE`.
- Save: JPEG q90 (photos), PNG (BW), PDF (wrap pages via `PdfDocument`).
