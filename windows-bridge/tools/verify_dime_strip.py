"""THE test: does the scan payload carry interleaved DIME record headers?

If the printer emits the image as a DIME record CHAIN (12-byte header +
2048 data, repeated), then the app's SOI..EOI slice INCLUDES those 12-byte
headers every 2048 bytes -> Huffman desync -> the rainbow page.

Strip them and the JPEG should decode perfectly.
"""
import io
import os
from collections import Counter

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# internal record header seen in the real wire bytes: b0=09 b1=00, opt=0,id=0,type=0, len=2048
PAT = bytes.fromhex("090000000000000000000800")
PAT2 = bytes.fromhex("091000000000000000000800")   # outer variant (b1=10)


def positions(b, pat):
    out = []
    i = b.find(pat)
    while i >= 0:
        out.append(i)
        i = b.find(pat, i + 1)
    return out


def report(label, path):
    b = open(path, "rb").read()
    print("=" * 74)
    print("%s  (%d bytes)" % (label, len(b)))
    print("=" * 74)
    for pat, nm in ((PAT, "09 00..08 00"), (PAT2, "09 10..08 00")):
        p = positions(b, pat)
        print("  %s : %d matches" % (nm, len(p)))
        if len(p) > 2:
            g = Counter(p[k + 1] - p[k] for k in range(len(p) - 1))
            print("      top gaps: %s" % g.most_common(5))
            print("      first: %s" % p[:6])
    return b


def jpeg_body(b):
    soi = b.find(b"\xff\xd8")
    eoi = b.rfind(b"\xff\xd9")
    return soi, eoi


def try_decode(raw, label):
    try:
        im = Image.open(io.BytesIO(raw)); im.load()
        print("   %s -> DECODE OK %s %dx%d" % (label, im.mode, im.size[0], im.size[1]))
        return True
    except Exception as e:
        print("   %s -> decode FAIL: %s" % (label, e))
        return False


def strip_and_test(b, pats):
    """Remove every 12-byte record header from the image and re-evaluate."""
    soi = b.find(b"\xff\xd8")
    eoi = b.rfind(b"\xff\xd9")
    img = b[soi:eoi + 2]
    print("  raw SOI..EOI slice: %d bytes" % len(img))
    try_decode(img, "as-is")
    out = bytearray()
    pos = 0
    removed = 0
    # remove only headers that sit on the expected chain (12 + 2048 cadence)
    while pos < len(img):
        here = -1
        for pat in pats:
            if img[pos:pos + len(pat)] == pat:
                here = 1
                break
        if here == 1:
            pos += 12
            removed += 1
            continue
        out.append(img[pos])
        pos += 1
    print("  removed %d record headers" % removed)
    try_decode(bytes(out), "after header strip")
    return bytes(out)


def main():
    print("PHONE 300dpi jfif scan (the rainbow one)")
    b = report("jfif dechunked body", os.path.join(ROOT, "tmp", "wire3", "dechunked.bin"))
    strip_and_test(b, [PAT, PAT2])

    print()
    print("HPRAW scan")
    b2 = report("hpraw dechunked body", os.path.join(ROOT, "tmp", "hpraw", "dechunked.bin"))


if __name__ == "__main__":
    main()
