# Fix log: Spike model (libgemmini, branch sparse-nm @ a14aaa1, Berkeley base ea8f7ed)

Scope: `~/chipyard/generators/gemmini/software/libgemmini` only. Nothing committed, stashed or installed.

Scratch: `/home/hunter/gemmini-fixwork/spike/`
- `env.sh`: chipyard env without conda base, `LD_LIBRARY_PATH=$RISCV/lib`.
- `mklib.sh <name> <N> <M> [srcdir] [patch...]`: copies the sources to `lib/<name>/`, applies mutant patches,
  builds there with the copied Makefile (`make NM_N=<N> NM_M=<M>`). Never installs.
- `run.sh <libname> <binary>`: `spike --extlib=lib/<name>/libgemmini.so --extension=gemmini <binary>`, PASS = exit 0;
  full output in `logs/<lib>.<binary>.log`.
- `src_orig/`: copy of the a14aaa1 sources (pre-fix).

## 0. Baseline (a14aaa1, before any change)

Old binaries from `gemmini-rocc-tests/build/bareMetalC` (built with the old `gemmini_nm.h`):

| lib | sw | matmul | matmul_48 | perf | perf_48 | debug | debug_48 |
|---|---|---|---|---|---|---|---|
| orig24 | PASS | PASS | FAIL | PASS | FAIL | PASS | FAIL |
| orig48 | PASS | FAIL | PASS | FAIL | PASS | FAIL | PASS |

So `--extlib` is honoured and the mismatched pattern fails.

RTL facts used (committed `ExecuteController.scala` at 639a5068, read-only):
- `b_address = b_address_rs2 + b_fire_counter`: a_hi rows are stride 1.
- `nm_preload_needs_meta = nm_sparse_mode && !preload_zeros`;
  `nm_meta_row := Mux(nm_preload_needs_meta, fifo, 0)`: dense and GARBAGE preloads carry index 0, never pop.
- `nm_meta_q = Queue(nm_tile_t, 4)`.
- The RS keeps a later mvin to the preload's rows behind the preload, so the weights are the ones present at the
  preload command, not at the compute.

## 1. Fixes (all uncommitted in libgemmini; full diff vs Berkeley: `/home/hunter/gemmini-fixwork/spike/libgemmini-final.diff`, vs a14aaa1: `libgemmini-vs-a14aaa1.diff`)

| item | where (gemmini.cc unless noted) |
|---|---|
| reset: `*this = gemmini_state_t{}` then the non-zero defaults; the per-field norm/counter zeroing from a14aaa1 is now redundant and removed | :17, :35-39 |
| startup prints `n:m sparsity = N:M` | :60 |
| preload latches weights (D/B tile), indexes, mode; real sparse preload pops, dense/GARBAGE carry index 0 and never pop; GARBAGE latches no mode; Berkeley's preload read moved here from compute() | :380-412 |
| empty FIFO message: "index tile must be sent before its preload" | :393 |
| config_ex: warn if sparse turned off with tiles/rows pending; abort unless WS && !a_t && !b_t (only full config_ex sets the mode) | :467-478 |
| two weight-buffer mode bits: COMPUTE_AND_FLIP flips `nm_buf` and takes the latched mode if the preload was real; COMPUTE_AND_STAY keeps it; mismatch aborts | :595-622 |
| GARBAGE A in a sparse compute aborts | :587-591 |
| a_hi read at `bd_addr_real + i` (stride 1); a_lo stays `a_addr + a_stride*i` | :642 |
| FIFO depth 4: a popped tile counts until its compute (`nm_tile_in_flight`), so a 5th tile between preload(t) and compute(t) aborts | :585, :770-775 |
| clear: funct 26 with rd == 1 empties FIFO and assembler, mode bits untouched | :784, :1733 |
| LOOP_WS / LOOP_CONV_WS abort while sparse | :803, :1162 |
| gemmini.h: `#error` if NM_N/M undefined or != GEMMINI_HW_NM_N/M; static_asserts (m == 2n, power of 2, DIM % n, DIM*log2 m <= 64); `NM_META_FIFO_DEPTH 4`; new state fields; `nm_meta_clear_rd = 1` | gemmini.h:24-40, :127-143, :205 |
| Makefile: `NM_N ?= 2`, `NM_M ?= 4`, passed as -D; .so depends on the headers | Makefile:9-16 |

`gemmini_params.h` untouched (stock dense; it has no GEMMINI_HW_* so the mismatch check is a no-op there, and Berkeley's chip
still builds with the default 2:4 model, which never fires unless funct 26 / rs1[10] are used).

Cleanup of the user's diff: removed redundant reset code, the loop-computed idx_bits (now `nm_log2_ceil`), the runtime
`assert(row_bits <= 64)` (static_assert), the unused per-row temp in sparse compute, the always-true `~a_addr_real != 0`
test (GARBAGE A now aborts); fixed the column-0 `dprintf`; comments shortened to one line except block/function headings.

Checked: `#error` fires with no -D and with -DGEMMINI_HW_NM_N=4 on a 2:4 build; static_asserts fire for 3:6.

### Differences from the RTL I could not match (or chose not to)
- Dense builds asserting on funct 26 / rs1[10]: Spike has no dense build (always built with some N:M).
- Clear between a sparse preload and its compute (no fence): RTL would flush the tile the preload waits for; Spike aborts
  ("fence first") instead of modelling the hang.
- Empty FIFO at a real sparse preload: RTL waits (a later index tile would satisfy it); Spike aborts per protocol item 6.
- RTL legality failure asserts AND forces sparse off; Spike aborts (same outcome in a test).
- A 5th whole tile with no preload in flight: RTL may still drain via preloads already in the RS; Spike aborts per spec
  ("at most 4 tiles ahead").
- Two preloads in a row without a compute: not modelled (Spike keeps only the last preload's latch).

## 2. Dense regression

All 56 Berkeley bareMetalC `-baremetal` tests: orig24 vs fix24 identical. 54 PASS; `matmul_spad`, `mvin_mvout_spad` FAIL
on both (pre-existing).

## 3. Mutants

Build: `/home/hunter/gemmini-fixwork/spike/mut/make_mutants.sh` (one sed edit of the fixed gemmini.cc per mutant, saved as
`mut/<name>.patch`, built with `mklib.sh <name>24 2 4 <libgemmini> mut/<name>.patch` and `<name>48 4 8`).

| mutant | bug |
|---|---|
| mutA_noidx | indexes ignored (index 0) |
| mutB_idxcol0 | wrong index mux: column 0's index for every column |
| mutC_staleD | weights read at the compute, not the preload |
| mutD_nomodecheck | mode-mismatch check removed (stale-index-after-dense-preload is unobservable while the check exists) |
| mutE_ahistride | a_hi at `bd + a_stride*i` (old bug) |
| mutF_noclear | clear is a no-op |
| mutG_nowrite | sparse computes write nothing |
| mutH_garbagepop | GARBAGE sparse preload pops a tile |
| mutI_densemath | sparse compute uses dense routing |

### rocc-tests matrix (`LIBDIR=.../spike/lib tests/matrix.sh tests/bin <libs>`, the rocc-tests agent's fixed binaries)

| lib | sw | matmul | debug | perf |
|---|---|---|---|---|
| fix24 / fix48 | PASS | PASS | PASS | PASS |
| mutA, mutB, mutG, mutI (24 and 48) | PASS | FAIL | FAIL | FAIL |
| mutF (24 and 48) | PASS | FAIL | PASS | PASS |
| mutC, mutD, mutE, mutH (24 and 48) | PASS | PASS | PASS | PASS |

(sw is host-side only and passes everywhere.) **Not caught by the rocc tests: mutC (stale D), mutD (mode check),
mutE (a_hi stride), mutH (GARBAGE pops)**, identical on 2:4 and 4:8.

### Spike probes (`/home/hunter/gemmini-fixwork/spike/probes/`: probe.c, build.sh, run_probes.sh)

16 directed probes (OK = right result, ABORT = Spike abort with a GEMMINI message, WRONG = wrong result or missing abort):
1 basic, 2 a_stride 2, 3 mvin between preload and compute, 4 5th tile between preload/compute (expect ABORT),
5 4 tiles ahead then 5th after a compute, 6 GARBAGE A (ABORT), 7 dense preload then sparse compute (ABORT), 8 clear,
9 sparse+OS (ABORT), 10 LOOP_WS sparse (ABORT), 11 warning, 12 COMPUTE_AND_STAY, 13 two tiles + a_stride 2,
14 GARBAGE preload into a dense buffer then sparse compute (ABORT), 15 dense after sparse, 16 GARBAGE preload doesn't pop.

fix24 and fix48: all as expected (OK except 4, 6, 7, 9, 10, 14 = ABORT). Every mutant deviates on both 2:4 and 4:8:
mutA/B/G/I WRONG on 1-3, 5, 8, 12, 13, 16; mutC p3; mutD p7, p14; mutE p2, p13; mutF p8; mutH p16 (ABORT instead of OK).
Pre-fix orig24 fails p2, p3, p4, p6, p7, p10, p13, p14.
Suggest the rocc-tests agent adds the p2/p3/p7/p16 cases (stride 2, mvin after preload, mode mismatch, GARBAGE in sparse).
