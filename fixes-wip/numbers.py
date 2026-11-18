#!/usr/bin/env python3
"""Every number the doc fixes use, computed from the recorded logs (read-only).

run: ~/chipyard/.conda-env/bin/python numbers.py /home/hunter/gemmini-sparsity
"""
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo / "verification"))
import nmdata  # noqa: E402

fair = nmdata.load_fair()
s = nmdata.summary(fair)
b, s24, s48 = s["berkeley"], s["2:4"], s["4:8"]
sp = fair["nm24_sameprog"]["perf"]
p24, p48, pb = fair["nm24"]["perf"], fair["nm48"]["perf"], fair["berkeley"]["perf"]

print("== README table (as printed now)")
for k in ("busy_reuse", "busy_fresh", "reuse", "fresh"):
    print(f"  {k:<11} berkeley {b[k]:>5}  2:4 {s24[k]:>5} ({b[k] / s24[k]:.3f}x)  4:8 {s48[k]:>5} ({b[k] / s48[k]:.3f}x)")

print("\n== fresh-weights grid time (ex_active of 'dense' vs 'sparse')")
print(f"  berkeley dense ex_active {pb['dense']['ex_active']}  2:4 sparse {p24['sparse']['ex_active']}"
      f"  4:8 sparse {p48['sparse']['ex_active']}  ratio {pb['dense']['ex_active'] / p24['sparse']['ex_active']:.4f}")

print("\n== same program (fair_perf_dense_only) on berkeley's chip vs our 2:4 chip")
for v in ("dense", "dense_reuse"):
    a, c = pb[v], sp[v]
    d = c["total"] - a["total"]
    print(f"  {v:<12} total berkeley {a['total']} ours {c['total']} diff {d:+d} ({abs(d) / a['total'] * 100:.3f}%)"
          f" | ex_active {a['ex_active']} vs {c['ex_active']} | tail (total-issued) {a['total'] - a['issued']} vs {c['total'] - c['issued']}"
          f" | issued {a['issued']} vs {c['issued']}")
    diffs = {k: (a[k], c[k]) for k in a if a[k] != c[k]}
    print(f"     counters that differ: {diffs}")

print("\n== same-build ratios (dense loop and sparse loop from the SAME binary, our chip)")
for pat, p in (("2:4", p24), ("4:8", p48)):
    for dv, sv in (("dense_reuse", "sparse_reuse"), ("dense", "sparse")):
        print(f"  {pat} {dv}/{sv}: {p[dv]['total']} / {p[sv]['total']} = {p[dv]['total'] / p[sv]['total']:.4f}")

print("\n== mixed-build effect: dense loops, berkeley DENSE_ONLY build vs full builds (same loop source)")
for name, p in (("dense_only on nm24 chip", sp), ("fair_perf_24 on nm24", p24), ("fair_perf_48 on nm48", p48)):
    print(f"  {name:<24} dense {p['dense']['total']}  dense_reuse {p['dense_reuse']['total']}")
print(f"  dense_reuse: {p24['dense_reuse']['total']} vs {sp['dense_reuse']['total']} on the same chip"
      f" = {(p24['dense_reuse']['total'] / sp['dense_reuse']['total'] - 1) * 100:+.2f}%")

print("\n== CPU-only issue time (fair, processor alone)")
print(f"  fresh: berkeley {b['cpu_fresh']} 2:4 {s24['cpu_fresh']} 4:8 {s48['cpu_fresh']}")

print("\n== original benchmark: CPU-only issue time as a share of each total (chipyard-setup-notes 65-85%)")
orig = nmdata.load_original()
fr = []
for cfg in ("nm24", "nm48"):
    pp = orig[cfg]["nm_sparse_perf"]["perf"]
    for v in ("dense", "sparse", "sparse_nat", "dense_reuse", "sparse_reuse"):
        fr.append((pp["cpu_" + v]["total"] / pp[v]["total"], cfg, v))
lo, hi = min(fr), max(fr)
print(f"  min {lo[0] * 100:.2f}% ({lo[1]} {lo[2]})  max {hi[0] * 100:.2f}% ({hi[1]} {hi[2]})  -> {lo[0] * 100:.0f}-{hi[0] * 100:.0f}%")

print("\n== pattern fidelity (energy kept), min-max over the two synthetic distributions")
fid = nmdata.load_fidelity()
for rule in ("4:8", "2:4", "paired 4:8", "no pattern"):
    v = [fid[(d, rule)][0] for d in ("bell curve", "heavy tail")]
    print(f"  {rule:<11} {v}  -> {min(v):.0f}-{max(v):.0f}%")

print("\n== stall explanation numbers (NEXT-STEPS): fresh-weight sparse grid time per tile vs dense")
print(f"  sparse fresh ex_active/tiles = {p24['sparse']['ex_active']}/{p24['sparse']['tiles']} = {p24['sparse']['ex_active'] / p24['sparse']['tiles']:.1f}")
print(f"  berkeley dense fresh ex_active/tiles = {pb['dense']['ex_active']}/{pb['dense']['tiles']} = {pb['dense']['ex_active'] / pb['dense']['tiles']:.1f}")
print(f"  sparse reuse ex_active/tiles = {p24['sparse_reuse']['ex_active']}/{p24['sparse_reuse']['tiles']} = {p24['sparse_reuse']['ex_active'] / p24['sparse_reuse']['tiles']:.1f}")
print(f"  berkeley dense reuse ex_active/tiles = {pb['dense_reuse']['ex_active']}/{pb['dense_reuse']['tiles']} = {pb['dense_reuse']['ex_active'] / pb['dense_reuse']['tiles']:.2f}")
