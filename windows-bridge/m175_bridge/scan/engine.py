"""Scanner engine — WIA flatbed scanning exposed as eSCL images.

Primary path: WIA 2.0 COM via pywin32. Fallback: a PowerShell WIA
script (also COM, but survives pywin32 gencache breakage).
"""
import os
import subprocess
import tempfile
import time

from ..config import TMP, SCANS

_JPEG_GUID = "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}"  # WIA_IMG_FMT_JPEG

_PS_SCAN = r"""
param([string]$OutPng, [int]$Dpi, [int]$ColorMode, [string]$DeviceId)
$dm = New-Object -ComObject WIA.DeviceManager
$dev = $null
if ($DeviceId) {
  foreach ($i in 0..($dm.DeviceInfos.Count)) {
    try { $di = $dm.DeviceInfos.Item($i) } catch { continue }
    if ($di.DeviceID -eq $DeviceId) { $dev = $di.Connect(); break }
  }
}
if (-not $dev) { $dev = $dm.DeviceInfos.Item(1).Connect() }
$item = $dev.Items.Item(1)
try { $item.Properties("6146").Value = $ColorMode } catch {}   # 1 color 2 gray 4 bw
try { $item.Properties("6147").Value = $Dpi } catch {}         # horizontal res
try { $item.Properties("6148").Value = $Dpi } catch {}         # vertical res
$img = $item.Transfer('{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}')
$img.SaveFile($OutPng)
Write-Output "SCANNED $OutPng"
"""


_PS_LIST = r"""
$dm = New-Object -ComObject WIA.DeviceManager
for ($i=1; $i -le $dm.DeviceInfos.Count; $i++) {
  $di = $dm.DeviceInfos.Item($i)
  $name = ''
  try { $name = $di.Properties('Name').Value } catch {}
  Write-Output ($di.DeviceID + '|' + $name)
}
"""


def list_scanners():
    """Return [(device_id, name)] via a timeout-protected subprocess.

    WIA/COM must never run inside a server thread: it can deadlock the
    whole bridge. A subprocess gives us isolation + a hard timeout.
    """
    try:
        import win32com.client  # noqa: F401  (probe: pywin32 present?)
    except Exception:
        pass
    script = os.path.join(TMP, "_wia_list.ps1")
    try:
        os.makedirs(TMP, exist_ok=True)
        with open(script, "w", encoding="utf-8") as f:
            f.write(_PS_LIST)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", script],
            capture_output=True, text=True, timeout=20)
        out = []
        for line in (proc.stdout or "").splitlines():
            if "|" in line:
                dev_id, name = line.split("|", 1)
                out.append((dev_id, name))
        return out
    except Exception:
        return []


def scan_once(cfg, device_id=None, dpi=None, color=None):
    """Scan the flatbed once; return path of a JPEG file (PNG fallback)."""
    dpi = int(dpi or cfg["scan_dpi"])
    color = color or cfg["scan_color"]
    cmap = {"color": 1, "grayscale": 2, "binary": 4}
    out_png = os.path.join(TMP, f"scan-{int(time.time()*1000)}.png")
    os.makedirs(TMP, exist_ok=True)

    script = os.path.join(TMP, "_wia_scan.ps1")
    with open(script, "w", encoding="utf-8") as f:
        f.write(_PS_SCAN)
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", script, out_png, str(dpi), str(cmap.get(color, 1)),
         device_id or ""],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not os.path.exists(out_png):
        raise RuntimeError("WIA scan failed: " + (proc.stderr or "")[-300:])

    # Convert to JPEG via Pillow for Android-friendly eSCL delivery
    try:
        from PIL import Image
        out_jpg = out_png[:-4] + ".jpg"
        Image.open(out_png).convert("RGB").save(out_jpg, "JPEG", quality=92)
        os.remove(out_png)
        return out_jpg
    except Exception:
        return out_png
