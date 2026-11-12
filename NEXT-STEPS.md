# Next steps: realistic streaming benchmark (handoff, 2026-10-06)

Paused until there's a machine that can run simulations for several hours straight. This file is the
status as of 2026-10-06, the plan for the next experiment, and an instruction set to paste to Claude when
work resumes.

---

## 1. Instructions to give Claude when you come back

Copy everything in this box, fill in the machine line, and paste it as your first message:

```
I'm resuming the Gemmini N:M (2:4 / 4:8) sparsity project. First read NEXT-STEPS.md and README.md in
the project folder, then run verification/verify_all.py to confirm everything still checks out. Then:

Machine: <OS + version, CPU model + core count, RAM, free disk, is Chipyard already installed? where?>

1. Check the setup. If Chipyard isn't installed here, install it following chipyard-setup-notes.md
   (Chipyard must be at a path with no spaces or ':'), bring over the three sparse-nm branches (export them
   from the old machine with git format-patch, bases listed in section 2, and apply with git am), build the three
   simulators (GemminiRocketConfig stock, GemminiNMRocketConfig, GemminiNM48RocketConfig), and confirm
   ./run-flow.sh check and ./run-flow.sh spike pass. Then run ./run-flow.sh fair (all three chips; it
   compares the new numbers with the recorded ones automatically) and confirm they match exactly before going further.
2. Build the realistic streaming benchmark in NEXT-STEPS.md section 3: real layer sizes, data streamed
   from main memory and included in the timing, Berkeley's original run through its own optimized
   hardware loop (tiled_matmul_auto), our 2:4 and 4:8 through a streaming sparse tiler, inputs and
   reference answers generated on the host. Put everything in experiments/streaming/.
3. Check every program on Spike first. Then time ONE small layer on Verilator, and use it to estimate
   how long the full set will take. Tell me that estimate and wait for my OK before starting anything
   expected to run longer than an hour.
4. Keep the laptop/machine awake during runs (systemd-inhibit), run independent simulations in
   parallel, and never touch the original results (results/, logs/, verification/).
5. When the runs finish, verify every result against the host reference, then write a new plain-language
   paper summary with the new numbers (tools/report-builders/build_paper.py is the starting point) and
   regenerate the figures (analysis/advanced_visuals.py). Then remake the zip for my group.
```

---

## 2. Where things stand (2026-10-06)

### Environment (Hunter's laptop)
- HP Envy x360 16, Ryzen 7 8840HS (8 cores / 16 threads), about 15 GiB RAM, Fedora 44. Chipyard at `~/chipyard`
  (`bfa5699f`, about 28 GB on disk), Gemmini `8c3f9923`.
- Fedora: `conda deactivate` before `source ~/chipyard/env.sh`.
- Gemmini's default config: 16×16 array, 256 KB scratchpad (4 banks × 4,096 rows × 16 B),
  64 KB accumulator (1,024 rows), int8 inputs, int32 accumulation.

### Code (all on local `sparse-nm` branches in ~/chipyard; bases: gemmini `8c3f9923`, libgemmini `ea8f7ed`, gemmini-rocc-tests `7c540b3`)
- `generators/gemmini`: N:M sparse weight-stationary mode in the RTL (index regs + M:1 mux per PE, notes sent
  with `NM_META_CMD` funct 26 into a 4-deep FIFO, `config_ex` rs1[10] = sparse on). Configs:
  `GemminiNMRocketConfig` (2:4), `GemminiNM48RocketConfig` (4:8).
- `software/libgemmini`: matching Spike model, plus an upstream bug fix (`gemmini_state_t::reset`).
- `software/gemmini-rocc-tests`: `include/gemmini_nm.h` (prune/compress/pack helpers + wrappers) and tests
  `nm_sparse_{sw,matmul,debug,perf}`.

### Verified results: the fair comparison (`verification/fair_perf.c`, same program on every chip)
64×128×32 matmul, all data already in the scratchpad, processor issues every instruction by hand.

| Clock cycles | Berkeley original | Ours, 2:4 | Ours, 4:8 |
|---|---|---|---|
| Multiplier grid working time | 1,257 | 672 (1.87×) | 672 (1.87×) |
| Whole job, weights reused | 1,622 | 1,686 (0.96×) | 1,913 (0.85×) |
| Whole job, fresh weights | 1,604 | 2,778 (0.58×) | 3,827 (0.42×) |
| Processor time just issuing (fresh) | 1,120 | 1,883 | 2,486 |

- Every answer was checked against a processor-computed reference; all correct.
- With sparsity off, our chip matches Berkeley's exactly when running the same program (1,604 = 1,604;
  1,628 vs 1,622). The sparse hardware doesn't slow normal use.
- Conclusion so far: the grid does the multiplying in about half the time, but sending the position notes
  (4 extra instructions per tile for 2:4, 8 for 4:8) uses up the savings, so the whole job is about even (2:4)
  or slower (4:8).
- The pattern comparison (`verification/pattern_fidelity.py`): share of weights kept is 4:8 90–94% > 2:4 87–92%
  > NVIDIA paired 4:8 79–86%.

### Superseded: don't cite
The earlier reports quoted **1.44× / 1.36×** end-to-end speed-ups. Those came from a test loop
(`nm_sparse_perf.c`, results in `results/cycles.csv` and `analysis/charts/`) that slowed normal mode much more
than sparse mode. The reports were removed on 2026-10-06 (in the Trash) and will be remade from the fair data. The
original logs and CSV are kept as the debugging record. Only the fair benchmark (`verification/fair_perf.c`) should
be cited.

### Gotchas learned the hard way
- **The laptop suspends when the lid closes.** That paused a run for an hour. The lid is now set to lock only
  (backup at `~/.config/powerdevilrc.bak-20261006`). Wrap long runs in `systemd-inhibit --what=sleep:idle`.
- **`make` breaks on paths containing `:`.** This project folder has one, so copy binaries to a `mktemp -d`
  path before passing `BINARY=`.
- **Chipyard rebuilds a simulator whenever Gemmini's Scala changes.** The stock `GemminiRocketConfig` sim
  was built from stashed (unmodified) sources. Run it with `BREAK_SIM_PREREQ=1`, or it gets rebuilt from
  the sparse branch.
- **Spike needs** `LD_LIBRARY_PATH=$RISCV/lib`, and its N:M pattern is fixed at compile time (default 2:4;
  rebuild libgemmini with `-DNM_N=4 -DNM_M=8` for 4:8).
- **Loop code sensitivity.** One leftover runtime branch in an issue loop changed a whole-job number by 27%.
  Compare chips only with byte-for-byte identical loop source.
- **The default `TIMEOUT_CYCLES` (10M) is too short.** Use 150M or more; much more for big layers.
- **Use `run-binary-fast` + `LOADMEM=1`** for timed runs. Plain `run-binary` writes a GB-sized instruction trace.
- **Most of today's simulation time** was the simulated processor computing reference answers and random
  inputs, not the measured work.

---

## 3. The plan: realistic streaming benchmark

### Why
Today's numbers are exact for what they measure, but they differ from real use in three ways:

| Gap | Likely effect |
|---|---|
| Data was preloaded into the scratchpad, so memory transfer wasn't timed. Real layers don't fit (256 KB) and stream from main memory. Sparse weights are half the bytes. | Favours sparse (unmeasured advantage) |
| Tiny matrices (each weight block reused only 4 times) | Favours sparse (note cost spread over more reuse) |
| Berkeley was run by hand-issued instructions, not its optimized hardware loop (`LOOP_WS` via `tiled_matmul_auto`) | Favours Berkeley (its real speed is better) |

These pull in opposite directions, so the real answer can't be predicted. It has to be measured.

### What to build (in `experiments/streaming/`)
1. **Layer list.** Start small, then grow. Suggested (M × K × N, int8):
   - transformer-style (BERT-base, 128 tokens): 128 × 768 × 768, 128 × 768 × 3072, 128 × 3072 × 768
   - one ResNet-50 3×3 conv as a matrix: 196 × 2304 × 256
   - K must be a multiple of 32 (2 × DIM) for sparse mode.
2. **Host-side data.** A Python script generates inputs and pruned weights (2:4 and 4:8), compresses and packs
   the sparse weights and notes, and computes the reference outputs with numpy. It emits C headers. The
   simulated processor should never generate data or compute references. Compare outputs with a 64-bit hash
   plus a full check of a sample of rows, so binaries stay small.
3. **Three timed programs per layer**, each timing from the first `mvin` to the last `mvout` + fence:
   - **Berkeley best:** stock Gemmini running `tiled_matmul_auto(..., WS)` with int32 (`full_C`) output, on the
     stock simulator.
   - **Dense, hand-streamed:** a manual streaming tiler (double-buffered `mvin` of weight/input tiles, preload/
     compute, `mvout`), run on both the stock chip and ours. This isolates what the hardware loop is worth.
   - **Sparse, hand-streamed:** the same tiler, streaming the half-size compressed weights plus notes, on the 2:4
     and 4:8 chips. Write it as a reusable `tiled_matmul_nm()` in `gemmini_nm.h`.
4. **Correctness first:** run every program on Spike (2:4, then 4:8 with libgemmini rebuilt).
5. **Timing:** time the smallest layer on Verilator first and extrapolate. If runs are long, rebuild the
   simulators with `VERILATOR_THREADS=<n>` (supported by `sims/verilator/Makefile`, default 1) and run layers
   in parallel. Raise `TIMEOUT_CYCLES` well above 150M.
6. **Report:** a new CSV under `experiments/streaming/results/` and a plain-language results summary
   comparing Berkeley best, Berkeley hand-streamed, ours 2:4 and ours 4:8 for each layer. It should also break
   down how much time went to memory transfer, the grid, and the processor issuing instructions.

### Machine needed
- Linux (Fedora or Ubuntu), **32 GB+ RAM** (64 GB better), **8+ fast cores**, **60 GB+ free disk** (Chipyard is
  about 28 GB, plus simulator builds).
- Able to run unattended for hours without sleeping. A desktop or server is ideal; a laptop needs to be plugged
  in with sleep blocked.
- If even that is too slow for the big layers, the next step up is **FireSim** (Chipyard's FPGA simulation,
  e.g. on AWS), which runs hundreds to thousands of times faster.

### After that (bigger changes, only if the streaming results justify them)
1. **Notes from memory:** load the position notes into the scratchpad with the weights and have preload read
   them, removing the per-tile note instructions. This is the biggest expected speed-up.
2. **Sparse support in the hardware loop** (`LOOP_WS` / `LoopMatmul`), so sparse can use the same fast path as
   Berkeley's.
3. **Tighter 4:8 note packing:** pack rows across 64-bit register boundaries (8 → 6 instructions per tile).
4. **The unexplained stall:** without reuse, a sparse tile keeps the grid busy about 30 cycles against about 20 for
   a normal one.
