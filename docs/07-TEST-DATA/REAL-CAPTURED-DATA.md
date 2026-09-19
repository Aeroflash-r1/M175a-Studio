# 07 — Real Captured Data (from THIS printer, Sep 2026)

Source captures: `D:\M175Bridge\captures\`
- `auto-print-165115.pcap` — automated test-page run (I triggered it)
- `print-session-164046.pcap` — 15.7 MB incl. full LEDM session
- `pml_findings.json` — decoded findings

Open any capture in Wireshark → filter: `usb.endpoint_address == 0x89`

## Decoded toner (ConsumableRawPercentageLevelRemaining)
```json
{ "black": 81, "cyan": 9, "magenta": 9, "yellow": 11 }
```
(255 = not installed / unknown → app must treat as "missing")

## Real XML the printer returned over USB (fragments)
```xml
<pudyn:Consumable>
  <dd:MarkerColor>Yellow</dd:MarkerColor>
  <dd:ConsumableTypeEnum>toner</dd:ConsumableTypeEnum>
  <dd:ConsumableRawPercentageLevelRemaining>11
    </dd:ConsumableRawPercentageLevelRemaining>
  <dd:Installation><dd:Date>2017-04-03</dd:Date></dd:Installation>
</pudyn:Consumable>
<pudyn:Consumable>
  <dd:ConsumableTypeEnum>imageDrum</dd:ConsumableTypeEnum>
  ...
</pudyn:Consumable>
```
ProductConfigDyn also exposes: `TotalMemory 128 (MB)`, `PowerSave off`,
`AssetNumber`, `PasswordStatus`.

## Endpoints observed (driver ↔ printer over USB)
```
POST /ipp/print                         (IPP 1.1, gSOAP/2.7 answers)
GET  /DevMgmt/ProductUsageDyn.xml       (toner/usage)
GET  /DevMgmt/ProductConfigDyn.xml      (config, memory, supplies meta)
GET  /DevMgmt/ProductStatusDyn.xml      (status)
GET  /DevMgmt/NetAppsDyn.xml
GET  /DevMgmt/NetAppsSecureDyn.xml
GET  /IoMgmt/Adapters
GET  /cdm/system/v1/identity
GET  /cdm/ioConfig/v2/adapterConfigs
GET  /cdm/network/v1/discoveryServices
GET  /cdm/network/v1/printServices
```
→ Try each over USB-OTG in your app; all are plain HTTP GETs on the BIDI pipe.

## EXACT print job structure (extracted from real capture,
## print-session-173348.pcap — 135,717 OUT bytes decoded)
```
ESC%-12345X                          <- UEL: start of job language switch
@PJL SET RET=ON                      <- resolution enhancement ON
@PJL JOB NAME="CAPTURE-JOB"          <- JOB START
@PJL SET STRINGCODESET=UTF8
@PJL SET USERNAME="..."
@PJL SET JOBNAME="..."
@PJL SET SEPARATORPAGE=OFF
@PJL SET GRAYSCALE=OFF               <- MONO/COLOR SWITCH (ON = grayscale!)
@PJL SET RESOLUTION=600              <- DPI COMMAND (300/600 verified)
@PJL SET BITSPERPIXEL=8
@PJL ENTER LANGUAGE=PCLXL            <- switch to PCL6 raster
) HP-PCL XL;3;...                    <- PCL XL binary stream follows
@PJL EOJ                             <- JOB END
ESC%-12345X                          <- UEL: done
```
So an app controls printing with just:
| Function | Exact command |
|---|---|
| Start job | `ESC%-12345X` + `@PJL JOB NAME="x"` |
| Set DPI | `@PJL SET RESOLUTION=300` (or 600) |
| Mono/Color | `@PJL SET GRAYSCALE=ON` / `OFF` |
| Enter raster | `@PJL ENTER LANGUAGE=PCLXL` |
| End job | `@PJL EOJ` + `ESC%-12345X` |
| Cancel | send `@PJL EOJ` immediately (flush pending data) |

## VERIFIED TEST RESULTS (all physically run on this printer, Sep 2026)

### Printing via IPP (exact path an Android app uses)
| Test | Result |
|---|---|
| IPP Print-Job, color PDF | ✅ SUCCESS — page printed, colors true |
| IPP Print-Job, mono PDF | ✅ SUCCESS — 600dpi text sharp |
| Manual duplex pass 1 (evens reversed) | ✅ SUCCESS — sheets face-up reversed |
| Manual duplex pass 2 (odds after flip) | ✅ SUCCESS — duplex verified end-to-end with the 2-sheet mini test (page 1 cyan-chip \| 2 magenta-chip, 3 yellow \| 4 black; flip = whole stack over like a book page, same edge on top) |

### Scanning (WIA engine = same one the bridge/phone path drives)
| Mode | Result | Real output |
|---|---|---|
| color 75 dpi | ✅ PASS | 637×876 px, 99 KB |
| color 150 dpi | ⚠️ quantizes to **200** | 1700×2338 px, 557 KB |
| color 200 dpi | ✅ PASS | 1700×2338 px, 557 KB |
| color 300 dpi | ✅ PASS | 2550×3507 px, 1.57 MB |
| color 600 dpi | ✅ PASS | 5100×7014 px, 7.3 MB |
| grayscale 200 dpi | ✅ PASS | 701 KB |
| grayscale 300 dpi | ✅ PASS | 2.1 MB |
| binary (B/W) 300 dpi | ✅ PASS | 1.37 MB |

**True scanner steps: 75 / 200 / 300 / 600 — 150 is NOT a native step**
(Windows WIA silently bumps it to 200; an app should offer only
75/200/300/600 to avoid surprises).

### Toner (live, moved during testing — proof of real-time reading)
Before tests: K81 C9 M9 Y11 → after 5 test pages: K80 C8 M8 Y9.

## Printer LCD behavior (captured during real job)
During printing the printer's status XML (its LCD text source) reported:
```xml
<psdyn:LocString lang="en">Printing document</psdyn:LocString>
```
The 2-line LCD only mirrors status strings (Ready / Printing document /
alerts). It NEVER pauses for a manual-duplex reinsert — the flip prompt
always comes from the submitting software (Windows driver dialog on PC,
your app's flip screen on Android, the bridge dashboard's flip card).
Poll `/DevMgmt/ProductStatusDyn.xml` and show these LocStrings as the
in-app printer status line.

## VERIFIED manual duplex order (do not change!)
```
PASS 1: EVEN pages in REVERSE order  → e.g. 8,6,4,2 (or 4,2)
  flip: whole stack over like a book page, blank sides up,
        same edge on top (long-edge flip, portrait)
PASS 2: ODD pages in FORWARD order   → e.g. 1,3,5,7
Result: collated 1|2, 3|4, 5|6, 7|8 — verified physically.
```
Reversing pass 1 is what makes the stack collate correctly; do not swap.

## USBPcap capture commands (cheat sheet)
```
C:\Program Files\USBPcap\USBPcapCMD.exe -d \\.\USBPcap1 -A -o out.pcap
D:\Wireshark\tshark.exe -r out.pcap -Y usb.src=="host" -T fields -e usb.capdata
```
Automated tooling already built: `D:\M175Bridge\tools\auto_capture.py`
(records + triggers test page + decodes toner, zero user input).
