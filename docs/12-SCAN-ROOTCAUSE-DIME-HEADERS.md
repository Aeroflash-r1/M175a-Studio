# 12 — Scan corruption ROOT CAUSE (solved, 15 Sept 2026)

**Symptom:** scans came back with a readable top strip, then flat colour
"rainbow" bands / noise for the rest of the page. Intermittent, at every dpi,
on BUTh transports. Repeated scans of the same page differed.

## The cause: DIME record headers were being fed to the JPEG decoder

This printer does **not** send the image as one contiguous blob. It sends it as
a **DIME record chain**, and each record carries exactly **2048 payload bytes**:

```
[SOAP record][img rec hdr 32 B][2048 B][hdr 12 B][2048 B][hdr 12 B][2048 B]...
```

So a **12-byte non-image header sits inside the image every 2048 bytes.**

Both scan clients sliced `SOI..last-EOI` straight out of the RAW response body,
which therefore embedded one of those headers into the **JPEG entropy stream
every 2048 bytes**. Huffman decoding loses sync at the first embedded header and
everything after it decodes as noise — precisely the reported appearance. It is
intermittent because the failure byte position depends on the image content.

The old DIME walk never caught this: it required `version == 1`, but HP's gSOAP
writes **version 0** (`0x09`), so the walk bailed out immediately and the
`sliceJpeg` short-circuit took over (which is why every log line said
`DIME records=0`).

## The proof (real 300 dpi colour capture)

```
response body            537,068 B
  raw SOI..EOI slice     536,513 B  -> decode FAIL: broken data stream
  DIME record headers       259     (gaps: 2060 x 258 — perfectly regular)
  strip those 259 headers 533,4xx B -> DECODE OK  RGB 2550x3507   <-- the whole page
```

Same bytes. Only the interleaved record headers were removed.

## The fix

`DimeFraming.assemblePayload()` — one shared implementation
(`app/src/main/java/com/ganesan/m175otg/scan/DimeFraming.kt`) used by BOTH
transports, which walks the DIME chain (accepting version 0), skips the SOAP
record, and concatenates the image records' payloads. The JPEG is sliced from
**that** payload, never from the raw body.

Order is the whole fix: **assemble the DIME payload FIRST, slice SOI..EOI SECOND.**

## On-device verification (same physical page, both transports)

```
HP wscn : raw 519KB  DIME rec 261  headers stripped 0  spread 14  flat 1
          -> saved untouched, no retry, 532,262 B, strict decode OK 2550x3507
LEDM    : raw 520KB                 headers stripped 0  spread 14  flat 1
          -> saved untouched, no retry, 532,740 B, strict decode OK 2550x3507
```

`spread` was 65–143 before the fix (rainbow). It is now **14**, and the
integrity gate passes the very first read — no auto-retry.

## Regression tests

`app/src/test/java/com/ganesan/m175otg/scan/DimeFramingTest.kt` (5 tests) runs
against the real captured body shipped as `app/src/test/resources/dime-body-300.bin`:
it asserts the chain assembles to exactly 533,393 B with SOI/APP0 head and EOI
tail, that the raw slice really does contain the 259 interleaved headers, and
that the assembled payload contains **zero** of them.

```
ChunkedFramingTest  tests=6 failures=0
DimeFramingTest     tests=5 failures=0
```

## Secondary findings (still open, lower impact)

1. **The printer's HTTP chunk sizes are unreliable.** It sometimes writes
   *more* data than the size line declares (extra bytes come in multiples of 7,
   the framing-line length; measured 80 anomalies in a 24 MB stream). The
   resync walker recovers, but this is why the scanner occasionally stalls.
2. **`hpraw` (compression NONE) works but is slow** — a 300 dpi A4 colour page
   is 26,828,550 B (7650 x 3507). Useful as a diagnostic; left as an
   off-by-default chip.

## Reproduce the diagnosis

```
python tools/verify_dime_strip.py     # strip 259 headers -> decode OK
python tools/analyze_hpraw.py         # framing break + DIME structure
python tools/gap_analysis.py          # chunk-boundary spacing anomalies
```
