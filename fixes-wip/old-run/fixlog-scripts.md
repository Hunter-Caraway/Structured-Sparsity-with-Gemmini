# Fix log: scripts, checks, docs (repo /home/hunter/gemmini-sparsity)

Scope: everything except verification/fair_perf.c and verification/berkeley_dense_perf.c. No commits.
Python: ~/chipyard/.conda-env/bin/python (numpy 1.26.4, pandas 2.2.3, matplotlib 3.10.9).

## 0. Baseline (before any change)

- Protected files snapshot: scratchpad/protected-before.sha256 (62 files under logs/, results/cycles.csv,
  verification/{fair,berkeley,rerun}-logs/, verification/bin/) + protected-before.mtime.
- MANIFEST: `sha256sum -c verification/MANIFEST.sha256` -> 66/66 OK (no failures).
- verify_all.py --skip-patches on a pristine copy (scratchpad/before/repo): **19 PASS, 1 SKIP (E), exit 0**
  (output in scratchpad/before/verify.out). Note printed: spike-20261006-165950.log not in manifest.
- Numbers for the docs: scratchpad/numbers.py -> scratchpad/numbers.out (all computed from the recorded logs via nmdata).

## Changes

## Session 2 (after old results were deleted in 48bb131; scratch: /home/hunter/gemmini-fixwork/scripts)

Scratch test data: gemmini-fixwork/scripts/old-results (copy of backup), runs/{fair-t1 (unseeded), fair-t2 (fake seeds 1,2),
rerun-t1, bench-nm24-t1, bench-nm48-t1} built from the old logs. NM_RUNS_DIR env var points the loaders at another runs/ folder.

### Item 4a: nmdata.py + compare_runs.py (done)
- nmdata.py rewritten: run-directory loaders (find_run newest-by-default, load_fair -> {chip:{seed:log}}, load_orig, load_bench),
  NoResults exception with a clear message, stat()/ratio() min/max/range over seeds, summary() generic (extra sparse variants such as a
  batched one are picked up as '<pat>/<variant>' rows). Log line format parser unchanged. Hard-coded ORIG_STAMP / FAIR_LOGS removed.
- compare_runs.py: `[RUN [REFERENCE]]`; checks each log passed + CPU-reference matches; with REFERENCE, requires identical numbers per
  (chip, seed) and fails on missing counterparts (old version skipped missing logs and exited 0). Exit 2 when no results.
- Verified on scratch copies: seeds listing, ranges, no-results message (rc 2), self-compare of rerun-t1 (121 numbers identical),
  mismatched seed sets fail.

### Item 4b: cross_check.py, paper_data.py, verify_all.py (done)
- cross_check.py: takes --bench-nm24/--bench-nm48/--rerun DIR (default newest); checks pass lines, cycles.csv vs logs row by row (row count
  derived from the logs, not a constant 26), rerun == bench numbers (optional); derived ratios printed as "info" only (the always-true
  `say(True,..)` and the hard-coded "report says" quotes are gone). Exit 2 if no bench results.
- paper_data.py: reads a fair run dir; writes <run>/derived/{paper_data.json,readme_table.md,paper_chart.png} (not into the repo tree);
  every number is a min-max over seeds, ratios are envelopes; adds "vs own dense (same binary, sparsity off)" columns; chart drops
  "faster/slower" wording; extra sparse variants (batched) listed generically.
- verify_all.py: takes RUN (default newest fair-*); sections A (skip if no bench), B, C, D, E (PDF; skip), F (zip; skip), G, H.
  D now: same seeds for every chip, each log passed + >=2/>=4 CPU-reference matches, program header N:M matches the chip name, pair counts
  vs count COMPUTED from i/k/j (old `tiles*2` tautology gone), array time within 15% of N/M (two-sided, was one-sided), sameprog vs Berkeley
  worst pair within 1% (printed with the actual value; old claim "cycle for cycle" no longer asserted), no silent skip when the JSON is
  missing (paper_data.json check removed: derived files are recomputed, H compares README table to readme_table()).
  G: run-folder SHA256SUMS must cover every file (new/unlisted files FAIL), static-file MANIFEST (bin/, logs/, *.c, *.out) is checked if
  present and files outside it FAIL; no MANIFEST = SKIP with an instruction (I did not write one: fair_perf.c is still being edited).
  H: README <!-- results:begin/end --> block must equal the computed table; no block = skip (README states no results).
  No results -> exit 2 with message, B and C still run. Report written to <run>/derived/verify_all_report.md.
- Verified on scratch copies (old logs as seeds 1,2): all pass; tampered log -> G fails; wrong pair count, wrong grid time, sameprog off by
  >1% -> D fails; NM_RUNS_DIR=/nonexistent -> "NO FAIR RESULTS", rc 2.

### Item 4c: analysis/ chart scripts (done)
- advanced_visuals.py [RUN]: reads a fair run dir via nmdata; bars = mean, label = min-max; speed-ups = envelope over seed combinations;
  outputs to <run>/derived/figures/ (not the source tree); wording fixed: "Array time (compute state), weights reused" (was "Multiplier grid
  working time"), fig5/6 "energy kept (sum of squares)", synthetic-weights caveat in the subtitle; "faster/slower" words use the envelope.
- make_charts.py / chart_all_data.py: read bench-<cfg>-<stamp>/{cycles.csv,<test>.log} (--bench-nm24/--bench-nm48/--out, default newest);
  removed unused idle_gap and the fig7 "design history" chart (its numbers were hard-coded from logs that were deleted); axis limits now
  computed from data; fig1/fig5/fig9 captions no longer call ex_active "busy/utilisation" and fig9 says the wait counters tick while idle;
  groupby().last() (mixed runs) is gone (one folder per config). Exit 2 + message when no bench results exist.
- Verified on scratch copies of the old logs: all figures render; NM_RUNS_DIR=/nonexistent -> rc 2 with message.
