"""Tiny duplex test — minimal color usage (2 sheets, 1cm color chips).

    python tools/make_duplex_mini.py

Creates testpages/duplex-mini.pdf: 4 pages, mostly black text, each page
carries only a 1cm color chip (~0.05 ml toner per page vs full-bar tests).
Page plan for 2-sheet manual duplex:
  sheet1: front=1 (cyan chip), back=2 (magenta chip)
  sheet2: front=3 (yellow chip), back=4 (black chip)
"""
import fitz
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "testpages")
os.makedirs(OUT, exist_ok=True)
A4 = (595, 842)

PAGES = [
    ("PAGE 1 — SHEET 1 FRONT", (0, 1, 1)),           # cyan chip
    ("PAGE 2 — SHEET 1 BACK (pass 1)", (1, 0, 1)),   # magenta chip
    ("PAGE 3 — SHEET 2 FRONT", (1, 1, 0)),           # yellow chip
    ("PAGE 4 — SHEET 2 BACK (pass 1)", (0, 0, 0)),   # black chip
]

doc = fitz.open()
for i, (label, chip) in enumerate(PAGES):
    p = doc.new_page(width=A4[0], height=A4[1])
    p.insert_text(fitz.Point(60, 120), label, fontsize=22)
    p.insert_text(fitz.Point(60, 180),
                  "Tiny duplex test — chip is 1cm, saves toner.", fontsize=11)
    # ONE tiny 1cm chip (28.35 pt), top-left area — negligible color usage
    p.draw_rect(fitz.Rect(60, 220, 60 + 28.35, 220 + 28.35),
                color=None, fill=chip)
    p.insert_text(fitz.Point(60, 300),
                  "chip color proves page identity", fontsize=10)
    p.insert_text(fitz.Point(A4[0] - 70, A4[1] - 40), str(i + 1), fontsize=30)

path = os.path.join(OUT, "duplex-mini.pdf")
doc.save(path)
doc.close()
print("created:", path)
