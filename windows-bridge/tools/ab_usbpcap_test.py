"""A/B: is USBPcap recording the corruptor?

  python tools/ab_usbpcap_test.py

Phase A (no recording): 3x real 300 dpi WIA scans -> check WIA's own JPEG.
Phase B (recording on): 3x same scans -> check WIA's JPEG + the wire payload.
If A is always clean and B corrupts, USBPcap drops bytes under load and all
'wire corruption' conclusions must be re-framed as capture artifacts.
"""
import io
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONPATH", ".")

CAPTURES = os.path.join(ROOT, "captures")
RESULTS = os.path.join(ROOT, "tmp", "ab-usbpcap-results.txt")
USBPCAP = r"C:\Program Files\USBPcap\USBPcapCMD.exe"
DPI = 300


def find_pcap_device():
    import ctypes
    k32 = ctypes.windll.kernel32
    for n in range(1, 9):
        dev = "\\\\.\\USBPcap%d" % n
        h = k32.CreateFileW(dev, 0xC0000000, 0, None, 3, 0, None)
        if h not in (-1, 0xFFFFFFFFFFFFFFFF):
            k32.CloseHandle(h)
            return dev
    return None


def one_scan(cfg, result):
    try:
        from m175_bridge.scan.engine import scan_once
        result["path"] = scan_once(cfg, dpi=DPI, color="color")
    except Exception as e:
        result["error"] = str(e)


def check_jpeg(path):
    from PIL import Image, ImageFile
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:
        return "BROKEN (%s)" % e
    im = im.convert("RGB")
    W, H = im.size
    # variance profile: flat saturated bands = corrupt entropy
    bands, flat = 8, []
    for b in range(bands):
        crop = im.crop((0, H * b // bands, W, H * (b + 1) // bands)).resize((64, 16))
        px = list(crop.getdata())
        n = len(px)
        mr = sum(p[0] for p in px) / n
        mg = sum(p[1] for p in px) / n
        mb = sum(p[2] for p in px) / n
        var = sum((p[0] - mr) ** 2 + (p[1] - mg) ** 2 + (p[2] - mb) ** 2 for p in px) / n
        if var < 50:
            flat.append(b)
    return "CLEAN %s" % (im.size,) if not flat else "CLEAN decode but flat bands %s" % flat


def main():
    from m175_bridge.config import load
    cfg = load()
    dev = find_pcap_device()
    if not dev:
        print("FATAL: no USBPcap device")
        return 1
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)

    with open(RESULTS, "a", encoding="utf-8") as res:
        def emit(s):
            print(s, flush=True)
            res.write(s + "\n")
            res.flush()

        emit("=" * 60)
        emit(" USBPcap A/B — %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
        emit("=" * 66)
        emit(">>> PAGE FACE-DOWN, LID CLOSED — starting in 15 s <<<")
        for i in range(15, 0, -5):
            emit("  %d s..." % i)
            time.sleep(5)

        for phase, record in (("A no-recording", False), ("B recording", True)):
            for k in range(1, 4):
                pcap = os.path.join(CAPTURES, "ab-%s-%d.pcap" % (phase[0], k))
                proc = None
                if record:
                    proc = subprocess.Popen([USBPCAP, "-d", dev, "-A", "-o", pcap],
                                            stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL)
                    time.sleep(3)
                result = {}
                t = threading.Thread(target=one_scan, args=(cfg, result))
                t.start()
                t.join(timeout=120)
                time.sleep(2)
                if proc:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                path = result.get("path")
                wia_state = check_jpeg(path) if path and os.path.exists(path) \
                    else "WIA failed: %s" % result.get("error")
                emit("%s round %d: WIA file -> %s" % (phase, k, wia_state))
                time.sleep(5)

        emit("Done. If all A rounds are CLEAN and B rounds corrupt, USBPcap is the corruptor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
