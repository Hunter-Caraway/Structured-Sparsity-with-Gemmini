# Fix log: verification/ (C benchmarks, python checks, launch scripts) (2026-11-03)

Scope: /home/hunter/gemmini-sparsity/verification/ only. No commits. No Verilator. Builds and test data in
/home/hunter/gemmini-fixwork/verification/ (bin/, old-logs copies, runs/).

## nmdata public API (for the analysis/ agent; stable from now on)

Run folder layout read by every script (what run-flow.sh `fair` should write):
- `verification/runs/<name>/`; `<name>` is free (`fair-<stamp>`, `<stamp>`, ...). Newest = largest
  `YYYYMMDD-HHMMSS` stamp found in the name (folders without a stamp sort by mtime, before stamped ones).
- Fair logs: `<chip>.log`, `<chip>.seed<S>.log` or `<chip>-seed<S>.log`, also one level down (e.g. `seed3/nm24.log`).
  `<chip>` = `berkeley` | `sameprog` | `nm24` | `nm48`; `nm24_sameprog` is read as `sameprog`.
- Seed of a log = `+verilator+seed+<S>` in the log's own make command line, else the `seed<S>` in its file or
  folder name, else `"default"`. Two logs of one chip with the same seed: error.
- Env `NM_RUNS_DIR` overrides `verification/runs` (test hook).

```python
import nmdata                            # sys.path.insert(0, "<repo>/verification")
nmdata.NoResults                         # exception; str(e) says what to run. nmdata.die_no_results(e) -> stderr + exit 2
nmdata.CHIPS                             # ("berkeley", "sameprog", "nm24", "nm48")
nmdata.find_runs(args=None)              # [Path]; args = list of run folders (or None = [newest]); raises NoResults
nmdata.parse_log(path)                   # dict, see below
nmdata.load_fair(runs=None, require=("berkeley", "nm24", "nm48"))   # {chip: {seed: parsed log}}, seeds sorted
nmdata.stat(values)                      # {"values", "n", "min", "max", "range", "mean"}
nmdata.metric(chip_logs, variant, key)   # stat over seeds of perf[variant][key]; None if any seed lacks it
nmdata.ratio(num_stat, den_stat)         # (lo, hi) envelope of num/den over all seed pairs
nmdata.fmt_stat(s), nmdata.fmt_ratio(r)  # "1,604" or "1,601-1,612"; "1.04x" or "1.02x-1.05x"
nmdata.summary(fair)                     # {row: {metric: stat}} rows "berkeley", "2:4", "4:8", "off_2:4", "off_4:8",
                                         #   "sameprog" (if present); metrics pairs, busy_reuse, busy_fresh, reuse, fresh,
                                         #   cpu_reuse, cpu_fresh; sparse rows also "batched", "busy_batched", "cpu_batched"
nmdata.load_fidelity()                   # {(distribution, rule): (energy_kept_pct, answer_error_pct)}
```
parse_log(path) -> `{"path", "seed", "passed", "failed", "header": {"n","m","i","k","j"} | None,
"build": "full"|"dense-only"|None, "poison_ok": bool, "ref_ok": [variants that matched the cpu reference],
"perf": {variant: {"total","issued","pairs","cyc_pair", <counter>=int ...}}, "prep": {"prep_cold"|"prep_warm":
{"prep","prune","compress","pack_meta","weights"}}, "ref_checks": int, "matmul": {...}, "debug": {...}}`.
Variant names in fair_perf logs: dense, dense_reuse, sparse, sparse_reuse, sparse_batched, cpu_dense,
cpu_dense_reuse, cpu_sparse, cpu_sparse_reuse, cpu_sparse_batched, cpu_meta_only.
Derived outputs go to `<run>/derived/` (first run folder given), never into the repo tree.

## Plan
1. Cleanup (dead scripts, comments).
2. fair_perf.c / berkeley_dense_perf.c fixes, build, objdump identity, Spike.
3. Python checks rework, tested on copies of old logs.

## Progress
- 08:56 NOTE for the rocc-tests agent: the WIP gemmini_nm.h (`#include <assert.h>` + `assert()` in nm_prune /
  nm_compress) does not link bare-metal with run-flow.sh's rv_cc flags: `undefined reference to '__assert_func'`
  (fair_perf.c, -DNM_N=2 -DNM_M=4). Until that is fixed I test with an overlay copy of the header
  (/home/hunter/gemmini-fixwork/verification/overlay/), never in the repo.
- Item 1 (cleanup): deleted verification/run_fair.sh, run_berkeley.sh, rerun.sh (superseded by run-flow.sh; nothing
  executes them). Remaining text mentions, for their owners: README.md:179 (file table row) and
  tools/report-builders/build_explained.py:127,531 (historical report text naming verification/rerun.sh).
- Item 2 (fair_perf.c) written: warm-up via run() (untimed pass with report() muted, then timed pass); poison()
  (c_out = 0x5A5A5A5A, accumulator tiles overwritten by mvin of a poison tile) before both passes, plus a one-time
  poison_selftest() that reads the poison back; both passes checked (warm-up silently); full-range int8
  (rand()%256-128); new sparse_batched / cpu_sparse_batched; volatile build_mode (0x5F full / 0x0D dense-only,
  both non-zero so it stays in .sdata); need_sparse() guard at the top of every sparse variant and meta_only;
  gemmini_nm_reset() before each sparse run; "so the hardware can overlap them" comment deleted; new
  nm_pack_meta(.., DIM, DIM, ..) signature. Output line formats unchanged; added lines "fair_perf build: ...",
  "poison reaches the accumulator (2048 values)".
- RTL FIFO rule (coordinator, from RTL agent): a tile counts against depth 4 until its compute is issued. Checked:
  sparse ≤ 2 queued (t and t+1), sparse_reuse ≤ 1, sparse_batched ≤ 4 (each batch starts after all earlier computes
  are issued). First preload after every mode change is real (WC_SP / W_SP) in all variants.
- Spike (header = WIP gemmini_nm.h + -DNDEBUG overlay, see note above): fix24 lib: 2:4 full passes (5/5 reference
  checks), dense-only passes (2/2); fix48 lib: 4:8 passes (5/5). Also pass on installed/orig48 spike with reset
  stubbed to a fence (overlay/).
- objdump identity (full 2:4 vs -DDENSE_ONLY, both -DNM_N=2 -DNM_M=4): .text bytes identical (cmp of objcopy -j
  .text), disassembly identical (2126 lines), section headers identical; whole load image differs in exactly 1 byte
  at 0x80004384 = build_mode (0x5F vs 0x0D). Dense-only Spike trace (spike -l): 0 of the 14 funct-26 instructions
  executed; 0 PCs executed in sparse_fresh / sparse_reuse / sparse_batched / meta_only / need_sparse (full build: 14/14).
- berkeley_dense_perf.c: same fixes (warm-up, poison + selftest, full-range int8, prune with NM_N:NM_M, build
  -DNM_N=2 -DNM_M=4); dense_bias is now checked too (reference = gold + sum over kt of a[y][kt*DIM + x%DIM]).
  Spike (installed and fix24): passes 3/3 reference checks. 0 funct-26 instructions in its .text.
- Mutation check (fix24 spike): fair_perf with sparse_reuse's accumulated computes removed, and with
  sparse_batched's computes removed, both FAIL (got 0x5A5A5A5A poison), warm-up and timed pass.
- Rebuilt against the real (fixed) gemmini_nm.h, no overlay, in /home/hunter/gemmini-fixwork/verification/bin/:
  fair_perf_24 on fix24 spike: passed, 5 reference checks; fair_perf_48 on fix48: passed, 5; fair_perf_dense_only on
  fix24 and orig24: passed, 2; berkeley_dense_perf on fix24 and orig24: passed, 3. objdump identity re-done: .text
  bytes identical (sha256 b29ea7cb6ef21c10), disassembly identical (2126 lines), load image differs only at
  0x80004384 (build_mode 0x5F/0x0D). Dense-only trace: 0/14 funct-26 executed, 0 PCs in any sparse function.

## Item 3: python checks (done)
Test data (copies only): /home/hunter/gemmini-fixwork/verification/old-logs (from ~/gemmini-sparsity-old-results),
runs/fair-20261006-120000 (old fair logs, single seed, nm24_sameprog name), runs/fair-20261007-120000 (same logs as
seeds 1 and 2 via +verilator+seed+N in the make line; seed 2 has +3 cycles on four totals),
runs/spike-20261103-090000 (new-format logs from Spike), runs-rr/rerun-* (old re-run logs), runs-t (tamper tests).
- nmdata.py: rewritten (API above). Run folders, seeds, NoResults/exit 2, stat/ratio envelopes, summary() with
  batched rows; hard-coded paths and stamps gone.
- compare_runs.py RUN [REFERENCE]: every log must pass; with REFERENCE every (log, seed) must exist in both and all
  numbers (perf, counters, prep, matmul, debug, matched variants) be identical; missing counterparts FAIL (old version
  skipped them). No REFERENCE = pass checks only, exit 0. Exit 2 if RUN has no logs.
- cross_check.py: bench pipeline only (newest stamp per config in logs/runs, cycles.csv rows of that stamp compared
  in both directions, newest verification/runs/rerun-*). Removed: hard-coded quoted numbers, the always-true
  say(True,..), the constant 26-row count, the all_data.csv check (derived chart data). Exit 2 if no bench logs.
  Old copies: 46 ok, 0 failed; one tampered csv value -> 1 FAIL.
- paper_data.py [RUN ...]: build_data(), readme_table(), chart() -> <run>/derived/{paper_data.json, readme_table.md,
  paper_chart.png}; min-max over seeds, ratio envelopes, adds "same chip dense / sparse (same program)" rows and the
  batched row; no "faster/slower" words. Old copies (seeds 1,2): 2:4 reuse vs Berkeley 0.96x, same-program 1.04x;
  4:8 0.85x / 0.92x-0.93x (matches REVIEW-FINDINGS). Refuses to build numbers from a run that did not pass.
- verify_all.py [RUN ...]: D now checks per chip and seed: passed; current fair_perf.c (build line, poison selftest,
  prep lines) so old-format logs FAIL; every gemmini variant has its own "matches the cpu reference" line (was a
  count); program N:M per chip; pair counts computed from i/k/j/N/M (tiles*2 tautology gone); array time two-sided
  N/M +-10% against the same chip's dense; same seeds on all chips; sameprog vs Berkeley within 1% on every seed pair,
  worded "within 1%" with the actual % (no "cycle for cycle"); the paper_data.json self-comparison is gone. G: run
  SHA256SUMS (all files listed, none extra) + static MANIFEST (new files FAIL); absent = SKIP with message. H: README
  <!-- results:begin/end --> block == paper_data.readme_table(). CHIPYARD_DIR honoured. Exit 2 if no fair results.
  Results: old copies (2 seeds): 42 pass, 12 FAIL (all "OLD-FORMAT LOG" / "missing sparse_batched", as intended),
  5 skip; Spike-format run: all pass except the two array-time checks (Spike's counters are not cycle counts);
  tamper tests: removed reference line -> FAIL, wrong pair count -> FAIL, edited log / extra file -> G FAIL,
  README table off by one number -> H FAIL; NM_RUNS_DIR=/nonexistent -> "NO FAIR RESULTS", rc 2.
- analysis/split.py runs unchanged on the new-format (Spike) logs.

## For other agents
- run-flow.sh (analysis agent): `fair` writes nm24_sameprog.log; nmdata reads both names, but split.py reads only
  sameprog.log, so please write sameprog.log. Seeds: either one folder per seed or <chip>.seed<S>.log; nmdata also
  reads the seed from +verilator+seed+<S> in the log. Writing <run>/SHA256SUMS after a run enables check G.
  compare_runs.py now takes `RUN [REFERENCE]` (exit 0 without reference). step_figures: paper_data.py now writes to
  <run>/derived/ (the "verification/paper_data.json" message is stale) and `> /dev/null && echo` still masks a failure.
  fair-build: build berkeley_dense_perf with -DNM_N=2 -DNM_M=4 if it is built at all (header now requires it).
- README.md: drop the row for run_fair.sh / run_berkeley.sh / rerun.sh (deleted); a results table goes between
  <!-- results:begin --> and <!-- results:end --> and must equal <run>/derived/readme_table.md (check H).
