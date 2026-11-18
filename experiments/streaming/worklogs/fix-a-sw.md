# Fix A worklog (Spike/C agent): scratchpad index LOAD in Spike, helpers, tests, benchmarks

Started 2026-11-11. Spec: `fix-a-spec.md` (FROZEN, not edited). RTL side: `fix-a.md` (other agent).
Edits only in: libgemmini, gemmini-rocc-tests (sources), experiments/streaming benchmark C sources,
verification/fair_perf.c, this log. No git operations, no Verilator, no make in sims/, no elaboration, no server.

Scratch (builds, mutants, logs): `/home/hunter/gemmini-fixwork/fixa/` (same area the earlier fix round used;
never installed into the toolchain, never written to gemmini-rocc-tests/build).

## Plan / checklist
1. [x] Spike: funct 26 rd==2 LOAD per spec section 4 + section 7 aborts; rd 3..31 abort; PUSH after LOAD abort;
       R computed (GEMMINI_HW_NM_SPAD_ROWS_PER_TILE static_assert if present). Build fix24/fix48 in scratch.
2. [x] gemmini_nm.h: NM_SPAD_ROWS_PER_TILE (computed fallback + static_assert vs generated define),
       nm_pack_meta_spad() (spec reference packer), nm_unpack_meta() (register words -> idx), gemmini_nm_load_spad().
       Host check of the packer against the spec's hex vectors (section 9).
3. [x] Tests: bareMetalC/nm_sparse_spad.c (positive 2:4/4:8 + -DNEG=<n> per abort), Makefile entry.
       Mutant Spike builds -> tests FAIL; fixed -> PASS.
4. [x] Benchmarks: Fix A variant in fair_perf.c and in the streaming sources; Spike verify 2:4/4:8;
       instructions per tile push vs LOAD (Spike instret).
5. [x] Report.

## Progress

### Step 1: Spike (libgemmini, uncommitted) - done 13:25
- gemmini.h:41-49 `nm_spad_rows_per_tile` = ceil(DIM*DIM*log2(m) / (DIM*8*sizeof(elem_t))) (4 / 6), static_assert
  against GEMMINI_HW_NM_SPAD_ROWS_PER_TILE when gemmini_params.h has it; :153 state `nm_ld_since_clear` (zeroed by
  reset()'s `*this = {}`); :179 `nm_meta_load_spad`; :217-218 rd constants (push 0, load 2).
- gemmini.cc:752-755 PUSH after LOAD without CLEAR aborts (P3); :795 CLEAR resets the flag;
  :799-861 `nm_meta_load_spad`: checks in spec-table order (n 1..4, reserved bits, rs1 >= BANK_NUM*BANK_ROWS,
  bank rule, half tile, q + in_flight + n <= 4), then per tile read R rows as bytes, decode
  idx[r][c] = S[(r*DIM+c)*b ..], push_back in order; sets nm_ld_since_clear. Abort messages = RTL assert texts.
  :1800-1807 dispatch: rd 1 clear, 0 push, 2 load, else abort "rd values 3..31 are reserved".
- Scratch: /home/hunter/gemmini-fixwork/fixa/{env.sh,mklib.sh,run.sh}; libs lib/fixa24, lib/fixa48 (this tree),
  lib/pre24, lib/pre48 (pre-Fix-A copy in src_orig/ = the earlier fix round's sources; diff vs tree = only my edits).
  No new compiler warnings from gemmini.cc/.h.
- static_assert checked: g++ -fsyntax-only with -DGEMMINI_HW_NM_SPAD_ROWS_PER_TILE=4 on 2:4 ok, =4 on 4:8 fails.

### Step 2: gemmini_nm.h (rocc-tests include/, uncommitted) - done 13:28
- :193-201 protocol block: LOAD rules. :268-276 `nm_unpack_meta()` (register words -> idx).
- :279-299 `nm_spad_rows_per_tile(m)`, `NM_SPAD_ROWS_PER_TILE` (= GEMMINI_HW_NM_SPAD_ROWS_PER_TILE + _Static_assert
  when present, computed otherwise), `NM_META_SPAD_BYTES` (64 / 96).
- :301-314 `nm_pack_meta_spad()` = spec reference packer (zeroes out first). :316-321 `nm_meta_regs_to_spad()`.
- :323-328 `gemmini_nm_load_spad(row, n)` (`.insn r CUSTOM_3, 0x3, 26, x2, rs1, rs2`), alias `gemmini_nm_load`.
- :330-342 `nm_mvin_meta_spad(packed, row, ntiles, ld_id)` (<= DIM rows per mvin, caller sets a 16 B stride).
- Register path (nm_pack_meta / nm_send_meta / nm_load_meta) unchanged.
- _Static_assert checked: riscv gcc -fsyntax-only, HW define 4 (2:4) / 6 (4:8) ok, 5 / 8 error.

### Step 3: tests - done 13:40
- New bareMetalC/nm_sparse_spad.c; Makefile:65 added to `tests`. Default build: packer vs spec section 9 hex
  (both patterns; 2:4 also == nm_pack_meta), unpack round trip, edge tile; 8-tile sparse matmul (2 row tiles,
  GARBAGE reuse), full-range int8, poisoned C + accumulator before every case, CPU reference (nm_ref_dense of the
  pruned W, cross-checked with nm_ref_sparse): load 4 early / loads 1,3,2,2 / register tile then loads / loads in
  dense mode / bank edges (bank 0 end, last spad row) / rows overwritten after load / reset then register rows /
  spec section 9 command sequence. -DNEG=21..37: one abort each (rd 3, rd 31, n 0, n 5, rs1 hi, rs2 hi, acc addr,
  GARBAGE, row 16384, bank cross, off the end, half tile, budget 4+1, budget 3+inflight+1, push after load,
  clear between preload and compute, preload with empty fifo).
- Scratch: build_tests.sh (all nm tests + proto NEG 4/6/7/9/10/14 + spad NEG 21..37, _24 and _48, into fixa/bin
  with the earlier round's cc.sh flags), matrix.sh <lib> (positive: exit 0; NEG: nonzero exit AND the expected
  GEMMINI message in the log), make_mutants.sh (mut/<name>.patch).
- Results (logs/mutant-matrix.txt and logs/<lib>/):
  - fixa24, fixa48: 29/29 ok each (6 positive incl. the older nm tests, 6 proto NEG, 17 spad NEG).
  - pre24/pre48 (pre-Fix-A Spike): nm_sparse_spad + spad_neg21..36 bad (12/29 ok).
  - mL1_ignore (load queues nothing): spad + neg33/34/36 bad. mL2_regfmt (decode 64-bit padded rows): 48 bad
    (spad), 24 passes (2:4 formats are identical, so not a bug there). mL3_msbfirst, mL4_tileorder, mL5_samerows,
    mL10_byteorder: spad bad (mismatches) on 24 and 48. mL7_bankoff1: spad bad (bank edges abort).
    mL9_clearkeeps: spad bad ("reset, then register rows" aborts). mL6_nochecks (every Fix A check off): neg21..35
    bad on both (11 say "NOT caught", 4 crash in std::vector::at without the message). mL8_noinflight: neg34 bad.
    mL11_oldchecks (empty-fifo and clear-in-flight checks off): neg36/37 bad.
- Dense regression: all 56 Berkeley bareMetalC binaries from gemmini-rocc-tests/build (read only) on pre24 vs fixa24:
  54 pass both, same 2 pre-existing failures (matmul_spad, mvin_mvout_spad).

### Step 4: benchmarks - done 14:20
Spike counts one cycle per retired instruction (riscv-isa-sim execute.cc:375 "Model a hart whose CPI is 1"), so
every Spike "total" below is the instruction count of the timed region.
- gemmini_nm.h (later edits): :316-338 `nm_meta_regs_to_spad()` rewritten word-level (cheap for big 4:8 layers;
  the test checks it against nm_pack_meta_spad on all tiles + spec tile, aligned and unaligned output).
  v1 tiler: :380-384 doc, `nm_stream_impl(sparse = 2)`: :414-418 index slot (upper half of the A bank the step does
  not read), :427 mvin3 config (16 B rows), :451-454 index mvins after the step's weights, :485-490 one
  gemmini_nm_load_spad per batch where tiled_matmul_nm pushes; :547-551 `tiled_matmul_nm_spad()`.
- verification/fair_perf.c: :9-12 doc, :46 meta_sp, :55-56 IDX_SP (bank 2 upper half), :68 LOAD_SPAD, :241-265
  `sparse_spad` (= sparse_batched with one load per batch), :364-371 pack + mvin of the index rows once (sparse
  builds only), :381 run, :392 cpu_sparse_spad. DENSE_ONLY and full 2:4 .text identical (sha256 275e2d1985abd95e both).
  Spike (logs/fair_after_{24,48}.log, fixa libs): all variants match the CPU reference, "fair_perf passed".
  Existing variant lines identical to the pre-edit build (fair/before, counters stripped).
  | | sparse_batched (push) | sparse_spad (Fix A) | cpu_sparse_batched | cpu_sparse_spad | 32 tiles |
  |---|---|---|---|---|---|
  | 2:4 | 1667 | 884 | 1307 | 644 | |
  | 4:8 | 2307 | 892 | 1819 | 652 | |
  (index mvins are outside the timed region here, like the weights.) pre24 Spike on the new fair_24: aborts at
  the first sparse_spad preload ("no index tile queued"), as expected for a pre-Fix-A model.
- experiments/streaming/src/stream_bench.c (main bench, v1 tiler): :6-7, :15 doc; :43 RUN_SPARSE_FIXA 8;
  :157-176 meta_sp (2:4 = l_META bytes; 4:8 repacked once, untimed) + v_sparse_fixa; :221 run. Pre-edit copy
  (sha256 3e06a032... = runs/20261109-144252 run.info): /home/hunter/gemmini-fixwork/fixa/stream/src_stream_bench.c.orig.
- experiments/streaming/investigate/src/tiled_matmul_nm_v2.h (keeper): :19-24 doc; :33-34 NMV2_SPADIDX, NMV2_IDX_ROW;
  :51, :65-67 slot + checks; :82 mvin3 config; :87 next-step state; :109-114 index mvins first in each step's loads
  (bank 3 even steps / bank 1 odd, the bank that step's computes do not read); :143, :164 first load of step 0;
  :180-185 early load of the next batch right after the compute_preloaded of the batch's last tile (crossing into
  the next step); :236 tiled_matmul_nm_v2 masks SPADIDX off; :239-245 `tiled_matmul_nm_v2_spad()`.
  investigate/src/stream_bench.c: :14-16 doc, :55 RUN_SPARSE_FIXA 128, :200-221 meta_sp + v_sparse_fixa
  (-DUSE_KEEPER only), :267 mask & 255, :298-302 run. Pre-edit copies (sha256 = keeper3 run.info):
  /home/hunter/gemmini-fixwork/fixa/stream/{stream_bench.c,tiled_matmul_nm_v2.h}.
- Unchanged existing variants (Spike, same totals before/after): v1 small/edge x 24/48 _full (berkeley, dense_stream,
  sparse_stream); keeper3 small/edge x 24/48 (dense_v3, sparse_v3). build.sh's .text identity of the _24 builds holds.
  Header-only effect on old code: NM_REQUIRE __LINE__ constants (keeper3 disassembly: only `li a1,<line>` differs).
- Spike results, every run verified (hash + 8 sampled rows), logs fixa/logs/{s,k}_<layer>_<pat>_fixa.log.
  Programs: v1 = src/stream_bench.c -DRUN_MASK=12; keeper = investigate/src -DUSE_KEEPER -DRUN_MASK=224.
  tiles = real preloads = (K/2/16)*(N/16)*ceil(ceil(M/16)/TI) (from the sbench header line).
  | layer | pat | tiles | v1 sparse_stream | v1 sparse_fixa | saved/tile | keeper sparse_v3 | keeper sparse_fixa | saved/tile |
  |---|---|---|---|---|---|---|---|---|
  | edge | 2:4 | 16 | 2913 | 2482 | 26.9 | 2606 | 2469 | 8.6 |
  | edge | 4:8 | 16 | 3229 | 2544 | 42.8 | 2806 | 2538 | 16.8 |
  | small | 2:4 | 64 | 11486 | 9537 | 30.5 | 8441 | 7743 | 10.9 |
  | small | 4:8 | 64 | 12750 | 9657 | 48.3 | 9241 | 7876 | 21.3 |
  | bert_qkv | 2:4 | 1152 | 331145 | 298378 | 28.4 | 303711 | 287902 | 13.7 |
  | bert_qkv | 4:8 | 1152 | 354473 | 302558 | 45.1 | 317535 | 292515 | 21.7 |
  | rn50_conv | 2:4 | 2304 | 566744 | 499269 | 29.3 | 517174 | 488259 | 12.5 |
  | rn50_conv | 4:8 | 2304 | 613400 | 508201 | 45.7 | 545974 | 497480 | 21.0 |
  | bert_ffn1 | 2:4 | 4608 | 1324640 | 1193413 | 28.5 | 1216674 | 1153201 | 13.8 |
  | bert_ffn1 | 4:8 | 4608 | 1417952 | 1210121 | 45.1 | 1271970 | 1171638 | 21.8 |
  | bert_ffn2 | 2:4 | 4608 | 1292777 | 1161715 | 28.4 | 1182650 | 1120035 | 13.6 |
  | bert_ffn2 | 4:8 | 4608 | 1386089 | 1178423 | 45.1 | 1237946 | 1138472 | 21.6 |
  (streaming totals include the index mvins; keeper push = BANKSPLIT + METAWARM, keeper Fix A = BANKSPLIT + SPADIDX.)
- Mutant check of the benchmarks: small_48_keeperfixa on mL2_regfmt48 -> sparse_fixa MISMATCH; small_24_fixa (v1) on
  mL3_msbfirst24 -> MISMATCH; fair_48 on mL5_samerows48 -> sparse_spad mismatch, fair_perf FAILED.
- berkeley_dense_perf.c still compiles (-DNM_N=2 -DNM_M=4). Final rerun after all header edits: fixa24 29/29, fixa48 29/29.

## Questions / notes (no spec bug found)
- The spec's section 9 hex vectors equal the reference packer's output on both patterns (test "packer" ok), and the
  section 9 command sequence gives the CPU reference result on Spike.
- Spike's address check is `rs1[31:0] >= BANK_NUM*BANK_ROWS`; equal to the spec's rs1[31:spAddrBits] != 0 because
  BANK_NUM*BANK_ROWS is a power of 2 on these chips (it would differ only on a config with a non-power-of-2 row count).
- Not modelled in Spike (spec says so): P4 (clear while a load is outstanding) and index rows written by a matmul C
  output in flight.

## For the server rebuild (not done here)
- Simulators: GemminiNMRocketConfig (2:4) and GemminiNM48RocketConfig (4:8) from the Fix A RTL; the stock chip is
  unchanged. Elaboration writes GEMMINI_HW_NM_SPAD_ROWS_PER_TILE; gemmini_nm.h / gemmini.h static_assert it.
- Programs (all built here only into scratch against the stock gemmini_params.h; rebuild after elaboration):
  - bareMetalC/nm_sparse_spad.c, -DNM_N/-DNM_M 2/4 and 4/8: must pass. Its -DNEG=21..37 builds must each hit the RTL
    assert named in the spec section 7 table (NEG 21-22 reserved rd, 23-24 count, 25-26 reserved bits, 27-29 address,
    30-31 bank, 32 half tile, 33-34 fifo budget, 35 push after load, 36 clear between preload/compute, 37 no tile).
    Plus the existing nm_sparse_{sw,matmul,debug,perf,protocol}.
  - verification/fair_perf.c (2:4, 4:8; -DDENSE_ONLY for stock): new lines sparse_spad / cpu_sparse_spad.
  - streaming: investigate/src/stream_bench.c -DUSE_KEEPER -DRUN_MASK=224 (dense_v3, sparse_v3, sparse_fixa) per
    layer/pattern; src/stream_bench.c -DRUN_MASK=12 (sparse_stream, sparse_fixa) or 15 with berkeley + dense.
- Scratch binaries (stock header): /home/hunter/gemmini-fixwork/fixa/{bin, fair/after, stream/after}.
