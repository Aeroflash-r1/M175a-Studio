"""Debug the v5/v6 chunk-chain walk on REAL captured 0x83 stream.

    python tools/debug_chunk_walk.py

For each HTTP response in the stream: print status, framing headers, and
walk the chunk chain verbosely — printing every chunk size, the bytes
after each chunk, and the exact failure position + hex context.
"""
import re
import subprocess
import sys

TSHARK = r"D:/Wireshark/tshark.exe"
CAPTURES = [
    "captures/scan-otg-235137.pcap",
    "captures/scan-otg-195230.pcap",
]


def load_stream(pcap):
    out = subprocess.run(
        [TSHARK, "-r", pcap,
         "-Y", "usb.endpoint_address == 131 && usb.transfer_type == 3 && usb.data_len > 0",
         "-T", "fields", "-e", "usb.capdata"],
        capture_output=True, text=True).stdout
    frames = [bytes.fromhex(l.strip()) for l in out.splitlines() if l.strip()]
    return frames, b"".join(frames)


def find_crlf(b, frm):
    i, limit = frm, len(b) - 1
    while i < limit:
        if b[i] == 0x0D and b[i + 1] == 0x0A:
            return i
        i += 1
    return -1


def walk_chunked(seg, he, verbose_every=200):
    """Verbose chunk-chain walk. Returns (end or -1, log lines)."""
    log = []
    pos = he + 4
    n = 0
    while pos < len(seg):
        eol = find_crlf(seg, pos)
        if eol < 0:
            log.append("chunk %d: NO CRLF from %d (context %r)"
                       % (n, pos, seg[pos:pos + 24]))
            return -1, log
        s = seg[pos:eol].decode("latin1").strip().split(";")[0]
        try:
            size = int(s, 16)
        except ValueError:
            log.append("chunk %d: BAD SIZE at %d: %r"
                       % (n, pos, seg[pos:pos + 24]))
            return -1, log
        data_start = eol + 2
        if size == 0:
            term = seg[pos:data_start + 2]
            log.append("chunk %d: TERMINAL %r at %d -> end=%d"
                       % (n, term, pos, data_start + 2))
            return data_start + 2, log
        if len(seg) < data_start + size + 2:
            log.append("chunk %d: size=0x%x incomplete (have %d need %d)"
                       % (n, size, len(seg), data_start + size + 2))
            return -1, log
        after = seg[data_start + size:data_start + size + 2]
        if n < 5 or n % verbose_every == 0:
            log.append("chunk %d: size=0x%x @%d after-data=%r"
                       % (n, size, pos, after))
        if after != b"\r\n":
            log.append("  !! chunk %d data NOT followed by CRLF: %r"
                       % (n, seg[data_start + size:data_start + size + 8]))
        pos = data_start + size + 2
        n += 1
    log.append("walk ran past end at pos=%d" % pos)
    return -1, log


for pcap in CAPTURES:
    frames, stream = load_stream(pcap)
    print("=" * 70)
    print("CAPTURE:", pcap, "| frames=%d stream=%dB" % (len(frames), len(stream)))
    starts = [m.start() for m in re.finditer(rb"HTTP/1\.1 ", stream)]
    print("response starts:", starts)
    bounds = starts + [len(stream)]

    for k in range(len(starts)):
        seg = stream[bounds[k]:bounds[k + 1]]
        he = seg.find(b"\r\n\r\n")
        if he < 0:
            print("resp %d @%d: NO HEADER END (%dB)" % (k, bounds[k], len(seg)))
            continue
        headers = seg[:he].decode("latin1", "replace")
        status = headers.splitlines()[0]
        chunked = "chunked" in headers.lower()
        m = re.search(r"(?i)content-length:\s*(\d+)", headers)
        cl = int(m.group(1)) if m else -1
        print("-" * 70)
        print("resp %d @%d: %s | chunked=%s cl=%s seglen=%d"
              % (k, bounds[k], status, chunked, cl, len(seg)))
        if k == 0 or not chunked:
            print("  headers: %r" % headers.replace("\r\n", " | ")[:400])
        if chunked:
            end, log = walk_chunked(seg, he)
            for line in log[:12]:
                print("   ", line)
            print("  WALK RESULT: end=%s (seg=%d)" % (end, len(seg)))
            if end and end > 0 and end < len(seg):
                print("  bytes after end: %r" % seg[end:end + 24])
        else:
            want = he + 4 + cl if cl >= 0 else None
            print("  CL path: want=%s have=%d -> %s"
                  % (want, len(seg),
                     "complete" if want is not None and len(seg) >= want
                     else "INCOMPLETE/CLOSE-DELIMITED"))
