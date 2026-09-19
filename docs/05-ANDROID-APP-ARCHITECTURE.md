# 05 — Android App Architecture (high-quality print app)

## Stack (all free)
- **Kotlin** + Jetpack Compose (Material 3)
- `UsbManager` (USB OTG host) + OkHttp (bridge/Wi-Fi path)
- PdfRenderer, PdfDocument (render & output)
- DataStore (settings), Coil (preview images)
- Optional: ML Kit document scanner (on-device crop/deskew)

## Modules
```
app/
 core-usb/      UsbSession, endpoint discovery, OTG permissions
 core-protocol/ Pcl5Writer, Pcl6Writer, IppClient, LedmClient, EsclClient
 core-render/   PdfToBitmaps, ImageScaler, DuplexPlanner
 feature-print/ screens: doc picker, preview, dpi/quality, duplex wizard
 feature-scan/  screens: scan, crop, multipage, export PDF
 feature-status/toner gauge UI, usage counters, alerts
```

## Screens (typical high-quality app)
1. **Home** — printer card (photo M175a, connection state: USB/Wi-Fi/both),
   toner gauges (K/C/M/Y), quick actions: Print / Scan / Supplies.
2. **Print sheet** — doc picker → page thumbnails → copies, color mode,
   **DPI (300 Fast / 600 Native / 1200 Photo)**, paper size (A4…),
   **Manual duplex wizard** (3-step with diagrams), range picker.
3. **Scan sheet** — dpi + color + format, live preview, multi-page tray,
   auto-crop toggle, export: PDF/JPEG/PNG → share sheet.
4. **Supplies** — % bars from LEDM, install dates, page counters,
   "buy" links (CE310A–CE313A).
5. **Settings** — duplex offset calibration, default dpi, dark mode.

## Connection manager (hybrid)
```kotlin
sealed interface Transport { UsbOtg, BridgeHttp(baseUrl), None }
class ConnectionManager {
  // 1. USB OTG attached? → UsbOtg
  // 2. mDNS browse _ipp._tcp / saved bridge URL? → BridgeHttp
  // 3. else None → onboarding screen
}
```
Both transports implement:
```kotlin
interface PrinterTransport {
  suspend fun capabilities(): PrinterCaps
  suspend fun print(job: PrintJob): JobHandle
  suspend fun toner(): TonerLevels
  suspend fun scan(settings: ScanSettings): List<Bitmap>
}
```
So features never care which transport is active.

## Manual duplex engine (feature-print)
```kotlin
class DuplexPlanner(total: Int) {
  val front = (1..total).filter { it % 2 == 1 }          // odd pages
  val back  = (2..total step 2).reversed()               // even, reversed
  // UX: print back-side stack → dialog w/ diagram:
  // "Take stack, BLANK SIDE UP, short edge first, reinsert tray 1" → print front
}
```
Calibration knob: `backOffsetXMm`, `backOffsetYMm`, `flipLongEdge/ShortEdge`
stored in DataStore.

## Toner gauges (feature-status) — data from LEDM
```kotlin
data class TonerLevels(val black: Int, val cyan: Int,
                       val magenta: Int, val yellow: Int,
                       val drum: Int? = null)
```
UI: 4 vertical pills w/ % + color, alert <15%, disabled grayscale option
when any color = 0 (offer "print in mono anyway").

## Notifications
- Foreground service while job runs (progress + cancel action)
- "Toner low" channel when <15% on any supply
