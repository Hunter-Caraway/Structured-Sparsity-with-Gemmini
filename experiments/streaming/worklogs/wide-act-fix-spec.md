STATUS: DRAFT (2026-11-17). Not frozen; the user freezes it. No code may be written from it until then.

# wide-act-fix spec: 4x N:M compression (1:4, 2:8, 4:16; M = 4N) on the existing Gemmini N:M array

Author: spec agent, 2026-11-17, read-only against RTL `sparse-loop-fix` (11cc20cd), libgemmini `d048776`, gemmini-rocc-tests `22158bf`.
Builds on `fix-a-spec.md` (FROZEN) and `fix-b-spec.md` (FROZEN). Nothing in Fix A / Fix B changes for 2x builds.
Tags: [M] measured or read in source (cited), [E] estimate (reasoning given), [Q] open question for the user.
Line numbers are from the branch heads above.

## 0. Summary and recommendation

Today a stored weight picks one of M = 2N activations, because only two activation rows reach the array per cycle (`a` and the
`b` port). A 4x build (M = 4N) needs four candidates per weight, i.e. 64 activations per cycle, but the scratchpad can supply
32 (section 1.4). Full-rate 4x needs more read ports than the chip has (section 2, option A).

Recommended design (option B, "phased compute", called P below): the compressed weight tile stays DIM x DIM and its index tile stays
log2(M) bits per weight. A 4x sparse tile is used by TWO ordinary sparse computes, phase 0 and phase 1, that accumulate into the same C.
Phase p streams the existing `a_lo` / `a_hi` pair (32 activations per row) and the array zeroes the PE rows whose group lies outside that
32-wide window. New hardware: one phase bit that rides with each compute request (same path as `nm_sparse`), a zero-gate in
`MeshWithDelays`, and a second compute per tile in the loop FSM. No change to the scratchpad, reservation station, PE, DMA, or the
ExecuteController operand ports. 2x netlists stay identical (checked, section 8.3).

Honest cost of P [E]: array time for a 64-wide K block is 2 computes = 32 cycles (with a_lo/a_hi in different banks), the same as 2:4,
so 1:4/2:8/4:16 are NOT faster than 2:4 at the array. What 4x buys is half the weight and index traffic and half the preloads per K
(section 7). A real 4x array speed-up needs option A (about +10 days, risky, section 2). Also, [M] the existing 2x loop places `a_lo` and
`a_hi` in the same scratchpad bank, which makes a sparse compute take 2x cycles (section 1.4); any array-time gain from 2x OR 4x needs a
bank-split A layout in the loop. That is a separate, small fix, recommended first (open question Q1).

## 1. How 2x works today

### 1.1 Config
`GemminiConfigs.scala:112` requires `m == 2 * n`; the comment gives the reason (activation row = `a` + `bd`). Other requires (:113-119): DIM % n == 0, WS only,
no `hardcode_d_to_garbage_addr`, equal input/weight widths ("sparse mode reuses the b port for activations"), m a power of 2,
`meshColumns*tileColumns*log2Up(m) <= 64` (one index row in one 64-bit register), `ex_read_from_spad`. Index width `nm_idx_bits = log2Up(m)` (:121); an index tile is
DIM*DIM*nm_idx_bits bits (:129), `nm_spad_rows_per_tile` spad rows (:130): 4 rows for m=4, 6 for m=8, 8 for m=16 at DIM 16, int8 (computed from the formula, [E] arithmetic only).
Chip configs: `Configs.scala:245-247` (`nmSparseConfig` (2,4), `nm48SparseConfig` (4,8), `nm816SparseConfig` (8,16), the last being added now).

### 1.2 How the candidates reach a PE
- `MeshWithDelays.scala:183-205` (sparse branch): the activation row is `dense_row = a_flat ++ b_shifter_in.flatten` (:190), 2*DIM values: `a` (low half, DIM values from the A operand) then `b` (high half, DIM values from the B operand, "the bias slot").
  PE row r holds a weight of group g = r/n and gets `VecInit(dense_row(g*m + i))` for i in 0 until m (:191-195). Group g covers K positions [g*m, g*m+m); with m = 2n
  and DIM rows this is exactly 2*DIM = the width of `dense_row`. That identity is why m == 2n is required.
- `b` into the array is forced to 0 in sparse mode (:201): the partial sums start at zero, so no bias through `b`.
- `Mesh.scala:25-31, 41`: `in_a` is `Vec(meshRows, Vec(tileRows, Vec(m, inputType)))`, one m-vector per PE row; `Tile.scala:60-62` chains it along the row; `PE.scala:38-42, 91-97`: `a` = `io.in_a(sel)`, `sel = Mux(prop===1, m2, m1)` (the index of the weight in use); `io.out_a := io.in_a` (:103) passes the whole vector on.
- Index: one `log2(m)`-bit index per weight, preloaded with the weight through `d_meta` (`MeshWithDelays.scala:74, 100, 203-204`), shifted down the column like `in_d` (`Mesh.scala:88-96`), held in `m1/m2` (`PE.scala:87-88, 151, 160`).
- So the PE cost is an m:1 mux of 8 bits per PE (2:4 uses 4:1, 4:8 uses 8:1); the row bus is m*8 bits per PE row.

### 1.3 How K is stepped
- Per-tile path (Fix A): `compute_preloaded(a_lo, a_hi)` / `compute_accumulated`; `a_lo` through the A operand (rows A_stride apart), `a_hi` through the B operand with stride 1
  (`ExecuteController.scala:361-362`, `b_address = b_address_rs2 + b_fire_counter`). One compute = 16 rows = 2*DIM of K per weight tile. One real preload (and one index tile, FIFO of 4) per weight tile.
- Fix B loop (`LoopMatmul.scala`): weight K tiles = max_k/2 (`ex_max_k`, :493; `max_k_b`, :450, wired from `max_k >> 1` at :1540); A keeps Berkeley's layout, `a_lo = tile(i, 2k)` (:616), `a_hi = a_lo + DIM`;
  `a_hi_tile = Cat(k, 1)` (:597) gates on LdA; order (k, j, i) with i fastest; preload real at i == 0 else GARBAGE; C accumulates when k != 0. Index tiles: funct 27 mvins in the order ex consumes them, rolling LOAD batches of 2
  (`fix-b-spec.md` 1.5, 2.5.3). K must be a multiple of 2*DIM (assert N6, `LoopMatmul.scala:1371`).

### 1.4 Scratchpad bandwidth per cycle
- 4 banks, single-ported (`Configs.scala:44, 47`), one 128-bit row (16 B) per bank per cycle [M]. The ExecuteController has three operand streams A, B, D; each reads one row per cycle from its bank; `must_wait_for` (`ExecuteController.scala:461-466`) stalls
  a lower-priority stream that hits the same bank in the same cycle. DMA writes win over EX reads (`investigate.md` section 2, citing `Scratchpad.scala:119-120, 175`).
- A sparse compute reads A (a_lo) + B (a_hi) = 32 B/cycle of activations; the weights come over D during the preload (16 rows) overlapped with the previous compute.
- [M] a_lo and a_hi in the SAME bank (what `a_hi = a_lo + DIM` does, both in the per-tile helper `gemmini_nm.h:504-506` and in the loop `LoopMatmul.scala:616`) run at 2 cycles per row: `investigate.md` section 5, micro2 `sp_same_tight` 32.2 cycles/compute vs `dense_tight` 16.15
  (`investigate/runs/20261109-192612-micro2`); with a_lo/a_hi in different banks (`sp_diff_tight`) 16.19, i.e. the full 2x per unit of K. The loop was not re-measured for this; it uses the same-bank layout by code reading [E].
  Consequence: the 2x loop results (berkeley / sparse_loop 1.03-1.35, `branch-status.md`) are likely not array-bound at full rate, and a 4x design inherits the same problem.

## 2. Design options for 4 candidates per stored weight

Common facts: 4x needs 4*DIM = 64 activation values per cycle. Scratchpad: 4 banks x 16 B = 64 B/cycle peak, all banks, no weights, no DMA, no double-buffering. Fix B gives each loop state half of the scratchpad = 2 banks
(`fix-b-spec.md` 2.5.4, "half = 8192 rows = 2 banks").

### Option A: full rate, read 4 activation rows per cycle (two more operand streams)
- Hardware: `ExecuteController.scala` gets two more operand streams (counters, bank arbitration over 5 operands instead of 3, `mesh_cntl_signals_q` fields, response pops, `readData` muxes), `MeshWithDelays` two more decoupled inputs plus written-flags,
  `Mesh/PE` m-vector width unchanged for 1:4 (already Vec(4) as in 2:4); compute command needs four addresses (rs1/rs2 carry two: new encoding), and the ReservationStation has only `opa`/`opb` per entry (`ReservationStation.scala:91-93`), so 4 read ranges
  needs a new RS operand or a conservative contiguous range that creates false dependencies.
- Area/wiring: +2 x 128-bit operand paths and arbitration; PE and mesh bus as in P. Moderate area, high control complexity in the heart of Berkeley's ExecuteController (stock file, touched under `// changed:`).
- Cycle effect [E]: array time per 64-wide K block 16 cycles (2x faster than P) only if the four A tiles sit in four different banks AND weights/DMA do not take a bank cycle. The weights (D) need a fifth read during preloads: 16 rows x 5 reads over 4 banks = 20 cycles for that compute, so TI=1 (every compute preloads) gets 20 not 16, large TI approaches 16. Loop double-buffering gives each loop state 2 banks, so A tiles cannot be spread over 4 banks without giving up the second concurrent loop. Realistic gain is lower than the ideal 4x [E].
- Risk: high. Dense build logic-equivalence is at risk because the operand arbitration code is shared with stock; needs generate-only-on-NM guards around shared logic. Estimate +10 to 14 days over P [E]. Rejected for this window; listed as future work.

### Option B: time-multiplex, two computes per compressed weight row (recommended, "P")
- Mechanism (section 3): phase 0 = first 32-wide window of the 64-wide K block, phase 1 = second window; PE rows outside the window are zero-gated. Same weights, same index tile, results accumulate in the accumulator.
- Hardware: `MeshWithDelays.scala` (gate), `ExecuteController.scala` (carry one bit from compute rs2 to the mesh request, next to `nm_sparse` at :938 / :1046), `Controller.scala` (asserts), `LoopMatmul.scala` (2 computes per tile, K stepping by 4),
  `GemminiConfigs.scala` / `Configs.scala` (ratio). No PE, Mesh, Tile, scratchpad, RS, LoadController change.
- Area/wiring: PE and row buses of 1:4 equal those of 2:4 (Vec(4), 4:1 mux); 2:8 equals 4:8; 4:16 equals 8:16. New: an AND on each bit of the 16 x m row vectors (about 16*m*8 AND gates) and one phase flop per request entry. Negligible.
- Cycle effect [E]: array time per 64-wide K block = 2 x 16 = 32 cycles (bank-split) = same as 2:4 on the same data volume; = 64 (same-bank), same as dense. Weight+index bytes per 64 K: 20 spad rows (1:4), 22 (2:8), 24 (4:16) vs 40 (2:4) and 64 (dense) [E] arithmetic from section 1.1.
  Preloads per 64 K: 1 (vs 2 for 2:4, 4 dense).
- Risk: low to medium. The mesh path is already generic in m. The loop FSM change is the main risk (Execute FSM and the LOAD-between-preload-and-compute rule). 2x elaboration is unchanged because every new line is under `ratio == 4`.
- Dense/2x equivalence: yes by construction; checked section 8.3.

### Option C: bank-wide single read (4 banks read at one address, one fire counter)
Spread the four K tiles over four banks at the same offset so one address broadcast fetches 64 B. Saves control for A but needs every sparse A tile at a fixed bank stride (all 4 banks, no second loop state), and the RS still sees four ranges.
Same cycle ceiling as A, plus a layout straitjacket. Rejected.

### Option D: other ideas considered
- Use the D port for a third candidate during computes with a GARBAGE preload (i > 0 in the loop): only 3 streams in total and D carries weights at i == 0; still 4 needed. Rejected.
- Read activations from accumulator banks (`ex_read_from_acc`) as extra ports: needs a 4th operand stream anyway, int8 re-scaling on read, and puts activations in the accumulator. Rejected.
- Interleaved instead of contiguous phase windows (phase p takes the p-th half of EACH group): same cycles, but the two computes would read A tiles that are not K-contiguous, which breaks the `a_hi = a_lo + DIM` layout and needs a software permute. Rejected; contiguous windows are used (section 3.2).
- Weight-side split (two 2-candidate weight tiles, no hardware change): gives no compression (two tiles for 64 K, same as 2:4). Rejected, it is not 4x.

### Decision
Choose B (P). It is the only option that fits about 2 weeks of work with server runs, leaves 2x builds and dense logic untouched, and is measurable. State in the paper that 1:4/2:8/4:16 here are 4x in storage and bandwidth, 2x in array time. Option A is the follow-up if a 4x array speed-up claim is needed (Q2).

## 3. Chosen design (P)

### 3.1 Config parameters
Replace the single `m == 2 * n` require with a ratio (`GemminiConfigs.scala:111-120`):
- `nm_ratio = m / n`; `require(m % n == 0 && (nm_ratio == 2 || nm_ratio == 4))`. Valid (n, m) at DIM 16: 2x: 2:4, 4:8, 8:16; 4x: 1:4, 2:8, 4:16. (1:2 would also pass ratio 2 but is out of scope; (8,32) fails ratio, m > 16, and the 64-bit index limit.)
- keep `isPow2(m)`, `DIM % n == 0` and add `(DIM / n) % 2 == 0` for ratio 4 (phase windows need an even group count, G = DIM/n).
- keep `meshColumns*tileColumns*log2Up(m) <= 64`: 1:4 = 32 bits, 2:8 = 48, 4:16 = 64 (at the limit, same as 8:16). Index tile spad rows: 4 / 6 / 8.
- `nm_ratio` is a `val` on the config (Option[Int] like `nm_idx_bits` pattern: 1 on dense, exported). New header define `GEMMINI_HW_NM_RATIO` next to `GEMMINI_HW_NM_N/M` (`GemminiConfigs.scala:531-533`); software and Spike take `NM_RATIO = NM_M / NM_N` and static_assert it equals the header value.
- `Configs.scala` (after :247): `nm14SparseConfig`, `nm28SparseConfig`, `nm416SparseConfig`; chipyard config names follow the nm24/nm48 pattern (implementer chooses; not in the spec).
Generated hardware for ratio 2 must be identical to today's (section 8.3).

### 3.2 Semantics (what RTL and Spike both implement)
Notation: n, m = 4n, G = DIM/n groups, K block = 4*DIM activations of one A row, window p = K positions [p*2*DIM, (p+1)*2*DIM), p in {0,1}. Group g covers K positions [g*m, g*m + m) of the block. Since 2*DIM/m = G/2, a group lies wholly in one window: window p holds groups [p*G/2, (p+1)*G/2).
- A compressed 4x tile is the usual DIM x DIM weight tile: PE (r, c) holds weight w(r, c) of group g = r/n with index idx(r, c) in [0, m). Real value position in the K block: kd = g*m + idx.
- A sparse compute with phase p (new bit, 3.3) with operands (a_lo, a_hi) = the two A tiles of window p (K-contiguous: a_hi = a_lo + DIM) feeds PE row r the vector
  `Vec(m, i -> dense_row(((g mod G/2) * m) + i))` if g / (G/2) == p, else a zero vector; `dense_row = a ++ b` as today (`MeshWithDelays.scala:190`).
  The PE index select is unchanged, so a PE whose group is outside the window multiplies by 0 and passes its partial sum through.
- Per output element: out(i, c) = sum over r of w(r,c) * A(i, kd(r,c)); over the two phases with accumulation exactly the 4x sparse dot product. Spike: `kd` as today but over 4*DIM with `a = 0` when `kd` is outside window p
  (replaces `gemmini.cc:635-646`, which reads `kd < DIM` from `a_lo` and else from `bd`).
- Phase 1 must accumulate into the C written by phase 0 (assert W3). Both computes use the same weights: phase 0 is `compute_preloaded` after the real preload (i == 0) or `compute_accumulated` after a GARBAGE preload; phase 1 is `compute_accumulated` after a GARBAGE preload whose C operand has the accumulate bit.
- Ratio 2: no phase bit; behaviour exactly as today.

### 3.3 Phase bit encoding
Compute rs2 (the B/`a_hi` operand) bit 63 = `nm_phase` (reserved today: `ComputeRs`, `GemminiISA.scala:250-257`; rows are bits [52:48], `ExecuteController.scala:195-196`; bits [62:53] and 63 are `_spacer2`). Bits [62:53] must be 0 (assert W5).
Meaning only on a ratio-4 build in sparse mode. The bit is read where the compute command is dequeued, stored in `mesh_cntl_signals_q` (new field `nm_phase`, ratio-4 builds only, beside `nm_sparse` at `ExecuteController.scala:938`), and applied through the request:
`MeshWithDelaysReq.nm_phase` (beside `nm_sparse`, `MeshWithDelays.scala:16`, applied at :1046 of the controller). The request holds all 16 rows of a compute, so the gate has the same timing as `nm_sparse`.
No new funct. Alternative considered: toggle a phase counter in hardware after each preload; rejected, it breaks when software reorders computes (explicit bit is assertable).

### 3.4 Loop (`LoopMatmul.scala`, `sparse-loop-fix` extension; all lines `// changed: wide-act-fix`)
- `max_k` stays the A tile count; weight K tiles `max_k_b = max_k / 4` (`:1540` `>> 1` becomes `>> log2(ratio)`); `ex_max_k` (`:493`) likewise. K must be a multiple of 4*DIM (assert W4, replaces N6 on ratio-4 builds).
- Weight tile k needs A tiles 4k..4k+3: `a_lo`(ph0) = tile(i, 4k), `a_hi`(ph0) = +DIM; `a_lo`(ph1) = tile(i, 4k+2), `a_hi`(ph1) = +DIM (`:616` and `a_hi_tile`, `:597`, become `Cat(k, 3.U(2.W))`; LdA/LdB lookahead gates use the last A tile of the weight tile).
- Execute order per (k, j): for i in 0 until max_i: [pre (real at i == 0 else GARBAGE), comp ph0 (flip at i == 0 else stay)], [pre GARBAGE with C accumulate = 1, comp ph1 (stay)]. Phase 0 C accumulate as today (k != 0); phase 1 always accumulates.
- LOAD rule (`fix-b-spec.md` 1.5) unchanged: LOADs only after the last compute of a weight tile and before the next preload; the lookahead before the next tile doubles (2 computes per i), so the FIFO budget rule P1 still holds.
- StC fires after the last weight tile (k = max_k/4 - 1) and its last phase-1 compute. Index tiles: n_tiles = (max_k/4)*max_j; LdIdx, `nm_spad_rows_per_tile` unchanged per tile.
- Spad regions: A as today, B region quarter size, index region (max_k/4)*max_j*R rows, same bank rules (N9 recomputed with ratio).
- Bank layout of A is NOT changed by this spec (Q1).

### 3.5 What does not change
Scratchpad, LoadController, DMA, ReservationStation, PE, Tile, Mesh, accumulator, Fix A index loader (an index tile is 16 rows of 16 x log2(m) bits for any m; `ExecuteController.scala:123-124` already generic), funct 26/27/28 encodings. `LOOP_WS_CONFIG_NM` (funct 28) keeps rs1 = idx_dram, rs2 = 0; the ratio is a build constant, not an operand.

## 4. ISA, software, Spike

### 4.1 Software (`gemmini-rocc-tests/include/gemmini_nm.h`; existing helpers and macros stay byte-identical for 2x)
- Replace `_Static_assert(NM_M == 2*NM_N)` (:44) with `NM_RATIO = NM_M / NM_N`, `NM_RATIO == 2 || NM_RATIO == 4`, `GEMMINI_HW_NM_RATIO` agreement. `NM_MAX_M` already 16 (:41); `NM_LOG2_M` (:43) fine.
- `nm_compress` / `nm_decompress` / `nm_ref_sparse` (:95-180): group arithmetic is already in terms of n, m; verify for m = 4n over K blocks (tests catch it). New helper `nm_kblock = NM_RATIO * DIM`.
- New macro for phase: `gemmini_nm_compute_phase(a_lo, a_hi, phase, ...)` = existing compute with `rs2 |= (uint64_t)phase << 63` (ratio-4 builds only; on ratio 2 a use is a `#error`/static assert).
- Per-tile path: new variants `sparse_wide` (`<mode>_<fix>` naming: `sparse_wideact`) that issue the two computes per tile; existing variants untouched.
- Loop helpers: `nm_loop_pad_k` (:614) pads to NM_RATIO*DIM; `gemmini_loop_ws_nm` unchanged call shape; `tiled_matmul_nm_loop` (:690) and `nm_loop_order_idx` (:667) use `K / NM_RATIO` weight tiles.
- mvin of activations: unchanged (plain mvin of A, a_hi = a_lo + DIM; contiguous 4-tile K blocks).
- Benchmarks: new variants only; same output line format; every variant verifies against the CPU reference (AGENTS C rules).

### 4.2 ISA (LOAD_IDX funct 27, LOOP_WS_CONFIG_NM funct 28, LOOP_WS rs1[3])
No new funct and no field changes. Funct 27 rows/cols limits (N12) unchanged: an index tile is `nm_spad_rows_per_tile` rows (4/6/8) and `block_size/R` tiles per mvin is 4/2/2 for 1:4/2:8/4:16 (R = 4/6/8: `floor(16/R)` = 4/2/2). Funct 28 unchanged. The only encoding change: compute rs2[63] (3.3).

### 4.3 Spike (libgemmini)
- `gemmini.h:35` static_assert `NM_M == 2*NM_N` becomes the ratio rule; `gemmini.h:38` 64-bit index row check stays.
- `gemmini.cc:635-646` sparse compute: phase from rs2[63] (read where `compute` parses rs2); window rule of 3.2; reserved-bit abort (W5), phase on ratio 2 abort (W6, Spike only).
- Sparse `LOOP_WS` (`gemmini.cc:1085-1135`): K stepping by NM_RATIO, two pairs of preload+compute per i, phase and accumulate bit on the second; `nm_loop_load` and the rolling batch (`:1040, ~1130`) are per weight tile and need no change.
- 2x builds: all new code under `#if NM_RATIO == 4` so 2x behaviour is unchanged (checked by the existing 2x Spike matrix re-run, section 8.1).

## 5. Illegal use: asserts and NEG tests
Messages start with the feature name `wide-act-fix:`. RTL asserts exist only in ratio-4 elaborations; Spike aborts with the same text unless marked.
| # | condition | message |
|---|---|---|
| W1 | (elaboration `require`, not sim) ratio not 2 or 4, `m % n != 0`, ratio 4 with odd DIM/n, index row > 64 bits | `wide-act-fix: n:m sparsity needs m == 2*n or m == 4*n ...` |
| W2 | compute with rs2[63] = 1 while not in n:m sparse mode (`nm_sparse_mode` false) | `wide-act-fix: compute phase bit (rs2[63]) set outside n:m sparse mode` |
| W3 | phase-1 compute whose C operand (its paired preload rs2) is not a valid accumulate address (accumulate bit 0 or GARBAGE) | `wide-act-fix: phase-1 compute must accumulate into C (preload rs2 accumulate bit)` |
| W4 | sparse loop on a ratio-4 build with K tile count % 4 != 0 or pad_K != 0 | `wide-act-fix: sparse loop needs K % 4*DIM == 0 and pad_K == 0` |
| W5 | compute rs2[62:53] != 0 on a ratio-4 build | `wide-act-fix: compute rs2 reserved bits [62:53] must be 0` |
| W6 | (Spike only) rs2[63] = 1 on a ratio-2 build; RTL 2x ignores the bit so its netlist stays unchanged | `wide-act-fix: phase bit on a build with m == 2*n` |
| I1 | (internal) loop emits phase-1 compute without a phase-0 compute of the same (k, j, i) before it | `wide-act-fix: internal: phase 1 without phase 0` |
| I2 | (internal) phase window A address mismatch (ph1 a_lo != ph0 a_lo + 2*DIM) | `wide-act-fix: internal: phase window addresses inconsistent` |
W2, W3, W5: Controller (program-order model, `unrolled_cmd`, where the existing Fix A asserts sit, `Controller.scala:579+`); W4: LoopMatmul at LOOP_WS decode next to N6 (`LoopMatmul.scala:1371`), replacing N6's condition on ratio-4 builds. N1-N14, P1-P5 of Fix A/B keep firing for ratio-4 programs unchanged.

NEG tests (each one build, one expected message, in Spike and RTL; numbering `wN` like fix-b-spec N-numbers):
- w2: ratio-4 chip, dense mode, compute with rs2[63] set.
- w3a: phase-1 compute with preload C accumulate bit 0; w3b: C GARBAGE.
- w4a: loop K = 3*DIM (odd tile count); w4b: K = 6*DIM (even, not multiple of 4); w4c: pad_K != 0.
- w5: rs2 bit 62; w5b: bit 53.
- w6: Spike only, 2:4 build with rs2[63] set.
- w1: server elaboration of five bad configs (1:2 with ratio rule bypass, 3:12, 2:6, 8:32, 1:8) must stop with the `require` text (no Verilator).
- I1/I2 are covered by mutants only.
Mutants (each must fail the positive matrix): phase gate inverted; phase always 0; phase read one request late; window map uses g instead of g mod G/2; ph1 without accumulate; loop K stepped by 2 (ratio-2 constant); ph1 a_lo = ph0 a_lo + DIM; StC at k == max_k/2 - 1; LdB or LdIdx tile count not divided by 4; W4/N6 check removed; index width log2(m) - 1; reserved-bit assert removed.

## 6. Hazards
- C double-write: phase 0 and phase 1 write the same accumulator rows ~16+ cycles apart; the RS and accumulator already serialise same-address accumulate writes (existing k accumulation with max_i = 1 does the same); `total_rows` floor 4 stays.
- Weight stationary: phase 1 must not re-preload real weights between the two phases; the loop order (i, phase) keeps weights resident; a real preload between phases is legal for software but changes weights (not asserted; phase is independent of weights).
- Index FIFO budget (P1) and LOAD placement unchanged: per tile the number of computes only grows.
- Bank conflicts: a_lo/a_hi of a phase same-bank means 2 cycles/row (section 1.4); not a correctness hazard.

## 7. Expected benefit [E] (reasoning, no new measurement)
Per 16x16 output tile and a 64-wide K block, array time in cycles (compute rows only, preload overlapped):
| build | a_lo/a_hi same bank | a_lo/a_hi different banks |
|---|---|---|
| dense | 64 | 64 |
| 2:4 / 4:8 / 8:16 | 64 (two 32-wide computes at 2 cycles/row) | 32 |
| 1:4 / 2:8 / 4:16 with P | 64 | 32 |
| 1:4 / 2:8 / 4:16 with option A | n/a | 16 (ideal, 20 with a preload) |
Weight+index spad rows per 64 K (tile rows 16; index rows 4/6/8): dense 64, 2:4 32+8 = 40, 1:4 16+4 = 20, 2:8 16+6 = 22, 4:16 16+8 = 24 (formula `GemminiConfigs.scala:129-130`). Weight DMA bytes and preload commands per K: about half of 2:4.
So against 2:4 the measurable gains are mvin bytes and preloads, not array cycles. Whether this shows in end-to-end cycles depends on whether the layer is weight-load bound; Fix B layers were mostly CPU/issue or DMA bound (`branch-status.md`). No speed claim beyond "same array time as 2:4, half the weight traffic" until measured.

## 8. Cost and test plan

### 8.1 Spike first (laptop, scratch dir, `--extlib`, AGENTS Done-means)
1. Build libgemmini in a scratch dir for 1:4, 2:8, 4:16 (and re-run 2:4, 4:8 and 8:16 if present) with `-DNM_N/-DNM_M`.
2. Positive tests: all existing `nm_sparse_*` tests (`bareMetalC/nm_sparse_{sw,matmul,spad,perf,debug,loop,protocol}.c`) built per chip; shapes adapted to K % (NM_RATIO*DIM); new `nm_sparse_wide` (per-tile phase pair, all window edges: idx 0, m-1, group at G/2-1 and G/2, rows < 16, a_rows/cols padding) and a loop variant covering max_i 1 and > 1, max_j 1 and > 1, odd/even weight tile counts, T < 4, T = 4, T > 4, bias, back-to-back loops, loop followed by per-tile sparse.
3. NEG tests w2-w6 (Spike). Mutants of section 5 against the positive tests (Spike side).
4. Berkeley dense 54 tests on each new Spike config; the 2x regression matrix of Fix A/B unchanged and passing (proves 2x software unaffected).

### 8.2 Verilator on the server (needs user approval per simulator build; at most 12 simulations at once)
Three new simulators (names follow the nm24 pattern): nm14, nm28, nm416. Existing nm24, nm48, stock simulators are NOT rebuilt (AGENTS rule 3); nm816 is a separate task.
- Per config: all `nm_sparse_*` tests (incl. `nm_sparse_wide`, `nm_sparse_loop`), the w-NEG tests (RTL side, `run-flow.sh` queue mode "fail"), the 54 dense tests (expected fail set = the 5 known Berkeley/test-timeout fails, `branch-status.md` "Dense tests"; any other fail is a regression), the streaming benches (rn50, ffn1, ffn2, qkv, edge, small) with new variants `sparse_wideact` and `sparse_loop_wideact` next to `berkeley` on the same chip, seeds 1-3, and `fair_perf`.
- Timeouts (`run-flow.sh:282-291` `prog_timeout`): `nm_sparse_loop_NN` >= 300M (passes 22/22 at 600M on nm24/nm48, `branch-status.md`); the ratio-4 loop test does 2 computes per tile, so use 600M until a measured cycle count exists, then set measured x 2; add `nm_sparse_wide*` the same 600M; `conv_with_input_dilation*` >= 300M (never finished at 150M, `fixb-verify.md` verdict); all others default 150M.
- Every cycle counts only with its verified line (rule 4); compare cycles only within one chip build (nm14 berkeley vs nm14 sparse). Cross-chip ratios (e.g. nm14 vs nm24) are allowed only labelled cross-chip (2026-11-12 ruling).

### 8.3 Dense and 2x equivalence
Elaborate (no Verilator) nm24 and nm48 before and after the RTL change on the server and diff the generated Verilog: must be identical modulo names and `@[file:line]` (user needs to approve the elaboration job; criterion of the 2026-11-13 changelog in `fix-b-spec.md`). The stock chip diff against the earlier dense-diff (`dense-verilog-diff.md`) must stay empty. All new RTL is guarded by `nm_ratio == 4`; the Controller assert path W2/W3/W5 is generated only for ratio 4.

### 8.4 Effort (days, working days of agent time incl. reviews; server waiting separate) [E]
| step | days |
|---|---|
| spec review, freeze, questions | 0.5 |
| config + headers + 3 chip configs, `sbt compile` | 0.5 |
| MeshWithDelays gate, ExecuteController phase plumbing, Controller asserts | 1.5 |
| LoopMatmul ratio-aware K stepping, 2 computes per tile, W4, N9 recompute | 3 |
| Spike model (compute, loop, asserts) | 1.5 |
| software helpers, per-tile variant, loop variant, benches | 2 |
| tests: positive, NEG, mutants, Spike matrix | 2 |
| elaboration diff of 2x + 3 new builds, server runs, triage | 2 |
| result verification and write-up | 1 |
| total | about 14 (about 9-10 elapsed with RTL, Spike and software agents in parallel after freeze) |
Cut line if late: drop 4:16 first (the config exists but is not run), then `conv_with_input_dilation*`, then benches beyond qkv/rn50. Bank-split fix (Q1) adds about 2 days and is separate.

## 9. Open questions (each with a recommended answer)
- [Q1] The 2x loop (and any 4x loop) puts `a_lo`/`a_hi` in one bank, so a sparse compute takes 2x cycles and the array gain disappears (section 1.4, [M] for the per-tile path, [E] for the loop). Do a small `bank-split-fix` (A tiles alternate between two banks of the loop's half) before or with this work? Recommended: yes, as its own spec, done first. It changes existing 2x cycle counts, so the README table and any paper number from the 2x loop would need re-measuring with user approval. Without it, 1:4/2:8/4:16 show no array-time gain at all.
- [Q2] Accept "same array time as 2:4, half the weight traffic" for 1:4/2:8/4:16 (option P), or require a true 4x array speed-up (option A, about +10 to +14 days, would not fit the 2-week budget)? Recommended: accept P now; list A as future work.
- [Q3] Phase bit in compute rs2[63] OK (reserved spacer today), or prefer a config_ex bit and a mode toggle? Recommended: rs2[63] (explicit, assertable, no new state).
- [Q4] Require K % 4*DIM == 0 in the loop (assert W4), software zero-pads, as Fix B did for 2*DIM (Q2 of Fix B)? Recommended: yes.
- [Q5] OK to touch the same Berkeley files as Fix B (MeshWithDelays, ExecuteController, Controller, LoopMatmul, GemminiConfigs, Configs) under `// changed: wide-act-fix`? Recommended: yes; no new Berkeley file.
- [Q6] Approve three new Verilator builds (nm14, nm28, nm416) and one elaboration-only run of nm24/nm48 for the equivalence diff, after the spec is frozen and Spike tests pass? Recommended: yes, builds sequential (AGENTS: never parallel `make` in `sims/`).
- [Q7] Which 4x configs matter for the paper? Recommended: 1:4 and 2:8 first, 4:16 last (index row at the 64-bit limit, widest PE mux).
- [Q8] Coordination with the nm816 work: that change also edits `Configs.scala` and `GemminiConfigs` requires. Recommended: merge nm816 first, then branch `wide-act-fix` from it, to avoid a conflict in the `m == 2*n` line.

## Changelog
- 2026-11-17: first draft (STATUS: DRAFT). Reads: GemminiConfigs.scala, PE.scala, Tile.scala, Mesh.scala, MeshWithDelays.scala, ExecuteController.scala, LoopMatmul.scala, ReservationStation.scala, Scratchpad.scala, libgemmini gemmini.cc/.h, gemmini_nm.h, investigate.md section 5, branch-status.md, run-flow.sh. Nothing built or run.

## Working notes / RESUME HERE
Done: read-only study of the 2x data path and loop; options A/B/C/D compared; design P chosen; asserts W1-W6, I1-I2, NEG and mutant lists, test plan, effort, open questions written.
Verified in source this session: m == 2n require (GemminiConfigs.scala:112); the 2*DIM `dense_row` and per-group gather (MeshWithDelays.scala:183-205); per-bank single-ported spad, 4 banks (Configs.scala:44, 47); RS has only opa/opb (ReservationStation.scala:91-93); compute rs2 bits [62:48] spare except rows [52:48] (GemminiISA.scala:250-257, ExecuteController.scala:195-196); loop a_hi = a_lo + DIM (LoopMatmul.scala:616, 597); Spike kd formula (gemmini.cc:635).
Not verified (check before freeze): (1) that no existing assert or RS logic reads rs2[63:53] of compute (grep of ExecuteController/Controller/RS for rs2 slices, only :195-196 found); (2) the loop currently runs a_lo/a_hi at 2 cycles/row: derived from the layout and the per-tile micro-benchmark, not from a loop measurement (suggest one cheap sim: nm_sparse_loop with a_hi forced to another bank, or read ex_active counters of an existing fixb run); (3) accumulator accepts phase-1 accumulate 16 cycles after phase 0 to the same rows without a WAW stall beyond the existing floor; (4) `nm_spad_rows_per_tile` numbers 4/6/8 are arithmetic from the formula, not a build; (5) whether LdA lookahead (`lda_ahead_nm`, :598) needs the exact last A tile index 4k+3 or 4k+1 per phase.
Next: user answers Q1-Q8, then freeze; implementers start with config + Spike (no RTL dependency), RTL agent starts with MeshWithDelays + ExecuteController plumbing, then LoopMatmul.
