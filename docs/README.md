# HP Color LaserJet MFP M175a — Android App DevKit

Everything needed to build a **native Android printing/scanning app** for the
HP Color LaserJet MFP M175a (USB VID `03F0`, PID `062A`), including the parts
nobody documents publicly. All protocol facts below were **reverse-engineered
from real USB captures of this exact machine** (USBPcap + Wireshark, saved in
`D:\M175Bridge\captures\`).

## The 3 connection modes your app can support

| Mode | Cable/Net | Printing | Scanning | Toner | Difficulty |
|---|---|---|---|---|---|
| **A. USB OTG direct** | OTG cable phone↔printer | ✅ PCL raster / IPP-over-USB | ⚠️ possible (see 04) | ✅ LEDM XML | Medium |
| **B. Wi-Fi via PC bridge** | Wi-Fi (bridge running on PC) | ✅ IPP | ✅ eSCL | ✅ LEDM | Easy (bridge already built & running) |
| **C. Hybrid (recommended)** | both | auto-falls back | auto-falls back | both | = A + B |

> KEY DISCOVERY (from `auto-print-165115.pcap`): this printer runs a **full
> embedded HTTP server over its USB bulk endpoints** (HP "LEDM" stack,
> gSOAP/2.7). Windows itself talks `POST /ipp/print` and
> `GET /DevMgmt/ProductUsageDyn.xml` **through the USB cable**. Your app can
> do exactly the same over USB OTG — no PC needed.

## DevKit contents
- `01-PRINTER-SPECS.md` — hardware facts: interfaces, endpoints, DPI, paper
- `02-USB-PROTOCOL.md` — the wire protocol with real captured evidence
- `03-PRINTING-GUIDE.md` — render pipeline, DPI, PCL raster, IPP-over-USB
- `04-SCANNING-GUIDE.md` — platen/ADF, resolutions, the OTG scan path
- `05-ANDROID-APP-ARCHITECTURE.md` — full app design (Kotlin, Compose, modules)
- `06-CODE-SNIPPETS/` — working Kotlin: USB session, PCL writer, LEDM parser, manual duplex
- `07-TEST-DATA/` — real captured XML, findings, endpoint list
- `08-BUILD-AND-TEST.md` — Gradle, manifest, test plan, troubleshooting

## Real data already decoded (from this printer)
```
Toner (ConsumableRawPercentageLevelRemaining):
  black   80%   cyan   8%   magenta   8%   yellow   9%    (255 = not installed)
Print engine: 600×600 dpi, color laser, no auto-duplex (manual duplex = app's job)
```

## ✅ Everything in this DevKit is PHYSICALLY VERIFIED on this printer
- IPP color + mono test pages printed via the exact app path (2026-09-14)
- Scan matrix 8/8 PASS across 75/200/300/600 dpi and 3 color modes
  (real finding: 150 dpi is not native — quantizes to 200)
- Exact job-control commands extracted from the wire (PJL start/stop/DPI/
  grayscale) — see `03-PRINTING-GUIDE.md` and `07-TEST-DATA/`
- Manual duplex: pass-1 (evens reversed) printed & verified; pass-2 flow
  documented — no guesswork anywhere
