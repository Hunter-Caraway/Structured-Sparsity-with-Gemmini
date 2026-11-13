# fixb-rtl: RTL agent worklog for sparse-loop-fix (Fix B)

Spec: `fix-b-spec.md` (FROZEN 2026-11-12). Repo `~/chipyard/generators/gemmini`, branch `sparse-loop-fix`
(created by the coordinator from `sparse-nm` d12b0840). Files owned: GemminiISA, LoadController,
ReservationStation, Controller, LoopMatmul (.scala). No commits, no elaboration, no Verilator, no server.
No measured numbers in this file; all line numbers are of the tree at d12b0840 unless marked "new".

## Step 1 (2026-11-12): reading checks C1, C2, C6

### C1: does the loop LOAD's `from_matmul_fsm` survive? YES (no spec change)
- LoopMatmul.scala:990 sets `io.out.bits.from_matmul_fsm := true.B` for every unrolled command.
- Controller.scala:269 `Queue(loop_cmd)` keeps the whole GemminiCmd; :421 `reservation_station.io.alloc.bits :=
  unrolled_cmd.bits`; the rd == 2 branch (:542-547) only raises `alloc.valid`, it does not rebuild the command.
- ReservationStation.scala:202 `new_entry.cmd := io.alloc.bits`; funct 26 goes to the ex queue (:324-325).
- Completion: ExecuteController.scala:1230-1231 sends `ld.rob_id` on `nm_ld_completed`, Controller.scala:458 feeds it
  into the completion arbiter, ReservationStation.scala:516-521 clears the ex entry and drives
  `matmul_ex_completed := entries_ex(issue_id).bits.cmd.from_matmul_fsm`.
- So a loop-generated LOAD is counted up by `ex.io.cmd.fire` (LoopMatmul.scala:975) and down by
  `io.ex_completed`: `ex_utilization` balances (H4). ExecuteController needs no change.

### C2: `ldb_ahead` (LoopMatmul.scala:459) with the halved B iterator
- Line: `io.ldb_completed || io.ld_kb > k || (io.ld_ka === k && io.ld_j > j)`. The third term tests LdA's k where
  LdB's k is meant (Berkeley code, reported, not fixed; dense path left as is).
- In a sparse loop `k` of ex is k' (0..max_k/2-1), LdB's k is also k' (LdB gets max_k/2), but `ld_ka` counts A
  tiles (0..max_k-1), so the term would compare unrelated units. The gate matters for correctness, not only for
  overlap: the RS sees a RAW only if the mvin was allocated before the preload.
- Decision (inside the spec, gate only): the sparse branch uses its own gates,
  `ldb: ldb_completed || ld_kb > k' || (ld_kb === k' && ld_j > j)` and
  `lda: lda_completed || ld_ka > 2k'+1 || (ld_ka === 2k'+1 && ld_i > i)` (P3). Dense expression untouched.
- Second Berkeley quirk seen (reported, not fixed): LoopMatmul.scala:185 `Mux(max_row_iterator ===
  max_row_iterator-1.U, row_pad, 0.U)` is never true, so LdB always loads DIM rows. Harmless for sparse (pad_K == 0, N6).

### C6: funct 27 constants. CONFIRMED (no spec change)
- Scale: `mvin_scale_t` is the `multiplicand_t` of `mvin_scale_args` (GemminiConfigs.scala:140-143); default config
  uses `Float(8, 24)` with `identity = "1.0"` (Configs.scala:108-110). The header prints `MVIN_SCALE_IDENTITY 1.0`
  (GemminiConfigs.scala:435-439) and software converts with a float/uint32 union (gemmini.h:150-158), so the bit
  pattern is IEEE-754 single 1.0 = 0x3f800000. Berkeley's LoopConv hardcodes the same value (LoopConv.scala:87).
  The RTL derives the constant from `mvin_scale_args` at elaboration (Float(8,24) -> floatToRawIntBits; UInt/SInt ->
  integer identity; anything else is a `require` failure on NM builds).
- Block stride: only used when cols > DIM (ReservationStation.scala:304-305, LoadController.scala:106); LOAD_IDX has
  cols == DIM (N12) so one block; constant DIM satisfies `assert(block_stride >= rows)` (LoadController.scala:136).
- Pixel repeats: LoadController stores the count (1 = none, :148); the RS stores count minus one (:174, :433), so
  the RS constant is 0 and the LoadController constant is 1.
- Shrink false; DRAM row stride = DIM * inputType bytes = 16 B.

### Other findings from the read (none blocks the spec)
- F1. `LoopMatmul` takes plain Ints, not the config, so `nm_sparsity` is not visible there. Two new constructor
  parameters with dense defaults are needed (`nm_rows_per_tile` = R, 0 on dense; `nm_bank_rows` for N9).
- F2. Spec 2.5.6 puts N8 in LoopMatmul, 6.1 puts the a_stride tracking in Controller. Implemented in Controller on
  `raw_cmd` next to N1 (same program-order point, same message).
- F3. Spec 2.5.7 wants identical dense Verilog and also N11/N14 asserts on a dense build. The two asserts are the only
  dense additions (simulation-only statements, no hardware). To be confirmed by the coordinator.
- F4. Spec P6 names a new ex state `ldidx`. A fourth ChiselEnum value would change the dense state encoding
  elaboration, so the LOAD is emitted while the FSM sits in `pre` under an NM-only flag; program order is identical.
- F5. `LOOP_WS_CONFIG_SPAD_AB` (funct 24) and LOOP_WS rs1[19:16] can move `a_addr_start` / `b_addr_end` away from the
  half boundaries. The spec's bank argument assumes the defaults; with another base the Fix A bank assert catches it.

## Step 2 (2026-11-12): implementation (uncommitted, branch `sparse-loop-fix`; line numbers of the edited tree)
sbt `;project gemmini; compile` (chipyard launcher, conda java) after each file: `[success]`, last run 23:48:26, only
pre-existing warnings. Nothing elaborated, nothing simulated: every statement below about behaviour is by reading.

- GemminiISA.scala:42-43: `LOAD_IDX_CMD = 27`, `LOOP_WS_CONFIG_NM = 28`.
- LoadController.scala:72-90: `ld_idx` and the constants (stride DIM*inputType bytes, identity scale, no shrink, block
  stride DIM, pixel repeats 1) behind `ld_sel`, which returns the plain register on a dense build. Uses at
  :97, :123, :126-129, :132, :157 read the `ld_*` values. DRAM address 0 still loads zeros (`all_zeros`, no assert).
- ReservationStation.scala:200 `funct_is_ld_idx`; :279 dst range; :299-301 block stride DIM / pixel repeats 0;
  :327-328 load queue.
- LoopMatmul.scala:
  - :334-431 new `LoopMatmulLdIdxReq` / `LoopMatmulLdIdx` (g = DIM / R tiles per LOAD_IDX, registered tile / spad /
    DRAM counters, throttle `ldb_done || u <= u_b + g`, spacer bits of rs2 driven 0 for N12).
  - :434-448 `LoopMatmulExecuteReq` gains `nm`, `max_k_b` (Option fields, NM only).
  - :493 `ex_max_k`, :496 `b_addr_start`, :660 `next_k` use it.
  - :575-663 class `NmLoad` (NM only): sparse compute operands (a_lo = tile(i, 2k), a_hi = a_lo + DIM, rs2 rows =
    a_rows, cols = DIM), sparse gates (C2), LOAD budget rule of spec 1.5, LOAD command (funct 26, rd 2, rs1 = row,
    rs2 = n), `nm_first_load`, asserts I1-I3.
  - :666-670 `cmd_gate`, `pre_or_ld_cmd` in `io.cmd.valid` / `io.cmd.bits`; :684 `nm_load.foreach(_.update())`.
  - `LoopMatmulState` gains `nm`, `idx_dram_addr`, `ldidx_started`, `ldidx_completed`; `all_completed` waits for LdIdx.
  - :1185-1190 `Arbiter(6)` on NM: stC, ex, ldD, ldIdx, ldab, stC_spad. `ld_utilization` counts LdIdx.
  - :1213-1216 funct 28 is a loop config command on NM.
  - :1347-1378 config decode (funct 28 -> `idx_dram_addr`, LOOP_WS rs1[3] -> `nm`), asserts N7, N6, N9.
  - :1526-1588 request wiring: LdB / StC get max_k / 2, B ends at `b_addr_end - idx_rows`, index region above it,
    LdIdx request / completion / throttle inputs, `io.nm_first_load`.
  - `LoopMatmul` / `apply` take `nm_rows_per_tile`, `nm_bank_rows` (default 0) and return a 4th value.
- Controller.scala: :262-268 call; :271-279 flag queue beside `Queue(loop_cmd)`; :282-315 raw_cmd checks N1, N2, N5,
  N3, N4, N8 (replaces the old LOOP_WS / LOOP_CONV_WS assert); :600-617 N12, N13 (NM) and N11, N14 (dense);
  :654-658 N10 at the first LOAD of a sparse loop.

### Design notes
- Dense build: every new signal sits behind a Scala `if` / `Option`; modified Berkeley expressions reuse the same
  Scala object on dense (`ex_max_k` is `req.max_k`, `cmd_gate` is `ld_ahead`, `ld_stride` is `stride`, ...).
  Known dense additions: the two asserts N11 / N14 (F3), unused `ld_idx` / `funct_is_ld_idx` nodes (constant false,
  expected to be removed by firtool), and value names (`is_loop_config_cmd_ws`, `ws_completed`, `ex_max_k`,
  `cmd_gate`, `pre_or_ld_cmd`). To be checked by the Verilog diff on the server.
- N13 checks only the address field (rs2[31:log2(spad rows)] == 0); the end `addr + rows` is not range checked.
- N12 checks the full 16-bit rows and cols fields.
- N9 uses sizes only; the region base follows `b_addr_end` / rs1[17:16] as LdB does (F5).
- Assert order when several rules break: Controller on `raw_cmd` first (N1, N2, N5, N3, N4, N8 in that cycle), then
  LoopMatmul at LOOP_WS decode (N7, N6, N9), then N10 at the first LOAD dispatch. Spike reports N7/N6 before N8.
- LOAD_IDX from the CPU with DRAM address 0 loads zeros, no assert (same as Spike).
- Sparse LOOP_WS with B == NULL: LdB goes idle at once (Berkeley behaviour), so LdIdx is unthrottled; index rows are
  still loaded, LOADs still issued, the B and index regions are still reserved. Nothing special implemented.
- The A/B `WeightedArbiter` compares LdA's k (A tiles) with LdB's k (weight tiles, half scale) in a sparse loop, so
  B runs further ahead of A than ex needs. Untouched as the spec says; affects overlap only.
- pad_J on a sparse loop passes `b_cols < DIM` to a sparse preload; the per-tile software always sends DIM. Not
  checked against ExecuteController here; needs a pad_J test.
- Tagging: every added line carries `// changed: sparse-loop-fix, ...` (coordinator instruction), new blocks included.

## RESUME HERE (round 1, superseded by the section at the end)
Done: C1, C2, C6; all five files edited; sbt compile passes; asserts N1-N14, I1-I3 in place.
Running: nothing. No server use, no elaboration, no simulator touched, no git writes.
Not done: elaboration (first real check of Option bundle fields, the nested `NmLoad` class and the LoadController
scale match), any simulation, NEG / mutant runs, dense Verilog diff.
Next: coordinator decisions on F2, F3, F5 and the N13 range; elaborate both NM configs and the dense config on the
server (needs approval); run Spike-matched tests once the software agent has `nm_sparse_loop`.

## Step 3 (2026-11-13): round 2, spec changelog D1 and D4 (uncommitted, branch `sparse-loop-fix`)
Only `Controller.scala` edited. LoopMatmul.scala untouched: N13 lives in the Controller (dispatch of `unrolled_cmd`).
- D1: the dense `else` branch with the N11 / N14 asserts is removed (was Controller.scala:612-617). It had no helper
  wiring. N11 / N14 were never in the :282-315 block (that block holds N1-N5, N8 and sits inside
  `if (nm_sparsity.isDefined)`).
- D4: N13 at Controller.scala:610-612, one assert, same message. Condition:
  `rs2[31:log2Ceil(sp_rows)] == 0 && (rs2[31:0] +& rows) <= sp_rows`, with `sp_rows = sp_banks * sp_bank_entries`
  (:606) and `rows = rs2[63:48]` (all 16 bits). `+&` gives a 33-bit sum, so no wrap. Boundary: `addr + rows == sp_rows`
  is legal (last row written is `sp_rows - 1`); `addr + rows == sp_rows + 1` asserts.
- N12 and N13 are separate asserts in the same `when`; rows == 0 or rows > 16 trips N12, and N13 too if the sum passes
  the end.
- Dense build, by reading Controller.scala: the remaining sparse-loop-fix code is (a) :262-268 the LoopMatmul call
  (Scala Int arguments 0 / `sp_bank_entries`, 4th result is `None`: LoopMatmul.scala:1131, :1643), (b) :273-279
  `Option.map` on that `None`, (c) :282-313 inside the existing `if (nm_sparsity.isDefined)`, (d) :600-614 inside
  `if (nm_sparsity.isDefined)`, no `else`, (e) :652-655 `Option.foreach` on `None`. No statement is generated on a
  dense build. Not confirmed by elaboration (dense Verilog diff on the server is still open).
- sbt `;project gemmini; compile` (`.conda-env/bin/java -jar scripts/sbt-launch.jar`, run in `~/chipyard`):
  `[success] Total time: 7 s, completed Nov 13, 2026, 2:47:11 PM`, pre-existing warnings only.
  Log: `experiments/streaming/worklogs/fixb-rtl-r2-sbt.log`.

## RESUME HERE
Done: rounds 1 and 2. All five RTL files edited, sbt compile passes (log above). Asserts in RTL: N1-N10, N12, N13
(with range check), I1-I3. N11 / N14 are Spike-only (D1).
Running: nothing. No server use, no elaboration, no simulator touched, no git writes.
Spike must match for N13: abort when `addr + rows > sp_rows` (sp_rows = sp_banks * sp_bank_entries), legal when equal.
Not done: elaboration of both NM configs and the dense config, dense Verilog diff against stock, any simulation,
NEG / mutant runs (N13 range NEG test is with the tests agent).
Next: server elaboration and Verilator runs, after user approval for the rebuild.
