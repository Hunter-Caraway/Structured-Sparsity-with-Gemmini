# Worklog: why sparse_stream gets no speed-up (investigate agent)

Started 2026-11-09 19:00. All work in experiments/streaming/investigate/ (copies of src/ and scripts/, plus new
files). Nothing in src/, gen/, scripts/, runs/, analysis/, deliverables/, tools/ or gemmini_nm.h was changed.
No simulator rebuilds, no git operations.

## 1. Reading the code (19:00-19:05)
- Sparse compute reads a_lo through the A port and a_hi through the B port (`b_address_rs2 + b_fire_counter`,
  ExecuteController.scala:307). The tiler puts both in the same A buffer: `a_lo = a_sp + 2c*DIM`,
  `a_hi = a_lo + DIM` (gemmini_nm.h:384-394), i.e. the SAME scratchpad bank.
- Same-bank operands: ExecuteController.scala:395-412 (`must_wait_for`): B (priority 1) waits while A (priority 0)
  reads the same bank with the same counter, and A may not run more than one row ahead of B (`one_ahead`). So
  A and B alternate: 2 cycles per row, 32 cycles per sparse compute instead of 16. That cancels the halving of
  the compute count, which matches ex_active(sparse) ~ ex_active(dense) in every layer.
- fair_perf.c:49 puts even K tiles in bank 0 and odd K tiles in bank 1 (a_lo / a_hi in different banks): that
  is why the old fair benchmark saw 1.88x in array time and the streaming one sees none.
- Spad banks are single-ported (Configs.scala:47 sp_singleported = true) and DMA writes win over EX reads
  (Scratchpad.scala:119-120, 175): an mvin into a bank the array is reading steals a cycle per row.
- `rs_full` is NOT "reservation station full": it is `!io.alloc.ready` (ReservationStation.scala:611) and
  alloc.ready defaults to false and is only raised when a command is being allocated (ReservationStation.scala:188,
  401). So it counts every cycle with no allocation, idle cycles included (Berkeley's own row: 13,951 of 14,840).
  It says nothing about the RS being full.

## 2. Tools built (19:03-19:12)
- investigate/src/micro.c: EX-unit microbenchmark, operands already in the spad (no DRAM). 512 computes per case,
  TI=1 (fresh weights each compute) and TI=8 (weight reuse): dense, sparse a_lo/a_hi same bank (as tiled_matmul_nm),
  sparse different banks (as fair_perf), sparse with cold index tiles (L2 evicted), and batches of 4.
  Spike: runs clean on 2:4 and 4:8 (build/spike-logs/micro_*.log). RTL: runs/20261109-190319-micro (laptop).
- investigate/src/nm_stream_v2.h: copy of the tiler with option bits: V2_BANKSPLIT (sparse: a_lo / a_hi in
  different banks via 2-tile mvins with block_mvin_stride = BANK_ROWS), V2_INTERLEAVE (both: next step's mvins
  spread over this step's compute stream), V2_META_EARLY (sparse: index tiles in a sliding window of 4 instead of
  batches of 4). investigate/src/stream_bench.c: copy of the benchmark + variants dense_v2 / sparse_v2
  (-DV2_OPTS, run_mask bits 8/16) and a "null window" counter check (ctr_start, two read_cycles, ctr_stop).
- Spike: small (2:4 opts 0,1,2,3,4,7; 4:8 opts 0,3,7), edge (opts 3,7, both patterns) and bert_qkv (2:4 opts 3,7,
  dense opts 2; 4:8 opts 3,7): every run verified (hash + 8 sampled rows), sbench passed.
- Runs started: laptop runs/20261109-190917-small (nm24 small o0/o1/o3/o7); server ~/sinv/runs/20261109-190940-small-srv
  (small o2/o4 nm24, o2dense stock, 48 o0/o3/o7, edge 24/48 o7) and ~/sinv/runs/20261109-191044-qkv-srv.
  Binaries copied to the server, sha256 identical.

## 3. Micro results (runs/20261109-190319-micro, measured pass, 512 computes, operands in the spad)
| case | nm24 TI=1 cyc/compute (ex_active) | nm48 TI=1 | stock TI=1 | stock TI=8 |
|---|---|---|---|---|
| dense | 34.2 (15,360) | 34.2 (15,360) | 34.2 (15,360) | 20.9 (9,603) |
| sp_same (a_lo, a_hi same bank) | 71.3 (23,552) | 84.5 (23,552) | - | - |
| sp_diff (different banks) | 62.2 (15,360) | 85.2 (15,360) | - | - |
| sp_diff_cold (index tiles from DRAM) | 104.8 | 185.7 | - | - |
- Same bank costs the array 23,552 vs 15,360 ex cycles at TI=1 and (warm-up pass, nm24 TI=8) 15,890 vs 9,984:
  1.6x. With different banks a sparse compute (32 K values) takes the same ex time as a dense one (16 K values).
- Cold index tiles: +42.6 cycles per tile (2:4, one 64 B line) and +100 per tile (4:8, two lines): ~50 cycles per
  L1+L2 miss, fully exposed. The generated core uses the blocking `DCache` (not NonBlockingDCache), so each miss
  stalls the Rocket pipeline; software prefetch cannot hide it.
- Warm index commands: (85.2 - 62.2) x 512 / (512 x 4 extra cmds) = ~6 cycles per meta cmd.
- At TI=1 even warm sparse is CPU-issue-bound (issue ~= total, ex_active only half of total).

## 4. Small layer, v2 options (runs/20261109-190917-small, nm24, seed 1) - first RTL result of the tiler changes
| program (opts) | variant | total | ex_active |
|---|---|---|---|
| o0 | dense_stream (v1) | 18,538 | 8,619 |
| o0 | sparse_stream (v1) | 29,869 | 8,836 |
| o0 | dense_v2 (no options = same schedule as v1) | 21,735 | 10,056 |
| o1 BANKSPLIT | sparse_v2 | 35,587 | 5,469 |
| o3 BANKSPLIT+INTERLEAVE | dense_v2 / sparse_v2 | 26,114 / 38,515 | 10,821 / 5,608 |
| o7 +META_EARLY | dense_v2 / sparse_v2 | 26,114 / 49,148 | 10,821 / 5,492 |
- BANKSPLIT works on RTL inside the tiler: sparse ex_active 8,836 -> 5,469 (-38%), but total gets WORSE.
- dense_v2 with no options runs v1's exact schedule and is 17% slower than v1 only because v2's bookkeeping adds
  CPU instructions per command. So the whole streaming tiler is bound by the CPU issuing commands, not by
  Gemmini. Every option that adds CPU work loses. -> v3: lean issue (precomputed rs1/rs2, adds only).
- Null window (ctr_start; read_cycles x2; ctr_stop): rs_full = 174 and 131 with a 1-cycle read_cycles delta.

## 5. EX ceiling with a tight feed (runs/20261109-192612-micro2: operands precomputed, 2 ld + 1 rocc per cmd, TI=8)
| case | nm24 cyc/compute (ex_active) | nm48 | stock |
|---|---|---|---|
| dense_tight | 16.15 (7,695) | 16.14 (7,695) | 16.14 (7,695) |
| sp_same_tight | 32.20 (15,887) | 32.25 (15,887) | - |
| sp_diff_tight (incl. warm index cmds) | 16.19 (7,695) | 16.56 (7,830) | - |
- Same-bank a_lo/a_hi = exactly 2x the cycles per compute. Different banks: a sparse compute (2x the K) costs the
  same 16 cycles as a dense one -> the array gives the full 2x per unit of work, on both patterns.
- The non-tight micro (~20 instr per pair) ran at 20.9 (dense) / 26.1 (sp_diff) cyc/compute: CPU-issue-bound.
  v1's inner loop is 16 instructions per (preload, compute) pair (static count of the disassembly), v3's is 11.

## 6. v3 = lean issue (v1 schedule, precomputed rs1/rs2), small layer
Runs: laptop runs/20261109-192907-v3small (nm24), server ~/sinv/runs/20261109-192907-v3-srv (stock dense, nm48).
| chip | variant (opts) | total | ex_active | vs v1 same chip |
|---|---|---|---|---|
| nm24 | dense_v3 (0) | 17,143 | 7,740 | v1 18,538 -> -7.5% |
| stock | dense_v3 (0) | 17,134 | 7,740 | v1 18,487 |
| nm24 | sparse_v3 BANKSPLIT (1) | 21,801 | 4,234 | v1 29,869 -> -27% |
| nm24 | sparse_v3 no options, same bank (0) | 21,332 | 8,229 | v1 29,869 -> -29% |
| nm24 | sparse_v3 BANKSPLIT+METAWARM (9) | 20,822 | 4,344 | METAWARM wins 4.5% on 2:4 too |
| nm48 | sparse_v3 BANKSPLIT (1) | 26,133 | 4,160 | v1 34,518 (main run) / 35,364 (o0 copy, server) |
| nm48 | sparse_v3 BANKSPLIT+METAWARM (9) | 23,866 | 4,275 | METAWARM wins 9% on 4:8 (2 lines/tile) |
- v2 options on the server (~/sinv/runs/20261109-190940-small-srv) all lose too, on both patterns (e.g. nm48 small
  sparse_v2 o3 43,503 / o7 53,686 vs v1 35,364). qkv v2 jobs were killed (KILLED.txt) and replaced by v3.

## 7. Timeline trace (v3 BANKSPLIT, nm24 small, -DV3_TRACE: rdcycle + live ex/rdma counters per step;
the trace itself costs ~10% (dense 19,417 traced vs 17,143))
- Each load group (12 mvins: A 4 or 8, W 8 or 4) blocks the CPU ~500-600 cycles: the ld queue has 8 entries
  (Configs.scala:56), so mvin #9 waits for the first mvin of the group to finish its DRAM round trip. During that
  time ex_active does not move (e.g. dense g=2: 6,411 -> 6,932, ex 1,935 -> 1,935): only ~8 pairs (~130 cycles)
  were queued in the RS before it.
- Compute-issue phases: dense 128 pairs in ~2,750-2,830 cycles with 1,833 ex cycles (21.5 cyc/pair vs 14.3 of
  work); sparse 64 pairs + 16 index tiles in ~4,000 cycles with ~1,020 ex cycles (~250 cycles per weight tile).
- RS dependency rules (ReservationStation.scala:326-373) checked by hand: no false RAW/WAR between step g's
  computes and step g+1's mvins in either layout.

## 8. CPU issue capacity (runs/20261109-194754-micro3: 1-row computes, so the array needs only ~4-7 cycles/pair)
| case (measured pass, 512 pairs, TI=8) | nm24 cyc/pair | nm48 cyc/pair |
|---|---|---|
| dense_rows1 (4 ld + 2 rocc per pair) | 8.14 | 8.25 |
| dense_rows1_alu8 (+8 addi per pair) | 15.48 | 15.49 |
| sp_diff_rows1 (+ warm index cmds, 4 or 8 per tile) | 12.44 | 14.47 |
| sp_diff_rows1_alu8 | 18.72 | 22.22 |
- +8 ALU instructions = +7.3 cycles per pair: the Rocket core issues ~1 instruction per cycle and RoCC commands
  themselves are cheap. To keep a 16-cycle compute fed, the CPU may spend at most ~14 instructions per
  (preload, compute) pair including the share of index commands, loop overhead, mvins and mvouts.
  v1's inner loop alone is 16 instructions per pair; v3's is 11.
- Warm index commands: (6,371 - 4,171) / 256 = 8.6 cycles each on 2:4, (7,411 - 4,225) / 512 = 6.2 on 4:8.

## 9. Counter window (coordinator question)
- ctr_start() = counter_reset() then counter_configure(i, ...) for i = 0..7, all before `start = read_cycles()`;
  ctr_stop() = counter_read(i) for i = 0..7, live, after `end = read_cycles()` (src/stream_bench.c:62, 66, 165-171).
- counter_reset clears the counter values (CounterFile.scala:168 withReset) but not the event configuration
  (counter_config, CounterFile.scala:164, outside the withReset). Counter i therefore counts from its own
  configure command to its own read: the timed region plus the remaining configure commands and rdcycle before
  `start`, plus the fence/rdcycle and reads 0..i-1 after `end`. Each counter access is a RoCC round trip.
- Measured (null window, nothing between the two read_cycles): rs_full = 174 and 131, loop_matmul_active = 8,
  ex/rdma/wdma/load/store = 0. So the window is ~130-175 cycles longer than the read_cycles region. Counters
  that only count while Gemmini works (ex, rdma, wdma, load, store) are unaffected, because Gemmini is idle in
  the extra cycles (after the fence). rs_full counts idle cycles, so it gains those ~130-175 cycles: on the edge
  sparse rows (8,310 total, few allocations) that gives rs_full 8,357 = 100.6% of total.
- Bigger point: rs_full is `!io.alloc.ready`, and alloc.ready is false whenever no command is being allocated
  (ReservationStation.scala:188, 401, 611). It counts "cycles with no RS allocation", idle cycles included, not
  "RS full". It cannot support "CPU blocked 97%". (A real RS-full measure would need RESERVATION_STATION_EX_COUNT
  / LD_COUNT occupancy, or cmd.valid && !cmd.ready at the RS input, which is not a counter today.)

## 10. v3 + HALFLOADS (16: half of step g+1's mvins before step g's computes, rest after half its weight rows)
Runs: laptop runs/20261109-194919-v3b-small. Small, seed 1, all verified.
| chip | variant (opts) | total | ex_active |
|---|---|---|---|
| nm24 | dense_v3 HALFLOADS (16 via o25) | 16,673 | 7,782 |
| stock | dense_v3 HALFLOADS (16) | 16,728 | 7,796 |
| nm24 | sparse_v3 SPLIT+HALF (17) | 23,512 | 4,455 |
| nm24 | sparse_v3 SPLIT+WARM+HALF (25) | 22,666 | 4,464 |
| nm48 | sparse_v3 SPLIT+WARM+HALF (25) | 25,753 | 4,243 |
- HALFLOADS: dense -2.7% (17,143 -> 16,673); sparse +8% on 2:4 (21,801 -> 23,512) and +8% on 4:8 with warm
  (23,866 -> 25,753). On small, a step's data takes about as long to arrive as its computes, so delaying half of
  it costs more than the ~500-cycle issue stall it removes (sparse has less compute per step to hide it).
- Best small so far: 2:4 sparse_v3 o1 21,801 = 0.68x Berkeley (14,840), 0.77x best dense_v3 (16,673 nm24);
  4:8 sparse_v3 o9 23,866 = 0.62x Berkeley (14,860 nm48 / 14,840 stock), 0.70x dense. v1 was 0.50x / 0.43x.
- Bound run started: PRETOUCH_META (index tiles read into L1 before the timed region, NOT a fair result) to size
  the CPU-side index cost: runs/20261109-200153-bound.

## 11. Index-cost bound (runs/20261109-200153-bound, PRETOUCH_META: all index lines read into L1 before the timed
region; NOT a fair result, only a bound on what removing CPU index misses buys)
- nm48 small sparse_v3 BANKSPLIT: 26,133 -> 22,341 with pre-touched index lines (-14.5%; 4:8 = 2 lines/tile).
- nm24 small sparse_v3 BANKSPLIT: 21,801 -> 20,104 (-7.8%; 2:4 = 1 line/tile). Even with free index loads 2:4 small
  sparse stays above dense_v3 (16,673).
- Option V3_META_EACH (32: each index tile right before its own preload instead of batches of 4)
  started on small/edge: runs/20261109-200634-v3c. Counter set 2 (rs_busy, ex control-queue block, spad A/B
  wait, load DMA wait) for berkeley/dense/sparse v1 and v3 on nm24 small: server ~/sinv/runs/20261109-200710-ctr-srv.

## 12. V3_META_EACH (each index tile right before its own preload) - loses everywhere
(runs/20261109-200634-v3c; edge HALFLOADS from server ~/sinv/runs/20261109-194919-v3b-srv)
| chip | layer | opts | total | ex_active | same without the option |
|---|---|---|---|---|---|
| nm24 | small | SPLIT+EACH (33) | 23,274 | 5,102 | 21,801 (o1) |
| nm48 | small | SPLIT+EACH (33) | 27,657 | 5,072 | 26,133 (o1) |
| nm48 | small | SPLIT+WARM+EACH (41) | 25,617 | 5,131 | 23,866 (o9) |
| nm24 | edge | SPLIT+EACH (33) | 7,450 | 786 | 6,719 (o9) |
| nm24 / nm48 | edge | SPLIT+WARM+HALF (25) | sparse 7,539 / 8,252; dense 5,301 / 5,368 | | o9: 6,719 / 7,579; dense o0 4,719 / 4,902 |
- With one index tile at a time ex_active rises (4.2k -> 5.1k): preloads reach the EX before their index tile
  (nm_meta_ok holds them, ExecuteController.scala:587-588 / 668). Batches of 4 stay.
- HALFLOADS also loses on edge (2 steps): keep it off for short layers.

## 13. Keeper, division-free index loop, runs in flight (20:00-20:25)
- Keeper: investigate/src/tiled_matmul_nm_v2.h = v3 with the losing options and trace hooks stripped.
  `tiled_matmul_nm_v2(NMV2_DEFAULT, ...)`: sparse = BANKSPLIT (+ METAWARM when NM_M == 8); dense = plain lean issue.
  Spike: edge/small/rn50_conv, 2:4 and 4:8, all verified (6/6).
- Static disassembly of v3's index-send loop: per batch of 4 tiles it did divu/remu/mul to find tile (q, j); Rocket's
  divider is iterative (tens of cycles). Replaced with an incremental (bq, bj) walk in both nm_stream_v2.h (v3) and
  the keeper; v_sparse_v3 now has 0 divu/remu. Spike: small 2:4 o1, small 4:8 o9, edge 2:4 keeper, rn50 4:8 keeper
  all verified. Timing: server ~/sinv/runs/20261109-202138-nodiv-srv (small o1 nm24, o9 nm48).
- In flight: laptop runs/20261109-201341-big (rn50_conv / bert_ffn2: v3o1 nm24, v3o9 nm48, v3dense stock);
  server qkv3 / v3b qkv / ctr2 / keeper (see section 11).

## 14. Proposed RTL change (not made; no RTL edits or rebuilds in this task)
Problem the software cannot remove: in sparse mode every command comes from the CPU (LOOP_WS is illegal,
Controller.scala:272-284), and each index tile costs the CPU 4 (2:4) or 8 (4:8) NM_META RoCC commands
(Controller.scala:499, 528-540) plus loads of the packed words through the blocking L1 (cold: +42.6 cycles/tile
2:4, +100 cycles/tile 4:8, micro sp_diff_cold). The array needs 16 cycles per sparse pair; the CPU issues ~1
instruction/cycle and spends ~11 instructions per pair plus ~3 per index command.
Change, in two steps:
1. Index tiles by DMA. Add a load-path variant (e.g. a config_ld id / mvin flag) whose destination is nm_meta_q
   instead of a spad row: the load controller's DMA response rows go to ex_controller.io.nm_meta_in (today driven
   only from the RoCC path at Controller.scala:372-374, 537-538) or straight into the tile assembler at
   ExecuteController.scala:200-239. Ordering stays as today: preloads wait on nm_meta_ok (ExecuteController.scala:588),
   pops at 712 / 731, row use at 881. Needs an RS dependency so a preload is not issued before its index mvin
   completes, or keep the FIFO-occupancy wait (nm_meta_ok) as the only sync, which already exists.
   Expected gain: removes the CPU index work. Bound from PRETOUCH_META (index loads free, commands still paid):
   -7.8% (2:4) / -14.5% (4:8) on small; the commands themselves add ~34 (2:4) / ~50 (4:8) cycles per tile
   (micro3 warm: 8.6 / 6.2 cycles per command), ~2.2k / 3.2k cycles of small's 64 tiles. Together roughly
   20,104 - 2.2k = ~17.9k (2:4) and 22,341 - 3.2k = ~19.1k (4:8) on small, i.e. ~0.83x / ~0.78x Berkeley
   (from 0.68x / 0.62x). An estimate, not measured. Still CPU bound for the computes.
2. Allow LOOP_WS in sparse mode. Drop the assert at Controller.scala:281-282 and teach LoopMatmul (the unroller
   instantiated at Controller.scala:262) to (a) place a_hi in the other bank (the BANKSPLIT layout) and pass it as
   the compute's B operand, and (b) emit the index mvin of step 1 before each weight tile's preload. Then sparse
   gets Berkeley's issue rate; the EX tight-feed result (16.2 cycles per sparse pair vs 16.15 dense, micro2) says
   the array then delivers ~2x per unit of K-work, so up to ~2x vs Berkeley on compute-bound layers, less where
   DMA bound (sparse A traffic is unchanged, weights halve).

## 15. Correction to sections 6 and 10 (20:35)
- The 23,914 in section 6 ("o9, METAWARM loses on 2:4") was the TRACED o1 run (small_24_v3o1tr, trace costs ~10%).
  The real nm24 small o9 is 20,822 (runs/20261109-192907-v3small/nm24.small_24_v3o9.seed1.log): METAWARM helps 2:4
  as well (-4.5% vs o1 21,801). Best 2:4 small is o9 20,822, not o1.
- v3 with no options (same bank) gives sparse 21,332 (ex_active 8,229), slightly better than BANKSPLIT o1 21,801
  (ex_active 4,234). On small the lean issue (v1 -> v3) is the whole gain; BANKSPLIT halves EX busy time but does
  not shorten the run, because the run is CPU-issue bound. The bank conflict is real (micro2: 32.2 vs 16.2
  cycles/compute) but it is not what limits the layer today.
- Machines: nm24 v3 results are laptop sims (built 2026-11-03), nm48 v3 and stock v3dense results are server sims
  (built 2026-11-09, different sha256; the Gemmini Scala sources are byte-identical on both). Cross-check of the
  laptop o0 / o9 binaries on the server nm24 sim: ~/sinv/runs/20261109-203920-xcheck-srv.
- Keeper on the server (~/sinv/runs/20261109-201457-keeper-srv): nm24 dense 18,770 / sparse (o1 schedule) 23,596;
  nm48 dense 18,443. The keeper's inner loops are instruction-identical to v3 (11 instructions per pair, checked
  in the disassembly); the gap to the laptop v3 numbers is being checked with the cross-check above.

## 16. Divisions and inlining (20:20-20:50)
- Index loop without divu/remu (incremental tile walk), server sim, same binary otherwise:
  nm48 small o9 23,866 -> 21,749 (-8.9%), ~/sinv/runs/20261109-202138-nodiv-srv. nm24 small o1 -> 20,165
  (server; the laptop o1 was 21,801, the cross-machine check is in 20261109-203920-xcheck-srv).
  The first attempt of that run dir failed at make (jobs file held a literal $HOME); kept as failed-relpath-*.
- Keeper slowdown explained: Spike instruction trace (spike -l) of the sparse call, nm48 small:
  v3 o9 build 12,430 instructions (636 c.ldsp, 192 c.sdsp, 354 div/rem); keeper 14,212 (906 c.ldsp, 312 c.sdsp).
  The keeper was compiled as a separate constprop function and GCC spilled the issue loops' registers. The nodiv
  v3 build lost its inlining the same way (14,236 instructions). Fix: keeper wrappers are always_inline.
- Remaining divisions were per mvout (e / stj, e % tj: 96 per call on small). Replaced by stepped (i, j) in v3 and
  the keeper (dense and sparse alike). keeper3 sparse call: 12,860 instructions, 66 div/rem (was 354).
  Spike: edge/small/rn50_conv x 2:4/4:8 12/12 verified. Keeper default now BANKSPLIT + METAWARM on both patterns.
  Verilator: server ~/sinv/runs/20261109-204637-keeper3-srv (small), 20261109-204734-keeper3qkv-srv (qkv).
- bert_qkv v3 (server, ~/sinv/runs/20261109-194522-qkv3-srv), all verified:
  | chip | variant | total | ex_active | main-run v1 |
  |---|---|---|---|---|
  | nm24 | dense_v3 | 428,190 | 279,313 | dense_stream 459,492 |
  | stock | dense_v3 | 430,212 | 278,927 | dense_stream 460,206, berkeley 316,791 |
  | nm24 | sparse_v3 o1 | 495,134 | 143,171 | sparse_stream 651,640 |
  | nm48 | sparse_v3 o1 | 575,617 | 142,690 | sparse_stream 743,192 |
  | nm48 | sparse_v3 o9 | 518,689 | 143,247 | |
  Sparse qkv is still slower than dense_v3 (0.86x on 2:4) with the EX half as busy: CPU-issue bound.
- Cross-check (~/sinv/runs/20261109-203920-xcheck-srv): the laptop binaries small_24_v3o0 / small_24_v3o9 on the
  server nm24 sim give dense_v3 17,143 and sparse_v3 20,822, identical to the laptop. The two machines' sims are
  cycle-identical, so laptop and server numbers compare directly. Hence nodiv nm24 small o1: 21,801 -> 20,165 (-7.5%).

## 17. Counter set 2 (server ~/sinv/runs/20261109-200710-ctr-srv, nm24 small, CTRSET2 build, all verified)
| variant | total | ex_active | rs_busy (RS holds >= 1 command) | spA_wait | spB_wait |
|---|---|---|---|---|---|
| berkeley | 14,723 | 9,282 | 13,531 (92%) | 4,954 | 0 |
| dense_stream (v1) | 18,500 | 8,622 | 16,259 (88%) | 9,413 | 0 |
| sparse_stream (v1) | 29,696 | 8,842 | 18,580 (63%) | 0 | 20,617 |
| dense_v3 | 18,368 | 7,755 | 15,342 (84%) | 10,252 | 0 |
| sparse_v3 o1 | 23,305 | 4,365 | 13,536 (58%) | 18,812 | 18,027 |
ex_ctlq_block and load_dma_wait are 0 everywhere. The RS is EMPTY for 37% (v1) / 42% (v3) of the sparse run:
Gemmini sits idle waiting for the CPU to send commands. This is the direct counter evidence for CPU-issue
bound, and it is the opposite of the "CPU blocked 97% on a full RS" reading of rs_full.
v1 sparse spB_wait 20,617 is the same-bank a_lo/a_hi conflict (B port waits on the A read); it goes to the
A/B-symmetric pattern with BANKSPLIT. (Totals differ slightly from other builds: different code layout.)

## 18. Status at hand-back (~21:30)
- qkv nm24 o9 (server qkv3): dense_v3 428,190, sparse_v3 476,320 (v1 651,640; Berkeley 316,791). qkv nm48 o25 599,203 (loses).
- rn50_conv (laptop runs/20261109-201341-big): nm24 dense_v3 734,474 (sparse o1 of that run still running);
  stock dense_v3 735,939 (Berkeley 661,605); nm48 sparse_v3 o9 1,004,823 (v1 4:8 sparse 1,346,269, -25%).
  CORRECTION: the hand-back report labelled 1,004,823 as 2:4 o1; it is 4:8 o9.
- keeper3 small (server 20261109-204637-keeper3-srv): dense nm24 17,900 / nm48 18,288 (v3 build 17,143; Spike shows
  about the same instruction count, so this is a layout/timing effect). Sparse results, keeper3 qkv, and laptop
  ffn2 / rn50 nm48 were still running at hand-back and are not recorded here.
- Server runs are still only in ~/sinv/runs/ (not yet copied into investigate/runs/).
- After hand-back: rn50_conv nm48 o9 (runs/20261109-201341-big): sparse_v3     total    1004823  cpu_issue_done    1004312 | ex_active=234450 rdma_active=1 sbench passed (1 of 1 runs verified) 

## 19. Leftover runs collected (2026-11-11)
Collection only: no simulations, builds or source edits. Numbers are copied from the `<variant> total ... cpu_issue_done
... | ex_active=...` lines and the `sbench passed (k of k runs verified)` line of each log (same lines as earlier
sections and scripts/collect.py). Ratios are computed from those numbers. "xB" = Berkeley total / sparse total.
- Server runs copied into investigate/runs/ (server copies kept): 20261109-204637-keeper3-srv and
  20261109-204734-keeper3qkv-srv. Python tarfile stream over the existing ssh socket. `sha256sum -c SHA256SUMS`: all 7
  listed files OK in both folders. A sha256 of every file (8 per folder, including SHA256SUMS) is identical on the
  server and the laptop. No mismatches.
- Laptop runs/20261109-201341-big: all 6 jobs finished, exit 0 in jobs.tsv (wall 2555-5184 s). `sha256sum -c SHA256SUMS`
  all OK. Every log ends with `sbench passed` and `Verilog $finish`. No failed, truncated or timed-out log in the
  three folders.

keeper3 (server sims; cycle-identical to the laptop, section 16). The keeper3 binary prints its variants as
dense_v3 / sparse_v3. Each log reports `sbench passed (2 of 2 runs verified)`.
| layer | chip | dense total (ex_active) | sparse total (cpu_issue_done, ex_active) | earlier best sparse | xB |
|---|---|---|---|---|---|
| small | nm24 | 17,900 (7,740) | 17,957 (16,745, 4,628) | v3 o9 20,822: -13.8% | 0.83x (Berkeley 14,840) |
| small | nm48 | 18,288 (7,764) | 20,431 (19,295, 4,502) | nodiv o9 21,749: -6.1% | 0.73x (Berkeley 14,840) |
| bert_qkv | nm24 | 452,257 (278,727) | 452,740 (451,669, 152,268) | v3 o9 476,320: -5.0%; v1 651,640: -30.5% | 0.70x (Berkeley 316,791) |
| bert_qkv | nm48 | 452,088 (278,718) | 496,569 (495,511, 146,281) | v3 o9 518,689: -4.3%; v1 743,192: -33.2% | 0.64x (Berkeley 316,791) |
Logs: investigate/runs/20261109-204637-keeper3-srv/nm{24,48}.small_{24,48}_keeper3.seed1.log and
investigate/runs/20261109-204734-keeper3qkv-srv/nm{24,48}.bert_qkv_{24,48}_keeper3.seed1.log.
- keeper3 sparse now equals keeper3 dense on 2:4 (small 17,957 vs 17,900; qkv 452,740 vs 452,257). On 4:8 it is
  0.90x (small) / 0.91x (qkv) of keeper3 dense. It is still slower than Berkeley everywhere.
- keeper3 dense on qkv is slower than the v3 dense build: 452,257 vs 428,190 (+5.6%, nm24). On small it is also slower
  (17,900 vs 17,143, section 18). Part of the 2:4 parity is therefore a slower dense, not only a faster sparse.
- The sparse runs stay CPU-issue bound: cpu_issue_done is within ~1.2k cycles of total and ex_active is
  about 1/4 (small) to 1/3 (qkv) of total.
- Odd value: nm48 qkv first null window shows `read_cycles delta 49` (all other null windows in these runs show 1).
  The second null window in the same log shows 1. The timed results are not affected.

laptop runs/20261109-201341-big (finished after hand-back). All logs verified (`sbench passed`, 2 of 2 or 1 of 1).
| layer | chip / program | variant | total | cpu_issue_done | ex_active | v1 main run (runs/20261109-144252) | xB |
|---|---|---|---|---|---|---|---|
| bert_ffn2 | nm24 v3o1 | dense_v3 | 1,765,831 | 1,764,562 | 1,115,082 | dense_stream 1,763,972 | |
| bert_ffn2 | nm24 v3o1 | sparse_v3 | 2,160,204 | 2,159,158 | 593,345 | sparse_stream 2,556,093: -15.5% | 0.82x (Berkeley 1,761,377) |
| bert_ffn2 | nm48 v3o9 | sparse_v3 | 2,204,812 | 2,203,687 | 579,390 | sparse_stream 2,915,792: -24.4% | 0.80x |
| bert_ffn2 | stock v3dense | dense_v3 | 1,766,718 | 1,765,468 | 1,115,007 | dense_stream 1,763,352, berkeley 1,761,377 | |
| rn50_conv | nm24 v3o1 | dense_v3 | 734,474 | 734,017 | 451,959 | dense_stream 740,332 | |
| rn50_conv | nm24 v3o1 | sparse_v3 | 960,349 | 959,808 | 235,097 | sparse_stream 1,158,534: -17.1% | 0.69x (Berkeley 661,605) |
| rn50_conv | nm48 v3o9 | sparse_v3 | 1,004,823 | 1,004,312 | 234,450 | sparse_stream 1,346,269: -25.4% | 0.66x |
| rn50_conv | stock v3dense | dense_v3 | 735,939 | 735,400 | 452,022 | dense_stream 741,495, berkeley 661,605 | |
Logs: investigate/runs/20261109-201341-big/{nm24.bert_ffn2_24_v3o1, nm48.bert_ffn2_48_v3o9, stock.bert_ffn2_24_v3dense,
nm24.rn50_conv_24_v3o1, nm48.rn50_conv_48_v3o9, stock.rn50_conv_24_v3dense}.seed1.log. The v1 and Berkeley numbers come
from the same lines in runs/20261109-144252/{nm24,nm48,stock}.{bert_ffn2,rn50_conv}_*.seed1.log.
- These runs use the v3 build (o1 / o9), not keeper3. v3 sparse beats v1 sparse on both layers. It still loses
  to Berkeley (0.66x-0.82x) and to dense_v3 (nm24: ffn2 0.82x, rn50 0.76x of dense_v3 speed).
- ex_active of sparse_v3 is about half of dense_v3 (ffn2 593,345 vs 1,115,082; rn50 235,097 vs 451,959). Total stays
  close to cpu_issue_done. Same CPU-issue-bound picture as small and qkv.

## 20. Fix A results
Server run `investigate/runs/20261111-183018-fixa-srv` (Fix A RTL, rebuilt 2:4 and 4:8 sims, seeds 1-3). Full
details, checks, fair_perf table and anomalies: fix-a-server.md "## Results (2026-11-12)". 98/98 jobs as
expected: 12/12 tests pass, 44/44 NEG builds hit their designed assert, every streaming and fair_perf output verified.
Seeds 1-3 give identical cycles. Keeper tiler, cycles (`<variant> total`). Berkeley = stock chip, runs/20261109-144252.
| layer | pattern | dense_v3 (same chip) | push sparse_v3 | Fix A sparse_fixa | Berkeley | Fix A vs push | Fix A vs Berkeley |
|---|---|---|---|---|---|---|---|
| edge | 2:4 | 4,931 | 5,979 | 4,989 | 4,304 | 1.20x | 0.86x |
| edge | 4:8 | 5,098 | 6,684 | 5,051 | 4,304 | 1.32x | 0.85x |
| small | 2:4 | 17,920 | 18,015 | 15,500 | 14,840 | 1.16x | 0.96x |
| small | 4:8 | 17,884 | 20,576 | 15,637 | 14,840 | 1.32x | 0.95x |
| bert_qkv | 2:4 | 451,373 | 454,535 | 401,522 | 316,791 | 1.13x | 0.79x |
| bert_qkv | 4:8 | 451,414 | 498,115 | 408,056 | 316,791 | 1.22x | 0.78x |
- v1 tiler: Fix A vs push sparse_stream 1.42-1.70x, but Fix A is still 0.68-0.77x of Berkeley.
- With the keeper tiler, Fix A beats dense on the same chip on small and qkv (1.11-1.16x). It is still slower than
  Berkeley stock on every layer.
