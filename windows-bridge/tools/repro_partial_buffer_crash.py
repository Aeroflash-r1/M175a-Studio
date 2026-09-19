"""Reproduce the phone's 'scan failed length=2165' crash — with REAL wire bytes.

    python tools/repro_partial_buffer_crash.py

The app's resync walker runs on PARTIAL buffers while the image streams in.
A chunk's DECLARED end routinely sits beyond the bytes received so far
(first read = 2165 B, chunk declares data ending ~4150). The old backward
search indexed beyond the buffer -> ArrayIndexOutOfBoundsException on the
very first read -> instant scan abort. This script runs both the OLD and
FIXED logic over the real captured response prefix.
"""
import re
import subprocess

TSHARK = r"D:/Wireshark/tshark.exe"
PCAP = "captures/four-rnd1-130013.pcap"
READ_SIZE = 2165  # the exact size from the phone's error message


def ep131_stream(pcap):
    out = subprocess.run(
        [TSHARK, "-r", pcap,
         "-Y", "usb.endpoint_address == 131 && usb.transfer_type == 3 && usb.data_len > 0",
         "-T", "fields", "-e", "usb.capdata"],
        capture_output=True, text=True).stdout
    parts = []
    for line in out.splitlines():
        line = line.strip()
        if line:
            try:
                parts.append(bytes.fromhex(line.replace(":", "")))
            except ValueError:
                pass
    return b"".join(parts)


def match_size_line(b, pos):
    i = pos
    digits = 0
    v = 0
    while i < len(b) and digits <= 6:
        c = b[i]
        if 48 <= c <= 57:
            d = c - 48
        elif 97 <= c <= 102:
            d = c - 87
        elif 65 <= c <= 70:
            d = c - 55
        elif c == 13:
            break
        else:
            return None
        v = v * 16 + d
        digits += 1
        i += 1
    if digits == 0 or digits > 6 or i + 1 >= len(b):
        return None
    if b[i] == 13 and b[i + 1] == 10:
        return [i + 2, v]
    return None


def match_size_line_chained(b, pos):
    m = match_size_line(b, pos)
    if m is None:
        return None
    ds, sz = m
    if sz == 0:
        return m
    de = ds + sz
    if match_size_line(b, de) is not None:
        return m
    if de + 2 <= len(b) and b[de] == 13 and b[de + 1] == 10 \
            and match_size_line(b, de + 2) is not None:
        return m
    return None


def at_true_boundary_OLD(b, i):
    """Kotlin as shipped at 12:53 — NO bounds check (throws past the end)."""
    return i == 0 or (i >= 2 and b[i - 2] == 13 and b[i - 1] == 10)


def at_true_boundary_FIXED(b, i):
    if i < 0 or i >= len(b):
        return False
    if i == 0:
        return True
    return i >= 2 and b[i - 2] == 13 and b[i - 1] == 10


def find_backward_OLD(b, pos, window):
    i = pos - 1                      # <-- unclamped: explodes past the end
    limit = max(0, pos - window)
    while i >= limit:
        if at_true_boundary_OLD(b, i) and match_size_line_chained(b, i) is not None:
            return i
        i -= 1
    return None


def find_backward_FIXED(b, pos, window):
    if len(b) == 0:
        return None
    i = min(pos - 1, len(b) - 1)     # <-- clamped to the real buffer
    limit = max(0, pos - window)
    while i >= limit:
        if at_true_boundary_FIXED(b, i) and match_size_line_chained(b, i) is not None:
            return i
        i -= 1
    return None


def walk(b, start, backward):
    """Minimal resync walk mirroring the Kotlin control flow."""
    pos = start
    guard = 0
    while pos < len(b) and guard < 100000:
        guard += 1
        m = match_size_line(b, pos)
        if m is None:
            # forward search (bounds-safe by construction)
            i = pos
            limit = min(len(b), pos + 512)
            found = None
            while i < limit:
                if at_true_boundary_FIXED(b, i) and match_size_line_chained(b, i) is not None:
                    found = i
                    break
                i += 1
            if found is None:
                return "incomplete"
            pos = found
            continue
        sz = m[1]
        if sz == 0:
            return "complete"
        de = m[0] + sz
        if match_size_line(b, de) is not None:
            pos = de
            continue
        if de + 2 <= len(b) and b[de] == 13 and b[de + 1] == 10 \
                and match_size_line(b, de + 2) is not None:
            pos = de + 2
            continue
        got = backward(b, de, 64)
        if got is None:
            fwd = None
            i = de
            limit = min(len(b), de + 512)
            while i < limit:
                if at_true_boundary_FIXED(b, i) and match_size_line_chained(b, i) is not None:
                    fwd = i
                    break
                i += 1
            if fwd is None:
                return "incomplete"
            pos = fwd
        else:
            pos = got
    return "incomplete"


def main():
    stream = ep131_stream(PCAP)
    m200 = [m for m in re.finditer(rb"HTTP/1\.1 (\d{3})", stream)
            if m.group(1) == b"200"][-1]
    he = stream.find(b"\r\n\r\n", m200.start())
    body = stream[he + 4:]

    print("real captured body: %d bytes" % len(body))
    print("first chunk line:", body[:16])
    prefix = body[:READ_SIZE]

    print("\n--- OLD logic (as shipped 12:53) on the first %d B read ---" % READ_SIZE)
    try:
        r = walk(prefix, 0, find_backward_OLD)
        print("result:", r)
    except IndexError as e:
        print("IndexError REPRODUCED -> phone would throw")
        print("  Android message form: ArrayIndexOutOfBoundsException "
              "length=%d; index=... " % len(prefix))
        print("  (python says: %s)" % e)

    print("\n--- FIXED logic on the same partial buffer ---")
    r = walk(prefix, 0, find_backward_FIXED)
    print("result:", r, "(no exception -> app keeps reading, scan completes)")

    print("\n--- FIXED logic on the FULL buffer (sanity) ---")
    r = walk(body, 0, find_backward_FIXED)
    print("result:", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
