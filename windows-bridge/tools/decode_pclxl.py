"""Tokenize the captured PCLXL binary stream -> operator/attribute listing.

    python tools/decode_pclxl.py

Walks the HP PCL XL binary encoding (protocol 2.x, class 0) using the
documented data-type tags, starting after the session header line.
Output tells us the EXACT syntax the M175a accepts (verified, not guessed).
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAP = os.path.join(ROOT, "devkit-reference", "otg-print-stream.bin")

# PCL XL data-type tags (protocol 2.x binary encoding)
def u8(d, i): return d[i], i + 1
def u16(d, i): return struct.unpack_from(">H", d, i)[0], i + 2
def u32(d, i): return struct.unpack_from(">I", d, i)[0], i + 4
def s16(d, i): return struct.unpack_from(">h", d, i)[0], i + 2
def s32(d, i): return struct.unpack_from(">i", d, i)[0], i + 4

def real32(d, i):
    v = struct.unpack_from(">f", d, i)[0]
    return v, i + 4

# attribute tags: (tag -> reader name)
ATTR = {
    0xC0: ("ubyte", u8), 0xC1: ("sbyte", u8), 0xC2: ("uint16", u16),
    0xC3: ("sint16", s16), 0xC4: ("uint32", u32), 0xC5: ("sint32", s32),
    0xC6: ("real32", real32),
    0xC8: ("ubyte_array", None), 0xC9: ("uint16_array", None),
    0xCA: ("uint32_array", None),
    0xCC: ("ascii", None), 0xCD: ("xy_ubyte", None), 0xCE: ("xy_uint16", None),
    0xD0: ("xy_uint32", None), 0xD1: ("xy_real32", None),
    0xD2: ("box", None), 0xD8: ("real32_array", None),
}

# operator opcodes we care about (protocol 2.x)
OPS = {
    0x25: "BeginPage", 0x26: "EndPage", 0x2A: "SetCursor",
    0x2B: "SetPageOrigin", 0x2C: "SetMediaSource", 0x2D: "SetMediaSize",
    0x2E: "SetMediaType", 0x33: "SetColorSpace", 0x34: "SetPalette",
    0x35: "SetColorDepth", 0x3E: "SetDefaultFont", 0x3F: "SetFont",
    0x40: "SetCharScale", 0x41: "TextOut", 0x43: "BeginImage",
    0x44: "ReadImage", 0x45: "EndImage", 0x46: "NewPath", 0x47: "PaintPath",
    0x4C: "Comment", 0x50: "ROP3", 0x5B: "SetBrushOrigin",
    0x62: "BeginSession", 0x63: "EndSession", 0x65: "ReadStream",
    0x6A: "SetPen", 0x6B: "SetFillColor", 0x6D: "SetLineDash",
    0x6E: "SetPaintTxMode", 0x70: "SetCharBoldValue",
    0x74: "SetCursorRel", 0x75: "SetHalftoneMethod", 0x76: "SetCharAngle",
    0x77: "SetCharShear", 0x78: "SetSourceTxMode", 0x79: "SetLineJoin",
    0x7A: "SetLineCap", 0x7B: "SetLineDashOffset", 0x7C: "SetMiterLength",
    0x7D: "SetRop3", 0x7E: "SetCursor", 0x89: "SetOrigin", 0x8A: "SetClipMode",
    0x92: "SetCharSize", 0x94: "SetCharAttributeValue", 0x95: "SetAngle",
    0x9B: "SetColorDepth", 0xA0: "SetPageRotation", 0xA1: "SetSimpleRotation",
    0xA2: "SetPageScale", 0xA3: "SetDuplex", 0xA4: "SetDuplexPageMode",
    0xA6: "SetPageOrigin", 0xA8: "SetCompression", 0xAA: "SetDataCompOrg",
    0xF8: "two-byte-op-prefix",
}

TWO_BYTE = {
    0x40: "BeginScan", 0x41: "EndScan", 0x48: "SetScanMode",
    0x26: "SetGrayCalibration", 0x1E: "SetLineColor", 0x1F: "SetFillColor2",
    0x20: "SetCharAttributeValue2", 0x25: "SetColorTrapping",
    0x2A: "SetHalftone", 0x2B: "SetNegativePrint", 0x2C: "SetTxMode",
    0x2D: "SetDitherMatrix", 0x03: "SetRGBColor", 0x03 | 0x00: "SetRGBColor",
}

ARRAY_TYPES = {0xC8: 1, 0xC9: 2, 0xCA: 4, 0xD8: 4}

def read_value(tag, d, i):
    """Read one attribute value; returns (readable, new_index)."""
    if tag in (0xC0, 0xC1):
        return d[i], i + 1
    if tag in (0xC2, 0xC3):
        return struct.unpack_from(">H", d, i)[0], i + 2
    if tag in (0xC4, 0xC5):
        return struct.unpack_from(">I", d, i)[0], i + 4
    if tag == 0xC6:
        return struct.unpack_from(">f", d, i)[0], i + 4
    if tag in (0xC8, 0xC9, 0xCA, 0xD8):
        n, i2 = u16(d, i)
        size = ARRAY_TYPES[tag]
        raw = d[i2:i2 + n * size]
        return f"[{n} items]", i2 + n * size
    if tag == 0xCC:
        n, i2 = u16(d, i)
        return d[i2:i2 + n].decode("latin-1"), i2 + n
    if tag == 0xCD:  # xy ubyte
        return (d[i], d[i + 1]), i + 2
    if tag == 0xCE:  # xy uint16
        return struct.unpack_from(">HH", d, i), i + 4
    if tag == 0xD0:  # xy uint32
        return struct.unpack_from(">II", d, i), i + 8
    if tag == 0xD1:  # xy real32
        return struct.unpack_from(">ff", d, i), i + 8
    if tag == 0xD2:  # box: 4 reals
        return struct.unpack_from(">ffff", d, i), i + 16
    return None, i

def main():
    data = open(CAP, "rb").read()
    start = data.find(b"HP-PCL XL")
    # session header is a text line; binary starts after its newline
    i = data.find(b"\n", start) + 1
    end = data.find(b"@PJL EOJ", i)
    print(f"PCLXL binary: bytes {i}..{end} ({end-i} bytes)")
    print("=" * 70)

    out = []
    count = 0
    # PCL XL binary layout: <attr tag+value pairs> <operator byte>
    # attributes PRECEDE their operator. Tags live in 0xC0..0xFE.
    while i < end and count < 8000:
        attrs = []
        while i < end:
            tag = data[i]
            if tag in ATTR:
                val, i2 = read_value(tag, data, i + 1)
                if val is None:
                    break
                attrs.append((ATTR[tag][0], val))
                i = i2
            elif tag == 0xFF:          # alignment padding
                i += 1
            else:
                break
        if i >= end:
            break
        op = data[i]
        i += 1
        if op == 0xF8 and i < end:     # two-byte operator
            op2 = data[i]
            i += 1
            name = TWO_BYTE.get(op2, f"f8:{op2:02X}")
        else:
            name = OPS.get(op, f"op:{op:02X}")
        out.append((name, attrs))
        count += 1

    seen = {}
    for name, attrs in out:
        key = name
        if key not in seen:
            seen[key] = (0, attrs)
        n = seen[key][0] + 1
        seen[key] = (n, seen[key][1])

    print(f"{'operator':24} {'count':>6}  first-seen attributes")
    print("-" * 70)
    for name, (n, attrs) in sorted(seen.items(), key=lambda kv: -kv[1][0]):
        astr = "; ".join(f"{t}={v}" for t, v in attrs[:6])
        print(f"{name:24} {n:>6}  {astr[:90]}")

    # full linear dump of the first 120 ops
    print("\n" + "=" * 70)
    print("FIRST 120 OPERATORS IN ORDER:")
    for name, attrs in out[:120]:
        print(name, [(t, v) for t, v in attrs[:4]])

if __name__ == "__main__":
    main()
