"""4-page minimal-ink probe PDF for manual-duplex + cancel testing.

    python tools/make_duplex_probe.py

Each page: large sheet/side label (so collation is obvious), a page number,
and ONE tiny 6mm colour chip (saves toner). Deliberately low ink.
"""
import os

import fitz  # PyMuPDF

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "testpages")
os.makedirs(OUT, exist_ok=True)
PATH = os.path.join(OUT, "duplex-probe-4p.pdf")
A4 = fitz.paper_rect("a4")

PAGES = [
    ("SHEET 1 - FRONT", 1, (0, 0.85, 0.85)),
    ("SHEET 1 - BACK", 2, (0.85, 0, 0.85)),
    ("SHEET 2 - FRONT", 3, (0.85, 0.85, 0)),
    ("SHEET 2 - BACK", 4, (0.4, 0.4, 0.4)),
]

doc = fitz.open()
for label, num, color in PAGES:
    page = doc.new_page(width=A4.width, height=A4.height)
    page.insert_text((60, 120), label, fontsize=30, color=(0, 0, 0))
    page.insert_text((60, 170), f"page {num} of 4", fontsize=18, color=(0, 0, 0))
    page.insert_text((60, 200), "M175a manual-duplex probe", fontsize=11,
                     color=(0.35, 0.35, 0.35))
    if num % 2 == 0:
        page.insert_text((60, 230), "this sheet was in pass 2 (odd pages)",
                         fontsize=10, color=(0.35, 0.35, 0.35))
    else:
        page.insert_text((60, 230), "this sheet was in pass 1 (even pages)",
                         fontsize=10, color=(0.35, 0.35, 0.35))
    # tiny 6mm chip - minimal toner
    page.draw_rect(fitz.Rect(60, 260, 77, 277), color=color, fill=color)

doc.save(PATH)
doc.close()
print("wrote", PATH, os.path.getsize(PATH), "bytes")
