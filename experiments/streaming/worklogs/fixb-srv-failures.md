# fixb-srv-failures (diagnosis only, no source edits)
Source run: server ~/sinv/runs/20261113-160015-fixb-srv (local copy investigate/runs/20261113-160015-fixb-srv).
Diagnosis run: server ~/sinv/runs/20261115-225958-fixbfail-srv (stock gemmini_counter, stock global_average, nm24/nm48 nm_sparse_loop at 600M cycles).

## Findings so far
- B gemmini_counter: stock sim fails identically (Read DMA 331 / snapshot 331 / "Cycles after snapshot is reset: 331" -> "Counter values changed too little"), stock.gemmini_counter.seed1.log. Test file unchanged vs Berkeley base 7c540b3 (git diff --stat). Class: Berkeley (pre-existing).
- C global_average: nm output == gold when printed, yet "Fail". Source include/gemmini.h:3402-3440 tiled_global_average has no gemmini_fence() before the CPU compare (race with last mvout). Stock also prints "Fail" (stock.global_average.seed1.log). Class: Berkeley.
- D conv_with_input_dilation(+_and_rot180,+_and_neg_padding): all stuck in "CPU conv..." (no "CPU conv took" line) at 150M. CPU conv cost from passing nm24 logs: conv_with_rot180 1.78M MACs -> 43.5M cycles (24 cyc/MAC). input_dilation: dilated 33x33, 2 batch, 19 oc, 162 MAC/out = 6.7M MACs -> ~164M cycles for CPU conv alone > 150M. neg_padding out 29x29 -> 5.2M MACs -> ~127M + rest. Class: budget (CPU reference), not hardware.
- A: see below.
- B stock check: stock.gemmini_counter.seed1.log (server run 20261115-225958-fixbfail-srv, exit 2, 69 s) fails identically: counter 331/331/331. Stock global_average also printed "Fail" (same log dir; the sim was still finishing when SSH dropped).
- A: nm_sparse_loop first 6 cases ok then no output within 20M. Hypothesis: CPU make_case (gold matmul, ~24 cyc/MAC) + 8-loop cases need > 20M. Test: scratch copy of the test (this dir: fixb-srv-failures-nm_loop_from7.c.txt) that skips cases 1-6 and prints per-case "CYC <cycles>"; binaries on server ~/fixb/failprogs/nm_loop7_{24,48}-baremetal.
- Also failing: conv_with_input_dilation_and_neg_padding nm24/nm48 (150M timeout, "CPU conv..." last line); same class as D.

## Conv budget stock control check 2026-11-17 (NOT launched)
- Stock re-runs in 20261115-225958-fixbfail-srv used bin/gemmini_counter-baremetal sha 39b7db84... (SHA256SUMS), the same sha as in run 20261113-160015-fixb-srv/bin; so the stock control already used run-1-style binaries.
- Committed gemmini_params.h at rocc-tests HEAD = sha256 3758ae96...da924 (git show HEAD:include/gemmini_params.h | sha256sum, 2026-11-17) = the stock dense params (dense-spad-check.md:7); it has no GEMMINI_HW_NM_* macros. Laptop include/ is clean vs HEAD now.
- run-flow.sh step_tests (lines 439-447) calls restore_params_h (committed header) then rv_cc with no NM flags for the 54 dense tests, so conv_with_input_dilation* are built with that header by design.
- NOT proven: no record (run.info, worklogs, logs) of the header sha at the time run-1 binaries (20ee07f3.., 01a9f72a.., 46adb343..) were built; run.info lists only gemmini_nm.h sha. Build-scratch is gone, so sha cannot be compared. Did not launch.
- Needed: user OK to rebuild the 3 tests in a laptop scratch dir (run-flow.sh tests, header restored first, header sha recorded) and compare binary shas to run-1 bin; if identical -> proven valid for stock, launch. Or user accepts the by-design argument above.

## Stock conv + stock dense runs 2026-11-17
- Binary proof (laptop scratch, `SCRATCH_DIR=<scratchpad>/rf ./run-flow.sh tests`: restore_params_h + rv_cc, no NM flags): gemmini_params.h sha256 3758ae96...da924, rocc-tests 22158bf, riscv64-unknown-elf-gcc (g6afcc4f6d) 16.1.0. 54 dense tests rebuilt; none byte-identical to run-1 bin.
- All 3 conv_with_input_dilation* + the other 51: objdump -d identical, objdump -s of all sections identical, same size; only 5-6 bytes differ = gcc temp object name (ccXXXXXX.o) in .strtab. Fresh binaries used; both shas recorded in each run's build.info/fresh*.sha (run-1 shas = 20261113-160015-fixb-srv/SHA256SUMS).
- Run A: ~/sinv/runs/20261117-111223-convbudget-stock-srv, stock sim (sha 84c2264a.. checked), 3 conv tests, seed 1, 300M, PAR=3; driver PID 702823 (PPID 1), sims 703061 703148 703201.
- Run B: ~/sinv/runs/20261117-111434-stockdense-srv, stock sim, 51 dense tests (54 minus 3 conv_with_input_dilation*), seed 1, 750M each (nm24 cycles not logged in run-1; all nm24 runs finished <150M so 5x <= 750M), PAR=6, slow tests first; driver PID 704747 (PPID 1). Quota total 12 (nm24 run 3 + A 3 + B 6).
- gemmini_counter / global_average expected to fail (B4/B5).
- Status: `cat ~/sinv/runs/<run>/STATUS` on the server (ALL_DONE when finished).

## RESUME HERE (superseded by the one at the end, 2026-11-17)
SSH socket DOWN at 2026-11-15 ~23:15 (Permission denied). Stopped.
Running on server (if they survived): ~/sinv/runs/20261115-225958-fixbfail-srv (stock gemmini_counter done; stock global_average, nm24/nm48 nm_sparse_loop_{24,48} at 600M budget -- ~1200 cyc/s so ~6 days, kill them if the CYC test settles it) and ~/sinv/runs/20261115-230636-fixbfail2-srv (nm_loop7_24/48, 150M, per-case CYC lines; STATUS written when done).
Next: after reconnect read both folders (jobs.tsv, logs). If CYC lines appear for case 7+ -> budget issue, need budget = sum of CYC for all 22 cases + cases 1-6 (~20M+).
D: needs ~200M+ cycles budget (input_dilation CPU conv ~164M est), ~50+ h wall; not launched.

## Copy-back 2026-11-17
- Copied via ssh + python tarfile stream into `investigate/runs/`: `20261115-225958-fixbfail-srv` (15 files, 144K; STATUS ALL_DONE Mon Nov 16 02:04:20 PM EST) and `20261115-230636-fixbfail2-srv` (11 files, 92K; STATUS ALL_DONE Mon Nov 16 10:32:38 AM EST).
- Checksums: `sha256sum -c SHA256SUMS`: fixbfail 12/13 OK, fixbfail2 8/9 OK; the one failure in each is `run.out` (SHA256SUMS written 5 ms before run.out/STATUS final write, so the server's own SHA256SUMS is stale for run.out). Full sha256 of every file computed on server and locally and diffed: identical for both runs (diff clean). Unlisted files: SHA256SUMS, STATUS (both runs) and run.out stale entry. Nothing modified after copy.
- Scratch binaries: `bin/nm_loop7_{24,48}-baremetal` are already in fixbfail2 `bin/` and sha256 match server `~/fixb/failprogs/`: nm_loop7_24 `11f8e76dbec9303be77501dcafa09072a8cda9c19a70480e3d176ffe94e98b35`, nm_loop7_48 `cb4784f239a6bacadb42566136840e3165cbc8791774747582e0deec4f48f932`. No `progs/` copy made. Source is `fixb-srv-failures-nm_loop_from7.c.txt` in this dir.
- fixbfail jobs.tsv: stock gemmini_counter exit 2 (69 s), stock global_average exit 2 (712 s), nm24 nm_sparse_loop_24 exit 0 (53248 s, 600M budget), nm48 nm_sparse_loop_48 exit 0 (54256 s). Both nm logs end "nm_sparse_loop passed". So nm_sparse_loop passes given 600M cycles: the earlier 20M timeout was budget, not hardware. Stock counter/global_average logs end "*** FAILED *** (tohost = 1)" (Berkeley failures, as diagnosed above).
- fixbfail2 jobs.tsv: nm_loop7_24 exit 0 (39772 s), nm_loop7_48 exit 0 (41157 s), 150M budget, both "nm_sparse_loop passed", 11 CYC lines each (cases 7-17 of the scratch test). CYC nm24: 4460944 6211780 1517481 579958 7066270 151091 737949 1088752 2868934 2654427 1238942 (sum 28576528). CYC nm48: 4636274 6318628 1697399 653266 7180327 158645 771465 1192379 3012026 2775022 1298142 (sum 29693573). Sums are of the printed CYC lines only (source: nm24/nm48 `.seed1.log`).
- parse_fixa.py (rc, output in session scratchpad `parse.<run>.out`): fixbfail rc=0: tests 2 PASS 0 FAIL (nm_sparse_loop_24/48 s1 PASS), fair_perf/streaming empty. fixbfail2 rc=1: "nm_loop7_24/48 s1 FAIL (no sbench passed)", parser judges it as a streaming bench; limitation (unknown program), logs themselves show "nm_sparse_loop passed".
- Odd: the two stock jobs show exit 2 in jobs.tsv (make Error 255 with tohost=1). `git status` shows both folders untracked (not committed, per instructions).

## RESUME HERE
Done: both runs copied and verified (above). No sims running by this agent; none needed. Findings: A (nm_sparse_loop) is a cycle budget issue, passes at 600M; B and C are stock/Berkeley failures; D (conv_with_input_dilation*) still unrun, needs ~200M+ budget (~50+ h wall), not launched.
Next: coordinator decides on D run and whether to raise the nm_sparse_loop timeout in run-flow; update parse_fixa.py to know nm_loop7 / dense logs if wanted.

## Conv budget run 2026-11-17
- Run: ~/sinv/runs/20261117-110726-convbudget-srv (server), launched 2026-11-17 11:07 EST (epoch 1794931646), user-approved, quota 3.
- Jobs: nm24 (GemminiNMRocketConfig) only, seed 1, TIMEOUT_CYCLES=300000000: conv_with_input_dilation, ..._and_rot180, ..._and_neg_padding (parallel).
- Binaries: bin/ from 20261113-160015-fixb-srv, sha256 verified against its SHA256SUMS before use (46adb343.., 01a9f72a.., 20ee07f3..).
- Sim sha256 checked before launch = 1042fc926288a463c829cdfe654a5515b6243ca56ae19b425fd7d542bf237891 (run.info sim.nm24 agrees). 0 other sims running.
- Launch: driver.sh (nohup setsid; PPID 1, own session) -> ~/fixb/run_jobs.sh with PAR=3; driver writes SHA256SUMS after run.out/STATUS (ordering fix). STATUS=ALL_DONE at end.
- Sim PIDs at +2 min: 702325, 702412, 702465 (all ~100% CPU, driver 702084).
- Note: logs do not grow while running (benchmark prints only at the end, same as earlier runs); liveness = CPU time via ps.
- Check: `ssh -o ControlPath=/tmp/claude-1000/cm-%C -o BatchMode=yes ai-user@ai-1769.floridapoly.org 'cat ~/sinv/runs/20261117-110726-convbudget-srv/STATUS; ps -o pid,etime,time -p 702325,702412,702465'`

## RESUME HERE
- Running: ~/sinv/runs/20261117-110726-convbudget-srv (3 sims, ETA ~55 h at ~1200 cycles/s, i.e. ~2026-11-19 evening). Do nothing until STATUS=ALL_DONE.
- Next: copy back to experiments/streaming/investigate/runs/ with SHA256SUMS verified; check each log for verified output (cycle count counts only if verified, rule 4).
- Also running: 20261117-111223-convbudget-stock-srv (driver 702823) and 20261117-111434-stockdense-srv (driver 704747); see section "Stock conv + stock dense runs". 12 sims total.

## Stock dense copy-back 2026-11-18
- Run: ~/sinv/runs/20261117-111434-stockdense-srv (STATUS `ALL_DONE Wed Nov 18 06:48:34 AM EST 2026`), 63 files, copied via ssh cat per file into `investigate/runs/20261117-111434-stockdense-srv/`. `sha256sum -c SHA256SUMS`: all 162 OK (rc 0).
- `python3 verification/verify_all.py --mode run <run>`: ALL CHECKS PASSED (7 checks, 2 skipped): 51 jobs.tsv rows = 51 logs, one stock sim (sha 84c2264a..), 49 jobs exit 0, 2 known Berkeley failures (stock gemmini_counter, stock global_average; berkeley-issues.md) not counted, parse_fixa.py rc 0. Streaming/fair checks skipped (no such logs).
- Own check (grep every `*.log`): 49 logs contain `Verilog $finish` and none of FAILED / %Error / assert; gemmini_counter and global_average end `*** FAILED *** (tohost = 1)` + `Verilog $stop` (jobs.tsv exit 2). Dense tests self-check (tohost=0 = pass); no cycle claims made.
- Coverage: 51 of Berkeley's 54: 49 pass, 2 known Berkeley fails; the 3 conv_with_input_dilation* are in the convbudget-stock run (still running). So stock dense is 49/51 pass here.

## RESUME HERE (stockdense only; convbudget entries above unchanged)
- stockdense: DONE, copied and verified (above). Nothing running from this run.
- Next: coordinator decides if 2 Berkeley failures stay excluded; 3 conv_with_input_dilation* pending from convbudget-stock run.
