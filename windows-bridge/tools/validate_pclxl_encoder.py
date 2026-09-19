"""Mirror of the Android app's PclxlPage.kt encoder (corrected layout).

    python tools/validate_pclxl_encoder.py

Generates devkit-reference/otg-test-stream.bin using the SAME byte layout
as the Kotlin code, then disassembles it with HP's pxldis.py.

Wire layout (verified against the real capture):
  - little-endian values (')' binding): 600 = 58 02
  - VALUE bytes come BEFORE their attr_ubyte selector:
      D1 58 02 58 02 F8 89  =  uint16_xy(600,600) UnitsPerMeasure
  - ubyte_array value: C8 + length-value + bytes + selector:
      C8 C0 02 41 34 F8 25  =  "A4" MediaSize
"""
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "devkit-reference", "otg-test-stream.bin")
PXLDIS = os.path.join(ROOT, "tmp", "pxldis.py")

# --- low-level writers (mirror Kotlin: value BEFORE selector) ---
def u8(v): return bytes([v & 0xFF])
def u16(v): return struct.pack("<H", v & 0xFFFF)
def u32(v): return struct.pack("<I", v & 0xFFFFFFFF)
def sel(n): return b"\xF8" + bytes([n])
# data-type tags prefix the value bytes (protocol 3)
T_UBYTE, T_UINT16, T_REAL32 = 0xC0, 0xC1, 0xC5
T_UBYTE_ARRAY, T_SINT16_XY, T_UINT16_XY, T_REAL32_XY = 0xC8, 0xD3, 0xD1, 0xD5
def ubyte_attr(n, v): return u8(T_UBYTE) + u8(v) + sel(n)
def uint16_attr(n, v): return u8(T_UINT16) + u16(v) + sel(n)
def real32xy_attr(n, x, y):
    return u8(T_REAL32_XY) \
         + u32(struct.unpack("<I", struct.pack("<f", x))[0]) \
         + u32(struct.unpack("<I", struct.pack("<f", y))[0]) + sel(n)
def uint16xy_attr(n, x, y): return u8(T_UINT16_XY) + u16(x) + u16(y) + sel(n)
def sint16xy_attr(n, x, y): return u8(T_SINT16_XY) + u16(x) + u16(y) + sel(n)
def ubyte_array_attr(n, d):
    if len(d) < 256:
        lenval = u8(T_UBYTE) + u8(len(d))
    else:
        lenval = u8(T_UINT16) + u16(len(d))
    return u8(T_UBYTE_ARRAY) + lenval + d + sel(n)

A_UNITS_PER_MEASURE, A_MEASURE, A_ERROR_REPORT = 137, 134, 143
A_SOURCE_TYPE, A_DATA_ORG = 136, 130
A_MEDIA_SOURCE, A_ORIENTATION, A_MEDIA_SIZE = 38, 40, 37
A_PAGE_ORIGIN, A_PAGE_SCALE, A_COLOR_SPACE = 42, 43, 3
A_TX_MODE, A_ROP3 = 45, 44
A_COLOR_MAPPING, A_COLOR_DEPTH = 100, 98
A_SOURCE_WIDTH, A_SOURCE_HEIGHT, A_DESTINATION_SIZE = 108, 107, 103
A_START_LINE, A_BLOCK_HEIGHT, A_COMPRESS_MODE = 109, 99, 101


def build_stream(pages_jpeg, page_w, page_h, dest_w=4760, dest_h=6735,
                 dpi=600, grayscale=False, job_name="M175-OTG"):
    out = bytearray()
    out += b"\x1B%-12345X@PJL SET RET=ON\r\n"
    out += b'@PJL JOB NAME="' + job_name.encode() + b'"\r\n'
    out += b"@PJL SET STRINGCODESET=UTF8\r\n"
    out += b"@PJL SET RESOLUTION=%d\r\n" % dpi
    out += (b"@PJL SET GRAYSCALE=" + (b"ON" if grayscale else b"OFF") + b"\r\n")
    out += b"@PJL SET BITSPERPIXEL=8\r\n"
    out += b"@PJL ENTER LANGUAGE=PCLXL\r\n"
    out += b") HP-PCL XL;3;0;Comment M175-OTG-Android\r\n"

    out += uint16xy_attr(A_UNITS_PER_MEASURE, dpi, dpi)
    out += ubyte_attr(A_MEASURE, 0)
    out += ubyte_attr(A_ERROR_REPORT, 3)
    out += u8(0x41)                                   # BeginSession
    out += ubyte_attr(A_SOURCE_TYPE, 0)
    out += ubyte_attr(A_DATA_ORG, 1)
    out += u8(0x48)                                   # OpenDataSource

    for jpeg in pages_jpeg:
        out += ubyte_attr(A_MEDIA_SOURCE, 1)
        out += ubyte_attr(A_ORIENTATION, 0)
        out += ubyte_array_attr(A_MEDIA_SIZE, b"A4")
        out += u8(0x43)                               # BeginPage
        out += sint16xy_attr(A_PAGE_ORIGIN, 100, 100)
        out += u8(0x75)                               # SetPageOrigin
        # v2: unified-cursor block (ops 5-7) — REQUIRED, was the PCLXL error
        out += ubyte_attr(30, 0) + u8(0x7E)           # SetNeutralAxis Text=0
        out += ubyte_attr(32, 1) + u8(0x7E)           # SetNeutralAxis Raster=1
        out += ubyte_attr(31, 0) + u8(0x7E)           # SetNeutralAxis Vector=0
        out += ubyte_attr(30, 2) + ubyte_attr(31, 2) + ubyte_attr(32, 2)
        out += u8(0x6D)                               # SetHalftoneMethod (per-class!)
        out += ubyte_attr(29, 1) + u8(0x94)           # SetAdaptiveHalftoning
        out += ubyte_attr(29, 2) + u8(0x92)           # SetColorTrapping
        out += ubyte_attr(120, 1) + u8(0x58)          # SetColorTreatment
        out += real32xy_attr(A_PAGE_SCALE, 1.0, 1.0)
        out += u8(0x77)                               # SetPageScale
        out += ubyte_attr(A_COLOR_SPACE, 1 if grayscale else 2)
        out += u8(0x6A)                               # SetColorSpace
        out += ubyte_attr(A_TX_MODE, 0)
        out += u8(0x78)                               # SetPatternTxMode
        out += ubyte_attr(A_TX_MODE, 0)
        out += u8(0x7C)                               # SetSourceTxMode
        out += ubyte_attr(A_ROP3, 204)
        out += u8(0x7B)                               # SetROP
        out += u8(0x61)                               # PushGS
        out += u8(0x69)                               # SetClipToPage
        # v2: in-context cursor + paint setup (ops 19-23)
        out += sint16xy_attr(76, 0, 40) + u8(0x6B)    # SetCursor (0,40)
        out += ubyte_attr(A_TX_MODE, 0) + u8(0x78)    # SetPatternTxMode
        out += ubyte_attr(A_TX_MODE, 0) + u8(0x7C)    # SetSourceTxMode
        out += ubyte_attr(A_ROP3, 204) + u8(0x7B)     # SetROP
        out += ubyte_attr(A_COLOR_SPACE, 1 if grayscale else 2) + u8(0x6A)
        out += ubyte_attr(A_COLOR_MAPPING, 0)
        out += ubyte_attr(A_COLOR_DEPTH, 2)
        out += uint16_attr(A_SOURCE_WIDTH, page_w)
        out += uint16_attr(A_SOURCE_HEIGHT, page_h)
        out += uint16xy_attr(A_DESTINATION_SIZE, dest_w, dest_h)
        out += u8(0xB0)                               # BeginImage
        out += uint16_attr(A_START_LINE, 0)
        out += uint16_attr(A_BLOCK_HEIGHT, page_h)
        out += ubyte_attr(A_COMPRESS_MODE, 2)         # JPEG
        out += u8(0xB1)                               # ReadImage
        out += b"\xFA" + u32(len(jpeg)) + jpeg        # embedded_data
        out += u8(0xB2)                               # EndImage
        out += u8(0x60)                               # PopGS
        out += u8(0x44)                               # EndPage

    out += u8(0x49)                                   # CloseDataSource
    out += u8(0x42)                                   # EndSession
    out += b"\x1B%-12345X@PJL EOJ NAME=\"" + job_name.encode() + b'"\r\n'
    out += b"\x1B%-12345X\r\n"
    return bytes(out)


REQUIRED = ["BeginSession", "OpenDataSource", "BeginPage", "EndPage",
            "BeginImage", "ReadImage", "EndImage", "CloseDataSource",
            "EndSession", "SetPageOrigin", "SetPageScale", "SetColorSpace",
            "SetSourceTxMode", "SetROP", "PushGS", "SetClipToPage", "PopGS"]


def main():
    fake_jpeg = b"\xFF\xD8\xFF\xE0" + b"\x00" * 256 + b"\xFF\xD9"
    data = build_stream([fake_jpeg], page_w=2380, page_h=3368)
    with open(OUT, "wb") as f:
        f.write(data)
    print("wrote", OUT, len(data), "bytes")

    res = subprocess.run([sys.executable, PXLDIS, OUT],
                         capture_output=True, text=True)
    dis = res.stdout
    if not dis.strip():
        print("DISASSEMBLER PRODUCED NOTHING — encoding broken")
        print(res.stderr[:1500])
        return 1

    # show disassembled op lines
    for l in dis.splitlines():
        s = l.strip()
        if s in REQUIRED or s.startswith("// Op Pos"):
            print("  ", s)

    missing = [r for r in REQUIRED if r not in dis]
    if missing:
        print("\nMISSING OPERATORS:", missing)
        return 1
    print("\nALL REQUIRED OPERATORS PRESENT — Kotlin encoder layout verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
