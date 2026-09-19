"""Find the TRUE chunk framing of the printer's DIME-over-chunked stream.

The naive walk (size line -> data -> CRLF -> next) parses 32x2048 cleanly
then lands 48 bytes PAST a real '800\r\n' boundary. This tool:
 1. walks with resync: at each boundary, if the expected size line isn't
    hex+CRLF, searches nearby for the real one and LOGS the correction,
 2. reconstructs the de-chunked DIME stream byte-exact,
 3. verifies the result against DIME structure + the embedded JPEG.
"""
import re

PCAP_BODY = None
import subprocess
TSHARK = r"D:/Wireshark/tshark.exe"

out = subprocess.run([TSHARK, "-r", "captures/scan-otg-110452.pcap",
    "-Y", "usb.endpoint_address == 131 && usb.transfer_type == 3 && usb.data_len > 0",
    "-T", "fields", "-e", "usb.data_len", "-e", "usb.capdata"],
    capture_output=True, text=True).stdout
frames = []
for line in out.splitlines():
    p = line.split("\t")
    if len(p) >= 2 and p[1]:
        frames.append(bytes.fromhex(p[1].replace(":", "")))
stream = b"".join(frames)
m200 = None
for m in re.finditer(rb"HTTP/1\.1 (\d{3})", stream):
    if m.group(1) == b"200":
        m200 = m
he = stream.find(b"\r\n\r\n", m200.start())
body = stream[he + 4:]
print("body:", len(body))

SIZE_RE = re.compile(rb"^([0-9A-Fa-f]{1,6})\r\n")


def find_real_boundary(pos, window=300):
    """Search [pos-window, pos+window] for a valid size-line start whose
    hex value is plausible (0 < v <= 4096). Returns (offset, size) or None."""
    best = None
    for d in range(0, window):
        for cand in (pos - d, pos + d):
            if cand < 0 or cand >= len(body):
                continue
            m = SIZE_RE.match(body, cand)
            if m:
                v = int(m.group(1), 16)
                if 0 < v <= 4096 and (best is None or abs(cand - pos) < abs(best[0] - pos)):
                    best = (cand, v)
        if best is not None and d > 8:
            break
    return best


pos = 0
chunks = []
corrections = []
data_out = bytearray()
guard = 0
while pos < len(body) and guard < 1_000_000:
    guard += 1
    m = SIZE_RE.match(body, pos)
    if m:
        sz = int(m.group(1), 16)
        if sz == 0:
            chunks.append((pos, 0))
            print("terminator at", pos)
            pos += 5  # "0\r\n\r\n" possibly with trailer
            break
        data_start = pos + len(m.group(0))
        if data_start + sz > len(body):
            print("incomplete final chunk at", pos)
            break
        data_out += body[data_start:data_start + sz]
        chunks.append((pos, sz))
        # after data: expect CRLF
        nxt = data_start + sz
        if body[nxt:nxt + 2] == b"\r\n":
            pos = nxt + 2
        else:
            corrections.append(("missing data CRLF after chunk %d" % len(chunks), nxt))
            # resync: next size line may be immediately at nxt
            m2 = SIZE_RE.match(body, nxt)
            if m2:
                pos = nxt
            else:
                fb = find_real_boundary(nxt)
                if fb is None:
                    print("cannot resync at", nxt)
                    break
                corrections.append(("resync +%d" % (fb[0] - nxt), nxt, fb[0]))
                pos = fb[0]
    else:
        fb = find_real_boundary(pos)
        if fb is None:
            print("dead end at", pos, "context:", body[pos:pos + 32].hex())
            break
        corrections.append(("boundary shift %+d" % (fb[0] - pos), pos, fb[0], fb[1]))
        pos = fb[0]

print("\nchunks walked:", len(chunks))
print("size histogram:", {})
from collections import Counter
print(Counter(s for _, s in chunks))
print("\ncorrections:", len(corrections))
for c in corrections[:20]:
    print("  ", c)

open("tmp/dime-stream.bin", "wb").write(bytes(data_out))
print("\nde-chunked data:", len(data_out), "bytes -> tmp/dime-stream.bin")

# DIME parse of the de-chunked stream
b = bytes(data_out)
i = 0
recs = []
while i + 12 <= len(b):
    b0 = b[i]
    if (b0 >> 5) != 1:
        print("DIME: non-DIME byte at", i, b[i:i + 8].hex())
        break
    me = (b0 & 0x08) != 0
    cf = (b0 & 0x04) != 0
    opt_len = (b[i + 2] << 8) | b[i + 3]
    id_len = (b[i + 4] << 8) | b[i + 5]
    ty_len = (b[i + 6] << 8) | b[i + 7]
    data_len = (b[i + 8] << 24) | (b[i + 9] << 16) | (b[i + 10] << 8) | b[i + 11]
    p = i + 12
    pad = lambda n: (n + 3) // 4 * 4
    p += pad(opt_len) + pad(id_len) + pad(ty_len)
    rtype = b[i + 12 + pad(opt_len) + pad(id_len): i + 12 + pad(opt_len) + pad(id_len) + ty_len]
    recs.append((i, "MB" if (b0 & 0x10) else "", "ME" if me else "", "CF" if cf else "",
                 opt_len, id_len, ty_len, data_len, rtype))
    i = p + pad(data_len)
    if me:
        break
print("\nDIME records:", len(recs))
for r in recs:
    print("  @%06d flags=%s type=%r datalen=%d" % (r[0], "".join(r[1:4]), r[8], r[7]))

soi = b.find(b"\xff\xd8")
eoi = b.rfind(b"\xff\xd9")
print("\nJPEG in de-chunked stream: SOI@%d EOI@%d len=%d" % (soi, eoi, eoi - soi + 2))
if soi >= 0 and eoi > soi:
    open("tmp/dime-jpeg.jpg", "wb").write(b[soi:eoi + 2])
    from PIL import Image
    try:
        im = Image.open("tmp/dime-jpeg.jpg"); im.load()
        print("PIL strict decode OK:", im.size)
    except Exception as e:
        print("PIL strict decode FAIL:", e)
