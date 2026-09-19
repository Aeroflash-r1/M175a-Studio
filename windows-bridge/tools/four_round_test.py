"""4x same-page 300 dpi test — laptop wire truth through the APP'S reader.

    python tools/four_round_test.py

Per round:
  1. Start USBPcap recording
  2. Trigger a REAL 300 dpi color WIA scan (page stays on the glass)
  3. Stop recording
  4. Reassemble the EP 0x83 stream from the pcap and run it through a
     mirror of the app's reader (chained resync walker + boundary guard,
     byte-identical logic to LedmScanClient/WscnScanClient)
  5. Print the VERDICT line + every resync event offset

Results are appended to tmp/four-round-results.txt after EACH round so a
timeout never loses completed rounds.
"""
import io
import os
import re
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONPATH", ".")

CAPTURES = os.path.join(ROOT, "captures")
TMP = os.path.join(ROOT, "tmp")
RESULTS = os.path.join(TMP, "four-round-results.txt")
USBPCAP = r"C:\Program Files\USBPcap\USBPcapCMD.exe"
TSHARK = r"D:\Wireshark\tshark.exe"
DPI = 300

# ---- app-mirror reader (keep byte-identical to the Kotlin walkers) ----


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


def at_true_boundary(b, i):
    return i == 0 or (i >= 2 and b[i - 2] == 13 and b[i - 1] == 10)


def find_size_line(b, pos, window):
    limit = min(len(b), pos + window)
    i = max(0, pos)
    while i < limit:
        if at_true_boundary(b, i) and match_size_line_chained(b, i) is not None:
            return i
        i += 1
    return None


def find_size_line_backward(b, pos, window):
    i = pos - 1
    limit = max(0, pos - window)
    while i >= limit:
        if at_true_boundary(b, i) and match_size_line_chained(b, i) is not None:
            return i
        i -= 1
    return None


def resync_chunk_walk(b, start, events):
    """Mirror of resyncChunkWalk: emit de-chunked bytes, log anomalies."""
    out = io.BytesIO()
    pos = start
    guard = 0
    while pos < len(b) and guard < 2_000_000:
        guard += 1
        m = match_size_line(b, pos)
        if m is None:
            events.append(("forward-search", pos))
            nxt = find_size_line(b, pos, 512)
            if nxt is None:
                return out.getvalue(), -1
            pos = nxt
            continue
        sz = m[1]
        if sz == 0:
            return out.getvalue(), pos
        ds = m[0]
        de = ds + sz
        if match_size_line(b, de) is not None:
            out.write(b[ds:de])
            pos = de
            continue
        if de + 2 <= len(b) and b[de] == 13 and b[de + 1] == 10 \
                and match_size_line(b, de + 2) is not None:
            out.write(b[ds:de])
            pos = de + 2
            continue
        back = find_size_line_backward(b, de, 64)
        resync = back if back is not None else find_size_line(b, de, 512)
        if resync is None:
            return out.getvalue(), -1
        events.append(("backward-resync" if back is not None else "forward-resync",
                       de, resync))
        if resync - 2 > ds:
            out.write(b[ds:resync - 2])
        pos = resync
    return out.getvalue(), -1


def slice_jpeg(b):
    soi = b.find(b"\xff\xd8")
    if soi < 0:
        return None
    eoi = b.rfind(b"\xff\xd9")
    if eoi <= soi:
        return None
    return b[soi:eoi + 2]


def sof_dims(b):
    i = 0
    while i + 9 < len(b):
        if b[i] != 0xFF:
            i += 1
            continue
        m = b[i + 1]
        if m in (0xC0, 0xC1, 0xC2):
            h = (b[i + 5] << 8) | b[i + 6]
            w = (b[i + 7] << 8) | b[i + 8]
            return w, h
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        if m == 0xD9 or m == 0xDA:
            break
        ln = (b[i + 2] << 8) | b[i + 3]
        if ln <= 0:
            break
        i += 2 + ln
    return 0, 0


def dime_assemble(b):
    """Walk DIME records, concatenate payloads until ME=1 (app-exact)."""
    out = io.BytesIO()
    i = 0
    while i + 12 <= len(b):
        b0 = b[i]
        if (b0 >> 5) != 1:
            break
        me = (b0 & 0x08) != 0
        pad4 = lambda n: (n + 3) & ~3
        opt = (b[i + 2] << 8) | b[i + 3]
        idl = (b[i + 4] << 8) | b[i + 5]
        tyl = (b[i + 6] << 8) | b[i + 7]
        dl = int.from_bytes(b[i + 8:i + 12], "big")
        p = i + 12 + pad4(opt) + pad4(idl) + pad4(tyl)
        if p + dl > len(b):
            break
        out.write(b[p:p + dl])
        i = p + pad4(dl)
        if me:
            break
    return out.getvalue()


# ---- wire extraction ----


def pcap_ep131_stream(pcap):
    out = subprocess.run(
        [TSHARK, "-r", pcap,
         "-Y", "usb.endpoint_address == 131 && usb.transfer_type == 3 && usb.data_len > 0",
         "-T", "fields", "-e", "usb.capdata"],
        capture_output=True, text=True, timeout=120).stdout
    frames = []
    for line in out.splitlines():
        line = line.strip()
        if line:
            try:
                frames.append(bytes.fromhex(line.replace(":", "")))
            except ValueError:
                continue
    return b"".join(frames)


def analyze_capture(pcap):
    stream = pcap_ep131_stream(pcap)
    if not stream:
        return None, "no EP 0x83 data in capture"
    m200 = None
    for m in re.finditer(rb"HTTP/1\.1 (\d{3})", stream):
        if m.group(1) == b"200":
            m200 = m
    if m200 is None:
        return None, "no HTTP 200 image response in capture"
    start = m200.start()
    he = stream.find(b"\r\n\r\n", start)
    if he < 0:
        return None, "no header end in image response"
    headers = stream[start:he].decode("latin1", "replace")
    if "chunked" not in headers.lower():
        return None, "image response not chunked"
    body = stream[he + 4:]
    # cut at the next response header if one follows in the same stream
    nxt = re.search(rb"HTTP/1\.1 \d{3}", body)
    if nxt:
        body = body[:nxt.start()]
    events = []
    payload, term = resync_chunk_walk(body, 0, events)
    # WIRE-VERIFIED (four-rnd1-130013): the LEDM 200 image-response payload
    # is RAW JPEG — no DIME envelope on the laptop wire. (The phone's wscn
    # path IS DIME-wrapped per HP's bb_soapht plugin — transports differ.)
    jpeg = slice_jpeg(payload)
    if jpeg is None:
        return None, "no JPEG in de-chunked payload (%dB, term=%s)" % (len(payload), term >= 0)
    w, h = sof_dims(jpeg)
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(jpeg))
        im.load()
        small = im.convert("RGB").resize((200, 200))
        px = list(small.getdata())
        rs = sum(p[0] for p in px) / len(px)
        gs = sum(p[1] for p in px) / len(px)
        bs = sum(p[2] for p in px) / len(px)
        spread = max(rs, gs, bs) - min(rs, gs, bs)
        stats = (rs, gs, bs, spread)
    except Exception as e:
        stats = ("DECODE FAIL: %s" % e,)
    return {"jpeg_kb": len(jpeg) // 1024, "sof": "%dx%d" % (w, h),
            "complete": term >= 0, "events": events, "stats": stats}, None


# ---- session ----


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


def wia_scan(cfg, result):
    try:
        from m175_bridge.scan.engine import scan_once
        result["path"] = scan_once(cfg, dpi=DPI, color="color")
    except Exception as e:
        result["error"] = str(e)


def main():
    os.makedirs(TMP, exist_ok=True)
    from m175_bridge.config import load
    cfg = load()
    dev = find_pcap_device()
    if not dev:
        print("FATAL: no USBPcap device (replug printer USB)")
        return 1

    with open(RESULTS, "a", encoding="utf-8") as res:
        def emit(s):
            print(s, flush=True)
            res.write(s + "\n")
            res.flush()

        emit("=" * 66)
        emit(" 4x SAME-PAGE 300 dpi TEST — %s (laptop wire, app-mirror reader)"
             % time.strftime("%Y-%m-%d %H:%M:%S"))
        emit("=" * 66)
        emit(">>> MAKE SURE THE PAGE IS FACE-DOWN ON THE GLASS, LID CLOSED <<<")
        for i in range(15, 0, -5):
            emit("  starting in %d seconds..." % i)
            time.sleep(5)

        for rnd in range(1, 5):
            pcap = os.path.join(CAPTURES, "four-rnd%d-%s.pcap" % (rnd, time.strftime("%H%M%S")))
            proc = subprocess.Popen([USBPCAP, "-d", dev, "-A", "-o", pcap],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)
            result = {}
            t = threading.Thread(target=wia_scan, args=(cfg, result))
            t.start()
            t.join(timeout=120)
            time.sleep(2)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

            scan_note = result.get("path") or ("WIA error: %s" % result.get("error"))
            if not os.path.exists(pcap) or os.path.getsize(pcap) < 1000:
                emit("ROUND %d: capture too small (%s) — scan note: %s"
                     % (rnd, os.path.getsize(pcap) if os.path.exists(pcap) else 0, scan_note))
                continue
            verdict, err = analyze_capture(pcap)
            emit("")
            emit("ROUND %d  capture: %s" % (rnd, os.path.basename(pcap)))
            emit("  scan: %s" % scan_note)
            if err:
                emit("  ANALYZE ERROR: %s" % err)
                continue
            ev = verdict["events"]
            evtxt = ("none — stream framed CLEAN" if not ev else
                     "; ".join("%s @%d→%d" % e if len(e) == 3 else "%s @%d" % (e[0], e[1])
                               for e in ev))
            if str(verdict["stats"][0]).startswith("DECODE FAIL"):
                st = verdict["stats"][0]
                spread_s = "n/a"
            else:
                rs, gs, bs, spread = verdict["stats"]
                st = "R%d G%d B%d" % (round(rs), round(gs), round(bs))
                spread_s = str(round(spread))
            emit("  VERDICT: laptop-mirror • req %ddpi • raw %dKB • SOF %s • "
                 "complete=%s • spread %s • %s"
                 % (DPI, verdict["jpeg_kb"], verdict["sof"],
                    "YES" if verdict["complete"] else "NO", spread_s, st))
            emit("  resync events: %s" % evtxt)
            emit("  [%s]" % st)
            time.sleep(5)  # let the engine settle back to idle between rounds

    emit("")
    emit("Full results: %s" % RESULTS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
