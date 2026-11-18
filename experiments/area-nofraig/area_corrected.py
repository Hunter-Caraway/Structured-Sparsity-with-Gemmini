#!/usr/bin/env python3
# Corrected area tables from the yosys runs in work/<chip>/stat.json (made by run_area_nofraig.py).
# BUG in analysis/area.py hier(): with yosys 0.69, `stat -json` gives each module an "area" that ALREADY includes
# its submodules (e.g. Tile: 0 own cells, area == PE_256's area). hier() adds the submodules' totals on top, so
# area is double-counted at every hierarchy level (flop/cell counts are fine: they come from leaf cells only).
# This script derives each block's area two independent ways and requires them to agree:
#   (a) yosys's own hierarchical "area" / "sequential_area" fields;
#   (b) leaf cells x liberty cell area, walked through the hierarchy (area.py's walk without the double count).
# Writes area-corrected.csv / area-corrected.md and redraws the chart with area.py's own chart() code.
import csv, json, re, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "analysis"))
import area
area.OUT = HERE
cell_area, cur = {}, None
for line in open(area.LIB):
    m = re.match(r'\s*cell\s*\(\s*"?([\w]+)"?\s*\)', line)
    if m: cur = m.group(1); continue
    m = re.match(r'\s*area\s*:\s*([\d.]+)', line)
    if m and cur and cur not in cell_area: cell_area[cur] = float(m.group(1))
old = {(r["chip"], r["block"]): r for r in csv.DictReader(open(HERE / "area.areapy-DOUBLECOUNTED.csv"))}
rows = []
for chip, cfg in area.CHIPS:
    mods = {k.lstrip("\\"): v for k, v in json.loads((HERE / "work" / chip / "stat.json").read_text())["modules"].items()}
    memo = {}
    def walk(m):
        if m in memo: return memo[m]
        a = s = 0.0; f = c = 0
        for t, n in mods[m].get("num_cells_by_type", {}).items():
            t = t.lstrip("\\")
            if t in mods: x = walk(t); a += n * x[0]; s += n * x[1]; f += n * x[2]; c += n * x[3]
            else:
                c += n
                if t.startswith("sky130_"): a += n * cell_area[t]
                if area.SEQ.match(t): s += n * cell_area[t]; f += n
        memo[m] = (a, s, f, c); return memo[m]
    for b, desc in area.BLOCKS:
        a, s, f, c = walk(b)
        ya, ys = float(mods[b]["area"]), float(mods[b]["sequential_area"])
        assert abs(a - ya) <= 1e-6 * ya + 0.01, f"{chip} {b}: walk {a} != yosys area {ya}"
        assert abs(s - ys) <= 1e-6 * ys + 0.01, f"{chip} {b}: walk seq {s} != yosys sequential_area {ys}"
        assert f == int(old[(chip, b)]["flops"]), f"{chip} {b}: flops differ from area.csv"
        rows.append({"chip": chip, "config": cfg, "block": b, "what": desc, "area_um2": round(ya, 1),
                     "seq_area_um2": round(ys, 1), "cells": c, "flops": f,
                     "areapy_area_um2_doublecounted": old[(chip, b)]["area_um2"]})
with open(HERE / "area-corrected.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
g = {(r["chip"], r["block"]): r for r in rows}
md = ["# Chip area (corrected): Berkeley's Gemmini vs. the 2:4 and 4:8 chips", "",
      "Standard-cell area, Yosys 0.69 synthesis to sky130 HD (`sky130_fd_sc_hd__tt_025C_1v80.lib`, OpenROAD-flow-scripts copy, "
      "sha256 ec0e1067…d0d9), before place and route, SRAM macros left out (byte-identical in all chips). abc run without "
      "`&fraig -x` (see run_area_nofraig.py). Areas are yosys's own hierarchical `area` / `sequential_area`, cross-checked "
      "against leaf cells × liberty areas (area_corrected.py). analysis/area.py's hier() double-counts these; its output here is kept as area.areapy-DOUBLECOUNTED.{csv,md} (wrong areas; flops OK).", "",
      "| Block | Berkeley (µm²) | 2:4 (µm²) | 2:4 vs Berkeley | 4:8 (µm²) | 4:8 vs Berkeley |", "|---|---:|---:|---:|---:|---:|"]
for b, desc in area.BLOCKS:
    a0 = g[("berkeley", b)]["area_um2"]; cells = [f"{b} ({desc})", f"{a0:,.0f}"]
    for c in ("nm24", "nm48"):
        a = g[(c, b)]["area_um2"]; cells += [f"{a:,.0f}", f"{(a / a0 - 1) * 100:+.1f}%"]
    md.append("| " + " | ".join(cells) + " |")
md += ["", "| Block | Chip | Flops | Flops vs Berkeley | Seq area (µm²) | Seq share of area | Seq share of added area |",
       "|---|---|---:|---:|---:|---:|---:|"]
for b, _ in area.BLOCKS:
    r0 = g[("berkeley", b)]
    for c, _ in area.CHIPS:
        r = g[(c, b)]
        add = "–" if c == "berkeley" else f"{(r['seq_area_um2'] - r0['seq_area_um2']) / (r['area_um2'] - r0['area_um2']) * 100:.0f}%"
        md.append(f"| {b} | {c} | {r['flops']:,} | {(r['flops'] / r0['flops'] - 1) * 100:+.1f}% | {r['seq_area_um2']:,.0f} | "
                  f"{r['seq_area_um2'] / r['area_um2'] * 100:.1f}% | {add} |")
(HERE / "area-corrected.md").write_text("\n".join(md) + "\n"); print("\n".join(md))
area.chart(rows)
