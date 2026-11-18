# fix-area worklog (analysis/area.py fixes)

## 2026-11-09: edits to analysis/area.py
- Backup of the pre-fix script: scratchpad area.py.orig (area.py is untracked in git).
- Hang fix: synth.ys now `synth -top Gemmini -noabc`, `dfflibmap`, `abc -liberty LIB -script +strash;scorr;dc2;dretime;strash;&get,-n;&dch,-f;&nf;&put`
  (yosys 0.69 default liberty script minus `&get -n; &fraig -x; &put`; identical to experiments/area-nofraig wrapper). Plus AREA_TIMEOUT (3600 s) kill.
- Double-count fix: hier() now sums leaf cells x liberty cell area (and SEQ cells for seq_area_um2) through the hierarchy, then
  cross-checks every module's yosys `area`/`sequential_area` (must match hierarchical or module-only walk, consistently) and the
  `design` totals; aborts on any disagreement. seq_area_um2 now always filled.
- Chips run one at a time by default (AREA_JOBS=1), each waits for MemAvailable >= AREA_MIN_FREE_GIB (3).
- Offline test of new hier() on experiments/area-nofraig/work/*/stat.json: all 15 blocks equal area-corrected.csv (area, seq, cells, flops);
  yosys stat detected as "hierarchical". Tampered Mesh area +1% -> aborts.

## 2026-11-09 17:08-17:18: full run `./run-flow.sh area` (one chip at a time)
- rc 0. yosys 187 / 193 / 199 s (berkeley / nm24 / nm48); whole step 9:41 wall. Peak RSS (largest single process, /usr/bin/time -v) 1.72 GB.
  MemAvailable 7 GiB before and after.
- Cross-check passed for all chips (yosys stat area detected as hierarchical; design totals agree).
- analysis/area/area.csv vs experiments/area-nofraig/area-corrected.csv: all 15 blocks identical in area_um2, seq_area_um2, cells, flops (0 diffs).
  Flops and cells identical to the old (double-counted) area.py output.
- Outputs: analysis/area/{area.csv, area.md, area-meta.json, area-light.png, area-dark.png, area.pdf}. run-flow.sh not changed.
