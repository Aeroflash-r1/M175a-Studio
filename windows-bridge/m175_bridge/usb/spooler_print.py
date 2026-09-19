"""Windows-side printing through the installed HP driver + spooler.

The Windows spooler owns the USB port and the HP PDL pipeline, so the
bridge submits jobs to it like any Windows app would. Every job is also
archived under captures/jobs so tools/analyze_pcap.py can correlate an
IPP job from the phone with the real USB traffic later.
"""
import json
import os
import subprocess
import time

from ..config import CAPTURES, TMP

JOB_ARCHIVE = os.path.join(CAPTURES, "jobs")
_PRINTER_CACHE = {"name": None}

# Status reported to phones; PML analysis (from USBPcap dumps) upgrades this.
STATUS = {
    "state": "idle",          # idle | printing | offline | error
    "detail": "Ready",
    "toner": {"black": -1, "cyan": -1, "magenta": -1, "yellow": -1},
    "jobs_sent": 0,
    "last_job": None,         # ISO-ish timestamp of last submitted job
}


def find_printer(cfg):
    """Return the Windows printer name to submit to (auto-detect M175 family)."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Printer | Select-Object -ExpandProperty Name"],
        capture_output=True, text=True, timeout=30,
    )
    names = [n.strip() for n in (out.stdout or "").splitlines() if n.strip()]
    want = (cfg.get("printer_name") or "").strip()
    if want:
        for n in names:
            if want.lower() in n.lower():
                return n
    keys = ("m175", "cm1415", "cp1525", "laserjet pro", "mfp m175")
    for n in names:
        low = n.lower()
        if any(k in low for k in keys):
            return n
    return names[0] if names else None


def print_file(path, printer, job_name="M175Bridge Job"):
    """Submit a PDF/PS/RAW file to the spooler; archive + update status."""
    os.makedirs(JOB_ARCHIVE, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archived = os.path.join(JOB_ARCHIVE, f"{stamp}-{os.path.basename(path)}")
    with open(path, "rb") as src, open(archived, "wb") as dst:
        dst.write(src.read())

    # RAW copy: direct-to-port via WinSpool, bypasses driver re-render
    helper = os.path.join(JOB_ARCHIVE, "_rawsend.ps1")
    with open(helper, "w", encoding="utf-8") as f:
        f.write(_RAWSEND_PS1 + "\n")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", helper, printer, archived],
        capture_output=True, text=True, timeout=180,
    )
    ok = proc.returncode == 0
    STATUS["state"] = "idle" if ok else "error"
    STATUS["detail"] = "Printed" if ok else ("Spooler error: " +
                                             (proc.stderr or "").strip()[:120])
    if ok:
        STATUS["jobs_sent"] += 1
        STATUS["last_job"] = stamp
    return ok


_RAWSEND_PS1 = """
param([string]$Printer, [string]$File)
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public class WinSpool {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Ansi)]
  public class DOCINFOA {
    [MarshalAs(UnmanagedType.LPStr)] public string pDocName;
    [MarshalAs(UnmanagedType.LPStr)] public string pOutputFile;
    [MarshalAs(UnmanagedType.LPStr)] public string pDataType;
  }
  [DllImport("winspool.Drv", EntryPoint="OpenPrinterA", SetLastError=true,
    CharSet=CharSet.Ansi)]
  public static extern bool OpenPrinter([MarshalAs(UnmanagedType.LPStr)]
    string szPrinter, out IntPtr hPrinter, IntPtr pd);
  [DllImport("winspool.Drv", SetLastError=true)]
  public static extern bool ClosePrinter(IntPtr hPrinter);
  [DllImport("winspool.Drv", SetLastError=true, CharSet=CharSet.Ansi)]
  public static extern bool StartDocPrinter(IntPtr hPrinter, int level,
    [In, MarshalAs(UnmanagedType.LPStruct)] DOCINFOA di);
  [DllImport("winspool.Drv", SetLastError=true)]
  public static extern bool EndDocPrinter(IntPtr hPrinter);
  [DllImport("winspool.Drv", SetLastError=true)]
  public static extern bool StartPagePrinter(IntPtr hPrinter);
  [DllImport("winspool.Drv", SetLastError=true)]
  public static extern bool EndPagePrinter(IntPtr hPrinter);
  [DllImport("winspool.Drv", SetLastError=true)]
  public static extern bool WritePrinter(IntPtr hPrinter, IntPtr pBytes,
    int dwCount, out int dwWritten);
  public static bool SendBytesToPrinter(string szPrinterName, IntPtr pBytes,
    int dwCount) {
    IntPtr hPrinter; DOCINFOA di = new DOCINFOA();
    di.pDocName = "M175Bridge"; di.pDataType = "RAW";
    bool ok = OpenPrinter(szPrinterName, out hPrinter, IntPtr.Zero);
    if (!ok) return false;
    if (!StartDocPrinter(hPrinter, 1, di)) { ClosePrinter(hPrinter); return false; }
    if (!StartPagePrinter(hPrinter)) { EndDocPrinter(hPrinter); ClosePrinter(hPrinter); return false; }
    int written; bool b = WritePrinter(hPrinter, pBytes, dwCount, out written);
    EndPagePrinter(hPrinter); EndDocPrinter(hPrinter); ClosePrinter(hPrinter);
    return b;
  }
}
"@
$bytes = [IO.File]::ReadAllBytes($File)
$ptr = [Runtime.InteropServices.Marshal]::AllocHGlobal($bytes.Length)
[Runtime.InteropServices.Marshal]::Copy($bytes, 0, $ptr, $bytes.Length)
$ok = [WinSpool]::SendBytesToPrinter($Printer, $ptr, $bytes.Length)
[Runtime.InteropServices.Marshal]::FreeHGlobal($ptr)
if (-not $ok) { exit 1 }
"""


def _raw_print(printer, file_path, job_name):
    """RAW passthrough for PCL/PS-shaped payloads (WritePrinter)."""
    helper = os.path.join(TMP, "_rawsend.ps1")
    os.makedirs(TMP, exist_ok=True)
    with open(helper, "w", encoding="utf-8") as f:
        f.write(_RAWSEND_PS1 + "\n")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", helper, printer, file_path],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError("RAW print failed: " + (proc.stderr or "")[-200:])


def _render_pdf(pdf_path, dpi=300):
    """PDF -> one PNG per page at `dpi` using PyMuPDF."""
    import fitz  # PyMuPDF
    doc = fitz.open(pdf_path)
    paths = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=dpi)
        out = os.path.join(TMP, f"pg-{os.path.basename(pdf_path)}.{i}.png")
        pix.save(out)
        paths.append(out)
    doc.close()
    return paths


def _gdi_print(printer, image_paths, job_name):
    """Print images through the HP driver's own GDI rendering (host-based OK)."""
    import win32ui
    from PIL import Image, ImageWin

    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(printer)
    hdc.StartDoc(job_name)
    try:
        for p in image_paths:
            img = Image.open(p).convert("RGB")
            area_w = hdc.GetDeviceCaps(8)    # HORZRES (printable px)
            area_h = hdc.GetDeviceCaps(10)   # VERTRES
            if not area_w or not area_h:
                area_w, area_h = 2480, 3500  # A4 @300dpi fallback
            scale = min(area_w / img.width, area_h / img.height)
            w, h = int(img.width * scale), int(img.height * scale)
            x, y = max(0, (area_w - w) // 2), max(0, (area_h - h) // 2)
            hdc.StartPage()
            ImageWin.Dib(img).draw(hdc.GetHandleOutput(), (x, y, x + w, y + h))
            hdc.EndPage()
    finally:
        hdc.EndDoc()
        hdc.DeleteDC()


def print_file_bytes(data, doc_format, cfg, job_name="Android Job"):
    """IPP entry point: route by document-format to the right pipeline."""
    printer = _PRINTER_CACHE["name"] or find_printer(cfg)
    if not printer:
        STATUS["state"] = "error"
        STATUS["detail"] = "No Windows printer found"
        return False
    _PRINTER_CACHE["name"] = printer

    os.makedirs(TMP, exist_ok=True)
    fmt = (doc_format or "").lower()
    ext = (".pdf" if "pdf" in fmt else
           ".jpg" if ("jpeg" in fmt or "image/" in fmt) else ".bin")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(TMP, f"job-{stamp}{ext}")
    with open(path, "wb") as f:
        f.write(data)

    STATUS["state"] = "printing"
    STATUS["detail"] = "Printing %s" % job_name
    try:
        if ext == ".pdf":
            pages = _render_pdf(path, cfg.get("render_dpi", 300))
            _gdi_print(printer, pages, job_name)
        elif ext in (".jpg", ".png"):
            _gdi_print(printer, [path], job_name)
        else:
            _raw_print(printer, path, job_name)
        STATUS["state"] = "idle"
        STATUS["detail"] = "Ready"
        STATUS["jobs_sent"] += 1
        STATUS["last_job"] = stamp
        return True
    except Exception as e:
        STATUS["state"] = "error"
        STATUS["detail"] = str(e)[:160]
        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


FINDINGS_PATH = os.path.join(CAPTURES, "pml_findings.json")
_findings_mtime = [0.0]


def load_pml_findings():
    """Re-read captures/pml_findings.json when it changed (mtime-gated).

    tools/analyze_pcap.py refreshes that file after every capture run;
    the bridge picks up real toner/status without a restart.
    """
    try:
        mt = os.path.getmtime(FINDINGS_PATH)
    except OSError:
        return
    if mt == _findings_mtime[0]:
        return
    _findings_mtime[0] = mt
    try:
        with open(FINDINGS_PATH, "r", encoding="utf-8") as f:
            apply_pml_findings(json.load(f))
        print("  [status] loaded real printer data from USB analysis:",
              STATUS["toner"])
    except (OSError, ValueError) as e:
        print("  [status] findings load failed:", e)


def apply_pml_findings(findings):
    """tools/analyze_pcap.py calls this with toner/status decoded from USB."""
    for key, value in findings.items():
        if key == "toner":
            STATUS["toner"].update(value)
        else:
            STATUS[key] = value
