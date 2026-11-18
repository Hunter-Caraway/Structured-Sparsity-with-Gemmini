#!/usr/bin/env python3
# Streaming-benchmark analytics: tables, area-normalised throughput, figures, and numbers.json for the summary.
# Every number comes from these inputs (read-only; nothing in them is modified):
#   experiments/streaming/runs/<stamp>/results.csv   (scripts/collect.py; default stamp 20261109-144252)
#   analysis/area/area.csv                           (analysis/area.py; whole-Gemmini standard-cell area)
#   verification/runs/fair-20261103-151404/          (fair benchmark, read through verification/nmdata.py)
#   verification/pattern_fidelity.out                (pattern comparison, through nmdata.load_fidelity)
# Writes experiments/streaming/analysis/out/: stream_table.csv, area_norm.csv, numbers.json, tables.md,
#   fig-s1-cycles, fig-s2-speedup, fig-s3-counters, fig-s4-perf-per-mm2 (-light.png, -dark.png, .pdf).
# Definitions (also written to tables.md):
#   MACs            = M*K*N, the dense layer's multiply-accumulates. Every variant computes the same (pruned) answer, so
#                     MACs/cycle compares variants on one job; for sparse rows half of those MACs are skipped zeros.
#   vs Berkeley best= stock-chip `berkeley` cycles / row cycles (>1 = faster).
#   vs dense_stream = stock-chip `dense_stream` cycles / row cycles: the same hand tiler, dense weights. The stock chip is
#                     the reference for every chip (nm48 has no dense_stream row for the big layers); the 2:4 chip's own
#                     dense_stream is listed next to it (vs_dense_same_chip) and agrees within dense_chip_spread_pct.
#   area            = whole-Gemmini standard-cell area of the chip the row ran on (SRAM macros excluded), mm^2.
#   rdma_bytes      = counter / 4 (the counter adds the request size on every 16 B beat of a 64 B request).
#   rs_full share   = rs_full counter / total cycles. Despite its name, rs_full is !io.alloc.ready
#                     (gemmini ReservationStation.scala:611): it counts every cycle in which no command is allocated
#                     into the reservation station, idle cycles included. It does NOT measure a full queue or a blocked
#                     CPU. Its window (own counter_configure to own read) is ~130-175 cycles longer than the timed
#                     region, so it can exceed 100% on tiny layers. Tables only; not plotted.
#                     See experiments/streaming/worklogs/investigate.md sections 1, 9 and 17.
#   Seeds: the small layer ran seeds 1-3; the script requires them to be identical and reports one number.
# run: ~/chipyard/.conda-env/bin/python experiments/streaming/analysis/stream_analysis.py [RUN_DIR]
import csv, json, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ALLOW_MIXED = "--allow-mixed-sims" in sys.argv
_ARGS = [a for a in sys.argv[1:] if a != "--allow-mixed-sims"]
RUN = Path(_ARGS[0]).resolve() if _ARGS else REPO / "experiments/streaming/runs/20261109-144252"
FAIR = REPO / "verification/runs/fair-20261103-151404"
AREA = REPO / "analysis/area/area.csv"
OUT = HERE / "out"
sys.path.insert(0, str(REPO / "verification"))
import nmdata

LAYERS = ["small", "bert_qkv", "bert_ffn1", "bert_ffn2", "rn50_conv"]   # edge (36x128x64) = path check: tables only
ALL_LAYERS = ["edge"] + LAYERS
LNAME = {"edge": "edge 36×128×64", "small": "small 64×256×128", "bert_qkv": "BERT QKV 128×768×768",
         "bert_ffn1": "BERT FFN1 128×768×3072", "bert_ffn2": "BERT FFN2 128×3072×768", "rn50_conv": "ResNet-50 conv 196×2304×256"}
LTICK = {"small": "small\n64×256×128", "bert_qkv": "BERT QKV\n128×768×768", "bert_ffn1": "BERT FFN1\n128×768×3072",
         "bert_ffn2": "BERT FFN2\n128×3072×768", "rn50_conv": "ResNet-50 conv\n196×2304×256"}
CHIP_AREA_KEY = {"stock": "berkeley", "nm24": "nm24", "nm48": "nm48"}
COUNTERS = ["total_cycles", "cpu_issue_done", "ex_active", "rdma_active", "wdma_active", "load_active", "store_active",
            "rs_full", "loop_matmul_active", "rdma_bytes"]
# the four series in the figures: (key, chip, variant, label)
SERIES = [("berkeley", "stock", "berkeley", "Berkeley tiled_matmul_auto (stock chip)"),
          ("dense", "stock", "dense_stream", "Hand tiler, dense (stock chip)"),
          ("sp24", "nm24", "sparse_stream", "Hand tiler, 2:4 sparse"),
          ("sp48", "nm48", "sparse_stream", "Hand tiler, 4:8 sparse")]


MIX = {}   # chip -> {sim_sha256: rows} for chips with several builds


def load_results():
    rows = list(csv.DictReader(open(RUN / "results.csv")))
    bad = [r["log"] for r in rows if r["verified"] != "yes"]
    if bad: sys.exit(f"unverified rows in results.csv: {bad}")
    per = defaultdict(lambda: defaultdict(int))
    for r in rows: per[r["chip"]][r["sim_sha256"]] += 1
    # one chip must come from one simulator build unless --allow-mixed-sims
    MIX.clear(); MIX.update({c: dict(m) for c, m in sorted(per.items()) if len(m) > 1})
    if MIX and not ALLOW_MIXED:
        lines = [f"  chip {c}: sim_sha256 {h} ({n} rows)" for c, m in MIX.items() for h, n in sorted(m.items())]
        sys.exit("a chip has rows from more than one simulator build:\n" + "\n".join(lines) +
                 "\nre-run with --allow-mixed-sims to continue; the outputs will then state the mix.")
    g = defaultdict(list)
    for r in rows: g[(r["layer"], r["chip"], r["variant"])].append(r)
    out = {}
    for k, rs in g.items():
        vals = {c: {int(r[c]) for r in rs} for c in COUNTERS}
        varying = [c for c, v in vals.items() if len(v) != 1]
        if varying: sys.exit(f"{k}: seeds {[r['seed'] for r in rs]} differ in {varying}; this script reports one number per row")
        r0 = rs[0]
        out[k] = {"layer": k[0], "chip": k[1], "variant": k[2], "M": int(r0["M"]), "K": int(r0["K"]), "N": int(r0["N"]),
                  "pattern": r0["pattern"], "seeds": ",".join(sorted(r["seed"] for r in rs)),
                  "hosts": ",".join(sorted({r["host"] for r in rs})), **{c: int(r0[c]) for c in COUNTERS}}
    return out, len(rows)


def load_area():
    a = {r["chip"]: float(r["area_um2"]) for r in csv.DictReader(open(AREA)) if r["block"] == "Gemmini"}
    blocks = [r for r in csv.DictReader(open(AREA))]
    return {chip: a[k] / 1e6 for chip, k in CHIP_AREA_KEY.items()}, blocks


def build():
    res, nrows = load_results()
    area, area_blocks = load_area()
    table = []
    for (layer, chip, variant), r in sorted(res.items(), key=lambda kv: (ALL_LAYERS.index(kv[0][0]), kv[0][1], kv[0][2])):
        base = res[(layer, "stock", "berkeley")]["total_cycles"]
        dref = res[(layer, "stock", "dense_stream")]["total_cycles"]
        same = res.get((layer, chip, "dense_stream"))
        macs = r["M"] * r["K"] * r["N"]
        cyc = r["total_cycles"]
        mpc = macs / cyc
        table.append({**r, "macs": macs, "macs_per_cycle": round(mpc, 3), "array_util_dense_equiv": round(mpc / 256, 4),
                      "vs_berkeley_best": round(base / cyc, 4), "vs_dense_stream_stock": round(dref / cyc, 4),
                      "vs_dense_same_chip": round(same["total_cycles"] / cyc, 4) if same else "",
                      "rdma_bytes_real": r["rdma_bytes"] // 4,
                      "ex_active_share": round(r["ex_active"] / cyc, 4), "rdma_active_share": round(r["rdma_active"] / cyc, 4),
                      "rs_full_share": round(r["rs_full"] / cyc, 4),
                      "gemmini_area_mm2": round(area[chip], 4),
                      "macs_per_cycle_per_mm2": round(mpc / area[chip], 4),
                      "perf_per_mm2_vs_berkeley_best": round(base / cyc * area["stock"] / area[chip], 4)})
    return table, area, area_blocks, nrows


def fair_numbers():
    s = nmdata.summary(nmdata.load_fair([FAIR]))
    out = {}
    for row, mets in s.items():
        out[row] = {}
        for m, st in mets.items():
            if not st: continue
            if st["min"] != st["max"]: sys.exit(f"fair {row} {m} varies over seeds: {st}")
            out[row][m] = st["min"]
    seeds = sorted({sd for chip in nmdata.load_fair([FAIR]).values() for sd in chip})
    return out, seeds


def write_tables(table, area, area_blocks, fair, fair_seeds, nrows):
    OUT.mkdir(parents=True, exist_ok=True)
    cols = list(table[0])
    with open(OUT / "stream_table.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(table)
    acols = ["layer", "chip", "variant", "total_cycles", "macs", "macs_per_cycle", "gemmini_area_mm2",
             "macs_per_cycle_per_mm2", "vs_berkeley_best", "perf_per_mm2_vs_berkeley_best"]
    with open(OUT / "area_norm.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=acols); w.writeheader(); w.writerows({c: t[c] for c in acols} for t in table)
    T = {(t["layer"], t["chip"], t["variant"]): t for t in table}
    # numbers used in the text
    n = {"run": str(RUN.relative_to(REPO)), "rows": nrows, "rows_verified": nrows,
         "area_mm2": {k: round(v, 3) for k, v in area.items()},
         "area_overhead_pct": {k: round((area[k] / area["stock"] - 1) * 100, 1) for k in ("nm24", "nm48")},
         "area_blocks": {f"{b['chip']}/{b['block']}": float(b["area_um2"]) for b in area_blocks},
         "layers": {}, "fair": fair, "fair_seeds": fair_seeds}
    for L in ALL_LAYERS:
        d = {}
        for key, chip, var, _ in SERIES:
            t = T[(L, chip, var)]
            d[key] = {c: t[c] for c in ("total_cycles", "macs_per_cycle", "array_util_dense_equiv", "vs_berkeley_best",
                                        "vs_dense_stream_stock", "macs_per_cycle_per_mm2", "perf_per_mm2_vs_berkeley_best",
                                        "ex_active", "rdma_bytes_real", "rs_full_share", "ex_active_share", "seeds")}
        d["dims"] = [T[(L, "stock", "berkeley")][c] for c in ("M", "K", "N")]
        d["nm24_dense_vs_stock_dense_pct"] = round((T[(L, "nm24", "dense_stream")]["total_cycles"] /
                                                    T[(L, "stock", "dense_stream")]["total_cycles"] - 1) * 100, 2)
        for chip in ("nm24", "nm48"):
            if (L, chip, "berkeley") in T:
                d[f"{chip}_berkeley_vs_stock_pct"] = round((T[(L, chip, "berkeley")]["total_cycles"] /
                                                            T[(L, "stock", "berkeley")]["total_cycles"] - 1) * 100, 2)
        d["ex_active_sparse24_vs_dense_pct"] = round((T[(L, "nm24", "sparse_stream")]["ex_active"] /
                                                      T[(L, "stock", "dense_stream")]["ex_active"] - 1) * 100, 1)
        d["ex_active_sparse48_vs_dense_pct"] = round((T[(L, "nm48", "sparse_stream")]["ex_active"] /
                                                      T[(L, "stock", "dense_stream")]["ex_active"] - 1) * 100, 1)
        n["layers"][L] = d
    big = LAYERS[1:]
    rng = lambda key, f: (min(n["layers"][L][key][f] for L in big), max(n["layers"][L][key][f] for L in big))
    n["ranges_real_layers"] = {f"{k}.{f}": rng(k, f) for k in ("dense", "sp24", "sp48")
                               for f in ("vs_berkeley_best", "vs_dense_stream_stock", "perf_per_mm2_vs_berkeley_best", "rs_full_share")}
    n["dense_chip_spread_pct"] = max(abs(n["layers"][L]["nm24_dense_vs_stock_dense_pct"]) for L in ALL_LAYERS)
    if MIX: n["mixed_sim_builds"] = MIX   # disclose the mix
    (OUT / "numbers.json").write_text(json.dumps(n, indent=1) + "\n")

    md = [f"# Streaming benchmark tables (stream_analysis.py, from {n['run']}/results.csv)", "",
          f"{nrows} result rows, all verified. One number per row (the small layer's seeds 1-3 are identical). "
          "Area = whole-Gemmini standard-cell area (analysis/area/area.csv, SRAM macros excluded).", "",
          "| Layer | Variant (chip) | Cycles | vs Berkeley best | vs dense_stream (stock) | MACs/cycle | MACs/cycle/mm² | perf/mm² vs Berkeley | ex_active | bytes read | no-alloc cycles (rs_full) ÷ total |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for t in table:
        md.append(f"| {t['layer']} | {t['variant']} ({t['chip']}) | {t['total_cycles']:,} | {t['vs_berkeley_best']:.3f}× | "
                  f"{t['vs_dense_stream_stock']:.3f}× | {t['macs_per_cycle']:.1f} | {t['macs_per_cycle_per_mm2']:.2f} | "
                  f"{t['perf_per_mm2_vs_berkeley_best']:.3f}× | {t['ex_active']:,} | {t['rdma_bytes_real']:,} | {t['rs_full_share'] * 100:.0f}% |")
    if MIX:   # disclose the mix
        md += ["", "WARNING: mixed simulator builds (--allow-mixed-sims). Rows per chip and sim_sha256:"]
        md += [f"- chip {c}: sim_sha256 {h} ({k} rows)" for c, m in MIX.items() for h, k in sorted(m.items())]
    md += ["", "Definitions: see the header of stream_analysis.py. bytes read = rdma_bytes counter / 4.",
           "no-alloc cycles (rs_full) = Gemmini's rs_full counter, which is !io.alloc.ready (ReservationStation.scala:611): "
           "cycles with no command allocated into the reservation station, idle cycles included. It is not a measure of a "
           "full queue. Its counting window is slightly longer than the timed region (~130-175 cycles, measured in the "
           "investigation), so it can exceed 100% on the smallest layers. See worklogs/investigate.md sections 9 and 17."]
    (OUT / "tables.md").write_text("\n".join(md) + "\n")
    return n, T


# ---------------------------------------------------------------- figures (same themes as analysis/area.py)
THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", grid="#e6e5e0", axis="#c9c8c2",
                  berkeley="#2a78d6", dense="#8f8d86", sp24="#eb6834", sp48="#1baf7a"),
    "dark": dict(surface="#1a1a19", ink="#ffffff", ink2="#c3c2b7", grid="#2e2e2c", axis="#4a4946",
                 berkeley="#3987e5", dense="#8a8880", sp24="#d95926", sp48="#199e70"),
}


def figures(T, area):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})

    def style(ax, Th, xgrid=True):
        ax.set_facecolor(Th["surface"])
        for sp in ("top", "right", "left"): ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(Th["axis"])
        ax.tick_params(colors=Th["ink2"], labelsize=8); ax.tick_params(axis="y", length=0, colors=Th["ink"])
        ax.grid(axis="x" if xgrid else "y", color=Th["grid"], linewidth=0.8); ax.set_axisbelow(True)

    def head(fig, Th, title, sub):
        fig.text(0.012, 0.985, title, ha="left", va="top", fontsize=12.5, fontweight="bold", color=Th["ink"])
        fig.text(0.012, 0.985 - 0.33 / fig.get_figheight(), sub, ha="left", va="top", fontsize=8.3, color=Th["ink2"])

    def legend(fig, Th, keys, y=0.885):
        hs = [matplotlib.patches.Patch(color=Th[k], label=lab) for k, _, _, lab in SERIES if k in keys]
        leg = fig.legend(handles=hs, loc="upper left", bbox_to_anchor=(0.012, y), ncol=len(hs), frameon=False, fontsize=8.3)
        for t in leg.get_texts(): t.set_color(Th["ink"])

    def save(fig, Th, name, theme):
        fig.savefig(OUT / f"{name}-{theme}.png", dpi=200, facecolor=fig.get_facecolor())
        if theme == "light": fig.savefig(OUT / f"{name}.pdf", facecolor=fig.get_facecolor())
        plt.close(fig)

    keys = [k for k, *_ in SERIES]
    for theme, Th in THEMES.items():
        # s1: cycles per layer, one panel per layer (scales differ by 100x)
        fig, axs = plt.subplots(1, len(LAYERS), figsize=(13, 3.9), gridspec_kw={"wspace": 0.25})
        fig.patch.set_facecolor(Th["surface"])
        for ax, L in zip(axs, LAYERS):
            style(ax, Th)
            vals = [T[(L, chip, var)]["total_cycles"] for _, chip, var, _ in SERIES]
            y = list(range(len(vals)))[::-1]
            ax.barh(y, vals, height=0.62, color=[Th[k] for k in keys], edgecolor=Th["surface"], linewidth=2)
            for yi, v in zip(y, vals):
                ax.text(v, yi, f" {v / 1e3:,.0f}k" if v >= 1e5 else f" {v / 1e3:,.1f}k", va="center", ha="left", fontsize=7.6, color=Th["ink"])
            ax.set_yticks([]); ax.set_xlim(0, max(vals) * 1.42)
            ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1e6:g}M" if v >= 1e6 else f"{v / 1e3:g}k"))
            ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))
            ax.set_title(LNAME[L], loc="left", fontsize=8.6, color=Th["ink"], fontweight="bold")
        axs[len(LAYERS) // 2].set_xlabel("clock cycles, first mvin to last mvout + fence (fewer = faster)", color=Th["ink2"], fontsize=8.3)
        head(fig, Th, "Streaming benchmark: cycles per layer", "int8 C = A × W with A and W streamed from main memory, cold L2. "
             "One deterministic run per row; every output verified against the host reference.")
        legend(fig, Th, keys)
        fig.subplots_adjust(left=0.02, right=0.99, top=0.70, bottom=0.17)
        save(fig, Th, "fig-s1-cycles", theme)

        # s2: speed-up of sparse vs Berkeley best and vs the dense hand tiler
        fig, axs = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw={"wspace": 0.08})
        fig.patch.set_facecolor(Th["surface"])
        panels = [("vs_berkeley_best", "Against Berkeley's tiled_matmul_auto (stock chip)", ["dense", "sp24", "sp48"]),
                  ("vs_dense_stream_stock", "Against the same hand tiler, dense (stock chip)", ["sp24", "sp48"])]
        ymax = max(T[(L, c, v)][f] for f, _, ks in panels for L in LAYERS for k, c, v, _ in SERIES if k in ks)
        for i, (ax, (f, title, ks)) in enumerate(zip(axs, panels)):
            style(ax, Th, xgrid=False)
            w = 0.8 / len(ks)
            for j, k in enumerate(ks):
                _, c, v, _ = SERIES[keys.index(k)]
                xs = [li + (j - (len(ks) - 1) / 2) * w for li in range(len(LAYERS))]
                vals = [T[(L, c, v)][f] for L in LAYERS]
                ax.bar(xs, vals, width=w * 0.92, color=Th[k], edgecolor=Th["surface"], linewidth=1.5)
                for xx, vv in zip(xs, vals):
                    ax.text(xx, vv + 0.015, f"{vv:.2f}", ha="center", va="bottom", fontsize=6.9, color=Th["ink"])
            ax.axhline(1.0, color=Th["ink2"], linewidth=1, linestyle=(0, (4, 3)))
            ax.text(-0.45, 1.0, "1.0 = same speed", ha="left", va="bottom", fontsize=7.2, color=Th["ink2"])
            ax.set_xticks(range(len(LAYERS)), [LTICK[L] for L in LAYERS], fontsize=7.4, color=Th["ink"])
            ax.tick_params(axis="x", length=0)
            ax.set_ylim(0, max(1.12, ymax * 1.12))
            if i == 0: ax.set_ylabel("speed-up (reference cycles ÷ row cycles)", color=Th["ink2"], fontsize=8.3)
            else: ax.set_yticklabels([])
            ax.set_title(title, loc="left", fontsize=9.5, color=Th["ink"], fontweight="bold")
        head(fig, Th, "Speed-up of the sparse runs (above 1 = faster)", "Same layer and answer in every bar. "
             "The dense hand tiler is itself slower than Berkeley's tiler on most layers (left, grey).")
        legend(fig, Th, ["dense", "sp24", "sp48"], y=0.9)
        fig.subplots_adjust(left=0.06, right=0.99, top=0.74, bottom=0.15)
        save(fig, Th, "fig-s2-speedup", theme)

        # s3: counters
        fig, axs = plt.subplots(1, 2, figsize=(11, 4.4), gridspec_kw={"wspace": 0.12})
        fig.patch.set_facecolor(Th["surface"])
        panels = [("ex_active", "Array busy (ex_active), cycles ÷ dense-tiler run", lambda L, t: t["ex_active"] / T[(L, "stock", "dense_stream")]["ex_active"], "{:.2f}"),
                  ("rdma", "Bytes read by the DMA ÷ dense-tiler run", lambda L, t: t["rdma_bytes_real"] / T[(L, "stock", "dense_stream")]["rdma_bytes_real"], "{:.2f}")]
        # rs_full is not plotted: it is !io.alloc.ready (cycles with no command allocated, idle included), not "queue full".
        ks = keys
        for i, (ax, (_, title, fn, fmt)) in enumerate(zip(axs, panels)):
            style(ax, Th, xgrid=False)
            w = 0.8 / len(ks)
            for j, k in enumerate(ks):
                _, c, v, _ = SERIES[keys.index(k)]
                xs = [li + (j - (len(ks) - 1) / 2) * w for li in range(len(LAYERS))]
                vals = [fn(L, T[(L, c, v)]) for L in LAYERS]
                ax.bar(xs, vals, width=w * 0.92, color=Th[k], edgecolor=Th["surface"], linewidth=1.2)
            ax.set_xticks(range(len(LAYERS)), [L.replace("bert_", "BERT ").replace("rn50_conv", "RN50") for L in LAYERS], fontsize=7.6, color=Th["ink"])
            ax.tick_params(axis="x", length=0)
            ax.axhline(1.0, color=Th["ink2"], linewidth=1, linestyle=(0, (4, 3)))
            ax.set_title(title, loc="left", fontsize=9, color=Th["ink"], fontweight="bold")
        head(fig, Th, "Gemmini's counters, relative to the dense hand tiler on the stock chip",
             "Left: the sparse runs keep the array busy about as long as dense, with half the computes. Right: they read less data.")
        legend(fig, Th, ks, y=0.89)
        fig.subplots_adjust(left=0.04, right=0.99, top=0.72, bottom=0.1)
        save(fig, Th, "fig-s3-counters", theme)

        # s4: area-normalised throughput
        fig, ax = plt.subplots(figsize=(11, 4.6)); fig.patch.set_facecolor(Th["surface"]); style(ax, Th, xgrid=False)
        w = 0.8 / len(keys)
        for j, (k, c, v, _) in enumerate(SERIES):
            xs = [li + (j - (len(keys) - 1) / 2) * w for li in range(len(LAYERS))]
            vals = [T[(L, c, v)]["macs_per_cycle_per_mm2"] for L in LAYERS]
            ax.bar(xs, vals, width=w * 0.92, color=Th[k], edgecolor=Th["surface"], linewidth=1.5)
            for xx, vv in zip(xs, vals):
                ax.text(xx, vv + 0.2, f"{vv:.1f}", ha="center", va="bottom", fontsize=7, color=Th["ink"])
        ax.set_xticks(range(len(LAYERS)), [LTICK[L] for L in LAYERS], fontsize=7.8, color=Th["ink"])
        ax.tick_params(axis="x", length=0)
        ax.set_ylabel("dense-equivalent MACs per cycle per mm²", color=Th["ink2"], fontsize=8.3)
        head(fig, Th, "Throughput per unit area (higher = better)",
             "MACs = M×K×N of the dense layer, divided by cycles and by the chip's whole-Gemmini standard-cell area "
             f"(sky130 HD, SRAM macros excluded): stock {area['stock']:.2f}, 2:4 {area['nm24']:.2f}, 4:8 {area['nm48']:.2f} mm².")
        legend(fig, Th, keys, y=0.885)
        fig.subplots_adjust(left=0.07, right=0.99, top=0.74, bottom=0.14)
        save(fig, Th, "fig-s4-perf-per-mm2", theme)


def main():
    table, area, area_blocks, nrows = build()
    fair, fair_seeds = fair_numbers()
    n, T = write_tables(table, area, area_blocks, fair, fair_seeds, nrows)
    figures(T, area)
    print(f"{nrows} rows -> {OUT}/stream_table.csv, area_norm.csv, tables.md, numbers.json, fig-s1..s4")


if __name__ == "__main__":
    main()
