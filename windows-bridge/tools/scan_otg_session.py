"""Fully automated scan-over-OTG capture session.

    python tools/scan_otg_session.py [dpi] [color]

1. Starts USBPcap recording (\\.\\USBPcap1)
2. Triggers a REAL scan via WIA (same engine the phone path uses)
3. Waits for the scan to finish, stops recording
4. Prints the output pcap path + scan result

User instruction: put a page on the glass BEFORE running.
"""
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONPATH", ".")

CAPTURES = os.path.join(ROOT, "captures")
USBPCAP = r"C:\Program Files\USBPcap\USBPcapCMD.exe"


def find_pcap_device():
    """Return e.g. \\\\.\\USBPcap1 for the first OPENABLE control device."""
    import ctypes
    k32 = ctypes.windll.kernel32
    for n in range(1, 9):
        dev = "\\\\.\\USBPcap%d" % n
        h = k32.CreateFileW(dev, 0xC0000000, 0, None, 3, 0, None)
        if h not in (-1, 0xFFFFFFFFFFFFFFFF):
            k32.CloseHandle(h)
            return dev
    return None


def run_scan(cfg, dpi, color, result):
    """Trigger one WIA scan in this process; capture success/error."""
    try:
        from m175_bridge.scan.engine import scan_once
        path = scan_once(cfg, dpi=dpi, color=color)
        result["path"] = path
    except Exception as e:
        result["error"] = str(e)


def main():
    dpi = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    color = sys.argv[2] if len(sys.argv) > 2 else "color"

    from m175_bridge.config import load
    cfg = load()

    dev = find_pcap_device()
    if not dev:
        print("No USBPcap device present - replug printer USB and retry.")
        return 1

    os.makedirs(CAPTURES, exist_ok=True)
    out = os.path.join(CAPTURES,
                       "scan-otg-%s.pcap" % time.strftime("%H%M%S"))

    print("=" * 62)
    print(" SCAN-OVER-OTG CAPTURE  dpi=%d color=%s" % (dpi, color))
    print(" device: %s" % dev)
    print("=" * 62)
    print(" >>> PUT THE PAGE ON THE GLASS NOW! <<<")
    print(" Recording starts in 20 seconds...")
    for i in range(20, 0, -5):
        print("  %d seconds..." % i)
        time.sleep(5)

    proc = subprocess.Popen(
        [USBPCAP, "-d", dev, "-A", "-o", out],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)  # recorder warm-up

    result = {}
    t = threading.Thread(target=run_scan, args=(cfg, dpi, color, result))
    t.start()
    t.join(timeout=90)  # WIA scan + warmup typically 15-60s

    # give trailing status packets a moment, then stop the recorder
    time.sleep(2)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    size = os.path.getsize(out) if os.path.exists(out) else 0
    print("\n scan result:", result.get("path") or result.get("error"))
    print(" capture  -> %s  (%d bytes)" % (out, size))
    if size > 1000:
        print("\n next: python tools/analyze_pcap.py \"%s\"" % out)
        return 0
    print(" (capture too small - retry or replug USB)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
