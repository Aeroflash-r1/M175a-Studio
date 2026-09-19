"""Probe extra printer features: WIA scanner properties + deep XML mining.

    python tools/probe_live_endpoints.py

Safe (read-only) discovery while Windows owns the USB device:
  1. WIA device properties for the M175 scanner - ADF presence,
     supported resolutions, document handling, size ranges.
  2. Deep parse of the captured ProductConfigDyn.xml - paper paths,
     PDL languages, installed accessories.
Output: devkit-reference/extra-features/ + console summary.
"""
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "devkit-reference", "extra-features")
os.makedirs(OUT_DIR, exist_ok=True)

PS = r'''
$ErrorActionPreference = "Stop"
$dm = New-Object -ComObject WIA.DeviceManager
foreach ($d in $dm.DeviceInfos) {
    if ($d.Properties("Vendor").Value -like "*HP*" -or
        $d.DeviceID -like "*03f0*" -or $d.DeviceID -like "*03F0*") {
        "=== WIA DEVICE: " + $d.Properties("Name").Value
        "ID: " + $d.DeviceID
        foreach ($p in $d.Properties) {
            try {
                $v = $p.Value
                if ($v -is [System.Array]) {
                    $v = ($v | ForEach-Object { $_.ToString() }) -join ", "
                }
                if ("$v".Length -gt 0 -and $p.Name -ne "Port" -and
                    $p.Name -ne "Server") {
                    "{0} = {1}" -f $p.Name, $v
                }
            } catch {}
        }
    }
}
'''


def wia_probe():
    ps1 = os.path.join(OUT_DIR, "wia-probe.ps1")
    with open(ps1, "w", encoding="utf-8-sig") as f:
        f.write(PS)
    res = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", ps1],
        capture_output=True, text=True, timeout=120)
    out = res.stdout
    open(os.path.join(OUT_DIR, "wia-properties.txt"), "w",
         encoding="utf-8", errors="replace").write(out)

    print("=== WIA SCANNER PROPERTIES ===")
    interesting = ["Document Handling", "Document Handling Capabilities",
                   "Horizontal Resolution", "Vertical Resolution",
                   "Horizontal Extent", "Vertical Extent",
                   "Optical", "Sheet Feeder", "Flatbed", "Duplex",
                   "Brightness", "Contrast", "Data Type", "Name"]
    for line in out.splitlines():
        if any(k.lower() in line.lower() for k in interesting):
            print(" ", line.strip())


def deep_config():
    path = os.path.join(OUT_DIR, "ProductConfigDyn.xml")
    if not os.path.exists(path):
        return
    s = open(path, encoding="utf-8", errors="replace").read()
    print("\n=== PRODUCT CONFIG DEEP DIVE ===")
    for tag in ["ModelName", "ProductName", "SerialNumber", "FirmwareVersion",
                "MediaPath", "MediaSource", "InputTray", "OutputBin",
                "PDL", "PclWorker", "Pdl", "Language", "Localization",
                "MemorySize", "ProcessorSpeed", "BoardID", "MACAddress"]:
        for m in list(re.finditer(r"<[^<>]*:?%s>([^<]+)</" % tag, s))[:4]:
            print("  %-16s %s" % (tag, m.group(1)[:60]))


def usage_summary():
    path = os.path.join(OUT_DIR, "ProductUsageDyn.xml")
    if not os.path.exists(path):
        return
    s = open(path, encoding="utf-8", errors="replace").read()
    print("\n=== USAGE / CONSUMABLES SUMMARY ===")
    tags = ["TotalImpressions", "ColorImpressions", "MonochromeImpressions",
            "SimplexImpressions", "JammedImpressions", "MispickedImpressions",
            "FormatterColorImpressionCount", "TotalPaperOutErrors",
            "ScannerExposureCount", "ScanMediaCount", "ScanColorMediaCount",
            "ScanGrayMediaCount"]
    for tag in tags:
        m = re.search(r"<[^<>]*:?%s>(\d+)</" % tag, s)
        if m:
            print("  %-32s %s" % (tag, m.group(1)))
    print("  --- consumable blocks ---")
    for cm in re.finditer(r"<[\w-]*:?Consumable[\s\S]{0,3000}?</[\w-]*:?Consumable>", s):
        b = cm.group(0)

        def g(t):
            r = re.search(r"<[^<>]*:?%s>([^<]*)</" % t, b)
            return r.group(1) if r else ""
        lbl = (g("MarkerColorName") or g("ConsumableLabel") or
               g("ConsumableDescription") or "?")
        print("   %-12s level=%s%% state=%s classify=%s"
              % (lbl[:12], g("ConsumableRawPercentageLevelRemaining"),
                 g("ConsumableState")[:30], g("ConsumableClassify")))


if __name__ == "__main__":
    wia_probe()
    deep_config()
    usage_summary()
    print("\nSaved to", OUT_DIR)
