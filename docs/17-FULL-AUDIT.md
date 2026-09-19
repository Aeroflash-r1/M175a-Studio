# 17 — Full App Audit (16 Sep 2026, final build)

Every item below was verified against a **clean build** of `D:\M175-Android-App`
running on the real phone + real HP M175a (VID 03F0 / PID 062A).
Shipped APK: `D:\M175-OTG-Print.apk`.

## 1. Root cause of "print error: unsupported pixel" — FIXED

**Symptom:** every PDF print failed instantly with a toast
`Print error: Unsupported pixel format`.

**Evidence (logcat, real device):**
```
E M175: java.lang.IllegalArgumentException: Unsupported pixel format
E M175:   at android.graphics.pdf.PdfRenderer$Page.render(PdfRenderer.java:397)
E M175:   at PageRenderer.renderPageBitmap(PageRenderer.kt:172)
```

**Cause:** `PdfRenderer.Page.render()` accepts **only ARGB_8888** bitmaps.
The RAM optimization had switched the render target to `RGB_565`, so the
render threw before a single byte reached the printer. The A4 test page
never hit this because it bypasses PdfRenderer entirely.

**Fix:** both PdfRenderer render targets are ARGB_8888 again
(`PageRenderer.renderPageBitmap`, `M175PrintService.renderOne`).
RGB_565 is still used everywhere it is safe (Canvas draw targets,
JPEG grayscale copies, scan decode) — those are not PdfRenderer targets.

**Proof (real prints, `result=Ok`, no PCL XL error):**
| Job | Settings | Result |
|---|---|---|
| scanned page (1p) | 600 dpi, colour | Ok 1,150,764 B |
| scanned page (1p) | 300 dpi, greyscale | Ok 250,050 B |
| scanned pages (3p) | 300 dpi, greyscale | Ok 962,734 B (5.6 s + 5.0 s per page) |

## 2. Print-start lag — FIXED

The ranged/streaming path re-opened the whole PDF for **every page**
(`renderSinglePage` per page). Now one `PageSession` (single
PdfRenderer) serves the entire job, with a placement fast-path so
untouched settings cost nothing extra. Skip-blank probing also uses a
single open renderer now (no per-page reopen, no JPEG round-trip).

## 3. Share-sheet / "Open with" print race — FIXED

A VIEW/SEND intent arriving before the async USB connect finished was
silently dropped (`checkReady()` bailed). Now the URI is queued
(`pendingPrintUri`) and printed the moment the connection opens.
Verified live: intent → connect → print → `result=Ok`.

## 4. Settings persistence — ADDED

`printDpi` and `grayscale` were runtime-only state that reset on every
restart. Both now persist (keys `printDpi`, `printGray`) alongside the
existing page-layout prefs. Verified: prefs written and honoured
(`dpi=300 gray=true` read back on next launch).

## 5. Error diagnosability — FIXED

All print catch blocks now log the exception class, message and full
stack to logcat (tag `M175`) before showing the toast. That is exactly
how the pixel-format root cause above was caught.

## 6. Code hygiene

- `clean assembleDebug` + `testDebugUnitTest`: **16/16 tests pass, 0 failures**
  (booklet imposition math, chunked framing, DIME framing)
- No TODO/FIXME/HACK left in `app/src/main`
- Dead helpers removed (`renderPdfPage`, `renderSinglePage`)
- Both PdfRenderer render sites audited as ARGB_8888

## 7. Live functional sweep (this build, this device)

| Area | Check | Result |
|---|---|---|
| Print | test page, scanned PDFs, colour + greyscale, 300/600 dpi | ✅ printed, `Ok` |
| Print | page-range / copies / reverse / parity / 2-up / 4-up / booklet | ✅ unit-tested math; range path verified |
| Print | page layout (fit / orientation / margins / 3×3 position) | ✅ persists; grid now visibly outlined |
| Scan | glass scan 300 dpi colour | ✅ 863,742 B, 2550×3507, `spread1 flat0` |
| Scan | saved file integrity | ✅ mean RGB 210/209/208 (matches app's own reading) |
| Scan | save location | ✅ `Pictures/M175Scans/*.jpg`, `Download/M175Scans/*.pdf` |
| Printer | live toner/drum/pages/lifetime + low-toner alert | ✅ live values |
| System | PrintService registered | ✅ `com.ganesan.m175otg.print.M175PrintService` |
| System | notification channels | ✅ `m175_alerts`, `m175_events` |
| Stability | crashes during the whole session | ✅ none |

## 8. Still needs YOUR hands on the printer (can't be automated)

These are interaction-dependent, not code-verified:

1. **Manual duplex / booklet** — needs a physical sheet flip at the prompt.
   Code path is unchanged from your last verified build; the flip prompt
   (phone dialog + printer LCD) is wired.
2. **ADF multi-page → single PDF** — needs pages in the feeder.
3. **Skip blank pages on a document that actually has blank pages.**
4. **Landscape page-layout printing** (2-up landscape geometry was never
   put on paper — 4-up is the safer sheet mode to test first).

Report any of these failing with the toast text and I can trace it from
logcat immediately now that every print failure is logged.
