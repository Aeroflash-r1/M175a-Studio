# 08 — Build & Test Plan

## Project setup (Android Studio, Kotlin)
```kotlin
// app/build.gradle.kts (key parts)
android {
    namespace = "com.example.m175print"
    compileSdk = 35
    defaultConfig { minSdk = 26; targetSdk = 35 }
    buildFeatures { compose = true }
}
dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.09.00"))
    implementation("androidx.compose.material3:material3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.datastore:datastore-preferences:1.1.1")
    implementation("io.coil-kt:coil-compose:2.6.0")
}
```

## AndroidManifest.xml (must-haves)
```xml
<uses-feature android:name="android.hardware.usb.host" android:required="false"/>
<uses-feature android:name="android.hardware.usb.host" />
<application ...>
  <activity android:name=".MainActivity" android:exported="true">
    <intent-filter>
      <action android:name="android.intent.action.MAIN"/>
      <category android:name="android.intent.category.LAUNCHER"/>
    </intent-filter>
    <!-- launched when the printer is plugged via OTG -->
    <intent-filter>
      <action android:name="android.hardware.usb.action.USB_DEVICE_ATTACHED"/>
    </intent-filter>
    <meta-data android:name="android.hardware.usb.action.USB_DEVICE_ATTACHED"
      android:resource="@xml/device_filter"/>
  </activity>
</application>
```
`res/xml/device_filter.xml`:
```xml
<resources>
  <usb-device vendor-id="1008"/>  <!-- 0x03F0 = 1008 decimal (HP) -->
</resources>
```
No INTERNET permission needed for pure USB; add it only for the bridge path.

## Test checklist (do in this order)
1. **Discovery** — OTG cable + printer on: device appears w/ VID 03F0.
   Permission dialog → allow.
2. **LEDM over USB** — app shows toner K81 C9 M9 Y11 (compare with real unit).
3. **Mono print** — PCL5 writer, 300 dpi, one text page. Expect page.
4. **600 dpi print** — sharper text; verify timing (<30 s transfer).
5. **PDF print via bridge** — IPP `application/pdf`; tests printer's own
   PDF interpreter (decides your color path!).
6. **Color print** — PCL6 or IPP-PDF; verify CMY registration.
7. **Scan via bridge** — eSCL 300 dpi RGB; auto-crop; export PDF.
8. **Scan over USB** — try `GET /eSCL/ScannerCapabilities` on BIDI pipe
   (04-SCANNING-GUIDE Path B-2); if 200 OK, implement OTG eSCL.
9. **Manual duplex** — 4-page doc: evens reversed → flip dialog → odds.
   Verify alignment; record offsets into Settings calibration.
10. **Toner low UX** — force-threshold at 15% → alert shown.

## Known gotchas (from building the PC side of this exact setup)
- Printer sleeps ~15 min; first job wakes it (allow +8 s before status read).
- bulkTransfer max is 16384 bytes per call on many devices — chunk writes.
- USB re-enumeration (HP tools replug) changes endpoint addrs — re-discover,
  never cache across attach events.
- If printer reports `Off-line` in status XML right after job: poll
  JobStatusDyn, it transitions Processing→Printing→Completed.
- 1200 dpi color A4 ≈ 100 MB raster — phone OOM risk: render per-page,
  stream rows, recycle bitmaps aggressively.

## Shipping checklist
- [ ] Runtime permissions (USB) with rationale screen
- [ ] Job progress notification + cancel
- [ ] Crash-safe: wrap USB errors → reconnect flow
- [ ] Store: screenshots of toner gauges + duplex wizard (sell the quality!)
