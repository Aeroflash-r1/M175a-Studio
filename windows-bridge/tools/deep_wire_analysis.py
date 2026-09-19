"""Deep wire analysis of the fresh 200 dpi capture — answer with certainty:
1. How big is the image response the printer REALLY sends?
2. Chunk framing: sizes, extensions, trailer format — anything nonstandard?
3. Mid-stream pauses (the phone-side stall evidence)?
4. Is the WIA-received image complete (SOI..EOI vs SOF dims)?
"""
import subprocess
import sys
import time

PCAP = "captures/scan-otg-110452.pcap"
TSHARK = r"D:/Wireshark/tshark.exe"

# 1) pull EP 0x83 bulk data with timestamps, in order
out = subprocess.run(
    [TSHARK, "-r", PCAP,
     "-Y", "usb.endpoint_address == 131 && usb.transfer_type == 3 && usb.data_len > 0",
     "-T", "fields", "-e", "frame.time_epoch", "-e", "usb.data_len", "-e", "usb.capdata"],
    capture_output=True, text=True).stdout

frames = []
for line in out.splitlines():
    parts = line.split("\t")
    if len(parts) >= 3 and parts[2]:
        try:
            ts = float(parts[0]); ln = int(parts[1])
            data = bytes.fromhex(parts[2].replace(":", ""))
            frames.append((ts, ln, data))
        except (ValueError, IndexError):
            continue

print("EP 0x83 frames with data:", len(frames),
      "total bytes:", sum(f[1] for f in frames))

stream = b"".join(f[2] for f in frames)
print("reassembled stream:", len(stream), "bytes")

# 2) find responses (HTTP headers) in the stream
import re
hdr_iter = list(re.finditer(rb"HTTP/1\.1 (\d{3})", stream))
print("\nresponses:", [(m.group(1).decode(), m.start()) for m in hdr_iter])

# image response = the 200
img_m = None
for m in hdr_iter:
    if m.group(1) == b"200":
        img_m = m
if img_m is None:
    print("NO 200 IMAGE RESPONSE"); sys.exit(1)

start = img_m.start()
he = stream.find(b"\r\n\r\n", start)
headers = stream[start:he].decode("latin1")
print("\n--- image response headers ---")
print(headers)

te = "chunked" in headers.lower()
cl = re.search(r"Content-Length:\s*(\d+)", headers, re.I)
print("chunked:", te, "| content-length:", cl.group(1) if cl else None)

body = stream[he + 4:]
print("\nbody bytes present:", len(body))

# 3) walk the chunk chain strictly, logging sizes and anomalies
sizes = []
pos = 0
anomalies = []
while pos < len(body):
    eol = body.find(b"\r\n", pos)
    if eol < 0:
        anomalies.append("no CRLF at %d (tail %d bytes)" % (pos, len(body) - pos))
        break
    sizeline = body[pos:eol]
    m = re.match(rb"^([0-9A-Fa-f]+)(;.*)?$", sizeline)
    if not m:
        # likely inside image entropy (not a chunk line) => body isn't chunked here
        anomalies.append("non-chunk-size line at %d: %r" % (pos, sizeline[:40]))
        break
    sz = int(m.group(1), 16)
    sizes.append(sz)
    if sz == 0:
        pos = eol + 2
        trailer_end = body.find(b"\r\n\r\n", pos - 2)
        print("terminator at body offset %d; trailer bytes after last chunk: %r"
              % (pos, body[pos:pos + 40]))
        break
    pos = eol + 2 + sz + 2
else:
    print("walk ended by stream end")

print("\nchunks:", len(sizes), "| first 5:", sizes[:5], "| last 5:", sizes[-5:])
print("chunk size min/max:", min(sizes), max(sizes))
if anomalies:
    print("ANOMALIES:", anomalies)
else:
    print("no anomalies — clean chunk chain")

# 4) where does the JPEG end relative to the body/stream?
soi = body.find(b"\xff\xd8")
eoi = body.rfind(b"\xff\xd9")
print("\nJPEG in body: SOI@%d EOI@%d -> image bytes %d" % (soi, eoi, eoi - soi + 2))
print("bytes after EOI in body:", len(body) - (eoi + 2))

# 5) mid-stream pauses from frame timestamps
print("\n--- top time gaps between consecutive EP 0x83 frames ---")
gaps = []
for i in range(1, len(frames)):
    g = frames[i][0] - frames[i - 1][0]
    gaps.append((g, i))
gaps.sort(reverse=True)
for g, i in gaps[:8]:
    print("gap %.2fs before frame %d (offset ~%d)" %
          (g, i, sum(f[1] for f in frames[:i])))

# 6) decode test of the delivered image (tolerant like Android, strict like PIL)
img = body[soi:eoi + 2]
open("tmp/wire-image-200.jpg", "wb").write(img)
try:
    from PIL import Image
    im = Image.open("tmp/wire-image-200.jpg"); im.load()
    print("\nPIL strict decode: OK", im.size)
except Exception as e:
    print("\nPIL strict decode FAIL:", e)
    try:
        from PIL import Image
        im = Image.open("tmp/wire-image-200.jpg")
        im = im.convert("RGB")
        print("PIL tolerant decode:", im.size, "(data incomplete but renderable)")
    except Exception as e2:
        print("even tolerant decode failed:", e2)
