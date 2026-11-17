# verify-generalize: pattern-agnostic parse_fixa / collect / verify_all

Agent: verify-generalize, started 2026-11-17. Scope: `experiments/streaming/tools/parse_fixa.py`,
`experiments/streaming/scripts/collect.py`, `verification/verify_all.py`, the `pattern-finish` lines of `run-flow.sh`
that call them, this worklog. No server, no sims, no commits. Recorded runs only read (tests on scratch copies).

## Steps
1. Read the three tools, nmdata.py, run-flow.sh pattern-finish (lines ~1234-1258), pattern-flow.md.
   Findings: collect.py hardcodes chips (CHIP_CFG, LOGNAME, summary order); parse_fixa.py also hardcodes
   `(nm24|nm48|stock)` and `_(24|48)$`, so an nm816 log is skipped silently; verify_all.py relies on nmdata
   (CHIPS/LOG_RE/PATTERN/require nm24+nm48: a single-pattern staging folder gives NoResults rc 2) and writes
   `<run>/derived/` (must not run on a recorded folder in a mode that has fair logs).
   Originals saved in session scratchpad `vg/orig/` for before/after.
2. (predecessor, from diffs) collect.py: chips from run.info sim.<chip>= lines, unknown chip / bad log name exits
   non-zero. parse_fixa.py: chips from run.info, `_<nm digits>` suffix stripped per chip, non-job .log listed NOT JUDGED.
   verify_all.py: `--mode run` (sections I S J V R) + `--extra-log`; paper mode untouched.
3. (resumed 2026-11-17, new agent) verify_all.py compiles; all helpers present. Before/after default-mode proof
   (`vg/run_old.sh`, run with committed tools -> `vg/before/`, current -> `vg/after2/`): all 9 commands same rc and
   byte-identical masked output/CSV/summary. rcs: parse_fixa fixb-srv 1, collect 140015 0, collect 144252 1 (mixed
   sims, needs its flag), collect stage24 0, verify fixb-srv 1 (STATUS not in SHA256SUMS), fair-both 1 (no sameprog
   log), fair-nm24 2 (no nm48), default 0, mixed 0. All pre-existing.
4. `--mode run` on fixb-srv: rc 1, output `vg/runmode/fixb.out`. Only J fails: the 8 logs parse_fixa already fails
   (6 conv_with_input_dilation* timeouts at 150000001 cycles, nm24/nm48 nm_sparse_loop_* TestDriver assert), the
   recorded faults of that run. I, S, V (48 bench logs), R (ratios 0.538 / 0.537 vs 0.5) pass.
5. Synthetic nm816 (`vg/tools/make_syn816.py`: fixb-srv nm48 logs relabeled nm816/8:16, same 1/2 density so pair
   counts and ratios hold; stock fair/bench logs; fake sim sha; SHA256SUMS regenerated) -> `vg/syn816`.
   verify --mode run rc 0 (56 checks, 1 skip: no nm816 fair_perf_dense_only), parse_fixa rc 0 (NEG neg10_816 PASS),
   collect on a pattern-finish-style staging copy (`vg/syn816c`, refs from build/data/<L>/48 with n,m=8,16) rc 0,
   36/36 rows verified. Outputs `vg/runmode/syn816*.out`.
6. Negatives (all rc != 0): neg1 one sparse_stream check line set to a wrong hash + MISMATCH, SHA256SUMS regenerated
   -> V FAIL rc 1; neg2 same without new sums -> I and V FAIL; neg3 log of chip nm1632 (not in run.info / nm_table)
   -> S FAIL, parse_fixa rc 1; neg4 collect on the unverified log -> rc 1, 35/36 verified; empty folder -> rc 2.
   Fix from neg1: V message counted variants with a total line as "verified"; now counts verified ones
   (verify_all.py:418).
7. run-flow.sh pattern-finish (lines 1248-1252): fair-staging folder + paper-mode call replaced with
   `verify_all.py --mode run "$dest"` plus `--extra-log` per stock-reused.tsv log. Tested by extracting those lines
   into `vg/flowtest/t.sh` on `vg/synx` (syn816 without stock fair logs, 3 reused from fixb-srv): rc_all=0, 64 checks.
   bash -n ok. Recorded run folders: git status clean.

## RESUME HERE
Done: steps 1-7, all tests above. Scratch outputs in session scratchpad `vg/` (before/, after2/, runmode/).
run_old.sh writes scratch copies to `experiments/streaming/build/verify-generalize-scratch` (build dir, not a run).
Open: run-flow.sh header comment (line ~53) still says verify_all.py gets "staging copies"; not edited (scope).
`$seeds` in pattern-finish may now be unused by this block. Nothing running. No commits.
