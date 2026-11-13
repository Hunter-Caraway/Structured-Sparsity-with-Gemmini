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
