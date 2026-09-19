# Scan DPI upgrade — status (Sept 15, 2026, tablet shutting down)

## VERIFIED RESULTS (live on the printer)

| DPI | Result |
|---|---|
| 300 | ✅ baseline, always worked |
| 600 | ✅ **REAL** — engine confirmed 5100×7014 px (exactly 2×300 lattice), 3.0 MB JPEG, channel spread 1.1 (clean), ~56 s scan |
| 1200 | 🔧 job accepted by printer (10200×14028 geometry confirmed in response), but first RetrieveImage returned 552B "not ready" — old code threw, new code retries every 5 s like HP's bb_soapht.c. **NOT YET TESTED LIVE.** |
| 150/200 | ✅ resampled from native 300 (unchanged behavior) |

Evidence: printer's own ScannerConfiguration says PlatenOpticalResolution=1200, ADFOpticalResolution=300 (ADF can never do 600/1200 — enforced in code).

## Current state
- Latest build installed on phone AND saved to `D:\M175-OTG-Print.apk` (27 MB, timestamp Sept 15 ~20:50)
- Build + all unit tests pass
- 1200 dpi retry loop added in WscnScanClient.scanFlatbed (retrieve attempt log line: "printer not ready - retrying in 5s")
- 1200 dpi budget: 20 min deadline; 600: 6 min
- Big-image memory safety in ScanAutoLevels (sub-sampled decode >16 Mpx, JPEG q capped at 85 for huge files)

## NEXT SESSION TODO
1. Test 1200 dpi scan on glass (put page face-down, scan takes ~10-15 min)
2. If the printer refuses 1200 after ~2 min of retries → accept it as "firmware won't actually deliver it" and either drop the chip or auto-fallback to 600
3. Re-verify 600 + 300 still clean after the retry-loop change
4. AI-reviewer backlog items (PrintService, share-sheet, multi-page PDF) still open — see chat history

## Files touched
- app/src/main/java/com/ganesan/m175otg/MainActivity.kt (engineDpi selection, 5 chips)
- app/src/main/java/com/ganesan/m175otg/scan/WscnScanClient.kt (budgetMs, retrieve-retry, 30 MB cap)
- app/src/main/java/com/ganesan/m175otg/scan/LedmScanClient.kt (budgetMs)
- app/src/main/java/com/ganesan/m175otg/scan/ScanAutoLevels.kt (huge-image safety)
