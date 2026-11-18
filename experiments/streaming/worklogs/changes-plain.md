# Plain-English list of code changes (Gemmini N:M sparsity)

Tags: [committed sparsity] = in the sparse-nm commits. [protocol fixes, uncommitted] = 2026-11-03 fix round. [spad-index-fix, uncommitted] = Fix A (index rows read from the scratchpad, funct 26 rd=2).
Items tagged [uncommitted, streaming] are uncommitted work for the streaming benchmark that is neither of the two fixes.

## Summary

- **Gemmini RTL.** Adds a 2:4 / 4:8 sparse weight-stationary mode: indexes travel with the weights, each PE picks one of M activations, and index tiles arrive by a new funct 26 command into a 4-deep FIFO. Uncommitted: protocol safety (clear, mode latch, legality, deadlock check) and Fix A (a scratchpad index loader).
- **Spike (libgemmini).** Models the sparse mode, the index FIFO and the sparse compute so tests run in seconds. Uncommitted: matches the RTL protocol, aborts on misuse, selectable N:M, and the Fix A load command.
- **Tests (gemmini-rocc-tests).** Adds the `gemmini_nm.h` helpers and four sparse tests. Uncommitted: stronger tests (poison, full-range data), two new tests (protocol, spad), reset and spad-load helpers, and a streaming tiler.
- **This repo.** Fair benchmark and Berkeley dense benchmark, `run-flow.sh`, result loaders, figure and report scripts. Uncommitted: all rewritten around run folders under `verification/runs/`, plus area, split, experiments and review/handoff docs.

### Gemmini RTL (`~/chipyard/generators/gemmini`, branch sparse-nm, `src/main/scala/gemmini/`)

**Configs.scala**
- [committed sparsity] Adds `nmSparseConfig` (2:4) and `nm48SparseConfig` (4:8): the default config with `nm_sparsity` set.
- [committed sparsity] Adds the `NMSparseGemminiConfig` class, a Gemmini RoCC config using the 2:4 sparse array.

**GemminiConfigs.scala**
- [committed sparsity] Adds the `nm_sparsity: Option[(Int, Int)]` config field; `None` means a plain dense chip.
- [committed sparsity] Adds elaboration `require` checks: m == 2n, power-of-2 m, WS only, no `hardcode_d_to_garbage_addr`, an index row fits in 64 bits.
- [committed sparsity] Adds `nm_n`, `nm_m`, `nm_idx_bits`, and a `gemmini_params.h` header block with `HAS_NM_SPARSITY`, `NM_N`, `NM_M`.
- [protocol fixes, uncommitted] Header macros renamed to `GEMMINI_HW_NM_N` / `GEMMINI_HW_NM_M` so they no longer override software `-D` flags.
- [protocol fixes, uncommitted] Removes the unused `nm_n` / `nm_m` vals.
- [spad-index-fix, uncommitted] Adds `require(ex_read_from_spad)` for the loader.
- [spad-index-fix, uncommitted] Adds `nm_tile_bits`, `nm_spad_rows_per_tile` (4 for 2:4, 6 for 4:8) and `nm_meta_fifo_depth` = 4 (formerly local to ExecuteController).
- [spad-index-fix, uncommitted] Header now also emits `GEMMINI_HW_NM_SPAD_ROWS_PER_TILE`.

**GemminiISA.scala**
- [committed sparsity] Adds `NM_META_CMD` = funct 26, which stages index rows for the next sparse preload.
- [committed sparsity] Adds config_ex field `nm_sparse` at rs1[10] (shrinks `CONFIG_EX_RS1_SPACER1_WIDTH` by one bit).

**Controller.scala**
- [committed sparsity] Routes funct 26 straight to the ExecuteController (`nm_meta_in`), skipping the reservation station.
- [protocol fixes, uncommitted] funct 26 with rd == 1 is a clear: pulses `io.nm_clear` at dispatch, never enqueued.
- [protocol fixes, uncommitted] Asserts on funct 26 in a dense build (`nm_sparsity = None`).
- [protocol fixes, uncommitted] Asserts if `LOOP_WS` / `LOOP_CONV_WS` is issued while sparse mode (config_ex rs1[10]) is on (`nm_loop_sparse`).
- [protocol fixes, uncommitted] Adds the index-FIFO deadlock check (`nm_dead_cnt`): asserts after 255 blocked cycles with an idle reservation station.
- [spad-index-fix, uncommitted] funct 26 rd == 2 is allocated into the reservation station; rd 3..31 asserts and is dropped.
- [spad-index-fix, uncommitted] `reservation_station_completed_arb` gets a 4th lowest-priority input for `ex_controller.io.nm_ld_completed`.
- [spad-index-fix, uncommitted] Adds a program-order model (`nm_q`, `nm_in_flight`, `nm_mode`, `nm_ld_since_clear`, `nm_ld_pending`) with asserts on load count, address, bank, FIFO room, clear and mixing register rows with loads.
- [spad-index-fix, uncommitted] `io.busy` stays high while a scratchpad index load is outstanding.

**ExecuteController.scala**
- [committed sparsity] Adds the index row assembler (`nm_asm`, `nm_asm_row`) that packs `nm_meta_in` rows into DIM x DIM tiles.
- [committed sparsity] Adds the 4-deep index tile FIFO (`nm_meta_q`); a real sparse preload pops one tile (`nm_meta_ok` gates preload/compute issue).
- [committed sparsity] Latches `nm_sparse_mode` from config_ex rs1[10], and sends `nm_sparse` and `nm_meta_row` through `mesh_cntl_signals_q` to the mesh.
- [committed sparsity] Passes the `nm` option into `MeshWithDelays` and drives `mesh.io.d_meta` from the FIFO tile.
- [protocol fixes, uncommitted] The FIFO gains flush; `nm_clear` also zeroes `nm_asm_row`.
- [protocol fixes, uncommitted] config_ex asserts sparse mode needs WS and no A/B transpose, and forces it off otherwise (`cfg_nm_legal`).
- [protocol fixes, uncommitted] config_ex asserts rs1[10] is 0 on a dense build; strides-only configs are excluded.
- [protocol fixes, uncommitted] Adds per-weight-buffer mode latch (`nm_buf_sparse`, `nm_mesh_prop` mirroring `MeshWithDelays.in_prop`); asserts a compute's mode equals its weights' mode.
- [protocol fixes, uncommitted] Comments added: a_hi comes through B with stride 1, FIFO depth rule ("at most 4 tiles ahead").
- [spad-index-fix, uncommitted] rd == 2 commands are diverted at `io.cmd` into a 4-deep side queue `nm_ld_q` and never enter the in-order command queue.
- [spad-index-fix, uncommitted] Adds the index loader at end of file: one scratchpad read per free bank cycle, per-bank owner queues, 128-bit chunk writes into the assembler, FIFO slot reservation, ROB completion.
- [spad-index-fix, uncommitted] Operand responses ignore loader reads (`readValid` uses `nm_resp_is_ld`); loader yields to operand reads (`nm_op_rd`).
- [spad-index-fix, uncommitted] Adds IO `nm_ld_completed`, `nm_reg_tile`, `nm_asm_busy`; register-row path waits while a load owns the assembler (`nm_ld_busy`).
- [spad-index-fix, uncommitted] Adds loader-internal asserts (FIFO full at enqueue, owner queue overflow, response with no request) and `require(!hasIm2Col)`.

**ReservationStation.scala**
- [spad-index-fix, uncommitted] Adds `funct_is_nm_ld`: funct 26 rd == 2 is an ex-queue command reading scratchpad rows `[rs1, rs1 + n*R)`, ordered against mvins (RAW and WAR).
- [spad-index-fix, uncommitted] `op1` holds the index rows and `op2` copies `op1`, since rs2 is a tile count, not an address.

**Mesh.scala**
- [committed sparsity] Takes the `nm` option; `in_a` becomes a group of M activations per row (`aType`).
- [committed sparsity] Adds `in_meta` and chains the weight indexes down each column, timed like `in_d`.

**MeshWithDelays.scala**
- [committed sparsity] Adds `nm_sparse` to the request, a `d_meta` input and a `d_meta_buf` register sampled with d.
- [committed sparsity] In sparse mode builds each row's group of M activations from the `a` (low) and `b` (high) halves, zeroes the b partial sums, and feeds indexes into the mesh.
- [committed sparsity] In dense mode puts the row's own activation in slot 0 and index 0.
- [protocol fixes, uncommitted] Comment text shortened only.

**PE.scala**
- [committed sparsity] Takes the `nm` option; `in_a` / `out_a` carry M activations; adds `in_meta` / `out_meta`.
- [committed sparsity] Adds index registers `m1` / `m2` that move with the weights in `c1` / `c2`; the PE picks the activation by the index of the weight in use.
- [committed sparsity] WS uses the index; OS takes slot 0 like a dense PE; `out_a` passes the whole group on.
- [protocol fixes, uncommitted] Comment text shortened only.

**Tile.scala**
- [committed sparsity] Takes the `nm` option, widens `in_a` / `out_a` to M-activation groups, passes `nm` to each PE.
- [committed sparsity] Adds `in_meta` / `out_meta` and chains the indexes down each column of PEs.

### Spike model (`~/chipyard/generators/gemmini/software/libgemmini`)

**gemmini.h**
- [committed sparsity] Adds `NM_N` / `NM_M` (default 2:4) and sparse state: `nm_sparse`, `nm_asm`, `nm_asm_row`, `nm_meta_q`, `pe_meta`, `preload_meta`.
- [committed sparsity] Declares `nm_meta_load` and `nm_meta_funct` = 26.
- [protocol fixes, uncommitted] `NM_N` / `NM_M` must come from `-D` (`#error` if missing or different from `GEMMINI_HW_NM_N/M`), plus `static_assert`s on m == 2n, power-of-2 m, DIM and index width.
- [protocol fixes, uncommitted] Adds `NM_META_FIFO_DEPTH` 4, `nm_log2_ceil`, and state `preload_d`, `preload_real`, `preload_nm_sparse`, `nm_buf_sparse[2]`, `nm_buf`, `nm_tile_in_flight`.
- [protocol fixes, uncommitted] Declares `nm_meta_clear` and `nm_meta_clear_rd` / `nm_meta_push_rd` constants.
- [spad-index-fix, uncommitted] Adds `nm_spad_rows_per_tile` (with `static_assert` against the generated define), `nm_ld_since_clear`, `nm_meta_load_spad` and `nm_meta_load_spad_rd` = 2.

**gemmini.cc**
- [committed sparsity] `reset()` zeroes the sparse state and the previously uninitialised `norm_stat_id` and counters.
- [committed sparsity] config_ex reads rs1[10]; asserts WS and no transposes in sparse mode.
- [committed sparsity] `preload()` pops an index tile for a real sparse preload (aborts if none queued); `compute()` has a sparse path where PE row r picks activation `g*M + idx`.
- [committed sparsity] Adds `nm_meta_load` (index rows into the assembler and FIFO) and dispatches funct 26 to it.
- [protocol fixes, uncommitted] `reset()` now does `*this = gemmini_state_t{}`, so every field starts zeroed.
- [protocol fixes, uncommitted] Preload latches weights into `preload_d` (a later mvin can no longer change them), the mode per weight buffer, and the popped tile; dense preloads zero the indexes.
- [protocol fixes, uncommitted] Compute aborts on a GARBAGE A operand in sparse mode, and on a compute whose mode differs from the weight buffer's mode.
- [protocol fixes, uncommitted] Sparse compute reads a_hi at `bd_addr + i` (stride 1, as the RTL), not `a_stride * i`.
- [protocol fixes, uncommitted] FIFO depth: aborts on a 5th tile (`nm_tile_in_flight` counts); config_ex aborts instead of asserting; warns if sparse mode is turned off with indexes pending.
- [protocol fixes, uncommitted] Adds `nm_meta_clear` (funct 26 rd == 1) and `nm_forbid_loop`, which aborts on `LOOP_WS` / `LOOP_CONV_WS` in sparse mode.
- [protocol fixes, uncommitted] Prints the N:M pattern at startup.
- [spad-index-fix, uncommitted] Adds `nm_meta_load_spad` with all RTL-matching checks, reads the packed bit string and decodes the index tiles into the FIFO.
- [spad-index-fix, uncommitted] Dispatch handles rd 0 / 1 / 2 and aborts on rd 3..31; register rows after a load abort until a clear.

**Makefile**
- [protocol fixes, uncommitted] Adds `NM_N ?= 2`, `NM_M ?= 4` passed as `-D`; the library now rebuilds when `gemmini.h` or `gemmini_params.h` change.

### Tests (`~/chipyard/generators/gemmini/software/gemmini-rocc-tests`)

**include/gemmini_nm.h**
- [committed sparsity] New helpers: `nm_prune`, `nm_check`, `nm_compress`, `nm_decompress`, `nm_ref_dense`, `nm_ref_sparse`.
- [committed sparsity] Adds `nm_pack_meta`, `nm_send_meta`, `nm_load_meta`, `nm_meta_cmds` and `gemmini_nm_config_ex` (sets rs1[10]).
- [protocol fixes, uncommitted] `NM_N` / `NM_M` come from `-D` or `GEMMINI_HW_*`, with `#error` and `_Static_assert`s; no silent 2:4 default.
- [protocol fixes, uncommitted] `nm_groups()` handles K not a multiple of M; `nm_compress` errors on unpruned groups; `NM_REQUIRE` replaces `assert` (links bare metal).
- [protocol fixes, uncommitted] `nm_pack_meta` / `nm_load_meta` take `rows, cols`, so edge tiles no longer read past the array.
- [protocol fixes, uncommitted] Adds `gemmini_nm_reset()` (fence, then funct 26 rd == 1), `NM_META_FIFO_DEPTH`, and a rewritten protocol comment block.
- [uncommitted, streaming] Adds streaming tiled matmul: `nm_stream_tiles`, `nm_stream_impl`, `tiled_matmul_stream_dense`, `tiled_matmul_nm` (dense and register-index variants).
- [spad-index-fix, uncommitted] Adds `NM_SPAD_ROWS_PER_TILE`, `NM_META_SPAD_BYTES`, `nm_pack_meta_spad`, `nm_unpack_meta`, `nm_meta_regs_to_spad`.
- [spad-index-fix, uncommitted] Adds `gemmini_nm_load_spad` (alias `gemmini_nm_load`), `nm_mvin_meta_spad` and the tiler variant `tiled_matmul_nm_spad` (`nm_stream_impl` sparse = 2).

**bareMetalC/Makefile**
- [committed sparsity] Adds `nm_sparse_sw`, `nm_sparse_matmul`, `nm_sparse_debug`, `nm_sparse_perf` to the test list.
- [protocol fixes, uncommitted] Adds `NM_N ?= 2`, `NM_M ?= 4` passed as `-D` to `nm_sparse_%` targets, and adds `nm_sparse_protocol`.
- [spad-index-fix, uncommitted] Adds `nm_sparse_spad` to the test list.

**bareMetalC/nm_sparse_sw.c**
- [committed sparsity] New CPU-only test of prune / compress / decompress / pack for 2:4 and 4:8.
- [protocol fixes, uncommitted] Adds a 1:2 pattern, K not a multiple of M, full-range int8 data and an edge-tile packing check (`pack_one`, `pack_edges`).

**bareMetalC/nm_sparse_debug.c**
- [committed sparsity] New one-tile test that scores the output against "broken in this way" references (index ignored, flipped, transposed, dense, a_hi as bias).
- [protocol fixes, uncommitted] Full-range data and poisons the output and accumulator tile first.

**bareMetalC/nm_sparse_matmul.c**
- [committed sparsity] New sparse vs dense matmul test checked against a CPU reference, printing cycles.
- [protocol fixes, uncommitted] Full-range data, poison before every run, and the sparse run starts after a half-sent index tile plus `gemmini_nm_reset()`.

**bareMetalC/nm_sparse_perf.c**
- [committed sparsity] New perf breakdown: dense, dense_bias, sparse, sparse_nat, reuse variants and CPU-only runs, with counters.
- [protocol fixes, uncommitted] Adds a CPU reference check for every run except dense_bias, poison before each run and full-range data.

**bareMetalC/nm_sparse_protocol.c** (untracked)
- [protocol fixes, uncommitted] New directed protocol test: a_hi stride 1, weight latch at preload, GARBAGE preload pops nothing, clear, 4 tiles queued, dense after sparse.
- [protocol fixes, uncommitted] `-DNEG=n` builds each trigger one illegal use (5th tile, GARBAGE A, mode mismatch, OS dataflow, LOOP_WS, stale-mode GARBAGE preload) that must abort or assert.

**bareMetalC/nm_sparse_spad.c** (untracked)
- [spad-index-fix, uncommitted] New Fix A test: packer against the spec hex vectors, unpack round trip, edge tile, and 8-tile sparse matmuls with poison and a CPU reference.
- [spad-index-fix, uncommitted] Covers load early or in batches, mixing with register tiles, bank edges, overwritten rows, reset, and the spec command sequence.
- [spad-index-fix, uncommitted] `-DNEG=21..37` builds each trigger one abort (reserved rd, bad count, bad address, bank cross, FIFO budget, push after load, clear in flight, no tile).

### This repo (`~/gemmini-sparsity`, HEAD 1e50e1c). All items are uncommitted.

**Modified files**
- `run-flow.sh`: rewritten. Adds steps `fair-build`, `fair`, `rerun`, `bench`, `compare`, `split`, `area`; per-seed run folders; kill-tree on abort; failed builds, sims or logs stop with non-zero exit. [protocol fixes, uncommitted]
- `run-flow.sh`: adds pattern-aware `spike-lib nm48`, `tests` with explicit `-DNM_N/-DNM_M`, base-commit check for `sim dense`, `BREAK_SIM_PREREQ=1`, `SEEDS`, `PAR`, `FAIR_BIN`, `AREA_*`; writes `run.info` and `SHA256SUMS`. [protocol fixes, uncommitted]
- `verification/fair_perf.c`: untimed warm-up of every variant, poison before every run, full-range data, a checked CPU reference, `DENSE_ONLY` flag-only build, and a runtime guard for the stock chip. [protocol fixes, uncommitted]
- `verification/fair_perf.c`: adds the `sparse_batched` variant (indexes up to 4 tiles ahead) and `prep_cold` / `prep_warm` timings. [protocol fixes, uncommitted]
- `verification/fair_perf.c`: adds the `sparse_spad` and `cpu_sparse_spad` variants (`IDX_SP`, `LOAD_SPAD`). [spad-index-fix, uncommitted]
- `verification/berkeley_dense_perf.c`: warm-up, poison, CPU-reference checks, and a bias variant; includes `gemmini_nm.h` for host helpers only; builds with `-DNM_N/-DNM_M`. [protocol fixes, uncommitted]
- `verification/nmdata.py`: rewritten as the shared log loader (`find_runs`, `load_fair`, `stat`, `ratio`, per-seed min-max); exits 2 with a message when no runs exist. [protocol fixes, uncommitted]
- `verification/verify_all.py`, `compare_runs.py`, `paper_data.py`, `cross_check.py`: reworked to read run folders and seeds instead of the deleted result files; `paper_data.py` writes into `<run>/derived/`. [protocol fixes, uncommitted]
- `analysis/chart_all_data.py`, `analysis/advanced_visuals.py`: reworked for run folders; output goes to `<run>/derived/figures/`, with min-max shading over seeds. [protocol fixes, uncommitted]
- `tools/report-builders/*` (`build_changes.py`, `build_explained.py`, `build_paper.py`, `build_report.py`, `README.md`): small path edits to remove the dead `PROJ` path. [protocol fixes, uncommitted]
- `README.md`: results marked withdrawn, run-flow steps, seeds and run folders, area and split sections, file table updated. [protocol fixes, uncommitted]
- `chipyard-setup-notes.md`: test-status wording corrected, per-pattern builds, setup commands trimmed. [protocol fixes, uncommitted]
- `.gitignore`: adds `analysis/area/work/`.

**Deleted files**
- `analysis/make_charts.py`: old chart script for the withdrawn results, dropped.
- `verification/rerun.sh`, `run_berkeley.sh`, `run_fair.sh`: old one-off launch scripts, superseded by `run-flow.sh`.

**Untracked files and folders**
- `HANDOFF.md`: status, protocol spec (section 5) and findings summary for the next session.
- `NEXT-STEPS.md`: the user's plan for the streaming benchmark (2026-10-06).
- `REVIEW-FINDINGS.md`: four read-only review reports with severity and fixes.
- `AGENTS.md`, `CLAUDE.md`: rules for AI agents and the coordinator workflow.
- `analysis/area.py`: yosys / sky130 synthesis of each simulator's Gemmini module, comparing area and flops per block.
- `analysis/area/`: area results (`area.csv`, `area.md`, `area-meta.json`, `area.pdf`, light and dark PNGs); `work/` is git-ignored.
- `analysis/split.py`: splits runtime into index issue, other issue and drain, and computes payback of preprocessing per seed.
- `fixes-wip/`: fix logs from the 2026-11-03 round (`fixlog-rtl.md`, `-spike.md`, `-rocc-tests.md`, `-analysis.md`, `-verification.md`).
- `logs/runs/`: setup logs from 2026-11-03 (simulator builds, libgemmini, rocc-tests, spike).
- `verification/runs/`: new run folders (`fair-*`, `rerun-*`, `bench-*`) with logs, `bin/`, `run.info`, `SHA256SUMS`.
- `experiments/area-nofraig/`: area re-run without the `&fraig` step, with a corrected script and the double-counted results kept for reference.
- `experiments/streaming/src/stream_bench.c`: main streaming benchmark (berkeley, dense_stream, sparse_stream, plus `sparse_fixa`).
- `experiments/streaming/investigate/src/`: micro-benchmarks (`micro*.c`), `nm_stream_v2.h`, `tiled_matmul_nm_v2.h` (the "keeper" tiler) and a second `stream_bench.c`.
- `experiments/streaming/tools/parse_fixa.py`: parses Fix A server run logs.
- `experiments/streaming/worklogs/`: agent worklogs (bench, investigate, dense-gap, speedup, analytics, anomalies, server, fix-a*, fix-b-spec, fix-area, fix-seeds, this file).
- `experiments/streaming/runs/` and `investigate/runs/`: per-run logs, `results.csv`, `run.info`, `SHA256SUMS` (including `20261111-183018-fixa-srv`).
- `experiments/streaming/research/nm-sparsity-literature.md`: literature review of N:M accelerator designs.
- `experiments/streaming/{scripts,gen,analysis,build,analytics-check,deliverables,*-scratch}`: build and run scripts, data generator, analysis scripts, build outputs, check outputs, a zipped results deliverable and scratch folders.
