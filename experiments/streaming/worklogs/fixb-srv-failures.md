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
