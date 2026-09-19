"""Hardware print test WITH back-channel error verification.

    python tools/hw_print_v2_verified.py

1. Starts USBPcap recording.
2. RAW-prints the v2 test stream (same bytes as the app sends).
3. Stops recording, decodes the BIDI IN (EP 0x89) back-channel.
4. PASS = no PCLXL error report from the printer's interpreter.
"""
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
TSHARK = r"D:\Wireshark\tshark.exe"
USBPCAP = r"C:\Program Files\USBPcap\USBPcapCMD.exe"

from hw_print_v2 import make_test_jpeg, raw_print  # noqa: E402
from validate_pclxl_encoder import build_stream    # noqa: E402


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


def main():
    jpeg = make_test_jpeg()
    stream = build_stream([jpeg], page_w=2480, page_h=3508, dpi=300,
                          grayscale=False, job_name="OTG-V2-VER")
    dev = find_pcap_device()
    if not dev:
        print("no USBPcap device")
        return 1
    cap = os.path.join(ROOT, "captures",
                       "v2-verify-%s.pcap" % time.strftime("%H%M%S"))
    print("recording", dev)

    proc = subprocess.Popen([USBPCAP, "-d", dev, "-A", "-o", cap],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    time.sleep(2)
    raw_print(stream)
    time.sleep(12)   # let the printer parse + respond on the back-channel
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()

    size = os.path.getsize(cap)
    print("capture:", size, "bytes")

    # decode BIDI IN back-channel
    res = subprocess.run(
        [TSHARK, "-r", cap, "-Y",
         "usb.endpoint_address==0x89 && (usb.capdata || usb.data_fragment)",
         "-T", "fields", "-e", "usb.capdata", "-e", "usb.data_fragment"],
        capture_output=True, text=True)
    back = bytearray()
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        h = (parts[0] or (parts[1] if len(parts) > 1 else "") or "").strip()
        h = h.replace(":", "")
        if h:
            try:
                back += bytes.fromhex(h)
            except ValueError:
                pass
    print("back-channel bytes:", len(back))
    text = back.decode("latin-1", "replace")

    errs = []
    for pat in [r"(?i)pcl[_ ]?xl", r"(?i)error", r"(?i)illegal",
                r"(?i)SubSystem", r"(?i)kerlib"]:
        for m in re.finditer(pat, text):
            s = max(0, m.start() - 60)
            errs.append(text[s:m.end() + 120].replace("\r\n", " | "))
    # dedupe
    seen, uniq = set(), []
    for e in errs:
        if e not in seen:
            seen.add(e)
            uniq.append(e)

    if uniq:
        print("\n!!! PRINTER REPORTED ERRORS ON BACK-CHANNEL:")
        for e in uniq[:5]:
            print("   ...", e[:200])
        return 1
    print("\nNO PCLXL ERROR REPORTS ON BACK-CHANNEL -> stream parsed CLEAN")
    return 0


if __name__ == "__main__":
    import re
    sys.exit(main())
