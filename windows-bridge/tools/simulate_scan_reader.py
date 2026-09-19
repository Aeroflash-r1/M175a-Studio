"""Replay the captured scan session through the app reader's completion rules.

Proves the corruption bug (EOI early-exit + small-frame-gated terminator)
and validates the fixed reader against the REAL wire frames.

    python tools/simulate_scan_reader.py
"""
import re
import subprocess

PCAP = "captures/scan-otg-235137.pcap"
TSHARK = r"D:/Wireshark/tshark.exe"

out = subprocess.run(
    [TSHARK, "-r", PCAP,
     "-Y", "usb.endpoint_address == 131 && usb.transfer_type == 3 && usb.data_len > 0",
     "-T", "fields", "-e", "usb.capdata"],
    capture_output=True, text=True).stdout

frames = [bytes.fromhex(l.strip()) for l in out.splitlines() if l.strip()]
print("total frames:", len(frames))


def simulate(gate_small_only, eoi_early_exit):
    """Replay captured frames through the reader's completion rules.

    gate_small_only: old bug - terminator only checked when the USB frame
                     was <= 16 bytes (a terminator glued to a big frame
                     was missed).
    eoi_early_exit:  old bug - stop when FFD9 appears near the tail
                     (embedded EXIF thumbnails kill the read mid-image).
    """
    responses = []
    buf = bytearray()
    header_end = -1
    content_length = -1
    for f in frames:
        buf += f
        if header_end < 0:
            idx = buf.find(b"\r\n\r\n")
            if idx >= 0:
                header_end = idx
                m = re.search(rb"(?i)content-length:\s*(\d+)", bytes(buf[:idx]))
                content_length = int(m.group(1)) if m else -1
        done = False
        if header_end >= 0:
            if content_length >= 0:
                done = len(buf) >= header_end + 4 + content_length
            else:
                tail = bytes(buf[-8:])
                ok = tail.endswith(b"\r\n0\r\n\r\n")
                if gate_small_only and len(f) > 16:
                    ok = False
                if ok:
                    done = True
                elif eoi_early_exit and b"\xff\xd9" in bytes(buf[-4096:]):
                    done = True
        if done:
            responses.append(bytes(buf))
            buf = bytearray()
            header_end = -1
            content_length = -1
    return responses


new_r = simulate(False, False)
old_r = simulate(True, True)

print()
print("NEW reader: %d complete responses" % len(new_r))
for i, r in enumerate(new_r, 1):
    st = re.search(rb"HTTP/1\.1 (\d+)", r).group(1).decode()
    term = r.endswith(b"\r\n0\r\n\r\n")
    print("  resp %d: status=%s len=%d terminator=%s" % (i, st, len(r), term))
if len(new_r) >= 5:
    img = new_r[4]
    soi, eoi = img.find(b"\xff\xd8\xff"), img.rfind(b"\xff\xd9")
    print("  image response: SOI@%d EOI@%d jpeg-span=%d" % (soi, eoi, eoi - soi + 1))

print()
print("OLD reader: %d responses" % len(old_r))
for i, r in enumerate(old_r, 1):
    st = re.search(rb"HTTP/1\.1 (\d+)", r).group(1).decode()
    term = r.endswith(b"\r\n0\r\n\r\n")
    soi, eoi = r.find(b"\xff\xd8\xff"), r.rfind(b"\xff\xd9")
    span = (eoi - soi + 1) if (soi >= 0 and eoi > soi) else -1
    print("  resp %d: status=%s len=%d terminator=%s jpegSpan=%d" %
          (i, st, len(r), term, span))
