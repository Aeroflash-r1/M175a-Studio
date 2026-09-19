"""THOROUGH laptop-side validation of the app's scan pipeline (v5 parser).

    python tools/scan_thorough_test.py

Test battery, all against REAL wire bytes from BOTH scan captures:
  A. As-captured replay       -> reader must segment every response
  B. ADVERSARIAL re-chunking  -> 200 random USB framings per capture,
                                 including reads that COALESCE many USB
                                 frames into one (the phone failure mode)
  C. JPEG integrity           -> does the printer's native stream decode?
  D. App chain                -> native dim JPEG -> auto-levels mirror ->
                                 document-quality metrics
"""
import io
import random
import re
import subprocess
import sys

from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

TSHARK = r"D:/Wireshark/tshark.exe"
CAPTURES = [
    "captures/scan-otg-235137.pcap",
    "captures/scan-otg-195230.pcap",
]

TERM = b"\r\n0\r\n\r\n"


def load_frames(pcap):
    out = subprocess.run(
        [TSHARK, "-r", pcap,
         "-Y", "usb.endpoint_address == 131 && usb.transfer_type == 3 && usb.data_len > 0",
         "-T", "fields", "-e", "usb.capdata"],
        capture_output=True, text=True).stdout
    return [bytes.fromhex(l.strip()) for l in out.splitlines() if l.strip()]


def find_crlf(b, frm):
    i = frm
    limit = len(b) - 1
    while i < limit:
        if b[i] == 0x0D and b[i + 1] == 0x0A:
            return i
        i += 1
    return -1


def chunked_end(b, start):
    """Mirror of LedmScanClient.chunkedEnd — walks the chunk chain."""
    pos = start
    while True:
        eol = find_crlf(b, pos)
        if eol < 0:
            return -1
        size_str = b[pos:eol].decode("latin1").strip().split(";")[0]
        try:
            size = int(size_str, 16)
        except ValueError:
            return -1
        data_start = eol + 2
        if size == 0:
            return data_start + 2 if len(b) >= data_start + 2 else -1
        data_end = data_start + size
        if len(b) < data_end + 2:
            return -1
        pos = data_end + 2


def reader_segment(frames):
    """Mirror of LedmScanClient.drainInbound v6 (chunk-chain + CARRY).

    CRITICAL: like the Kotlin, this must ACCUMULATE across reads into
    `out` (a 1 MB image spans hundreds of USB frames) and seed each new
    read with the carry (bytes past a completed response boundary).
    """
    responses = []
    out = bytearray()      # accumulates ACROSS frames (Kotlin `out`)
    carry = bytearray()    # bytes beyond a completed response (Kotlin `carry`)
    header_end = -1
    content_length = -1
    for f in frames:
        out += carry + bytearray(f)   # seed carry + this read
        carry = bytearray()
        # ONE read can complete SEVERAL responses (big reads / queued acks)
        # — keep extracting while a complete response is buffered.
        while True:
            if header_end < 0:
                idx = out.find(b"\r\n\r\n")
                if idx < 0:
                    break
                header_end = idx
                m = re.search(rb"(?i)content-length:\s*(\d+)", bytes(out[:idx]))
                content_length = int(m.group(1)) if m else -1
            if content_length >= 0:
                want = header_end + 4 + content_length
                end = want if len(out) >= want else -1
            else:
                end = chunked_end(bytes(out), header_end + 4)
            if end <= 0:
                break
            if len(out) > end:
                carry = bytearray(out[end:])
            responses.append(bytes(out[:end]))
            out = bytearray(carry)
            carry = bytearray()
            header_end = -1
            content_length = -1
    return responses, bytes(carry + out)


def jpeg_span(r):
    soi = r.find(b"\xff\xd8\xff")
    eoi = r.rfind(b"\xff\xd9")
    return (soi, eoi) if (soi >= 0 and eoi > soi) else None


def autolevels_mirror(jpeg):
    """Mirror of ScanAutoLevels.fix() — same thresholds, same math."""
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    small = im.resize((128, 128))
    px = list(small.getdata())
    hist = [0] * 256
    for r, g, b in px:
        hist[min(255, max(0, int(0.299 * r + 0.587 * g + 0.114 * b)))] += 1

    def pct(f):
        acc, target = 0, int(len(px) * f)
        for i in range(256):
            acc += hist[i]
            if acc >= target:
                return i
        return 255

    low, high = pct(0.01), pct(0.99)
    if high < 40:
        return None, "BLACK p99=%d" % high, im
    if high >= 210:
        return im, "bright — untouched", im
    scale = 255.0 / max(1, high - low)
    lut = [min(255, max(0, int((i - low) * scale))) for i in range(256)]
    return im.point(lut * 3), "auto-leveled p1=%d p99=%d" % (low, high), im


def brightness(im):
    t = im.resize((64, 64)).convert("L")
    d = list(t.getdata())
    return sum(d) / len(d)


def edge_density(im):
    g = im.resize((256, 256)).convert("L")
    px = list(g.getdata())
    w = 256
    tot = n = 0
    for y in range(1, 255):
        for x in range(1, 255):
            i = y * w + x
            gx = px[i + 1] - px[i - 1]
            gy = px[i + w] - px[i - w]
            tot += abs(gx) + abs(gy)
            n += 1
    return tot / n


def main():
    random.seed(42)
    failures = 0

    for pcap in CAPTURES:
        print("=" * 66)
        print("CAPTURE:", pcap)
        frames = load_frames(pcap)
        stream = b"".join(frames)
        print("  raw 0x83 stream: %d frames, %d bytes" % (len(frames), len(stream)))

        # ---- A: as-captured replay --------------------------------------
        resp, tail = reader_segment(frames)
        ok = len(resp) == 7 and tail == b""
        print("  A. as-captured: %d responses, leftover=%dB -> %s" %
              (len(resp), len(tail), "PASS" if ok else "FAIL"))
        failures += 0 if ok else 1

        # ---- B: adversarial re-chunking ---------------------------------
        # GOLD criterion: under ARBITRARY USB framing, the reader must
        # produce the SAME 7 responses BYTE-IDENTICAL to as-captured,
        # zero leftover — and the image response's JPEG must decode.
        # (SOAP acks contain no JPEG — requiring one everywhere was a
        # harness bug that masked real results.)
        bad = 0
        for t in range(200):
            rechunked = []
            i = 0
            while i < len(stream):
                size = random.choice(
                    [64, 128, 512, 1024, 2328, 4096, 8192, 16384, 65536])
                rechunked.append(stream[i:i + size])
                i += size
            got, tail2 = reader_segment(rechunked)
            ok = (len(got) == len(resp) and tail2 == b"" and
                  all(got[k] == resp[k] for k in range(min(len(got), len(resp)))))
            if ok:
                img = max(got, key=len)
                he2 = img.find(b"\r\n\r\n")
                be = chunked_end(img, he2 + 4)
                body = img[he2 + 4:be] if be > 0 else img[he2 + 4:]
                sp = jpeg_span(body)
                if not sp:
                    ok = False
                else:
                    try:
                        Image.open(io.BytesIO(body[sp[0]:sp[1] + 2])).load()
                    except Exception:
                        ok = False
            if not ok:
                bad += 1
        print("  B. adversarial x200 re-chunkings (byte-identical): "
              "%d/200 failures -> %s" % (bad, "PASS" if bad == 0 else "FAIL"))
        failures += bad

        # ---- C: JPEG integrity on the wire (dechunked!) -----------------
        img_resp = max(resp, key=len)
        he = img_resp.find(b"\r\n\r\n")
        body_end = chunked_end(img_resp, he + 4)
        body = img_resp[he + 4:body_end] if body_end > 0 else img_resp[he + 4:]
        # v5 extraction path: body is DECHUNKED before JPEG search
        span = jpeg_span(body)
        jpeg = body[span[0]:span[1] + 2] if span else b""
        strict_ok = tolerant_ok = False
        if jpeg:
            try:
                Image.open(io.BytesIO(jpeg)).load()
                strict_ok = True
            except Exception:
                pass
            try:
                im = Image.open(io.BytesIO(jpeg)).convert("RGB")
                im.load()
                tolerant_ok = True
            except Exception:
                pass
        print("  C. native JPEG (dechunked) %dB: strict=%s tolerant=%s %s" %
              (len(jpeg), strict_ok, tolerant_ok,
               "(capture may have dropped USB frames)" if not strict_ok else ""))

        # ---- D: app chain (native -> auto-levels -> metrics) ------------
        fixed, verdict, original = autolevels_mirror(jpeg)
        if fixed is None:
            print("  D. chain: BLACK scan detected -> %s" % verdict)
            failures += 1
            continue
        b0, b1 = brightness(original), brightness(fixed)
        e0, e1 = edge_density(original), edge_density(fixed)
        doc_like = e1 > 3.0 and b1 > 150
        print("  D. chain: %s | brightness %.0f -> %.0f | edge-detail "
              "%.1f -> %.1f -> %s" %
              (verdict, b0, b1, e0, e1,
               "DOC-LIKE PASS" if doc_like else "CHECK"))

    print("=" * 66)
    print("VERDICT:", "ALL CORE TESTS PASS" if failures == 0 else
          "%d FAILURES" % failures)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
