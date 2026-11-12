#!/usr/bin/env python3
# chip area of each gemmini build, from a yosys synthesis of the generated verilog to the sky130 hd
# standard cells (typical corner). compares berkeley's stock chip with the 2:4 and 4:8 chips.
#   - synthesises the whole Gemmini module (the accelerator, not the rocket core) of each simulator's
#     generated-src. the sram macros (*_ext in *.top.mems.v) are left as black boxes: they are byte-identical
#     in all three chips (checked below), so they cancel in the comparison, and yosys can't size them anyway.
#     so are the simulation helpers in LIB_V (plusarg_reader only reads +args in simulation; EICG_wrapper is a
#     clock gate). every black box actually used is listed in area-meta.json.
#   - area is standard-cell area from the liberty file (um^2), before place and route: no wires, no
#     utilisation factor, no timing-driven sizing. good for comparing the chips, not an absolute die size.
#   - firtool writes packed-array literals as '{a, b, ..} which yosys can't read; for packed arrays that
#     means the same as {a, b, ..}, so the working copy rewrites it. nothing else is changed or left out.
#   - technology mapping: `synth -noabc`, `dfflibmap`, then `abc -liberty LIB -script +ABC_SCRIPT` with
#     ABC_SCRIPT = strash;scorr;dc2;dretime;strash;&get,-n;&dch,-f;&nf;&put
#     (commas are spaces). that is yosys 0.69's default liberty script without its `&get -n; &fraig -x; &put`
#     step. why: with the default script, `&fraig -x` ran >85 min (never finished) on Berkeley's
#     LoopConvLdWeight (a chain of 16..64-bit multipliers, the same RTL in all three chips); without it the
#     module maps in 19 s. on standalone PE_256 / MeshWithDelays syntheses, dropping it made absolute area
#     0.8-2.8% larger and moved the 2:4 / 4:8 overheads by <= 1.5 points (experiments/streaming/worklogs/
#     analytics.md). the same script is used for all three chips and recorded in area-meta.json.
#   - area is counted by this script, not taken from yosys's per-module numbers: each block's leaf cells
#     (walked through the hierarchy) x the cell's `area` in the liberty file; seq_area_um2 is the same over
#     flip-flops/latches (SEQ). yosys's `stat -json` "area" is hierarchical in 0.69 (it already includes the
#     submodules) but per-module in older versions; adding submodules on top of 0.69's numbers double-counted
#     (32.9M um^2 for a 7.79M Gemmini). as a cross-check, every module's yosys "area" (and "sequential_area",
#     when present) must equal either the hierarchical or the module-only walk, the same way for every module,
#     and the design totals must match; otherwise the script aborts.
#
# writes analysis/area/area.csv (one row per chip and block), area.md (the comparison),
# area-meta.json (what was synthesised, with hashes), so each re-synthesis can be tracked in git, and
# area-{light,dark}.png + area.pdf (the chart). `--chart-only` redraws the chart from area.csv (no yosys).
# work files go to analysis/area/work/ (not tracked).
#
# run (each chip takes ~3.5 min and ~1.8 GB; one at a time by default):
#   ~/chipyard/.conda-env/bin/python analysis/area.py
# needs yosys (AREA_YOSYS, default ~/gemmini-fixwork/eda/bin/yosys) and the sky130 hd liberty file
# (AREA_LIB, default ~/gemmini-fixwork/pdk/sky130hd/sky130_fd_sc_hd__tt_025C_1v80.lib).
# AREA_JOBS (default 1) chips in parallel; each chip waits until MemAvailable >= AREA_MIN_FREE_GIB (default 3);
# a yosys run longer than AREA_TIMEOUT seconds (default 3600) is killed and the script fails.
import csv, hashlib, json, os, re, resource, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "analysis" / "area"
GS = Path(os.environ.get("CHIPYARD_DIR", HOME / "chipyard")) / "sims" / "verilator" / "generated-src"
YOSYS = os.environ.get("AREA_YOSYS", str(HOME / "gemmini-fixwork/eda/bin/yosys"))
LIB = Path(os.environ.get("AREA_LIB", HOME / "gemmini-fixwork/pdk/sky130hd/sky130_fd_sc_hd__tt_025C_1v80.lib"))
CHIPS = [("berkeley", "GemminiRocketConfig"), ("nm24", "GemminiNMRocketConfig"), ("nm48", "GemminiNM48RocketConfig")]
TOP = "Gemmini"
# blocks reported on their own (hierarchical area, i.e. including everything inside them)
BLOCKS = [("Gemmini", "whole accelerator (no sram macros)"),
          ("ExecuteController", "execute unit (array, index fifo, control)"),
          ("MeshWithDelays", "array + input/output skew registers"),
          ("Mesh", "16x16 array of tiles"),
          ("PE_256", "one multiply-accumulate pe")]
LIB_V = ["plusarg_reader.v", "EICG_wrapper.v"]
SKIP = re.compile(r"^(TestHarness|SimDRAM|extern_modules)")
SEQ = re.compile(r"sky130_fd_sc_hd__(e?s?df|dl[xr]|lpflow_inputisolatch)")   # flip-flops and latches (not dlygate delay cells)
# yosys 0.69's default `abc -liberty` script minus `&get -n; &fraig -x; &put` (see the header), commas = spaces
ABC_SCRIPT = "strash;scorr;dc2;dretime;strash;&get,-n;&dch,-f;&nf;&put"
JOBS = int(os.environ.get("AREA_JOBS", "1"))
MIN_FREE_GIB = float(os.environ.get("AREA_MIN_FREE_GIB", "3"))
TIMEOUT = int(os.environ.get("AREA_TIMEOUT", "3600"))


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def collateral(cfg):
    d = GS / f"chipyard.harness.TestHarness.{cfg}" / "gen-collateral"
    if not d.is_dir(): sys.exit(f"no generated verilog for {cfg} at {d} (build that simulator first)")
    return d


def prepare(chip, cfg):
    src, work = collateral(cfg), OUT / "work" / chip
    (work / "sv").mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    files = []
    for p in sorted(src.glob("*.sv")):
        if SKIP.match(p.name): continue
        t = p.read_text()
        h.update(p.name.encode()); h.update(t.encode())
        t = re.sub(r"(=\s*)'\{", r"\1{", t)    # packed-array literal -> concatenation (same bits)
        (work / "sv" / p.name).write_text(t)
        files.append(str(work / "sv" / p.name))
    mems = src / f"chipyard.harness.TestHarness.{cfg}.top.mems.v"
    ys = work / "synth.ys"
    ys.write_text("\n".join([
        f"read_verilog -lib {mems} {' '.join(str(src / v) for v in LIB_V if (src / v).exists())}",
        f"read_verilog -sv -DSYNTHESIS -defer {' '.join(files)}",
        f"hierarchy -check -top {TOP}",
        f"synth -top {TOP} -noabc",
        f"dfflibmap -liberty {LIB}",
        f"abc -liberty {LIB} -script +{ABC_SCRIPT}",
        "opt_clean",
        f"tee -q -o {work / 'stat.json'} stat -json -liberty {LIB}",
        f"stat -liberty {LIB} -top {TOP}", ""]))
    return work, ys, h.hexdigest(), mems


def mem_avail_gib():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable:"): return int(l.split()[1]) / 2**20
    return float("inf")


def synth(chip, cfg):
    work, ys, rtl_hash, mems = prepare(chip, cfg)
    while mem_avail_gib() < MIN_FREE_GIB:
        print(f"{chip}: waiting for {MIN_FREE_GIB} GiB free memory (MemAvailable {mem_avail_gib():.1f} GiB)", flush=True)
        time.sleep(60)
    (work / "stat.json").unlink(missing_ok=True)
    t0 = time.monotonic()
    try:
        r = subprocess.run([YOSYS, "-q", "-l", str(work / "yosys.log"), "-s", str(ys)], capture_output=True, text=True,
                           timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"yosys for {chip} ({cfg}) ran over {TIMEOUT} s (AREA_TIMEOUT); see {work / 'yosys.log'}")
    if r.returncode != 0:
        tail = (work / "yosys.log").read_text().splitlines()[-15:] if (work / "yosys.log").exists() else []
        raise RuntimeError(f"yosys failed for {chip} ({cfg}), see {work / 'yosys.log'}:\n" + "\n".join(tail) + r.stderr[-1000:])
    secs = round(time.monotonic() - t0)
    # largest single child process so far (yosys or its yosys-abc); with AREA_JOBS=1 this bounds this chip's peak
    rss = round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024)
    print(f"{chip}: synthesised in {secs} s (largest child process so far {rss} MiB)", flush=True)
    return rtl_hash, mems, json.loads((work / "stat.json").read_text()), {"yosys_wall_s": secs, "max_child_rss_mib": rss}


def liberty_areas(lib):
    """cell name -> area (um^2), the first `area :` inside each `cell (...)` group."""
    out, cur = {}, None
    with open(lib) as fh:
        for line in fh:
            m = re.match(r'\s*cell\s*\(\s*"?(\w+)"?\s*\)', line)
            if m: cur = m.group(1); continue
            m = re.match(r'\s*area\s*:\s*([\d.]+)', line)
            if m and cur and cur not in out: out[cur] = float(m.group(1))
    if not out: sys.exit(f"no cell areas found in {lib}")
    return out


def hier(stat, cell_area, chip=""):
    """per-module totals from leaf cells x liberty areas, cross-checked against yosys's own area numbers.
    returns (mods, total, boxes, mode); total(m) = (area, seq_area, cells, flops) including submodules."""
    mods = {k.lstrip("\\"): v for k, v in stat["modules"].items()}
    memo, own, boxes = {}, {}, set()
    def leaf(t, n):
        if t.startswith("sky130_"):
            if t not in cell_area: sys.exit(f"{chip}: cell {t} not in {LIB.name}")
            a = n * cell_area[t]
        else:
            boxes.add(t); a = 0.0     # black box (sram macro, sim helper, yosys $check): no area, as in yosys
        return a, (a if SEQ.match(t) else 0.0), n, (n if SEQ.match(t) else 0)
    def total(m):
        if m in memo: return memo[m]
        acc, mine = [0.0, 0.0, 0, 0], [0.0, 0.0, 0, 0]
        for typ, n in mods[m].get("num_cells_by_type", {}).items():
            t = typ.lstrip("\\")
            if t in mods: x = [n * v for v in total(t)]
            else: x = leaf(t, n); mine = [p + q for p, q in zip(mine, x)]
            acc = [p + q for p, q in zip(acc, x)]
        memo[m], own[m] = tuple(acc), tuple(mine)
        return memo[m]
    for m in mods: total(m)

    # cross-check: yosys's "area" must be the hierarchical walk (0.69) or the module-only walk (older), for all modules
    close = lambda a, b: abs(a - b) <= 1e-6 * max(abs(a), abs(b)) + 0.01
    modes = set()
    for m, v in mods.items():
        for key, i in (("area", 0), ("sequential_area", 1)):
            if key not in v: continue
            y, h, o = float(v[key]), memo[m][i], own[m][i]
            ok = {name for name, w in (("hierarchical", h), ("per-module", o)) if close(y, w)}
            if not ok: sys.exit(f"{chip}: {m} yosys {key} {y} matches neither the hierarchical ({h}) nor the module-only ({o}) "
                                f"leaf-cell x liberty area: refusing to report")
            if len(ok) == 1: modes |= ok
    if len(modes) != 1:
        sys.exit(f"{chip}: yosys stat areas are {sorted(modes) or 'never distinguishable'}: cannot cross-check, refusing to report")
    mode = modes.pop()
    d = stat.get("design", {})
    a, s, c, _ = memo[TOP]
    for key, mine in (("area", a), ("sequential_area", s), ("num_cells", c)):
        if key in d and mode == "hierarchical" and not close(float(d[key]), mine):
            sys.exit(f"{chip}: yosys design {key} {d[key]} != leaf-cell walk of {TOP} {mine}: refusing to report")
    return mods, total, boxes, mode


# chart: same theme and entity colours as advanced_visuals.py (chip colour follows the chip in every figure)
THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", grid="#e6e5e0", axis="#c9c8c2",
                  berkeley="#2a78d6", nm24="#eb6834", nm48="#1baf7a"),
    "dark": dict(surface="#1a1a19", ink="#ffffff", ink2="#c3c2b7", grid="#2e2e2c", axis="#4a4946",
                 berkeley="#3987e5", nm24="#d95926", nm48="#199e70"),
}
NAMES = {"berkeley": "Berkeley original", "nm24": "Ours, 2:4", "nm48": "Ours, 4:8"}
SHORT = {"Gemmini": "Whole accelerator", "ExecuteController": "Execute unit", "MeshWithDelays": "Array + skew regs",
         "Mesh": "16x16 array", "PE_256": "One PE"}


def chart(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5})
    get = {(r["chip"], r["block"]): float(r["area_um2"]) for r in rows}
    chips = [c for c, _ in CHIPS]
    for theme, T in THEMES.items():
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.6), gridspec_kw={"width_ratios": [1, 1.25], "wspace": 0.45})
        fig.patch.set_facecolor(T["surface"])
        for ax in (a1, a2):
            ax.set_facecolor(T["surface"])
            for sp in ("top", "right", "left"): ax.spines[sp].set_visible(False)
            ax.spines["bottom"].set_color(T["axis"])
            ax.tick_params(colors=T["ink2"], labelsize=8.5); ax.tick_params(axis="y", length=0, colors=T["ink"])
            ax.grid(axis="x", color=T["grid"], linewidth=0.8); ax.set_axisbelow(True)
        # left: whole accelerator, mm^2
        base = get[("berkeley", TOP)]
        vals = [get[(c, TOP)] / 1e6 for c in chips]
        y = list(range(len(chips)))[::-1]
        a1.barh(y, vals, height=0.55, color=[T[c] for c in chips], edgecolor=T["surface"], linewidth=2)
        for yi, c, v in zip(y, chips, vals):
            pct = "" if c == "berkeley" else f"  ({(get[(c, TOP)] / base - 1) * 100:+.1f}%)"
            a1.text(v, yi, f" {v:.2f} mm²{pct}", va="center", ha="left", fontsize=8.5, color=T["ink"])
        a1.set_yticks(y, [NAMES[c] for c in chips]); a1.set_xlim(0, max(vals) * 1.45)
        a1.set_xlabel("standard-cell area (mm²)", color=T["ink2"], fontsize=8.5)
        a1.set_title("Whole accelerator (no SRAM macros)", loc="left", fontsize=10, color=T["ink"], fontweight="bold")
        # right: % over berkeley per block
        blocks = [b for b, _ in BLOCKS]
        yb = list(range(len(blocks)))[::-1]
        h = 0.36
        allp = []
        for k, c in enumerate(("nm24", "nm48")):
            pcts = [(get[(c, b)] / get[("berkeley", b)] - 1) * 100 for b in blocks]; allp += pcts
            off = h / 2 if k == 0 else -h / 2
            a2.barh([v + off for v in yb], pcts, height=h, color=T[c], edgecolor=T["surface"], linewidth=2, label=NAMES[c])
            for yi, p in zip(yb, pcts):
                a2.text(p, yi + off, f" {p:+.1f}%", va="center", ha="left" if p >= 0 else "right", fontsize=8, color=T["ink"])
        a2.axvline(0, color=T["axis"], linewidth=1)
        a2.set_yticks(yb, [SHORT.get(b, b) for b in blocks])
        a2.set_xlim(min(0, min(allp)) * 1.3, max(allp) * 1.3)
        a2.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
        a2.set_xlabel("area vs. Berkeley's same block", color=T["ink2"], fontsize=8.5)
        a2.set_title("Extra area per block", loc="left", fontsize=10, color=T["ink"], fontweight="bold")
        leg = a2.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=2, frameon=False, fontsize=8.5)
        for t in leg.get_texts(): t.set_color(T["ink"])
        fig.text(0.012, 0.98, "Chip area: Berkeley's Gemmini vs. the 2:4 and 4:8 chips", ha="left", va="top",
                 fontsize=12.5, fontweight="bold", color=T["ink"])
        fig.text(0.012, 0.915, f"Yosys synthesis to sky130 HD ({LIB.name}), before place and route.\n"
                 "SRAM macros left out (identical in all chips). Compare the chips; this is not an absolute die size.",
                 ha="left", va="top", fontsize=8.5, color=T["ink2"])
        fig.subplots_adjust(left=0.13, right=0.97, top=0.74, bottom=0.14)
        fig.savefig(OUT / f"area-{theme}.png", dpi=200, facecolor=fig.get_facecolor())
        if theme == "light": fig.savefig(OUT / "area.pdf", facecolor=fig.get_facecolor())
        plt.close(fig)
    print(f"chart: {OUT / 'area-light.png'}, area-dark.png, area.pdf")


def main():
    if "--chart-only" in sys.argv[1:]:
        f = OUT / "area.csv"
        if not f.exists(): sys.exit(f"no {f}: run without --chart-only first")
        with open(f) as fh: chart(list(csv.DictReader(fh)))
        return
    if not Path(YOSYS).exists(): sys.exit(f"yosys not found at {YOSYS} (set AREA_YOSYS)")
    if not LIB.exists(): sys.exit(f"liberty file not found at {LIB} (set AREA_LIB)")
    mems = [collateral(cfg) / f"chipyard.harness.TestHarness.{cfg}.top.mems.v" for _, cfg in CHIPS]
    norm = {m.read_text().replace(cfg, "CFG") for m, (_, cfg) in zip(mems, CHIPS)}
    if len(norm) != 1: sys.exit("the sram macros differ between the chips, so leaving them out would bias the comparison")
    OUT.mkdir(parents=True, exist_ok=True)
    cell_area = liberty_areas(LIB)
    with ThreadPoolExecutor(max(1, JOBS)) as ex:
        res = dict(zip([c for c, _ in CHIPS], ex.map(lambda cc: synth(*cc), CHIPS)))

    rows, meta = [], {"date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "yosys": subprocess.run([YOSYS, "-V"], capture_output=True, text=True).stdout.strip(),
                      "liberty": LIB.name, "liberty_sha256": sha(LIB), "top": TOP,
                      "sram_macros": "black boxes, identical in all chips",
                      "synthesis": {"script": ["synth -top Gemmini -noabc", "dfflibmap -liberty <liberty>",
                                               f"abc -liberty <liberty> -script +{ABC_SCRIPT}", "opt_clean"],
                                    "abc_script": ABC_SCRIPT.replace(",", " "),
                                    "why": "yosys 0.69's default liberty abc script minus `&get -n; &fraig -x; &put`: "
                                           "&fraig -x did not finish in 85+ min on LoopConvLdWeight (same RTL in all "
                                           "chips); without it the module maps in 19 s. Same script for all chips."},
                      "area_method": "leaf cells x liberty cell area, summed through the hierarchy; seq_area = same over "
                                     "flip-flops/latches. Cross-checked against yosys stat -json (must agree for every module).",
                      "chips": {}}
    for chip, cfg in CHIPS:
        rtl_hash, mem_file, stat, run = res[chip]
        mods, total, boxes, mode = hier(stat, cell_area, chip)
        meta["chips"][chip] = {"config": cfg, "generated_verilog_sha256": rtl_hash,
                               "generated_verilog_dir": str(collateral(cfg)), "black_boxes": sorted(boxes),
                               "yosys_stat_area_is": mode, **run}
        for b, desc in BLOCKS:
            if b not in mods: sys.exit(f"{chip}: no module {b} in the synthesised design")
            a, s, c, f = total(b)
            rows.append({"chip": chip, "config": cfg, "block": b, "what": desc, "area_um2": round(a, 1),
                         "seq_area_um2": round(s, 1), "cells": c, "flops": f})
    with open(OUT / "area.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (OUT / "area-meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    get = {(r["chip"], r["block"]): r for r in rows}
    md = ["# Chip area: Berkeley's Gemmini vs. the 2:4 and 4:8 chips", "",
          f"Standard-cell area from a Yosys synthesis to sky130 HD (`{LIB.name}`), before place and route. "
          "SRAM macros are left out (identical in all chips). Generated by `analysis/area.py` on "
          f"{meta['date']}; inputs and hashes in `area-meta.json`. Mapped with yosys's default liberty abc script minus "
          "`&fraig -x` (it does not finish on LoopConvLdWeight), the same for all chips. Area = leaf cells × liberty "
          "cell area, cross-checked against yosys's own `stat`.", "",
          "| Block | Berkeley (µm²) | 2:4 (µm²) | 2:4 vs Berkeley | 4:8 (µm²) | 4:8 vs Berkeley |",
          "|---|---:|---:|---:|---:|---:|"]
    for b, desc in BLOCKS:
        base = get[("berkeley", b)]["area_um2"]
        cells = [f"{b} ({desc})", f"{base:,.0f}"]
        for chip in ("nm24", "nm48"):
            a = get[(chip, b)]["area_um2"]
            cells += [f"{a:,.0f}", f"{(a / base - 1) * 100:+.1f}%"]
        md.append("| " + " | ".join(cells) + " |")
    md += ["", "| Block | Berkeley flops | 2:4 flops | 4:8 flops |", "|---|---:|---:|---:|"]
    for b, _ in BLOCKS:
        md.append(f"| {b} | " + " | ".join(f"{get[(c, b)]['flops']:,}" for c, _ in CHIPS) + " |")
    (OUT / "area.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    chart(rows)


if __name__ == "__main__":
    main()
