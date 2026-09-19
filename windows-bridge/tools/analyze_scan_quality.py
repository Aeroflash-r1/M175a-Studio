"""Quantify scan quality: brightness stats + horizontal color-band detection.

    python tools/analyze_scan_quality.py path/to/scan.jpg [more.jpg ...]

Verdicts:
  - brightness: mean + p1/p99 percentiles (luma)
  - banding:    per-row mean RGB; counts distinct hue bands. A "rainbow
                stripe" scan (calibration strip / wrong region) shows few
                strong bands; a real document shows high row diversity
                with a mostly-white body.
"""
import io
import sys

from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True


def analyze(path):
    im = Image.open(path).convert("RGB")
    small = im.resize((128, 160))
    px = list(small.getdata())

    luma = [int(0.299 * r + 0.587 * g + 0.114 * b) for r, g, b in px]
    luma_sorted = sorted(luma)
    n = len(luma)
    p1 = luma_sorted[int(n * 0.01)]
    p99 = luma_sorted[int(n * 0.99)]
    mean = sum(luma) / n

    # per-row means -> color banding detection
    w, h = small.size
    bands = []
    for y in range(h):
        row = px[y * w:(y + 1) * w]
        mr = sum(p[0] for p in row) / w
        mg = sum(p[1] for p in row) / w
        mb = sum(p[2] for p in row) / w
        bands.append((mr, mg, mb))

    # classify each row into a coarse hue bucket
    def bucket(rgb):
        r, g, b = rgb
        if min(r, g, b) > 200:
            return "white"
        if max(r, g, b) < 50:
            return "black"
        mx, mn = max(r, g, b), min(r, g, b)
        if mx - mn < 25:
            return "gray"
        if r >= g and r >= b:
            return "red/yellow" if g > b else "red"
        if g >= r and g >= b:
            return "green"
        return "blue"

    seq = [bucket(b) for b in bands]
    # count band transitions (a real doc: white/black/gray transitions;
    # rainbow garbage: many saturated hue transitions)
    trans = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    from collections import Counter
    hist = Counter(seq)

    print("=" * 64)
    print(path)
    print("  size: %dx%d  brightness mean=%.0f p1=%d p99=%d"
          % (im.width, im.height, mean, p1, p99))
    print("  row-band histogram: %s" % dict(hist))
    print("  band transitions: %d/%d rows" % (trans, h))
    verdict = []
    if p99 < 40:
        verdict.append("BLACK (empty bed?)")
    elif mean < 80 and p99 > 200:
        verdict.append("mostly dark with bright stripe(s) — CALIBRATION-STRIP "
                       "signature")
    if hist.get("red", 0) + hist.get("green", 0) + hist.get("blue", 0) + \
            hist.get("red/yellow", 0) > h * 0.2:
        verdict.append("SATURATED COLOR BANDS — rainbow/strip signature")
    if not verdict and mean > 150 and p99 >= 210:
        verdict.append("looks like a normal bright document scan")
    print("  VERDICT:", " + ".join(verdict) if verdict else "check manually")
    return im


if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyze(p)
