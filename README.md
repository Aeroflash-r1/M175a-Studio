# M175a Studio — HP LaserJet 100 MFP M175a control suite

A complete, self-developed printing & scanning stack for the **HP LaserJet 100
color MFP M175a** (USB VID `03F0` / PID `062A`), built from live wire captures
of the real device — every protocol byte verified, nothing guessed.

```
┌──────────────┐  USB OTG   ┌─────────────┐
│   Android    │───────────▶│  HP M175a   │   Print · Scan (flatbed+ADF) ·
│  (this app)  │            │             │   Toner/drum status · Manual
└──────────────┘            └─────────────┘   duplex · Booklet · 21 papers
       │
       │ optional (Wi-Fi / same LAN)
       ▼
┌──────────────────────────────┐
│  windows-bridge (Python)     │  eSCL + IPP bridge that lets ANY phone
│  runs on the PC, owns USB    │  or iOS device print & scan over Wi-Fi
└──────────────────────────────┘
```

## Repository layout

| Path | What it is |
|---|---|
| `app/` | **Android app** (Kotlin + Compose Material 3) — USB OTG print/scan/status, system PrintService, plus Wi-Fi bridge mode |
| `docs/` | **M175 Android DevKit** — 17 reverse-engineering reports: USB/PCL XL/LEDM protocols, verified packet captures analysis, scan-corruption root-cause chain, full audit |
| `windows-bridge/` | PC-side Python bridge (IPP/eSCL → Windows spooler/WIA) + USBPcap analysis tools |
| `reference/` | Raw captured OTG streams used by the reverse-engineering docs |

## Feature summary (app)

- **Print**: PDFs & images over USB OTG (PCL XL), 300/600 dpi, color or greyscale,
  page ranges, copies, scale/margins/position, orientation, **21 paper sizes**
  with media names byte-verified against HP's own driver output
- **Manual duplex** & **booklet imposition** (with printer-display prompts and
  even/odd two-pass ordering), N-up layouts, reverse order, skip blank pages
- **Scan**: flatbed + ADF, JPEG/PDF output, real DPI, greyscale/color,
  chunked-transfer hardened against HP's misframed HTTP chunks
- **Status**: live toner levels, drum, lifetime page counters, alerts
- **System integration**: registered Android `PrintService` (print from any
  app), share-sheet intake, persisted defaults, job history, notifications

## Building the app

**Requirements**: JDK 17, Android SDK (platform 34, build-tools 34), Gradle
8.7 (wrapper included).

```bash
./gradlew assembleDebug          # APK at app/build/outputs/apk/debug/
./gradlew testDebugUnitTest      # 29 unit tests (incl. wire-byte regression)
```

Or open the folder in Android Studio / a GitHub Codespace — the included
devcontainer provisions JDK 17 + the Android SDK automatically.

> **Hardware note**: printing/scanning needs a real M175a on the cable.
> Emulators can only exercise the UI and the pure-JVM protocol layers.

## The PC bridge

```powershell
cd windows-bridge
install.bat          # creates venv, installs deps, registers autostart
python run.py        # serves IPP + eSCL + web UI on :8080
```

See `docs/README.md` for the full reverse-engineering story, including the
verified USB endpoint map (`docs/09-OTG-PROTOCOL-VERIFIED.md`) and the
scan-over-OTG protocol (`docs/10-SCAN-OTG-VERIFIED.md`).
