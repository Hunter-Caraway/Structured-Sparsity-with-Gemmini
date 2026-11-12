# Fix log: gemmini-rocc-tests (gemmini_nm.h, nm_sparse_*.c, bareMetalC/Makefile)

Scope: `~/chipyard/generators/gemmini/software/gemmini-rocc-tests` only, branch sparse-nm @ 61086b4. Nothing
committed. Build/run scripts: `/home/hunter/gemmini-fixwork/tests/{env.sh,cc.sh,build.sh}`.

## Binaries (for other agents)

- New (fixed) tests: `/home/hunter/gemmini-fixwork/tests/bin/nm_sparse_{sw,matmul,debug,perf}_{24,48}-baremetal`
  (`_24` = `-DNM_N=2 -DNM_M=4`, `_48` = `-DNM_N=4 -DNM_M=8`, same flags as run-flow.sh's `rv_cc`).
- Baseline (committed sources): `/home/hunter/gemmini-fixwork/tests/baseline/` (same names).
- Rebuild: `source /home/hunter/gemmini-fixwork/tests/env.sh; /home/hunter/gemmini-fixwork/tests/build.sh`.

## API changes in gemmini_nm.h (fair_perf.c owner: please apply)

- `nm_pack_meta(idx, stride, m, out)` becomes `nm_pack_meta(idx, stride, rows, cols, m, out)`: only the top-left
  `rows x cols` of the tile are read, the rest packs as index 0. For full tiles pass `DIM, DIM`:
  `verification/fair_perf.c:197` -> `nm_pack_meta(&idx[t * DIM][jt * DIM], NM_J, DIM, DIM, NM_M, meta[t][jt]);`
- `nm_load_meta(idx, stride, m)` becomes `nm_load_meta(idx, stride, rows, cols, m)` (same reason).
- New: `gemmini_nm_reset()` (fence, then funct 26 with rd == 1, rs1 = rs2 = 0), `NM_META_FIFO_DEPTH` (4),
  `nm_groups(k, m)`.
- `NM_N`/`NM_M`: from `-DNM_N/-DNM_M` if given, else `GEMMINI_HW_NM_N/M` from gemmini_params.h; `#error` if
  neither, or if they disagree. No silent 2:4 default any more. `berkeley_dense_perf.c` includes gemmini_nm.h, so it
  must be built with `-DNM_N=2 -DNM_M=4` (or any valid pair) when the header is the stock one.
- Unchanged names: `nm_prune`, `nm_check`, `nm_compress`, `nm_decompress`, `nm_ref_dense`, `nm_ref_sparse`,
  `nm_send_meta`, `nm_meta_cmds`, `nm_idx_bits`, `gemmini_nm_config_ex`, `nm_idx_t`, `k_NM_META`.

## 0. Baseline

- Committed tests built into `baseline/`; all four `_24` pass on the installed Spike (`spike --extension=gemmini`).

## Note for the verification agent: assert() is gone

`gemmini_nm.h` no longer includes `<assert.h>`; argument checks use `NM_REQUIRE(cond)` (printf + exit(1)), which
links bare metal. Checked: `verification/fair_perf.c` (current, with the new `nm_pack_meta` call at :284) builds with
run-flow's `rv_cc` flags for `-DNM_N=2 -DNM_M=4`, `-DNM_N=4 -DNM_M=8` and `-DDENSE_ONLY -DNM_N=2 -DNM_M=4`;
`berkeley_dense_perf.c` builds with `-DNM_N=2 -DNM_M=4` (and, as intended, #errors with no -D on the stock header).
The overlay header can be dropped.

## 1. gemmini_nm.h (done)

- `NM_N/NM_M` selection, `#error`s and `_Static_assert`s (m == 2n, power of 2, m <= NM_MAX_M, DIM % n, DIM*log2 m <= 64).
  Checked with a fake sparse gemmini_params.h: stock+none -> #error; stock+-D 4:8 ok; HW 4:8 + none ok; HW 4:8 +
  -D 4:8 ok; HW 4:8 + -D 2:4 -> mismatch #error; only NM_N -> #error; 3:6 and 1:4 -> static_assert.
- `nm_pack_meta` / `nm_load_meta` take `rows, cols` (no read past the array on edge tiles).
- `nm_groups()`: K not a multiple of M no longer drops the tail group (`nm_compress`, `nm_decompress`, `nm_ref_sparse`);
  `nm_compress` now errors on an unpruned group instead of silently keeping the first n.
- `gemmini_nm_reset()` (fence, `.insn r CUSTOM_3, 0x3, 26, x1, x0-valued rs1, rs2`), `NM_META_FIFO_DEPTH 4` with the
  RTL rule ("a tile holds its slot until its preload fires, after its compute dispatches").
- Protocol block rewritten to match the shared spec + RTL agent's rules (mode per weight buffer, GARBAGE does not
  update it, mode bits survive reset, a_hi stride 1, A not GARBAGE, no LOOP_WS while sparse).
- The checked-in `include/gemmini_params.h` is untouched (stock). No comment added: run-flow.sh's `step_tests`
  does `git checkout -- include/gemmini_params.h`, which would wipe an uncommitted comment anyway.

## 2. Tests (done)

- All four: full-range int8 data (`rand() % 256 - 128`); overflow proof in old-run/fixlog-spike.md covers these sizes
  (matmul K=64, perf K=128, debug one tile).
- matmul: outputs + accumulator tiles poisoned (0x5EADBEEF, via mvin to the acc) before both runs; before the sparse run
  it sends half an index tile of junk and then `gemmini_nm_reset()`; removed the "lets the hardware overlap" claim;
  added W / acc capacity `#error`s.
- perf: CPU reference (`nm_ref_dense`) added; poison before every checked run; dense, sparse, sparse_nat, dense_reuse
  and sparse_reuse all checked against it (dense_reuse was never checked before); bank/acc capacity `#error`s.
  dense_bias stays unchecked (timing only).
- debug: poison output + acc tile before the run.
- sw: K = 63 (2:4) and 61 (4:8) tail-group cases; edge-tile packing check (4 tiles of a 21x21 index array, each
  compared against packing a zero-padded copy).
- Protocol: every sparse run starts with a real preload after config_ex, <= 2 tiles queued, GARBAGE preloads only in
  reuse, WS / no transposes, no loops.
- bareMetalC/Makefile: `NM_N ?= 2`, `NM_M ?= 4` passed as `-D` to `nm_sparse_%` targets only (build.sh builds them
  against the stock header). Checked in an out-of-tree configure build in `/home/hunter/gemmini-fixwork/tests/mkbuild`
  (not the repo's build/): flags only on nm targets, `make NM_N=4 NM_M=8` overrides, the 4 binaries pass on fix24.

## 3. Test matrix (Spike, `/home/hunter/gemmini-fixwork/tests/matrix.sh`)

Spike agent libs (`spike/lib/`): installed, orig24/orig48 fail only matmul (they have no reset: rd==1 is treated as
index data; with the junk+reset lines removed matmul passes on the installed model). fix24 and fix48: all PASS, no
warnings.

Own mutants (built from fix24 gemmini.cc into `/home/hunter/gemmini-fixwork/tests/mut/lib/<name>{24,48}`, script
`mut/mk.py`), new tests vs the committed (baseline) tests, same result for 24 and 48:

| mutant | new: matmul / debug / perf | baseline: matmul / debug / perf |
|---|---|---|
| mB sparse never writes | FAIL / FAIL / FAIL | PASS / FAIL / FAIL |
| mE sparse writes dropped after 32 computes | PASS / PASS / FAIL | PASS / PASS / PASS |
| mR reset does nothing | FAIL / PASS / PASS | PASS / PASS / PASS |
| mI indexes ignored | FAIL / FAIL / FAIL | FAIL / FAIL / FAIL |
| mH a_hi reads 0 | FAIL / FAIL / FAIL | FAIL / FAIL / FAIL |
| mA sparse always accumulates | FAIL / FAIL / FAIL | FAIL / PASS / FAIL |

(sw is CPU-only and passes on every lib.) Every mutant is caught by at least one new test. Spike agent mutant libs
were not present yet; rerun with `LIBDIR=/home/hunter/gemmini-fixwork/spike/lib ./matrix.sh <bindir> <names>`.

Not covered: a_hi stride (all tests use A_stride = 1, so the old `a_stride*i` Spike bug would pass); FIFO-depth abort
and mode-latch checks (no negative tests: they would abort / deadlock by design).
