# 💎 Extra Features — Discovered from the live printer's data (Sept 2026)

Mined from the captured BIDI responses (`ProductUsageDyn.xml`,
`ProductConfigDyn.xml`, `ProductStatusDyn.xml`) that the Windows driver
exchanged with THIS printer. All values below are real readings from
your unit (Serial `CND8F6TKPP`). Evidence:
`M175Bridge/devkit-reference/extra-features/`.

## 1. Full consumable intelligence (beyond % levels)

`GET /DevMgmt/ProductUsageDyn.xml` over EP 0x09/0x89 returns per-supply:

| Field (dd: namespace) | Your printer's live value |
|---|---|
| `MarkerColor` | Black / Cyan / Magenta / Yellow |
| `ConsumableTypeEnum` | **`toner` or `imageDrum`** — tells supplies apart! |
| `ConsumableRawPercentageLevelRemaining` | K80 C8 M9 Y10, drum 81 |
| `EstimatedPagesRemaining` | **K800 C50 M100 Y100, drum 20000** |
| `TotalImpressions` (per cartridge) | K202, C1163, M1176, Y1170 |
| `PreviousCartridgeData` | previous black cart did 763 pages |
| `UsageByMedia` | pages per paper size (a4_or_letter, b4_or_legal, custom) |
| Coverage histogram | `GreaterThanZeroToTwoPercentSaturatedImpressions` etc. |

App impact: the toner card can now show **"Cyan 8% (~50 pages left)"**
with a buy-now warning, plus drum health — data HP's own app barely shows.

## 2. Lifetime usage counters

| Counter | Value |
|---|---|
| `TotalImpressions` | **4,315 pages printed lifetime** |
| `ColorImpressions` | 2,411 |
| `MonochromeImpressions` | 1,904 |
| `FormatterColorImpressionCount` | 202 |
| Per-cart A4-equivalents + media-size breakdown | available |

App impact: a **"Printer lifetime stats"** screen — pages printed, color
vs mono split. Nothing extra to implement: one more XML GET.

## 3. Device identity

| Field | Value |
|---|---|
| `SerialNumber` | CND8F6TKPP |
| `UUID` | 434E4438-4636-544B-5050-000000000000 |
| Languages | en, fr, de, it (+ more in ProductConfigDyn) |

App impact: About screen can show serial/UUID read live over the cable.

## 4. Status model (verified)

`ProductStatusDyn.xml` gives structured status:
`<StatusCategory>processing|idle|...</StatusCategory>` + localized
`LocString` ("Printing document"). An app can drive a live status chip:
**Ready / Printing / Paper out / Cover open / Error** — all from this one
endpoint (categories map 1:1 to alert states).

## 5. What the M175a does NOT have (confirmed absences)

- **No ADF**: the M175a flatbed-only; `GetScannerElements` traffic shows
  `Platen`/`Feeder`/`Duplex` keywords only in the generic template, and
  WIA reports no document feeder. Scan apps must use the glass, one page
  per pass (multi-page = app-side stitching, like our duplex planner).
- **No auto-duplexer** (manual 2-pass only — already implemented).
- **No network stack** on this "basic" unit — USB-only, which is exactly
  why the OTG app is the right approach.

## 6. Feature ideas now trivially enabled (endpoints already decoded)

1. **Cartridge shop advisor** — pages-left + coverage histogram → smart
   "buy Cyan now" notifications.
2. **Page counter odometer** — lifetime + per-cartridge history.
3. **Print-cost estimator** — coverage histogram × toner price.
4. **Multi-page scan → single PDF** — repeat `RetrieveImageRequest`
   per page (JobId increments), stitch with Android's PdfDocument.
5. **Idle vs printing detection** — poll `StatusCategory` (2-byte GET) for
   a live status chip without any push channel.
