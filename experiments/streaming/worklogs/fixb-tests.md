# fixb-tests worklog (tests agent, sparse-loop-fix software side, 2026-11-12)
Spec: `fix-b-spec.md` (FROZEN 2026-11-12), sections 2.5, 6.1, 6.3. Compile-only on the laptop; no Spike, no sims, no git writes.
Scope: gemmini-rocc-tests `include/gemmini_nm.h`, `bareMetalC/nm_sparse_loop.c`, `bareMetalC/Makefile`; this repo
`experiments/streaming/src/stream_bench.c`, `verification/fair_perf.c`, `run-flow.sh`.
gemmini-rocc-tests is on branch `sparse-loop-fix` (created by the coordinator from sparse-nm 25a6611).

## Step 1: read (done)
Spec, gemmini_nm.h, Berkeley's gemmini_loop_ws / tiled_matmul_outer / tiled_matmul_auto (gemmini.h:366, 716, 1257),
nm_sparse_spad.c, stream_bench.c, fair_perf.c, run-flow.sh. RTL and libgemmini have no sparse-loop-fix lines yet
(grep, 2026-11-12), so everything below follows the spec text only.

## Step 2: header (done)
`gemmini-rocc-tests/include/gemmini_nm.h` (gemmini.h untouched):
- :203 protocol note (LOOP_WS legal in sparse mode only with rs1[3] + funct 28).
- :557-729 new section: `k_NM_LOAD_IDX` 27, `k_LOOP_WS_CONFIG_NM` 28, `NM_LOOP_WS_NM_BIT` 3; `gemmini_nm_load_idx` /
  `gemmini_nm_extended_load_idx` (:584); `nm_load_idx_meta_spad` (:590, g = 16/R tiles per command);
  `gemmini_loop_ws_config_nm`, `gemmini_loop_ws_nm` (:602, Berkeley's macro + funct 28 before LOOP_WS + rs1[3]);
  `nm_loop_pad_k`, `nm_zero_pad` (:614, :617); `nm_loop_spad_rows`, `nm_loop_fits` (:626, :630: spec 2.5.4 bound,
  index rows <= one bank, even K, I*J*DIM <= ACC_ROWS/2); `nm_loop_tiles` (:639, tiled_matmul_auto's double-buffered
  rule, tile_K even); `nm_loop_order_idx` (:667); `tiled_matmul_nm_loop` (:690, bias + repeating bias, int32 C).
Design decisions (inside the spec, recorded because the spec leaves them to software):
- Index DRAM order. The loop wants tile (k', j) of *its own call* at idx_dram + (k'*J + j)*R*16. A layer split over
  several calls therefore needs the tiles grouped per call: `nm_loop_order_idx` reorders the (t, jt) array once
  (untimed prep, depends on tile_J / tile_K); the tiler computes each call's offset in closed form. Offset formula
  checked against the reorder loop by brute force (python, 960 shapes, 0 mismatches; no log, re-run is seconds).
- a_spad_id / b_spad_id reuse is not used (always 0): spec does not say what LdIdx does when B is not reloaded.
- The tiler ends with dense config_ex + fence (as tiled_matmul_auto fences), so C is ready on return.

## Step 3: tests (done, compile only)
`bareMetalC/nm_sparse_loop.c` (new, 313 lines), `bareMetalC/Makefile` (:66 test entry; :131-134, :144-149 NEG rule
`nm-loop-neg`; :162 junk). Positive cases (all vs CPU reference, C + whole accumulator poisoned, writes outside C checked):
T=1/2/3/4/5/10 single loops (i 1..3, j 1..5, partial row tile, no / repeating / per-row bias); 8 back-to-back loops
(partial i and j, K blocks accumulate, with and without bias); 4 loops with T=3 and T=1; K=40 zero-padded to 64;
nm_loop_tiles (3x6x6, T=18); sequence sparse loop -> Berkeley dense loop -> per-tile sparse with CPU LOAD_IDX (groups,
bank-3 edge) -> sparse loop -> per-tile with one LOAD_IDX per tile -> sparse loop in 2 calls.
NEG=<n>, n/10 = spec assert: 10,11 N1 | 20 N2 | 30 N3 | 40 N4 | 50,51,52 N5 | 60,61 N6 | 70..74 N7 | 80 N8 | 90,91 N9 |
100 N10 | 110 N11 | 120,121,122 N12 | 130,131,132 N13 | 140 N14.

## Step 4: benchmarks and run-flow (done, compile only)
- `experiments/streaming/src/stream_bench.c`: variant `sparse_loop`, RUN_MASK bit 16 (:46, :177-207, :238, :252).
  Existing variants and their lines untouched; one new line `sparse_loop tiles: ...` only when the variant runs.
  Index reorder is untimed prep; nm_loop_tiles and all loop commands (so the funct 27 index mvins) are timed.
- `verification/fair_perf.c`: `dense_loop` + `sparse_loop` (:298-336), run last (:437) because a loop overwrites the
  scratchpad rows the other variants preloaded; `c_in_dram` (:68, :123, :375, :379) skips store_c for them.
- `run-flow.sh`: nm_tests + nm_sparse_loop (:79), `loop_neg` / `loop_neg_dense` / `loop_neg_msg` (:91-113), tests
  (:420), spike (:532, :548-558, exact message, grep -F), rerun (:604, :625-633). Paths, formats and the
  --extlib-before---extension order unchanged. `bash -n` clean.

## Step 5: compile results
- `SCRATCH_DIR=<S> ./run-flow.sh tests` rc 0, "134 bare-metal tests built" (56 dense + 12 nm + 12 protocol NEG + 54 loop NEG):
  /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-tests/tests.log
- -Wall -Wextra syntax pass of nm_sparse_loop.c (2:4 and NEG=100): no warning in nm_sparse_loop.c or the new header lines:
  .../fixb-tests/wall24.log, wallneg.log
- fair_perf x3, build.sh (edge, small, bert_ffn1; _24 .text identity check still passes) and 12 `<layer>_<24|48>_loop`
  (RUN_MASK=17) programs: .../fixb-tests/bench-build.log
- objdump of nm_sparse_loop_24: funct7 27 and 28 present with funct3 = 3, rd = 0 (no log kept; one-line re-run).
- Makefile NEG rule: `make -n` out of tree lists all 27 NEG programs with -DNEG and -DNM flags.
Binaries (S = /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-tests):
S/tests/bareMetalC/nm_sparse_loop_{24,48}-baremetal, S/tests/bareMetalC/nm_sparse_loop_neg<n>_{24,48}-baremetal,
S/fair/fair_perf_{24,48,dense_only}-baremetal, S/sbench/<layer>/<layer>_{24,48}_loop-baremetal.
NOTHING WAS RUN: no Spike, no simulation. All behaviour claims above are by construction only.

## 6.3 verification plan (to run once the Fix B Spike lib exists)
1. `SCRATCH_DIR=<S> ./run-flow.sh spike nm24` and `nm48` (lib at S/libgemmini-<pat>/): nm_sparse_loop must print
   `nm_sparse_loop passed`; each loop NEG must abort with its 2.5.6 text. 56 dense tests: run each S/tests/bareMetalC dense binary.
2. NEG 110 / 140 need a dense libgemmini (no nm_sparsity); run-flow builds them but does not run them.
3. Mutants (6.3.3) and which positive case should kill them: wrong a_hi base / K not halved in StC / nm flag not latched ->
   every loop case; idx stride or LOAD3 instead of funct 27 -> bias cases and the per-tile LOAD_IDX cases (id 2 stride
   is set to 3*DIM*4 there); N9 removed -> NEG 90; throttle / priority mutants are RTL timing only.
4. RTL: `./run-flow.sh rerun` now includes nm_sparse_loop and 25 loop NEGs per chip.

## Open questions / spec ambiguities
1. N11 / N14 on RTL: the only dense RTL is Berkeley's stock simulator, never built from our sources, so it has no such
   assert. Which build is meant to prove N11 / N14 in RTL?
2. N9 "index region exceeds one bank" cannot occur alone: with DIM 16 and R <= 6 the B region is already over the half
   whenever idx_rows > 4096. NEG 91 therefore proves the same condition as NEG 90.
3. N13 "outside the scratchpad": tested with a start row of 16384. A LOAD_IDX that starts inside and runs off the end
   (row 16383, 2 rows) is not named by the spec and not tested.
4. a_spad_id / b_spad_id (operand reuse) with a sparse loop: not forbidden by N7, behaviour of the index rows undefined.
5. Spec 6.1 lists a separate `nm_load_idx.c`; the CPU-issued funct 27 cases and N11-N13 are inside nm_sparse_loop.c instead
   (task brief names only that file; the Makefile's -DNM_N/-DNM_M rule matches `nm_sparse_%`).
6. NEG 70 / 71 set LOOP_WS rs2[0] / [1]; if an older assert on transposes in sparse mode fires first the message differs.
7. `experiments/streaming/scripts/build.sh` (not mine) has no RUN_MASK=16 program yet; verification parsers
   (verify_all.py, collect.py, parse_fixa.py) were not checked against the new `dense_loop` / `sparse_loop` lines.
8. `./run-flow.sh spike` now fails with a pre-Fix-B lib (nm_sparse_loop is in its list); intended, but note it.

## RESUME HERE
Done: header, test + 27 NEG builds, Makefile, stream_bench `sparse_loop`, fair_perf `dense_loop` / `sparse_loop`,
run-flow; everything compiles (logs above). Running: nothing. Not done: any execution (Spike lib with funct 27/28 not
available to this agent), mutants, the 56-dense regression on the new lib, server runs.
Findings: tile sizes nm_loop_tiles will pick, from a python model of the function (not a log): edge 3x4x8 (1 call),
small 4x8x16 (1), bert_qkv 5x6x48 (16), bert_ffn1 5x6x48 (64), bert_ffn2 5x6x58 2:4 / 5x6x56 4:8 (64), rn50_conv
5x6x58 / 5x6x56 (27). Next: coordinator passes the binaries to the Spike agent; fix whatever the first run shows.

# Round 2 (2026-11-13, spec changelog D1-D5)
Scope: gemmini-rocc-tests `bareMetalC/Makefile`, `bareMetalC/nm_sparse_loop.c` only (`include/gemmini_nm.h` not changed this round).
R2T = `experiments/streaming/investigate/runs/20261113-145158-fixb-r2-tests/` (run.info, SHA256SUMS, r2.sh, cc.sh).

## Changes
- D4: `nm_sparse_loop.c:32-33, :315-316` NEG=133: funct 27 at row `BANK_NUM*BANK_ROWS - R + 1` with R rows (R = 4 for 2:4,
  6 for 4:8, so N12 stays quiet): starts inside the scratchpad, last row one past the end. Expected text
  `sparse-loop-fix: LOAD_IDX destination must be a scratchpad row address`. NEG 130, 131, 132 kept.
  Legal edge (address + rows == end) is in the positive test already: "seq: per-tile, LOAD_IDX groups" ends its index
  rows at row 4 * BANK_ROWS (`nm_sparse_loop.c:242`).
- D1: `Makefile:133` `nm_loop_negs` now holds only the n:m-build cases (133 added); `Makefile:134-136` new list
  `nm_loop_negs_dense_spike_only = 110 140` with the reason (dense Spike lib only, no RTL assert, legal on an n:m build);
  `Makefile:137` `nm-loop-neg` still builds both lists. Test header `nm_sparse_loop.c:28-29, :34` says the same.
- pad_J: `nm_sparse_loop.c:11-12, :228-234` five positive cases with N % DIM != 0: N=5 (the partial tile alone),
  N=DIM+1 (repeating bias), N=4*DIM+13 (partial i, row bias, 5 column tiles), N=5*DIM-1 in 4 loops (last column block
  2 tiles, 1 column missing), N=5*DIM+7 with nm_loop_tiles and K=40 padded. All against the CPU reference, with the
  "wrote outside C" check. (Round 1 had one such case: "8 loops, partial i and j".)

## Results (Spike, round-2 libs of the Spike agent in scratch `fixb-r2/libs/`, hashes in R2T/run.info)
- Build: 58 programs (positive + 28 NEG, 2:4 and 4:8), R2T/build.log. Makefile `make -n nm-loop-neg` lists 28 -DNEG (no log).
- Positive: nm_sparse_loop_24 and _48 rc 0, 22 of 22 cases ok each, 5 of 5 pad_J cases, `nm_sparse_loop passed`
  (R2T/pos.summary, R2T/pos/).
- NEG on the n:m libs: 26 x 2 = 52 of 52 abort with their 2.5.6 text, NEG 133 included (R2T/neg.summary, R2T/neg/).
  NEG 110 / 140: abort with the N11 / N14 text on the dense libs (R2T/neg-dense/), run through with rc 0 on the n:m
  libs where they are legal (R2T/neg-nmlib/).
- Mutants (scratch copies of libgemmini, R2T/mutants.summary, mutation.diff per mutant in R2T/mutants/):
  - `n13-start-only` (range part of N13 removed): NEG 133 no longer shows the N13 text on 2:4 and 4:8 (Spike dies in
    `vector::_M_range_check` instead), NEG 130-132 still pass. So only 133 proves the range part.
  - `pad-j-ignored` (loop pad_J forced to 0): 5 of 5 pad_J cases FAIL ("wrote outside C") plus the round-1 partial-j
    case, on both patterns. The summary's "5 of 10" counts the mismatch lines too.

## Not done / open
- RTL: nothing run. The RTL agent's question (pad_J gives a sparse preload `b_cols < DIM`, fixb-rtl.md:104) is answered
  for the Spike model only; the five pad_J cases are the RTL test for it.
- run-flow.sh (other owner) needs 133 in `loop_neg`; its `loop_neg_dense=(110 140)` already matches the Makefile list.
- Berkeley's dense tests and the benches were not re-run here (no change to the header).

## RESUME HERE
Done: round 2 edits (Makefile, nm_sparse_loop.c), build, Spike positive / NEG / 2 mutants x 2 patterns, all as expected
(R2T). Running: nothing. Nothing committed; uncommitted in gemmini-rocc-tests: Makefile, gemmini_nm.h, nm_sparse_loop.c.
Next: run-flow.sh owner adds NEG 133; RTL runs of nm_sparse_loop (pad_J cases) and NEG 133 on the server after the
approved rebuild. Scratch binaries (`fixb-r2/tests/bareMetalC/`) are lost with the session; rebuild with R2T/r2.sh.
