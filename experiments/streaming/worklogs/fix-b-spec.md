STATUS: DRAFT, not approved for RTL. Spec only; no source file was edited, nothing built or simulated.

# Fix B spec and cost estimate: N:M sparse mode inside the hardware matmul loop (LOOP_WS)

Author: spec agent, 2026-11-12 (written 11:15-11:45 EST against the working tree; Fix A and protocol changes are
uncommitted there). Builds on `fix-a-spec.md` (FROZEN) and HANDOFF.md section 5. Nothing in Fix A changes; Fix B
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
| P5 | new `LoopMatmulLdIdx` | new FSM (copy of LdB structure) that mvins index tiles, see 1.4. Joins `ldab_arb`/`arb` (arb becomes 6 inputs); counted in `ld_utilization`. |
| P6 | `LoopMatmulExecute` | new state `ldidx` between the last compute of weight tile u and the preload of tile u+1 (and before the first preload) that emits a Fix A LOAD (funct 26, rd = 2) when the budget rule of 1.5 allows. |
| P7 | Controller.scala:274-285 | relax the "LOOP_WS in sparse mode" assert (section 2.3). |
| P8 | ExecuteController.scala | **no change expected**: it already handles real sparse preload, compute with a_hi, and the LOAD diverter; the loop emits exactly the commands software emits today. |

Layout consequence (spad): A tiles keep Berkeley's `(i*max_k + k)*DIM` row-major tile layout with the original max_k,
so a_lo = tile(i, 2k'), a_hi = tile(i, 2k'+1) = a_lo + DIM (rows consecutive, matches "a_hi stride 1"). B region is
half size. Index region (new): `idx_addr_end = b_addr_start`, `idx_addr_start = idx_addr_end - n_tiles*R` where
`n_tiles = (max_k/2)*max_j`; carved just below the B region of the loop's half. RTL assert: the whole region lies in
one scratchpad bank (LOAD bank rule, Fix A section 3) and does not collide with A (`a_end <= idx_addr_start`).
Software tiler must size tiles with this reserve (section 6).

### 1.4 LdIdx (index mvin) detail
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

### 2.1 Chosen: a flag in LOOP_WS and reuse of the D slots; no new funct
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

### 2.2 Alternative (if [Q1] says bias is needed): one new funct
funct 27 `LOOP_WS_CONFIG_NM`: rs1 = idx_dram, rs2 = flags/idx spad base. It must be added to `is_loop_config_cmd`
(line 983) and the LoopUnroller range checks; the sparse flag then lives there. Costs ~10 lines more, a new CPU
instruction per call, and LdD must be told a different mvin id (only three ids exist, so bias and index would share
mvin3 stride config: not possible without a new load-config id). Not recommended for v1.

### 2.3 Controller assert (Controller.scala:274-285)
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

Spike must match the RTL on a deliberately illegal loop: Spike has no timing, so the checks to mirror are only the
legality ones; P4 and in-flight C-output hazards stay unmodelled as in Fix A.

## 5. Expected benefit

### 5.1 CPU instructions removed per layer
Measured baseline [M]: Spike instruction counts (`fix-a-sw.md` Step 4; CPI 1 so instructions = timed-region cycles),
keeper tiler Fix A (`sparse_fixa`), 2:4 / 4:8: edge 2,469 / 2,538; small 7,743 / 7,876; bert_qkv 287,902 / 292,515;
rn50_conv 488,259 / 497,480; bert_ffn1 1,153,201 / 1,171,638; bert_ffn2 1,120,035 / 1,138,472. Index-LOAD savings
already taken by Fix A (push -> LOAD) were 13.7-21.8 instr per tile [M]; remaining per tile is ~190-250 instructions
(qkv: 287,902/1152 real preloads = 250, includes A/B mvins and the garbage preload/compute pairs of the i loop).

Fix B per layer [E]: CPU issues config (about 6-8 RoCC commands per `LOOP_WS`, plus address arithmetic and the one-time
`config_ld`s) per loop call. Assuming 40-100 instructions per call and tiled_matmul_auto-style tiling into 4-30 calls
per layer, the CPU cost is about 0.2-3k instructions per layer for all the layers above, i.e. >99% of the issue
instructions are removed (qkv: ~286k of 288k; ffn1: ~1.15M of 1.15M). The number of calls is the main uncertainty; no
Berkeley instruction count is recorded in the logs ([M] only `cpu_issue_done` is, which includes the final fence and
is therefore not an instruction count), so Berkeley's own dense Spike instret should be measured first (cheap, Spike
only) [Q3].

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
| LoopMatmul.scala | state/req bundles (+nm, idx base), LdB halving, Execute (k' loop, a_hi, LOAD state, ahead gates), StC bounds, new `LoopMatmulLdIdx`, arb 5 -> 6, utilization counters, config decode (`rs1[3]`, D slot reuse), derived idx region + asserts | 250-350 lines |
| Controller.scala | assert at 274-285 | ~15 lines |
| ExecuteController.scala, ReservationStation.scala | none expected (check C1 for completion routing) | 0-10 |
| libgemmini gemmini.cc/.h | section 4 | ~120 lines |
| gemmini-rocc-tests include/gemmini.h or gemmini_nm.h | `gemmini_loop_ws` sparse variant (rs1[3], idx addr in D slot), `tiled_matmul_nm_loop()` with tile sizing that reserves the index region and requires even K, K-padding helper | ~150 lines |
| tests | `bareMetalC/nm_sparse_loop.c` (+ NEG builds), stream_bench variant `sparse_loop`, fair_perf variant | ~400 lines |
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
2. NEG builds (each must abort in Spike with the RTL message and in RTL with the same assert): flag/mode mismatch (both
   ways), LOOP_CONV_WS in sparse, transposes, low_D, odd K, pad_K, A_stride != 1, idx_dram 0/unaligned, region collides with A
   or crosses a bank, loop in sparse mode on a dense-latched buffer. Plus RTL-only internal asserts: LOAD between a
   preload and its compute, budget overflow (these must never fire in positive runs; a mutant that removes the
   `loaded - pre <= 2` gate must trip the Controller's budget assert, proving the check is live).
3. Mutants (`make_mutants.sh` style): wrong a_hi base, K not halved in StC, LOAD without RAW gate (idx mvin not yet issued),
   LdIdx lockstep removed, idx stride 4:8 as 8 rows. Each must fail the positive matrix.
4. Elaborate GemminiNMRocketConfig and GemminiNM48RocketConfig (and the stock chip with `DENSE_ONLY`, check generated
   Verilog diff of the dense/stock config is empty modulo names), Verilator build on the server (see memory: ai-1769,
   VPN), run: all nm_* tests incl. NEG, streaming benches with a new `sparse_loop` variant per layer/pattern (the
   12-layer grid used for Fix A, seeds 1-3), fair_perf. Compare the cycle table with section 5.2 predictions.
5. Fresh-eyes review round of RTL + software as for Fix A (`fix-a-review.md` found M6-type issues; budget one round).

### 6.4 Hours (agent working time, excluding user waiting) [E]
| item | hours |
|---|---|
| RTL implementation (LoopMatmul + Controller) | 10-14 |
| Spike | 5-7 |
| Software tiler/header + tests + NEG + mutants | 10-14 |
| Review round + fixes | 6-8 |
| Elaboration, Verilator builds (2 configs, ~1-2 h each incl. waiting) | 3-5 |
| Server runs and collection (98-job grid took ~8 h wall for Fix A; sparse_loop only: ~4 h wall) | 4-6 (wall 6-10) |
| Analysis + paper numbers | 3-4 |
Total about 40-55 agent hours; with parallel agents (RTL, Spike, SW) and the serial server stage the wall time is
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

## 8. Open questions for the user
- [Q1] Is bias (LdD / `D`) needed in sparse layers? v1 reuses the D DRAM slot and mvin3 for the index tiles, so a sparse
  loop cannot take a bias. BERT QKV/FFN and ResNet convs normally have one; software can add it after (extra pass) or we
  take the new-funct route of 2.2 (and still need a load id for the index: needs more thought).
- [Q2] OK to require K % (2*DIM) == 0 (pad with zeros) in v1? Real layers (768, 3072, 2048-ish) satisfy it; edge shapes get padded.
- [Q3] May an agent run Berkeley's dense `tiled_matmul_auto` under Spike for the six layers to get instruction counts (cheap, no
  server)? It turns the 5.1 estimate into a measurement.
- [Q4] Fix B vs the cheaper alternatives (B software tuning, D macro): which risk/benefit do you want before 15 Dec?
- [Q5] Does the paper need a "faster than Berkeley dense" claim? If only "area-neutral, beats equal-effort dense", Fix B may not be worth its schedule risk.

## RESUME HERE
Done (11:45 EST): everything above: design (1), ISA (2), hazards (3), Spike (4), benefit estimate (5), cost (6),
alternatives (7), questions (8).
Not verified (read-only session, do these first if continuing):
- C1: CLOSED 11:19. ReservationStation.scala:502-521 completes an ex entry by its own rob id and reports
  `matmul_ex_completed := entries_ex(id).cmd.from_matmul_fsm`; a loop-generated LOAD carries that bit like any ex
  command, so the unroller's `ex_utilization` stays balanced. Remaining check: the LOAD's `from_matmul_fsm` must survive the
  Controller path (Controller.scala:542-547 handles LOAD on `unrolled_cmd`; confirm it copies the bit into the RS entry).
- C2: `ldb_ahead`'s use of `ld_ka` (LoopMatmul.scala ~457) with a halved B iterator: still open.
- C3: PARTLY CLOSED. StC/StCSpad `ex_k` bound read (P4 row updated). Still open: how `tiled_matmul_auto` chooses tile
  sizes, to size the index reserve in the software tiler.
- C4: PARTLY CLOSED. Spike `loop_ws` read (section 4 item 0 added). Still open: the exact Spike handling of `a_spad_id/b_spad_id`
  for the second half (upper-half B start) with the index region.
- C5: no Berkeley instruction counts exist (see [Q3]); section 5.1 numbers are estimates.
Next steps: get answers to Q1-Q5; if approved, spawn (a) RTL agent from sections 1-3, (b) Spike agent from section 4,
(c) software/tests agent from sections 2, 6.1-6.3; run C1-C4 as the first task of each; freeze this file (STATUS line)
only after C1-C4 are closed and Q1 is decided.
