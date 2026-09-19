"""Single-port HTTP server: IPP print, eSCL scan, web UI, JSON API."""
import io
import json
import os
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

from .config import WEB_STATIC, SCANS, TMP, ROOT, load
from .usb import spooler_print
from .scan import engine

CFG = load()
_CAPS_CACHE = {"xml": None, "ts": 0}
_SCANNER_CACHE = {"names": []}   # refreshed at startup only (WIA must not
                                 # run inside server threads — see engine.py)
_SCAN_JOBS = {}

# Manual duplex state machine — the flip prompt is OUR software's job
# (the M175a has no display; the HP driver dialog normally does this on PC,
# and a phone app shows the same screen — see DevKit 05/06).
DUPLEX_STATE = {"stage": "idle", "doc": None, "pass2": []}
_JOB_LOCK = threading.Lock()
_JOB_SEQ = [0]


# ---------------------------------------------------------------- IPP

def _ipp_group(out, tag):
    out.append(tag)


def _ipp_attr(out, tag, name, values):
    if not isinstance(values, (list, tuple)):
        values = [values]
    for i, val in enumerate(values):
        out.append(tag)
        nb = name.encode() if i == 0 else b""
        out += struct.pack(">H", len(nb)) + nb
        if isinstance(val, int):
            out += struct.pack(">H", 4) + struct.pack(">i", val)
        elif isinstance(val, bool):
            out += struct.pack(">H", 1) + bytes([1 if val else 0])
        else:
            vb = str(val).encode()
            out += struct.pack(">H", len(vb)) + vb


def _ipp_parse(data):
    """Return (request_id, operation, dict of interesting op attrs)."""
    if len(data) < 8:
        return 0, 0, {}
    ver_major, ver_minor, op = struct.unpack(">BBH", data[:4])
    req_id = struct.unpack(">I", data[4:8])[0]
    attrs, pos, group = {}, 8, None
    while pos < len(data):
        tag = data[pos]; pos += 1
        if tag <= 0x0F:            # delimiter (group) tag
            group = tag
            continue
        if pos + 2 > len(data):
            break
        nlen = struct.unpack(">H", data[pos:pos + 2])[0]; pos += 2
        name = data[pos:pos + nlen].decode("utf-8", "replace"); pos += nlen
        if pos + 2 > len(data):
            break
        vlen = struct.unpack(">H", data[pos:pos + 2])[0]; pos += 2
        val = data[pos:pos + vlen]; pos += vlen
        if group == 0x01 and name:
            attrs[name] = val.decode("utf-8", "replace")
    return req_id, op, attrs


def _ipp_document(body):
    """Strip IPP headers/attribute groups -> raw document bytes.

    Walks the attribute structure using length fields (never search for
    raw 0x03 bytes — they occur inside binary documents too).
    """
    pos = 8                            # skip version(2)+op(2)+reqid(4)
    while pos < len(body):
        tag = body[pos]
        if tag == 0x03:                # end-of-attributes delimiter
            return body[pos + 1:]
        if tag <= 0x0F:                # group delimiter
            pos += 1
            continue
        if pos + 3 > len(body):
            break
        nlen = struct.unpack(">H", body[pos + 1:pos + 3])[0]
        pos += 3 + nlen
        if pos + 2 > len(body):
            break
        vlen = struct.unpack(">H", body[pos:pos + 2])[0]
        pos += 2 + vlen
    return body                        # fallback: treat whole body as doc


def ipp_handler(body):
    req_id, op, attrs = _ipp_parse(body)
    out = bytearray()
    if op == 0x0002:                                  # Print-Job
        fmt = attrs.get("document-format", "")
        ok = spooler_print.print_file_bytes(
            _ipp_document(body), fmt, CFG,
            job_name=attrs.get("job-name", "Android Job"))
        status = 0x0000 if ok else 0x0500             # successful / server-error
    elif op in (0x000A, 0x0004):                      # Get-Printer-Attributes
        status = 0x0000
    elif op in (0x0008, 0x0009):                      # job queries -> empty ok
        status = 0x0000
    else:
        status = 0x040B                               # operation-not-supported

    out += struct.pack(">BBH", 1, 1, status) + struct.pack(">I", req_id)
    _ipp_attr(out, 0x47, "attributes-charset", "utf-8")
    _ipp_attr(out, 0x48, "attributes-natural-language", "en")
    if op in (0x000A, 0x0004):
        st = spooler_print.STATUS
        up = int(time.time())
        _ipp_group(out, 0x04)                         # printer group
        _ipp_attr(out, 0x23, "printer-state", 4 if st["state"] == "printing" else 3)
        _ipp_attr(out, 0x44, "printer-state-reasons", "none")
        _ipp_attr(out, 0x44, "ipp-versions-supported", "1.1")
        _ipp_attr(out, 0x23, "operations-supported", [2, 4, 10])
        _ipp_attr(out, 0x42, "printer-name", CFG.get("device_name", "HP M175a"))
        _ipp_attr(out, 0x41, "printer-make-and-model",
                  "HP Color LaserJet MFP M175a (M175 Bridge)")
        _ipp_attr(out, 0x45, "printer-uri-supported", "/ipp/print")
        _ipp_attr(out, 0x44, "uri-security-supported", "none")
        _ipp_attr(out, 0x44, "uri-authentication-supported", "none")
        _ipp_attr(out, 0x49, "document-format-supported",
                  ["application/pdf", "application/octet-stream"])
        _ipp_attr(out, 0x22, "printer-is-accepting-jobs", True)
        _ipp_attr(out, 0x44, "pdl-override-supported", "not-attempted")
        _ipp_attr(out, 0x21, "queued-job-count", 0)
        _ipp_attr(out, 0x21, "printer-up-time", up)
        _ipp_attr(out, 0x47, "charset-configured", "utf-8")
        _ipp_attr(out, 0x48, "natural-language-configured", "en")
    elif op == 0x0002:
        _ipp_group(out, 0x02)                         # job group
        _ipp_attr(out, 0x21, "job-id", 1)
        _ipp_attr(out, 0x23, "job-state", 9)          # completed
        _ipp_attr(out, 0x44, "job-state-reasons", "none")
    out.append(0x03)                                  # end-of-attributes
    return bytes(out)


# ---------------------------------------------------------------- eSCL

_SCAN_NS_SCAN = "http://schemas.hp.com/imaging/escl/2011/05"
_SCAN_NS_PWG = "http://www.pwg.org/schemas/2010/12/sm"


def scanner_capabilities_xml():
    if _CAPS_CACHE["xml"] and time.time() - _CAPS_CACHE["ts"] < 3600:
        return _CAPS_CACHE["xml"]
    name = CFG.get("device_name", "HP Color LaserJet MFP M175a")
    uuid = CFG.get("device_uuid", "ce1f6a20-0002-3d17-8d3a-6d31373561")
    x = f'''<?xml version="1.0" encoding="UTF-8"?>
<scan:ScannerCapabilities xmlns:scan="{_SCAN_NS_SCAN}" xmlns:pwg="{_SCAN_NS_PWG}" version="1.0">
 <pwg:Version>1.0</pwg:Version>
 <pwg:MakeAndManufacturer>HP</pwg:MakeAndManufacturer>
 <pwg:ModelName>{name}</pwg:ModelName>
 <pwg:SerialNumber>M175BRIDGE</pwg:SerialNumber>
 <pwg:UUID>{uuid}</pwg:UUID>
 <scan:SettingProfile>
  <scan:ColorModes>
   <scan:ColorMode>BlackAndWhite1</scan:ColorMode>
   <scan:ColorMode>Grayscale8</scan:ColorMode>
   <scan:ColorMode>RGB24</scan:ColorMode>
  </scan:ColorModes>
  <scan:DocumentFormats>
   <pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>
  </scan:DocumentFormats>
  <scan:SupportedResolutions>
   <scan:Resolution><scan:XResolution><pwg:Number>75</pwg:Number></scan:XResolution><scan:YResolution><pwg:Number>75</pwg:Number></scan:YResolution></scan:Resolution>
   <scan:Resolution><scan:XResolution><pwg:Number>100</pwg:Number></scan:XResolution><scan:YResolution><pwg:Number>100</pwg:Number></scan:YResolution></scan:Resolution>
   <scan:Resolution><scan:XResolution><pwg:Number>150</pwg:Number></scan:XResolution><scan:YResolution><pwg:Number>150</pwg:Number></scan:YResolution></scan:Resolution>
   <scan:Resolution><scan:XResolution><pwg:Number>200</pwg:Number></scan:XResolution><scan:YResolution><pwg:Number>200</pwg:Number></scan:YResolution></scan:Resolution>
   <scan:Resolution><scan:XResolution><pwg:Number>300</pwg:Number></scan:XResolution><scan:YResolution><pwg:Number>300</pwg:Number></scan:YResolution></scan:Resolution>
   <scan:Resolution><scan:XResolution><pwg:Number>600</pwg:Number></scan:XResolution><scan:YResolution><pwg:Number>600</pwg:Number></scan:YResolution></scan:Resolution>
  </scan:SupportedResolutions>
  <scan:Platen>
   <scan:PlatenInputCaps>
    <scan:MinWidth>8</scan:MinWidth><scan:MaxWidth>2550</scan:MaxWidth>
    <scan:MinHeight>8</scan:MinHeight><scan:MaxHeight>3508</scan:MaxHeight>
    <scan:MaxScanRegions>1</scan:MaxScanRegions>
   </scan:PlatenInputCaps>
  </scan:Platen>
 </scan:SettingProfile>
</scan:ScannerCapabilities>'''
    _CAPS_CACHE["xml"] = x
    _CAPS_CACHE["ts"] = time.time()
    return x


def scanner_status_xml():
    st = spooler_print.STATUS
    state = "Idle" if st["state"] in ("idle", "offline") else "Processing"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<scan:ScannerStatus xmlns:scan="{_SCAN_NS_SCAN}" xmlns:pwg="{_SCAN_NS_PWG}">
 <pwg:State>{state}</pwg:State>
 <scan:AdfState>ScannerAdfEmpty</scan:AdfState>
</scan:ScannerStatus>'''


def _escl_parse_settings(xml_bytes):
    import xml.etree.ElementTree as ET
    dpi, color = CFG["scan_dpi"], CFG["scan_color"]
    try:
        root = ET.fromstring(xml_bytes)
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag in ("Dpi", "XResolution"):
                txt = (el.text or el.findtext(".//{*}Number") or "").strip()
                if txt.isdigit():
                    dpi = int(txt)
            if tag == "ColorMode" and el.text:
                t = el.text.strip()
                color = {"RGB24": "color", "Grayscale8": "grayscale",
                         "BlackAndWhite1": "binary"}.get(t, color)
    except Exception:
        pass
    return dpi, color


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "M175Bridge/1.0"

    def log_message(self, fmt, *args):
        print("  [http] %s" % (fmt % args))

    # ---- helpers
    @staticmethod
    def _render_pages(pdf_path, pages, out_name):
        """Extract `pages` (1-based, print order) into a temp PDF."""
        import fitz
        doc = fitz.open(pdf_path)
        out = fitz.open()
        for p in pages:
            out.insert_pdf(doc, from_page=p - 1, to_page=p - 1)
        path = os.path.join(TMP, out_name)
        out.save(path)
        out.close()
        doc.close()
        return path

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                self._send(200, f.read(), ctype)
        except OSError:
            self._send(404, "not found", "text/plain")

    # ---- routes
    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            return self._file(os.path.join(WEB_STATIC, "index.html"),
                              "text/html; charset=utf-8")
        if p.startswith("/static/"):
            fn = unquote(p[len("/static/"):])
            ctype = ("image/png" if fn.endswith(".png") else
                     "text/css" if fn.endswith(".css") else
                     "application/javascript" if fn.endswith(".js") else
                     "application/octet-stream")
            return self._file(os.path.join(WEB_STATIC, fn), ctype)
        if p == "/api/status":
            spooler_print.load_pml_findings()   # live USB-analysis refresh
            st = dict(spooler_print.STATUS)
            st["duplex"] = DUPLEX_STATE["stage"]
            st["scanners"] = [n for _, n in
                              _SCANNER_CACHE.get("names", [])]
            return self._send(200, json.dumps(st), "application/json")
        if p.startswith("/scans/"):
            return self._file(os.path.join(SCANS, unquote(p[len("/scans/"):])),
                              "image/jpeg")
        if p == "/eSCL":
            return self._send(200, scanner_capabilities_xml(),
                              "text/xml; charset=utf-8")
        if p == "/eSCL/ScannerCapabilities":
            return self._send(200, scanner_capabilities_xml(),
                              "text/xml; charset=utf-8")
        if p == "/eSCL/ScannerStatus":
            return self._send(200, scanner_status_xml(), "text/xml; charset=utf-8")
        if p.startswith("/eSCL/ScanJobs/") and p.endswith("/NextDocument"):
            jid = p[len("/eSCL/ScanJobs/"):-len("/NextDocument")]
            job = _SCAN_JOBS.get(jid)
            if not job:
                return self._send(404, "no such job", "text/plain")
            with open(job["file"], "rb") as f:
                return self._send(200, f.read(), "image/jpeg")
        if p in ("/ipp/print", "/ipp/printer"):
            return self._send(200, "M175 Bridge IPP endpoint (POST here)",
                              "text/plain")
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        p = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if p.startswith("/ipp"):
            return self._send(200, ipp_handler(body), "application/ipp")
        if p == "/eSCL/ScanJobs":
            dpi, color = _escl_parse_settings(body)
            with _JOB_LOCK:
                _JOB_SEQ[0] += 1
                jid = str(_JOB_SEQ[0])
            try:
                path = engine.scan_once(CFG, dpi=dpi, color=color)
            except Exception as e:
                return self._send(500, "scan failed: %s" % e, "text/plain")
            _SCAN_JOBS[jid] = {"file": path, "ts": time.time()}
            return self._send(201, b"", "text/plain",
                              {"Location": f"/eSCL/ScanJobs/{jid}/NextDocument"})
        if p == "/api/duplex/start":
            try:
                import json as _json
                req = _json.loads(body or b"{}")
                pdf = req.get("path") or os.path.join(
                    ROOT, "testpages", "duplex-mini.pdf")
                pdf = os.path.normpath(pdf)
                if not pdf.lower().startswith(ROOT.lower()):
                    return self._send(400, "{\"ok\":false,"
                                      "\"error\":\"path outside bridge\"}",
                                      "application/json")
                import fitz
                doc = fitz.open(pdf)
                n = doc.page_count
                doc.close()
                evens = list(range(2, n + 1, 2))[::-1]   # pass 1: reversed
                odds = list(range(1, n + 1, 2))          # pass 2
                pages_path = self._render_pages(pdf, evens, "dx-pass1.pdf")
                with open(pages_path, "rb") as f:
                    data = f.read()
                ok = spooler_print.print_file_bytes(
                    data, "application/pdf", CFG, "Duplex Pass 1 (backs)")
                if not ok:
                    raise RuntimeError(spooler_print.STATUS["detail"])
                DUPLEX_STATE.update(stage="awaiting-flip", doc=pdf,
                                    pass2=odds)
                return self._send(200, json.dumps(
                    {"ok": True, "stage": "awaiting-flip",
                     "pass1_pages": evens}), "application/json")
            except Exception as e:
                return self._send(500, json.dumps(
                    {"ok": False, "error": str(e)[:160]}),
                    "application/json")
        if p == "/api/duplex/continue":
            try:
                if DUPLEX_STATE["stage"] != "awaiting-flip":
                    return self._send(400, json.dumps(
                        {"ok": False,
                         "error": "no duplex job waiting for flip"}),
                        "application/json")
                pages_path = self._render_pages(
                    DUPLEX_STATE["doc"], DUPLEX_STATE["pass2"], "dx-pass2.pdf")
                with open(pages_path, "rb") as f:
                    data = f.read()
                ok = spooler_print.print_file_bytes(
                    data, "application/pdf", CFG, "Duplex Pass 2 (fronts)")
                if not ok:
                    raise RuntimeError(spooler_print.STATUS["detail"])
                DUPLEX_STATE.update(stage="complete", doc=None, pass2=[])
                return self._send(200, json.dumps({"ok": True}),
                                  "application/json")
            except Exception as e:
                return self._send(500, json.dumps(
                    {"ok": False, "error": str(e)[:160]}),
                    "application/json")
        if p == "/api/scan":
            try:
                path = engine.scan_once(CFG)
                return self._send(200, json.dumps(
                    {"ok": True, "url": "/scans/" + os.path.basename(path)}),
                    "application/json")
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "error": str(e)}),
                                  "application/json")
        self._send(404, "not found", "text/plain")

    def do_DELETE(self):
        p = urlparse(self.path).path
        if p.startswith("/eSCL/ScanJobs/") and _SCAN_JOBS.pop(p[15:], None) is not None:
            return self._send(200, b"", "text/plain")
        self._send(404, "not found", "text/plain")


def serve(port):
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd
