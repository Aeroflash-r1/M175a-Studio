"""Dump EVERY WIA property of the M175a scanner (device + items).

    python tools/dump_wia_props.py

Goal: find gamma/LUT/calibration tables exposed by the HP driver at
runtime. WIA property IDs of interest: 1028 (Brightness), 1029
(Contrast), 1030/1031 threshold, plus any vendor-range IDs HP added.
Writes a full text report to tmp/wia-props.txt.
"""
import os
import subprocess

TMP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tmp")
os.makedirs(TMP, exist_ok=True)

PS = r'''
$ErrorActionPreference = "Stop"
$devMgr = New-Object -ComObject WIA.DeviceManager
$out = @()
foreach ($devInfo in $devMgr.DeviceInfos) {
    $out += "====================================================="
    $out += "DEVICE: " + $devInfo.DeviceID
    try { $dev = $devInfo.Connect() } catch { $out += "  connect failed: $_"; continue }
    $out += "--- device properties:"
    foreach ($p in $dev.Properties) {
        $val = ""
        try {
            if ($p.IsVector) {
                $v = $p.Value
                if ($v -is [array] -or $v.GetType().Name -like "*[]*") {
                    $arr = @($v)
                    $val = "VECTOR[" + $arr.Count + "]: " + (($arr | Select-Object -First 32) -join ",")
                    if ($arr.Count -gt 32) { $val += " ..." }
                } else { $val = "VECTOR: " + $v }
            } else { $val = [string]$p.Value }
        } catch { $val = "<unreadable>" }
        $out += ("  [{0}] {1} ({2}) = {3}" -f $p.PropertyID, $p.Name, $p.Type, $val)
        foreach ($sf in $p.SubValues) { }
    }
    foreach ($item in $dev.Items) {
        $out += "--- ITEM: " + $item.Name
        foreach ($p in $item.Properties) {
            $val = ""
            try {
                if ($p.IsVector) {
                    $v = $p.Value
                    if ($v -is [array] -or $v.GetType().Name -like "*[]*") {
                        $arr = @($v)
                        $val = "VECTOR[" + $arr.Count + "]: " + (($arr | Select-Object -First 32) -join ",")
                        if ($arr.Count -gt 32) { $val += " ..." }
                    } else { $val = "VECTOR: " + $v }
                } else { $val = [string]$p.Value }
            } catch { $val = "<unreadable>" }
            $out += ("  [{0}] {1} ({2}) = {3}" -f $p.PropertyID, $p.Name, $p.Type, $val)
        }
    }
}
$out | Out-String -Width 200
'''

ps1 = os.path.join(TMP, "_wia_props.ps1")
open(ps1, "w", encoding="utf-8").write(PS)

r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", ps1], capture_output=True, text=True, timeout=180)
out = (r.stdout or "") + (r.stderr or "")
path = os.path.join(TMP, "wia-props.txt")
open(path, "w", encoding="utf-8").write(out)

# grep for the interesting stuff right away
low = out.lower()
print("report written:", path, len(out), "bytes")
for key in ["gamma", "lut", "calib", "shading", "white", "table", "vector"]:
    n = low.count(key)
    if n:
        print("  %-10s x%d" % (key, n))
# show all vector properties (tables live in vectors)
import re
for m in re.finditer(r"^.*VECTOR\[.*$", out, re.M):
    print("  ", m.group().strip()[:160])
