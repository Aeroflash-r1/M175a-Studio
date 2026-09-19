"""Mine existing captures for features we haven't documented yet.

    python tools/extract_extra_features.py

1. Pulls the BIDI-IN stream (EP 0x89) from the big print capture - the
   Windows driver asked for /cdm/system/v1/identity, ProductConfigDyn.xml,
   ProductUsageDyn.xml, ProductStatusDyn.xml and the RESPONSES are recorded.
2. Parses scan-responses.bin for GetScannerElementsResponse - scanner
   capabilities (ADF present? true resolution list? color modes?).
3. Writes readable evidence files + prints a feature summary.
"""
import os
import re
import subprocess
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TSHARK = r"D:\Wireshark\tshark.exe"
CAP = os.path.join(ROOT, "captures", "print-session-173348.pcap")
SCAN_RESP = os.path.join(ROOT, "devkit-reference", "scan-responses.bin")
OUT_DIR = os.path.join(ROOT, "devkit-reference", "extra-features")
os.makedirs(OUT_DIR, exist_ok=True)


def ep89_stream():
    res = subprocess.run(
        [TSHARK, "-r", CAP, "-Y",
         "usb.endpoint_address==0x89 && (usb.capdata || usb.data_fragment)",
         "-T", "fields", "-e", "usb.capdata", "-e", "usb.data_fragment"],
        capture_output=True, text=True)
    raw = bytearray()
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        h = (parts[0] if len(parts) > 0 and parts[0].strip() else
             parts[1] if len(parts) > 1 else "").strip().replace(":", "")
        if h:
            try:
                raw += bytes.fromhex(h)
            except ValueError:
                pass
    return bytes(raw)


def main():
    raw = ep89_stream()
    print("BIDI IN (0x89) bytes:", len(raw))
    open(os.path.join(OUT_DIR, "bidi-in-stream.bin"), "wb").write(raw)

    text = raw.decode("latin-1")
    open(os.path.join(OUT_DIR, "bidi-in-readable.txt"), "w",
         encoding="utf-8", errors="replace").write(text)

    print("\n=== 1. DEVICE IDENTITY ===")
    # /cdm/system/v1/identity returns JSON with SerialNumber etc.
    for m in re.finditer(r'\{[^{}]*(?:[Ss]erial|Model|Firmware|UUID)[^{}]*\}',
                         text):
        s = m.group(0)
        if len(s) < 600:
            print(s[:500])
            open(os.path.join(OUT_DIR, "identity.json"), "w",
                 encoding="utf-8").write(s)
            break

    print("\n=== 2. USAGE COUNTERS (pages printed etc.) ===")
    m = re.search(r'<[^<>]*:?ProductUsageDyn[\s\S]{0,60000}?</[\w-]*:?ProductUsageDyn>', text)
    if not m:
        # fall back: find the usage payload by a known tag
        i = text.find("TotalImpressions")
        m = type("X", (), {"group": lambda self, k=0:
                           text[max(0, i - 2000):i + 60000]})()
    if m:
        seg = m.group(0)
        open(os.path.join(OUT_DIR, "ProductUsageDyn.xml"), "w",
             encoding="utf-8").write(seg)
        for tag in ["TotalImpressions", "A4EquivalentImpressions",
                    "ColorImpressions", "MonochromeImpressions",
                    "FormatterColorImpressionCount",
                    "SimplexImpressions", "JammedImpressions",
                    "MispickedImpressions"]:
            for mm in re.finditer(r"<[^<>]*%s>(\d+)</" % tag, seg):
                print("  %-38s %s" % (tag, mm.group(1)))
                break
        # consumable details
        print("  --- consumables ---")
        for cm in re.finditer(
                r"<[\w-]*:?Consumable[\s\S]{0,2000}?</[\w-]*:?Consumable>",
                seg):
            b = cm.group(0)
            def g(t, d=b):
                r = re.search(r"<[^<>]*:?%s>([^<]*)</" % t, d)
                return r.group(1) if r else ""
            print("   %s: level=%s%% marker=%s serial=%s install=%s"
                  % (g("MarkerColorName") or g("ConsumableLabel"),
                     g("ConsumableRawPercentageLevelRemaining"),
                     g("MarkerInfo")[:24],
                     g("SerialNumber"), g("InstallDate") or "n/a"))

    print("\n=== 3. PRODUCT CONFIG (model/firmware etc.) ===")
    i = text.find("ProductConfigDyn")
    if i > 0:
        seg = text[i:i + 20000]
        seg = seg[:max(seg.find("HTTP/1.1"), 1)] if "HTTP/1.1" in seg else seg
        open(os.path.join(OUT_DIR, "ProductConfigDyn.xml"), "w",
             encoding="utf-8").write(seg)
        for tag in ["ModelName", "ProductName", "SerialNumber", "FirmwareVersion",
                    "UUID", "BoardID", "MemorySize"]:
            r = re.search(r"<[^<>]*:?%s>([^<]+)</" % tag, seg)
            if r:
                print("  %-18s %s" % (tag, r.group(1)))

    print("\n=== 4. STATUS GROUPS (paper out / alerts) ===")
    i = text.find("ProductStatusDyn")
    if i > 0:
        seg = text[i:i + 12000]
        open(os.path.join(OUT_DIR, "ProductStatusDyn.xml"), "w",
             encoding="utf-8").write(seg)
        for r in re.finditer(r"<[^<>]*:?StatusCategory>([^<]+)<", seg):
            print("  status category:", r.group(1))
        for r in re.finditer(r"<[^<>]*:?LocString[^>]*>([^<]+)<", seg):
            print("  LCD string:", r.group(1))

    print("\n=== 5. SCANNER CAPABILITIES (ADF? resolutions? modes) ===")
    if os.path.exists(SCAN_RESP):
        s = open(SCAN_RESP, "rb").read().decode("latin-1")
        i = s.find("GetScannerElementsResponse")
        if i > 0:
            seg = s[i:i + 40000]
            open(os.path.join(OUT_DIR, "ScannerCapabilities.txt"), "w",
                 encoding="utf-8").write(seg)
            insrc = set(re.findall(r"<(\w+)>", seg))
            for t in ["Platen", "Adf", "Feeder", "Duplex"]:
                print("  InputSource %-8s present: %s"
                      % (t, t in seg))
            print("  resolutions:", sorted(set(
                int(x) for x in re.findall(r"<(?:X|Y|Width|Height)>(\d+)</",
                                           seg) if 50 < int(x) < 5000)[:20]))
            for cm in ["BlackAndWhite1", "Grayscale8", "RGB24", "RGB48"]:
                if cm in seg:
                    print("  color mode:", cm)


if __name__ == "__main__":
    main()
