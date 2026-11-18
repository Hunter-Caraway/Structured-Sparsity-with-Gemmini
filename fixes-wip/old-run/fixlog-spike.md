# Fix log: Spike model, gemmini_nm.h, nm tests, fair_perf / berkeley_dense_perf

Workspace: `scratchpad/spikefix/` (env.sh, mklib.sh, cc.sh, run.sh; originals backed up in `spikefix/orig/`).
Spike libs are built only into `spikefix/lib/<name>/libgemmini.so` and run with
`spike --extlib=<scratch .so> --extension=gemmini` (extlib must come first). Test binaries go to `spikefix/bin/`.

## 0. Baseline (before any change)

- Original model rebuilt from HEAD into `lib/orig24`, `lib/orig48`.
- Old binaries (`scratchpad/bin/nm_sparse_*-24/48`): all four pass on the matching build.
- `--extlib` is honored: `lib/orig48` on `nm_sparse_matmul-24` aborts ("sparse preload with no index tile queued").
- Old mutants reproduce the review: mutA passes `nm_sparse_matmul` (fails `nm_sparse_perf`); mutB and mutE pass
  both `nm_sparse_matmul` and `nm_sparse_perf`.
- RTL facts used below (read-only, committed `ExecuteController.scala`): `b_address = b_address_rs2 + b_fire_counter`
  (a_hi stride 1); `dataB` is 0 when B is GARBAGE (`accumulate_zeros`), so GARBAGE a_hi = 0 like Spike; `dataA` is
  not zeroed for a GARBAGE A (stale bank data); `nm_meta_row := Mux(nm_preload_needs_meta, fifo, 0)` so dense and
  zero preloads carry index 0; meta FIFO is `Queue(nm_tile_t, 4)`.
- Overflow proof for full-range int8 (fair_perf / berkeley_dense_perf): both NM configs are
  `defaultConfig.copy(nm_sparsity = ...)`, so `inputType = SInt(8)`, `spatialArrayOutputType = SInt(20)`,
  `accType = SInt(32)`. One column of the 16x16 array sums at most 16 products (dense: 16 weights; sparse: 16
  kept weights, one per PE row) plus an int8 bias: |s| <= 128 + 16*128*128 = 262,272 < 2^19 = 524,288 (fits
  SInt(20)). The accumulator sums KT = 8 such tiles (sparse: KCT = 4): <= 8*262,272 = 2,098,176 < 2^31. The CPU
  reference sums 128 products in int32: <= 2,097,152. So no intermediate can overflow.

