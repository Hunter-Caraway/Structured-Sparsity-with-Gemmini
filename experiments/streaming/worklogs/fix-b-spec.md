STATUS: FROZEN (2026-11-12). Semantics below must not change without a changelog entry at the end.

# Fix B spec and cost estimate: N:M sparse mode inside the hardware matmul loop (LOOP_WS)

Author: spec agent, 2026-11-12 (written 11:15-11:45 EST against the working tree; Fix A and protocol changes are
uncommitted there). Builds on `fix-a-spec.md` (FROZEN) and HANDOFF.md section 5 (removed from the tree; see `git show e06b436:HANDOFF.md`). Nothing in Fix A changes; Fix B
only adds a new *producer* of the Fix A commands (preload / compute with a_hi / LOAD / mvin of index rows).

Tags: [M] = measured (log or source cited), [E] = estimated (reasoning given), [Q] = open question for the user.

## 0. Why

[M] With Fix A, a sparse layer still issues every preload, compute and mvin from the CPU. Streaming totals, keeper
tiler, Fix A RTL (`fix-a-server.md` Results): sparse is 0.95-0.96x (small), 0.85-0.86x (edge) and 0.78-0.79x (bert_qkv)
of Berkeley's stock dense `LOOP_WS` run. Sparse beats the same-chip per-tile dense stream by 1.1-1.16x but not Berkeley's
loop. The remaining gap is CPU issue cost: [M] Spike instruction counts of the keeper Fix A programs are 287,902
(qkv 2:4) vs 401,522 HW cycles, i.e. the CPU issues roughly 0.7 instruction per cycle of runtime (Spike CPI = 1, real
Rocket is slower), so the run is CPU-issue-bound. Berkeley's loop issues ~6 RoCC commands per `LOOP_WS` call and the
unroller generates the rest in hardware. Fix B lets a sparse layer use that unroller.

## 1. What LoopMatmul generates today, and where sparse plugs in

### 1.1 Today (LoopMatmul.scala; line numbers of the working tree)
`LoopMatmul` (line 892) holds 2 concurrent loop states (`concurrent_loops = 2`, line 910), each with half of the
scratchpad (`a_addr_start = i * max_addr/2`, `b_addr_end = (i+1) * max_addr/2`, reset block at the end of the file).
Config commands LOOP_WS_CONFIG_BOUNDS/ADDRS_AB/ADDRS_DC/STRIDES_AB/STRIDES_DC (functs 9-13) and the SPAD_AB/SPAD_C
variants (24, 25) fill `LoopMatmulState` (line 813); `LOOP_WS` (funct 8) marks it configured and starts it. Five FSMs
then run in parallel and merge into one RoCC command stream through `arb = Arbiter(5)` (line 960):

| FSM | line | emits | iteration order |
|---|---|---|---|
| `LoopMatmulLdA` | 28 | mvin (LOAD_CMD, id 0) of A tiles into `a_addr_start + (i*max_k + k)*DIM` | k, i |
| `LoopMatmulLdB` | 139 | mvin2 (LOAD2_CMD, id 1) of B tiles into `b_addr_end - max_k*max_j*DIM + (k*max_j + j)*DIM`, up to `max_block_len` tiles along j per command | k, j |
| `LoopMatmulLdD` | 253 | mvin3 (LOAD3_CMD, id 2) of bias into the accumulator | |
| `LoopMatmulExecute` | 352 | per (k, j, i): preload (real B at i == 0, GARBAGE at i > 0, C acc address with accumulate when k != 0), then compute (`COMPUTE_AND_FLIP` at i == 0, `COMPUTE_AND_STAY` else; rs2 = GARBAGE) | k, j, i (i fastest) |
| `LoopMatmulStC` / `StCSpad` | 514 / 707 | mvout of C once ex has passed (k = max_k-1) for that (i, j) | i, j |

Pacing: `ex` only emits a command when A and B tiles it needs are already *issued* (`lda_ahead`, `ldb_ahead`, lines
~456-460, fed from `ldA.io.k/i`, `ldB.io.k/j`); the reservation station (RS) then enforces the real RAW/WAR by
scratchpad address. `ld_utilization`/`ex_utilization`/`st_utilization` (line ~968) throttle against RS entries
(`max_lds/max_exs/max_sts`). A loop is done when all five FSMs are idle (`all_completed`, line 863 / 1294).

### 1.2 What a sparse tile looks like (Fix A / HANDOFF 5)
A sparse weight tile is a squashed DIM x DIM tile covering 2*DIM original K rows. The compute streams a 2*DIM wide
activation: `rs1` = a_lo (K tile 2k'), `rs2` = a_hi (K tile 2k'+1), a_hi rows always 1 apart, a_lo rows A_stride
apart (A_stride = 1 in the loop layout). The index tile (R rows of 16 B, R = 4 for 2:4, 6 for 4:8) must be in the
index FIFO before the real preload; mode is latched with the weights at the real preload. This is what `nm_stream_impl`
in gemmini_nm.h (lines ~440-510) already issues per tile.

### 1.3 Plug-in points (all inside LoopMatmul.scala unless noted)
| # | place | change |
|---|---|---|
| P1 | `LoopMatmulState` / `LoopMatmulExecuteReq` / `LdBReq` / `StCReq` | new field `nm: Bool` (sparse loop) plus index base addresses (section 2). Generated only `if (nm_sparsity.isDefined)`; dense elaboration is untouched. |
| P2 | `LoopMatmulLdB` | B has max_k/2 K tiles: use `kb = max_k >> 1` for `sp_addr_start` (line 178), iteration bound (`max_row_iterator`) and `blocks`. DRAM side unchanged (B in DRAM is already the squashed K/2 x N matrix, `B_stride` as given). |
| P3 | `LoopMatmulExecute` | iterate k' in 0..max_k/2-1; a_lo address uses A tile `2k'`, a_hi = a_lo + DIM; `comp_cmd_rs2` = a_hi with num_rows = a_rows, num_cols = DIM (today GARBAGE, rows/cols DIM); `b_addr_start` uses `max_k/2`; `lda_ahead` must test A tile `2k'+1`; C accumulate flag `k' != 0` unchanged. |
| P4 | `LoopMatmulStC`, `StCSpad` | [M, read] they test `io.ex_k === req.max_k - 1` (LoopMatmul.scala:629, 780) and the wiring at 1215/1228 passes `max_k`: pass `max_k/2` for a sparse loop. `ex` itself needs both values (A layout uses the original max_k via `a_max_col`, line 398; B layout and k iteration use the half), so `LoopMatmulExecuteReq` gains `max_k_b`. LdA (line 1121) keeps the original max_k, LdB (line 1142) gets the half. |
| P5 [SUPERSEDED in part: funct 27, see 2.5.3] | new `LoopMatmulLdIdx` | new FSM (copy of LdB structure) that mvins index tiles, see 1.4. Joins `ldab_arb`/`arb` (arb becomes 6 inputs); counted in `ld_utilization`. |
| P6 | `LoopMatmulExecute` | new state `ldidx` between the last compute of weight tile u and the preload of tile u+1 (and before the first preload) that emits a Fix A LOAD (funct 26, rd = 2) when the budget rule of 1.5 allows. |
| P7 | Controller.scala:274-285 | replace the "LOOP_WS in sparse mode" assert by 2.5.5/2.5.6. |
| P9 | GemminiISA.scala, LoadController.scala, ReservationStation.scala | funct 27 `LOAD_IDX_CMD` (2.5.2): funct constants, constant stride/scale/block-stride mux in LoadController (:61-70, :107), RS dst range / is_load / id handling (ReservationStation.scala:276, 296, 323); NM builds only. |
| P8 | ExecuteController.scala | **no change expected**: it already handles real sparse preload, compute with a_hi, and the LOAD diverter; the loop emits exactly the commands software emits today. |

Layout consequence (spad): A tiles keep Berkeley's `(i*max_k + k)*DIM` row-major tile layout with the original max_k,
so a_lo = tile(i, 2k'), a_hi = tile(i, 2k'+1) = a_lo + DIM (rows consecutive, matches "a_hi stride 1"). B region is
half size. [SUPERSEDED by 2.5.4: index region at the top of the half, B below it] Index region (new): `idx_addr_end = b_addr_start`, `idx_addr_start = idx_addr_end - n_tiles*R` where
`n_tiles = (max_k/2)*max_j`; carved just below the B region of the loop's half. RTL assert: the whole region lies in
one scratchpad bank (LOAD bank rule, Fix A section 3) and does not collide with A (`a_end <= idx_addr_start`).
Software tiler must size tiles with this reserve (section 6).

### 1.4 LdIdx (index mvin) detail [mvin3 / config_ld id 2 / "D = NULL" parts SUPERSEDED by 2.5.2-2.5.3: LdIdx emits funct 27 with fixed config; bias allowed]
- Index tiles are stored in DRAM contiguously in the same order the loop consumes weight tiles: tile u = k'*max_j + j
  (k', j as in LdB order), each tile R*16 bytes (the Fix A "tight" format, `nm_pack_meta_spad`). DRAM address of tile
  u = `idx_dram + u*R*16`; spad rows `idx_addr_start + u*R`.
- One mvin covers g = floor(16/R) tiles (4 for 2:4, 2 for 4:8; mvin row limit 16 rows, cols = 16 B): rows = min(g,
  remaining)*R. Command: mvin3 (LOAD3_CMD, id 2) so it needs `config_ld(16 B stride, id 2)` set by software before
  the loop. Consequence: a sparse loop cannot use LdD bias in v1 (D = NULL), see [Q1].
- Pacing against LdB: the ex-side LOAD can only be emitted after the covering mvin is *issued* (otherwise the RS misses
  the RAW dependence). If LdIdx were a low-priority arbiter input it would issue only after all A/B mvins, serializing
  load and compute. Rule: LdIdx issues whenever `u_idx <= u_B + g` (stays one mvin ahead of LdB, tile index of LdB =
  k*max_j + j) and wins the arbiter against LdB in that case; LdA/LdB order logic (`WeightedArbiter`) is untouched.

### 1.5 LOAD generation rule in Execute (implements Fix A rule P1/P5)
State in `ex`: `loaded` = tiles named by LOADs emitted so far; `pre` = real preloads emitted (counts at emission, i.e.
program order, same as the Controller's model). Program order of `ex` commands: LOAD(0..3) (n = 4), then for each tile u:
`pre(u) comp(u) [garbage pre + comp for i = 1..max_i-1]`, with a LOAD inserted **only after the last compute of a
tile and before the next preload** (never between a preload and its paired compute: P5). After the last compute of
tile u (so `pre = u+1`, in_flight = 0): if `loaded < n_tiles` and `loaded - pre <= 2` and idx mvins covering
tile `loaded + n - 1` are issued, emit LOAD with `n = min(2, n_tiles - loaded)`, `addr = idx_addr_start + loaded*R`.
Then q + in_flight + n = (loaded - pre) + 2 <= 4: the P1 budget holds by construction. This is the "rolling batch of 2"
pattern of Fix A section 6 (lookahead >= 2 tile-times of max_i computes each). Bank rule satisfied because the whole
index region is in one bank (asserted). 1 LOAD per 2 tiles, plus one initial LOAD of 4: for a layer of T tiles about
T/2 + 1 LOADs, i.e. +0.5 command per tile; irrelevant because they are generated in hardware (CPU cost zero).

## 2. ISA changes

### 2.1 [SUPERSEDED 2026-11-12 by 2.5: no bias possible, rejected by Q1] A flag in LOOP_WS and reuse of the D slots; no new funct
Dense LOOP_WS encoding is unchanged bit for bit. Used bits today: LOOP_WS rs1 [0] ex_accumulate, [1] full_C, [2] low_D,
[15:8] act, [19:16] spad ids; rs2 [0] a_transpose, [1] b_transpose, [2] is_resadd, [9:3] FSM-started flags, [63:32]
c_spad_addr (SPAD variant). Free: rs1[7:3], rs1[63:20], rs2[31:10].

New bit **LOOP_WS rs1[3] = nm_sparse** (call it `loop_nm`). When set:
- `ADDRS_DC.rs1` (the D DRAM pointer, otherwise bias) = **index DRAM address** `idx_dram` (must be non-zero, 16 B
  aligned); `STRIDES_DC.rs1` (D stride) must be 0 (ignored).
- The loop's K bound in CONFIG_BOUNDS is the **original** K tile count (A needs it) and must be even; pad_K must be
  0 (v1, [Q2]); the software pads K up to a multiple of 2*DIM with zero rows in A and zero weights (cost <= 1 tile pair).
- Illegal with `loop_nm`: A_transpose, B_transpose, is_resadd, low_D, `spad_only` variant (v1), LOOP_CONV_WS.
- Mode: software still issues `gemmini_nm_config_ex(1, ...)` (rs1[10] of config_ex) before the loop, exactly as for
  the per-tile path. The loop does not touch config_ex; the preloads it emits are latched sparse by the existing
  ExecuteController logic. Index base in scratchpad is not an operand (derived, section 1.3).

### 2.2 [ADOPTED 2026-11-12 in the form of 2.5, with a second funct 27; text below is the original sketch] Alternative: one new funct
funct 27 `LOOP_WS_CONFIG_NM`: rs1 = idx_dram, rs2 = flags/idx spad base. It must be added to `is_loop_config_cmd`
(line 983) and the LoopUnroller range checks; the sparse flag then lives there. Costs ~10 lines more, a new CPU
instruction per call, and LdD must be told a different mvin id (only three ids exist, so bias and index would share
mvin3 stride config: not possible without a new load-config id). Not recommended for v1.

### 2.3 [SUPERSEDED by 2.5.5/2.5.6, messages now "sparse-loop-fix: ..."] Controller assert (Controller.scala:274-285)
Today: LOOP_WS / LOOP_CONV_WS while `nm_loop_sparse` (config_ex rs1[10]) is on is fatal. New rule, checked where
LOOP_WS is seen on `raw_cmd`: `LOOP_WS.rs1[3] == nm_loop_sparse` (sparse loop only in sparse mode, dense loop only in
dense mode) and LOOP_CONV_WS with sparse mode stays fatal. Message: "LOOP_WS nm flag (rs1[3]) differs from n:m sparse mode (config_ex rs1[10])". The program-order model (q, in_flight, mode latch, P1-P5 asserts) sits after the
unroller on `unrolled_cmd` (Controller.scala:579+), so it automatically polices the commands the loop generates; no
change. (This is also the self-check for the loop FSM: a budget or ordering bug becomes a named assert in simulation.)

### 2.4 Backwards compatibility
Dense chips (`nm_sparsity = None`): the new fields and FSM are not elaborated; rs1[3] is ignored as today (assert in
the stock Berkeley build is unchanged). NM chips running dense code: rs1[3] = 0 so behaviour is identical. Existing
sparse per-tile software (Fix A path) is unchanged and remains the fallback; `LOOP_WS` with rs1[3] = 1 in the old
protocol would have been fatal, so no existing program breaks.

### 2.5 Chosen design after the 2026-11-12 decisions (Q1: bias needed; Q2: K % 2*DIM == 0). Replaces 2.1; adopts 2.2 in this form

Two new functs and one flag. Nothing in Fix A, in the dense LOOP_WS encoding, or in config_ld/LdD changes. Bias (LdD, mvin3,
accumulator) works exactly as in a dense loop.

#### 2.5.1 Why the index rows cannot use LdA/LdB/LdD's mvin ids
[M] Every mvin funct selects a per-id DRAM row stride, scale and block stride in LoadController
(`strides/scales/block_strides = Reg(Vec(load_states, ...))`, LoadController.scala:33-36, `state_id` from funct at :61-64; `load_states = 3`,
GemminiConfigs.scala:193). [M] The software always configures all three before a loop (`gemmini_extended3_config_ld` ids 0, 1, 2 for A, B, D,
gemmini.h:760-762), and LdA/LdB/LdD emit LOAD_CMD/LOAD2_CMD/LOAD3_CMD (LoopMatmul.scala:75, 189, 292). Index rows need a 16 B DRAM row
stride (tiles are packed contiguously), so any of the three ids would clobber the A, B or D stride (D is the bias, now needed). [M]
The `state_id` field of config_ld is 2 bits (GemminiISA.scala:107) but `load_states = 3` and the id comes from the mvin funct, so a 4th id needs a
4th funct anyway. Rejected: index in DRAM with B's row stride (padded, 4x line traffic [E]); a 4th configurable id (resizes Vec in
LoadController and RS for NM builds, more Berkeley lines, one more config_ld the software must remember).

#### 2.5.2 Encodings (all custom-3 / XCUSTOM_ACC, R-type, funct3 = 0x3, xs1 = xs2 = 1, xd = 0)
Funct collision check [M]: Berkeley uses 0-25 and 126 (GemminiISA.scala:8-39, 62); the cisc-gemmini opcodes 10-17 (GemminiISA.scala:52-61) are an
unused separate decoder; Fix A uses 26 (:41); `grep` of src/, libgemmini, gemmini-rocc-tests/include (2026-11-12) finds no use of 27 or 28.

| funct | name | rs1 | rs2 |
|---|---|---|---|
| 27 | `LOAD_IDX_CMD` (mvin of index rows, fixed config) | DRAM byte address of the first index row | `MvinRs2` layout: [63:48] rows (1..16), [47:32] cols (must be 16), [31:0] spad row address |
| 28 | `LOOP_WS_CONFIG_NM` | `idx_dram`: DRAM byte address of index tile 0 of this loop (non-zero, 16 B aligned) | must be 0 |
| 8 | `LOOP_WS`, new bit | **rs1[3] = nm_sparse** (free today: used rs1 bits are [0], [1], [2], [15:8], [19:16], LoopMatmul.scala:1081-1112) | unchanged |

LOAD_IDX semantics: identical to an mvin (LOAD_CMD) with these constants, selected by funct and not stored in any config register: DRAM
row stride 16 B (the `rows` rows are contiguous, `rows*16` bytes), scale = identity, no shrink, pixel repeats 1, block stride DIM. One mvin
therefore reads `rows*16` contiguous bytes, i.e. `g = floor(16/R)` whole index tiles (g = 4 for 2:4, 2 for 4:8 = 12 rows). It is an ld-queue command
like LOAD3 (RS dst range = `rs2[31:0] .. + rows`), and is legal from the CPU too (used by tests). The scale constant must equal the bit
pattern `scale_t_to_scale_t_bits(MVIN_SCALE_IDENTITY)` produces for the chip's `mvin_scale_t` [E; RTL agent confirms, check C6].
Why it cannot be a Fix A rd value: funct 26 rd == 3 is "reserved" in Fix A and funct 26 commands bypass the RS (rd 0/1) or enter the ex queue
(rd 2); an mvin must enter the ld queue and the DMA path, so it needs its own funct [E].

LOOP_WS_CONFIG_NM is a loop config command like funct 9-13/24/25: it must be added to `is_loop_config_cmd` (LoopMatmul.scala:983-984) and to the
config `switch` (:1043-1080), storing `idx_dram` in `loop_being_configured`. LOOP_WS rs1[3] is latched into `loop_being_configured.nm`.
A `nm_cfg_seen` bit (set by funct 28, cleared at LOOP_WS) ties the two together (assert, 2.5.6).

Instruction sequence for one sparse loop (bias optional; software also keeps the Fix A prerequisites):
`gemmini_nm_reset(); config_ex(sparse=1, A_stride=1); config_ld ids 0,1,2 (as today); LOOP_WS_CONFIG_BOUNDS (original K tile count, even);
ADDRS_AB; ADDRS_DC (D = bias or NULL, C); STRIDES_AB; STRIDES_DC; LOOP_WS_CONFIG_NM(idx_dram, 0); LOOP_WS(rs1[3] = 1, ...)`.
CPU cost +1 RoCC command per loop (funct 28) versus a dense loop. No `config_ld` for the index.

#### 2.5.3 Load path, ordering, and why it cannot deadlock or reorder [M] cites, [E] argument
- New FSM `LoopMatmulLdIdx` (copy of LdB structure) emits LOAD_IDX_CMD into `unrolled_cmd`. The existing arbiter is `Arbiter(5)` with fixed priority
  (in(0) stC, in(1) ex, in(2) ldD, in(3) `ldab_arb.out`, in(4) stC_spad; LoopMatmul.scala:960-964); `ldab_arb` is a WeightedArbiter between only A and B
  (:943-957). LdIdx is **not** added to `ldab_arb` (it would perturb the A/B weighting; untouched) but is a new `arb` input (arb becomes `Arbiter(6)`)
  placed **above** `ldab_arb` (priority between ldD and ldab) so it is never starved behind a long A/B stream. It cannot starve A/B because it
  self-throttles: it issues only while `u_idx_issued <= u_B_issued + g` (at most one mvin ahead of LdB; at most R*g rows = 16 rows per mvin).
- RS ordering is by address, not by mvin id: a load entry depends only on older ld/ex entries whose dst/src ranges overlap (RS deps_ld/deps_ex,
  ReservationStation.scala:351-375; dst range from `rs2[31:0]` for LOAD/LOAD2/LOAD3, :276-282). The index region is disjoint from the A region, the
  B region (asserted, 2.5.4), and from the accumulator (different address space; bias lives there), so an idx mvin has no RAW/WAR edge with any
  LdA/LdB/LdD mvin or with computes. Its only edges: RAW into the Fix A LOAD that reads it (ex queue, younger), and WAR against the Fix A LOAD of the
  loop two loops earlier that read the same rows (older, in ex queue). All edges point to program-order-older entries, so no cycle (same argument as
  H2/H10) [E].
- Because LOAD_IDX is a plain load-queue command the `ld_utilization` counter (:973) counts it (add `ldIdx.io.cmd.fire`), `rob_overloaded`
  throttles it like LdA/LdB (:998-1001), and `io.ld_completed` (RS `matmul_ld_completed`) balances it, as for LdD.
- The ex FSM emits the Fix A LOAD (funct 26 rd 2) under the unchanged section 1.5 rule; its gate "covering mvin issued" now reads LdIdx's
  `u_idx_issued` counter (the same counter used for throttling), so the RS always has the producer mvin allocated before the LOAD (RAW seen).
- Reordering: LOAD_IDX commands of one loop are issued by one FSM in tile order; the RS may complete them out of order but the Fix A LOAD
  waits (RAW) for the rows it reads, and tiles enter the FIFO in LOAD program order (Fix A section 4), so order of arrival of data is irrelevant [E].
- Two concurrent loops: loop n+1's LdIdx may start before loop n's ex is done (like LdA/LdB); its region is the other half of the scratchpad (2.5.4),
  so no overlap with loop n's index rows [E].

#### 2.5.4 Scratchpad reservation (replaces the 1.3 "index region just below B")
[M] Berkeley halves the scratchpad per loop: `a_addr_start = i*max_addr/2`, `b_addr_end = (i+1)*max_addr/2` (LoopMatmul.scala:1296-1297;
B start = `b_addr_end - max_k*max_j*DIM`, :387). max_addr = 16384 rows (4 banks x 4096), half = 8192 rows = 2 banks.
For a sparse loop (kb = max_k/2, n_tiles = kb*max_j, idx_rows = n_tiles*R):
- index region = rows `[b_addr_end - idx_rows, b_addr_end)` (top of the loop's half, so it ends on a bank boundary);
- B region = `[b_addr_end - idx_rows - kb*max_j*DIM, b_addr_end - idx_rows)` (LdB and ex both use `b_addr_end_eff = b_addr_end - idx_rows`);
- A region unchanged, `[a_addr_start, a_addr_start + max_i*max_k*DIM)` (A keeps the original max_k, layout of 1.3).
Because idx_rows <= 4096 is asserted and the region ends on a bank boundary (multiples of 4096), it lies in one bank, satisfying the Fix A
LOAD bank rule for every n <= 4 sub-range. Bias is in the accumulator (`acc` address space, LoopMatmul.scala:1115 `ld_d_addr_start`, :1115, :1209), so it cannot
collide with the index region [E]. Software tiler must satisfy `max_i*max_k*DIM + kb*max_j*DIM + idx_rows <= 8192` (asserted in RTL and Spike).
Per-tile cost: 2:4 R = 4 rows per 32 original K rows x 16 cols weight tile => +4 rows per 16 weight rows (+25% spad rows of the B region); 4:8 R = 6 (+37.5%).
Tiles per loop shrink accordingly: this is a tiler constraint, not a bug [E].

#### 2.5.5 Controller rules (replaces the 2.3 rule; same location Controller.scala:274-285)
On `raw_cmd`: `LOOP_WS.rs1[3] == nm_loop_sparse` (both ways); LOOP_CONV_WS in sparse mode stays fatal. The program-order model after the unroller
(Controller.scala:579+) polices loop-generated LOAD/mvin traffic unchanged (P1..P5 asserts). New sideband bit from LoopMatmul to the Controller
(`nm_loop_first_load`, true on the first LOAD of a sparse loop) lets the Controller require `q == 0 && !in_flight` at that point [E; implementation detail
left to the RTL agent but the assert is required].

#### 2.5.6 Illegal use and sim-time asserts (new; all messages start with the feature name "sparse-loop-fix:"; Spike aborts with the same text)
| # | condition | message |
|---|---|---|
| N1 | LOOP_WS rs1[3] != config_ex rs1[10] mode | `sparse-loop-fix: LOOP_WS nm flag (rs1[3]) differs from n:m sparse mode (config_ex rs1[10])` |
| N2 | LOOP_CONV_WS while sparse mode on | `sparse-loop-fix: LOOP_CONV_WS issued while n:m sparse mode (config_ex rs1[10]) is on` |
| N3 | LOOP_WS rs1[3] = 1 with no LOOP_WS_CONFIG_NM since the previous LOOP_WS | `sparse-loop-fix: LOOP_WS with rs1[3] set needs LOOP_WS_CONFIG_NM (funct 28) first` |
| N4 | LOOP_WS_CONFIG_NM seen, LOOP_WS rs1[3] = 0 | `sparse-loop-fix: LOOP_WS_CONFIG_NM (funct 28) without LOOP_WS rs1[3]` |
| N5 | funct 28: rs1 == 0 or rs1[3:0] != 0 or rs2 != 0 | `sparse-loop-fix: LOOP_WS_CONFIG_NM needs a non-zero 16-byte aligned rs1 and rs2 == 0` |
| N6 | sparse loop with odd K tile count or pad_K != 0 | `sparse-loop-fix: sparse loop needs an even K tile count and pad_K == 0 (K % 2*DIM)` |
| N7 | sparse loop with A_transpose, B_transpose, is_resadd, low_D, or spad_only | `sparse-loop-fix: sparse loop does not support transposes, resadd, low_D or spad-only` (bias with full-width D is legal) |
| N8 | A_stride (config_ex rs1[31:16]) != 1 at a sparse LOOP_WS | `sparse-loop-fix: sparse loop needs A_stride == 1` |
| N9 | A + B + index regions exceed the loop's half of the scratchpad, or idx_rows > 4096 | `sparse-loop-fix: A, B and index regions do not fit in the loop's scratchpad half (or index region exceeds one bank)` |
| N10 | sparse loop started with index tiles pending (q != 0 or in_flight) | `sparse-loop-fix: sparse loop started with index tiles pending in the FIFO: gemmini_nm_reset() first` |
| N11 | funct 27 on a dense build (Spike dense lib only, no RTL assert; changelog 2026-11-13 D1) | `sparse-loop-fix: LOAD_IDX (funct 27) on a dense build (nm_sparsity = None)` |
| N12 | funct 27 with cols != 16 or rows == 0 or rows > 16 | `sparse-loop-fix: LOAD_IDX needs cols == 16 and 1..16 rows` |
| N13 | funct 27 local address is an accumulator address or GARBAGE or outside the scratchpad, or address + rows > scratchpad rows (changelog 2026-11-13 D4) | `sparse-loop-fix: LOAD_IDX destination must be a scratchpad row address` |
| N14 | funct 28 on a dense build (Spike dense lib only, no RTL assert; changelog 2026-11-13 D1) | `sparse-loop-fix: LOOP_WS_CONFIG_NM (funct 28) on a dense build (nm_sparsity = None)` |
| I1 | (internal, never in a legal run) ex emits a LOAD between a preload and its compute | `sparse-loop-fix: internal: LOAD between a preload and its compute` |
| I2 | (internal) ex emits a LOAD before its covering index mvin was issued | `sparse-loop-fix: internal: LOAD before its index mvin was issued` |
| I3 | (internal) loop ends with `loaded != n_tiles` or the FIFO budget gate disagrees | `sparse-loop-fix: internal: loop finished with undelivered index tiles` |
N2 replaces the LOOP_CONV_WS half of the existing Controller.scala:281 message (the LOOP_WS half is replaced by N1). Existing Fix A messages
(P1 budget, P3, ...) keep firing for loop-generated LOADs. N9/N6/N7/N8 are checked at LOOP_WS decode in LoopMatmul (they need the fully
configured loop); N1-N5, N10 in Controller (N11, N14 Spike only, D1); N12/N13 where LOAD_IDX is dispatched (Controller, like the Fix A funct 26 checks).

#### 2.5.7 Dense chips and compatibility
Dense chips (`nm_sparsity = None`): new fields, FSM, constants muxes and functs are not elaborated; dense Verilog must stay identical (checked in
6.3). Functs 27/28 on a dense build hit N11/N14 in Spike only (D1). NM chips running dense code: rs1[3] = 0 and no funct 27/28, behaviour identical. Fix A per-tile software
unchanged. A stock Berkeley chip never sees these functs.

## 3. Hazards and deadlock analysis

H1. **FIFO depth 4 (meta FIFO).** Budget rule in 1.5 keeps `q + in_flight + n <= 4` at every LOAD in program order.
Initial LOAD(4) is legal because q = 0. The loader reserves a FIFO slot per tile and waits if the FIFO is full, so
pending LOADs never block operand reads. No tile is ever more than 4 ahead, so Controller assert "more than 4 index
tiles ahead" cannot fire for a legal loop. Verified by construction only [E]; sim asserts are the check.

H2. **RS in-order ex queue / P5.** LOAD is an ex-queue command (Fix A section 8). The loop emits it only after a
compute and before a real preload, so it is never between a preload and its compute (P5). Its RAW source is the LdIdx
mvin in the ld queue. Cycle check: ld queue order is [A/B/idx mvins of loop n, then loop n+1's]; ex queue order
[LOAD, pre, comp...]. Edges: LOAD(ex) waits for idx mvin (ld); idx mvin of loop n+1 may WAR-wait for the LOAD of loop
n that reads the same rows (ex, earlier in program order); mvin A/B of loop n+1 WAR-wait for computes of loop n (ex,
earlier). All wait edges go from a later program-order command to an earlier one or from a LOAD to its producer mvin,
which is earlier in program order too, so there is no cycle provided the producer mvin is *allocated* before the LOAD
(the `ex` gate of 1.4/1.5 guarantees this) and the RS has room. [E] argued on paper only.

H3. **Head-of-line blocking.** A LOAD at the ex-queue head waits for its mvin to complete (DRAM round trip) and blocks
the following preload even though that preload's own tile may already be in the FIFO. Mitigation: LdIdx runs one mvin
ahead of LdB (1.4), and the rolling LOAD is emitted >= 2 tiles ahead, so the producer mvin was issued tens to hundreds
of cycles earlier. First LOAD of a loop has no slack but overlaps the loop's first A/B mvins. Residual start-up cost
[E] one DRAM latency (~100-200 cycles) per loop, comparable to Berkeley's own first-mvin latency.

H4. **RS capacity.** Each LOAD takes an ex entry and each idx mvin an ld entry; both counted in the unroller's
utilization counters (`ex.io.cmd.fire` already; add `ldIdx.io.cmd.fire` to `ld_utilization`). `ex_completed` for the
LOAD must be reported to the unroller; check that the RS routes completion of `from_matmul_fsm` LOADs to
`matmul_ex_completed` (underflow assert at line ~977 would catch a mismatch). Open check C1.

H5. **Two concurrent loops.** Only one loop's `ex` runs at a time, in order, so index tiles of loop n+1 enter the FIFO
after those of loop n; q accounting is global program order and is back to 0 at the end of each sparse loop (all tiles
popped). Index regions are per loop half, so loop n+2 reuses loop n's region: RS WAR on the LOAD's operand rows
protects it (Fix A section 4), the stale-read exclusion (index rows written by a matmul C output) does not apply.

H6. **Mode latch.** Each real preload latches sparse with its weight buffer; GARBAGE preloads (i > 0) pop nothing and
do not update the latch (already so). Dense loop right after a sparse loop needs `config_ex` sparse off first, and
all tiles consumed (q = 0): satisfied by loop completion; software must fence or at least issue config_ex after the
loop's last command (it does, it is in program order).

H7. **A_stride / a_hi.** The loop writes A with row stride 1 per tile, matching "a_hi rows always 1 apart"; a_lo uses
`A_stride` from config_ex (software sets 1). If software set another stride the loop's layout would mismatch: assert
`A_stride == 1` when `loop_nm` (software side) and note in header.

H8. **Padding.** v1 requires even K tile count and pad_K = 0, pad_I/pad_J as Berkeley (rows/cols of C edge, handled by
a_rows / b_cols / c_* existing fields). Sparse compute passes `a_rows` for rs2.num_rows, not `block_size`.

H9. **Existing quirk to re-check.** `ldb_ahead` (line ~457) compares `io.ld_ka === k` for a B condition, which looks
like a Berkeley copy-paste quirk. With the halved B iterator it must be reviewed (it is conservative or wrong
depending on lda/ldb relative progress). Open check C2; the RS RAW check keeps correctness either way, the gate only
affects overlap.

H10. **Deadlock from RS full.** `LOAD`s wait in the RS holding entries while A/B mvins queued behind them cannot enter
(RS full). Because LOAD is emitted only after its mvin is *allocated*, and the mvin is older, the older command can
always complete (its own deps are older commands). Same argument as Berkeley's own loop. [E]

H11. **Bias vs index (new, 2026-11-12).** [E] Bias is mvin3 (id 2, config_ld stride D) into the accumulator; index rows are funct 27 into the scratchpad with
no config state. Different funct, different address space, different config: no hazard and no shared stride. A sparse loop with bias has the same LdD traffic as a dense one.
H12. **Arbiter starvation / priority (new).** [E] LdIdx above `ldab_arb` in `Arbiter(6)` (2.5.3) with its self-throttle `u_idx_issued <= u_B_issued + g`; a mutant that
removes the throttle must fail by starving A/B or by tripping the budget (6.3).
H13. **LOAD_IDX vs ld queue capacity (new).** [E] It takes ld RS entries (counted in `ld_utilization`); worst case g-tile mvins ahead of LdB = 1 mvin, so at most
1-2 extra ld entries beyond a dense loop.
H14. **Second concurrent loop, index region (new).** [E] Loop 0's index region is the top of rows [0, 8192), loop 1's the top of [8192, 16384): disjoint. Loop n+2 reuses loop n's
rows; WAR is protected by the RS against the Fix A LOAD of loop n (as H5).

## 4. Spike changes (libgemmini gemmini.cc / gemmini.h)

Spike models `loop_ws` (gemmini.cc:870) functionally by calling its own mvin/preload/compute handlers. Needed:
0. [M, read gemmini.cc:870-1010] Spike's `loop_ws` is not a pipeline model: it walks k, j, i and issues the A mvin at j == 0
   and the B mvin at i == 0 just in time, then preload/compute. It computes `B_sp_addr_start = BANK_NUM*BANK_ROWS/2 - K*J*DIM`
   (or the upper half for `b_spad_id == 2`) and aborts when `(I*K + K*J)*DIM > half the scratchpad`. For a sparse loop
   the bound becomes `(I*K + (K/2)*J)*DIM + (K/2)*J*R <= half`, B start uses K/2, and the index region sits just
   below B (same derivation as 1.3), so Spike and RTL agree on the layout the software tiler must respect.
1. `nm_forbid_loop(..., "LOOP_WS")` (gemmini.cc:871): replace by the section 2.3 rule (flag == mode; LOOP_CONV_WS still
   forbidden). New abort texts equal the RTL assert text.
2. Decode `rs1[3]` in `loop_ws`; store `loop_ws_nm` and use `loop_ws_D` as `idx_dram`; abort on illegal combos of 2.1
   (transposes, low_D, resadd, odd K, pad_K != 0, A_stride != 1, D stride != 0, idx_dram == 0 or unaligned).
3. In the sparse branch: B loop over max_k/2 K tiles; compute loop k' calls the existing sparse compute with a_lo =
   tile(2k'), a_hi = tile(2k'+1) (existing path already handles rs2 = a_hi, gemmini.cc:588-630).
4. Index: Spike has no cycle model, so emulate the rolling policy of 1.5 exactly: at the start, mvin index tiles into the
   derived region (the same mvins LdIdx issues, mvin id 2) and perform LOAD(n = 4); after the last compute of tile u
   with `loaded - (u+1) <= 2`, perform LOAD(n = min(2, remaining)); each LOAD is the existing `nm_meta_load_spad` (mvin of index rows into the derived region, then LOAD with the same
   rolling n), reusing `nm_meta_load_spad` (gemmini.cc:799-861) so every Fix A abort (budget, bank, P1..P5) also fires
   for loop-generated traffic. The derived region and the bank/collision asserts are checked in Spike too.
5. Keep `nm_ld_since_clear` semantics: loop LOADs set it (P3: a register-path PUSH after a loop needs a CLEAR; same as after
   a software LOAD).
6. Tests (section 6) must run on the *mutants* too (section 6.4). ~120 lines of C++ [E].

7. [E] New `LOAD_IDX_CMD` (funct 27) handler: an mvin with constants (row stride 16 B, scale identity, no shrink) into the scratchpad model; aborts N11-N13 text. Dense
   Spike build (`nm_sparsity` absent) aborts with N11. Funct 28 handler: stores `idx_dram`, sets `nm_cfg_seen`; N3-N5, N14.
8. [E] `loop_ws` sparse branch: replace the `loop_ws_D` reuse of the v1 text by `loop_ws_idx_dram` from funct 28; D/bias keeps its dense behaviour; region layout
   of 2.5.4 (B end = `b_addr_end - idx_rows`); abort N6-N10 with the RTL text. Index mvins are performed with the LOAD_IDX handler (same group size g, same
   rolling LOAD policy of 1.5).
9. [E] `nm_forbid_loop` for LOAD/PUSH interplay unchanged; N10 uses Spike's existing `q`/`in_flight` model.
10. [E] Spike gains no timing: I1-I3 (internal) and the arbiter-priority / throttle behaviour are RTL-only.

Spike must match the RTL on a deliberately illegal loop: Spike has no timing, so the checks to mirror are only the
legality ones; P4 and in-flight C-output hazards stay unmodelled as in Fix A.

## 5. Expected benefit

### 5.1 CPU instructions removed per layer
Measured baseline [M]: Spike instruction counts (`fix-a-sw.md` Step 4; CPI 1 so instructions = timed-region cycles),
keeper tiler Fix A (`sparse_fixa`), 2:4 / 4:8: edge 2,469 / 2,538; small 7,743 / 7,876; bert_qkv 287,902 / 292,515;
rn50_conv 488,259 / 497,480; bert_ffn1 1,153,201 / 1,171,638; bert_ffn2 1,120,035 / 1,138,472. Index-LOAD savings
already taken by Fix A (push -> LOAD) were 13.7-21.8 instr per tile [M]; remaining per tile is ~190-250 instructions
(qkv: 287,902/1152 real preloads = 250, includes A/B mvins and the garbage preload/compute pairs of the i loop).

[SUPERSEDED by the measurement below for the Berkeley-dense numbers; kept as history] Fix B per layer [E]: CPU issues config (about 6-8 RoCC commands per `LOOP_WS`, plus address arithmetic and the one-time
`config_ld`s) per loop call. Assuming 40-100 instructions per call and tiled_matmul_auto-style tiling into 4-30 calls
per layer, the CPU cost is about 0.2-3k instructions per layer for all the layers above, i.e. >99% of the issue
instructions are removed (qkv: ~286k of 288k; ffn1: ~1.15M of 1.15M). The number of calls is the main uncertainty; no
Berkeley instruction count is recorded in the logs ([M] only `cpu_issue_done` is, which includes the final fence and
is therefore not an instruction count), so Berkeley's own dense Spike instret should be measured first (cheap, Spike
only) [Q3].

**Measured (Q3, 2026-11-12) supersedes the estimates above for Berkeley's dense loop.** [M] Spike instruction counts of Berkeley's dense `tiled_matmul_auto`
(the call of the `berkeley` variant of stream_bench.c, WS, int32 C, no bias; dims at run time), run folder
`experiments/streaming/investigate/runs/20261112-205136-q3-spike/`, all verified; worklog `experiments/streaming/worklogs/fixb-q3-spike.md`.
Values from `rt/logs/<layer>.log:4` (instret) and `rt/logs/<layer>.trace.txt:4` (LOOP_WS calls = funct7 8 count, RoCC commands):

| layer | instret | LOOP_WS calls | RoCC cmds | vs Fix A 2:4 keeper count above (removed) |
|---|---|---|---|---|
| edge | 397 | 1 | 11 | 83.9% |
| small | 463 | 1 | 11 | 94.0% |
| bert_qkv | 3,209 | 20 | 125 | 98.9% |
| rn50_conv | 4,827 | 36 | 221 | 99.0% |
| bert_ffn1 | 11,994 | 78 | 473 | 99.0% |
| bert_ffn2 | 10,051 | 80 | 485 | 99.1% |
The percentages are (1 - dense instret / Fix A count) recomputed from these logs and the Fix A counts quoted above (verified 2026-11-12). The old assumption
(40-100 instr and 4-30 calls per layer, 0.2-3k per layer) was too low for the big layers: measured 126-160 instr per call on the multi-call layers and
up to 80 calls (ffn1 11,994 = 4x the old upper bound). ">99% removed" holds for rn50_conv and ffn2 (99.0%, 99.1%); qkv and ffn1 are 98.9% and 99.0%,
small 94.0%, edge 83.9%. The conclusion (issue cost nearly gone on big layers; edge and small keep a visible CPU share) stands.
Fix B's own count stays [E]: a sparse call adds one RoCC command (funct 28) and may split tiles differently (index region, 2.5.4), so expect somewhat more calls
and 1-2% more instructions per call than the dense numbers [E]. Spike counts instructions, not Rocket cycles; compiler gcc 16.1.0 -O2 (run.info in the run folder).
A sparse loop with bias issues the same LdD bias path as dense; the Berkeley number above has no bias.

### 5.2 Cycles
The CPU removal only matters if the hardware, not the CPU, becomes the limit. Berkeley dense hardware counters
[M] (`analytics-check/recollect-20261109-144252/stock.*.seed1.log`, `berkeley` line):

| layer | total | ex_active | rdma_active | ex/total | rdma/total | loop_matmul_active |
|---|---|---|---|---|---|---|
| edge | 4,304 | 1,756 | 1,592 | 41% | 37% | 2,996 |
| bert_qkv | 316,791 | 291,727 | 212,334 | 92% | 67% | 315,280 |
| rn50_conv | 661,605 | 562,519 | 534,192 | 85% | 81% | 659,974 |
| bert_ffn2 | 1,761,377 | 1,418,461 | 1,522,905 | 81% | 86% | 1,759,921 |

(`loop_matmul_active` is ~total for Berkeley: the unroller is busy the whole run, the CPU is not the issue; dense
per-tile streaming shows 22-77k.) A sparse tile halves the number of computes (ex_active about halves) and cuts the
weight bytes by ~50% (index +6% to +9% of dense weight bytes for 2:4 / 4:8: 64 B or 96 B per 16x16 weight pair).
A bytes are unchanged. Hence [E]:
- qkv (array-bound): ex ~146k, rdma ~200k, total ~215-260k => 1.2-1.45x vs Berkeley dense (317k), 1.5-1.85x vs
  Fix A keeper (401,522).
- rn50_conv and ffn (DMA-bound, rdma 81-86% of dense time, only B bytes shrink): 1.05-1.25x vs Berkeley.
- small and edge (latency / startup dominated, ex 41% on edge): 0.95-1.1x vs Berkeley; they will not beat it much and
  that is acceptable (`edge` Fix A keeper already 0.86x).
Overall estimate: **about 1.0-1.45x faster than Berkeley dense, 1.2-1.85x faster than the current Fix A software path,
bigger layers better**. All of this is [E]; it assumes the loop path reaches Berkeley's overlap quality, which only a
simulation can show. 4:8 should land within a few percent of 2:4 (same compute count, +50% index bytes of a ~6-9%
share).

## 6. Cost

### 6.1 Files / regions
| file | region | size [E] |
|---|---|---|
| LoopMatmul.scala | state/req bundles (+nm, idx_dram), LdB halving + `b_addr_end_eff`, Execute (k' loop, a_hi, LOAD state, ahead gates), StC bounds, new `LoopMatmulLdIdx` (funct 27, priority above ldab), arb 5 -> 6, utilization counters, config decode (funct 28, `rs1[3]`), region layout + N6-N9, I1-I3 | 280-380 lines |
| GemminiISA.scala | funct 27, 28 | ~3 |
| LoadController.scala, ReservationStation.scala | funct 27 constants mux (stride 16 B, identity scale, block stride, pixel repeats) and load-queue decode; NM builds only | ~15-25 |
| Controller.scala | N1-N5, N10-N14 asserts, `nm_cfg_seen`, `nm_loop_first_load` sideband, a_stride tracking (N8), replace assert at 274-285 | ~50-70 lines |
| ExecuteController.scala | none expected (check C1 for completion routing) | 0 |
| libgemmini gemmini.cc/.h | section 4 (items 0-10, funct 27/28 handlers) | ~160 lines |
| gemmini-rocc-tests include/gemmini.h or gemmini_nm.h | `gemmini_loop_ws_nm` (funct 28 + rs1[3]), `gemmini_nm_load_idx` (funct 27), `tiled_matmul_nm_loop()` with bias support, tile sizing that reserves the index region and requires even K, K-padding helper | ~170 lines |
| tests | `bareMetalC/nm_sparse_loop.c` (+ one NEG build per row N1-N14, incl. bias positive case), `nm_load_idx.c`, stream_bench variant `sparse_loop`, fair_perf variant | ~500 lines |
| run-flow.sh / verification scripts | add the new tests and NEG messages | small |

### 6.2 Area and timing risk [E]
Area: LdIdx ~ same as LdB (an address counter set and 3-4 16-bit iterators) plus the ex LOAD state and 2 counters:
low hundreds of flops and a few hundred LUT-equivalents; against the 4 x 512/768-bit FIFO already added by Fix A it is
negligible. Elaborated only for NM builds. Timing: the loop FSMs are not on the array's critical path; new risk is the
extra multiplier chains (`(k*max_j + j)*R`, `loaded*R`) in the ex address path and the 6:1 arbiter. Mitigate with a
constant-R shift/add (R = 4: shift; R = 6: x4 + x2) and registered address counters (`u` increments by 1, address by R).
Medium-low risk; synthesis was not run, so area/timing remain unmeasured.

### 6.3 Verification plan
1. Spike model + unit tests (no RTL): unchanged dense LOOP_WS regression (all 56 bareMetalC from Fix A matrix) + new
   `nm_sparse_loop` positive tests: 2:4 and 4:8; I x J x K shapes covering max_i 1 and >1, max_j 1 and >1 (mvin blocks),
   odd/even tile counts T (so n = 1 tails), T < 4, T = 4, T > 4, index region at bank edge, two back-to-back loops
   (concurrent loops, both halves), loop followed by a dense loop and by a per-tile sparse sequence, full-range int8,
   CPU reference as in `nm_sparse_spad.c`.
2. NEG builds, one per assert, N1-N14 of 2.5.6 (each must abort in Spike with the RTL message and in RTL with the same assert; N11/N14 on a dense build): N1 both ways, N2, N3, N4, N5 (three variants: zero, unaligned, rs2 != 0), N6 (odd K, pad_K), N7 (one build per option), N8, N9 (collision; over-4096 rows), N10 (PUSH tile pending before the loop), N11-N14. Positive cases additionally: sparse loop with bias (full-width D, repeating bias and per-row bias), without bias. Plus RTL-only internal asserts I1-I3 and Fix A budget overflow (never fire in positive runs; each gets a mutant that must trip it: I1 LOAD emitted mid preload/compute, I2 LOAD without the issued-gate, I3 a LOAD count off by one; removing the `loaded - pre <= 2` gate must trip the Fix A budget assert, proving the check is live).
3. Mutants (`make_mutants.sh` style; Spike and RTL where applicable): wrong a_hi base, K not halved in StC, LOAD without RAW gate (idx mvin not yet issued),
   LdIdx throttle removed, idx stride 4:8 as 8 rows, funct 27 row stride 32 instead of 16 (index garbage), LdIdx emitting LOAD3 (bias stride collision: must fail the bias positive test),
   index region overlapping B (N9 removed), LdIdx at lowest arbiter priority (must show as a timeout or a large cycle regression, not a wrong result: run with a sim timeout), `nm` flag not latched. Each must fail the positive matrix.
4. Elaborate GemminiNMRocketConfig and GemminiNM48RocketConfig (and the stock chip with `DENSE_ONLY`, check generated
   Verilog diff of the dense/stock config is empty modulo names), Verilator build on the server (see memory: ai-1769,
   VPN), run: all nm_* tests incl. NEG, streaming benches with a new `sparse_loop` variant per layer/pattern (the
   12-layer grid used for Fix A, seeds 1-3), fair_perf. Compare the cycle table with section 5.2 predictions.
5. Fresh-eyes review round of RTL + software as for Fix A (`fix-a-review.md` found M6-type issues; budget one round).

### 6.4 Hours (agent working time, excluding user waiting) [E]
| item | hours |
|---|---|
| RTL implementation (LoopMatmul, Controller, LoadController, ReservationStation, ISA) | 12-17 |
| Spike | 6-8 |
| Software tiler/header + tests + NEG (14 builds) + mutants | 12-16 |
| Review round + fixes | 6-8 |
| Elaboration, Verilator builds (2 configs, ~1-2 h each incl. waiting) | 3-5 |
| Server runs and collection (98-job grid took ~8 h wall for Fix A; sparse_loop only: ~4 h wall) | 4-6 (wall 6-10) |
| Analysis + paper numbers | 3-4 |
Total about 46-64 agent hours (was 40-55 before the bias/funct 27 revision, [E]); with parallel agents (RTL, Spike, SW) and the serial server stage the wall time is
about 3-4 days. Today is Thu 12 Nov; paper due Mon 15 Dec (33 days), so the schedule fits with ~2 weeks margin even
with one failed server round. Recommended gate: decide by ~Mon 16 Nov so results exist by ~Fri 4 Dec.

## 7. Alternatives considered
| | design | verdict |
|---|---|---|
| A | **do nothing** (Fix A only) | Sparse stays 0.78-0.96x of Berkeley stock; paper claim is "beats per-tile dense, not Berkeley". Zero cost. |
| B | software-only command batching (tune the keeper tiler: fewer instructions per RoCC command, unroll, precomputed addresses, hoist `config`/address math) | no RTL risk; measured keeper Fix A already shows ~190-250 instr/tile, a hand-tuned rewrite might get -20..-40% instructions [E], leaving it CPU-bound; could close maybe half the gap on qkv; cheap (6-10 h) but cannot reach Berkeley-class loop issue. Worth doing regardless as a fallback. |
| C | simpler sparse-only loop: a new funct `LOOP_NM_WS` and a new standalone unroller module (no changes to the five Berkeley FSMs) | isolates dense risk completely and is easier to reason about (own pacing, no `rs1[3]`), but duplicates LdA/LdB/ex/StC logic (~2x the lines, extra flops for state, and needs its own 2-loop double-buffering and arbiter port) and a second implementation of the RS/utilization handshakes. Consider if review finds the in-place change too invasive; est. +10 h and +area. |
| D | macro command "sparse tile": one new RoCC command = real preload + max_i computes (i loop in hardware), CPU still issues mvins | cuts ~70-85% of issue instructions per tile with very little RTL (inside ExecuteController, not the loop); leaves A/B/idx mvin issue to the CPU (still ~20% of today's instr). Middle path: ~half the benefit at ~40% of the cost [E]; but touches ExecuteController FSM (high-risk area per Fix A). |
| E | index stored interleaved with weights in B DRAM so LdB's mvin brings both | removes LdIdx and the D slot reuse, but needs a spad layout change in B and a new split of the B mvin (rows of different widths) and changes the Fix A format contract; rejected for v1. |
| F | index loaded by preload (Fix A alt B) | rejected in Fix A. |

## 8. Open questions and user decisions
User decisions of 2026-11-12 (recorded; do not re-argue):
- [Q1] DECIDED: bias IS needed in sparse loops. The v1 design (index tiles through the D DRAM slot / mvin3) is rejected. Design adopted: section 2.5
  (funct 27 `LOAD_IDX_CMD` fixed-config index mvin, funct 28 `LOOP_WS_CONFIG_NM`, LOOP_WS rs1[3]); bias keeps LdD, mvin3 and the accumulator unchanged.
- [Q2] DECIDED: yes, require K % (2*DIM) == 0 in v1; software zero-pads K (assert N6).
- [Q3] DECIDED: yes. A separate agent measures Berkeley's dense `tiled_matmul_auto` instruction counts under Spike for the six layers; results go to
  `experiments/streaming/worklogs/fixb-q3-spike.md` (placeholder in 5.1; the coordinator will pass numbers).
- [Q4] DECIDED: Fix B (go ahead) over the cheaper alternatives B (software tuning) and D (macro command).
- [Q5] DECIDED: no, the paper does not need a "faster than Berkeley dense" claim. Fix B still goes ahead. Consequence for planning only: the 5.2 speed-up
  ranges are not an acceptance threshold; acceptance is correctness (6.3) plus a measured same-build comparison (AGENTS rule 4).

Remaining decisions for the user: see "Ready to freeze?" below.

### Ready to freeze?
R1-R3 answered and the spec frozen 2026-11-12. C1, C2, C6 remain first tasks of the RTL agent (reading tasks, no user input; a finding that changes semantics needs a changelog entry):
- [x] R1. DECIDED 2026-11-12: accept the spad reserve of the index region (+4 rows per 16 weight rows for 2:4, +6 for 4:8, 2.5.4) and the smaller tiles.
- [x] R2. DECIDED 2026-11-12: CPU-issued funct 27 (LOAD_IDX) is legal outside loops; no `from_matmul_fsm` assert (as written in 2.5.2; N11-N13 apply to any source). Tests may issue it directly.
- [x] R3. DECIDED 2026-11-12: yes, OK, every added line carries `// changed: sparse-loop-fix, <why>`. (Question was: is adding two functs (27, 28) and a funct-27 constants mux in LoadController/ReservationStation (five Berkeley files touched: GemminiISA, LoadController,
  ReservationStation, Controller, LoopMatmul) acceptable under AGENTS rule 6?)
- [ ] C1 (RTL agent): LOAD's `from_matmul_fsm` bit survives the Controller path (Controller.scala:542-547).
- [ ] C2: `ldb_ahead` quirk (LoopMatmul.scala:459, `io.ld_ka === k` in a B condition) reviewed with the halved B iterator.
- [ ] C6: identity-scale bit pattern for the LOAD_IDX constant and the RS block_stride / pixel-repeat constants (2.5.2) confirmed in code.
- [ ] C3/C4 (tiler sizing, Spike second-half B start) closed by the software and Spike agents; not blockers for freezing the ISA.

## RESUME HERE
Done (2026-11-12 revision): decisions Q1-Q5 recorded (8); new ISA, load path, spad reservation, asserts in 2.5; hazards H11-H14 added; Spike items
(4 items 7-10); cost 6.1/6.4 and verification 6.3 updated; changelog entry. Superseded v1 parts are marked, not deleted.
Not verified: nothing was built or run; all [E] items are paper arguments. C1, C2, C6 open (section 8). Q3 numbers pending (worklogs/fixb-q3-spike.md).
Next: spawn RTL / Spike / software agents from 2.5, 3, 4, 6 (spec is FROZEN; C1, C2, C6 first).

## Changelog
- 2026-11-13 (5.1 correction, measured): the [E] "somewhat more calls and 1-2% more instructions per call" is contradicted by Spike. RUN3
  (`investigate/runs/20261112-235246-fixb-spike-tests/bench/`) shows sparse_loop 2:4 at about 0.45x Berkeley's instret on qkv/rn50/ffn1/ffn2
  (bert_qkv 1,451 vs 3,214). qkv trace: 16 LOOP_WS calls at ~61 instr vs Berkeley's 20 at ~148 (worklogs/fixb-icount.md). Cause: specialised
  `tiled_matmul_nm_loop` vs Berkeley's generic run-time `tiled_matmul_outer` plus tile search, and halved B allowing tile_J 6 vs 5 (inferred).
  This is code specialisation, not a sparsity gain; do not present it as one. Funct-27 index mvins are loop-issued and invisible to the CPU count.
- 2026-11-13 (user: "all as recommended", post-implementation decisions D1-D5):
  D1. N11/N14 are Spike-only. The RTL dense build generates no funct 27/28 hardware and must stay identical to stock, so it carries no N11/N14 assert;
  the dense libgemmini build (Makefile switch `NM_DENSE_BUILD`) aborts with the 2.5.6 texts. NEG tests for N11/N14 run on the dense Spike lib only.
  D2. N9's "idx_rows > 4096" part is unreachable under the other checks; kept as a defensive check, covered by a mutant, no NEG test required.
  D3. Sparse loop with B = NULL is legal; index rows are still loaded (RTL and Spike already agree).
  D4. N13 gains a range check: local address + rows must not pass the end of the scratchpad. Same 2.5.6 text, in RTL and Spike, with a NEG test.
  D5. stream_bench `sparse_loop`: the CPU-side index reorder (data prep, no mvins) is outside the timed region; index-row loads stay timed.
  Dense regression: `matmul_spad` and `mvin_mvout_spad` fail on Berkeley's stock Spike lib too (funct 23 unhandled; Berkeley's
  `bareMetalC/Makefile:70-71` excludes them on normal configs; run `investigate/runs/20261113-143811-dense-spad-stock/`). run-flow.sh uses
  Berkeley's filtered list: 54 dense tests.
- 2026-11-12 (FREEZE): user answered R1 (accept spad reserve), R2 (CPU-issued funct 27 legal outside loops, no `from_matmul_fsm` assert; 2.5.2 text already says so), R3 (five Berkeley files, `// changed: sparse-loop-fix`). Q3 measured and recorded in 5.1 (old 5.1 CPU-instruction estimates superseded by measurement for Berkeley dense; Fix B count stays [E]). Line 1 changed from DRAFT to FROZEN; no semantic change to 2.5.
- 2026-11-12: HANDOFF.md was removed from the tree; its section 5 ("Plan for the fix round", which holds the "Shared protocol spec") is now at `git show e06b436:HANDOFF.md`. Header line 6 updated to point there.
- 2026-11-12 (revision for user decisions, STATUS still DRAFT): Q1 bias needed -> v1 ISA (old 2.1: index through the D DRAM slot and mvin3, no bias) is SUPERSEDED by
  new 2.5; old 2.2 (one new funct) is adopted in the form of 2.5 (funct 28 `LOOP_WS_CONFIG_NM` + LOOP_WS rs1[3]) plus a new funct 27 `LOAD_IDX_CMD`, because all three mvin
  ids carry configured strides. Old 1.3 P5 (LdIdx used mvin3 id 2) and old 1.4 "mvin3 / config_ld id 2 / D = NULL" are SUPERSEDED (LdIdx emits funct 27;
  priority and throttle rule in 2.5.3 replace the "wins the arbiter against LdB" wording); old 1.3 layout "index region just below B" is SUPERSEDED by 2.5.4
  (index region at the top of the loop's half). Old 2.3 Controller rule is superseded by 2.5.5/2.5.6 (message prefix "sparse-loop-fix:"). Q2 decided yes (K % 2*DIM,
  assert N6). Q3 decided yes (placeholder in 5.1). Q4 decided Fix B. Q5 decided no (8). Added hazards H11-H14, Spike items 7-10, cost and verification updates.
