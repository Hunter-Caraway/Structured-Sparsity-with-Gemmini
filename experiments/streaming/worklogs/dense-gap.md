# Worklog: why our dense runs are slower than Berkeley's stock Gemmini (dense-gap agent)

Started 2026-11-12 ~10:50 EST. This is an investigation only. No source file was edited. Nothing was built or
simulated, and no git operation was run.
Laptop scratch: /tmp/claude-1000/-home-hunter-gemmini-sparsity/02a1660a-afd8-4d63-b078-262a0414bff5/scratchpad/densegap/
- src-snap/: copy of investigate/src/* as of 11:00 (mtimes kept: stream_bench.c and tiled_matmul_nm_v2.h 2026-11-11 13:42,
  which is the version the Fix A run compiled). Another agent is editing investigate/src, so use this copy.
- keeper_qkv24.dis: objdump -d of investigate/runs/20261111-183018-fixa-srv/bin/bert_qkv_24_keeperfixa-baremetal.

## The gap (cycles, `<variant> total` lines)
| layer | ours dense_v3 nm24 / nm48 (Fix A chips) | Berkeley stock | gap nm24 |
|---|---|---|---|
| bert_qkv | 451,373 / 451,414 | 316,791 | +134,582 (+42%) |
| small | 17,920 / 17,884 | 14,840 | +3,080 |
| edge | 4,931 / 5,098 | 4,304 | +627 |
Ours: investigate/runs/20261111-183018-fixa-srv/nm{24,48}.<layer>_{24,48}_keeperfixa.seed1.log (seeds 1-3 identical).
Berkeley: runs/20261109-144252/stock.{bert_qkv,small,edge}_24_dense.seed1.log.

## 1. Findings so far (reading and log arithmetic only, no new runs)
### 1a. Measurement: same timed region (probably 0%)
- Both variants go through the same `run()` in investigate/src/stream_bench.c. It does the same warm-up on a corner of the
  layer, the same poison, the same 2 MiB L2 eviction and the same ctr_start / read_cycles / call / fence / read_cycles.
  Both write int32 C (Berkeley: full_C = true). Data placement is the same (l_A, l_W, c_out).
- Not yet checked: the warm-up corner leaves state behind (I-cache or branch predictors) that may help one variant more
  than the other. This is unlikely to matter at the 100k-cycle scale.

### 1b. Hardware: about 0% on the pre-Fix-A chips; Fix A chips not yet measured
- Berkeley's own binary on the pre-Fix-A sparse chips (runs/20261109-144252/*.seed1.log, `berkeley` line):
  small nm24 14,842 / nm48 14,860 vs stock 14,840; edge nm24 4,306 / nm48 4,373 vs stock 4,304.
- Our v3 tiler on stock vs the sparse chip, qkv: stock 430,212 vs nm24 428,190 (investigate.md section 16, server run
  ~/sinv/runs/20261109-194522-qkv3-srv). Small: stock 17,134 vs nm24 17,143 (section 6).
- So before Fix A, the sparse chip's dense path costs about 0 to 1.6%. Still open: the same check on the Fix A sims
  (next step N1).

### 1c. Software is the gap: the EX unit is idle in our runs
- qkv EX idle time (total - ex_active): ours 451,373 - 278,688 = 172,685 cycles. Berkeley 316,791 - 291,727 = 25,064.
  Our EX does the same work in fewer active cycles than Berkeley's. The whole gap is EX starvation.
- cpu_issue_done 450,021 = total - 1,352: the CPU is busy issuing for the whole run.
- Spike instruction count of the dense_v3 timed region (Spike CPI = 1): qkv 322,215
  (/home/hunter/gemmini-fixwork/fixa/logs/k_bert_qkv_24_fixa.log), small 8,919, edge 2,430
  (k_small_24_fixa.log, k_edge_24_fixa.log).
- qkv has 8 x 48 x 48 = 18,432 (preload, compute) pairs. The EX floor is 16 cycles per pair = 294,912 cycles.
  Our CPU executes 322,215 instructions (17.5 per pair), which is already above the EX floor at IPC 1. The measured IPC
  on RTL is 322,215 / 450,021 = 0.72. Berkeley's LOOP_WS issues only a few RoCC commands per tile, so the CPU never
  limits it.
- Inner pair loop (keeper_qkv24.dis 0x80002cc4-0x80002ce0): 11 instructions per pair, 3 of them loads (pre2[i], cmp1[i],
  cmp2[i] from the stack) and 2 RoCC instructions. 18,432 x 11 = 203k. The remaining ~119k instructions
  (~6.5 per pair) are not yet attributed. Next step N3.
- Load-queue stall (investigate.md section 7, small-layer trace): each step's 12 mvins are issued before the previous
  step's computes. The ld queue has 8 entries, so mvin #9 blocks the CPU for ~500-600 cycles while the EX drains
  (only ~8 pairs are queued). qkv has 144 steps (TI 8, TJ 4, KSTEP 4: 1 x 12 x 12).
  Estimate: 144 x ~400 = ~58k idle cycles. Not measured on qkv yet.
- Tiling (computed from gemmini.h tiled_matmul_auto:1257-1330, WS double-buffered rules, DIM 16, 4 x 4096 spad rows,
  1024 acc rows): Berkeley uses tile_I 5, tile_J 5, tile_K 48 (I0 = 2, J0 = 10, K0 = 1), one LOOP_WS per tile, and
  2 loops in flight in LoopMatmul.
  Ours: TI 8, TJ 4, K step 64, 144 steps, every command issued by the CPU.
  Ours reads 7,077,888 rdma_bytes (= 4 x 1.77 MB: A is re-read 12 times plus W once). Berkeley's counter reads
  4,251,648, but its request sizes differ, so do not compare the bytes directly.
  rdma_active is ours 153,692 vs Berkeley 212,334. DMA is not our limit.

### 1d. Keeper dense slower than v3 dense (+5.6% on qkv)
- keeper3 452,257 vs v3 428,190 (investigate.md section 19).
- Small: Spike shows about the same instruction count (section 18), so it is a layout or timing effect there. Not yet
  checked on qkv (next step N4).

## RESUME HERE (11:20 EST 2026-11-12)
Done: read all the worklogs and sources; findings 1a-1d above; disassembly of the keeper qkv binary.
Server: NOTHING is running and nothing was started. At ~11:00 the ssh probe over the socket hung for more than 10 min and
was killed. `ssh -O check` said "Master running", but no command returned. Check the server before any run.
No ~/sinv/runs/<ts>-densegap-srv folder exists yet.

Next steps (≤ 4 sims; run folder ~/sinv/runs/<ts>-densegap-srv with run.info / jobs.tsv / SHA256SUMS; copy back to
investigate/runs/):
- N1 (hardware split). Run Berkeley's exact binary on the Fix A sims nm24 and nm48: qkv, small, edge.
  Binaries: runs/20261109-144252/bin/<layer>_24_dense (stock run, run_mask = berkeley + dense_stream).
  For berkeley only, patch a scratch copy's .sdata `run_mask` word (RUN_MASK | 0x1000) to 0x1001. This leaves .text
  byte-identical. Symbol address: `objdump -t | grep run_mask`.
  Expected result if the hardware share is 0: within 0.5% of 316,791 / 14,840 / 4,304.
- N2. Run the keeperfixa qkv binary with run_mask patched to 0x1020 (dense_v3 only) on the stock sim.
  This is the hardware share for our tiler on Fix A vs stock, with identical .text.
- N3. Spike PC histogram of dense_v3 qkv. Patch run_mask to 0x1020, then run
  `spike -l --extlib=/home/hunter/gemmini-fixwork/fixa/lib/fixa24/libgemmini.so --extension=gemmini <bin>`
  and count PCs between the two rdcycles of run(). This attributes the 322k instructions: the pair loop, the per-(q,j)
  first pair, the mvin array build + NMV2_ISSUE_LD, and the mvouts.
- N4. The same histogram for the v3 build (nm_stream_v2.h, -DRUN_MASK=32, no USE_KEEPER) to find the keeper +5.6%.
- N5 (software split on RTL, scratch builds in ~/densegap/). Two variants:
  (a) the mvins of step g+1 spread one per (q,j) group, so the ld queue never fills;
  (b) the operands kept resident with no mvins, to measure the pure CPU issue bound.
  The difference to dense_v3 gives the ld-stall share. The rest of the gap is instruction count.
- Candidate fixes for the speed-up agent (unmeasured):
  - tiled_matmul_nm_v2.h nm_stream_v2k_impl: interleave next-step mvins into the compute loop.
  - Keep pre2/cmp1/cmp2 in registers: unroll the i loop for TI = 8 to drop 3 loads per pair.
  - For dense, call tiled_matmul_auto (LOOP_WS) directly.
