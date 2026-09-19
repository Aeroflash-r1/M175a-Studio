"""JPEG marker-level diff: native printer output vs WIA (HP-driver-processed) output.

If the ONLY differences are color-interpretation markers (SOF component IDs,
APP14 Adobe transform, JFIF APP0), then HP's 'repair' is a metadata flip and
standard decoders misread the planes — the rainbow mystery, solved exactly.
"""
import os
import sys

TMP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tmp")

FILES = {
    "NATIVE-200 (printer raw, same session)": os.path.join(TMP, "native-200dpi.jpg"),
    "WIA-200 (after HP driver, same session)": os.path.join(TMP, "scan-1789418962818.jpg"),
    "NATIVE-300 (capture 235137)": os.path.join(TMP, "native-300dpi.jpg"),
    "NATIVE-300 (capture 195230)": os.path.join(TMP, "native-300dpi-195230.jpg"),
}

MARKERS = {
    0xC0: "SOF0 baseline", 0xC1: "SOF1", 0xC2: "SOF2 progressive",
    0xC4: "DHT", 0xDB: "DQT", 0xDD: "DRI",
    0xE0: "APP0", 0xE1: "APP1", 0xE2: "APP2", 0xEC: "APP12", 0xEE: "APP14",
    0xFE: "COM",
}


def parse(path):
    out = []
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] != b"\xff\xd8":
        return ["NOT A JPEG"], 0
    i = 2
    n = len(data)
    while i < n - 1:
        if data[i] != 0xFF:
            i += 1
            continue
        m = data[i + 1]
        if m in (0xD8, 0xD9):
            out.append((m, None))
            i += 2
            if m == 0xD9:
                break
            continue
        if 0xD0 <= m <= 0xD7 or m == 0x01 or m == 0xFF:
            i += 2
            continue
        if i + 4 > n:
            break
        seglen = (data[i + 2] << 8) | data[i + 3]
        seg = data[i + 4:i + 2 + seglen]
        out.append((m, seg))
        i += 2 + seglen
        if m == 0xDA:  # SOS: skip entropy data to next marker
            while i < n - 1:
                if data[i] == 0xFF and data[i + 1] not in (0x00,) and not (0xD0 <= data[i + 1] <= 0xD7):
                    break
                i += 1
    return out, n


def describe(m, seg):
    name = MARKERS.get(m, "0x%02X" % m)
    if seg is None:
        return name
    s = "%s len=%d" % (name, len(seg))
    if m in (0xC0, 0xC1, 0xC2) and len(seg) >= 6:
        prec = seg[0]
        h = (seg[1] << 8) | seg[2]
        w = (seg[3] << 8) | seg[4]
        nc = seg[5]
        comps = []
        for c in range(nc):
            off = 6 + c * 3
            cid = seg[off]
            samp = seg[off + 1]
            comps.append("id=0x%02X(%r) samp=%dx%d q=%d" % (
                cid, chr(cid) if 32 <= cid < 127 else ".",
                samp >> 4, samp & 15, seg[off + 2]))
        s += " %dx%d prec=%d comps[%d]: %s" % (w, h, prec, nc, " | ".join(comps))
    elif m == 0xE0:
        s += " " + seg[:16].hex() + " " + repr(seg[:16])
    elif m == 0xEE:  # Adobe
        s += " " + repr(seg[:12]) + " transform=" + (str(seg[-1]) if seg else "?")
    elif m == 0xDB:
        s += " tables=%d" % (len(seg) // 65 if len(seg) % 65 == 0 else -1)
    elif m == 0xFE:
        s += " " + repr(seg[:40])
    return s


def main():
    parsed = {}
    for label, path in FILES.items():
        if not os.path.exists(path):
            print("== %s == MISSING: %s" % (label, path))
            continue
        segs, total = parse(path)
        parsed[label] = segs
        print("== %s == (%d bytes)" % (label, total))
        for m, seg in segs:
            print("   ", describe(m, seg))
        print()

    # Structural diff of the two same-session files
    keys = [k for k in parsed if "NATIVE-200" in k or "WIA-200" in k]
    if len(keys) == 2:
        a, b = parsed[keys[0]], parsed[keys[1]]
        print("=" * 60)
        print("SEGMENT DIFF: %s vs %s" % (keys[0], keys[1]))
        print("=" * 60)
        la, lb = len(a), len(b)
        for i in range(max(la, lb)):
            sa = describe(*a[i]) if i < la else "<none>"
            sb = describe(*b[i]) if i < lb else "<none>"
            ma = a[i][0] if i < la else None
            mb = b[i][0] if i < lb else None
            same = (ma == mb) and (a[i][1] == b[i][1])
            flag = "SAME" if same else "DIFF"
            print("[%s] A: %s" % (flag, sa))
            if not same:
                print("       B: %s" % sb)


if __name__ == "__main__":
    main()
