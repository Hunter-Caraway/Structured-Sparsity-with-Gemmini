# Analytics worklog (area + analytics-pipeline check)

## 2026-11-09: Task 1 setup (chip area)

- Tools already present from the 2026-11-03 fix round, so nothing was installed:
  - yosys: `~/gemmini-fixwork/eda/bin/yosys`, a separate conda env made with
    `~/chipyard/.conda-env/bin/conda create -p ~/gemmini-fixwork/eda -c conda-forge yosys` (conda-meta/history,
    2026-11-03 08:35). Package `yosys-0.69-py313h96e71be_0` (conda-forge). `yosys -V`:
    `Yosys 0.69+ (git sha1 9f09efcdb-dirty, ...) [github.com/conda-forge/yosys-feedstock at main]`.
    Chipyard's own conda env is not modified.
  - liberty: `~/gemmini-fixwork/pdk/sky130hd/sky130_fd_sc_hd__tt_025C_1v80.lib`, 12,800,135 bytes,
    sha256 `ec0e1067a35c8bf20b11e58d1e8ac53326067e4dac84a125cc1b917a3518d0d9`, git blob `5773657fe730d984ac06726d0addfdad80395b9b`.
    Its origin was not recorded, so I checked it: it is byte-identical (cmp) to
    `flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib` in The-OpenROAD-Project/OpenROAD-flow-scripts,
    downloaded at ORFS HEAD `b19abe97f412f90fd0a4e18cc9f0c34c2e951a93` on 2026-11-09. The file was last changed in ORFS by commit
    `b5dceb3c08fd30c9a1c5c0587bc6a57e0392080a` (2022-05-15, "sky130 default fanout", 1 line), so it is the ORFS copy of
    SkyWater's sky130_fd_sc_hd tt_025C_1v80 liberty file. That one-line edit is a fanout default and does not change cell areas.
    Google's skywater-pdk-libs-sky130_fd_sc_hd main (`ac7fb61f`) has only `timing/*.lib.json` at that path, not a .lib file.
- SRAM macros: `chipyard.harness.TestHarness.<cfg>.top.mems.v` are byte-identical raw (sha256 prefix 1f51990015d1c2f6,
  5660 lines) for GemminiRocketConfig / GemminiNMRocketConfig / GemminiNM48RocketConfig.
- An old, incomplete area run (2026-11-03 16:42, no stat.json, no area.csv) left files in analysis/area/work/; area.py overwrites them.
- area.py runs all 3 chips in parallel and has no option to change that. Wrapper (source unchanged):
  scratchpad `area-run/run_area_serial.py` monkeypatches ThreadPoolExecutor to 1 worker and waits for >= 3 GiB
  MemAvailable before each chip. AREA_YOSYS points to a shim that runs the same yosys under `/usr/bin/time -v` (peak RSS per run).

## 2026-11-09 13:36-13:45: Task 2, analytics pipeline on fair-20261103-151404

- The tools only write into `<run>/derived/`, so the run was copied (`cp -a`) to the scratchpad
  (`.../scratchpad/runcopy/fair-20261103-151404`). The copy's SHA256SUMS check passed. Its old `derived/` was moved aside so
  everything was regenerated from scratch. The original run folder was not modified: SHA256SUMS still OK, no file newer than 2026-11-04.
- Outputs: `experiments/streaming/analytics-check/` (`<tool>.out` = stdout+stderr+rc, `derived/` = all regenerated
  derived files, `run-flow-checks.out` / `run-flow-compare.out` = the same steps through run-flow.sh).
- Tools run with `~/chipyard/.conda-env/bin/python`, each given the copied run as its argument. All of them exited with rc=0:
  - verify (verify_all.py): ALL CHECKS PASSED, 75 checks, 5 skipped (4 with --skip-patches). Skipped: no bench logs in
    logs/runs; no N-M-Sparsity-Paper-Summary.pdf; no Gemmini-NM-Sparsity-*.zip; no verification/MANIFEST.sha256;
    no README results block.
  - split (analysis/split.py): works. split.csv/md/png.
  - figures: paper_data.py, advanced_visuals.py (12 PNG + 6 PDF + figure_data.csv), chart_all_data.py (fig7 + all_data.csv,
    1080 numbers from 12 logs): all work. fig1 and split.png checked by eye: they render correctly.
  - math (independent_math_check.py): works; output identical to the committed verification/independent_math_check.out.
  - patterns (pattern_fidelity.py): works; output identical to the committed verification/pattern_fidelity.out.
  - compare (compare_runs.py RUN, no reference): ALL GOOD, 12 logs.
  - `./run-flow.sh checks RUN` and `./run-flow.sh compare RUN`: rc 0.
- Reproducibility: the regenerated readme_table.md, split.csv/md, all_data.csv and figure_data.csv are byte-identical to the
  run's 2026-11-03 derived/. paper_data.json differs only in the run path. The PDFs differ only in bytes, probably the embedded creation dates.
- CONCERN (seeds): for every chip, all program output lines (perf counters, totals, and even the CPU prep_cold/prep_warm
  timings) are identical across seeds 1, 2 and 3. The logs differ only in the make command line and in where the DRAMSim2 messages
  land. So "min-max over seeds" has zero width everywhere, and the seeds are not giving the variation the methodology
  relies on. The Verilator flags are `--x-assign fast --x-initial fast` (sims/verilator/Makefile:105-106), so `+verilator+seed`
  probably randomises nothing. Also, sameprog (2:4 chip, dense-only program) is exactly equal to Berkeley on every line.
  This needs checking before the paper claims seed ranges.

## 2026-11-09 14:10: Task 1 progress

- Area run started 13:35:48 (serial wrapper). berkeley: yosys RSS about 1.6 GB, yosys-abc about 0.25 GB.
- At 13:40 synth's internal abc reached `LoopConvLdWeight` (77,768 cells; a chain of 16/32/48/64-bit multipliers in an
  address expression). At 14:08 it was still on that module after 27 min of 100% single-core CPU. The 2026-11-03 run stopped at the same
  point (probably killed). The module is Berkeley's code and byte-identical in all three chips
  (sha256 prefix e223c13e303d303a). Waiting, not changing the method.

## 2026-11-09 15:10: default area run abandoned; fraig is the cause

- By 15:05 the berkeley run had spent 85 min in synth's internal abc on LoopConvLdWeight. Bisected standalone in the scratchpad (abc-probe/):
  synth -noabc + dfflibmap, saved as RTLIL, then abc -liberty with parts of yosys 0.69's default script (300 s timeout):
  `&fraig -x` + map: timeout; `scorr` + map: 10 s; default script without `&get -n; &fraig -x; &put`: 19 s;
  the full default: timeout. `synth -booth` did not help (timeout, 900 s). This yosys has no `abc -fast`.
- Killed the default run (no output had been written to analysis/area/ except work/ files).
- New wrapper `experiments/area-nofraig/run_area_nofraig.py` (area.py unchanged; drops only the fraig step for all chips;
  output goes to experiments/area-nofraig/, analysis/area/ is left for the default method).
- Before using it, a sensitivity check (abc-probe/sens/): PE_256 and MeshWithDelays per chip, default vs no-fraig.
- Sensitivity check (standalone block synthesis, scratchpad abc-probe/sens/sensitivity.md; both methods finish on these blocks):
  | block | method | 2:4 vs B | 4:8 vs B |
  | PE_256 | default | +4.76% | +10.60% |  | PE_256 | nofraig | +5.75% | +9.52% |
  | MeshWithDelays | default | +10.31% | +21.66% |  | MeshWithDelays | nofraig | +9.82% | +20.19% |
  Without fraig, absolute area is 0.8-2.8% higher, and the overhead percentages move by up to 1.5 points.
- 15:07:57: started the full no-fraig run (one chip at a time, 8.4 GiB available).

## 2026-11-09 15:30: Task 1 done (area)

- No-fraig run: 15:07:57-15:17:51, one chip at a time. yosys wall time 3:20 / 3:15 / 3:19 (berkeley / nm24 / nm48),
  peak RSS 1.67 / 1.72 / 1.78 GB (/usr/bin/time -v). MemAvailable stayed >= 8.3 GiB.
- BUG in analysis/area.py `hier()`: yosys 0.69 `stat -json` "area" is already hierarchical (Tile: 0 own cells, area ==
  PE_256's), and hier() adds the submodule totals on top. Areas are double-counted at every level (Gemmini 32.9M reported vs 7.79M real,
  4.2x; Mesh 2.95x). The flop and cell counts are correct. Also seq_area_um2 is empty because this yosys version writes
  `sequential_area`, not `area_by_type`. area.py NOT modified; this needs a fix by the user or a fix agent.
- `experiments/area-nofraig/area_corrected.py` writes area-corrected.{csv,md} and redraws the chart with area.py's chart().
  It uses yosys's own hierarchical area / sequential_area and asserts that they equal an independent leaf-cell x liberty-area walk
  (all 15 blocks agree) and that the flops equal area.py's. area.py's wrong outputs are kept as area.areapy-DOUBLECOUNTED.{csv,md}.
- Result (area-corrected.md): whole Gemmini 7,794,492 / 8,201,671 (+5.2%) / 8,546,004 (+9.6%) µm²; ExecuteController
  +14.7% / +27.0%; MeshWithDelays +11.3% / +21.8%; Mesh +10.8% / +21.8%; PE_256 +6.2% / +11.1%.
- Against HANDOFF's +27% / +60% "array flops": synthesised MeshWithDelays flops are 34,414 / 43,903 (+27.6%) / 53,479 (+55.4%).
  So the flop growth agrees for 2:4. 4:8 is 5 points lower, and the base count is 34.4k against 39.5k: the old count was register bits in the pre-fix SV,
  and synthesis removes or merges some. Area grows much less than flops because flops are only 35% of the stock array's area
  (the 8-bit multipliers and the adders are combinational) and the rest of Gemmini (DMA, controllers, scratchpad logic) is unchanged.
  About 68% of the added array area is flops (the wider activation pipeline), and the M:1 muxes are the rest.
- Not checked: whether the fraig-free mapping biases the chips differently on the full design. On the standalone blocks it moved the overheads by
  <= 1.5 points (see above).

## 2026-11-09: Task 3, streaming analytics (run 20261109-144252)

New files only. No run folder was modified (runs/20261109-144252 SHA256SUMS OK; fair-20261103-151404 SHA256SUMS OK).
- `analysis/stream_analysis.py` (conda python) reads runs/20261109-144252/results.csv, analysis/area/area.csv (the fixed area.py;
  identical to area-corrected) and the fair run through nmdata (read-only). It writes `analysis/out/`: stream_table.csv, area_norm.csv,
  tables.md, numbers.json, fig-s1-cycles / s2-speedup / s3-counters / s4-perf-per-mm2 (light + dark PNG, PDF).
  - It refuses unverified rows and requires the seeds to be identical (small: seeds 1-3 identical; fair: identical) -> one number per row.
  - vs dense_stream always uses the stock chip's dense_stream (nm48 has none for the big layers). The 2:4 chip's dense_stream is within 0.8%.
  - Throughput = M*K*N / cycles / whole-Gemmini std-cell mm² (7.794 / 8.202 / 8.546). rdma_bytes divided by 4.
  - Chip palette checked with the dataviz validator: passes in light and dark; light has a contrast WARN -> value labels + tables.md.
- `analysis/build_stream_paper.py` (repo .venv with reportlab, made per tools/report-builders/README.md) is based on build_paper.py and leaves that file untouched.
  It writes analysis/out/Streaming-Results-Summary.pdf (6 pages) and results-summary.md. Every number is formatted from numbers.json / area.csv,
  and its claims are guarded by asserts (sparse < 1x everywhere, 4:8 slower than 2:4, equal 2:4/4:8 bytes, ...).
- `analysis/make_deliverable.sh` -> deliverables/Gemmini-NM-Streaming-Results-20261109/ (README, PDF, md, 15 figures, 11 data files,
  scripts, SHA256SUMS) + .zip (1.7 MB, 36 entries, unzip -t OK).
- Key results (numbers.json, the 4 real layers): 2:4 sparse 0.49-0.69x of Berkeley best, 0.64-0.71x of the dense hand tiler; 4:8 0.43-0.60x / 0.55-0.62x;
  dense hand tiler 0.69-1.00x of Berkeley; per mm², 2:4 0.46-0.65x, 4:8 0.39-0.55x of Berkeley; sparse ex_active within -2.4..+1.7% of dense;
  rs_full share 91-92% dense, 97% 2:4, 97-98% 4:8.
- Checks: collect.py re-run on a copy (analytics-check/recollect-20261109-144252) -> results.csv byte-identical, summary.md differs only in the folder name;
  my vs_berkeley_best equals collect.py's summary column on all 36 rows; verify_all.py (fair copy) ALL CHECKS PASSED, 75 checks, 5 skipped;
  compare_runs ALL GOOD (12 logs); math/patterns == committed .out; deliverable SHA256SUMS OK. Outputs in analytics-check/task3/.
- Note: rs_full exceeds total_cycles on the edge rows (101%), i.e. a slightly different counting window. Stated in the caveats.

## rs_full correction (2026-11-09)
- The deliverables said the CPU is "blocked on a full command queue" 91-98% of the time (rs_full / total). Wrong:
  rs_full is !io.alloc.ready (ReservationStation.scala:611), i.e. cycles with no command allocated, idle included,
  and its window is ~130-175 cycles longer than the timed region (worklogs/investigate.md sections 1, 9, 17).
- stream_analysis.py: rs_full dropped from fig-s3 (now 2 panels: ex_active, bytes read); table column relabelled
  "no-alloc cycles (rs_full) ÷ total" with a definition in tables.md and the script header.
- build_stream_paper.py: "CPU is blocked" bullet removed; replaced by the investigation's finding (sparse path is
  CPU-issue bound: no LOOP_WS in sparse mode, index tiles sent by RoCC commands; RS empty 37% v1 / 42% v3 vs 8%
  Berkeley, cited as the investigation's own ctr-srv runs, not from results.csv) plus a note on what rs_full means.
- make_deliverable.sh README row for fig-s3 fixed. Regenerated figures, results-summary.md, PDF, deliverable + zip.
