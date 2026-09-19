"""Extract the EXACT print-stream commands Windows sends to the printer.

    python tools/extract_print_stream.py captures/auto-print-165115.pcap

Reassembles bulk-OUT data and prints the PJL/PCL command structure —
this is how we get the printer's real start/stop/page language instead
of guessing.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_pcap import payloads  # proven reader: capdata + data_fragment


def out_stream(pcap):
    chunks = []
    for direction, blob in payloads(pcap):
        if direction == "OUT":
            chunks.append(blob)
    return b"".join(chunks)


def describe(stream):
    print("total OUT bytes: %d" % len(stream))
    # PJL commands
    for m in re.finditer(rb"@PJL[^\r\n\x1b]*", stream):
        print("PJL :", m.group(0).decode("latin1").strip())
    # UEL = universal exit language, separates jobs
    print("UEL count (job separators):", stream.count(b"\x1b%-12345X"))
    # PCL reset / notable escapes
    for name, pat in (("PCL reset (EcE)", rb"\x1bE"),
                      ("start raster (Ec*r0F|Ec*v)", rb"\x1b\*r0?F|\x1b\*v[01]a"),
                      ("end raster (Ec*rC)", rb"\x1b\*rC"),
                      ("form feed", rb"\x0c"),
                      ("PCLXL header", rb"\) HP-PCL XL"),
                      ("PCLXL EndSession", rb"\xfe\x02")):
        n = len(re.findall(pat, stream))
        if n:
            print("%-28s x%d" % (name, n))
    # show first 400 printable bytes for context
    txt = "".join(chr(c) if 32 <= c < 127 else ("\x1b" if c == 0x1b else ".")
                  for c in stream[:600])
    print("\nstream head:\n%s" % txt)


if __name__ == "__main__":
    describe(out_stream(sys.argv[1]))
