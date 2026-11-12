#!/usr/bin/env python3
"""Host-side data generator for the streaming benchmark.

For every layer (M x K x N, int8) and every pattern (2:4, 4:8) it writes, into <out>/<layer>/<pat>/:
  A.bin      M x K int8, row-major (same for both patterns of a layer)
  W.bin      K x N int8, the n:m-pruned weights in the normal dense layout (what the dense runs multiply by)
  WC.bin     (K/2) x N int8, the compressed weights (kept values of each m-group, in increasing row order)
  IDX.bin    (K/2) x N uint8, which row inside its m-group each kept value came from (the "index notes", unpacked)
  META.bin   the index notes packed exactly like gemmini_nm.h's nm_pack_meta(), one DIM x DIM tile after another,
             tile order [t][jt] (t = compressed row tile, jt = column tile), 2*nm_meta_cmds(m) uint64 words per tile
  SREF.bin   int32 reference values of the sampled rows (NSAMPLE x N)
  data.h     C header: dimensions, pattern, 64-bit hash of the whole reference C, sampled row numbers, and the
             arrays above pulled in with .incbin (so the binaries stay quick to compile)
  ref.json   the same facts for the host-side log checker (hash, sampled rows, sha256 of every .bin)

Data: full-range int8 (-128..127, uniform), numpy default_rng(seed) with seed = BASE_SEED + layer index.
Pruning: in every column, each group of m consecutive K rows keeps its n largest |values| (ties to the lower row),
the rule of gemmini_nm.h's nm_prune(). Reference C = A @ W_pruned in exact integer arithmetic.
The simulated CPU never generates data or computes a reference; it only hashes its output and compares the samples.

usage: gen_data.py <out_dir> [layer ...]      (default: every layer in LAYERS)
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

DIM = 16
BASE_SEED = 20261109
NSAMPLE = 8
PATTERNS = {"24": (2, 4), "48": (4, 8)}

# name: (M, K, N). K must be a multiple of 2*DIM (one compressed tile covers 2*DIM rows of K), N of DIM.
LAYERS = {
    "small":     (64, 256, 128),     # smoke test + timing extrapolation
    "bert_qkv":  (128, 768, 768),    # BERT-base, 128 tokens, Q/K/V/O projection
    "bert_ffn1": (128, 768, 3072),   # BERT-base FFN up
    "bert_ffn2": (128, 3072, 768),   # BERT-base FFN down
    "rn50_conv": (196, 2304, 256),   # ResNet-50 3x3 conv (14x14 output, 256 in-ch x 9 -> 256 out-ch) as a matmul
    "edge":      (36, 128, 64),      # partial last row tile (M % 16 = 4), two K steps: cheap RTL check of the edge paths
}

FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
MASK64 = (1 << 64) - 1


def fnv1a64_words(c):
    """stream_bench.c hash_c(): C (row-major int32) read as little-endian uint64 words (two values each),
    64-bit FNV-1a in 4 interleaved lanes (lane l takes words i with i % 4 == l, starts at OFFSET + l),
    then the 4 lane values folded with FNV-1a starting from OFFSET."""
    w = np.ascontiguousarray(c.astype("<i4")).view("<u8").ravel()
    assert w.size % 4 == 0
    lanes = [(FNV_OFFSET + l) for l in range(4)]
    for l in range(4):
        h = lanes[l]
        for v in w[l::4].tolist():
            h = ((h ^ v) * FNV_PRIME) & MASK64
        lanes[l] = h
    h = FNV_OFFSET
    for v in lanes:
        h = ((h ^ v) * FNV_PRIME) & MASK64
    return h


def prune(w, n, m):
    """nm_prune(): per column, per m-group of rows, keep the n largest |w| (ties to the lower row)."""
    k, j = w.shape
    assert k % m == 0
    g = w.reshape(k // m, m, j).astype(np.int16)
    mag = np.abs(g)
    # stable sort on -mag keeps the lower row first among equals
    order = np.argsort(-mag, axis=1, kind="stable")
    keep = np.zeros_like(g, dtype=bool)
    np.put_along_axis(keep, order[:, :n, :], True, axis=1)
    return np.where(keep, g, 0).reshape(k, j).astype(np.int8), keep.reshape(k, j)


def compress(w, keep, n, m):
    """Kept positions of each group, in increasing row order -> values (k/m*n x j) and in-group indexes.
    A kept value may be 0 (the data had a 0 there); that is still a legal (index, value) pair."""
    k, j = w.shape
    kg = keep.reshape(k // m, m, j)
    assert (kg.sum(axis=1) == n).all()
    # row indexes of the kept entries, ascending: argsort of ~keep (stable) puts kept rows first in row order
    rows = np.argsort(~kg, axis=1, kind="stable")[:, :n, :]          # (k/m, n, j)
    vals = np.take_along_axis(w.reshape(k // m, m, j), rows, axis=1)
    return vals.reshape(k // m * n, j).astype(np.int8), rows.reshape(k // m * n, j).astype(np.uint8)


def decompress(wc, idx, k, n, m):
    kc, j = wc.shape
    w = np.zeros((k, j), dtype=np.int8)
    g = np.arange(kc) // n
    rows = g[:, None] * m + idx.astype(np.int64)
    np.put_along_axis(w, rows, wc, axis=0)  # every (row, col) written at most once
    return w


def idx_bits(m):
    b = 0
    while (1 << b) < m:
        b += 1
    return b


def meta_cmds(m):
    rows_per_cmd = 2 * (64 // (DIM * idx_bits(m)))
    return (DIM + rows_per_cmd - 1) // rows_per_cmd


def pack_meta(idx, m):
    """nm_pack_meta() for every full DIM x DIM tile, order [t][jt]."""
    kc, j = idx.shape
    assert kc % DIM == 0 and j % DIM == 0
    ib = idx_bits(m)
    row_bits = DIM * ib
    rows_per_reg = 64 // row_bits
    words = 2 * meta_cmds(m)
    out = np.zeros((kc // DIM, j // DIM, words), dtype=np.uint64)
    for t in range(kc // DIM):
        for jt in range(j // DIM):
            tile = idx[t * DIM:(t + 1) * DIM, jt * DIM:(jt + 1) * DIM].astype(np.uint64)
            r = 0
            for wd in range(words):
                v = 0
                for q in range(rows_per_reg):
                    if r < DIM:
                        for c in range(DIM):
                            v |= (int(tile[r, c]) & ((1 << ib) - 1)) << (q * row_bits + c * ib)
                    r += 1
                out[t, jt, wd] = v
    return out


def exact_matmul(a, w):
    """A @ W exactly. float64 is exact here (|products| <= 2^14, |sums| <= K * 2^14 < 2^53); a few rows are
    re-done in int64 as a cross-check."""
    c = (a.astype(np.float64) @ w.astype(np.float64))
    assert np.abs(c).max() < 2 ** 31
    c = c.astype(np.int64)
    for r in (0, a.shape[0] // 2, a.shape[0] - 1):
        assert (a[r].astype(np.int64) @ w.astype(np.int64) == c[r]).all()
    return c.astype(np.int32)


def incbin(sym, path, align=64):
    return (f'__asm__(".section .rodata.sbench,\\"a\\",@progbits\\n.balign {align}\\n.globl {sym}\\n{sym}:\\n'
            f'.incbin \\"{path}\\"\\n.previous");\n')


def sample_rows(m_rows, rng):
    rows = {0, 1, m_rows // 2, m_rows - 2, m_rows - 1}
    if m_rows % DIM:
        rows.add(m_rows - m_rows % DIM)  # first row of the partial row tile
    while len(rows) < NSAMPLE:
        rows.add(int(rng.integers(0, m_rows)))
    return sorted(rows)[:NSAMPLE] if len(rows) > NSAMPLE else sorted(rows)


def gen_layer(out, li, name, dims):
    mm, kk, nn = dims
    assert kk % (2 * DIM) == 0 and nn % DIM == 0, (name, dims)
    seed = BASE_SEED + li
    rng = np.random.default_rng(seed)
    a = rng.integers(-128, 128, size=(mm, kk), dtype=np.int16).astype(np.int8)
    w_full = rng.integers(-128, 128, size=(kk, nn), dtype=np.int16).astype(np.int8)
    srows = sample_rows(mm, rng)
    for pat, (n, m) in PATTERNS.items():
        d = out / name / pat
        d.mkdir(parents=True, exist_ok=True)
        wp, keep = prune(w_full, n, m)
        wc, idx = compress(wp, keep, n, m)
        assert (decompress(wc, idx, kk, n, m) == wp).all()
        # nm_ref_sparse math == dense math on the pruned weights (checked on a few rows)
        for r in srows[:3]:
            g = np.arange(wc.shape[0]) // n
            ar = a[r].astype(np.int64)[g[:, None] * m + idx.astype(np.int64)]  # (kc, j) activations each weight grabs
            sp = (ar * wc.astype(np.int64)).sum(axis=0)
            assert (sp == a[r].astype(np.int64) @ wp.astype(np.int64)).all()
        meta = pack_meta(idx, m)
        c = exact_matmul(a, wp)
        h = fnv1a64_words(c)
        sref = c[srows].astype(np.int32)
        files = {"A.bin": a, "W.bin": wp, "WC.bin": wc, "IDX.bin": idx, "META.bin": meta.astype("<u8"),
                 "SREF.bin": sref.astype("<i4")}
        sums = {}
        for fn, arr in files.items():
            raw = np.ascontiguousarray(arr).tobytes()
            (d / fn).write_bytes(raw)
            sums[fn] = hashlib.sha256(raw).hexdigest()
        hdr = [f"// generated by experiments/streaming/gen/gen_data.py; do not edit\n",
               f"// layer {name}: M={mm} K={kk} N={nn}, pattern {n}:{m}, data seed {seed}\n",
               "#ifndef SBENCH_DATA_H\n#define SBENCH_DATA_H\n#include <stdint.h>\n",
               f'#define L_NAME "{name}"\n#define L_M {mm}\n#define L_K {kk}\n#define L_N {nn}\n',
               f"#define L_NM_N {n}\n#define L_NM_M {m}\n#define L_SEED {seed}\n",
               f"#define L_HASH 0x{h:016x}ULL\n#define L_NSAMPLE {len(srows)}\n",
               f"#define L_META_WORDS {2 * meta_cmds(m)}\n",
               "static const int l_sample_rows[L_NSAMPLE] = {" + ", ".join(map(str, srows)) + "};\n",
               "extern const int8_t l_A[];\nextern const int8_t l_W[];\nextern const int8_t l_WC[];\n",
               "extern const uint64_t l_META[];\nextern const int32_t l_SREF[];\n"]
        for sym, fn in (("l_A", "A.bin"), ("l_W", "W.bin"), ("l_WC", "WC.bin"), ("l_META", "META.bin"),
                        ("l_SREF", "SREF.bin")):
            hdr.append(incbin(sym, (d / fn).resolve()))
        hdr.append("#endif\n")
        (d / "data.h").write_text("".join(hdr))
        ref = {"layer": name, "M": mm, "K": kk, "N": nn, "n": n, "m": m, "seed": seed,
               "hash": f"0x{h:016x}", "sample_rows": srows, "sha256": sums,
               "kept_fraction": float(np.count_nonzero(wp)) / wp.size,
               "meta_words_per_tile": 2 * meta_cmds(m),
               "bytes": {"A": a.size, "W": wp.size, "WC": wc.size, "META": meta.size * 8, "C_int32": c.size * 4}}
        (d / "ref.json").write_text(json.dumps(ref, indent=1) + "\n")
        print(f"{name:10s} {n}:{m}  M={mm:4d} K={kk:5d} N={nn:5d}  hash=0x{h:016x}  samples={srows}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1]).resolve()
    want = sys.argv[2:] or list(LAYERS)
    for li, (name, dims) in enumerate(LAYERS.items()):
        if name in want:
            gen_layer(out, li, name, dims)


if __name__ == "__main__":
    main()
