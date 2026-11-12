# Gemmini 2:4 / 4:8 sparsity: streaming benchmark results

Start with **Streaming-Results-Summary.pdf** (the same text is in results-summary.md).

| Path | What it is |
|---|---|
| Streaming-Results-Summary.pdf, results-summary.md | Plain-language results summary: method, results, area, throughput per mm², the small fair benchmark, caveats |
| figures/fig-s1-cycles-* | Cycles per layer, every variant |
| figures/fig-s2-speedup-* | Speed-up of 2:4 / 4:8 sparse vs Berkeley's tiled_matmul_auto and vs the same hand tiler (dense) |
| figures/fig-s3-counters-* | Gemmini counters: array busy time and bytes read, relative to the dense hand tiler |
| figures/fig-s4-perf-per-mm2-* | Dense-equivalent MACs per cycle per mm² |
| figures/area-* | Chip area per block (analysis/area.py) |
| data/results.csv, collect-summary.md, run.info | The benchmark's own results (scripts/collect.py), unchanged copies from experiments/streaming/runs/20261109-144252 |
| data/stream_table.csv, tables.md | Every row with the derived ratios, throughput, area and counters |
| data/area_norm.csv | Throughput per mm² per layer × chip × variant |
| data/numbers.json | Every number quoted in the summary |
| data/area.csv, area.md, area-meta.json | Chip area (Yosys, sky130 HD standard cells, pre-layout, SRAM macros excluded) |
| scripts/ | The scripts that made all of the above (they run inside the gemmini-sparsity repo) |
| SHA256SUMS | Hashes of every file here |

Figures come in -light.png, -dark.png and .pdf. Every number comes from the scripts; none is typed by hand.
Each result is one deterministic simulation: totals are unchanged when all non-reset register/SRAM contents are
randomised (seeds 1–3, verified), so no ranges over seeds are given.
