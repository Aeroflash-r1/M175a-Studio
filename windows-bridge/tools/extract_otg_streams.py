"""Extract complete USB OUT streams from captures for the Android OTG app.

    python tools/extract_otg_streams.py

Produces in devkit-reference/:
  otg-print-stream.bin     - full raw PJL+PCLXL job as sent to EP 0x01
  otg-bidi-http-requests.txt - every HTTP request sent over BIDI EP 0x09
  otg-stream-summary.txt   - human-readable summary of both
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAP = os.path.join(ROOT, "captures", "print-session-173348.pcap")
OUT_DIR = os.path.join(ROOT, "devkit-reference")
os.makedirs(OUT_DIR, exist_ok=True)
TSHARK = r"D:\Wireshark\tshark.exe"

if not os.path.exists(CAP):
    # fall back to newest capture
    import glob
    caps = sorted(glob.glob(os.path.join(ROOT, "captures", "*.pcap*")),
                  key=os.path.getmtime)
    CAP = caps[-1]

print("Using capture:", CAP)

# pull every data-bearing frame: number, endpoint, payload hex
res = subprocess.run(
    [TSHARK, "-r", CAP, "-Y", "usb.capdata || usb.data_fragment",
     "-T", "fields", "-e", "frame.number", "-e", "usb.endpoint_address",
     "-e", "usb.capdata", "-e", "usb.data_fragment"],
    capture_output=True, text=True)

ep01 = bytearray()   # print stream (bulk OUT to printer)
ep09 = bytearray()   # BIDI OUT (HTTP requests)
counts = {"0x01": 0, "0x09": 0, "0x89": 0, "0x81": 0, "other": 0}

for line in res.stdout.splitlines():
    parts = line.split("\t")
    if len(parts) < 4:
        continue
    ep = parts[1].strip()
    hexdata = (parts[2] or parts[3] or "").strip().replace(":", "")
    if not hexdata:
        continue
    try:
        raw = bytes.fromhex(hexdata)
    except ValueError:
        continue
    if ep == "0x01":
        ep01 += raw
        counts["0x01"] += 1
    elif ep == "0x09":
        ep09 += raw
        counts["0x09"] += 1
    elif ep in ("0x89", "0x81"):
        counts[ep] += 1
    else:
        counts["other"] += 1

# 1. full print stream
p1 = os.path.join(OUT_DIR, "otg-print-stream.bin")
with open(p1, "wb") as f:
    f.write(ep01)

# 2. BIDI HTTP requests, pretty split
p2 = os.path.join(OUT_DIR, "otg-bidi-http-requests.txt")
with open(p2, "w", encoding="utf-8", errors="replace") as f:
    for req in ep09.split(b"\r\n\r\n"):
        if req.strip():
            f.write(req.decode("utf-8", errors="replace") + "\n" + "-" * 60 + "\n")

# 3. summary — first 900 bytes of print stream as text
head = ep01[:900].decode("latin-1")
with open(p1 + ".head.txt", "w", encoding="utf-8") as f:
    f.write(head)

print("EP packet counts:", counts)
print("print stream size:", len(ep01), "bytes ->", p1)
print("bidi http bytes  :", len(ep09), "bytes ->", p2)
print("done.")
