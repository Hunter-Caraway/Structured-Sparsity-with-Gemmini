# Worklog: software speed-up of sparse (2:4, 4:8) on the Fix A chips (speedup agent)

Started 2026-11-12 ~10:50 EST. Goal: cut CPU instructions per tile and overlap better, so Fix A sparse beats Berkeley
stock dense. Sources owned: experiments/streaming/investigate/src/ and the streaming-tiler section of gemmini_nm.h.
Rules: new variants only (e.g. `sparse_fixa2`), Spike-verify 2:4 and 4:8, then server Fix A sims (at most 6 at once),
new runs in ~/sinv/runs/<timestamp>-speedup-srv. No git operations.

Laptop scratch: `/tmp/claude-1000/-home-hunter-gemmini-sparsity/02a1660a-afd8-4d63-b078-262a0414bff5/scratchpad/speedup/`
(below: `$S`).

## RESUME HERE (checkpoint 2026-11-12 11:15 EST, coordinator asked to stop)

### Done
- Read the Fix A spec, fix-a-sw, fix-a-review, fix-a-server, investigate, bench and server worklogs.
- Laptop build script `$S/cc.sh <24|48> <layer> <out> [flags]`. It uses the server's build_progs.sh flags and the
  server-generated headers (copied to `$S/hdr/{24,48}/include/gemmini_params.h`, sha256 434f86be... / 2731193e...,
  equal to build.info). Check: the laptop build of small_24_keeperfixa has the same .text sha256 (18506c0a...) as the
  server binary `investigate/runs/20261111-183018-fixa-srv/bin/small_24_keeperfixa-baremetal`. So laptop Spike
  counts apply to the server binaries.
- Instruction-trace analyser `$S/itrace.py <bin> <spike -l trace> [--lines]`. It counts the instructions of each timed
  run() region (start rdcycle to issued rdcycle), splits the RoCC commands by funct (funct 26 by rd), and groups
  instructions by source line (build with -g; -g does not change .text). Spike lib:
  `/home/hunter/gemmini-fixwork/fixa/lib/fixa24` (cmp-identical to the current libgemmini sources).
- Outputs: `$S/logs/{edge_24_k,small_24_kf,bert_qkv_24_kf}.itrace` (+ .out). All runs verified ("sbench passed").

### Nothing running, nothing changed
- No server simulation was started. No source file was changed (no `sparse_fixa2` yet). No variant is ready for the
  server. Only this worklog and the scratch files were written.

### Findings so far (2:4, Spike instruction counts; cycles from investigate/runs/20261111-183018-fixa-srv/nm24.*_keeperfixa.seed1.log)
Instructions per timed region:
| layer | Berkeley (LOOP_WS) | Fix A keeper | keeper RoCC cmds | real tiles / pairs | RTL cycles keeper | keeper instr/cycle |
|---|---|---|---|---|---|---|
| edge | (not traced) | 2,466 | 140 | 16 / 48 | 4,989 | 0.49 |
| small | 465 (11 cmds) | 7,740 | 632 | 64 / 256 | 15,500 | 0.50 |
| bert_qkv | 3,211 (125 cmds) | 287,899 | 21,992 | 1,152 / 9,216 | 401,522 | 0.72 |

Keeper bert_qkv by source line (tiled_matmul_nm_v2.h; `$S/logs/bert_qkv_24_kf.itrace`):
- GARBAGE pair loop (:186-188): 101,384 instructions for 8,064 pairs = 12.6 per pair.
  The loop loads pre2/cmp1/cmp2[i] from stack arrays. Lean target: about 6 per pair (3 adds, 2 RoCC, 1 branch).
- Real-tile part (:159-184): about 38k for 1,152 tiles = about 33 per tile. Two checks cost about 3.5-3.75
  instructions per tile each: `spadidx && h == 0 && u == 0` (:164) and the `% NM_META_FIFO_DEPTH` batch-end test
  (:180).
- mvins (:109-132, struct array ld[] + NMV2_ISSUE_LD): about 80k for 2,880 mvins = about 28 per mvin. Lean target:
  about 5.
- Per-step setup (:142-153): about 30k / 144 steps = about 200 per step.
- mvouts (:201-203): about 8k / 384 = about 20 per mvout.
- Small shows the same shape: 13.4 per GARBAGE pair, about 30 per real tile, about 23 per mvin, about 9 per mvout.
- RoCC mix qkv: PRELOAD 9,216, COMPUTE 9,216, MVIN 2,304 (A, 2-tile BANKSPLIT), MVIN2 288 (W), MVIN3 288 (index),
  LOAD (26/rd2) 288, MVOUT 384, CONFIG 7, CLEAR 1.

Interpretation (not yet measured on RTL):
1. Cycles are about 2x instructions on edge and small, and 1.4x on qkv. So the gap is RoCC back-pressure as well as
   instruction count. Each step issues 20 mvins in one burst (qkv: 16 A + 2 W + 2 index). The RS ld queue has 8
   entries (Configs.scala:56; ex 16, st 4). The CPU therefore blocks on mvin 9 while the ex queue (at most 8 pairs,
   about 128 array cycles) drains. investigate.md section 7 saw the same: about 500-600 cycles blocked per load
   group. Fix idea: interleave the next step's mvins into the pair stream (about 1 mvin per 3 pairs on qkv), so the
   ld queue never fills. Issue them directly, with incremental rs1/rs2 and no ld[] struct array.
2. DMA efficiency. BANKSPLIT A mvins move 32 B rows (2 tiles), so each DMA request is 32 B instead of 64 B.
   max_in_flight_mem_reqs = 16 (Configs.scala:66), so a latency-bound DMA gets about half the bandwidth.
   rdma_bytes counts 2x the bytes for 32 B requests and 4x for 64 B (DMA.scala adds 1<<size per beat). Keeper qkv
   DRAM traffic is about 1.5 MB: A 96 KB is read JB = 12 times (TI=8, TJ=4), plus W 288 KB and index 72 KB.
   Berkeley moves about 1.06 MB (rdma_bytes 4,251,648 / 4, runs/20261109-144252/stock.bert_qkv_24_dense.seed1.log).
   Options:
   - 4-tile A mvins with block_mvin_stride = BANK_ROWS. Each mvin gets 64 B requests, but a step's A then fills all
     4 banks, and the DMA writes would collide with A reads.
   - A different block shape. With TI=4, TJ=8 the traffic would be 6x96 + 2x288 = 1,152 KB, against
     12x96 + 288 = 1,440 KB now. The cost is twice as many real preloads and index tiles.
   These need an RTL measurement.
3. Hardware lower bound for qkv sparse: ex_active about 158k (sparse_fixa log). Berkeley's array is 92% busy
   (ex_active 291,727 of 316,791). There is headroom if the feed keeps up.

### Next steps (in order)
1. Add `sparse_fixa2` (new RUN bit 256 in investigate/src/stream_bench.c; new opts bit in tiled_matmul_nm_v2.h, or a
   new function; leave the keeper paths byte-identical). Make these changes:
   - (a) GARBAGE pair loop with incremental registers instead of the stack arrays. Keep the last partial row tile
     separate.
   - (b) mvins issued directly with incremental rs1/rs2 (no ld[] array), interleaved into step g's pair stream at a
     fixed rate. Issue all of them before the step's last preload (rule P5: never between a preload and its compute).
   - (c) The index LOAD at a fixed tile position, with no `%` test. Move the h==0 check out of the loop.
   - (d) Move M3: put each step's first index batch in the bank that step g-1 does not read.
   Check every change with `$S/itrace.py` (instructions per pair, per mvin).
2. Spike: edge/small/bert_qkv x 2:4/4:8 must all be verified. Also confirm that the old variants' totals are
   unchanged.
3. Server: build with ~/fixa/build_progs.sh-style flags into a new dir. Run edge and small (RUN_MASK with only the
   new bit + sparse_fixa, to keep the per-variant ~0.45M-cycle overhead low) in ~/sinv/runs/<ts>-speedup-srv, with
   at most 6 sims. Then run bert_qkv seed 1 for the best variant.
4. If the result is still DMA-bound, try 4-tile A mvins (64 B requests) and TI=4/TJ=8 on qkv.
