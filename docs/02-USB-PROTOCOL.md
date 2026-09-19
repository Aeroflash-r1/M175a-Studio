# 02 — USB Protocol (from real captures of this printer)

Evidence files: `D:\M175Bridge\captures\auto-print-165115.pcap` and
`print-session-164046.pcap` (open in Wireshark, filter
`usb.endpoint_address==0x89`).

## What we learned (surprising but verified)

The M175a's MI_02 BIDI interface is **not** old PML-over-1284.4. It is a
**raw TCP-like HTTP pipe**: Windows writes whole HTTP requests into bulk OUT
and reads whole HTTP responses from bulk IN. The printer's embedded server is
**gSOAP/2.7 (HP LEDM)**. This means a phone with USB OTG can literally speak
HTTP to the printer.

### Proof (captured requests the driver sent through USB)
```
POST /ipp/print HTTP/1.1
Content-Type: application/ipp
HOST: localhost
Content-Length: 197
<binary IPP payload>

GET /DevMgmt/ProductUsageDyn.xml HTTP/1.1
HOST: localhost
```

### Proof (responses)
```
HTTP/1.1 200 OK
Server: gSOAP/2.7
Content-Type: application/ipp        (for /ipp/print)
Content-Type: text/xml; charset=utf-8 (for /DevMgmt/*)

<prdcfgdyn:ProductConfigDyn ...>
  <dd:TotalMemory>128</dd:TotalMemory>
  <ConsumableRawPercentageLevelRemaining>81</...>  ← REAL TONER
```

## HTTP-over-USB session pattern (what your app must do)
1. Open `UsbDeviceConnection.bulkTransfer(epOut=0x09, httpBytes)`
2. Loop `bulkTransfer(epIn=0x89, buf)` until you have `Content-Length` bytes
   (or connection close). Chunked responses: parse chunks.
3. One HTTP request = one "session". Keep-alive is supported but optional.

## Endpoint discovery at runtime
Don't hardcode. Enumerate interfaces:
```kotlin
for (iface in device.interfaces) when (iface.interfaceClass) {
    7  -> {}  // printer class - bulk OUT = print path
    6  -> {}  // still image - scan path
    255 -> {} // vendor BIDI (this model: HTTP/LEDM lives here)
}
```
On this unit: printer bulk OUT `0x09`, BIDI IN `0x89`, scan IN `0x81`
(re-verify per device — they can differ after re-enumeration).

## Idle traffic fingerprint (useful for connection sanity check)
When idle, Windows polls BIDI with empty 27-byte frames ~2/sec. If you see
those, the pipe is healthy. Print jobs show as bursts of large OUT frames.

## Frames we verified byte-level
- `1b 00 10 c0 ... 00 07 00 89 03` — USBPcap pseudo-header + endpoint 0x89
- Empty polls: 27-byte frames, no payload
- Real HTTP: whole request visible in single OUT frame (up to MTU), continued
  in subsequent frames for bodies (IPP job data).

## IPP-over-USB note
The printer accepts `POST /ipp/print` with IPP 1.1 payloads. For pure
USB-OTG printing, your app can send:
- `Get-Printer-Attributes` → capabilities (media, dpi, duplex info)
- `Print-Job` with `document-format: application/octet-stream` containing
  **PCL raster** you rendered (guide 03), or `application/pdf` if the
  printer's PDF interpreter accepts it (test — firmware 2015+ usually does).

## Old-school fallback (if you prefer classic path)
The printer also understands PCL6/PCL5 + PJL on the plain printer interface
(MI_01). Status via PJL `@PJL INFO STATUS` / USTATUS works there. But the
LEDM HTTP path is richer (toner percentages, usage counters) and is what we
verified working on this exact unit.
