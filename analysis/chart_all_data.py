#!/usr/bin/env python3
# every number the fair benchmark printed, per chip, variant and counter (fair_perf.c logs read through nmdata).
# a cell shows the min-max over seeds and is shaded by the mean. the counters are snapshots at the fence:
#   ex_active   cycles the execute controller is in its compute state (not multiplier activity)
#   rs_full     cycles the reservation station can't take a command (!alloc.ready), not "full"
#   spad_*_wait cycles with no A / B / D row ready; they also tick while gemmini is idle, so cpu_* rows count too
# writes <first run>/derived/figures/fig7-all-counters-{light,dark}.png and <first run>/derived/all_data.csv
# (one row per chip, seed, variant and counter). nothing is written into the repo tree.
# run: ~/chipyard/.conda-env/bin/python analysis/chart_all_data.py [RUN ...]   (default: newest fair run; exit 2 if none)
import csv, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verification"))
import nmdata  # noqa: E402

NAMES = {"berkeley": "Berkeley original", "sameprog": "Ours, sparsity off (Berkeley's program)",
         "nm24": "Ours, 2:4", "nm48": "Ours, 4:8"}
FIRST = ["total", "issued", "pairs", "cyc_pair"]
THEMES = {"light": dict(surface="#fcfcfb", fg="#0b0b0b", fg2="#52514e"),
          "dark": dict(surface="#1a1a19", fg="#ffffff", fg2="#c3c2b7")}
# blue sequential ramp; on dark, near zero recedes toward the surface
BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
RAMP = {"light": BLUE, "dark": BLUE[::-1][:-1]}


def ink_on(rgba):
    r, g, b = rgba[:3]
    return "#0b0b0b" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5 else "#ffffff"


def table(logs):
    """(variants, counters, {(variant, counter): stat}) for one chip, in log order."""
    variants = list(dict.fromkeys(v for log in logs.values() for v in log["perf"]))
    keys = list(dict.fromkeys(k for log in logs.values() for p in log["perf"].values() for k in p))
    counters = [k for k in FIRST if k in keys] + [k for k in keys if k not in FIRST]
    cells = {(v, c): s for v in variants for c in counters if (s := nmdata.metric(logs, v, c)) is not None}
    return variants, counters, cells


def chart(fair, theme, out):
    t = THEMES[theme]
    cmap = LinearSegmentedColormap.from_list("seq", RAMP[theme])
    tabs = {chip: table(logs) for chip, logs in fair.items()}
    vmax = max(s["mean"] for _, _, cells in tabs.values() for s in cells.values()) or 1
    heights = [len(v) * 0.32 + 0.9 for v, _, _ in tabs.values()]
    fig, axes = plt.subplots(len(tabs), 1, figsize=(11, sum(heights) + 0.9), squeeze=False,
                             gridspec_kw={"height_ratios": heights})
    fig.patch.set_facecolor(t["surface"])
    h = fig.get_figheight()
    fig.text(0.012, 1 - 0.08 / h, "Every counter from fair_perf, per chip", ha="left", va="top", fontsize=13,
             fontweight="bold", color=t["fg"])
    fig.text(0.012, 1 - 0.36 / h, "cycles at the fence · cell = min-max over seeds, shade = mean · wait counters also tick "
             "while idle · rs_full = reservation station not ready", ha="left", va="top", fontsize=9, color=t["fg2"])
    for ax, (chip, (variants, counters, cells)) in zip(axes[:, 0], tabs.items()):
        grid = [[cells[(v, c)]["mean"] if (v, c) in cells else 0 for c in counters] for v in variants]
        ax.imshow(grid, cmap=cmap, vmin=0, vmax=vmax, aspect="auto")
        for i, v in enumerate(variants):
            for j, c in enumerate(counters):
                if (v, c) in cells:
                    ax.text(j, i, nmdata.fmt_stat(cells[(v, c)]), ha="center", va="center", fontsize=6.8,
                            color=ink_on(cmap(grid[i][j] / vmax)))
        ax.set_xticks([x - 0.5 for x in range(1, len(counters))], minor=True)
        ax.set_yticks([y - 0.5 for y in range(1, len(variants))], minor=True)
        ax.grid(which="minor", color=t["surface"], linewidth=2)
        ax.tick_params(which="both", length=0)
        ax.set_xticks(range(len(counters)), counters, rotation=30, ha="right", fontsize=8.5, color=t["fg"])
        ax.set_yticks(range(len(variants)), variants, fontsize=8.5, color=t["fg"])
        for s in ax.spines.values():
            s.set_visible(False)
        n = len(fair[chip])
        ax.set_title(f"{NAMES.get(chip, chip)}  ({n} seed{'s' if n > 1 else ''})", loc="left", fontsize=10.5,
                     color=t["fg"], fontweight="bold")
    fig.subplots_adjust(left=0.16, right=0.99, top=1 - 0.75 / h, bottom=0.55 / h, hspace=0.55)
    fig.savefig(out / f"fig7-all-counters-{theme}.png", dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    try:
        runs = nmdata.find_runs(sys.argv[1:] or None)
        fair = nmdata.load_fair(runs, require=())
    except nmdata.NoResults as e:
        nmdata.die_no_results(e)
    derived = runs[0] / "derived"
    (derived / "figures").mkdir(parents=True, exist_ok=True)
    rows = [(chip, seed, v, k, val) for chip, logs in fair.items() for seed, log in logs.items()
            for v, p in log["perf"].items() for k, val in p.items()]
    with open(derived / "all_data.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["chip", "seed", "variant", "counter", "value"]); w.writerows(rows)
    for theme in THEMES:
        chart(fair, theme, derived / "figures")
    print(f"{len(rows)} numbers from {sum(map(len, fair.values()))} logs -> {derived}/all_data.csv, "
          f"figures/fig7-all-counters-{{light,dark}}.png")


if __name__ == "__main__":
    main()
