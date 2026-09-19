"""Analyze ALL uploaded phone scans: integrity + channel health per file.

Produces the definitive quality map of every scan the app has produced,
keyed by time (each timestamp = a different app build / strategy era).
"""
import os
import io
from PIL import Image

DIR = "D:/m175a app logs"


def quality(path):
    name = os.path.basename(path)
    size = os.path.getsize(path)
    try:
        im = Image.open(path)
        im.load()
        w, h = im.size
        small = im.convert("RGB").resize((96, 128))
        px = list(small.getdata())
        n = len(px)
        rs = sum(p[0] for p in px) / n
        gs = sum(p[1] for p in px) / n
        bs = sum(p[2] for p in px) / n
        spread = max(rs, gs, bs) - min(rs, gs, bs)
        lum = 0.299 * rs + 0.587 * gs + 0.114 * bs
        verdict = ("CLEAN" if spread < 40 else
                   "RAINBOW" if spread >= 60 else "CAST")
        return (name[:34], size // 1024, "%dx%d" % (w, h),
                "R%03d G%03d B%03d" % (rs, gs, bs),
                "spread %3d" % spread, "lum %3d" % lum, verdict)
    except Exception as e:
        return (name[:34], size // 1024, "DECODE FAIL", str(e)[:40], "", "", "BROKEN")


rows = []
for f in sorted(os.listdir(DIR)):
    if f.lower().endswith((".jpg", ".jpeg")):
        rows.append(quality(os.path.join(DIR, f)))

print("%-34s %6s %10s %-16s %-10s %-8s %s" %
      ("file", "KB", "dims", "channel means", "spread", "lum", "verdict"))
print("-" * 100)
for r in rows:
    print("%-34s %6s %10s %-16s %-10s %-8s %s" % r)

# summary by dpi class
print("\n=== by resolution class ===")
from collections import defaultdict
cls = defaultdict(list)
for r in rows:
    try:
        w = int(r[2].split("x")[0])
        k = "600dpi" if w > 4000 else "300dpi" if w > 2000 else "200dpi"
    except Exception:
        continue
    cls[k].append(r)
for k in sorted(cls):
    spreads = [int(r[4].split()[1]) for r in cls[k]]
    verdicts = [r[6] for r in cls[k]]
    print("%s: n=%d  spread min/med/max = %d/%d/%d  verdicts=%s" % (
        k, len(spreads), min(spreads), sorted(spreads)[len(spreads) // 2],
        max(spreads), dict((v, verdicts.count(v)) for v in set(verdicts))))
