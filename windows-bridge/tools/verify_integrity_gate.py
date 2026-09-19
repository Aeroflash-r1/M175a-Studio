"""End-to-end verification on the laptop (printer attached).

    python tools/verify_integrity_gate.py [n_scans]

1. Runs N fresh REAL 300 dpi color scans through WIA (the printer).
2. Applies the APP'S EXACT integrity-gate rules to each result:
     - decodes at all?
     - decoded size == header size (truncation check)?
     - channel spread >= 60            -> corrupt (rainbow)
     - >= 2 flat bands AND spread >= 35 -> corrupt (flat saturated / fill)
3. Applies the same rules to KNOWN-CORRUPT artifacts so we prove the gate
   discriminates (clean scans must PASS, corrupt bytes must FAIL).

Reports a single table: scan # | dims | spread | flat | gate verdict.
"""
import io
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONPATH", ".")

SAMPLE_DIM = 128
OUT = os.path.join(ROOT, "tmp", "integrity-gate-verification.txt")


def gate(jpeg_bytes, label):
    """Exact port of ScanAutoLevels.fix()'s integrity gate."""
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    try:
        im = Image.open(io.BytesIO(jpeg_bytes))
        declared = im.size
        im.load()
        decoded = im.size
        if decoded != declared:
            return (label, declared, decoded, "-", "-", "CORRUPT (truncated decode)")
    except Exception as e:
        return (label, "-", "-", "-", "-", "CORRUPT (will not decode)")
    im = im.convert("RGB")
    small = im.resize((SAMPLE_DIM, SAMPLE_DIM))
    px = list(small.getdata())
    n = len(px)
    mr = sum(p[0] for p in px) / n
    mg = sum(p[1] for p in px) / n
    mb = sum(p[2] for p in px) / n
    spread = round(max(mr, mg, mb) - min(mr, mg, mb))
    # flat bands: 8 bands of 16 rows, variance < 50 counts as flat
    flat = 0
    band_n = (SAMPLE_DIM // 8) * SAMPLE_DIM
    for band in range(8):
        sub = px[band * band_n:(band + 1) * band_n]
        ar = sum(p[0] for p in sub) / band_n
        ag = sum(p[1] for p in sub) / band_n
        ab = sum(p[2] for p in sub) / band_n
        v = sum((p[0] - ar) ** 2 + (p[1] - ag) ** 2 + (p[2] - ab) ** 2 for p in sub) / band_n
        if v < 50:
            flat += 1
    corrupt = spread >= 60 or (flat >= 2 and spread >= 35)
    verdict = "CORRUPT (spread>=60)" if spread >= 60 else (
        "CORRUPT (flat bands + spread)" if corrupt else "PASS (clean)")
    return (label, declared, decoded, spread, flat, verdict)


def scan_once(cfg, result):
    try:
        from m175_bridge.scan.engine import scan_once as do_scan
        result["path"] = do_scan(cfg, dpi=300, color="color")
    except Exception as e:
        result["error"] = str(e)


def main():
    n_scans = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    from m175_bridge.config import load
    cfg = load()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    rows = []
    with open(OUT, "a", encoding="utf-8") as f:
        def emit(s):
            print(s, flush=True)
            f.write(s + "\n")
            f.flush()

        emit("=" * 74)
        emit(" INTEGRITY-GATE END-TO-END VERIFICATION — %s"
             % time.strftime("%Y-%m-%d %H:%M:%S"))
        emit("=" * 74)
        emit(">>> page face-down on the glass, lid closed — starting in 10 s <<<")
        time.sleep(10)

        emit("\n--- FRESH REAL SCANS (300 dpi color, via the printer) ---")
        for k in range(1, n_scans + 1):
            r = {}
            t = threading.Thread(target=scan_once, args=(cfg, r))
            t.start()
            t.join(timeout=120)
            path = r.get("path")
            if not path or not os.path.exists(path):
                emit("scan %d: WIA failed: %s" % (k, r.get("error")))
                continue
            with open(path, "rb") as fh:
                data = fh.read()
            row = gate(data, "real scan #%d" % k)
            rows.append(row)
            emit("  %-14s dims %sx%s  spread %s  flat %s  -> %s"
                 % (row[0], row[1][0], row[1][1], row[3], row[4], row[5]))
            time.sleep(4)

        emit("\n--- KNOWN-CORRUPT ARTIFACTS (gate must FAIL these) ---")
        samples = [
            ("tmp/wire-300.jpeg", "corrupt wire JPEG (USBPcap-loss stream)"),
            ("tmp/wire-payload.bin", "raw de-chunked payload (DIME+JPEG, not a file)"),
        ]
        for rel, label in samples:
            p = os.path.join(ROOT, rel)
            if not os.path.exists(p):
                emit("  %-40s (missing)" % label)
                continue
            with open(p, "rb") as fh:
                data = fh.read()
            row = gate(data, label)
            emit("  %-40s -> %s" % (label, row[5]))

        emit("\n--- SUMMARY ---")
        clean = [r for r in rows if r[5].startswith("PASS")]
        emit("  fresh real scans: %d | gate PASS: %d | gate FAIL: %d"
             % (len(rows), len(clean), len(rows) - len(clean)))
        emit("  false positives on clean scans: %d (must be 0)"
             % (len(rows) - len(clean)))
        emit("  full log: %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
