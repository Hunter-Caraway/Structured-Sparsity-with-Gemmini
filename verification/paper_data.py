#!/usr/bin/env python3
# the paper's numbers, straight from one or more fair run folders (default: newest), as min-max over seeds.
# writes <first run>/derived/paper_data.json, readme_table.md and paper_chart.png; nothing goes into the repo tree.
# ratios are "Berkeley cycles / ours" (above 1 = ours takes fewer cycles), as the envelope over every seed pair.
# run: ~/chipyard/.conda-env/bin/python verification/paper_data.py [RUN ...]
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nmdata  # noqa: E402

PATS = ("2:4", "4:8")
ROWS = [("busy_reuse", "Array time (cycles in the compute state), weights reused"),
        ("reuse", "Whole job, weights reused"), ("fresh", "Whole job, fresh weights"),
        ("batched", "Whole job, fresh weights, indexes batched 4 tiles ahead")]


def build_data(fair):
    s = nmdata.summary(fair)
    d = {"seeds": {c: list(v) for c, v in fair.items()}, "rows": s, "vs_berkeley": {}, "vs_own_dense": {}}
    b = s["berkeley"]
    for pat in PATS:
        r, off = s[pat], s["off_" + pat]
        d["vs_berkeley"][pat] = {k: nmdata.ratio(b["fresh" if k == "batched" else k], r[k])
                                 for k, _ in ROWS if k in r}
        d["vs_own_dense"][pat] = {k: nmdata.ratio(off["fresh" if k == "batched" else k], r[k])
                                  for k, _ in ROWS if k in r and ("fresh" if k == "batched" else k) in off}
    if "sameprog" in s:
        o = s["sameprog"]
        d["sameprog_vs_berkeley_pct"] = {k: max(abs(x - y) / y for x in o[k]["values"] for y in b[k]["values"]) * 100
                                         for k in ("busy_reuse", "busy_fresh", "reuse", "fresh") if k in o and k in b}
    return d


def readme_table(d):
    s, cols = d["rows"], ["berkeley", *PATS]
    cell = lambda row, k: nmdata.fmt_stat(s[row][k]) if k in s[row] else "–"
    out = ["| Cycles (min-max over seeds) | Berkeley | 2:4 | 4:8 |", "|---|---:|---:|---:|"]
    for k, label in ROWS:
        out.append(f"| {label} | " + " | ".join(cell(c, k) if not (c == "berkeley" and k == "batched") else "–" for c in cols) + " |")
    for key, label in (("vs_berkeley", "Berkeley / ours"), ("vs_own_dense", "same chip dense / sparse (same program)")):
        for k, name in ROWS:
            vals = [nmdata.fmt_ratio(d[key][p][k]) if k in d[key][p] else "–" for p in PATS]
            if any(v != "–" for v in vals):
                out.append(f"| {label}: {name[0].lower() + name[1:]} | – | " + " | ".join(vals) + " |")
    seeds = sorted({x for v in d["seeds"].values() for x in v}, key=nmdata.seed_key)
    out += ["", f"Seeds: {', '.join(seeds)}. Ratios above 1 mean fewer cycles than the reference column."]
    return "\n".join(out) + "\n"


def chart(d, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ser = [("berkeley", "Berkeley original", "#2a78d6"), ("2:4", "Ours, 2:4", "#eb6834"), ("4:8", "Ours, 4:8", "#1baf7a")]
    rows = [(k, l) for k, l in ROWS[:3]]
    ink, ink2, grid, surf = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, ax = plt.subplots(figsize=(8.4, 4.4), dpi=200)
    fig.patch.set_facecolor(surf); ax.set_facecolor(surf)
    bar_h, gap, top = 0.22, 0.03, 0
    for r, (key, _) in enumerate(rows):
        for i, (sk, _, col) in enumerate(ser):
            st, y = d["rows"][sk][key], r + (i - 1) * (bar_h + gap)
            ax.barh(y, st["mean"], height=bar_h, color=col, edgecolor=surf, linewidth=1, zorder=3)
            if st["range"]:
                ax.plot([st["min"], st["max"]], [y, y], color=ink, linewidth=1, zorder=4)
            txt = nmdata.fmt_stat(st)
            if sk != "berkeley":
                txt += f"   Berkeley / ours {nmdata.fmt_ratio(d['vs_berkeley'][sk][key])}"
            ax.text(st["max"] * 1.02, y, txt, va="center", ha="left", fontsize=8.6, color=ink2 if sk == "berkeley" else ink, zorder=4)
            top = max(top, st["max"])
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([l.replace(", ", ",\n", 1) for _, l in rows], color=ink)
    ax.invert_yaxis()
    ax.set_xlim(0, top * 1.8)
    ax.set_xlabel("cycles, 64x128x32 matmul (bar = mean, line = min-max over seeds)", color=ink2, fontsize=9)
    ax.grid(axis="x", color=grid, linewidth=0.8, zorder=0); ax.set_axisbelow(True)
    for side in ("top", "right", "left"): ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#c9c8c2"); ax.tick_params(axis="x", colors=ink2, labelsize=8.5); ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    handles = [matplotlib.patches.Patch(color=c, label=n) for _, n, c in ser]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.42, 1.0), ncol=3, frameon=False, fontsize=9, labelcolor=ink)
    fig.tight_layout()
    fig.savefig(path, facecolor=surf)


def main():
    try:
        runs = nmdata.find_runs(sys.argv[1:] or None)
        fair = nmdata.load_fair(runs)
    except nmdata.NoResults as e:
        nmdata.die_no_results(e)
    nmdata.die_unpassed(fair, "paper numbers")
    d = build_data(fair)
    out = runs[0] / "derived"
    out.mkdir(exist_ok=True)
    (out / "paper_data.json").write_text(json.dumps({"runs": [str(r) for r in runs], **d}, indent=1) + "\n")
    (out / "readme_table.md").write_text(readme_table(d))
    chart(d, out / "paper_chart.png")
    print(readme_table(d))
    print(f"wrote {out}/paper_data.json, readme_table.md, paper_chart.png")


if __name__ == "__main__":
    main()
