"""Fully automated capture: USBPcap records while WE trigger the test page.

    python tools\\auto_capture.py [seconds]

Timeline: capture starts -> 4 s idle -> rundll32 printui /k fires the
Windows test page -> job flows over USB -> capture closes -> analyze.
No human timing needed.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from usb_capture import find_pcap_device, USBPCAP, CAPTURES  # noqa: E402
from analyze_pcap import analyze  # noqa: E402

PRINTER = "HP LaserJet 100 color MFP M175 PCL6"


def main():
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    dev = find_pcap_device()
    if not dev:
        print("USBPcap device not openable — reboot once and retry.")
        sys.exit(1)

    os.makedirs(CAPTURES, exist_ok=True)
    out = os.path.join(CAPTURES,
                       "auto-print-%s.pcap" % time.strftime("%H%M%S"))
    print("[1/4] recording on %s ..." % dev)
    proc = subprocess.Popen([USBPCAP, "-d", dev, "-A", "-o", out],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    time.sleep(4)

    print("[2/4] triggering TEST PAGE ourselves (printui /k)")
    subprocess.run(["rundll32", "printui.dll,PrintUIEntry",
                    "/k", "/n", PRINTER], timeout=30)

    print("[3/4] waiting %d s for the job to flow..." % (seconds - 4))
    time.sleep(max(5, seconds - 4))
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    size = os.path.getsize(out)
    print("[4/4] saved %s (%d bytes) — analyzing\n" % (out, size))
    if size < 1000:
        print("capture empty — printer asleep? print something once, retry.")
        sys.exit(1)
    analyze(out)


if __name__ == "__main__":
    main()
