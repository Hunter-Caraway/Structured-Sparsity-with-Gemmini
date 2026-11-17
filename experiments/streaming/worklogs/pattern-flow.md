# pattern-flow: one-command N:M flow (`./run-flow.sh pattern <pat>`)

Agent: pattern-flow agent, started 2026-11-17. Scope: `run-flow.sh`, new files in `experiments/streaming/tools/`, this worklog.
No sims, no builds on the server, no git commits.

## Steps
1. Read AGENTS.md, run-flow.sh, branch-status.md, fixb-srv-failures.md, fixb-scripts.md, merge-plan.md, area-flow.md, bank-split-impl.md.
2. Facts gathered (read-only):
   - Server sims (2026-11-17 ls): GemminiRocketConfig (Nov 9), GemminiNMRocketConfig (Nov 13 15:56), GemminiNM48RocketConfig
     (Nov 13 16:00); no `*.src.sha256` build lists; no nm816 sim. 12 `simulator-chip*` running (9 stock, 3 nm24).
   - Server sources: gemmini 639a5068 / libgemmini a14aaa1 / rocc-tests 61086b4 on `sparse-nm` with applied diffs (old HEADs);
     laptop: bank-split-fix 7b19c038 / 4886238 / 2ad1fd3, clean. So src comparison must be by file content, not HEAD.
   - Old server runner `~/fixb/run_jobs.sh` ran `make run-binary-fast` 12 in parallel in sims/verilator (AGENTS: never
     parallel make in sims/). New driver calls the simulator directly with the same args make passed (log line 2-7 of
     `investigate/runs/20261113-160015-fixb-srv/nm24.matmul.seed1.log`) and echoes that command into the log.
   - Passing sim logs have no total-cycle line. Rates (cycles/s) only from timeouts and `sbench end cycle`: timeouts in
     20261113-160015-fixb-srv: nm24 1177-1201, nm48 1227-1238 c/s (`(timeout) after N` / jobs.tsv wall_s).
   - nm_sparse_loop_24 full: 53,248 s at 600M budget, passed (20261115-225958-fixbfail-srv/jobs.tsv). x 1177 c/s = ~62.7M
     cycles (ESTIMATE). Bank-split Spike instr 59,512,572 / 23,101,494 = 2.576 (bank-split-impl.md step 9) -> ~162M cycles
     (ESTIMATE) < 300M floor; wall ~38 h (ESTIMATE). Floor kept at 300M.
   - parse_fixa/collect/verify_all: collect.py writes into its run dir and needs ref/ + `program` column, chips only
     stock|nm24|nm48; verify_all takes fair-run folders (`<chip>.seed<S>.log`), EXPECT has no nm816. Both get a staging
     copy under the flow folder (recorded run never written).
   - Area: `area/` holds only `verilog_closure.py` + `runs/`; `worklogs/area-run.md` has no entry-point yet. Yosys is on the server.
3. Code written (uncommitted):
   - `run-flow.sh`: `nm_table` (pattern, n, m, config) drives cfg_name/pat_nm/lib_nm, step_tests, build_fair;
     loop_neg += 92; prog_timeout 300M floor now `^nm_sparse_loop_[0-9]+-baremetal$` (covers _816); new
     `pattern <pat>` (stages spike/sim/srv, DRY_RUN, FLOW, APPROVED_REBUILD, QUOTA, SCHED_HINTS) and
     `pattern-finish <pat> <flow>`; header documents both.
   - `tools/pattern_flow.py` (reuse / schedule / summary), `tools/pattern_srv_driver.sh` (server job runner, direct
     simulator call, QUOTA + 12 cap), `tools/pattern_srv_build.sh` (server rebuild with backup + build-time list).
   - `bash -n`, `shellcheck -S warning` clean; py_compile ok; table lookups and prog_timeout unit-checked
     (nm_sparse_loop_816 -> 300M, neg92_816 -> 150M).
4. Tool tests on recorded data (scratch `<scratchpad>/pf-test/`, recorded folders only read):
   - summary on 20261113-160015-fixb-srv (hand-made plan): numbers equal branch-status.md (nm24 bert_ffn1 berkeley
     1,438,096, sparse_loop 1,207,250, ratio 1.191; fair_perf_24 dense 1,544, sparse_loop 2,779); known failures
     (nm_sparse_loop 20M timeout, gemmini_counter, global_average, conv_with_input_dilation*) reported FAIL, rc 1.
   - schedule: per-chip slowest measured rate for budget-bound jobs (stock bench rates 393-496 c/s from `sbench end
     cycle` / wall_s in 20261113-160015-fixb-srv; nm 1177-1238 from timeouts); analogs (nm816 -> nm24 / _24 programs).
   - reuse: R1 stock sha 84c2264a + R1 bin -> 12/12 stock jobs reused; wrong sha -> 0 reused, 12 scheduled.
5. nm24 Spike stage launched: `SCRATCH_DIR=build-scratch/pattern-flow PAR=4 STAGES=spike ./run-flow.sh pattern nm24`
   (output in session scratchpad `spike-nm24.out`, flow folder `investigate/runs/<stamp>-nm24-flow/`).
6. Mock tests (session scratchpad `drvtest/`, `bldtest/`, fake HOME, stub simulators / Makefile; nothing on the server):
   - driver: QUOTA=2 holds 2 jobs at once; jobs.tsv rows with exit codes (stub assert -> exit 1); STATUS ALL_DONE;
     `sha256sum -c SHA256SUMS` ok; log line 1 = the simulator command with `+verilator+seed+S`.
   - build: backup (old sim + generated-src + SHA256SUMS), `<sim>.src.sha256` = pre-build list + `# sim sha256=`,
     STATUS BUILD_DONE; GemminiRocketConfig refused (BUILD_FAILED).
7. nm24 Spike stage (real): rc 0, 122 pass lines, 0 FAIL (session scratchpad `spike-nm24.out`; copy in
   `investigate/runs/20261117-145939-nm24-flow/pattern.out`, Spike output `spike.log`). 177 programs built; spike step 98
   (54 dense, 6 nm_sparse, 3 fair, 6 NEG, 27 loop NEG incl. 92, 2 dense-lib NEG) + 24 bench runs (6 layers x
   full/fixa/loop/dense, "sbench passed (k of k runs verified)"). 119 programs in `bin/` (`bin.sha256`), libs in `spike.info`.
8. Schedule fixes after first dry run: rates only from jobs >= 3600 s wall (start-up skews short ones: 41 of 78 kept);
   families `_fixa|_loop -> _full`, `nm_sparse_*_negN -> longest recorded NEG`, sameprog -> stock.
9. Dry run (`SCRATCH_DIR=build-scratch/pattern-flow DRY_RUN=1 STAGES="sim srv" FLOW=investigate/runs/20261117-145939-nm24-flow
   ./run-flow.sh pattern nm24`), rc 0, output session scratchpad `dry-nm24.out`, files in
   `build-scratch/pattern-flow/pattern-dryrun-20261117-150333-nm24/`:
   - would STOP: server sources differ from laptop in 12 lines = 6 files (bank-split files: Configs.scala, GemminiConfigs.scala,
     LoopMatmul.scala, gemmini.cc, gemmini_nm.h, nm_sparse_loop.c); nm24 sim has no build-time list.
   - stock: 6 fair jobs reused from 20261113-160015-fixb-srv (same stock sha 84c2264a, same load image); 6 stock benches scheduled.
   - 0 free slots (12 running); schedule shown for 12 slots: 122 jobs, predicted 70.5 h. Over 24 h: 3 conv_with_input_dilation*
     (69.4-70.5 h, budget-bound upper bounds: timed out at 150M before), nm_sparse_loop_24 38.1 h (53,248 s x 2.576 hint),
     conv_with_kernel_dilation 27.5 h (99,170 s, R1).
   - `pattern-finish` not-done path tested on a scratch flow.state pointing at convbudget-srv: prints progress, rc 3.

## RESUME HERE
- Done: all code + tests above. Nothing running. No server writes, no sims, no builds, no commits.
- Not tested end to end (needs a real server run): upload/launch, copy-back, the collect/verify_all staging and
  summary inside `pattern-finish`, the rebuild wait loop. Driver and build script only mock-tested.
- Next: coordinator review; server sync of bank-split sources + user-approved rebuild
  (`STAGES="sim srv" FLOW=experiments/streaming/investigate/runs/20261117-145939-nm24-flow APPROVED_REBUILD=1 ./run-flow.sh pattern nm24`,
  with SCRATCH_DIR=build-scratch/pattern-flow); clear SCHED_HINTS once a bank-split nm_sparse_loop run exists.
