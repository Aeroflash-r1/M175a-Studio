"""Pinpoint the EXACT byte where the phone's JPEG entropy stream breaks.

A well-formed JPEG entropy stream may only contain 0xFF followed by:
  0x00            (byte stuffing)
  0xD0..0xD7      (restart markers — only if DRI is set; it is NOT here)
Anything else inside the entropy segment is a desync.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sos_start(b):
    i = b.find(b"\xff\xd8")
    while i + 3 < len(b):
        if b[i] != 0xFF:
            i += 1
            continue
        m = b[i + 1]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        ln = (b[i + 2] << 8) | b[i + 3]
        if m == 0xDA:
            return i + 2 + ln
        i += 2 + ln
    return -1


def scan(label, b):
    print("=" * 74)
    print(label, len(b), "bytes")
    print("=" * 74)
    ent = sos_start(b)
    eoi = b.rfind(b"\xff\xd9")
    print("entropy %d .. %d (%d bytes)" % (ent, eoi, eoi - ent))
    anomalies = []
    i = ent
    while i < eoi:
        if b[i] == 0xFF:
            nxt = b[i + 1]
            if nxt != 0x00 and not (0xD0 <= nxt <= 0xD7):
                anomalies.append(i)
                if len(anomalies) <= 12:
                    ctx = b[max(0, i - 8):i + 10]
                    print("  ANOMALY at %d (%.1f%% into entropy): FF %02X | ctx %s"
                          % (i, 100.0 * (i - ent) / (eoi - ent), nxt,
                             ctx.hex(" ")))
                i += 2
                continue
        i += 1
    print("total FF-anomalies in entropy: %d" % len(anomalies))
    if anomalies:
        d = [anomalies[k + 1] - anomalies[k] for k in range(len(anomalies) - 1)]
        print("gaps between anomalies (first 20): %s" % d[:20])
    # 09 10 pairs (a DIME record header starts 0x09 0x10)
    pairs = []
    i = ent
    while i < eoi - 1:
        if b[i] == 0x09 and b[i + 1] == 0x10:
            pairs.append(i)
        i += 1
    print("0x09 0x10 pairs inside entropy: %d" % len(pairs))
    if pairs:
        print("  first offsets rel to entropy: %s" % [p - ent for p in pairs[:15]])
        d2 = [pairs[k + 1] - pairs[k] for k in range(len(pairs) - 1)]
        print("  gaps: %s" % d2[:15])
    return anomalies


def main():
    phone = os.path.join(ROOT, "tmp", "wire3", "dechunked.bin")
    pb = open(phone, "rb").read()
    pj = pb[pb.find(b"\xff\xd8"):pb.rfind(b"\xff\xd9") + 2]
    scan("PHONE wscn (CORRUPT)", pj)

    wire = os.path.join(ROOT, "tmp", "wire-300.jpeg")
    if os.path.exists(wire):
        scan("LAPTOP WIRE (CLEAN, decodes OK)", open(wire, "rb").read())

    lap = os.path.join(ROOT, "tmp", "scan-1789458291461.jpg")
    if os.path.exists(lap):
        scan("LAPTOP WIA (CLEAN, 766KB)", open(lap, "rb").read())


if __name__ == "__main__":
    main()
