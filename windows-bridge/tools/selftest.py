"""Self-test for the running bridge.

    python tools\\selftest.py [host:port]
"""
import json
import struct
import sys
import urllib.request

BASE = "http://" + (sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:8080")


def build_get_printer_attrs():
    out = bytearray()
    out += struct.pack(">BBH", 1, 1, 0x000A)          # IPP 1.1 Get-Printer-Attributes
    out += struct.pack(">I", 1)                        # request id
    out.append(0x01)                                   # operation-attributes-tag
    for tag, name, val in ((0x47, "attributes-charset", "utf-8"),
                           (0x48, "attributes-natural-language", "en"),
                           (0x45, "printer-uri", "ipp://localhost/ipp/print")):
        out.append(tag)
        nb = name.encode()
        out += struct.pack(">H", len(nb)) + nb
        vb = val.encode()
        out += struct.pack(">H", len(vb)) + vb
    out.append(0x03)
    return bytes(out)


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + ("  " + detail if detail else ""))
    return ok


def main():
    ok = True
    # 1. status API
    try:
        with urllib.request.urlopen(BASE + "/api/status", timeout=5) as r:
            st = json.loads(r.read())
        ok &= check("status API", True,
                    "state=%s printers=%s" % (st["state"],
                                              ",".join(st.get("scanners", [])) or "-"))
    except Exception as e:
        ok &= check("status API", False, str(e)[:80])

    # 2. IPP Get-Printer-Attributes
    try:
        req = urllib.request.Request(BASE + "/ipp/print",
                                     data=build_get_printer_attrs(),
                                     headers={"Content-Type": "application/ipp"})
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read()
        status = struct.unpack(">H", body[2:4])[0]
        has_state = b"printer-state" in body
        ok &= check("IPP Get-Printer-Attributes",
                    status == 0 and has_state,
                    "ipp-status=0x%04X" % status)
    except Exception as e:
        ok &= check("IPP Get-Printer-Attributes", False, str(e)[:80])

    # 3. eSCL capabilities
    try:
        with urllib.request.urlopen(BASE + "/eSCL/ScannerCapabilities",
                                    timeout=5) as r:
            xml = r.read().decode()
        ok &= check("eSCL ScannerCapabilities",
                    "ScannerCapabilities" in xml and "RGB24" in xml)
    except Exception as e:
        ok &= check("eSCL ScannerCapabilities", False, str(e)[:80])

    print("\n" + ("ALL SYSTEMS GO!" if ok else "SOME TESTS FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
