"""Manual duplex verification (M175a has NO auto-duplex).

    python tools/duplex_test.py 1      -> prints EVEN pages reversed (pass 1)
    (user flips stack per the printed instruction)
    python tools/duplex_test.py 2      -> prints ODD pages (pass 2)

Uses testpages/duplex-test.pdf (8 pages, color-coded FRONT/BACK markers).
If collation is correct at the end: sheet1=1|2, sheet2=3|4, sheet3=5|6,
sheet4=7|8 — with backs upside-down relative to fronts (long-edge flip).
"""
import os
import sys

import fitz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "testpages", "duplex-test.pdf")
TMP = os.path.join(ROOT, "tmp")
sys.path.insert(0, os.path.join(ROOT, "tools"))

from ipp_send import send  # noqa: E402


def build_pass(pages, out_name):
    doc = fitz.open(SRC)
    out = fitz.open()
    for p in pages:
        out.insert_pdf(doc, from_page=p - 1, to_page=p - 1)
    path = os.path.join(TMP, out_name)
    out.save(path)
    out.close()
    doc.close()
    return path


def main():
    global SRC
    if not os.path.exists(SRC):
        raise SystemExit("run tools/make_test_pdfs.py first")
    which = sys.argv[1] if len(sys.argv) > 1 else "1"
    if which == "1":
        # ManualDuplexPlanner.firstPass = evens, reversed
        path = build_pass([8, 6, 4, 2], "duplex-pass1.pdf")
        print("PASS 1: printing pages 8,6,4,2 (each lands face-UP, reversed)")
        ok = send(path, "application/pdf", "DUPLEX-PASS1")
        print("\nAfter it finishes: take the 4-sheet stack AS-IS from the")
        print("output tray, flip the whole stack over like a book page")
        print("(blank sides up now), keep top edge at top, reinsert in tray.")
        print("Then run:  python tools/duplex_test.py 2")
    elif which == "2":
        path = build_pass([1, 3, 5, 7], "duplex-pass2.pdf")
        print("PASS 2: printing pages 1,3,5,7 onto the blank backs")
        ok = send(path, "application/pdf", "DUPLEX-PASS2")
        print("\nCheck collation: sheet1 = 1|2, sheet2 = 3|4,")
        print("sheet3 = 5|6, sheet4 = 7|8.")
    elif which == "mini1":
        SRC = os.path.join(ROOT, "testpages", "duplex-mini.pdf")
        path = build_pass([4, 2], "duplex-mini-pass1.pdf")
        print("MINI PASS 1: printing pages 4,2 (2 sheets, tiny color chips)")
        ok = send(path, "application/pdf", "DUPLEX-MINI-P1")
        print("\nFlip: whole stack over like a book page (blank sides up),")
        print("same edge on top, reinsert. Then: duplex_test.py mini2")
    elif which == "mini2":
        SRC = os.path.join(ROOT, "testpages", "duplex-mini.pdf")
        path = build_pass([1, 3], "duplex-mini-pass2.pdf")
        print("MINI PASS 2: printing pages 1,3 onto the blank backs")
        ok = send(path, "application/pdf", "DUPLEX-MINI-P2")
        print("\nCheck collation: sheet1 = 1|2, sheet2 = 3|4.")
    else:
        raise SystemExit("pass: 1, 2, mini1, mini2")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
