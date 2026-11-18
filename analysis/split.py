#!/usr/bin/env python3
# preprocessing vs runtime, per chip, from one or more fair benchmark run folders (./run-flow.sh fair).
#   preprocessing = the one-time cpu work that turns dense weights into the sparse format
#                   (fair_perf's prep_cold / prep_warm lines: prune, compress, pack_meta). dense needs none.
#   runtime       = one timed matmul (the existing fair_perf runs), split into
#                   - index issue:  cpu cycles spent issuing the index tiles (cpu_meta_only, per tile, times
#                                   the tiles that variant sends; an estimate from the cpu-only run)
#                   - other issue:  the rest of the cpu issue time (preload / compute instructions, stalls)
#                   - drain:        after the last instruction is issued, waiting for gemmini to finish
# also: how many runs it takes for sparse's per-run saving (if any) to pay back the preprocessing.
# every number is computed per seed; split.md shows the min-max over seeds, the chart the mean.
#
# writes <first run>/derived/split.csv (one row per chip, variant and seed), split.md and split.png.
# nothing is written into the repo tree.
# run: ~/chipyard/.conda-env/bin/python analysis/split.py [RUN ...]   (default: newest fair run; exit 2 if none)
import csv, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verification"))
import nmdata  # noqa: E402

LABEL = {"berkeley": "Berkeley", "sameprog": "ours, sparsity off", "nm24": "ours 2:4", "nm48": "ours 4:8"}
SPARSE = {"sparse": ("fresh weights", "dense"), "sparse_batched": ("fresh weights, batched", "dense"),
          "sparse_reuse": ("weights reused", "dense_reuse")}
DENSE = {"dense": "fresh weights", "dense_reuse": "weights reused"}
DIM = nmdata.DIM
# colours: categorical slots 1-3 of the reference palette, in fixed order; light surface
INK, INK2, SURF = "#0b0b0b", "#52514e", "#fcfcfb"
C = {"prune": "#2a78d6", "compress": "#eb6834", "pack_meta": "#1baf7a",
     "index_issue": "#2a78d6", "other_issue": "#eb6834", "drain": "#1baf7a"}


def split_log(chip, log):
    """rows for one log (one chip, one seed)."""
    h, p, sparse = log["header"], log["perf"], chip.startswith("nm")
    if h is None: sys.exit(f"{log['path']}: no 'fair_perf:' header line (not a fair_perf log?)")
    if not log["passed"] or log["failed"]: sys.exit(f"{log['path']}: the run did not pass; not splitting it")
    if sparse and not log["prep"]:
        sys.exit(f"{log['path']}: no prep_cold/prep_warm lines: made by an older fair_perf.c, rebuild with ./run-flow.sh fair-build")
    kc = h["k"] * h["n"] // h["m"]
    # index tiles sent: one per preload/compute pair with fresh weights, one per weight block when reused
    tiles = {"sparse": h["i"] // DIM * h["j"] // DIM * kc // DIM, "sparse_batched": h["i"] // DIM * h["j"] // DIM * kc // DIM,
             "sparse_reuse": h["j"] // DIM * kc // DIM}
    per_tile = p["cpu_meta_only"]["total"] / p["cpu_meta_only"]["pairs"] if sparse else 0.0
    pw, pc = log["prep"].get("prep_warm", {}), log["prep"].get("prep_cold", {})
    rows = []
    for var in ([v for v in SPARSE if v in p] if sparse else [v for v in DENSE if v in p]):
        r = p[var]
        idx = min(per_tile * tiles[var], r["issued"]) if sparse else 0.0
        row = {"chip": chip, "label": LABEL[chip], "seed": log["seed"], "pattern": f"{h['n']}:{h['m']}" if sparse else "dense",
               "variant": SPARSE[var][0] if sparse else DENSE[var], "runtime_total": r["total"], "index_issue": round(idx),
               "other_issue": round(r["issued"] - idx), "drain": r["total"] - r["issued"], "array_active": r.get("ex_active", ""),
               "prep_cold": pc["prep"] if sparse else 0, "prep_warm": pw["prep"] if sparse else 0,
               "prune": pw["prune"] if sparse else 0, "compress": pw["compress"] if sparse else 0,
               "pack_meta": pw["pack_meta"] if sparse else 0, "own_dense_runtime": "", "runs_to_repay_prep": ""}
        if sparse:
            saving = p[SPARSE[var][1]]["total"] - r["total"]
            row["own_dense_runtime"] = p[SPARSE[var][1]]["total"]
            row["runs_to_repay_prep"] = round(pw["prep"] / saving, 1) if saving > 0 else "never"
        rows.append(row)
    return rows


def span(vals, f="{:,}"):
    """min-max text of the values over seeds ('never' wins if any seed never repays)."""
    if "never" in vals: return "never" if all(v == "never" for v in vals) else "never on some seeds"
    lo, hi = min(vals), max(vals)
    return f.format(lo) if lo == hi else f"{f.format(lo)}-{f.format(hi)}"


def main():
    try:
        runs = nmdata.find_runs(sys.argv[1:] or None)
        fair = nmdata.load_fair(runs, require=())
    except nmdata.NoResults as e:
        nmdata.die_no_results(e)
    rows = [r for chip, logs in fair.items() for log in logs.values() for r in split_log(chip, log)]
    out = runs[0] / "derived"; out.mkdir(exist_ok=True)
    with open(out / "split.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    groups = {}
    for r in rows: groups.setdefault((r["chip"], r["variant"]), []).append(r)
    h = next(iter(next(iter(fair.values())).values()))["header"]
    md = [f"# Preprocessing vs. runtime ({', '.join(r.name for r in runs)})", "",
          f"Cycles from `fair_perf.c` (i={h['i']} k={h['k']} j={h['j']}), min-max over seeds. Preprocessing is one-time "
          "CPU work per weight set (warm = second pass, cold = first pass with cache misses); runtime is one timed "
          "matmul. Index issue is estimated from the CPU-only `cpu_meta_only` run.", "",
          "| Chip | Weights | Seeds | Runtime | Index issue | Other issue | Drain | Prep (warm) | Prep (cold) | Runs to repay prep |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for (chip, var), g in groups.items():
        col = lambda k: span([r[k] for r in g])
        md.append(f"| {LABEL[chip]} | {var} | {len(g)} | {col('runtime_total')} | {col('index_issue')} | {col('other_issue')} | "
                  f"{col('drain')} | {col('prep_warm')} | {col('prep_cold')} | "
                  f"{span([r['runs_to_repay_prep'] for r in g], '{}') if chip.startswith('nm') else ''} |")
    md += ["", "'Runs to repay prep' compares each sparse run with the same chip's own dense run of the same matmul in the "
           "same log; 'never' means the sparse run is not faster, so the preprocessing is never paid back."]
    (out / "split.md").write_text("\n".join(md) + "\n")

    # two charts, one axis each (prep is ~100x a run, so they can't share a scale); bars are means over seeds
    mean = [{**g[0], **{k: sum(r[k] for r in g) / len(g) for k in C}} for g in groups.values()]
    plt.rcParams.update({"font.size": 9, "text.color": INK, "axes.labelcolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK, "axes.edgecolor": "#d5d4cf"})
    sp = [r for r in mean if r["pattern"] != "dense" and r["variant"] == "fresh weights"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 2.0 + 0.32 * (len(sp) + len(mean))),
                                 gridspec_kw={"height_ratios": [max(len(sp), 1), len(mean)]}, facecolor=SURF)
    def stack(ax, items, parts, title, names):
        ax.set_facecolor(SURF)
        ys = list(range(len(items)))[::-1]
        for y, r in zip(ys, items):
            x = 0
            for p in parts:
                ax.barh(y, r[p], left=x, height=0.55, color=C[p], edgecolor=SURF, linewidth=2, label=p.replace("_", " ") if y == ys[0] else None)
                x += r[p]
            ax.text(x, y, f"  {x:,.0f}", va="center", color=INK2, fontsize=8)
        ax.set_yticks(ys, [names(r) for r in items])
        ax.set_title(title, loc="left", fontsize=10, color=INK, pad=18)
        ax.set_xlabel("cycles (mean over seeds)"); ax.xaxis.grid(True, color="#ebeae6", linewidth=0.8); ax.set_axisbelow(True)
        for s in ("top", "right", "left"): ax.spines[s].set_visible(False)
        ax.margins(x=0.12)
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, ncol=len(parts), fontsize=8,
                  borderaxespad=0, handlelength=1.2)
    stack(a1, sp, ["prune", "compress", "pack_meta"], "Preprocessing (one time per weight set, warm)",
          lambda r: r["label"])
    stack(a2, mean, ["index_issue", "other_issue", "drain"], "Runtime (one matmul)",
          lambda r: f"{r['label']}, {r['variant']}")
    fig.tight_layout()
    fig.savefig(out / "split.png", dpi=160, facecolor=SURF)
    print("\n".join(md)); print(f"\nwrote {out}/split.csv, split.md, split.png")


if __name__ == "__main__":
    main()
