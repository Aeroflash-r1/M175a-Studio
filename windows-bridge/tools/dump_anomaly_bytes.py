"""Show the exact bytes of the printer's extra inserts at chunk boundaries.

Every anomalous gap is a multiple of 14 bytes, so the printer is injecting
14-byte units into its own chunked stream. Print them verbatim.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "tmp", "hpraw", "raw.bin")
MARK = b"\r\n800\r\n"
NORM = 2055


def main():
    raw = open(RAW, "rb").read()
    pos = []
    i = raw.find(MARK)
    while i >= 0:
        pos.append(i)
        i = raw.find(MARK, i + 1)

    shown = 0
    for k in range(len(pos) - 1):
        gap = pos[k + 1] - pos[k]
        extra = gap - NORM
        if extra <= 0 or extra % 7 != 0:
            continue
        # where the declared chunk would end:
        p = pos[k]
        declared_end = p + NORM          # start of next CRLF if framing were honest
        print("=" * 78)
        print("marker@%d gap=%d  extra=%+d (=%d x 14)" % (p, gap, extra, extra // 14))
        print("  declared boundary would be at %d" % declared_end)
        print("  bytes from declared_end (%d):" % extra)
        print("   ", raw[declared_end:declared_end + extra].hex(" "))
        print("  as text:", repr(raw[declared_end:declared_end + extra]))
        print("  24 bytes BEFORE declared_end:",
              raw[declared_end - 24:declared_end].hex(" "))
        print("  24 bytes AFTER the extra:",
              raw[declared_end + extra:declared_end + extra + 24].hex(" "))
        shown += 1
        if shown >= 6:
            break

    # Look at the most common single value
    from collections import Counter
    c = Counter()
    for k in range(len(pos) - 1):
        gap = pos[k + 1] - pos[k]
        if NORM < gap <= NORM + 1000:
            c[gap - NORM] += 1
    print()
    print("extra-value histogram:", sorted(c.items()))


if __name__ == "__main__":
    main()
