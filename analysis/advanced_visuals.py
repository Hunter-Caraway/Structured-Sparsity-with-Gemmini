#!/usr/bin/env python3
"""Paper figures for the N:M sparsity results (fair benchmark + pattern comparison).

Reads the raw logs of one or more fair run folders through verification/nmdata.py, so every plotted number comes
straight from the simulator. With several RANDOM_SEEDs, bars show the mean, lines and labels the min-max range, and
ratios are the envelope over every seed pair. Writes <first run>/derived/figures/:
  fig1-berkeley-vs-ours      array time and whole-job time, Berkeley's original vs ours (2:4, 4:8)
  fig2-where-time-goes       each run split into array time and the rest, with the processor-only issue time marked
  fig3-speedup-map           every ratio against Berkeley on one log scale (1x = break-even, 2x = the ideal)
  fig4-cost-per-work         cycles per unit of work for the processor and for the array
  fig5-pattern-share-kept    share of the weights' energy (sum of squares) each pruning rule keeps, synthetic weights
  fig6-pattern-masks         which weights each rule keeps, on one block of synthetic Laplace weights
  figure_data.csv            every plotted value (table view)
Each figure: <name>-light.png, <name>-dark.png, and <name>.pdf (vector, light, for the paper).
"Array time" is ex_active: cycles the execute controller is in its compute state, not multiplier activity.

run: ~/chipyard/.conda-env/bin/python analysis/advanced_visuals.py [RUN ...]   (default: newest fair run; exit 2 if none)
"""
import csv, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "verification"))
import nmdata  # noqa: E402

OUT = None

# ---- theme: reference palette, categorical slots in fixed order; colour follows the entity in every figure ----
THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#8a8984", grid="#e6e5e0", axis="#c9c8c2",
                  berkeley="#2a78d6", nm24="#eb6834", nm48="#1baf7a", paired="#eda100",
                  work="#52514e", idle="#d6d5cf", dot="#0b0b0b", ref="#8a8984",
                  seq=["#a9c8f0", "#6fa3e6", "#2a78d6", "#0d3d7a"], dropped="#ecebe6"),
    "dark": dict(surface="#1a1a19", ink="#ffffff", ink2="#c3c2b7", muted="#8f8e86", grid="#2e2e2c", axis="#4a4946",
                 berkeley="#3987e5", nm24="#d95926", nm48="#199e70", paired="#c98500",
                 work="#c3c2b7", idle="#3d3d3a", dot="#ffffff", ref="#8f8e86",
                 seq=["#2a5585", "#3a78c4", "#5f9cec", "#b5d4f8"], dropped="#262624"),
}
ENT = [("berkeley", "Berkeley original"), ("nm24", "Ours, 2:4"), ("nm48", "Ours, 4:8")]
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5, "axes.titlesize": 10.5, "axes.titleweight": "bold"})


def style(ax, T, xgrid=True):
    ax.set_facecolor(T["surface"])
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(T["axis"])
    ax.tick_params(colors=T["ink2"], labelsize=8.5)
    ax.tick_params(axis="y", length=0, colors=T["ink"])
    if xgrid:
        ax.grid(axis="x", color=T["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.title.set_color(T["ink"])


def header(fig, T, title, sub):
    fig.text(0.012, 0.975, title, ha="left", va="top", fontsize=12.5, fontweight="bold", color=T["ink"])
    fig.text(0.012, 0.915, sub, ha="left", va="top", fontsize=9, color=T["ink2"])


def save(fig, name, theme):
    fig.savefig(OUT / f"{name}-{theme}.png", dpi=200, facecolor=fig.get_facecolor())
    if theme == "light":
        fig.savefig(OUT / f"{name}.pdf", facecolor=fig.get_facecolor())
    plt.close(fig)


def word(r):
    return "faster" if r[0] > 1.02 else "slower" if r[1] < 0.98 else "about even or unclear"


def env(e, m):
    return nmdata.ratio(base(m), S[KEY[e]][m])


def base(m):
    return S["berkeley"]["fresh" if m == "batched" else m]


def measures(pairs):
    return [(m, l) for m, l in pairs if all(m in S[KEY[e]] for e in ("nm24", "nm48"))]


def rtxt(r):
    return nmdata.fmt_ratio(r).replace("x", "×")


# ---- data (filled in by main) ----
S = None
KEY = {"berkeley": "berkeley", "nm24": "2:4", "nm48": "4:8"}
FID = nmdata.load_fidelity()
rows_out = []


# ---- fig 1: berkeley vs ours ----
def fig1(T, theme):
    meas = measures([("busy_reuse", "Array time (compute state),\nweights reused"), ("reuse", "Whole job,\nweights reused"),
                     ("fresh", "Whole job,\nfresh weights"), ("batched", "Whole job, fresh weights,\nindexes batched")])
    fig, ax = plt.subplots(figsize=(8.6, 1.6 + 1.0 * len(meas))); fig.patch.set_facecolor(T["surface"]); style(ax, T)
    h, g = 0.22, 0.04
    vmax = max(base(m)["max"] if e == "berkeley" else S[KEY[e]][m]["max"] for e, _ in ENT for m, _ in meas)
    for r, (m, lab) in enumerate(meas):
        for i, (e, ename) in enumerate(ENT):
            st = base(m) if e == "berkeley" else S[KEY[e]][m]; y = r + (i - 1) * (h + g)
            ax.barh(y, st["mean"], height=h, color=T[e], edgecolor=T["surface"], linewidth=1.5, zorder=3)
            if st["range"]:
                ax.plot([st["min"], st["max"]], [y, y], color=T["ink"], lw=1.4, zorder=4)
            t = nmdata.fmt_stat(st) if e == "berkeley" else f"{nmdata.fmt_stat(st)}   {rtxt(env(e, m))} ({word(env(e, m))})"
            ax.text(st["max"] + vmax * 0.012, y, t, va="center", fontsize=8.3, color=T["ink2"] if e == "berkeley" else T["ink"])
            if theme == "light":
                rows_out.append(["fig1", lab.replace("\n", " "), ename, nmdata.fmt_stat(st),
                                 "" if e == "berkeley" else f"Berkeley / ours {nmdata.fmt_ratio(env(e, m))}"])
    ax.set_yticks(range(len(meas))); ax.set_yticklabels([l for _, l in meas]); ax.invert_yaxis()
    ax.set_xlim(0, vmax * 1.6)
    ax.set_xlabel("clock cycles (fewer = faster) · bar = mean over seeds, line = min-max", color=T["ink2"], fontsize=8.5)
    ax.legend(handles=[Patch(color=T[e], label=n) for e, n in ENT], loc="lower right", frameon=False, fontsize=8.5,
              labelcolor=T["ink"], ncol=3, bbox_to_anchor=(1.0, 1.0))
    header(fig, T, "Berkeley's original vs our sparse Gemmini",
           "fair_perf.c, same job on every chip · ratio = Berkeley's cycles ÷ ours, range over seeds · batched row vs Berkeley's fresh")
    fig.subplots_adjust(left=0.24, right=0.98, top=1 - 1.0 / fig.get_figheight(), bottom=0.5 / fig.get_figheight())
    save(fig, "fig1-berkeley-vs-ours", theme)


# ---- fig 2: where the time goes ----
def fig2(T, theme):
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.9), sharex=True); fig.patch.set_facecolor(T["surface"])
    vmax = max(S[KEY[e]][k]["max"] for e, _ in ENT for k in ("reuse", "fresh"))
    for ax, (k, ttl) in zip(axes, [("reuse", "Weights reused"), ("fresh", "Fresh weights")]):
        style(ax, T)
        for i, (e, ename) in enumerate(ENT):
            d = S[KEY[e]]; busy = d["busy_" + k]["mean"]; tot = d[k]["mean"]; cpu = d["cpu_" + k]["mean"]
            ax.barh(i, busy, height=0.5, color=T["work"], edgecolor=T["surface"], linewidth=1.5, zorder=3)
            ax.barh(i, tot - busy, left=busy, height=0.5, color=T["idle"], edgecolor=T["surface"], linewidth=1.5, zorder=3)
            ax.plot([cpu], [i], "o", ms=7.5, color=T["dot"], mec=T["surface"], mew=2, zorder=5)
            ax.text(tot + vmax * 0.02, i, nmdata.fmt_stat(d[k]), va="center", fontsize=8.3, color=T["ink"])
            if theme == "light":
                rows_out.append(["fig2", ttl, ename, nmdata.fmt_stat(d[k]),
                                 f"means: array time {busy:.0f}, rest {tot - busy:.0f}, processor-only {cpu:.0f}"])
        ax.set_yticks(range(3)); ax.set_yticklabels([n for _, n in ENT]); ax.invert_yaxis()
        ax.set_title(ttl, loc="left", fontsize=10, color=T["ink"]); ax.set_xlim(0, vmax * 1.35)
        ax.set_xlabel("clock cycles", color=T["ink2"], fontsize=8.5)
    fig.legend(handles=[Patch(color=T["work"], label="array time (compute state)"), Patch(color=T["idle"], label="rest of the job"),
                        Line2D([], [], marker="o", ls="", color=T["dot"], ms=7, label="processor alone, just issuing instructions")],
               loc="upper left", bbox_to_anchor=(0.005, 0.875), ncol=3, frameon=False, fontsize=8.3, labelcolor=T["ink"])
    header(fig, T, "Where the time goes", "Array time, the rest of the job, and the processor issuing the same instructions alone (dots) · means over seeds")
    fig.subplots_adjust(left=0.13, right=0.98, top=0.68, bottom=0.14, wspace=0.32)
    save(fig, "fig2-where-time-goes", theme)


# ---- fig 3: speed-up map (log scale) ----
def fig3(T, theme):
    meas = measures([("busy_reuse", "Array time, weights reused"), ("reuse", "Whole job, weights reused"),
                     ("fresh", "Whole job, fresh weights"), ("batched", "Whole job, fresh, batched")])
    fig, ax = plt.subplots(figsize=(8.6, 2.1 + 0.5 * len(meas))); fig.patch.set_facecolor(T["surface"]); style(ax, T, xgrid=False)
    ax.set_xscale("log"); ax.set_xlim(0.35, 2.6)
    ticks = [0.4, 0.5, 0.67, 1, 1.5, 2]
    ax.set_xticks(ticks); ax.set_xticklabels([f"{t:g}×" for t in ticks]); ax.minorticks_off()
    for t in ticks:
        ax.axvline(t, color=T["grid"], lw=0.8, zorder=0)
    ax.axvline(1, color=T["ref"], lw=1.4, zorder=1); ax.axvline(2, color=T["ref"], lw=1.0, zorder=1)
    lbl = dict(facecolor=T["surface"], edgecolor="none", pad=1.5)
    ax.text(1, -0.75, "break-even", ha="center", fontsize=8, color=T["ink2"], bbox=lbl, zorder=6)
    ax.text(2, -0.75, "ideal (half the work)", ha="center", fontsize=8, color=T["ink2"], bbox=lbl, zorder=6)
    for r, (m, lab) in enumerate(meas):
        for j, e in enumerate(("nm24", "nm48")):
            lo, hi = env(e, m); sp = base(m)["mean"] / S[KEY[e]][m]["mean"]; y = r + (j - 0.5) * 0.28
            ax.plot([1, sp], [y, y], color=T[e], lw=2, solid_capstyle="round", zorder=2)
            ax.plot([lo, hi], [y, y], color=T["ink"], lw=1, zorder=4)
            ax.plot([sp], [y], "o", ms=9, color=T[e], mec=T["surface"], mew=2, zorder=3)
            ax.text(hi * 1.04 if sp >= 1 else lo * 0.96, y, rtxt((lo, hi)), va="center", ha="left" if sp >= 1 else "right",
                    fontsize=8.3, color=T["ink"])
            if theme == "light":
                rows_out.append(["fig3", lab, dict(ENT)[e], nmdata.fmt_ratio((lo, hi)), "Berkeley / ours, envelope over seeds"])
    ax.set_yticks(range(len(meas))); ax.set_yticklabels([l for _, l in meas]); ax.set_ylim(len(meas) - 0.4, -1.0)
    ax.legend(handles=[Line2D([], [], marker="o", color=T[e], ms=8, lw=2, label=n) for e, n in ENT[1:]],
              loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=2, frameon=False, fontsize=8.5, labelcolor=T["ink"])
    header(fig, T, "Speed-up against Berkeley's original", "Right of the break-even line = fewer cycles · dot = ratio of means, line = range over seeds · log scale")
    fig.subplots_adjust(left=0.22, right=0.97, top=1 - 0.85 / fig.get_figheight(), bottom=0.45 / fig.get_figheight())
    save(fig, "fig3-speedup-map", theme)


# ---- fig 4: cost per unit of work ----
def fig4(T, theme):
    # one unit of work = one dense 16x16 weight tile pass; a sparse tile covers two units
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.9), sharey=True); fig.patch.set_facecolor(T["surface"])
    groups = [("cpu", "Processor issuing\ninstructions"), ("busy", "Array time\n(compute state)")]
    vmax = 0
    vals = {}
    for k in ("fresh", "reuse"):
        for e, _ in ENT:
            d = S[KEY[e]]; units = S["berkeley"]["pairs"]["mean"]
            vals[(k, e, "cpu")] = d["cpu_" + k]["mean"] / units
            vals[(k, e, "busy")] = d["busy_" + k]["mean"] / units
            vmax = max(vmax, vals[(k, e, "cpu")], vals[(k, e, "busy")])
    for ax, (k, ttl) in zip(axes, [("reuse", "Weights reused"), ("fresh", "Fresh weights")]):
        style(ax, T, xgrid=False); ax.grid(axis="y", color=T["grid"], lw=0.8)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        w = 0.24
        for gi, (g, glab) in enumerate(groups):
            for i, (e, ename) in enumerate(ENT):
                v = vals[(k, e, g)]; x = gi + (i - 1) * (w + 0.03)
                ax.bar(x, v, width=w, color=T[e], edgecolor=T["surface"], linewidth=1.5, zorder=3)
                ax.text(x, v + vmax * 0.015, f"{v:.1f}", ha="center", va="bottom", fontsize=8, color=T["ink"])
                if theme == "light":
                    rows_out.append(["fig4", f"{ttl} · {glab.replace(chr(10), ' ')}", ename, f"{v:.2f}", "cycles per unit of work"])
        ax.set_xticks(range(len(groups))); ax.set_xticklabels([l for _, l in groups], color=T["ink"])
        ax.tick_params(axis="x", length=0); ax.set_title(ttl, loc="left", fontsize=10, color=T["ink"])
        ax.set_ylim(0, vmax * 1.15)
    axes[0].set_ylabel("cycles per unit of work", color=T["ink2"], fontsize=8.5)
    fig.legend(handles=[Patch(color=T[e], label=n) for e, n in ENT], loc="upper left", bbox_to_anchor=(0.005, 0.875),
               ncol=3, frameon=False, fontsize=8.5, labelcolor=T["ink"])
    header(fig, T, "The cost of each unit of work", "Unit = one dense 16×16 weight-tile pass (a sparse tile covers M/N of them) · means over seeds")
    fig.subplots_adjust(left=0.08, right=0.98, top=0.68, bottom=0.14, wspace=0.12)
    save(fig, "fig4-cost-per-work", theme)


# ---- fig 5: share of weights kept per pruning rule ----
def fig5(T, theme):
    rules = [("paired 4:8", "Paired 4:8 (NVIDIA)", "paired"), ("2:4", "2:4", "nm24"), ("4:8", "4:8 (ours)", "nm48")]
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6), sharex=True); fig.patch.set_facecolor(T["surface"])
    for ax, dist in zip(axes, ("bell curve", "heavy tail")):
        style(ax, T)
        for i, (rk, lab, col) in enumerate(rules):
            v = FID[(dist, rk)][0]
            ax.barh(i, v, height=0.5, color=T[col], edgecolor=T["surface"], linewidth=1.5, zorder=3)
            ax.text(v + 0.6, i, f"{v:.1f}%", va="center", fontsize=8.3, color=T["ink"], zorder=6,
                    bbox=dict(facecolor=T["surface"], edgecolor="none", pad=1.2))
            if theme == "light":
                rows_out.append(["fig5", dist, lab, f"{v:.1f}", f"answer error {FID[(dist, rk)][1]:.1f}%"])
        best = FID[(dist, "no pattern")][0]
        ax.axvline(best, color=T["ref"], lw=1.2, zorder=4)
        ax.text(best, -0.75, f"no pattern:\n{best:.1f}%", ha="center", va="bottom", fontsize=7.8, color=T["ink2"],
                bbox=dict(facecolor=T["surface"], edgecolor="none", pad=1.2), zorder=6)
        ax.set_yticks(range(3)); ax.set_yticklabels([l for _, l, _ in rules]); ax.invert_yaxis()
        ax.set_xlim(60, 100); ax.set_ylim(2.5, -1.3)
        ax.set_title(f"{dist.capitalize()} weights", loc="left", fontsize=10, color=T["ink"])
        ax.set_xlabel("share of the weights' energy kept (sum of squares, %)", color=T["ink2"], fontsize=8.5)
    header(fig, T, "How much of the weights' energy each rule keeps",
           "All three keep exactly half the weights · synthetic Gaussian / Laplace weights, not a trained model · axis starts at 60%")
    fig.subplots_adjust(left=0.15, right=0.98, top=0.76, bottom=0.15, wspace=0.42)
    save(fig, "fig5-pattern-share-kept", theme)


# ---- fig 6: which weights each rule keeps ----
def masks(w):
    a = w * w; k, j = w.shape
    def topk(g, n):
        m = np.zeros_like(g, dtype=bool); np.put_along_axis(m, np.argsort(-g, axis=1, kind="stable")[:, :n, :], True, axis=1); return m
    m24 = topk(a.reshape(k // 4, 4, j), 2).reshape(k, j)
    m48 = topk(a.reshape(k // 8, 8, j), 4).reshape(k, j)
    pm = topk(a.reshape(k // 8, 4, 2, j).sum(axis=2), 2)
    mp = np.repeat(pm, 2, axis=1).reshape(k, j)
    mn = np.zeros_like(w, dtype=bool); np.put_along_axis(mn, np.argsort(-a, axis=0, kind="stable")[: k // 2, :], True, axis=0)
    return [("Paired 4:8 (NVIDIA)", mp, 8, True), ("2:4", m24, 4, False), ("4:8 (ours)", m48, 8, False), ("No pattern (best possible)", mn, None, False)]


def fig6(T, theme):
    rng = np.random.default_rng(11)
    w = rng.laplace(size=(32, 12))
    mag = np.abs(w)
    cmap = LinearSegmentedColormap.from_list("seq", T["seq"])
    fig, axes = plt.subplots(1, 4, figsize=(9.2, 4.6)); fig.patch.set_facecolor(T["surface"])
    for ax, (ttl, m, grp, paired) in zip(axes, masks(w)):
        img = np.ones((*w.shape, 3))
        norm = mag / mag.max()
        img[:] = matplotlib.colors.to_rgb(T["dropped"])
        img[m] = cmap(norm[m])[:, :3]
        ax.imshow(img, aspect="auto", interpolation="nearest")
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        if grp:
            for r in range(grp, w.shape[0], grp):
                ax.axhline(r - 0.5, color=T["surface"], lw=2.2)
        if paired:
            for r in range(2, w.shape[0], 2):
                if r % 8:
                    ax.axhline(r - 0.5, color=T["surface"], lw=0.8)
        kept = (mag[m] ** 2).sum() / (mag ** 2).sum() * 100
        ax.set_title(ttl, fontsize=9.5, color=T["ink"], loc="left")
        ax.text(0, w.shape[0] + 0.9, f"keeps {kept:.0f}% of the energy", fontsize=8.2, color=T["ink2"], va="top")
        if theme == "light":
            rows_out.append(["fig6", "32x12 synthetic Laplace block", ttl, f"{kept:.1f}", "share of energy (sum of squares) kept"])
    fig.legend(handles=[Patch(color=T["seq"][2], label="kept (darker = larger magnitude)"), Patch(color=T["dropped"], label="pruned to zero")],
               loc="upper left", bbox_to_anchor=(0.005, 0.875), ncol=2, frameon=False, fontsize=8.3, labelcolor=T["ink"])
    header(fig, T, "Which weights each rule keeps", "One synthetic Laplace block: 32 weights (rows, the pruning direction) × 12 output columns · white lines = group boundaries")
    fig.subplots_adjust(left=0.02, right=0.98, top=0.74, bottom=0.08, wspace=0.12)
    save(fig, "fig6-pattern-masks", theme)


if __name__ == "__main__":
    try:
        runs = nmdata.find_runs(sys.argv[1:] or None)
        fair = nmdata.load_fair(runs)
    except nmdata.NoResults as e:
        nmdata.die_no_results(e)
    nmdata.die_unpassed(fair, "figures")
    S = nmdata.summary(fair)
    OUT = runs[0] / "derived" / "figures"
    OUT.mkdir(parents=True, exist_ok=True)
    for theme, T in THEMES.items():
        for f in (fig1, fig2, fig3, fig4, fig5, fig6):
            f(T, theme)
    with open(OUT / "figure_data.csv", "w", newline="") as fh:
        wr = csv.writer(fh); wr.writerow(["figure", "measure", "series", "value", "note"]); wr.writerows(rows_out)
    print(f"wrote {len(list(OUT.glob('*.png')))} PNGs, {len(list(OUT.glob('*.pdf')))} PDFs and figure_data.csv to {OUT}")
