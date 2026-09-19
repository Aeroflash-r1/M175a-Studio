"""Decode HP's binary Scanner Parameter File (hppls100.spf) — v3.

Recovered structure (reverse-engineered from hppls100.spf, 3208 bytes):
  b"!@#$%\\0" + u32 root_token (0x149=329) + u32 leaf_count (75) + u32 ?
  + 75 leaf slots (u32 char-code + 8x 0xFF filler), 12 B each
  + 74 triplet records (u32 token-id 0x100.., u32 child0, u32 child1)
      child < 0x100  -> literal ASCII char
      child >= 0x100 -> another tree token
  + bit-packed message (Huffman codes from root)

75 leaves + 74 internal nodes = full binary tree (checks out).

This decoder tries the 4 bit conventions (MSB/LSB-first x bit-polarity),
scores by printable-ASCII ratio, picks the best, and writes the text.
"""
import struct
import sys

PATH = (r"C:\Windows\System32\DriverStore\FileRepository"
        r"\hppasc20.inf_amd64_217c86e51e43d225\hppls100.spf")


def parse(path):
    d = open(path, "rb").read()
    assert d[:5] == b"!@#$%", "bad magic"
    root, leaves, extra = struct.unpack_from("<III", d, 6)
    off = 18
    leaf_chars = []
    for i in range(leaves):
        u = struct.unpack_from("<I", d, off + i * 12)[0]
        leaf_chars.append(u)
    off += leaves * 12

    tree = {}
    tok = 0x100
    while off + 12 <= len(d) and tok <= root:
        tid, c0, c1 = struct.unpack_from("<III", d, off)
        if tid != tok:
            break
        tree[tid] = (c0, c1)
        tok += 1
        off += 12
    print("root=0x%X leaves=%d extra=%d | leaf chars: %d | triplets: %d "
          "(0x100..0x%X) | bitstream at %d, %d bytes"
          % (root, leaves, extra, len(leaf_chars), len(tree),
             0x100 + len(tree) - 1, off, len(d) - off))
    return root, tree, d[off:], extra


def decode(root, tree, bits, msb_first=True, zero_is_child0=True,
           max_out=20000):
    out = []
    node = root
    invalid = 0
    for byte in bits:
        for k in range(8):
            bit = ((byte >> (7 - k)) & 1) if msb_first else ((byte >> k) & 1)
            c0, c1 = tree[node]
            child = c0 if (bit == 0) == zero_is_child0 else c1
            if child < 0x100:
                out.append(child)
                node = root
            elif child in tree:
                node = child
            else:
                invalid += 1
                node = root
                if invalid > 40:
                    return bytes(out), False
            if len(out) >= max_out:
                return bytes(out), True
    return bytes(out), node == root


def main(path=PATH):
    root, tree, bits, extra = parse(path)

    best = None
    for msb in (True, False):
        for pol in (True, False):
            txt, clean = decode(root, tree, bits, msb, pol)
            printable = sum(1 for b in txt if 32 <= b < 127 or b in (9, 10, 13))
            ratio = printable / max(1, len(txt))
            print("msb=%s zero=c0=%s: %d chars, printable %.2f%%, clean=%s"
                  % (msb, pol, len(txt), ratio * 100, clean))
            if best is None or ratio > best[0]:
                best = (ratio, msb, pol, txt)

    ratio, msb, pol, txt = best
    print("\n=== BEST: msb=%s zero=c0=%s, %.2f%% printable, %d chars ==="
          % (msb, pol, ratio * 100, len(txt)))
    text = txt.decode("latin1")
    open(r"D:/M175Bridge/tmp/spf-decoded.txt", "w",
         encoding="utf-8").write(text)
    print(text[:4000])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else PATH)
