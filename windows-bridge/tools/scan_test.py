"""Scan verification harness — every DPI and color mode, with output proof.

    python tools/scan_test.py

Uses the same WIA engine the bridge/phone path uses. Each scan is saved
to captures/scantest/ with its dimensions; PASS requires a valid image
of plausible size. Put a page on the glass first!
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.environ.setdefault("PYTHONPATH", ".")

from m175_bridge.config import load          # noqa: E402
from m175_bridge.scan.engine import scan_once  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "captures", "scantest")
os.makedirs(OUT, exist_ok=True)

CASES = [
    (75, "color"), (150, "color"), (200, "color"), (300, "color"),
    (600, "color"),
    (200, "grayscale"), (300, "grayscale"),
    (300, "binary"),
]


def main():
    cfg = load()
    results = []
    import time
    rng = sys.argv[1] if len(sys.argv) > 1 else None
    cases = CASES
    if rng:
        a, b = rng.split("-")
        cases = CASES[int(a):int(b) + 1]
    print("Put a page on the glass — starting in 15 seconds...")
    time.sleep(15)
    for dpi, color in cases:
        tag = "%s-%ddpi" % (color, dpi)
        try:
            path = scan_once(cfg, dpi=dpi, color=color)
            from PIL import Image
            with Image.open(path) as img:      # close handle before moving
                w, h = img.size
            final = os.path.join(OUT, tag + os.path.splitext(path)[1])
            os.replace(path, final)
            kb = os.path.getsize(final) // 1024
            ok = w > 500 and h > 500 and kb > 5
            print("  %-14s PASS  %dx%d px  %d KB  -> %s" %
                  (tag, w, h, kb, os.path.basename(final)))
            results.append((tag, ok, "%dx%d %dKB" % (w, h, kb)))
        except Exception as e:
            print("  %-14s FAIL  %s" % (tag, str(e)[:90]))
            results.append((tag, False, str(e)[:90]))
    print("\n=== SCAN MATRIX ===")
    for tag, ok, info in results:
        print("  %-14s %s  %s" % (tag, "PASS" if ok else "FAIL", info))
    npass = sum(1 for _, ok, _ in results if ok)
    print("  %d/%d passed" % (npass, len(results)))


if __name__ == "__main__":
    main()
