# Advanced print layout tier (Sept 15, 2026)

All implemented, unit-tested where math is involved, installed on the phone,
saved to D:\M175-OTG-Print.apk.

## Page selection & ordering
- **Range syntax** "Pages" field: `1-3, 5, 8-10`, open ranges (`5-`, `-3`),
  duplicates collapse, garbage returns empty with a friendly toast.
  (PageLayout.parseRange + 7 test assertions)
- **Reverse order** chip — last page first (face-up stacking fix).
- **Skip blank pages** — each planned page probed at 72 dpi, <1% dark
  pixels = dropped. "All pages blank" toast when nothing remains.
- **Odd only / Even only** chips — standalone, for re-feeding backs.

## N-up
- **2-up**: two pages side-by-side per sheet, printed LANDSCAPE
  (PclxlPage.writePage gained `landscape` — orientation=1 + swapped
  destination units; same verified op sequence otherwise).
- **4-up**: 2x2 grid on one portrait sheet (TL, TR, BL, BR).

## Booklet
- PageLayout.bookletSheets implements the exact imposition math:
  sheet i front [N-(i-1)*2 | (i-1)*2+1], back [(i-1)*2+2 | N-(i-1)*2-1],
  pages padded to a multiple of 4 with blanks. VERIFIED by unit test
  against the analyser's own 8-page example.
- 2-up landscape sheets composed on the fly; reuses the EXACT manual-duplex
  two-pass flow (pass 1 fronts reversed, flip prompt on printer LCD +
  phone dialog, pass 2 backs forward — same physical stacking behavior the
  user already validated with duplex). Fold + staple by hand.
- Booklet needs 4+ pages; guarded.

## Note on pairing order (important for future changes)
Manual duplex VERIFIED physical behavior: pass 1 = evens REVERSED,
pass 2 = odds FORWARD. Generalized: one pass reversed, other forward.
Booklet follows the same structure (fronts reversed, backs forward) so the
flip-and-stack behavior matches what was physically validated on 2026-09-14.
If duplex ever changes, booklet must mirror it.

## NOT yet done (scan-side + job-level from the same list)
- Page picker after ADF scan (thumbnail grid, exclude/reorder)
- "Insert scan here" (replace one page of a batch)
- Combine multiple files into one job
- Named settings presets / Settings tab

## Test coverage added
- PageLayoutTest: 5 tests (booklet 8-page exact layout, padding/blank
  placement, page-appearance invariant 4..17 pages, range parser,
  parity filter). All green.
