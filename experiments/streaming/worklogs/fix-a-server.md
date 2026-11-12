# Fix A server worklog: rebuild of the 2:4 / 4:8 simulators on ai-1769 and the Fix A test + benchmark runs

Started 2026-11-11 18:10 (laptop time). User approval (2026-11-11): back up the server's 2:4 and 4:8 simulators,
elaborate, rebuild only those two simulators from the Fix A sources, then run tests and benchmarks.
Berkeley's stock simulator (GemminiRocketConfig) is not rebuilt or touched.
Access: the existing ssh socket only (`ssh -o ControlPath=/tmp/claude-1000/cm-%C -o BatchMode=yes ai-user@ai-1769...`).
No git commit/stash/reset/checkout anywhere. No laptop file changed except this worklog and the copied run folder.
Laptop scratch: `/tmp/claude-1000/-home-hunter-gemmini-sparsity/02a1660a-afd8-4d63-b078-262a0414bff5/scratchpad/fixa-srv/`.
Server scratch (scripts, logs, binaries): `~/fixa/`.

## Plan / checklist
1. [ ] Transfer laptop sources to the server (gemmini src/, libgemmini, gemmini-rocc-tests, fair_perf.c, streaming
       src + investigate/src, streaming data of the layers run), sha256 of every file.
2. [x] Backup (done before the transfer, so the backup holds the server's prior trees).
3. [ ] Build GemminiNMRocketConfig, then GemminiNM48RocketConfig (serial, nohup). Save each elaboration's
       gemmini_params.h.
4. [ ] Build tests + benchmarks on the server against the generated headers (new folder, nothing old overwritten).
5. [ ] Run: tests (nm24 + nm48), fair_perf, streaming (keeper RUN_MASK=224, v1 RUN_MASK=12), seeds 1-3.
6. [ ] Copy the run folder back to investigate/runs/, sha256-verified.
7. [ ] Parse + compare (Fix A vs push, vs Berkeley, push vs earlier v3/keeper3 numbers).

## Laptop provenance (source of truth)
- gemmini 639a5068bc7f01c5c8fed5a4bea15a55963c60a3, `git diff HEAD --binary | sha256sum` = 27c66ae5931490a7...
  (8 files: Controller, ExecuteController, GemminiConfigs, MeshWithDelays, PE, ReservationStation + 2 submodule lines)
- libgemmini a14aaa15ed5fa34e61ddf73e302be00af9538d51, diff sha256 ab50c82854dfcda0... (Makefile, gemmini.cc, gemmini.h)
- gemmini-rocc-tests 61086b433e1b7fb57bcd22634d03b4285f9d00cf, diff sha256 42b75980ab9df5c3... (6 files) + untracked
  bareMetalC/nm_sparse_protocol.c, bareMetalC/nm_sparse_spad.c
- gemmini-sparsity 1e50e1c45b8b607e2899562d6c51d4343c99a3ac, diff sha256 6dae4a342f1fe468... (fair_perf.c modified;
  experiments/streaming/src and investigate/src untracked)

## Step 2: backup (18:16, before the transfer and before any build)
- `~/fixa/backup.sh` -> `~/backup-prefixA-20261111/` (1.2 GB, 4061 files, `SHA256SUMS` inside), log `~/fixa/backup.log`.
  Every file compared by sha256 with its source: sims nm24 97b5d3b2... and nm48 ddf8b694... MATCH, generated-src
  nm24 1445 files / nm48 1457 files MATCH, gemmini src 561 / libgemmini 8 / gemmini-rocc-tests 586 files MATCH,
  generated gemmini_params.h (the 4:8 one, GEMMINI_HW_NM_N 4 / M 8) saved as gemmini_params.h.generated.
- Stock simulator before anything: `84c2264ab08524b8e6b6f822b53ebb8613e381219e5ccb8144ad9cc9543b75e4`
  (`~/backup-prefixA-20261111/stock-sim.sha256.before`; same value as the recorded runs' run.info).

## Step 1: transfer
- Before: server vs laptop file lists (`list.sh`: every tracked + untracked non-ignored file of the 3 repos + the
  benchmark sources): 11 files differ (Controller, ExecuteController, GemminiConfigs, ReservationStation, libgemmini
  gemmini.cc/.h, rocc-tests Makefile, gemmini_nm.h, gemmini_params.h (server: generated 4:8), fair_perf.c), 1 missing
  (nm_sparse_spad.c), and the server has no experiments/streaming/ tree (7 files missing).
- Transfer (18:18): only the 10 differing gemmini/libgemmini/rocc-tests files + nm_sparse_spad.c (laptop `tar -cf -`
  piped into server `python3` tarfile, filter="tar", laptop mtimes kept), and fair_perf.c, experiments/streaming/src/*,
  experiments/streaming/investigate/src/* plus all 96 files of experiments/streaming/build/data/ (6 layers x 2 patterns,
  28 MB) into the matching paths under the server's `~/gemmini-sparsity/`. `~/sinv/src` (old copies) untouched.
  The server's gemmini_params.h (generated 4:8) was replaced by the laptop's committed one (backup has the old one).
- After: `list.sh` on both sides: ALL 238 FILES MATCH (gemmini incl. src/, libgemmini 6, rocc-tests 122, 8 benchmark
  sources); data 96/96 match. Server `git diff HEAD --binary | sha256sum`: gemmini 27c66ae5..., libgemmini ab50c828...,
  rocc-tests 42b75980... = the laptop values; `git status --short` identical.
- Lists: laptop scratch `fixa-srv/{laptop,server-before,server-after,data-laptop,data-server}.sha256`.
- [x] Step 1 done.

## Step 3: simulator builds (`~/fixa/build_chain.sh`, nohup setsid, started 18:19:32 server time = EST)
- Serial: `make -j12 CONFIG=GemminiNMRocketConfig`, then 4:8; logs `~/fixa/logs/build-<cfg>.log`, summary
  `~/fixa/logs/chain.log`, status `~/fixa/logs/BUILD_STATUS`. After each build the generated header is saved to
  `~/fixa/hdr/<24|48>/include/gemmini_params.h` (the 4:8 elaboration overwrites the 2:4 one in the tree).
- 2:4 elaboration (first full-SoC elaboration of the Fix A Controller): OK. sbt `success` (compile 94 s), Chisel
  "There were 26 warning(s) during hardware elaboration", the same 26 `[W005] Dynamic index` warnings as the 11-09
  build (`~/logs/build-GemminiNMRocketConfig.log`), identical after stripping line numbers. firtool + Verilator ran.
  Generated header: GEMMINI_HW_NM_N 2, GEMMINI_HW_NM_M 4, GEMMINI_HW_NM_SPAD_ROWS_PER_TILE 4.
- Program build script `~/fixa/build_progs.sh <new dir>` and runner `~/fixa/run_jobs.sh <run> <jobs>` written
  (runner = investigate/scripts/run_bins.sh + PAR 12 + nm24/nm48 only + STATUS file).
- 2:4 build: BUILD_EXIT=0, 314 s, min MemAvailable 23.2 GB. New sim sha256 c9664cc017251e2927131ba5602681d57286acdff81d5a6f7e4da824a200a36f.
- 4:8 build: BUILD_EXIT=0, 202 s, min MemAvailable 29.2 GB. Same 26 `[W005]` elaboration warnings as the 11-09 build
  (identical modulo line numbers). New sim sha256 4b414e5a3679dc232ee84a62fc9de3c23f794c1432621753ded5e1eb6b22d637.
- Headers: 2:4 434f86be... (HW_NM_N 2, M 4, SPAD_ROWS_PER_TILE 4); 4:8 2731193e... (4, 8, 6). The two differ only in
  those 3 lines; the 4:8 one differs from the pre-Fix-A generated header only by the new SPAD_ROWS_PER_TILE line.
  The gemmini_params.h in the server's rocc-tests tree is now the generated 4:8 one (so that repo's diff hash in
  run.info is 91c2a09c..., not the laptop's 42b75980...; the only difference is that generated header).
- Generated Verilog: the loader asserts ("n:m index loader") are in gen-collateral/ExecuteController.sv of both chips.
- Stock simulator after both builds: 84c2264ab08524b8e6b6f822b53ebb8613e381219e5ccb8144ad9cc9543b75e4 (unchanged).
- [x] Step 3 done (18:28).

## Step 4: programs (`~/fixa/build_progs.sh ~/fixa/progs`, 18:28-18:30, 84 s)
- 70 programs, `~/fixa/progs/build.info` (sha256, pattern check `[n:m hw=n:m R=r]` from `-dM -E`, extra flags):
  per pattern 6 positive tests (nm_sparse_sw/debug/matmul/perf/protocol/spad), proto NEG 4/7/9/10/14 (run-flow.sh
  neg_rtl; 6 is Spike-only), spad NEG 21..37, fair_perf, and streaming for edge/small/bert_qkv:
  `<L>_<p>_keeperfixa` = investigate/src/stream_bench.c -I investigate/src -DUSE_KEEPER -DRUN_MASK=224,
  `<L>_<p>_v1fixa` = src/stream_bench.c -DRUN_MASK=12.
- Every compile: NM_N:NM_M = the pattern, GEMMINI_HW_NM_N:M = the pattern, GEMMINI_HW_NM_SPAD_ROWS_PER_TILE 4 / 6
  (so gemmini_nm.h's _Static_assert ran against the generated value).
- None is byte-identical to the laptop scratch builds in ~/gemmini-fixwork/fixa (those used the stock header and the
  pre-17:50 gemmini_nm.h). Spike cross-check of the server binaries on the laptop: see step 5.
- Layers: edge, small, bert_qkv only (the recorded keeper3 server numbers are small + qkv; rn50/ffn1/ffn2 would need
  ~1.5-5 h per job x 3 seeds x 4 programs).

## Step 5: runs: `~/sinv/runs/20261111-183018-fixa-srv` (started 18:30:18)
- `nohup setsid ~/fixa/run_jobs.sh <run> ~/fixa/jobs-20261111-183018-fixa-srv.txt`, 98 jobs, PAR 12, out
  `~/fixa/logs/run-20261111-183018-fixa-srv.out`, done marker `<run>/STATUS`.
- Run folder also holds build.info, hdr/{24,48}/gemmini_params.h, build-chain.log, and the 3 scripts.
- Timeouts: tests 20M cycles, fair 150M (run-flow.sh default), bert_qkv 30M, small/edge 15M.
- Order: spad positive x2, qkv seed 1 x4, fair x6, other tests x54, qkv seeds 2-3, small x12, edge x12.
- Spike cross-check of the exact server binaries (copied back, 70/70 sha256 = build.info) on the laptop Fix A Spike
  libs `~/gemmini-fixwork/fixa/lib/fixa{24,48}` (their gemmini.cc/.h == the current libgemmini sources, cmp):
  script + logs in laptop scratch `fixa-srv/{spike_check.sh,spike-logs/}`. 12/12 positive tests print "<t> passed";
  44/44 NEG builds abort (rc 255) with the expected GEMMINI message; all 12 streaming programs "sbench passed"
  (keeper 3 of 3, v1 2 of 2 verified); fair_perf passed on both. Spike totals equal the fix-a-sw.md table
  (e.g. qkv 2:4 keeper sparse_v3 303711 / sparse_fixa 287902; fair 2:4 sparse_batched 1667 / sparse_spad 884).
- [x] Step 4 done.
- Speed: ~800 simulated cycles/s per sim at 12 parallel (fair_perf_24 printed prep_warm, ~0.75M cycles, after 16 min).
  Spike instruction counts of all 70 programs (laptop scratch `fixa-srv/instret.txt`): every spad NEG build runs
  make_data() first (2.45M / 2.58M instructions before the illegal command), nm_sparse_spad 2.7M, fair_perf 3.0-3.3M.
  Estimate for the whole set ~340M cycles, ~10 h at 12 parallel; the 34 spad NEG builds are about half.
- 19:15: queue after line 13 reordered in place (same 98 jobs; first 13 lines byte-identical, the runner's read
  offset is at line 14): remaining positive tests + proto NEG, small x12, edge x12, qkv seeds 2-3 x8, spad NEG x34.
  Original order `~/fixa/jobs-original-order.txt`; new order also in the run folder (`jobs-reordered-1915.txt`,
  `NOTE-reorder.txt`).

## Status at hand-back (~19:20 EST, agent asked to report early; the runs keep going on the server)
- Running unsupervised: `~/fixa/run_jobs.sh` (nohup setsid) on `~/sinv/runs/20261111-183018-fixa-srv`, 98 jobs,
  12 at a time, expected ~10 h in total. Done when `<run>/STATUS` says ALL_DONE (SHA256SUMS is written then).
- First RTL output: nm_sparse_spad on nm24 and nm48 print "load 4, early ok (0/2048 wrong)" and
  "loads of 1,3,2,2 ok (0/2048 wrong)"; nm24 also "register tile, then loads ok (0/2048 wrong)". No job has finished.
- Still to do: step 6 (copy the run folder to investigate/runs/20261111-183018-fixa-srv, sha256-verified, with the
  python tarfile stream) and step 7 (laptop scratch `fixa-srv/parse.py <run dir>` judges tests/NEG messages and prints
  the fair and streaming tables with seed ranges; comparison numbers are listed below).
- Comparison numbers already pulled from recorded logs: Berkeley stock (runs/20261109-144252) edge 4304, small 14840
  (3 seeds), qkv 316791; v1 sparse_stream nm24 edge 8310 / small 29777 / qkv 651640, nm48 9448 / 34518 / 743192;
  keeper3 (investigate/runs/20261109-2047*) nm24 small dense_v3 17900 sparse_v3 17957, qkv 452257 / 452740;
  nm48 small 18288 / 20431, qkv 452088 / 496569; fair (server.md) Berkeley dense 1555 / dense_reuse 1541,
  nm24 sparse_batched 2110, nm48 sparse_batched 2964.
- [ ] Step 5 running, [ ] step 6, [ ] step 7.

## Results (2026-11-12)
Collection, verification and parsing only. No simulation or build was started, and no source file was changed.
Run: `~/sinv/runs/20261111-183018-fixa-srv`, STATUS `ALL_DONE Thu Nov 12 02:28:01 AM EST 2026`.

### Copy (step 6)
- Copied to `investigate/runs/20261111-183018-fixa-srv` with the python tarfile stream over the existing ssh socket.
  The server copy is kept.
- 182 files on each side. `sha256sum -c SHA256SUMS` passes on the laptop. That file lists 180 files: every file except
  itself and STATUS.
- A sha256 of all 182 files (including SHA256SUMS and STATUS) was computed on both sides. The two lists are
  byte-identical. Lists: laptop scratch `fixa-srv/{local-all,server-all}.sha256`.

### Jobs (step 7)
- `jobs.tsv`: 98 jobs. 54 exit 0 (12 positive tests, 6 fair_perf, 36 streaming); 44 exit 2 (all NEG builds). Wall
  time 35-9966 s. No job hit its cycle timeout. Every exit-0 log contains `Verilog $finish`.
- Positive tests: 12/12 print `<test> passed` (nm_sparse_{sw,debug,matmul,perf,protocol,spad}, 2:4 and 4:8).
- NEG: 44/44 stop on exactly one `Assertion failed`. Message and source line per case (identical on nm24 and nm48),
  checked against the spec section 7 table, fix-a-sw.md:139-141 and run-flow.sh `neg_msg`. Line numbers match the
  laptop `generators/gemmini/src/main/scala/gemmini/{Controller,ExecuteController}.scala`:
  | NEG | source | message (start) | expected |
  |---|---|---|---|
  | spad 21, 22 | Controller.scala:551 | rd values 3..31 are reserved | yes |
  | spad 23 | Controller.scala:604 | tile count rs2[7:0] must be 1..4 | yes |
  | spad 24 | Controller.scala:604 | tile count rs2[7:0] must be 1..4 | yes (one of the two, review M6) |
  | spad 25, 26 | Controller.scala:605 | rs1[63:32] and rs2[63:8] must be 0 | yes |
  | spad 27, 29 | Controller.scala:606 | rs1 must be a scratchpad row address | yes |
  | spad 28 | Controller.scala:606 | rs1 must be a scratchpad row address | yes (one of the two, review M6) |
  | spad 30, 31 | Controller.scala:608 | the index rows must all lie in one scratchpad bank | yes |
  | spad 32 | Controller.scala:610 | rd == 2 while a register-path index tile is half sent | yes |
  | spad 33, 34 | Controller.scala:611 | n:m index fifo: more than 4 index tiles ahead | yes |
  | spad 35 | Controller.scala:622 | register rows (rd == 0) after a scratchpad index load | yes |
  | spad 36 | Controller.scala:617 | clear (rd == 1) between a sparse preload and its compute | yes |
  | spad 37 | Controller.scala:629 | n:m sparse preload with no index tile sent | yes |
  | proto 4 | Controller.scala:575 | n:m index fifo deadlock | yes (run-flow.sh neg_msg 4) |
  | proto 7, 14 | ExecuteController.scala:949 | differs from the mode its weights were preloaded in | yes |
  | proto 9 | ExecuteController.scala:677 | needs weight stationary dataflow | yes |
  | proto 10 | Controller.scala:281 | LOOP_WS / LOOP_CONV_WS issued while n:m sparse mode | yes |
  Review M6 cites the asserts as Controller.scala:600-611. The current lines are 604 (count), 606 (row address),
  608 (bank) and 611 (budget). Only the line numbers differ.
- Streaming: 36/36 logs `sbench passed (k of k runs verified)`. All 90 `<variant> check: ... -> verified` lines say
  verified, including every `sparse_fixa` run (18 logs). fair_perf: 6/6 `fair_perf passed`, each with 6
  `matches the cpu reference` lines (dense, dense_reuse, sparse, sparse_reuse, sparse_batched, sparse_spad).
- parse.py (laptop scratch `fixa-srv/parse.py`) was run unchanged: 56 PASS / 0 FAIL, output `fixa-srv/parse.out`.
  Its NEG check accepts the expected text anywhere in the log and does not check the source line. The table above
  was therefore made separately from the `Assertion failed:` and `at <file>.scala:<line>` lines. The script was not
  changed. Table script: `fixa-srv/table.py`, output `fixa-srv/table.out`.

### Streaming (cycles, `<variant> total` line; seeds 1-3 identical in every log)
Sources: this run's `nm{24,48}.<layer>_{24,48}_{keeperfixa,v1fixa}.seed{1,2,3}.log`. Keeper: dense = dense_v3,
push = sparse_v3, Fix A = sparse_fixa, all from the same binary. v1: push = sparse_stream, Fix A = sparse_fixa. The v1
binary has no dense run (RUN_MASK=12), so "dense (rec.)" is v1 dense_stream from the pre-Fix-A sims in
`runs/20261109-144252/nm{24,48}.<layer>_*.seed1.log`; there is no recorded qkv 4:8 dense (n/r).
Berkeley stock = the `berkeley` line of `runs/20261109-144252/stock.{edge_24_dense,small_24_dense,bert_qkv_24_dense}.seed1.log`
(small seeds 1-3 all 14840). Ratios > 1 mean Fix A is faster. "push vs recorded" compares with keeper3
(`investigate/runs/20261109-204637-keeper3-srv`, `20261109-204734-keeper3qkv-srv`) and v1 (`runs/20261109-144252`).
| layer | pat | tiler | dense same chip | push sparse | Fix A sparse | Berkeley stock | FixA vs push | FixA vs Berkeley | FixA vs dense | seeds 1-3 | push vs recorded |
|---|---|---|---|---|---|---|---|---|---|---|---|
| edge | 2:4 | keeper | 4931 | 5979 | 4989 | 4304 | 1.198x | 0.863x | 0.988x | identical | no record |
| edge | 2:4 | v1 | 4908 (rec.) | 8363 | 5561 | 4304 | 1.504x | 0.774x | 0.883x | identical | +0.64% vs 8310 |
| edge | 4:8 | keeper | 5098 | 6684 | 5051 | 4304 | 1.323x | 0.852x | 1.009x | identical | no record |
| edge | 4:8 | v1 | 4834 (rec.) | 9529 | 5623 | 4304 | 1.695x | 0.765x | 0.860x | identical | +0.86% vs 9448 |
| small | 2:4 | keeper | 17920 | 18015 | 15500 | 14840 | 1.162x | 0.957x | 1.156x | identical | +0.32% vs 17957; dense +0.11% vs 17900 |
| small | 2:4 | v1 | 18634 (rec.) | 29683 | 19973 | 14840 | 1.486x | 0.743x | 0.933x | identical | -0.32% vs 29777 |
| small | 4:8 | keeper | 17884 | 20576 | 15637 | 14840 | 1.316x | 0.949x | 1.144x | identical | +0.71% vs 20431; dense -2.21% vs 18288 |
| small | 4:8 | v1 | 18588 (rec.) | 34344 | 20647 | 14840 | 1.663x | 0.719x | 0.900x | identical | -0.50% vs 34518 |
| bert_qkv | 2:4 | keeper | 451373 | 454535 | 401522 | 316791 | 1.132x | 0.789x | 1.124x | identical | +0.40% vs 452740; dense -0.20% vs 452257 |
| bert_qkv | 2:4 | v1 | 459492 (rec.) | 652222 | 459897 | 316791 | 1.418x | 0.689x | 0.999x | identical | +0.09% vs 651640 |
| bert_qkv | 4:8 | keeper | 451414 | 498115 | 408056 | 316791 | 1.221x | 0.776x | 1.106x | identical | +0.31% vs 496569; dense -0.15% vs 452088 |
| bert_qkv | 4:8 | v1 | n/r | 742933 | 464641 | 316791 | 1.599x | 0.682x | - | identical | -0.03% vs 743192 |

- Fix A beats the push path everywhere: 1.13-1.32x (keeper) and 1.42-1.70x (v1).
- With the keeper tiler, Fix A beats dense on the same chip for small (1.16x / 1.14x) and qkv (1.12x / 1.11x). Edge is
  about even (0.99x / 1.01x).
- Fix A is still slower than Berkeley stock everywhere: 0.95-0.96x on small, 0.85-0.86x on edge, 0.78-0.79x on qkv
  (keeper).

### fair_perf (cycles, `<variant> total`; seeds 1-3 identical)
Sources: `nm24.fair_perf_24.seed{1,2,3}.log`, `nm48.fair_perf_48.seed{1,2,3}.log`. Recorded = `verification/runs/fair-20261103-151404/{nm24,nm48,berkeley}.seed*.log`
(pre-Fix-A RTL and fair_perf.c; server-validated in server.md). The stock chip was not run here: Berkeley dense
1555 / dense_reuse 1541 (recorded).
| variant | 2:4 new | 2:4 recorded | 4:8 new | 4:8 recorded |
|---|---|---|---|---|
| dense | 1555 | 1542 (+0.84%) | 1468 | 1468 (0.00%) |
| dense_reuse | 1502 | 1515 (-0.86%) | 1483 | 1471 (+0.82%) |
| sparse | 2277 | 2281 (-0.18%) | 3152 | 3170 (-0.57%) |
| sparse_reuse | 1375 | 1395 (-1.43%) | 1567 | 1607 (-2.49%) |
| sparse_batched | 2117 | 2110 (+0.33%) | 2910 | 2964 (-1.82%) |
| sparse_spad (Fix A) | 966 | - | 1019 | - |
| cpu_dense | 1104 | 1107 | 1095 | 1095 |
| cpu_dense_reuse | 1071 | 1071 | 1046 | 1061 (-1.41%) |
| cpu_sparse | 1716 | 1725 | 2063 | 2061 |
| cpu_sparse_reuse | 992 | 1013 (-2.07%) | 1130 | 1131 |
| cpu_sparse_batched | 1506 | 1509 | 2148 | 2148 |
| cpu_sparse_spad (Fix A) | 674 | - | 734 | - |
| cpu_meta_only | 960 | 960 | 1493 | 1493 |
M4 caveat: `sparse_spad` keeps the index mvins out of the timed region (`verification/fair_perf.c:370`). It means
"indexes resident in the scratchpad". It is not an end-to-end or fresh-weights number, so do not compare it with
`sparse_batched` or with the Berkeley dense lines as a like-for-like cost. Take end-to-end claims from the streaming
table above, where the keeper bench times the index mvins.

### Anomalies
- No unverified output, no failed test, no timeout, no NEG mismatch.
- Streaming push path vs recorded: all within 1% (largest +0.86%, edge 4:8 v1). Not a push number, but over 1%:
  small 4:8 keeper dense_v3 17884 vs keeper3 18288 (-2.21%).
- fair_perf push-path variants over 1% vs the recorded run: 2:4 sparse_reuse -1.43%, cpu_sparse_reuse -2.07%;
  4:8 sparse_reuse -2.49%, sparse_batched -1.82%, cpu_dense_reuse -1.41%. Both the RTL (Fix A Controller) and
  fair_perf.c (new sparse_spad block, so a different code layout) changed since that run. That run's cycle numbers
  for these variants should not be quoted as current.
- Edge keeper has no earlier record, so its push numbers (5979 / 6684) have nothing to compare against.
- [x] Step 5 done, [x] step 6 done, [x] step 7 done.
