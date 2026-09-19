"""Chunk-boundary spacing analysis of the hpraw raw stream.

The printer streams chunks of 2048 data bytes framed as:
        CRLF + "800" + CRLF + 2048 bytes
=> perfect spacing between consecutive "\\r\\n800\\r\\n" markers = 2055 bytes.

Any boundary spacing != 2055 is either DROPPED bytes (shorter) or INSERTED
bytes (longer). This is the definitive byte-loss measurement.
"""
import os
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "tmp", "hpraw", "raw.bin")

MARK = b"\r\n800\r\n"
NORM = 2055


def main():
    raw = open(RAW, "rb").read()
    print("raw size", len(raw))
    pos = []
    i = raw.find(MARK)
    while i >= 0:
        pos.append(i)
        i = raw.find(MARK, i + 1)
    print("markers found:", len(pos))
    if not pos:
        return
    gaps = [pos[k + 1] - pos[k] for k in range(len(pos) - 1)]
    c = Counter(gaps)
    print("gap histogram (top 12):")
    for g, n in c.most_common(12):
        print("   gap=%6d  count=%6d   delta_vs_2055=%+d" % (g, n, g - NORM))
    odd = [(pos[k], gaps[k]) for k in range(len(gaps)) if gaps[k] != NORM]
    print("non-normal gaps: %d of %d" % (len(odd), len(gaps)))
    # cumulative drift: sum of (gap-2055) over the file
    drift = 0
    print("first 25 anomalies (abs offset, gap, drift contribution):")
    for off, g in odd[:25]:
        drift += g - NORM
        print("   @%d  gap=%d  %+d" % (off, g, g - NORM))
    total_drift = sum(g - NORM for g in gaps)
    print("TOTAL DRIFT over all gaps: %+d bytes" % total_drift)
    print("expected markers if perfect: %d" % ((len(raw) - 117) // NORM))
    print("last marker at %d ; bytes after it: %d" % (pos[-1], len(raw) - pos[-1]))
    tail = raw[pos[-1] + len(MARK):pos[-1] + len(MARK) + 40]
    print("bytes after last marker:", tail.hex(" "))


if __name__ == "__main__":
    main()
