# Fix log: analysis / tools / flow / docs agent (2026-11-03)

Files: analysis/, tools/, run-flow.sh, README.md, chipyard-setup-notes.md, .gitignore, sparsity.code-workspace.
No commits. No builds or simulations run. Python tests run only on copies in /home/hunter/gemmini-fixwork/analysis/.
A Yosys run of analysis/area.py was in progress at start (pids 98127-98129); area.py was not run and analysis/area/ was not touched.

## Item 3: tools/report-builders (done)
- build_{changes,explained,paper,report}.py: `PROJ = Path(__file__).resolve().parents[2]` (was the dead
  "/home/hunter/Structured 4:8 Sparsity with Gemmini").
- build_changes.py, build_report.py: `GEM` from `CHIPYARD_DIR` (default ~/chipyard) instead of /home/hunter/chipyard;
  build_report.py `short()` derives the display substitutions from GEM and Path.home().
- README.md: path note updated.
- Verified: py_compile of all four; parents[2] resolves to the repo root.

## Item 2: run-flow.sh (done; python CLIs of verify/compare/paper_data follow the verification agent)
Run folder layout written (matches the nmdata API in fixlog-verification.md):
- `verification/runs/fair-<stamp>/<chip>.seed<S>.log` (chip = nm24 | nm48 | berkeley | sameprog), `bin/` (copies of
  the programs that were run), `run.info` (key=value: stamp, seeds, timeout_cycles, step, fair_bin, git.<repo>=HEAD
  [+ dirty flag], sim.<cfg>=mtime + sha256 prefix), `SHA256SUMS` (every file except derived/).
- `verification/runs/rerun-<stamp>/orig-<nm24|nm48>-<test>.seed<S>.log` (+ bin/, run.info, SHA256SUMS).
- `verification/runs/bench-<cfg>-<stamp>/<test>.seed<S>.log` + `cycles.csv` (new `seed` column after `variant`).
Changes:
- Failures loud: rv_cc removes the old output first and checks gcc's exit status (RWX warning still filtered);
  spike-lib no longer masks make failures (`|| true` gone); spike dies on missing programs; baseline checks make's
  status and a PASSED line; sim checks the simulator exists after make.
- Simulations: one queue (`queue`/`run_queue`), PAR at a time (`wait -n -p`); each job's exit code is checked and
  its log must contain the expected lines (fair: `^fair_perf: N:M,`, `^fair_perf passed$`, `+verilator+seed+S`;
  rerun/bench: `^<test> passed$`); any failure -> non-zero exit with a per-job FAIL line. Old `(exit $?)` bug and
  the uncounted `fails` are gone.
- Abort: `trap 'exit 130' INT`, `trap 'exit 143' TERM`; EXIT cleanup kills every running job's process tree
  (pgrep -P walk) and the inhibitor. Mock-tested: TERM mid-run -> rc 143, 0 make/sim processes left.
  (Bug found while testing: a bare `wait` in cleanup also waited on the inhibitor's `sleep infinity`; fixed.)
- No racing make: every run uses BREAK_SIM_PREREQ=1 (never builds); simulators must exist up front (need_sim);
  builds only happen in `sim`, one at a time. EXTRA_SIM_OUT_NAME=<chip>.seed<S>.<stamp> so parallel runs of the same
  program don't share chipyard's output/ log names.
- `sim dense`: refuses unless gemmini, libgemmini, gemmini-rocc-tests are at 8c3f9923 / ea8f7ed / 7c540b3 with no
  tracked changes (no FORCE override for that); FORCE=1 only allows replacing an existing stock sim.
- `fair`: SEEDS (default "1 2 3") -> RANDOM_SEED per run, recorded in run.info and checked in each log; which =
  all|nm24|nm48|berkeley|sameprog; validates sims + programs before creating the folder; refuses an existing folder.
  FAIR_BIN default changed to verification/build (verification/bin holds the old programs).
- `fair-build` / `tests`: `rv_cc_nm` compiles with explicit -DNM_N/-DNM_M and then checks, with `gcc -dM -E` and the
  same flags, that NM_N:NM_M really is the pattern in the name (dies otherwise). Mock-tested with a forced 2:4
  header: "fair_perf_48-baremetal was meant to be 4:8 but compiles as '2:4'". Both restore the committed
  gemmini_params.h first (only if it was changed). tests now builds nm_sparse_{debug,matmul,perf}_24 and _48.
- `bench <cfg>`: no longer touches results/cycles.csv; writes its own folder, cycles.csv via temp file + mv; the
  errexit-on-no-rows bug is gone.
- `spike-lib [nm24|nm48]` passes NM_N/NM_M to libgemmini's make (needs the Makefile hook from the spike agent) with
  -B; `spike [nm24|nm48]` runs that pattern's programs.
- stay_awake warns if systemd-inhibit died at once (P5). Temp-binary staging removed (the ':' folder name is gone;
  `queue` refuses paths with spaces or ':'). `results` variable removed.
- `figures [run...]`, `checks [run...]`, `compare <run> [ref]` pass run folders through.
- Checks: `bash -n` clean, `shellcheck` clean. Mock harness: /home/hunter/gemmini-fixwork/analysis/mock (fake make,
  gcc, objcopy, sims; fake make replays old logs). Tested: fair (2 seeds, PAR=3), a failing sim, wrong N:M in a log,
  missing sim, bad SEEDS, abort, rerun, bench, sim dense guard, fair-build gcc failure and N:M mismatch.
- Follow-ups from the verification agent (done): SHA256SUMS paths are written without "./" (verify_all G keys by
  relative path; mock-checked: "all 12 files match SHA256SUMS"); sparsity-off logs are `sameprog.seed<S>.log`
  (canonical nmdata name; split.py now reads through nmdata, so a bare `sameprog.log` is not needed); fair-build
  also builds berkeley_dense_perf with -DNM_N=2 -DNM_M=4 and checks it; `checks` passes --skip-patches to
  verify_all as before; figures no longer prints the stale paper_data.json path or masks paper_data failures
  (mock: figures exits 1 when paper_data.py refuses failed runs). No caller relies on compare_runs' exit without a
  reference (fair no longer calls it; `compare` passes arguments through).

## Item 4: analysis/ chart scripts (done)
- advanced_visuals.py: `[RUN ...]` via nmdata.find_runs/load_fair/summary; exit 2 with nmdata's message when no run;
  output `<first run>/derived/figures/` (was analysis/advanced/). Bars = mean over seeds, black line = min-max,
  labels = fmt_stat ranges, ratios = nmdata.ratio envelope, "faster/slower" only when the whole envelope is past
  ±2%. New "fresh weights, indexes batched" row in fig1/fig3 when both sparse chips have sparse_batched (compared
  with Berkeley's fresh). fig4 units = Berkeley's pairs (was hard-coded 64). Wording (review §1 #6/#7): "Multiplier
  grid working time" -> "Array time (compute state), weights reused"; "grid idle" -> "rest of the job"; fig5/fig6
  "weights kept / weights' size" -> "energy kept (sum of squares)", synthetic-weights caveat in the subtitles;
  "(realistic)/(stress test)" dropped. Discarded rework reused where it matched the new API.
- chart_all_data.py: rewritten for a fair run: fig7-all-counters (one heatmap per chip, every variant x counter,
  cell = min-max over seeds, shade = mean; captions say ex_active = compute state, rs_full = !alloc.ready, wait
  counters tick while idle) + `<run>/derived/all_data.csv` (chip, seed, variant, counter, value). Dropped the old
  fig9 (mislabelled waits), fig10 (original-benchmark totals) and fig11 (nm_sparse_debug scores): all were charts of
  the superseded original benchmark. No longer imports make_charts.
- DELETED analysis/make_charts.py: every chart (fig1-6) was of the superseded original benchmark (results/cycles.csv,
  deleted), fully covered by advanced_visuals on the fair run; fig7 used numbers hard-coded from deleted logs;
  `idle_gap` was dead. References left: tools/report-builders/build_report.py:220,452 (historical report text in a
  template whose speed-ups are superseded); README row updated.
- split.py (new feature, kept): now reads through nmdata (it looked for `sameprog.log` / `<chip>.log` only, so it
  found no seed logs); per-seed rows in split.csv (new `seed` column), split.md shows min-max over seeds (repay:
  "never on some seeds" when mixed), chart = means; handles sparse_batched; `[RUN ...]`, exit 2 when no run.
- area.py: not changed and not run (Yosys still running the whole session).
- Tested on synthetic run folders built from copies of the old logs (/home/hunter/gemmini-fixwork/analysis/runs:
  fair-20261006-000001 old format, fair-20261103-000002 with fake prep/batched/meta_only lines for code paths only)
  with copies of the scripts in /home/hunter/gemmini-fixwork/analysis/rc; all render; NM_RUNS_DIR=/x -> rc 2.
  Figures inspected visually (two label clippings fixed).

## Item 5: docs (done)
- README.md: results stay withdrawn; run section rewritten for the new flow (SEEDS/PAR, run folder layout,
  derived/, loud failures, sim dense base-commit rule, spike-lib/spike nm48), new paragraphs for `area` and `split`
  (no numbers), Chipyard version 1.14.0-36-gbfa5699f, folder tables updated (analysis scripts, verification
  build/ and runs/; deleted run_fair.sh/run_berkeley.sh/rerun.sh row removed). The pattern percentages already in
  the README equal verification/pattern_fidelity.out (script output), so they stay. No results block added; a
  future table goes between <!-- results:begin --> / <!-- results:end --> (verify_all H).
- chipyard-setup-notes.md: "2:4 and 4:8 both pass on Spike" corrected (no 4:8 Spike log; tests later found weak);
  _24/_48 test builds; "roughly 65-85%" -> "67-86%" (fixes-wip/numbers.py, from the original logs; inside the
  withdrawn section); re-run block and the Spike 4:8 note updated.
- tools/report-builders/README.md: path note.

## Item 1: cleanup summary
- Deleted: analysis/make_charts.py (see item 4). Removed dead code in run-flow.sh: make_tmpbin/stage_bin staging,
  `results` var, csv_row, build_48_tests (folded into tests), ':'-folder note. chart_all_data.py lost its
  make_charts import and the dead latest-logs/cycles.csv cross-check.
- build_explained.py kept (withdrawn, refuses to run; its text mentions verification/rerun.sh as history).
