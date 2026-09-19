"""HARDWARE TEST - multi-page PCL XL session (the path the fixed app uses).

    python tools/hw_print_multipage.py

Prints 3 TINY pages (1cm color chips, toner economy) in ONE PCL XL session:
  BeginSession/OpenDataSource + [BeginPage..EndPage]x3 + CloseDataSource/EndSession

PASS = all 3 pages in the tray, no PCL XL error page.
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


def tiny_page(label: str) -> bytes:
    """Mostly-white page: header + one ~1cm chip. Toner-frugal on purpose."""
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((150, 120), "MULTI-PAGE TEST - PAGE %s" % label, fill="black")
    d.text((150, 220), "single PCL XL session, 3 BeginPage blocks", fill="black")
    chip = {"1": (0, 255, 255), "2": (255, 0, 255), "3": (0, 0, 0)}[label]
    d.rectangle([150, 350, 228, 428], fill=chip)  # ~78px = ~1cm at 300dpi
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def raw_print(data: bytes):
    import win32print
    queues = win32print.EnumPrinters(
        win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
    name = None
    for p in queues:
        if "M175" in p[2] or "HP" in p[2].upper():
            name = p[2]
            break
    if not name:
        print("No HP queue found:", [p[2] for p in queues])
        return False
    print("Queue:", name)
    h = win32print.OpenPrinter(name)
    try:
        win32print.StartDocPrinter(h, 1, ("OTG-MULTIPAGE", None, "RAW"))
        win32print.StartPagePrinter(h)
        win32print.WritePrinter(h, data)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)
    print("RAW job submitted:", len(data), "bytes")
    return True


def main():
    pages = [tiny_page("1"), tiny_page("2"), tiny_page("3")]
    print("pages:", [len(p) for p in pages], "bytes (JPEG each)")
    stream = build_stream(pages, page_w=W, page_h=H, dpi=DPI,
                          grayscale=False, job_name="OTG-MULTIPAGE")
    out = os.path.join(ROOT, "devkit-reference", "otg-multipage-hwtest.bin")
    with open(out, "wb") as f:
        f.write(stream)
    print("stream:", len(stream), "bytes ->", out)
    ok = raw_print(stream)
    print("RESULT:", "SUBMITTED - 3 pages should land in the tray"
          if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
