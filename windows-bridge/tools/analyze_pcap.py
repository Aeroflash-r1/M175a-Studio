"""USBPcap analyzer — decodes HP PML status/toner from captured USB traffic.

    python tools\\analyze_pcap.py captures\\print-session-XXXXXX.pcapng

Pipeline:
  1. tshark (ships with Wireshark) extracts USB bulk payloads.
  2. We separate OUT (PC -> printer, PML SET / print data) from
     IN (printer -> PC, PML GETRESP with OID + value).
  3. Toner OIDs live under 1.3.6.1.2.1.43.11.1.1 (prtMarkerSupplies):
     ...9.1 = max capacity, ...9.2 = current level. We scan for those
     byte patterns inside IN payloads and print percentages.
  4. Findings are written to captures\\pml_findings.json, which the
     bridge loads on startup to report REAL toner/status to phones.
"""
import json
import os
import re
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPTURES = os.path.join(ROOT, "captures")
TSHARK = (r"D:\Wireshark\tshark.exe"
          if os.path.exists(r"D:\Wireshark\tshark.exe")
          else r"C:\Program Files\Wireshark\tshark.exe")

PML_HEAD = bytes([0x1B, 0x25, 0x2D, 0x31, 0x32, 0x33, 0x34, 0x35])  # ESC%-12345
TONER_BASE = b"\x2b\x80\x86\xe0\x2b\x0b\x01\x01"  # 1.3.6.1.2.1.43.11.1.1 tail


def payloads(pcap):
    """Yield (direction, bytes) for USB bulk data from tshark.

    Uses both usb.capdata and usb.data_fragment (field name varies by
    Wireshark version / desegmentation state). Direction from usb.src:
    'host' as source = OUT (PC -> printer), anything else = IN.
    """
    out = subprocess.run(
        [TSHARK, "-r", pcap, "-T", "fields",
         "-e", "usb.src", "-e", "usb.dst", "-e", "usb.capdata",
         "-e", "usb.data_fragment"],
        capture_output=True, text=True, timeout=300)
    for line in (out.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        src, dst = parts[0], parts[1]
        hexdata = parts[2] or parts[3]
        if not hexdata:
            continue
        try:
            blob = bytes.fromhex(hexdata.replace(":", ""))
        except ValueError:
            continue
        direction = "OUT" if src == "host" else "IN"
        yield direction, blob


def parse_pml_in(blob):
    """Extract (oid_tuple, value_int) pairs from a PML GETRESP."""
    results = []
    # PML reply: <OID length><OID bytes><value-tag 0x21/0x05><len><value>
    i = blob.find(TONER_BASE)
    while i != -1:
        start = max(0, i - 4)
        oid = blob[start:i + 8]
        tail = blob[i + 8:]
        if len(tail) >= 4:
            # try to find a plausible 32-bit big-endian value nearby
            for off in (0, 2, 3, 4):
                if len(tail) >= off + 4:
                    val = struct.unpack(">I", tail[off:off + 4])[0]
                    if 0 <= val <= 100000:
                        results.append((oid.hex(), val))
                        break
        i = blob.find(TONER_BASE, i + 1)
    return results


def parse_pml_out(blob):
    """Find OIDs the PC asked for (SET/GET) — useful for status mapping."""
    oids = []
    for m in re.finditer(rb"\x06[\x01-\x0f]((?:\x2b|\x2e)[\x80-\xff]\x86)",
                         blob):
        oids.append(m.group(0).hex())
    return oids


def parse_ledm_xml(blobs):
    """Reassemble IN-side fragments and extract HP LEDM consumable data.

    The M175a runs an embedded HTTP server over USB (HP LEDM):
    /DevMgmt/ProductUsageDyn.xml carries per-supply levels.
    """
    import re
    text = b"".join(blobs)
    findings = {"toner": {}, "other_supplies": {}}
    # Per-consumable blocks: color + type + remaining percentage
    blocks = text.split(b"<pudyn:Consumable>")
    for blk in blocks[1:]:
        color = re.search(rb"<dd:MarkerColor>([A-Za-z]+)</dd:MarkerColor>", blk)
        ctype = re.search(rb"<dd:ConsumableTypeEnum>([a-zA-Z]+)"
                          rb"</dd:ConsumableTypeEnum>", blk)
        level = re.search(rb"<dd:ConsumableRawPercentageLevelRemaining>"
                          rb"(\d+)</dd:ConsumableRawPercentageLevelRemaining>",
                          blk)
        if not (color and level):
            continue
        val = int(level.group(1))
        if val == 255:            # 255 = supply not installed
            continue
        name = color.group(1).decode().lower()
        if ctype and ctype.group(1).lower() == b"toner":
            findings["toner"][name] = val
        else:
            key = (ctype.group(1).decode().lower() if ctype
                   else "supply") + "_" + name
            findings["other_supplies"][key] = val
    # Printer state from ProductStatusDyn if present
    m = re.search(rb"<Status>([^<]{1,60})</Status>", text)
    if m:
        findings["printer_status"] = m.group(1).decode(errors="replace")
    return findings


def analyze(pcap):
    findings = {"toner": {}, "status_oids": [], "pages": 0}
    counts = {"OUT": 0, "IN": 0}
    in_blobs = []
    print("reading %s ..." % pcap)
    for direction, blob in payloads(pcap):
        counts[direction] += 1
        if direction == "IN":
            if len(blob) > 60:
                in_blobs.append(blob)
        else:
            if PML_HEAD in blob or b"@PJL " in blob:
                for o in parse_pml_out(blob):
                    if o not in findings["status_oids"]:
                        findings["status_oids"].append(o)
            if (b"\x1b" in blob and b"*p" in blob) or b"PJL PAGE" in blob:
                findings["pages"] += 1
    ledm = parse_ledm_xml(in_blobs)
    findings.update(ledm)
    print("  bulk packets: OUT=%d IN=%d" % (counts["OUT"], counts["IN"]))
    if ledm.get("toner"):
        print("  REAL toner levels: %s" % ledm["toner"])
    if ledm.get("other_supplies"):
        print("  other supplies: %s" % ledm["other_supplies"])
    if ledm.get("printer_status"):
        print("  printer status: %s" % ledm["printer_status"])

    os.makedirs(CAPTURES, exist_ok=True)
    out_json = os.path.join(CAPTURES, "pml_findings.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2)
    print("  saved ->", out_json)
    print("  (bridge picks this up next start — real toner on your phone)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    analyze(sys.argv[1])
