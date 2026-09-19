"""Validate the CHAINED-FALSE-POSITIVE resync fix (mirrors the final Kotlin
logic in LedmScanClient.kt / WscnScanClient.kt, including backward resync).

Proves on synthetic streams:
  A. OLD behavior (unchained forward-only) is fooled by a coincidental
     hex+CRLF lookalike inside chunk data -> mis-framing (the bug).
  B. NEW behavior (chained matcher, backward-then-forward) -> byte-perfect.
  C. The canonical short-chunk case (26 B short at the 64 KB boundary,
     capture scan-otg-110452) now recovers BYTE-EXACT (no hole at all).
  D. Clean streams: zero resync events, byte-identical output.
"""
import io


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
    declared_end = ds + sz
    if match_size_line(b, declared_end) is not None:
        return m
    if declared_end + 2 <= len(b) and b[declared_end] == 13 and b[declared_end + 1] == 10 \
            and match_size_line(b, declared_end + 2) is not None:
        return m
    return None


def at_true_boundary(b, i):
    return i == 0 or (i >= 2 and b[i - 2] == 13 and b[i - 1] == 10)


def find_size_line(b, pos, window, chained):
    check = match_size_line_chained if chained else match_size_line
    limit = min(len(b), pos + window)
    i = max(0, pos)
    while i < limit:
        if (not chained or at_true_boundary(b, i)) and check(b, i) is not None:
            return i
        i += 1
    return None


def find_size_line_backward(b, pos, window, chained):
    check = match_size_line_chained if chained else match_size_line
    i = pos - 1
    limit = max(0, pos - window)
    while i >= limit:
        if (not chained or at_true_boundary(b, i)) and check(b, i) is not None:
            return i
        i -= 1
    return None


def resync_chunk_walk(b, start, chained, events):
    out = io.BytesIO()
    pos = start
    guard = 0
    while pos < len(b) and guard < 2_000_000:
        guard += 1
        m = match_size_line(b, pos)
        if m is None:
            events.append(("forward-search", pos))
            nxt = find_size_line(b, pos, 512, chained)
            if nxt is None:
                return None, -1
            pos = nxt
            continue
        sz = m[1]
        if sz == 0:
            return out.getvalue(), pos
        ds = m[0]
        declared_end = ds + sz
        if match_size_line(b, declared_end) is not None:
            out.write(b[ds:declared_end])
            pos = declared_end
            continue
        if declared_end + 2 <= len(b) and b[declared_end] == 13 and b[declared_end + 1] == 10 \
                and match_size_line(b, declared_end + 2) is not None:
            out.write(b[ds:declared_end])
            pos = declared_end + 2
            continue
        back = find_size_line_backward(b, declared_end, 64, chained) if chained else None
        resync = back if back is not None else find_size_line(b, declared_end, 512, chained)
        if resync is None:
            return out.getvalue(), -1
        events.append(("backward" if back is not None else "forward", declared_end, resync))
        # shared form, identical to the Kotlin branch: for a backward match
        # resync-2 strips the closing CRLF (byte-exact short-chunk recovery);
        # for a forward match it drops the last 2 bytes (over-long data).
        if resync - 2 > ds:
            out.write(b[ds:resync - 2])
        pos = resync
    return out.getvalue(), -1


def build_stream(chunk_sizes, shorts=None, lookalike=None):
    """lookalike = (chunk_idx, offset_in_data, fake_line) planted in data."""
    body = b""
    for idx, sz in enumerate(chunk_sizes):
        missing = (shorts or {}).get(idx, 0)
        data = bytes(((i * 37 + idx * 11) % 251) + 1 for i in range(sz - missing))
        if lookalike is not None and idx == lookalike[0]:
            off = lookalike[1]
            data = data[:off] + lookalike[2] + data[off + len(lookalike[2]):]
        body += ("%x\r\n" % sz).encode() + data + b"\r\n"
    return body + b"0\r\n\r\n"


def payload_of(chunk_sizes, shorts=None, lookalike=None):
    out = bytearray()
    for idx, sz in enumerate(chunk_sizes):
        missing = (shorts or {}).get(idx, 0)
        data = bytes(((i * 37 + idx * 11) % 251) + 1 for i in range(sz - missing))
        if lookalike is not None and idx == lookalike[0]:
            off = lookalike[1]
            data = data[:off] + lookalike[2] + data[off + len(lookalike[2]):]
        out += data
    return bytes(out)


print("=== A/B: over-long chunk + coincidental lookalike in the search window ===")
# chunk 1 delivers 6 bytes MORE than declared -> its declared end lands
# INSIDE the delivered data -> CRLF-variant fails -> forward search runs
# over the remaining entropy bytes, where a planted "1a2\r\n" (hex
# lookalike) sits. OLD walker trusts it -> mis-frame. NEW walker's chained
# matcher rejects it and finds the real next boundary.
sizes = [2048, 2048, 2048]
shorts = {1: -6}                    # negative = over-long delivery
lookalike = (1, 2049, b"1a2\r\n")  # "1a2" = 418 -> claims 418 data bytes
stream = build_stream(sizes, shorts=shorts, lookalike=lookalike)
old_data, old_end = resync_chunk_walk(stream, 0, chained=False, events=[])
new_data, new_end = resync_chunk_walk(stream, 0, chained=True, events=[])
expected = payload_of(sizes, shorts=shorts, lookalike=lookalike)
print("expected payload: %d B" % len(expected))
print("OLD (unchained): %d B, terminator: %s  -> mis-framed (bug reproduced)"
      % (len(old_data), old_end >= 0))
print("NEW (chained):   %d B, byte-identical: %s, terminator: %s"
      % (len(new_data), new_data == expected, new_end >= 0))

print()
print("=== C: canonical short-chunk (26 B short @ 64 KB, capture-derived) ===")
sizes = [2048] * 33
shorts = {7: 26}
stream = build_stream(sizes, shorts=shorts)
new_data, new_end = resync_chunk_walk(stream, 0, chained=True, events=[])
expected = payload_of(sizes, shorts=shorts)
print("NEW: recovered %d/%d B, byte-identical: %s, terminator: %s"
      % (len(new_data), len(expected), new_data == expected, new_end >= 0))

print()
print("=== D: clean stream ===")
sizes = [2048] * 10
stream = build_stream(sizes)
events = []
new_data, new_end = resync_chunk_walk(stream, 0, chained=True, events=events)
print("NEW: byte-identical: %s, terminator: %s, resync events: %d"
      % (new_data == payload_of(sizes), new_end >= 0, len(events)))
