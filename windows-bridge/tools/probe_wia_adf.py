"""Probe WIA for ADF/feeder presence (read-only, no scan triggered).

    python tools/probe_wia_adf.py

Prints every WIA item on the device with its ItemFlags and the
Document-Handling properties. WIA IPS facts:
  ItemFlags 64 = Feeder item, 32 = Flatbed item
  Property 3088 = Document Handling Select (1=FEEDER 2=FLATBED 4=DUPLEX)
  Property 3096 = Pages (pages to pull from feeder)
"""
import os
import subprocess
import tempfile

PS = r"""
$dm = New-Object -ComObject WIA.DeviceManager
for ($i=1; $i -le $dm.DeviceInfos.Count; $i++) {
  try { $dev = $dm.DeviceInfos.Item($i).Connect() } catch { continue }
  Write-Output ("DEVICE: " + $dev.Properties("Name").Value)
  foreach ($item in $dev.Items) {
    $flags = -1
    try { $flags = $item.Properties("ItemFlags").Value } catch {}
    Write-Output ("  ITEM: " + $item.Name + "  flags=" + $flags)
    foreach ($p in $item.Properties) {
      if ($p.PropertyID -ge 3080 -and $p.PropertyID -le 3100) {
        $v = ""
        try { $v = $p.Value } catch {}
        Write-Output ("    [" + $p.PropertyID + "] " + $p.Name + " = " + $v)
      }
    }
  }
}
"""

def main():
    script = os.path.join(tempfile.gettempdir(), "_wia_adf_probe.ps1")
    with open(script, "w", encoding="utf-8") as f:
        f.write(PS)
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
        capture_output=True, text=True, timeout=40)
    print(proc.stdout or "(no output)")
    if proc.stderr:
        print("stderr:", proc.stderr[-400:])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
