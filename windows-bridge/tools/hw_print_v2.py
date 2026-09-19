"""HARDWARE TEST of the v2 OTG encoder.

    python tools/hw_print_v2.py

1. Draws a real test image with PIL (text + CMY chips + fine lines).
2. Builds the PCLXL stream using the SAME byte layout as the app's v2
   PclxlPage.kt (via validate_pclxl_encoder.build_stream).
3. RAW-prints it through the Windows spooler (datatype RAW) -> the exact
   bytes go to the printer's USB print endpoint.
4. PASS = a clean page in the tray (no PCL XL error).
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from PIL import Image, ImageDraw  # noqa: E402
from validate_pclxl_encoder import build_stream  # noqa: E402

DPI = 300
W, H = 2480, 3508  # A4 @300dpi


def make_test_jpeg():
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((150, 120), "M175a OTG ENCODER V2 TEST", fill="black")
    d.text((150, 220), "300 dpi - color chips + fine lines", fill="black")
    colors = [(0, 255, 255), (255, 0, 255), (255, 255, 0), (0, 0, 0)]
    x = 150
    for c in colors:
        d.rectangle([x, 350, x + 400, 650], fill=c)
        x += 450
    for i in range(60):
        y = 800 + i * 6
        d.line([150, y, W - 150, y], fill="black", width=2)
    d.text((150, 1300), "If you can read this without a PCLXL error, "
                        "the v2 encoder is FIXED.", fill="black")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def raw_print(data: bytes) -> bool:
    """Send bytes to the Windows printer queue as datatype RAW."""
    import win32print
    PRINTER = win32print.EnumPrinters(
        win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
    name = None
    for p in PRINTER:
        if "M175" in p[2] or "HP" in p[2].upper():
            name = p[2]
            break
    if not name:
        print("No HP printer queue found:", [p[2] for p in PRINTER])
        return False
    print("Queue:", name)
    h = win32print.OpenPrinter(name)
    try:
        job = win32print.StartDocPrinter(h, 1, ("OTG-V2-TEST", None, "RAW"))
        win32print.StartPagePrinter(h)
        win32print.WritePrinter(h, data)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)
    print("RAW job submitted:", len(data), "bytes")
    return True


def main():
    jpeg = make_test_jpeg()
    print("test jpeg:", len(jpeg), "bytes  (%dx%d)" % (W, H))
    stream = build_stream([jpeg], page_w=W, page_h=H, dpi=DPI,
                          grayscale=False, job_name="OTG-V2")
    out = os.path.join(ROOT, "devkit-reference", "otg-v2-hwtest.bin")
    open(out, "wb").write(stream)
    print("stream:", len(stream), "bytes ->", out)
    ok = raw_print(stream)
    print("RESULT:", "SUBMITTED - check the page in the tray!" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
