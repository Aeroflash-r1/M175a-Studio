# 01 — Printer Specs (measured on this machine)

## Identity
| | |
|---|---|
| Model | HP Color LaserJet Pro MFP M175a (also sold as CLJ MFP M175 / CM1415 family) |
| USB VID:PID | `03F0:062A` (HP Inc.) |
| Windows device | USB Composite Device → 3 interfaces |
| Windows queue | "HP LaserJet 100 color MFP M175 PCL6" |
| Firmware HTTP server | gSOAP/2.7 (HP LEDM stack) — alive over USB |

## USB interfaces (from Get-PnpDevice + captures)
| Interface | Function | Windows binding |
|---|---|---|
| MI_00 | **Scan** (still image) | `HP LJ100 M175 Scan` (WIA, `hpwia2_lj100m175.dll`) |
| MI_01 | **Printer** (host-based printing) | `Hewlett-Packard HP LaserJet 100 colorMFP M175a` |
| MI_02 | **BIDI status channel** | `HP Printer (BIDI)` — carries HTTP/LEDM over bulk pipes |

## USB endpoints seen in captures (bus 1, device 7)
| Endpoint | Dir | Type | Purpose |
|---|---|---|---|
| `0x09` | OUT | bulk | Print data (host→printer) |
| `0x89` | IN | bulk | **Status/HTTP replies (printer→host)** — BIDI |
| `0x81` | IN | bulk | Scan image data |
| `0x00/0x80` | control | — | Enumeration |

## Engine
| | |
|---|---|
| Technology | Color laser, single-pass in-line |
| Native resolution | **600×600 dpi** (engine); 300/600 for host-based rendering |
| Duplex | ❌ **No auto-duplex** → manual duplex = app's job (guide 06) |
| Control panel | Small 2-line **LCD** (status/errors) + LED buttons — NOTE: duplex flip-prompt still comes from software (driver dialog on PC, app screen on phone), not from the printer LCD |
| Max monthly duty | 30,000 pages |
| Scan | Flatbed only, up to 1200×1200 enhanced / 1200 optical CIS |
| Paper | A4, A5, A6, B5, B6, exec, legal, letter; tray 150 sheets; output 100 |
| Speed | 600 MHz, 128 MB RAM (from ProductConfigDyn.xml) |

## Consumables (as reported by THIS unit via LEDM)
```
CE310A black  ~1600 pages   current: 81%
CE311A cyan   ~1000 pages   current:  9%   ← buy soon
CE312A yellow ~1000 pages   current: 11%   ← buy soon
CE313A magenta ~1000 pages  current:  9%   ← buy soon
image drum    14000 pages   (reported as imageDrum supply)
```
Installation dates of supplies are in the XML (`dd:Installation/dd:Date`).

## Network: none built-in (USB only) — that's why the bridge/OTG exists.
