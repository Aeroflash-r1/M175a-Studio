"""Fully automated ADF (feeder) scan capture session.

    python tools/adf_scan_session.py [dpi] [color]

1. Starts USBPcap recording
2. Triggers a REAL WIA scan with DocumentHandling=Feeder (ADF), 1 page
3. Stops recording; prints capture + result

User instruction: LOAD A PAGE IN THE FEEDER TRAY before running.
If the model has no feeder, WIA errors immediately -> that IS the answer.
"""
import os
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPTURES = os.path.join(ROOT, "captures")
USBPCAP = r"C:\Program Files\USBPcap\USBPcapCMD.exe"

PS_ADF = r"""
param([string]$OutPng, [int]$Dpi, [int]$ColorMode)
$dm = New-Object -ComObject WIA.DeviceManager
if ($dm.DeviceInfos.Count -lt 1) { throw "no WIA devices" }
$dev = $dm.DeviceInfos.Item(1).Connect()

# prefer a FEEDER item (ItemFlags 64), else use item 1
$item = $null
for ($j=1; $j -le $dev.Items.Count; $j++) {
  $it = $dev.Items.Item($j)
  $flags = 0
  try { $flags = $it.Properties("ItemFlags").Value } catch {}
  if ($flags -band 64) { $item = $it; break }
}
if (-not $item) { $item = $dev.Items.Item(1); Write-Output "NO-FEEDER-ITEM" }

# ADF selection: 3088 Document Handling Select (1=FEEDER 2=FLATBED 4=DUPLEX)
# 3096 Pages (how many sheets to pull), 3097 = pages remaining (read-only)
try { $item.Properties("3088").Value = 1; Write-Output "handling=FEEDER" }
catch { Write-Output ("3088 set failed: " + $_.Exception.Message) }
try { $item.Properties("3096").Value = 1; Write-Output "pages=1" }
catch { Write-Output ("3096 set failed: " + $_.Exception.Message) }
try { $item.Properties("6146").Value = $ColorMode } catch {}
try { $item.Properties("6147").Value = $Dpi } catch {}
try { $item.Properties("6148").Value = $Dpi } catch {}

$img = $item.Transfer('{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}')
$img.SaveFile($OutPng)
Write-Output "ADF-SCANNED $OutPng"
"""


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


def run_adf_scan(dpi, color, result):
    script = os.path.join(tempfile.gettempdir(), "_wia_adf_scan.ps1")
    with open(script, "w", encoding="utf-8") as f:
        f.write(PS_ADF)
    out_png = os.path.join(ROOT, "tmp", "adf-%d.png" % int(time.time() * 1000))
    cmap = {"color": 1, "grayscale": 2, "binary": 4}
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", script, out_png, str(dpi), str(cmap.get(color, 1))],
            capture_output=True, text=True, timeout=120)
        print("--- WIA output ---")
        print(proc.stdout or "(none)")
        if proc.returncode != 0 or not os.path.exists(out_png):
            result["error"] = (proc.stderr or proc.stdout or "no file")[-400:]
        else:
            result["path"] = out_png
    except Exception as e:
        result["error"] = str(e)


def main():
    dpi = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    color = sys.argv[2] if len(sys.argv) > 2 else "color"

    dev = find_pcap_device()
    if not dev:
        print("No USBPcap device - replug printer USB and retry.")
        return 1
    os.makedirs(CAPTURES, exist_ok=True)
    out = os.path.join(CAPTURES, "adf-scan-%s.pcap" % time.strftime("%H%M%S"))

    print("=" * 62)
    print(" ADF SCAN CAPTURE  dpi=%d color=%s" % (dpi, color))
    print("=" * 62)
    print(" >>> LOAD A PAGE IN THE FEEDER TRAY NOW! <<<")
    print(" Recording starts in 20 seconds...")
    for i in range(20, 0, -5):
        print("  %d seconds..." % i)
        time.sleep(5)

    proc = subprocess.Popen(
        [USBPCAP, "-d", dev, "-A", "-o", out],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    result = {}
    t = threading.Thread(target=run_adf_scan, args=(dpi, color, result))
    t.start()
    t.join(timeout=150)

    time.sleep(2)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    size = os.path.getsize(out) if os.path.exists(out) else 0
    print("\n ADF scan result:", result.get("path") or result.get("error"))
    print(" capture -> %s  (%d bytes)" % (out, size))
    return 0 if result.get("path") else 1


if __name__ == "__main__":
    sys.exit(main())
