"""Analyze the hpraw response: where framing breaks, and what size the
DIME record DECLARES (the authoritative image length).

hpraw == compression NONE, so:
    expected payload = BytesPerLine x NumberOfLines
The DIME header also carries a 32-bit declared dataLen. If declared >
received, the transport truncated; if declared == received, the printer
itself sent a short image.
"""
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "tmp", "hpraw", "raw.bin")
DEC = os.path.join(ROOT, "tmp", "hpraw", "dechunked.bin")


def strict_walk(raw, start):
    """Walk chunks strictly; return (sizes, break_offset, reason)."""
    i = start
    sizes = []
    while True:
        j = raw.find(b"\r\n", i)
        if j < 0:
            return sizes, i, "no CRLF for size line"
        line = raw[i:j]
        try:
            sz = int(line, 16)
        except ValueError:
            return sizes, i, "non-hex size line %r" % line[:40]
        if len(line) > 8:
            return sizes, i, "size line too long %r" % line[:40]
        sizes.append(sz)
        if sz == 0:
            return sizes, i, "proper 0-chunk terminator"
        data_end = j + 2 + sz
        if data_end + 2 > len(raw):
            return sizes, i, "ran out of data"
        if raw[data_end:data_end + 2] != b"\r\n":
            return sizes, i, ("chunk data not followed by CRLF (got %r)"
                              % raw[data_end:data_end + 6])
        i = data_end + 2


def main():
    raw = open(RAW, "rb").read()
    dec = open(DEC, "rb").read()
    h = raw.find(b"\r\n\r\n")
    start = h + 4
    print("raw=%d  dechunked=%d  header_end=%d" % (len(raw), len(dec), h))

    sizes, brk, reason = strict_walk(raw, start)
    print("strict walk: %d chunks, data=%d, broke at %d (%s)"
          % (len(sizes), sum(sizes), brk, reason))
    print("  last sizes: %s" % sizes[-4:])
    ctx = raw[max(0, brk - 48):brk + 80]
    print("  context around break:")
    print("   ", ctx.hex(" "))

    # does a real 0-terminator exist later?
    print("  chunks consumed so far: %d (%.2f MB)"
          % (len(sizes), sum(sizes) / 1e6))

    # --- DIME parse of the dechunked body -----------------------------
    print()
    print("=" * 70)
    print("DIME structure of the dechunked body")
    print("=" * 70)
    i = 0
    rec = 0
    while i + 12 <= len(dec) and rec < 8:
        b0 = dec[i]
        ver = b0 >> 5
        if ver != 1:
            print("  record %d: version=%d at %d — not DIME (%02x %02x %02x %02x)"
                  % (rec, ver, i, dec[i], dec[i + 1], dec[i + 2], dec[i + 3]))
            break
        mb = (b0 >> 4) & 1
        me = (b0 >> 3) & 1
        cf = (b0 >> 2) & 1
        opt = struct.unpack(">H", dec[i + 2:i + 4])[0]
        idl = struct.unpack(">H", dec[i + 4:i + 6])[0]
        typ = struct.unpack(">H", dec[i + 6:i + 8])[0]
        dlen = struct.unpack(">I", dec[i + 8:i + 12])[0]
        hdr = 12 + ((opt + 3) & ~3) + ((idl + 3) & ~3) + ((typ + 3) & ~3)
        print("  record %d @%d: MB=%d ME=%d CF=%d optLen=%d idLen=%d typeLen=%d "
              "declaredDataLen=%d" % (rec, i, mb, me, cf, opt, idl, typ, dlen))
        tstart = i + hdr
        tend = tstart + dlen
        print("      type=%r  first id bytes=%r"
              % (dec[i + hdr - typ:i + hdr - typ + 24] if typ else b"",
                 dec[tstart:tstart + 40]))
        avail = len(dec) - tstart
        print("      payload range %d..%d ; available=%d , SHORTFALL=%d"
              % (tstart, tend, avail, max(0, avail - dlen)))
        if me:
            break
        if dlen == 0:
            break
        i = tend if tend <= len(dec) else len(dec)
        if dlen in (0xFFFFFFFF,):
            break
        i = tstart + ((dlen + 3) & ~3)
        rec += 1

    # --- what the ticket SHOULD imply --------------------------------
    print()
    print("expected hpraw RGB24 300dpi: 2550 x 3507 x 3 =", 2550 * 3507 * 3)
    print("expected BytesPerLine 7650 x 3507   =", 7650 * 3507)
    print("expected padded 7652 x 3507         =", 7652 * 3507)
    print("received dechunked body             =", len(dec))
    for bpl in (7650, 7652, 7656, 7660, 7664):
        print("   bpl=%d -> %d  (delta %d)" % (bpl, bpl * 3507, len(dec) - bpl * 3507))
    # payload after the soap part
    soi = dec.find(b"\xff\xd8")
    print("SOI present:", soi)
    print("first 64 bytes of dechunked:", dec[:64].hex(" "))
    print("tail 32 bytes:", dec[-32:].hex(" "))


if __name__ == "__main__":
    main()
