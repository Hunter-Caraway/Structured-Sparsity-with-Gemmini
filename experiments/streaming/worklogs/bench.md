# Worklog: realistic streaming benchmark (bench agent)

Started 2026-11-09. Spec: NEXT-STEPS.md section 3 + the task brief. All work in experiments/streaming/.

## 0. Orientation (done)
- Read NEXT-STEPS.md, HANDOFF.md, fixes-wip/fixlog-*.md, run-flow.sh, verification/fair_perf.c, gemmini_nm.h,
  verification/runs/fair-20261103-151404/.
- Sims present (not rebuilt): stock GemminiRocketConfig (Oct 6), GemminiNMRocketConfig (Nov 3 15:10),
  GemminiNM48RocketConfig (Nov 3 15:12).
- Repos: gemmini 639a5068, libgemmini a14aaa1, gemmini-rocc-tests 61086b4 (all sparse-nm, uncommitted fix-round
  changes present; not touched).
- Machine facts used in the design (from the generated dts / l2.json of GemminiRocketConfig): system bus 128 bit,
  L2 = 512 KiB, 8 ways, 64 B lines, RANDOM replacement (LFSR victim), L1 D$ 32 KiB, DRAM 256 MiB (DRAMSim2).
  Gemmini: DIM 16, spad 4 banks x 4096 rows x 16 B, acc 1024 rows, MAX_BYTES 64 (block mvin up to 4 tiles,
  acc mvout 1 tile).

## Design decisions
- One C program (src/stream_bench.c), compiled per (layer, pattern) against a generated data header.
  Variants: berkeley (tiled_matmul_auto WS full_C), dense_stream (hand tiler), sparse_stream (tiled_matmul_nm).
  A volatile build_mode / run_mask in .sdata selects what runs, so dense-only (stock chip) and full 2:4 builds of
  a layer have byte-identical .text (checked with objcopy -j .text).
- Timed region per variant: read_cycles() before the first instruction of the matmul call (configs included),
  last mvout + gemmini_fence() at the end. Also cpu_issue_done (CPU returned from issuing).
- Before every timed run: untimed warm-up of the same function on a small sub-problem (I-cache, branch predictors),
  poison C (CPU) + whole accumulator (mvin of a poison tile), then evict L2 with a DMA read of a 4 MiB junk buffer
  (random replacement: P(line survives) ~ (7/8)^64), fence. So every variant starts with cold L2/L1 for A, W, C.
- Check after each timed run: 64-bit FNV-1a hash over all of C (compared in-binary and again by the host script
  against the numpy reference) + full compare of sampled rows embedded in the header.

## 1. Code + data (done, 13:45)
- gen/gen_data.py -> build/data/<layer>/{24,48}/ (A, W pruned, WC compressed, IDX, META packed like nm_pack_meta,
  SREF sampled reference rows, data.h with .incbin, ref.json with hash + sha256s). Layers: small 64x256x128,
  bert_qkv 128x768x768, bert_ffn1 128x768x3072, bert_ffn2 128x3072x768, rn50_conv 196x2304x256, plus
  edge 36x128x64 (partial last row tile; cheap RTL check of the edge paths). Data seed = 20261109 + layer index.
  Host self-checks in the generator: decompress(compress) == pruned W; sparse math == dense math on 3 rows;
  float64 matmul cross-checked against int64 on 3 rows.
- gemmini_nm.h (gemmini-rocc-tests, OUTSIDE experiments/streaming): appended nm_stream_tiles(),
  nm_stream_impl() (always_inline, compile-time `sparse`), tiled_matmul_stream_dense(), tiled_matmul_nm().
  Nothing above the append changed. Backup of the pre-edit file: build/gemmini_nm.h.before-tiled_matmul_nm
  (sha256 d02d2d1f...).
- src/stream_bench.c; scripts/build.sh (5 programs per layer; .text of _24_full/_24_dense/_24_sparse checked
  identical), scripts/spike_lib.sh (scratch libgemmini builds build/spike/nm24, nm48), spike_run.sh, spike_all.sh.
- Tiler: K steps of 64 columns (4 dense / 2 compressed weight tiles), 4 spad buffers (A banks 0/1, W banks 2/3),
  block mvins (<= 4 tiles), output blocks TI x TJ (TI <= 8, TI*TJ <= 32 tiles = half the accumulator), two acc
  halves alternate, mvouts of block b spread over the steps of block b+1; sparse index tiles in batches of <= 4
  right before their preload/computes.

## 2. Spike correctness (done, 13:46)
- `scripts/spike_all.sh` -> build/spike-logs/20261109-134539/: 30/30 programs pass (all layers; 2:4 on the 2:4
  model, 4:8 on the 4:8 model, dense-only builds on the 2:4 model), every run "verified" (hash + 8 sampled rows),
  no GEMMINI warnings. Wall time 13 s.
- Mutation check (edge_24_sparse on the fix-round mutant libs in ~/gemmini-fixwork/spike/lib): mutA_noidx24 ->
  MISMATCH, mutG_nowrite24 -> MISMATCH (poison seen), mutF_noclear24 -> pass (expected: nothing pending at reset).

## 3. RTL pilot (done, 13:46-13:59)
- runs/20261109-134644-pilot: edge_24_full on the 2:4 sim, seed 1: berkeley / dense_stream / sparse_stream all
  verified on RTL (incl. the partial last row tile). Wall 12.8 min (3 variants; each ~4 min, mostly the fixed
  overhead: warm-up, poison, 4 MiB L2 eviction). Sim RSS ~60 MB, so memory is not the limit (yosys of another
  agent uses ~1.6 GB).
- Found: rdma_bytes read 0. Cause (CounterFile.scala): a snapshot picks external-vs-internal by the snapshot
  command's own counter index (0), so snapshots return the wrong value for external counters. Fix in
  stream_bench.c: read the counters live after the fence (nothing is running then) instead of via a snapshot.
  Also added "sbench end cycle N" (read_cycles at exit) for the sim speed. Rebuilt all, Spike re-run: 30/30 pass
  (build/spike-logs/20261109-135956). The pilot folder stays as a record; its numbers are not used.

## 4. Phase 1: small layer timing (started 14:00:15)
- Main run folder: runs/20261109-140015. Jobs build/jobs-phase1.txt (copied into the run folder at the end):
  small on stock (_24_dense), nm24 (_24_full), nm48 (_48_full), seeds 1 and 2; edge seed 1 on all three chips.
  PAR=6, TIMEOUT 100M (small) / 50M (edge), inside systemd-inhibit --what=sleep:idle.

## 5. Phase 1 findings + program v2 (14:37-14:45)
- Phase 1 sim speed: stock small_24_dense finished in 2205 s with "sbench end cycle" 1,958,968, i.e. ~890 simulated
  cycles/s per sim with 6 sims + yosys running. The pilot (1 sim alone) did roughly 4x that per sim, so total
  throughput with 6 at once is only ~1.4x one sim (memory-bound host).
- Of those ~1.96M cycles only ~33k were timed: the overhead per variant (~0.95M cycles) was mostly the 4 MiB L2
  eviction, and for big layers the CPU poisoning + hashing of C (Spike instret: ~0.9M for the 393k-value hash of
  bert_ffn1) would have dominated.
- v2 of stream_bench.c (timed region unchanged, only untimed setup/check changed):
  - C poisoned by DMA (mvout of poisoned acc tiles) instead of CPU stores; poison_selftest() once at start checks
    that every value of C reads back as poison
  - hash = FNV-1a 64 in 4 interleaved lanes over uint64 words (gen_data.py updated to match; data regenerated:
    A/W/WC/META bytes unchanged, sha256s equal; only the hash constant changed)
  - L2 eviction buffer 4 MiB -> 2 MiB (survival per line ~1.4% under random replacement)
  - prints "<variant> overhead (untimed): poison / evict_l2 / check cycles"
  - new program <layer>_24_ds (run_mask 6: dense_stream + sparse_stream) for the 2:4 chip on the big layers
- v2 programs built into build/bin-v2 (BIN_DIR) so phase 1 (still copying from build/bin) is not disturbed.
  Spike: 36/36 v2 programs pass (build/spike-logs/v2-144154).
- run_rtl.sh: BIN_ROOT env, copies each program's ref.json into <run>/ref/ (collect.py now reads the reference from
  the run folder, so later regenerations cannot change a recorded run's check), copies the jobs file.
  (Replaced via mv so the running phase-1 bash keeps its old inode.) Phase-1 refs copied by hand into
  runs/20261109-140015/ref/ before the data was regenerated.
- Phase 1 stays a record of program v1 (small x2 seeds, edge). Small is re-run in phase 2 with v2 (3 seeds) so
  every number in the main table comes from one program version.

## 6. Estimate for the full set (v2)
Per variant ~ warm-up + poison (~0.02M) + eviction (~0.4M est.) + timed run + hash check (~4 cycles/value est.).
Timed run guess ~30 cycles per (preload, compute) pair from the small layer (berkeley 14.7k cycles / 512 pairs):
qkv ~0.55M, ffn1/ffn2 ~2.2M, rn50 ~0.9M. 5 variants per layer (stock: berkeley + dense; nm24: dense + sparse;
nm48: sparse) -> ~58M simulated cycles for the 4 big layers. At ~5k cycles/s total throughput: ~3-4 h; the
longest single job (stock ffn, 2 variants, ~9M cycles) ~2.5-3 h at ~900 cycles/s. Below the 10 h limit, so the
whole set runs (phase 2), big layers 1 seed, small 3 seeds. Timeouts: 60M (ffn), 30M (qkv, rn50), 15M (small, edge).
Jobs: build/jobs-phase2.txt (biggest first, edge first as an early check of v2 on RTL).

## 7. Phase 2 started 14:42:52 -> runs/20261109-144252 (BIN_ROOT=build/bin-v2)
- `BIN_ROOT=$PWD/build/bin-v2 PAR=6 systemd-inhibit --what=sleep:idle scripts/run_rtl.sh $PWD/runs/20261109-144252 build/jobs-phase2.txt`
- runs/20261109-144252/PAR starts at 1 (phase 1 still has 6 sims); raise to 6 when phase 1 ends.

## 8. Phase 1 complete (15:32), phase 2 progress
- Phase 1 (program v1) all 9 jobs ok, 24/24 rows verified: runs/20261109-140015/{results.csv,summary.md}
  (collect.py). Small: stock berkeley 14,755; stock dense_stream 18,609; nm24 sparse_stream 29,804; nm48
  sparse_stream 35,162 cycles; seeds 1 and 2 identical on every row. Berkeley on the 2:4 / 4:8 chips within 0.4%
  of stock. This is the v1 record; the paper table should use phase 2 (v2).
- rdma_bytes: with 64 B DMA requests it is exactly 4x the bytes (DMA.scala adds 1 << size per 16 B beat):
  small dense 196,608 = 4 x 48 KiB (A 16 KiB + W 32 KiB); sparse 131,072 = 4 x (16 + 16) KiB. Report /4.
- Phase 2 edge v2: stock, nm24, nm48 all ok and verified on RTL (DMA poison + 4-lane hash work on RTL).
  Measured v2 overhead per variant: evict_l2 ~339-353k cycles, check (edge) ~68k, poison ~5k.
- 15:34: PAR file of the first runner stayed at 4 (my waiter's pgrep matched itself). The runner only re-reads PAR
  when a job ends, so I started a second runner on the same run dir for the small + qkv jobs (reverse order):
  `PAR_FILE=PAR2 PAR=2 ... scripts/run_rtl.sh $PWD/runs/20261109-144252 build/jobs-phase2b.txt` (PAR=4 + PAR2=2
  = 6 sims). Jobs whose log exists are skipped, so the two runners share the queue.
- 15:47 revised timing: the one-time poison_selftest() (CPU writes + reads all of C) is ~45-60 min of wall time
  for bert_ffn1 (C = 393k values), and the per-variant hash of C will be of the same order. Not restarting (the
  program version must stay the same across layers). Expected: ffn1 jobs ~4-4.5 h from 15:02 (done ~19:30),
  nm48 ffn1/ffn2 and rn50 queue behind them on runner 1 (4 slots); small + qkv on runner 2 (2 slots).
  Projected end of the whole set ~20:00-21:00 (well under the 10 h limit).

## 9. 15:58 five queued phase-2 jobs moved to the server (coordinator: SERVER READY, validated)
- Moved (not yet started on the laptop): nm48 bert_ffn1_48_sparse, nm48 bert_ffn2_48_sparse, nm24 rn50_conv_24_ds,
  stock rn50_conv_24_dense, nm48 rn50_conv_48_sparse (seed 1; timeouts 60M / 60M / 30M / 30M / 30M as in
  jobs-phase2.txt). Laptop runners can't start them: placeholder logs created first in runs/20261109-144252/
  (run_rtl.sh skips jobs whose log exists); they get replaced by the server logs.
- Binaries copied to server ~/sbench/bin; sha256 identical to build/bin-v2 (checked on both sides).
- Server simulators (built there from the same sources, validated by the coordinator: fair benchmark identical to
  the laptop on 4 chips x 3 seeds) have their own sha256: stock 84c2264a..., nm24 97b5d3b2..., nm48 ddf8b694...
  (full values in ~/sbench/host.info, copied into the run folder at pull time).
- Same make invocation as run_rtl.sh (run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1, RANDOM_SEED, TIMEOUT_CYCLES),
  script ~/sbench/run.sh, started with nohup setsid; all 5 in parallel (server idle, 16 cores, 31 GiB).
  Done marker: ~/sbench/STATUS = ALL_DONE.

## 10. 18:17 status
- Done and verified on the laptop: edge x3, small x9 (3 seeds; every seed identical), qkv x3, ffn2 stock + nm24.
- Server: rn50 x3 and nm48 ffn2 done (logs still on the server); nm48 ffn1 running.
- Laptop still running: nm24 bert_ffn1_24_ds (sparse variant) and stock bert_ffn1_24_dense (dense variant).
  bert_ffn1 untimed overhead per variant: poison ~281k, evict ~376k, check ~3.6M cycles.
- Preview (collect.py, partial): qkv stock berkeley 316,791 / dense_stream 460,206 / nm24 sparse 651,640 /
  nm48 sparse 743,192; ffn2 stock berkeley 1,761,377 / dense_stream 1,763,352 / nm24 sparse 2,556,093.
- 18:50 server ALL_DONE (5 jobs, all "sbench passed", exit 0; wall 2236-10098 s). Logs copied over the
  placeholders in runs/20261109-144252/; server jobs.tsv, host.info (hostname, kernel, simulator sha256s), run.sh
  and sha256sums of the server's bin/ + logs/ in runs/20261109-144252/remote/. Copied log sha256 == server-side
  sha256; server program sha256 == build/bin-v2. collect.py fills host + sim_sha256 per row from run.info /
  remote/.

## 11. Done (18:55). All runs finished, nothing remains.
- runs/20261109-144252: 24 simulations (19 laptop, 5 server), 52 result rows, 52/52 verified (in-binary hash +
  8 sampled rows, host-side hash check against ref/, seed and config checked in each log). No correctness failure.
- results.csv + summary.md written by scripts/collect.py; SHA256SUMS rewritten after collect (66 files).
  Phase 1 folder re-collected (now has host/sim_sha256 columns) and its SHA256SUMS refreshed.
- run.info got a `remote=` line pointing at remote/.
- Files touched outside experiments/streaming/: only
  ~/chipyard/generators/gemmini/software/gemmini-rocc-tests/include/gemmini_nm.h (append-only: the
  tiled_matmul_nm() block before the final #endif; checked with diff against build/gemmini_nm.h.before-tiled_matmul_nm).
  On the server: ~/sbench/ (bin, logs, run.sh, jobs.tsv, host.info, STATUS). No git operations anywhere.
  Never rebuilt a simulator; never installed a Spike lib; never touched verification/runs, results/, logs/.
