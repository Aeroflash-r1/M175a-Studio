# 🔬 Scan-over-OTG Protocol — VERIFIED from the real wire (Sept 2026)

Captured live: `scan-otg-195230.pcap` (10.7 MB) while Windows scanned a real
page at 300 dpi color via WIA. Every line below is from that capture.

## Endpoints

| EP | Dir | Use |
|---|---|---|
| `0x03` | OUT | scan commands: HTTP POST (chunked) + SOAP XML |
| `0x83` | IN | responses: HTTP 202 SOAP acks + the scanned **JPEG** |
| `0x81` | IN | idle scanner status chatter (27-byte frames) |

The protocol is **HP LEDM / WS-Scan SOAP over USB** — the same WS-Scan
dialect the printer would speak over the network, carried on bulk pipes.
No HP SDK, no WIA — an Android app can send these strings directly.

## The exact captured sequence

```
PHONE -> PRINTER (EP 0x03):                PRINTER -> PHONE (EP 0x83):

POST / HTTP/1.1
Host: http:0
User-Agent: gSOAP/2.7
Content-Type: application/soap+xml
Transfer-Encoding: chunked
Connection: close

<wscn:CreateScanJobRequest>          ---->  HTTP/1.1 202 ACCEPTED
  <ScanTicket>                              <CreateScanJobResponseType>
    <DocumentParameters>                      <JobId>1</JobId>
      <Format>jfif</Format>                   <JobToken></JobToken>
      <InputSource>Platen</InputSource>     </CreateScanJobResponseType>
      <InputMediaSize>
        <Width>8500</Width>   (1/1000 inch!)
        <Height>11690</Height>
      </InputMediaSize>
      <ScanRegion ...same units...>
      <ColorProcessing>RGB24</ColorProcessing>
      <Resolution><Width>300</Width><Height>300</Height></Resolution>
    </DocumentParameters>
  </ScanTicket>
</wscn:CreateScanJobRequest>

<wscn:RetrieveImageRequest>          ---->  HTTP/1.1 200 OK
  <JobId>1</JobId>                          [raw JPEG bytes FFD8...FFD9]
  <JobToken></JobToken>                     (~1 MB for A4 300dpi color)
</wscn:RetrieveImageRequest>

<wscn:GetJobInfo><jobId>1</jobId>    ---->  HTTP/1.1 202 ACCEPTED
</wscn:GetJobInfo>                          (cleanup ack)
```

That is the WHOLE protocol: 7 tiny SOAP commands total were sent for a full
scan. Total command bytes: 5,183. Response: 1,070,340 bytes of JPEG.

## Verified parameter values

- `Format`: `jfif` (JPEG!) — the scanner returns JPEG natively
- `InputSource`: `Platen` (the glass)
- Size units: **1/1000 inch** — 8500×11690 = full glass = 8.5"×11.69"
- `ColorProcessing`: `RGB24` (color, 24-bit), `Grayscale` (8-bit),
  `BlackPixel1` (1-bit lineart)
- DPI: 75 / 200 / 300 / 600 are the true engine steps (150 is quantized
  to 200 by firmware — verified in the earlier scan matrix)
- Response image = bare JPEG inside chunked HTTP; find `FFD8FF` … `FFD9`
- HTTP statuses: 202 = command accepted, 200 = image payload

## Kotlin implementation

`M175-Android-App/.../scan/LedmScanClient.kt` implements exactly this:
`scanFlatbed(dpi, colorMode) -> ByteArray (JPEG)`. It reuses the
connection's scan endpoints and the same chunked-HTTP framing the driver
used (hex length + CRLF + body + `0\r\n\r\n`).

## Reference files

- `D:\M175Bridge\devkit-reference\scan-commands-readable.txt` — all 7 captured commands, full text
- `D:\M175Bridge\devkit-reference\scan-responses.bin` — raw 1.07 MB response stream (acks + JPEG)
- `D:\M175Bridge\captures\scan-otg-195230.pcap` — full Wireshark capture

## Cross-check vs the Wi-Fi path

The PC bridge's eSCL server also scans via WIA — same engine, same image
sizes. A page scanned over USB SOAP at 300 dpi color ≈ 1 MB JPEG ≈ what
eSCL returns on the network path. Consistency confirmed.

---

# 🔁 UPDATE — Sept 14 late session (fresh capture scan-otg-235137.pcap)

Corrections found by re-analyzing a NEW capture with full frame visibility
(the original reassembler silently dropped the 7-byte terminator frames,
leading to two wrong conclusions that broke the phone app):

1. **ARMING HANDSHAKE — REQUIRED.** The driver sends
   `GetScannerElements` (empty body, 414 B) **three times** BEFORE
   `CreateScanJobRequest`, each answered by HTTP 202. Without this, the
   M175a accepts CreateScanJob but never starts the lamp/mechanism —
   job shows on the LCD and stalls forever (observed on the phone).
2. **Chunked terminator IS on the wire.** Every command ends with a
   7-byte frame `\r\n0\r\n\r\n` (frame 27/35/etc. in the raw listing —
   visible in `usb.data_len`, absorbed by Wireshark's HTTP dissector so
   it does not appear in `usb.capdata`). Omitting it = printer never
   parses the command at all.
3. **XML declaration newline is LF only**: `<?xml ...?>\n` (not CRLF).
4. **Response sequence per command** (must read exactly one response
   after each send, in order):
   `GetScannerElements` -> 202 x3, `CreateScanJob` -> 202 (JobId in body),
   `RetrieveImage` -> 200 + DIME JPEG (chunked, terminator present),
   `GetJobInfo` -> 202, `GetPreviousImagePadInfo` -> 202.
5. GetScannerElements/GetJobInfo bodies captured: literally
   `<wscn:GetScannerElements></wscn:GetScannerElements>` and
   `<wscn:GetJobInfo><jobId>N</jobId></wscn:GetJobInfo>`.

Full template byte-check: the app's CreateScanJobRequest now equals the
wire EXACTLY (1492/1492 bytes, byte-level diff clean).

---

# 🔬 ADDENDUM — Native-image coherence & the HP driver's secret file (Sept 15, 2026)

## 1. The "rainbow stripes" root cause — MEASURED
Paired captures (same page, same session): native JPEG from the wire vs
the JPEG Windows/WIA finally delivers.

| Mode | native channel means R/G/B | spread | verdict |
|---|---|---|---|
| 300 dpi color (2 sessions) | 130/130/130 · 115/136/113 | **0–23** | coherent |
| 200 dpi color | 75/144/218 | **143** | RGB line misregistration |
| 200 dpi "gray" | 85/179/144 (still 3-plane!) | **94** | misregistered |

**Rule for this model: raw RGB24 output is only structurally coherent at
300 dpi.** At 150/200 the engine decimates CCD lines with channel
misregistration → rainbow/dark output. HP's WIA driver repairs this in
software ("WIA_AIO_PASSTHROUGH_SETTINGS: Reads raw data from scanner,
applies brightness/contrast/threshold in software" — from its own config).

## 2. App ticket vs driver ticket — byte-identical
Full CreateScanJobRequest extracted from the live WIA session
(tmp/wia-cmd-3.xml): every field identical to the app's ticket
(Format/Exposure/ScanRegion/Resolution/RGB24/timeout). The app does
exactly what the driver does; the difference is HP's post-processing.

## 3. Repair-pipeline replication attempts (all FAILED, real paired data)
Inversion, line de-interleave (period 2–8, both orders), chroma-plane
swap, per-channel histogram matching, linear per-channel fit (gains came
out NEGATIVE — no linear fix exists), planes-as-RGB, DIME contamination
(none found), column segment packing, inter-plane shift search.
Conclusion: 200 dpi damage is multi-stage sensor processing, not a
simple permutation. NOT worth replicating — 300 dpi needs no repair.

## 4. 💎 hppls100.spf DECODED (HP's binary scanner parameter file)
Location: `C:\Windows\System32\DriverStore\FileRepository\hppasc20.inf_*\hppls100.spf`
Format (reverse-engineered, see tools/decode_spf.py):
```
b"!@#$%\0" + u32 root_token(0x149) + u32 leaf_count(75) + u32 msg_len(2126)
+ 75 leaf slots (u32 ascii-code + 8x 0xFF, 12 B each)
+ 74 Huffman-tree triplets (u32 id 0x100..0x149, child0, child1)
+ bit-packed message (MSB-first, bit0=child0) — Huffman-compressed TEXT
```
Decoded contents (full text in tmp/spf-decoded.txt):
- **SHARP_SMOOTH**: sharpen values 0/20/30/40/50, smooth 0–8
- **DEFAULTS**: photoRes=200, grayChannel=3(NTSC), glass 1200×992,
  highlight=255
- **JPEG_QFACTOR_24**: JPEG on for 150/200/300/600 dpi (Q=2, Q=3 at
  1200), OFF at 75
- **EXCLUSION_AREAS**: full glass 8.5×11.69"
- The WIA driver's gamma/LUT tables are configured at runtime
  (Tulip::SetGammaTable), values sourced per-session — not in this file.

## 5. App decisions locked
- Scan default = **300 dpi** (coherent native path; 600 optional "slow",
  150 removed — engine quantizes it)
- Client-side per-channel auto-levels stand in for the driver's
  brightness/contrast software layer
- Black-scan detector explains empty-bed scans instead of saving garbage
