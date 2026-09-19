"""Extract the scan-over-USB protocol from a scan capture.

    python tools/extract_scan_protocol.py captures/scan-otg-195230.pcap

Reassembles EP 0x03 (SOAP commands OUT) and EP 0x83 (responses + image IN)
into devkit-reference/:
  scan-commands.txt    - every full SOAP POST (headers + body)
  scan-responses.txt   - the reply headers/bodies from the scanner
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TSHARK = r"D:\Wireshark\tshark.exe"
OUT_DIR = os.path.join(ROOT, "devkit-reference")
os.makedirs(OUT_DIR, exist_ok=True)

cap = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "captures", "scan-otg-195230.pcap")


def stream_for(ep):
    res = subprocess.run(
        [TSHARK, "-r", cap, "-Y",
         "usb.endpoint_address==%s && (usb.capdata || usb.data_fragment)" % ep,
         "-T", "fields", "-e", "usb.capdata", "-e", "usb.data_fragment"],
        capture_output=True, text=True)
    raw = bytearray()
    for line in res.stdout.splitlines():
        h = (line.split("\t")[0] or (line.split("\t") + [""])[1] or "").strip()
        h = h.replace(":", "")
        if h:
            try:
                raw += bytes.fromhex(h)
            except ValueError:
                pass
    return bytes(raw)


cmds = stream_for("0x03")
resp = stream_for("0x83")
print("EP 0x03 bytes:", len(cmds), " EP 0x83 bytes:", len(resp))

# split the OUT stream into individual HTTP messages
p1 = os.path.join(OUT_DIR, "scan-commands.txt")
with open(p1, "wb") as f:
    f.write(cmds)

p2 = os.path.join(OUT_DIR, "scan-responses.bin")
with open(p2, "wb") as f:
    f.write(resp)

# quick text view of commands
with open(p1.replace(".txt", "-readable.txt"), "w",
          encoding="utf-8", errors="replace") as f:
    f.write(cmds.decode("utf-8", errors="replace"))

print("wrote", p1)
print("wrote", p2)
