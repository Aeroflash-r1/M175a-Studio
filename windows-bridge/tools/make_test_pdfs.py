"""Generate physical test PDFs for print verification.

    python tools/make_test_pdfs.py

Creates in testpages/:
  color-test.pdf   - color blocks + fine lines (verify CMY + 600dpi sharpness)
  mono-test.pdf    - pure black text/patterns (grayscale check)
  duplex-test.pdf  - 4 pages marked FRONT/BACK for manual duplex validation
"""
import fitz  # PyMuPDF
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "testpages")
os.makedirs(OUT, exist_ok=True)

A4 = (595, 842)  # points


def _new(doc):
    return doc.new_page(width=A4[0], height=A4[1])


def make_color():
    doc = fitz.open()
    p = _new(doc)
    colors = {"CYAN": (0, 1, 1), "MAGENTA": (1, 0, 1),
              "YELLOW": (1, 1, 0), "BLACK": (0, 0, 0)}
    x = 40
    for name, c in colors.items():
        p.draw_rect(fitz.Rect(x, 60, x + 110, 220), color=None,
                    fill=c)
        p.insert_text(fitz.Point(x + 12, 250), name, fontsize=14)
        x += 130
    # fine detail: 600dpi lines (~0.12pt gaps) + circles + gradient-ish steps
    y = 300
    for i in range(40):
        p.draw_line(fitz.Point(40, y + i * 0.7), fitz.Point(555, y + i * 0.7),
                    color=(0, 0, 0), width=0.1)
    p.insert_text(fitz.Point(40, 350), "600 DPI FINE-LINE TEST", fontsize=10)
    steps = 10
    for i in range(steps):
        g = i / steps
        p.draw_rect(fitz.Rect(40 + i * 52, 420, 40 + (i + 1) * 52, 560),
                    color=None, fill=(g, g, g))
    p.insert_text(fitz.Point(40, 600), "GRAY RAMP (verify banding)", fontsize=10)
    p.insert_text(fitz.Point(40, 660),
                  "COLOR TEST — check blocks are true CYAN/MAGENTA/YELLOW and "
                  "sharp edges", fontsize=11)
    doc.save(os.path.join(OUT, "color-test.pdf"))
    doc.close()


def make_mono():
    doc = fitz.open()
    p = _new(doc)
    p.insert_text(fitz.Point(40, 80), "M175a MONO TEST", fontsize=28)
    p.insert_text(fitz.Point(40, 120),
                  "If you can read this at arm's length, 600dpi text is good.",
                  fontsize=11)
    sizes = [6, 7, 8, 9, 10, 12, 16, 24]
    y = 170
    for s in sizes:
        p.insert_text(fitz.Point(50, y), f"font size {s} pt — "
                      "The quick brown fox jumps over the lazy dog 0123456789",
                      fontsize=s)
        y += s + 10
    p.draw_rect(fitz.Rect(40, y + 20, 555, y + 120), color=(0, 0, 0),
                fill=(0, 0, 0))
    p.insert_text(fitz.Point(50, y + 145), "solid black block above "
                  "(should be even, no streaks)", fontsize=10)
    doc.save(os.path.join(OUT, "mono-test.pdf"))
    doc.close()


def make_duplex():
    doc = fitz.open()
    labels = [
        ("DUPLEX TEST 1/8", "SHEET 1 FRONT (odd #1)", (1, .4, .4)),
        ("DUPLEX TEST 2/8", "SHEET 1 BACK  (even #2 - print 2nd pass)",
         (.4, 1, .4)),
        ("DUPLEX TEST 3/8", "SHEET 2 FRONT (odd #3)", (.4, .4, 1)),
        ("DUPLEX TEST 4/8", "SHEET 2 BACK  (even #4 - print 2nd pass)",
         (1, 1, .4)),
        ("DUPLEX TEST 5/8", "SHEET 3 FRONT (odd #5)", (1, .6, .2)),
        ("DUPLEX TEST 6/8", "SHEET 3 BACK  (even #6 - print 2nd pass)",
         (.2, .8, .8)),
        ("DUPLEX TEST 7/8", "SHEET 4 FRONT (odd #7)", (.8, .4, 1)),
        ("DUPLEX TEST 8/8", "SHEET 4 BACK  (even #8 - print 2nd pass)",
         (.6, 1, .6)),
    ]
    for i, (head, sub, col) in enumerate(labels):
        p = _new(doc)
        p.draw_rect(fitz.Rect(0, 0, A4[0], 140), color=None, fill=col)
        p.insert_text(fitz.Point(40, 80), head, fontsize=30)
        p.insert_text(fitz.Point(40, 220), sub, fontsize=16)
        p.insert_text(fitz.Point(40, 260),
                      f"page number in corner -> {i + 1}", fontsize=12)
        p.insert_text(fitz.Point(A4[0] - 80, A4[1] - 40), str(i + 1),
                      fontsize=36)
    doc.save(os.path.join(OUT, "duplex-test.pdf"))
    doc.close()


if __name__ == "__main__":
    make_color()
    make_mono()
    make_duplex()
    for f in sorted(os.listdir(OUT)):
        print("created:", f)
