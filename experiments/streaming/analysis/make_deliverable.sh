#!/bin/bash
# Packages the streaming results for the group: experiments/streaming/deliverables/<name>/ + <name>.zip.
# Run stream_analysis.py and build_stream_paper.py first. Copies only; nothing in runs/ or analysis/area/ is changed.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); repo=$(cd "$here/../../.." && pwd); st="$repo/experiments/streaming"
run=${RUN:-$st/runs/20261109-144252}; name=${NAME:-Gemmini-NM-Streaming-Results-$(date +%Y%m%d)}
dst="$st/deliverables/$name"; [ -e "$dst" ] && { echo "$dst exists; remove it or set NAME"; exit 1; }
mkdir -p "$dst"/{figures,data,scripts}
cp "$here/out/Streaming-Results-Summary.pdf" "$here/out/results-summary.md" "$dst/"
cp "$here"/out/fig-s*.png "$here"/out/fig-s*.pdf "$dst/figures/"
for f in area-light.png area-dark.png area.pdf; do cp "$repo/analysis/area/$f" "$dst/figures/$f"; done
cp "$here"/out/{stream_table.csv,area_norm.csv,tables.md,numbers.json} "$dst/data/"
cp "$run/results.csv" "$dst/data/results.csv"; cp "$run/summary.md" "$dst/data/collect-summary.md"; cp "$run/run.info" "$dst/data/run.info"
for f in area.csv area.md area-meta.json; do cp "$repo/analysis/area/$f" "$dst/data/$f"; done
cp "$here"/{stream_analysis.py,build_stream_paper.py,make_deliverable.sh} "$dst/scripts/"
cat > "$dst/README.md" <<MD
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
| data/results.csv, collect-summary.md, run.info | The benchmark's own results (scripts/collect.py), unchanged copies from $(realpath --relative-to="$repo" "$run") |
| data/stream_table.csv, tables.md | Every row with the derived ratios, throughput, area and counters |
| data/area_norm.csv | Throughput per mm² per layer × chip × variant |
| data/numbers.json | Every number quoted in the summary |
| data/area.csv, area.md, area-meta.json | Chip area (Yosys, sky130 HD standard cells, pre-layout, SRAM macros excluded) |
| scripts/ | The scripts that made all of the above (they run inside the gemmini-sparsity repo) |
| SHA256SUMS | Hashes of every file here |

Figures come in -light.png, -dark.png and .pdf. Every number comes from the scripts; none is typed by hand.
Each result is one deterministic simulation: totals are unchanged when all non-reset register/SRAM contents are
randomised (seeds 1–3, verified), so no ranges over seeds are given.
MD
(cd "$dst" && find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | xargs sha256sum > SHA256SUMS)
(cd "$st/deliverables" && rm -f "$name.zip" && zip -qr "$name.zip" "$name")
echo "$dst"; echo "$st/deliverables/$name.zip ($(du -h "$st/deliverables/$name.zip" | cut -f1))"
