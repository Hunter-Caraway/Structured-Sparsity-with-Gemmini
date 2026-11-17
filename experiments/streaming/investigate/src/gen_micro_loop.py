#!/usr/bin/env python3
"""Host-side data and reference for micro_loop.c (bank-split-fix-spec.md section 8).

One problem: C (80 x 96 int32) = A (80 x 768 int8) * W (768 x 96, n:m pruned), i.e. the qkv loop tile
I=5, J=6, K=48 tiles. The 3x6x48 and 1x6x48 shapes use the first 48 / 16 rows of the same A and C.

Writes into <out_dir>:
  A.bin      80 x 768 int8 (full range -128..127, uniform)
  W.bin      768 x 96 int8, pruned: each column keeps the n largest |values| of every m rows (ties to the lower row),
             the rule of gemmini_nm.h nm_prune()
  WC.bin     384 x 96 int8, compressed (nm_compress() rule: kept nonzeros in row order, short groups padded)
  IDX.bin    384 x 96 uint8, row inside the m-group of each WC value
  IDXSP.bin  index tiles in the scratchpad format (nm_pack_meta_spad), tile u = k' * 6 + j (the loop's order)
  C.bin      80 x 96 int32 little-endian, exact A @ W
  data.h     dimensions, pattern, sha256 of each .bin, the arrays via .incbin

usage: gen_micro_loop.py <out_dir> <n> <m> [seed]
"""
import hashlib
import random
import struct
import sys
from operator import mul
from pathlib import Path

DIM = 16
M_ROWS, K, N = 80, 768, 96


def idx_bits(m):
    b = 0
    while (1 << b) < m:
        b += 1
    return b


def prune(w, n, m):
    """nm_prune(): per column and m-group keep n entries by |value|, strict > so ties go to the lower row."""
    for c in range(N):
        for g in range(0, K, m):
            keep = [False] * m
            for _ in range(n):
                best, best_mag = -1, -1
                for r in range(m):
                    if keep[r]:
                        continue
                    mag = abs(w[g + r][c])
                    if mag > best_mag:
                        best_mag, best = mag, r
                if best >= 0:
                    keep[best] = True
            for r in range(m):
                if not keep[r]:
                    w[g + r][c] = 0


def compress(w, n, m):
    """nm_compress(): kept nonzeros in row order, then pad with unused rows, then sort the group by idx."""
    kc = K // m * n
    wc = [[0] * N for _ in range(kc)]
    idx = [[0] * N for _ in range(kc)]
    for c in range(N):
        for g in range(K // m):
            vals, used = [], [False] * m
            for r in range(m):
                v = w[g * m + r][c]
                if v != 0:
                    assert len(vals) < n, "w is not n:m pruned"
                    vals.append((r, v))
                    used[r] = True
            for r in range(m):
                if len(vals) >= n:
                    break
                if not used[r]:
                    vals.append((r, 0))
            vals.sort(key=lambda t: t[0])
            for s, (r, v) in enumerate(vals):
                wc[g * n + s][c] = v
                idx[g * n + s][c] = r
    return wc, idx


def pack_tile_spad(idx, t, jt, m):
    """nm_pack_meta_spad() of index tile (t, jt): idx[r][c] at bit (r*DIM + c)*b, little-endian bytes."""
    b = idx_bits(m)
    rows = (DIM * DIM * b + DIM * 8 - 1) // (DIM * 8)
    out = bytearray(rows * DIM)
    for r in range(DIM):
        for c in range(DIM):
            v = idx[t * DIM + r][jt * DIM + c] & ((1 << b) - 1)
            p = (r * DIM + c) * b
            for k in range(b):
                if v >> k & 1:
                    out[(p + k) // 8] |= 1 << ((p + k) % 8)
    return bytes(out)


def i8(rows):
    return bytes(v & 0xFF for row in rows for v in row)


def incbin(sym, path, align=64):
    return (f'__asm__(".section .rodata.microloop,\\"a\\",@progbits\\n.balign {align}\\n.globl {sym}\\n{sym}:\\n'
            f'.incbin \\"{path}\\"\\n.previous");\n')


def main():
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__)
    out, n, m = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    seed = int(sys.argv[4]) if len(sys.argv) == 5 else 20261117
    if m != 2 * n or m & (m - 1) or K % (2 * DIM) or (K // 2) % DIM:
        sys.exit("need m == 2n, m a power of 2")
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    a = [[rng.randint(-128, 127) for _ in range(K)] for _ in range(M_ROWS)]
    w = [[rng.randint(-128, 127) for _ in range(N)] for _ in range(K)]
    prune(w, n, m)
    wc, idx = compress(w, n, m)
    kb, jt_n = K // (2 * DIM), N // DIM
    idxsp = b"".join(pack_tile_spad(idx, t, jt, m) for t in range(kb) for jt in range(jt_n))
    wcols = [[w[z][x] for z in range(K)] for x in range(N)]
    c = [[sum(map(mul, a[y], wcols[x])) for x in range(N)] for y in range(M_ROWS)]
    # cross-check the compressed form against the dense pruned matrix (same math the sparse array does)
    for y in range(0, M_ROWS, 7):
        for x in range(N):
            s = sum(a[y][g * m + idx[g * n + q][x]] * wc[g * n + q][x] for g in range(K // m) for q in range(n))
            assert s == c[y][x], "compressed form disagrees with the dense reference"
    files = {"A.bin": i8(a), "W.bin": i8(w), "WC.bin": i8(wc), "IDX.bin": i8(idx), "IDXSP.bin": idxsp,
             "C.bin": b"".join(struct.pack("<i", v) for row in c for v in row)}
    sums = {}
    for fn, data in files.items():
        (out / fn).write_bytes(data)
        sums[fn] = hashlib.sha256(data).hexdigest()
    hdr = ["// generated by gen_micro_loop.py, do not edit\n", "#ifndef MICRO_LOOP_DATA_H\n#define MICRO_LOOP_DATA_H\n",
           "#include <stdint.h>\n",
           f"#define D_NM_N {n}\n#define D_NM_M {m}\n#define D_M {M_ROWS}\n#define D_K {K}\n#define D_N {N}\n",
           f"#define D_SEED {seed}\n#define D_IDXSP_BYTES {len(idxsp)}\n"]
    for fn, s in sums.items():
        hdr.append(f"// sha256 {fn} {s}\n")
    hdr.append('#define D_SHA_C "' + sums["C.bin"][:16] + '"\n')
    hdr.append("extern const int8_t d_A[]; extern const int8_t d_W[]; extern const int8_t d_WC[];\n"
               "extern const uint8_t d_IDX[]; extern const uint8_t d_IDXSP[]; extern const int32_t d_C[];\n")
    for sym, fn in (("d_A", "A.bin"), ("d_W", "W.bin"), ("d_WC", "WC.bin"), ("d_IDX", "IDX.bin"),
                    ("d_IDXSP", "IDXSP.bin"), ("d_C", "C.bin")):
        hdr.append(incbin(sym, (out / fn).resolve()))
    hdr.append("#endif\n")
    (out / "data.h").write_text("".join(hdr))
    print(f"gen_micro_loop: {n}:{m} seed {seed} -> {out} C.bin sha256 {sums['C.bin'][:16]}")


if __name__ == "__main__":
    main()
