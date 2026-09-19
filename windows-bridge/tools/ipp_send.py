"""Send a real IPP Print-Job (like Android would) to the bridge.

    python tools/ipp_send.py testpages/color-test.pdf application/pdf
    python tools/ipp_send.py testpages/mono-test.pdf application/pdf mono
"""
import struct
import sys
import urllib.request

TARGET = "http://127.0.0.1:8080/ipp/print"


def ipp_print_job(doc: bytes, fmt: str, job_name: str) -> bytes:
    out = bytearray()
    out += struct.pack(">BBH", 1, 1, 0x0002)      # IPP 1.1 Print-Job
    out += struct.pack(">I", 1)                    # request-id
    out.append(0x01)                               # operation-attributes

    def attr(tag, name, val):
        out.append(tag)
        nb = name.encode()
        out.extend(struct.pack(">H", len(nb)) + nb)
        vb = val.encode()
        out.extend(struct.pack(">H", len(vb)) + vb)

    attr(0x47, "attributes-charset", "utf-8")
    attr(0x48, "attributes-natural-language", "en")
    attr(0x45, "printer-uri", "ipp://localhost/ipp/print")
    attr(0x42, "requesting-user-name", "bro")
    attr(0x42, "job-name", job_name)
    attr(0x49, "document-format", fmt)
    out.append(0x03)                               # end-of-attributes
    out += doc
    return bytes(out)


def send(path, fmt="application/pdf", name="test"):
    with open(path, "rb") as f:
        doc = f.read()
    payload = ipp_print_job(doc, fmt, name)
    req = urllib.request.Request(
        TARGET, data=payload,
        headers={"Content-Type": "application/ipp"})
    with urllib.request.urlopen(req, timeout=300) as r:
        body = r.read()
    status = struct.unpack(">H", body[2:4])[0]
    print("IPP response status: 0x%04X (%s)" %
          (status, "SUCCESS" if status == 0 else "FAILED"))
    return status == 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    fmt = sys.argv[2] if len(sys.argv) > 2 else "application/pdf"
    name = sys.argv[3] if len(sys.argv) > 3 else "test"
    ok = send(path, fmt, name)
    sys.exit(0 if ok else 1)
