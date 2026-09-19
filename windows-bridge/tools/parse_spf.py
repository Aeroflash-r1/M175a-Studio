"""Parse HP's binary Scanner Parameter File (hppls100.spf) — v2.

Observed layout: b"!@#$%" + \\0, then 12-byte slots of (u32 LE, 8x 0xFF).
The u32 stream so far looks like ASCII char codes (9,10,13,32,38,...) —
likely delimiter/filter tables. This parser:
  1. walks slots until the (u32,FFx8) pattern breaks,
  2. dumps every u32,
  3. hexdumps the tail region that breaks the pattern.
"""
import struct
import sys

PATH = (r"C:\Windows\System32\DriverStore\FileRepository"
        r"\hppasc20.inf_amd64_217c86e51e43d225\hppls100.spf")


def dump(path=PATH):
    d = open(path, "rb").read()
    print("file:", path, len(d), "bytes")
    print("magic:", d[:6])

    off = 18  # 6-byte magic + 3 header u32s (329, 75, 2126)
    vals = []
    while off + 12 <= len(d):
        u, fill = struct.unpack_from("<I", d, off)[0], d[off + 4:off + 12]
        if fill != b"\xff" * 8:
            break
        vals.append(u)
        off += 12
    print("header u32s: %d, %d, %d" % struct.unpack_from("<III", d, 6))
    print("slots parsed: %d (ends at offset %d)" % (len(vals), off))
    asc_all = "".join(chr(v) if 32 <= v < 127 else "<%d>" % v for v in vals)
    print("slot values as ascii stream:\n  %s" % asc_all)

    tail = d[off:]
    print("\ntail after slots: %d bytes" % len(tail))
    for i in range(0, min(len(tail), 512), 16):
        chunk = tail[i:i + 16]
        hexs = " ".join("%02x" % b for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print("  %06x  %s  %s" % (off + i, hexs.ljust(47), asc))


if __name__ == "__main__":
    dump(sys.argv[1] if len(sys.argv) > 1 else PATH)
