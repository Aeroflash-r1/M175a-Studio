"""Phone-wscn JPEG vs laptop-WIA JPEG — full structural comparison.

Answers, with the real bytes:
  * how many bytes each image has (are we getting HALF?)
  * SOF dimensions + component sampling factors
  * DHT table count/sizes (same encoder fingerprint?)
  * strict decode: OK / broken, and how many rows survive
  * first entropy desync offset
"""
import io
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MARKERS = {
    0xD8: "SOI", 0xD9: "EOI", 0xDA: "SOS", 0xC0: "SOF0", 0xC1: "SOF1",
    0xC2: "SOF2", 0xC4: "DHT", 0xDB: "DQT", 0xDD: "DRI", 0xE0: "APP0",
    0xE1: "APP1", 0xEE: "APP14", 0xFE: "COM",
}


def marker_walk(b, label):
    print("=" * 74)
    print("%s  —  %d bytes" % (label, len(b)))
    print("=" * 74)
    soi = b.find(b"\xff\xd8")
    eoi = b.rfind(b"\xff\xd9")
    print("  SOI at %d, last EOI at %d, tail after EOI: %d bytes"
          % (soi, eoi, len(b) - (eoi + 2)))
    if soi < 0 or eoi < 0:
        return
    i = soi + 2
    counts = {}
    while i + 3 < eoi:
        if b[i] != 0xFF:
            i += 1
            continue
        m = b[i + 1]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        ln = (b[i + 2] << 8) | b[i + 3]
        name = MARKERS.get(m, "FF%02X" % m)
        counts[name] = counts.get(name, 0) + 1
        if name in ("SOF0", "SOF1", "SOF2"):
            if i + 9 < len(b):
                prec = b[i + 4]
                h = (b[i + 5] << 8) | b[i + 6]
                w = (b[i + 7] << 8) | b[i + 8]
                ncomp = b[i + 9]
                print("  %s: %dx%d prec=%d comps=%d" % (name, w, h, prec, ncomp))
                p = i + 10
                for c in range(ncomp):
                    cid = b[p]; sf = b[p + 1]; tq = b[p + 2]
                    print("      comp id=%d sampling=0x%02x (%d h x %d v) quantTbl=%d"
                          % (cid, sf, sf >> 4, sf & 0x0F, tq))
                    p += 3
        if name == "DHT":
            # count how many tables are packed into this segment
            p = i + 4
            end = i + 2 + ln
            tbls = []
            while p + 17 <= end:
                tc = b[p] >> 4
                th = b[p] & 0x0F
                n = sum(b[p + 1:p + 17])
                tbls.append("T%d.%d(len=%d)" % (tc, th, n))
                p += 17 + n
            print("  DHT seg len=%d -> %s" % (ln, ", ".join(tbls)))
        if name == "SOS":
            n = b[i + 2 + ln - 1] if ln else 0
            print("  SOS at %d (len=%d, spectral=%d) entropy starts %d, %d entropy bytes"
                  % (i, ln, n, i + 2 + ln, eoi - (i + 2 + ln)))
            break
        i += 2 + ln
    print("  marker counts: %s" % counts)
    print("  DRI (restart interval) present: %s" % ("yes" if 0xDD in
          [b[k + 1] for k in range(soi, min(eoi, soi + 4000)) if b[k] == 0xFF] else "no"))


def decode_probe(path_or_bytes, label):
    raw = path_or_bytes
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        print("  strict decode: OK  %s  %dx%d" % (im.mode, im.size[0], im.size[1]))
        return
    except Exception as e:
        print("  strict decode: FAIL — %s" % e)
    try:
        ImageFile = Image
        import PIL.ImageFile as IF
        IF.LOAD_TRUNCATED_IMAGES = True
        im = Image.open(io.BytesIO(raw))
        im.load()
        px = im.convert("RGB")
        w, h = px.size
        # find how many rows match the last row (flat tail => truncated)
        last = px.getpixel((w // 2, h - 1))
        if last != (0, 0, 0) and last != (255, 255, 255):
            pass
        rows = 0
        for y in range(h - 1, -1, -1):
            if px.getpixel((w // 2, y)) == last:
                rows += 1
            else:
                break
        print("  truncated decode: %dx%d, flat tail rows = %d (%.0f%% of page)"
              % (w, h, rows, 100.0 * rows / h))
    except Exception as e:
        print("  truncated decode also failed: %s" % e)


def main():
    phone = os.path.join(ROOT, "tmp", "wire3", "dechunked.bin")
    if not os.path.exists(phone):
        print("missing", phone)
        sys.exit(1)
    pb = open(phone, "rb").read()

    # Walk DIME-ish framing like the app does: SOI .. last EOI
    soi = pb.find(b"\xff\xd8")
    eoi = pb.rfind(b"\xff\xd9")
    phone_jpeg = pb[soi:eoi + 2]
    print("phone dechunked body %d B -> JPEG slice %d B (SOI at %d)"
          % (len(pb), len(phone_jpeg), soi))
    marker_walk(phone_jpeg, "PHONE (wscn over OTG)")
    decode_probe(phone_jpeg, "phone")

    laptop = os.path.join(ROOT, "tmp", "scan-1789458291461.jpg")
    if os.path.exists(laptop):
        lb = open(laptop, "rb").read()
        marker_walk(lb, "LAPTOP (WIA, known-good)")
        decode_probe(lb, "laptop")

    wire = os.path.join(ROOT, "tmp", "wire-300.jpeg")
    if os.path.exists(wire):
        wb = open(wire, "rb").read()
        marker_walk(wb, "LAPTOP-WIRE (extracted from USB capture)")
        decode_probe(wb, "laptop-wire")


if __name__ == "__main__":
    main()
