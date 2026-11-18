# Anomalies worklog: open anomalies after the Fix A server run

Started 2026-11-12. Scope: investigate 5 anomalies (fix-a-server.md "Anomalies", investigate.md section 19,
fix-a-review.md M3, the seeds question) and fix the Fix A parse script's NEG check.
Rules: no edit of any existing source file (another agent edits investigate/src and gemmini_nm.h), programs built
only in scratch (laptop scratchpad `anom/`, server `~/anom/`), at most 3 concurrent simulations on the server, new runs
only in `~/sinv/runs/<timestamp>-anom-srv`, no simulator rebuild, no git commit/stash/reset.
Laptop scratch: `/tmp/claude-1000/-home-hunter-gemmini-sparsity/02a1660a-afd8-4d63-b078-262a0414bff5/scratchpad/anom/`.

## Checklist
1. [ ] fair_perf push-path variants moved >1% vs fair-20261103-151404
2. [ ] small 4:8 keeper dense_v3 17,884 vs 18,288
3. [ ] nm48 qkv keeper3 first null window `read_cycles delta 49`
4. [ ] M3: cross-step LOAD into a bank the previous step still reads
5. [~] RANDOM_SEED: does it reach the simulator? (static part only)
6. [x] parse.py: check the NEG source file:line

## 6. parse.py NEG check (done 2026-11-12)
- Old check (`fixa-srv/parse.py`, original kept as scratch `anom/parse.py.orig`, sha256 a174f909...): an expected text
  could match on any line, including the Verilator `at Controller.scala:<n> assert(..., "<msg>")` echo of the source,
  and the source line was never compared.
- New check: every `Assertion failed: <msg>` line is paired with the `at <File>.scala:<line>` line after it. A NEG
  passes only if it has at least one pair, every pair is an accepted (message, file:line) for that case, rc != 0 and no
  `NOT caught`. Accepted pairs = the fix-a-server.md "Results" table (spec section 7, fix-a-sw.md:139-141, run-flow.sh
  neg_msg; M6 double asserts: 24 = :604 or :611, 28 = :606 or :608; proto 4 = :575 or :611). Lines checked against the
  laptop Controller.scala / ExecuteController.scala, whose `git diff HEAD --binary` sha256 27c66ae5... equals the diff
  the 20261111 sims were built from.
- Rerun on `investigate/runs/20261111-183018-fixa-srv`: `tests: 56 PASS, 0 FAIL`, 44/44 NEG PASS (scratch
  `anom/parse_fixa.out`). The non-NEG output is identical to the old `fixa-srv/parse.out`.
- Mutation check (scratch `anom/parse-mut/`, 6 copied logs): wrong line (23 -> :611, 24 -> :606), an extra unexpected
  assert (28 + :629), a missing `at` line (proto 4), a wrong message on the right line (37) all FAIL; unchanged
  proto 9 PASS. The old parser passed all 6 (the 37 mutant passed through the echoed source text).
- Copied to `experiments/streaming/tools/parse_fixa.py` (new file; sha256 000ad782..., same as `fixa-srv/parse.py`).

## 5. RANDOM_SEED (partial, stopped 11:15 at the coordinator's checkpoint; no run made)
Static evidence only so far (laptop Chipyard tree, same flow as the server):
- The seed reaches the sim: `sims/verilator/Makefile:31-32` turns RANDOM_SEED into `+verilator+seed+$(RANDOM_SEED)`,
  `common.mk:372` adds it to every run; the Fix A logs show it (e.g.
  `investigate/runs/20261111-183018-fixa-srv/nm48.small_48_keeperfixa.seed2.log` has `+verilator+seed+2`).
- The sims are built with `+define+RANDOMIZE_MEM_INIT +define+RANDOMIZE_REG_INIT +define+RANDOMIZE_GARBAGE_ASSIGN
  +define+RANDOMIZE_INVALID_ASSIGN` (`sims/common-sim-flags.mk`), `RANDOM` = `$random` in the generated SV, and
  `--x-initial fast --x-assign fast` (`sims/verilator/Makefile:105-106`). The verilated C++ of the 4:8 model has 6871
  `VL_RANDOM_I` (+61 _Q, 45 _W) init calls (`generated-src/.../GemminiNM48RocketConfig/*.cpp`), and the `--main` main()
  calls `contextp->commandArgs()` before constructing the model (`VTestDriver__main.cpp:13`), so the seed is set before
  the initial blocks run. Verilator is 5.022 (conda env).
- Working hypothesis (NOT yet measured): the seed is not a no-op; it changes the random initial register / SRAM
  contents, but every timing-relevant state is reset before the program runs, so the cycles do not depend on it.
  `+verilator+rand+reset+2` would matter only with `--x-initial unique` (rebuild needed), and only for state the
  RANDOMIZE_* blocks do not cover.

## RESUME HERE (written 2026-11-12 11:15 EST)
Done:
- Item 6 (parse.py): done, see section 6. `experiments/streaming/tools/parse_fixa.py`; 44/44 NEG and 56/56 tests PASS.
- Item 5: static part only (section 5).
Running on the server: NOTHING. No simulation was started, no `~/anom/` or `~/sinv/runs/*-anom-srv` folder was made.
A read-only `ssh ... uptime; ps` status check was still pending at hand-back.
Not started: items 1, 2, 3, 4 (no findings yet beyond the inputs in fix-a-server.md "Anomalies" and investigate.md 19).
Next steps:
1. Item 5, empirical: on the server, run the nm24 simulator binary directly (not via make) twice, in
   `~/sinv/runs/<ts>-anom-srv`, with `+verbose +max-cycles=200 +verilator+seed+1` and `+verilator+seed+2` and any
   test binary: TestDriver.v:40-46 prints `testing $random <x>`; different values = the seed reaches `$random`.
   Stronger: a scratch program (laptop `scratchpad/anom/`) that mvouts never-written scratchpad and accumulator rows and
   prints a hash; run seeds 1 and 2. Different hashes + identical cycles in all runs = seed works, timing is
   insensitive to initial state.
2. Item 1 (fair_perf): build in scratch the recorded fair_perf.c (git HEAD version, `git show HEAD:verification/fair_perf.c`)
   against the current header; run on the new nm24/nm48 sims. Same cycles as fair-20261103-151404 = the RTL did not
   change the push path, so the moves come from the fair_perf.c edits / code layout. Compare `objdump` of the timed
   functions of the recorded binary (verification/runs/fair-20261103-151404 or ~/fair-bin on the server) and the new one.
3. Item 2 (small 4:8 dense_v3 17,884 vs 18,288): the keeper3 and keeperfixa binaries differ (keeper source changed for
   Fix A); compare dense_v3 code addresses / objdump. Option: run the keeper3 binary
   (`investigate/runs/20261109-204637-keeper3-srv` binary) on the new nm48 sim to split RTL vs layout.
4. Item 3 (`read_cycles delta 49`): read `investigate/runs/20261109-204734-keeper3qkv-srv/nm48.bert_qkv_48_keeper3.seed1.log`
   and investigate/src/stream_bench.c null window; likely first-touch I-cache / D-cache misses on the first window.
5. Item 4 (M3): A/B in scratch: copy investigate/src to `scratchpad/anom/`, move the cross-step LOAD at
   `tiled_matmul_nm_v2.h:184` (or put step g's first batch in the other bank), build small 2:4 / 4:8, run on the server
   (max 3 sims), compare sparse_fixa totals with 15,500 / 15,637 (fix-a-server.md table).
