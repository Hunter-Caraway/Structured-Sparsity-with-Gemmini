# fixb-icount: why sparse_loop Spike counts are below Berkeley's dense loop (2026-11-13)

Scope: investigation only, laptop Spike in scratch (`.../scratchpad/icount/seg.py`, `gap.py`; binaries and libs from
`.../scratchpad/fixb-tests/sbench/bert_qkv/bert_qkv_24_loop-baremetal`, `.../fixb-spike/libgemmini-nm24`). Nothing written to repos except this file.
RUN3 = investigate/runs/20261112-235246-fixb-spike-tests; Q3 = investigate/runs/20261112-205136-q3-spike.

## Findings
1. Same region and method. RUN3 numbers are stream_bench.c `run()` (src/stream_bench.c:214-224): rdcycle before v() .. rdcycle after
   gemmini_fence(); Spike CPI 1 so cycles = instructions. Berkeley is the same variant (v_berkeley, :147) -> 3,214 in RUN3
   bench/bert_qkv_24_loop.log, vs Q3 rt 3,209 (q3 log:4) + 3 fence + 2 = same code. Trace (spike -l, my own, bert_qkv 2:4) between the rdcycle
   pairs: Berkeley 3,211 instr, 20 LOOP_WS (funct7 8), RoCC {0:5, 8-13:20 each}; sparse_loop 1,448 instr, 16 LOOP_WS, RoCC {0:6, 8-13:16, 26:1, 28:16}.
   Both include their own tile-size search, config_*, call loop, fence. No CPU work is moved out of the timed region for sparse
   except the one-time compression and index reordering (prep_meta_loop, untimed, as for Fix A). Index mvins (funct 27) are
   issued by the hardware loop, so they are not CPU instructions at all: the instruction count is blind to them (they matter in HW cycles).
2. Two causes:
   a. Fewer calls. Berkeley 20 (2 I blocks x 10 J blocks x 1 K block, gap pattern in trace); sparse 16 = I0 2 x J0 8 x K0 1 with tile 5x6x48
      (RUN3 bench log "sparse_loop tiles"). Berkeley's tile_J is probably 5 [E, inferred from 20 = 2x10x1; its A+B rows at tile_K 48 leave no room for 6];
      sparse B is K/2 tiles so tile_J 6 fits (gemmini_nm.h:586-606 nm_loop_fits / nm_loop_tiles). So the spec's "somewhat more calls" was wrong; K halving gives
      the same or fewer calls on qkv/ffn1, rn50/ffn2 differ (tile_K 58 etc., see bench logs).
   b. Much cheaper per call. Instructions between consecutive LOOP_WS (trace, qkv): Berkeley 148 (144 on the second i block), sparse 61 (one
      extra funct-28 command included). Berkeley goes through the generic tiled_matmul_outer (gemmini.h:716-856) with a function pointer to
      sp_tiled_matmul_ws and run-time act / transpose / bias / reuse / low_D / padding handling; tiled_matmul_nm_loop (gemmini_nm.h:672-729) is
      specialised (all those are constants, bias NULL) and inlined. Q3 const-only build (dims constants, call inlined) of Berkeley gives 1,991 for qkv
      (about 100 per call, Q3 worklog table), so most of Berkeley's per-call cost is run-time generality, not the dense algorithm.
      Berkeley rt total = 3,209 vs const-only 1,991 also shows the run-time tile-size search (tiled_matmul_auto, gemmini.h:1262-1330) costs ~1.2k instr.
   Rough split for qkv: 3,211 - 1,448 = 1,763: calls 20x148 = 2,960 vs 16x61 = 976 (rest is head/tail: Berkeley 105 + 39 around the calls and a long config prefix, sparse 302 + 49).
3. Not skipped work. All 12 `<layer>_{24,48}_loop` runs print "verified" for both berkeley and sparse_loop (RUN3/bench/*.log, whole-C hash == expected
   and 8/8 sampled rows; bench.summary: "sbench passed (2 of 2 runs verified)"). The trace shows all 16 calls (8 I x 48 J tiles, K = 48 tiles, B 24 tiles) so every output tile is computed.

## Spec 5.1
Needs a changelog correction: the "expect somewhat more calls and 1-2% more instructions per call" [E] is contradicted by RUN3 (fewer calls, ~0.4x instr per call,
totals 0.45x on qkv/rn50/ffn1/ffn2). Caveat to state: the instruction win is mostly code specialisation (and tile count), not sparsity; Spike counts are not Rocket cycles;
real HW cycles stay the deciding number.

## Bug suspicion
None. Counts consistent, outputs verified, call/command counts match the loop structure.

## RESUME HERE
Done: analysis above. Running: nothing. Next: spec agent adds the 5.1 changelog entry; optional: confirm Berkeley's tile_J by PRINT_TILE build or commit log of LOOP_WS_CONFIG_BOUNDS.
