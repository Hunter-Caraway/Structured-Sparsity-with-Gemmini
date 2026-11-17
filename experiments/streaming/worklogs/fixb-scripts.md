# fixb-scripts: script support for sparse-loop-fix (Fix B), round 2

Agent: Fix B scripts agent, 2026-11-13. Branch `spad-index-fix` (uncommitted tree, nothing committed by this agent).
Scope: `run-flow.sh`, `experiments/streaming/scripts/build.sh`, `experiments/streaming/scripts/collect.py`,
`verification/verify_all.py`, `experiments/streaming/tools/parse_fixa.py`.
Scratch: `/tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-r2/scripts/`.
No measured numbers in this file except counts quoted with their log path.

## Inputs read
- `fix-b-spec.md` Changelog 2026-11-13 (D1-D5, dense list = 54).
- Berkeley `bareMetalC/Makefile:70-71`: `runs_baremetal := $(filter-out matmul_spad-baremetal.run mvin_mvout_spad-baremetal.run,...)`.
- Sample logs: `experiments/streaming/investigate/runs/20261112-235246-fixb-spike-tests/bench/` (RUN3).
- Seen in the fork trees (not yet confirmed by the coordinator): libgemmini `Makefile` already has `NM_DENSE_BUILD ?=`
  (`NM_DENSE_BUILD=1` adds `-DNM_DENSE_BUILD`); `nm_sparse_loop.c` already has `NEG == 133` (N13 range case).

## Steps
1. `run-flow.sh` dense list: `step_tests` reads Berkeley's `tests =` list and the Makefile's
   `runs_baremetal := $(filter-out ...)` line (sed), removes those names, dies unless 54. Dies too if the filter line is absent.
   Result: "134 bare-metal tests built (54 dense, without matmul_spad mvin_mvout_spad; ...)", rc=0
   (`<scratch>/run-flow-tests.out`).
2. `run-flow.sh` NEG runner: new `lib_nm`, `spike-lib dense24|dense48` (`NM_DENSE_BUILD=1`, own dir `libgemmini-dense<pat>`;
   the make log must show `-DNM_DENSE_BUILD` for dense and must not for nm), helper `spike_loop_neg <lib> <note> <n...>`;
   `spike <pat>` runs `loop_neg` on the nm lib and `loop_neg_dense` (110, 140) on the dense lib of the same pattern and
   dies if that lib is missing. `loop_neg` gained 133 (N13 range case, already in `nm_sparse_loop.c`). `all` builds dense24.
   Coordinator message received mid-task: same make line + `NM_DENSE_BUILD=1`, expected sha256 dense24 7617dce5...3745,
   dense48 8eb89b8a...efef7. Built libs match both (`sha256sum <scratch>/libgemmini-dense*/libgemmini.so`; build log
   `<scratch>/spike-lib.out`). `spike nm24` and `spike nm48`: rc=0, 45 pass lines each, incl. NEG 133, 110, 140
   (`<scratch>/spike-nm24.out`, `spike-nm48.out`; Spike output in `logs/runs/spike-20261113-145047.log`, `...-145049.log`).
3. `build.sh`: `<layer>_24_loop` / `<layer>_48_loop` = `-DRUN_MASK=16`; `_24_loop` joins the .text identity check, `_48_loop`
   is checked against `_48_full`. `BIN_DIR=<scratch>/sbench build.sh small`: rc=0, 8 programs (`<scratch>/build-small.out`);
   both run on Spike, "sbench passed (1 of 1 runs verified)" (`<scratch>/small_24_loop.mask16.log`, `small_48_loop.mask16.log`).
4. Parsers.
   - `collect.py`: `sparse_loop` in TOT/CHK/MASK_VARIANTS (bit 16) and the summary table; `sparse_loop tiles:` line parsed
     into new last CSV columns `loop_tile_I/J/K`; a sparse_loop row without exactly one tiles line is verified=no.
   - `parse_fixa.py`: loop NEG logs (`nm_sparse_loop_neg<n>` or `loop_neg<n>`) judged by message text + an
     `at <File>.scala:<line>` line (lines not pinned); NEG 110/140 on RTL fail; fair `*_loop` totals need their own
     "matches the cpu reference"; streaming sparse_loop needs "-> verified" and one tiles line. Also fixed a crash:
     `sorted(fair)` compared dicts when one chip+seed had two fair programs.
   - `verify_all.py`: `LOOP_EXPECT`; if any log of the run has a `*_loop` variant, every log must have its build's set, each
     matched once. Runs without loop variants are judged as before.
5. Parser tests on RUN3 logs (copies in scratch; RUN3 folder untouched). collect.py was run as a byte-identical copy
   (`<scratch>/cx/scripts/collect.py`, `cmp` clean) because it writes into the run folder and needs the run under its own root.
   - collect, raw Spike logs: 24 rows, 0 verified, rc=1 (`collect-raw.out`): expected, Spike logs carry no
     `+verilator+seed+` and no chip config name.
   - collect, same logs + one SYNTHETIC first line holding those two markers: 24 rows, 24 verified, rc=0 (`collect-synth.out`,
     `cx/collect-synth/results.csv`). Tiles line removed from one log: 23 verified, 1 not, rc=1 (`collect-notiles.out`).
   - parse_fixa, RUN3 bench + pos logs with a scratch jobs.tsv: rc=0 (`parse_fixa-run3.out`). Negative fixtures: 5 of 6 fail
     as intended, rc=1 (`parse_fixa-neg.out`). Recorded Fix A run `20261111-183018-fixa-srv`: rc=0, "tests: 56 PASS, 0 FAIL"
     (`parse_fixa-fixa-srv.out`), as before.
   - verify_all `sec_d` only (imported, no sections A-C/E-H): loop checks PASS on the 3 RUN3 fair logs
     (`verify_all-ok.out`; the 3 FAILs there are the sameprog and N/M-ratio checks, expected for Spike logs) and FAIL when a
     loop line is removed (`verify_all-bad.out`).
   - `bash -n` on both shell scripts and `py_compile` on the three Python files: clean.

## TODO / open
- N13 range NEG: 133 is wired in from the source tree; the coordinator had not yet confirmed the final name. If it changes,
  edit `loop_neg` in `run-flow.sh` only (messages are keyed by n / 10).
- RTL assert source lines for loop NEG are not pinned in `parse_fixa.py` (`LOOP_MSG`); pin `(message, file:line)` pairs like
  the Fix A table once the RTL build is fixed. Server log naming for loop NEG is assumed (`nm_sparse_loop_neg<n>_<pat>` or
  `loop_neg<n>_<pat>`).
- `build.sh` `_loop` = mask 16 (sparse_loop only). RUN3's hand-built `_loop` programs were mask 17 (berkeley + sparse_loop).
  collect.py reads the mask from the log header, so both parse; the name means two things across runs.
- `parse_fixa.py` "fair ranges" pool `fair_perf_<pat>` and `fair_perf_dense_only` of one chip under one key (old behaviour, not changed).
- `collect.py` cannot take a run folder outside `experiments/streaming/` (`relative_to(HERE)`, old behaviour, not changed).
- `run-flow.sh spike` now needs the dense lib; `check` lists dense24/dense48.

## RESUME HERE
Done: tasks 1-5 above; all edits uncommitted on `spad-index-fix`. Running: nothing. Scratch outputs in
`/tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-r2/scripts/` (session
scratch; copy out anything worth keeping). Next: the TODO list above; then RTL `rerun` on the server once a
sparse-loop-fix simulator exists (not started, needs user approval for any rebuild).

# Round 2: run-flow gaps
2026-11-13. Only `run-flow.sh` edited (uncommitted, branch `spad-index-fix`, HEAD 7fd60dc). Scratch
`<scratchpad>/runflow-r3`; run folder `experiments/streaming/investigate/runs/20261113-151044-runflow-r3/` (R below).
Gaps came from `worklogs/fixb-final-spike.md` (stale `verification/build/fair_perf_*`; 2 of 54 dense tests).

## Steps
1. Gap 1, stale fair programs. New `build_fair <dir>` (the four `rv_cc_nm` lines, moved out of `step_fair_build`, which now
   calls it for `verification/build`). `step_spike` calls `build_fair "$scratch/fair"` on every run and runs those
   programs; it no longer reads `FAIR_BIN` / `verification/build`. `verification/bin` is never written.
   A zero exit is no longer enough: `fair_perf_<pat>` must print "dense_loop matches the cpu reference" and
   "sparse_loop matches ..."; `fair_perf_dense_only` must print the dense_loop line.
2. Gap 2, dense tests. The Makefile-derived list moved from `step_tests` into `dense_tests` (global `dense_list`, dies
   unless 54). `step_spike` dies if any of the 54 programs is missing, runs them all on the n:m lib `PAR` at a time
   (`clamp_par`, cap 12; `timeout 600` each), prints one pass/FAIL line each in list order, and counts any non-zero exit.
3. Header text updated (`spike`, `PAR`, `FAIR_BIN`).

## Results (all in R)
- `bash -n run-flow.sh`: clean.
- `spike-lib nm24|dense24|nm48|dense48`: rc 0 (`spike-lib-*.out`); lib sha256 equal to the final-spike run (`run.info` of both).
- `tests`: rc 0, "134 bare-metal tests built (54 dense ...)" (`tests.out`).
- `spike nm24`, `spike nm48`: rc 0, 97 pass lines each, 0 FAIL (`spike-nm24.out`, `spike-nm48.out`): 54 dense, 6 nm_sparse,
  3 fair, 6 NEG, 26 loop NEG, 2 dense-lib loop NEG. Fair lines: "pass  fair_perf_24 (dense_loop sparse_loop verified)",
  same for `fair_perf_48`; Spike output `spike-nm24.log` / `spike-nm48.log` lines 694, 696, 719.
- Negative checks, each rc 1: an aborting program in place of `conv-baremetal` -> "FAIL  conv (exit 255)"
  (`neg-dense-fail.out`); `matmul-baremetal` moved away -> "missing ..." (`neg-dense-missing.out`); mutant script that
  expects sparse_loop from `fair_perf_dense_only` -> "FAIL ... no 'matches the cpu reference' line for sparse_loop"
  (`neg-loop-line.out`, `mutant-run-flow.sh`). Scratch programs restored afterwards.
- `PAR=1`: rc 0, 97 pass (`spike-nm48-par1.out`). `PAR=40`: clamped to 12, rc 0, 97 pass (`spike-nm24-par40.out`).
- `$RISCV/lib/libgemmini.so` and `verification/build/*` sha256 unchanged (`riscv-lib-before.sha`,
  `verification-build-before.sha`; compared after the runs). gemmini-rocc-tests `git status`: clean.

## Open
- `./run-flow.sh fair-build` was not run after the `build_fair` refactor (it would overwrite the 2026-11-03 programs in
  `verification/build`); the same helper is exercised by `spike`. `verification/build` is still stale for the RTL `fair` step.
- `spike` now calls `restore_params_h` (through `build_fair`), as `tests` and `fair-build` already do.
- `run-flow.sh` wrote its usual untracked logs to `logs/runs/` (`libgemmini-20261113-1508*.log`, `spike-20261113-15*.log`).

## RESUME HERE
Done: both gaps fixed in `run-flow.sh`, tested, outputs in R with `SHA256SUMS`. Running: nothing. No git writes.
Next: coordinator review; decide whether to run `fair-build` to refresh `verification/build` before any RTL `fair` run.

## NEG table fix 2026-11-15
Edited only `run-flow.sh` and `experiments/streaming/tools/parse_fixa.py` (uncommitted, branch `spad-index-fix`). No sims, no
server, no git writes. Scratch outputs: `<scratchpad>/negfix/{before,after}-<run>.{out,err}`, mutant folder `negfix/mut2/`.
Runs parsed: A = `investigate/runs/20261111-183018-fixa-srv`, B = `investigate/runs/20261113-160015-fixb-srv`.

### Changes
1. NEG 10 text. `fix-b-spec.md:232` ("N2 replaces the LOOP_CONV_WS half of the existing Controller.scala:281 message (the LOOP_WS
   half is replaced by N1)") and RTL `Controller.scala:298-301` (11cc20cd) confirm the old combined assert is gone. B's
   `nm{24,48}.nm_sparse_protocol_neg10_*.seed1.log` print N1 at `Controller.scala:298`.
   - `run-flow.sh:95` `neg_msg 10` = the full N1 text. `run-flow.sh:708` escapes the message's ERE specials (it is a
     `grep -E` pattern; N1 has `()[]`), as the loop NEG line already did. Checked: the escaped pattern matches B's neg10 log
     (1 line) and not its neg9 log (0).
   - `parse_fixa.py:35-36,56`: `proto_neg10` accepts the old text (run A's build) or N1 (run B's build).
2. Source lines. `parse_fixa.py:19-57`: the NEG table holds message texts only (feature prefix + message). A NEG passes when
   every assert it prints has an accepted text and its own `at <File>.scala:<line>` line (`:137`); the line is printed, not
   checked. `parse_fixa.py:60,131-133`: `nm_sparse_protocol_neg<n>` (B's names) maps to the `proto_neg<n>` entries (A's names).
3. Dense tests. `parse_fixa.py:66-78` lists Berkeley's 54 dense tests (Makefile `tests` at gemmini-rocc-tests 22158bf, without
   nm_* and the two spad tests). `:161-167`: a dense log passes when jobs.tsv exit is 0, its last non-empty line has
   `Verilog $finish`, and it has no `*** FAILED ***`, `Assertion`, `%Error`, `%Fatal` or `Verilog $stop`. Dense rows print in
   the `== tests` table. `:15-16`: jobs.tsv program column may be `binary` or `program`.

### Results
| run | before | after |
|---|---|---|
| A | rc 0; tests 56 PASS, 0 FAIL | rc 0; tests 56 PASS, 0 FAIL; stdout byte-identical (`diff` of before/after `.out`) |
| B | rc 1; "120 failed or missing logs, 212 logs judged"; tests 62 PASS, 12 FAIL; 108 dense logs FAIL in streaming | rc 1; "12 failed or missing logs, 212 logs judged"; tests 170 PASS, 12 FAIL; streaming 30 ok, 0 FAIL |

B's 12 FAILs after: `nm_sparse_loop_24/48` (timeout assert, `TestDriver.v:147`); `gemmini_counter`, `global_average`
(`*** FAILED *** (tohost = 1)`); `conv_with_input_dilation`, `..._and_rot180`, `..._and_neg_padding` (timeout after 150000001
cycles); each on nm24 and nm48. All 12 have exit 2 in B's `jobs.tsv`.
- `bash -n run-flow.sh`: clean.
- Mutant folder (`negfix/mut2/`, copies of B's logs with a made-up jobs.tsv): exit 0 with FAILED text -> FAIL; clean log with
  exit 2 -> FAIL; exit 0 without the `$finish` line -> FAIL; neg10 log holding the neg9 assert -> FAIL; neg9 log with its
  `at ...scala` line removed -> FAIL; unchanged `template` log -> PASS; rc 1. Same result with the column renamed `program`.
- B's `SHA256SUMS` verifies after the work (run folder untouched).

### Open
- B has 12 `stock.*` logs (jobs.tsv chip `stock`). The parser only reads `nm24.` / `nm48.` logs, so they are not judged and not
  reported (212 judged of 224 jobs). Not changed here; behaviour predates this fix.
- Spike's NEG 10 check in `run-flow.sh` only needs a `GEMMINI:` abort line, not a specific text, so it needed no change.
- `spad_neg*` entries now also match on text only; no `spad_neg` log exists on the sparse-loop-fix build to test them against
  (A's 34 pass unchanged).

## RESUME HERE
Done: all three items, tested on A and B. Running: nothing. No git writes. Next: coordinator review; decide whether the parser
should judge the `stock.*` logs.
