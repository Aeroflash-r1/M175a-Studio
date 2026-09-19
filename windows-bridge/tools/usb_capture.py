"""USBPcap capture controller — print & scan sessions.

    python tools\\usb_capture.py print [seconds]   (default 40)
    python tools\\usb_capture.py scan  [seconds]   (default 60)

Finds the first \\\\.\\USBPcapN control device and records raw USB traffic
to D:\\M175Bridge\\captures\\<kind>-session-<time>.pcap while you generate
a job. Then analyze with:

    python tools\\analyze_pcap.py captures\\<file>
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPTURES = os.path.join(ROOT, "captures")
USBPCAP = r"C:\Program Files\USBPcap\USBPcapCMD.exe"


def find_pcap_device():
    """Return e.g. \\\\.\\USBPcap1 for the first OPENABLE control device.

    Uses CreateFileW directly (GENERIC_READ|WRITE, exclusive) because
    Python's open() share-mode gets rejected by the control device.
    """
    import ctypes
    k32 = ctypes.windll.kernel32
    for n in range(1, 9):
        dev = "\\\\.\\USBPcap%d" % n
        h = k32.CreateFileW(dev, 0xC0000000, 0, None, 3, 0, None)
        if h not in (-1, 0xFFFFFFFFFFFFFFFF):
            k32.CloseHandle(h)
            return dev
    return None


def capture(kind, seconds):
    if not os.path.exists(USBPCAP):
        print("USBPcapCMD.exe not found — install USBPcap first.")
        sys.exit(1)
    dev = find_pcap_device()
    if not dev:
        print("No \\\\.\\USBPcapN device present yet.\n"
              "Fix: reboot once (filter attaches at hub power-up),\n"
              "or unplug+replug the printer's USB cable and retry.")
        sys.exit(1)

    os.makedirs(CAPTURES, exist_ok=True)
    out = os.path.join(CAPTURES,
                       "%s-session-%s.pcap" % (kind, time.strftime("%H%M%S")))
    print("=" * 62)
    print(" USB CAPTURE: %s  on %s  (%d s)" % (kind.upper(), dev, seconds))
    print("=" * 62)
    if kind == "print":
        print(" >>> PUT PAPER IN TRAY. Print ANY test page when I say GO.")
    else:
        print(" >>> PUT A PAGE ON THE GLASS. Scan when I say GO.")
    print(" starting in 3...")
    time.sleep(1)
    print(" 2..."); time.sleep(1)
    print(" 1..."); time.sleep(1)
    print(" >>> GO! DO THE %s NOW! <<<\n" % kind.upper())

    proc = subprocess.Popen(
        [USBPCAP, "-d", dev, "-A", "-o", out],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(seconds)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    size = os.path.getsize(out) if os.path.exists(out) else 0
    print("\n saved -> %s  (%d bytes)" % (out, size))
    if size:
        print(" next: python tools\\analyze_pcap.py \"%s\"" % out)
    else:
        print(" (empty capture — no traffic seen; replug USB and retry)")
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("print", "scan"):
        print(__doc__)
        sys.exit(1)
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else (40 if mode == "print" else 60)
    capture(mode, secs)
