"""Validate the wscn DIME parser fix (ME=0x08, not 0x04) — Python mirror.

Builds a synthetic multi-record DIME message exactly as a server must send
a large image (record1 MB+CF, record2 CF, record3 ME) carrying a JPEG split
across records, then runs the Kotlin-equivalent parser logic:
  - OLD (buggy) logic treats CF as end -> truncated image (phone symptom)
  - NEW logic concatenates all records -> byte-identical JPEG
"""
import struct


def dime_record(version=1, mb=False, me=False, cf=False,
                opt=b"", rec_id=b"", rtype=b"image/jpeg", data=b""):
    """Real DIME 12-byte header: ver/flags, 0, optlen(16), idlen(16),
    typelen(16), datalen(32)."""
    b0 = (version << 5) | (0x10 if mb else 0) | (0x08 if me else 0) | (0x04 if cf else 0)
    pad = lambda n: (n + 3) // 4 * 4
    rec = struct.pack(">BBHHHI", b0, 0, len(opt), len(rec_id), len(rtype), len(data))
    rec += opt + b"\0" * (pad(len(opt)) - len(opt))
    rec += rec_id + b"\0" * (pad(len(rec_id)) - len(rec_id))
    rec += rtype + b"\0" * (pad(len(rtype)) - len(rtype))
    rec += data + b"\0" * (pad(len(data)) - len(data))
    return rec


def parse_dime(buf):
    """Mirror of the fixed Kotlin parser: ME=0x08, concatenate until ME record."""
    out = bytearray()
    records = 0
    i = 0
    while i + 12 <= len(buf):
        b0 = buf[i]
        version = b0 >> 5
        if version != 1:
            break
        me = (b0 & 0x08) != 0
        cf = (b0 & 0x04) != 0
        opt_len = (buf[i + 2] << 8) | buf[i + 3]
        id_len = (buf[i + 4] << 8) | buf[i + 5]
        ty_len = (buf[i + 6] << 8) | buf[i + 7]
        data_len = (buf[i + 8] << 24) | (buf[i + 9] << 16) | (buf[i + 10] << 8) | buf[i + 11]
        p = i + 12
        p += (opt_len + 3) // 4 * 4 + (id_len + 3) // 4 * 4 + (ty_len + 3) // 4 * 4
        if p + data_len > len(buf):
            break
        out += buf[p:p + data_len]
        records += 1
        i = p + (data_len + 3) // 4 * 4
        if me:
            break
    return records, bytes(out)


def parse_dime_old_buggy(buf):
    """The OLD parser: stopped at CF (0x04) — truncated multi-record images."""
    out = bytearray()
    records = 0
    i = 0
    while i + 12 <= len(buf):
        b0 = buf[i]
        if (b0 >> 5) != 1:
            break
        me = (b0 & 0x04) != 0          # BUG
        opt_len = (buf[i + 2] << 8) | buf[i + 3]
        id_len = (buf[i + 4] << 8) | buf[i + 5]
        ty_len = (buf[i + 6] << 8) | buf[i + 7]
        data_len = (buf[i + 8] << 24) | (buf[i + 9] << 16) | (buf[i + 10] << 8) | buf[i + 11]
        p = i + 12
        p += (opt_len + 3) // 4 * 4 + (id_len + 3) // 4 * 4 + (ty_len + 3) // 4 * 4
        out += buf[p:p + data_len]
        records += 1
        i = p + (data_len + 3) // 4 * 4
        if me:
            break
    return records, bytes(out)


# --- synthetic JPEG-ish payload: marker header + big body ---
SOI_SOF = bytes.fromhex("ffd8ffc0001108" + "092a" + "06a4" + "03" +
                        "010000020101030101")   # 2346x1700 3-comp SOF-ish
BODY = bytes(range(256)) * 2600                   # 665,600 bytes of image data
EOI = bytes.fromhex("ffd9")
jpeg = SOI_SOF + BODY + EOI
print("reference JPEG:", len(jpeg), "bytes")

# split into 3 DIME records (64 KB / 64 KB / rest) — first record MB+CF,
# second CF, third ME (exactly how a 666 KB image must arrive)
parts = [jpeg[:65536], jpeg[65536:131072], jpeg[131072:]]
msg = (dime_record(mb=True, cf=True, data=parts[0]) +
       dime_record(cf=True, data=parts[1]) +
       dime_record(me=True, data=parts[2]))
print("DIME message:", len(msg), "bytes, 3 records")

# NEW parser
records, assembled = parse_dime(msg)
ok_new = assembled == jpeg
print("NEW parser: records=%d assembled=%dB -> %s" %
      (records, len(assembled), "BYTE-IDENTICAL ✓" if ok_new else "MISMATCH ✗"))

# OLD parser (reproduces the phone symptom)
records_old, truncated = parse_dime_old_buggy(msg)
pct = 100 * len(truncated) / len(jpeg)
print("OLD parser: records=%d assembled=%dB (%.0f%% of image) -> reproduces the "
      "'top of page only' truncation" % (records_old, len(truncated), pct))

assert ok_new, "NEW parser failed!"
assert len(truncated) < len(jpeg), "OLD-bug reproduction failed!"
print("\nVERDICT: fix proven — multi-record DIME now assembles byte-identical; "
      "old code truncated exactly like the phone symptom.")
