# Streaming benchmark (real layer sizes, data streamed from main memory)

The experiment planned in `NEXT-STEPS.md` section 3. Each program multiplies one real-size int8 layer,
C (M x N, int32) = A (M x K) x W (K x N), with A and W in main memory, and times it from the first instruction to
the last `mvout` + `gemmini_fence()`.

| variant | what it is | chips |
|---|---|---|
| `berkeley` | Berkeley's `tiled_matmul_auto(..., WS)`, full_C (int32) output: the `LOOP_WS` hardware loop | stock (and 2:4, 4:8 in dense mode) |
| `dense_stream` | `tiled_matmul_stream_dense()`: the hand-written streaming tiler, dense (pruned) weights | stock, 2:4 (dense mode), 4:8 |
| `sparse_stream` | `tiled_matmul_nm()`: the same tiler with half-size compressed weights + packed index tiles | 2:4, 4:8 |

Layers (`gen/gen_data.py`): `small` 64x256x128 (smoke test, timing extrapolation), `bert_qkv` 128x768x768,
`bert_ffn1` 128x768x3072, `bert_ffn2` 128x3072x768, `rn50_conv` 196x2304x256, and `edge` 36x128x64 (a cheap check
of the partial-row-tile path). The dense runs multiply by the 2:4-pruned weights (the 4:8 programs by the 4:8-pruned
ones), so every variant of a program computes the same answer.

## Method
- **Host data**: `gen/gen_data.py` makes A, W, the pruned/compressed weights, the packed index tiles (same packing as
  `nm_pack_meta`) and the exact numpy reference; the program pulls them in with `.incbin`. The simulated CPU never
  generates data or computes a reference.
- **Check**: after every timed run the CPU hashes all of C (64-bit FNV-1a over the int32 values) and compares 8
  sampled rows in full. `scripts/collect.py` checks the printed hash again against `ref.json` from the host.
- **Warm-up**: every variant first runs untimed on a 32 x 128 x 128 corner of the layer (same code).
- **Poison**: C and the whole accumulator are filled with 0x5A5A5A5A before every run.
- **Cold caches**: before every timed run a 2 MiB junk buffer is read by Gemmini's DMA, which evicts A, W and C from
  the 512 KiB L2 (random replacement, so ~(7/8)^32 = 1.4% of lines survive) and the inclusive L1s.
- **Same code**: `<layer>_24_full`, `_24_dense` (stock chip) and `_24_sparse` differ only in two volatile data flags;
  `build.sh` checks their `.text` is byte-identical.
- **Breakdown**: Gemmini's own counters, read live after the fence: `ex_active` (execute unit in its compute state:
  array busy), `rdma_active` / `wdma_active` (read / write DMA busy), `load_active` / `store_active` (load / store
  controllers moving rows), `rs_full` (reservation station full: the CPU cannot issue), `loop_matmul_active`
  (LOOP_WS unroller busy), `rdma_bytes` (bytes read by the DMA); plus `cpu_issue_done` (cycles until the CPU had
  issued the last instruction).

## The tiler (`tiled_matmul_nm()` in gemmini-rocc-tests `include/gemmini_nm.h`)
K advances in steps of 64 columns of A (4 dense or 2 compressed weight tiles). Each step is loaded with block
`mvin`s into one of 4 scratchpad buffers while the previous step computes. The output is computed in blocks of
TI x TJ tiles (TI <= 8, TI*TJ <= 32) that alternate between the two accumulator halves. Each weight tile is
preloaded once per block and reused for its TI row tiles, and a block's `mvout`s are spread over the next block's
steps. Sparse mode follows the protocol in the header: `gemmini_nm_reset()`, the sparse `config_ex`, index tiles in
batches of at most 4 right before their preloads, WS only, no LOOP_WS, and a dense `config_ex` at the end.

## Rebuild and re-run
```
cd ~/gemmini-sparsity/experiments/streaming
~/chipyard/.conda-env/bin/python gen/gen_data.py build/data       # data + headers (seconds)
scripts/build.sh                                                   # 5 programs per layer -> build/bin/<layer>/
scripts/spike_lib.sh                                               # 2:4 and 4:8 Spike models -> build/spike/ (never installed)
scripts/spike_all.sh                                               # every program on Spike (must all pass first)
PAR=6 systemd-inhibit --what=sleep:idle scripts/run_rtl.sh $PWD/runs/<stamp> <jobs file>
~/chipyard/.conda-env/bin/python scripts/collect.py runs/<stamp>   # -> results.csv + summary.md
```
A jobs file has one `<chip> <program> <seed> [timeout_cycles]` per line, chip = `stock | nm24 | nm48`. The jobs
files that were used are copied into each run folder. `run_rtl.sh` never builds a simulator (`BREAK_SIM_PREREQ=1`,
`run-binary-fast LOADMEM=1`), writes `run.info` (git hashes and diff stats of all four repos, simulator sha256s,
flags) and `SHA256SUMS`.

## Files
- `gen/gen_data.py`: data generator. `src/stream_bench.c`: the benchmark program.
- `scripts/`: `build.sh`, `spike_lib.sh`, `spike_run.sh`, `spike_all.sh`, `run_rtl.sh`, `collect.py`.
- `runs/<stamp>/`: logs, `bin/`, `run.info`, `jobs.tsv` (wall time per simulation), `SHA256SUMS`,
  `results.csv`, `summary.md`.
- `worklogs/bench.md`: what was done, when, and what is still open.
- `build/`: generated data, programs, Spike models and Spike logs (all rebuildable).

## Recorded runs
- `runs/20261109-144252/`: the main set (program v2). Every layer x variant x chip, big layers 1 seed, small 3
  seeds; 52/52 rows verified. `results.csv` and `summary.md` come from `scripts/collect.py`. Five jobs ran on the
  remote server (see `remote/`); the `host` and `sim_sha256` columns say where each row ran.
- `runs/20261109-140015/`: phase 1, program v1 (CPU poisoning, 4 MiB eviction, 1-lane hash), small (2 seeds) and
  edge. The timed code is the same; the numbers agree with v2 to within 2% (small 4:8 sparse: 35,162 v1 vs 34,518 v2; code placement and the eviction changed). Kept as a record.
- `runs/20261109-134644-pilot/`: the first RTL run (counters read through a snapshot, so `rdma_bytes` reads 0).

## Caveats on the counters
- `rdma_bytes` adds the whole request size on every 16 B beat (DMA.scala). With the 64 B requests used here it
  is exactly 4x the bytes read (small: 196,608 = 4 x 48 KiB).
- Read the counters live, not through a snapshot. A snapshot picks external vs. internal counters by the snapshot
  command's own index, so it returns the wrong value for external counters (CounterFile.scala).
- `loop_matmul_active` is non-zero in the hand-streamed runs even though they never use LOOP_WS. Treat it as
  meaningful only for `berkeley`.
- `ex_active` counts cycles the execute controller spends in its compute state, including stalls inside it. In
  these runs the sparse rows show about the same `ex_active` as dense, with half as many computes.
- The untimed per-variant overhead is printed as `<variant> overhead (untimed): poison / evict_l2 / check`. The
  check (hash of all of C) dominates the simulation time for the big layers (~3.6M cycles for bert_ffn1).
