# Chipyard + Gemmini setup notes (Fedora 44)

Setup date: 2026-10-05 / 06. Host: Fedora 44, x86_64, 16 cores, 14 GB RAM, glibc 2.43, KDE Plasma 6.7.
Chipyard lives at `~/chipyard`. This folder holds the logs, results, and these notes.

## Sourcing the environment in a fresh terminal

Fedora is a RHEL-family system, so deactivate conda *before* sourcing `env.sh`:

```bash
conda deactivate
cd ~/chipyard
source env.sh
```

`env.sh` re-activates `~/chipyard/.conda-env` itself and sets `RISCV=~/chipyard/.conda-env/riscv-tools`.
Check: `echo $CONDA_DEFAULT_ENV $RISCV` should show both under `~/chipyard/.conda-env`.

> Chipyard must stay at a path with no spaces or `:`. That's why it isn't inside this folder:
> `:` is the PATH / LD_LIBRARY_PATH separator, and Make can't handle spaces. The conda env also can't be moved.

## Original failure: root cause and fix

**Symptom:** `./build-setup.sh` exited with code 1 at step 1 (conda environment setup), and `setup.log` ended in a
`conda-lock install` usage/help dump.

**Root cause:** a bug in `build-setup.sh` (lines ~201-207) that shows up on hosts *newer* than the pinned glibc.
1. The script compares the host glibc (`ldd --version`, which is 2.43 on Fedora 44) with the pin in
   `conda-reqs/chipyard-base.yaml` (`sysroot_linux-64=2.34`). They don't match, so the script runs `sed` to rewrite
   the pin to `=2.43` and runs `scripts/generate-conda-lockfiles.sh`.
2. That script runs `rm -f` on the linux-64 lockfile *before* re-solving. **conda-forge has no `sysroot_linux-64=2.43`**
   (the newest is 2.39), so the solve fails and the committed lockfile is gone.
3. On the next run the YAML already says 2.43, which matches the host, so regeneration is skipped. `conda-lock install`
   is then pointed at a lockfile that doesn't exist, which produces the usage dump and exit code 1.

The mismatch check only makes sense when the host glibc is *older* than the pin. A 2.34 sysroot runs fine on 2.43.
`conda update -n base --all` does **not** fix this.

**Fix (no Chipyard source changes):**
1. `git checkout -- conda-reqs/chipyard-base.yaml conda-reqs/conda-lock-reqs/conda-requirements-riscv-tools-linux-64.conda-lock.yml`.
   Then deleted `chipyard-base.yaml.bak` and the stale `.conda-lock-env`. (The stale directory was
   `.conda-lock-env`; `.conda-env` never got created.)
2. Ran step 1 by hand, exactly as the script does it, minus the glibc rewrite:
   ```bash
   conda install -n base -c conda-forge conda-lock        # conda-lock 4.0.2
   conda-lock install --conda "$CONDA_EXE" -p ~/chipyard/.conda-env \
       conda-reqs/conda-lock-reqs/conda-requirements-riscv-tools-linux-64.conda-lock.yml
   ```
   Then wrote the same `build-setup-conda` activation block into `env.sh` with the script's own
   `replace_content` helper (`scripts/utils.sh`).
3. Ran the rest with step 1 skipped: `./build-setup.sh riscv-tools -s 1`.

If you ever re-run `build-setup.sh` from scratch on this machine, it will hit the same bug again. Use `-s 1`, or
repeat the manual step 1 above.

## Other problems hit along the way

| # | Problem | Fix |
|---|---------|-----|
| 1 | Step 9 (FireMarshal buildroot precompile) failed: `FileNotFoundError: 'guestmount'` | FireMarshal isn't needed for Gemmini bare-metal work. **Skipped step 9** and ran steps 10-11 with `./build-setup.sh riscv-tools -s 1 -s 2 ... -s 9`. To enable it later: `sudo dnf install libguestfs`, then re-run step 9. (Not done: needs sudo.) |
| 2 | Only 14 GB RAM, so `make -j$(nproc)` (16 jobs) for Verilator risks the OOM killer | Built with `-j4` from the start. |
| 3 | `generators/constellation` shows as modified, and libgloss / riscv-* toolchain submodules show as untracked in `git status` | These are leftovers from setup builds, not source edits. Left alone. |
| 4 | Four `mvin_mvout*` test binaries were **0 bytes**. A `make` I'd piped into a `grep` with a bad pattern got killed mid-write, and the truncated files had fresh timestamps, so later builds skipped them | Deleted the 0-byte files and rebuilt. `run-flow.sh tests` now deletes 0-byte binaries before building. |
| 5 | **First baseline run failed: `*** FAILED *** (timeout) after 10000001 simulation cycles`.** Chipyard's default `TIMEOUT_CYCLES` is 10M, but `matmul-baremetal` needs about 28.6M (mostly CPU reference math). Only 2 of 8 combinations had finished | Re-ran the same `run-binary` command with `TIMEOUT_CYCLES=150000000`. Failed log kept as `logs/baseline/baseline_matmul-try1-timeout-10Mcycles.log`. |
| 6 | Re-running the baseline after I'd started editing Gemmini's Scala made Chipyard **re-elaborate `GemminiRocketConfig` from the modified sources** (make tracks the Scala files) | Stopped it, `git stash`ed the RTL edits so the Scala was stock again, rebuilt and launched the baseline, and `git stash pop`ped once the sim process was running. I checked that the generated RTL contained no `nm_meta` logic, and that the restored edits matched a saved patch byte for byte. |
| 7 | `run-binary` logs every instruction (`+verbose`): the baseline trace is **1.2 GB** (`sims/verilator/output/.../matmul-baremetal.out`) | Kept for now. Delete it if you need the space. For runs that time themselves, use `run-binary-fast` and `LOADMEM=1`. |

Setup steps 2-8, 10 and 11 all succeeded. Spike's Gemmini extension (`libgemmini.so`) and all 56 `bareMetalC` tests
built without errors.

## Smoke tests on Spike

`spike --extension=gemmini <test>`. Log: `logs/baseline/spike-smoke.log`.

| Test | Result |
|------|--------|
| `mvin_mvout-baremetal` | PASS (exit 0, ~0.02 s) |
| `matmul-baremetal` | PASS (exit 0, ~0.03 s; all 8 combinations of OS/WS dataflow × A/B transpose) |

Gemmini is configured with `dim = 16` (16×16 systolic array).

## Baseline: Verilator, GemminiRocketConfig, matmul-baremetal

Command (yours, plus a longer timeout; see problem 5):

```bash
cd ~/chipyard/sims/verilator
make CONFIG=GemminiRocketConfig run-binary \
  BINARY=../../generators/gemmini/software/gemmini-rocc-tests/build/bareMetalC/matmul-baremetal \
  TIMEOUT_CYCLES=150000000 2>&1 | tee logs/baseline/baseline_matmul.log
```

| | |
|---|---|
| Result | **`*** PASSED *** Completed after 28599226 simulation cycles`** |
| Combinations checked | all 8 (OS and WS dataflow × A/B transpose) |
| Last core-trace cycle | 12,831,398 (the core's own cycle counter in the instruction trace) |
| Wall time | 104 min 33 s (Verilator with `+verbose` tracing) |
| Hardware | stock `GemminiRocketConfig`, built from unmodified Gemmini Scala |

Logs: `logs/baseline/baseline_matmul.log` (make output), `logs/baseline/baseline_matmul-sim-stdout.log` (program output),
`logs/baseline/baseline_matmul-RESULT.txt` (the PASSED line plus where the full trace is).

Caveat: `matmul-baremetal` doesn't print its own timing, so 28.6M is the simulator's total. It includes loading the
program over the serial (TSI) link and the CPU computing reference results, and only a small fraction is Gemmini doing
matrix work. For sparse vs dense comparisons, use `nm_sparse_perf` below, which times just the Gemmini work with
`rdcycle` and hardware counters.

## Version info: Gemmini `CHIPYARD.hash` vs Chipyard HEAD

| | Commit | Date |
|---|---|---|
| Gemmini's `CHIPYARD.hash` (the Chipyard version Gemmini says it was tested against) | `e02074414158c85059c1dcb231ff2f8941254b9a` (Merge PR #2198, boom-idx-dep-tracking) | 2025-02-12 |
| Actual Chipyard HEAD | `bfa5699fe9c7b0ffbff7bd972e362bf507f8bf21` (Merge PR #2385, corigine-mimicturbo-gt) | 2026-10-05 |
| Gemmini submodule commit (pinned by Chipyard HEAD) | `8c3f9923a44a2fe2c7930587be297d6d4f8c09ca` (Merge PR #392, modular) | 2025-09-01 |

The `CHIPYARD.hash` commit is an ancestor of HEAD, **635 commits behind**. So Chipyard is much newer than the
version Gemmini declares, but Chipyard HEAD is what pins this Gemmini commit, and the build and Spike tests work.
If something Gemmini-specific breaks later, checking out `e0207441` in Chipyard is the fallback to try.

## Gemmini branch

Created branch `sparse-nm` in `~/chipyard/generators/gemmini` at `8c3f9923`. (At this point nothing was pushed; the
branches were later published to the `Hunter-Caraway` forks listed in the README.)
(The submodule's existing `origin` is `ucb-bar/gemmini` from the submodule init.)

## Logs in this folder

```
logs/setup/setup-attempt1-failed.log              original failing run (step 1)
logs/setup/step1-conda-env-manual.log             manual conda-lock install
logs/setup/setup-steps2-9.log                     build-setup.sh -s 1 (stopped at step 9)
logs/setup/firemarshal-step9-guestmount-failure.log
logs/setup/setup-steps10-11.log                   CIRCT + cleanup
logs/setup/gemmini-rocc-tests-build.log
logs/baseline/spike-smoke.log
logs/baseline/verilator-build-j4.log
logs/baseline/baseline_matmul-try1-timeout-10Mcycles.log
logs/baseline/baseline_matmul.log                 the passing baseline (make output)
logs/baseline/baseline_matmul-sim-stdout.log
logs/baseline/baseline_matmul-RESULT.txt
logs/sparse/verilator-build-*.log                 every N:M sim build (try1/try2 = compile errors, try3 = width fix, try4 = fifo, nm48)
logs/sparse/nm24-rtl-*.log, nm48-rtl-*.log        every RTL test run, in order
logs/sparse/rtl-wip-backup.patch                  safety copy of the RTL edits taken before the stash for the stock build
```

---

# N:M sparsity work (overnight, 2026-10-06)

The work is on `sparse-nm` branches, which were later published to the `Hunter-Caraway` forks (see the README).
Three repos are involved:

| Repo | Commits |
|---|---|
| `generators/gemmini` | `b24e0430` bump submodules · `01f14010` RTL N:M mode · `47f5f15f` index FIFO |
| `generators/gemmini/software/libgemmini` (Spike model) | `761558c` sparse model · `cb3ffc7` latch at preload · `7679121` index FIFO · `a14aaa1` **upstream bug fix** (uninitialized state) |
| `generators/gemmini/software/gemmini-rocc-tests` | `e2e7e27` SW helpers · `8a11c1d` Gemmini wrappers + matmul test · `a7daeea` debug/perf tests · `61086b4` perf variants |

The design is generic N:M with M = 2N. The original tests passed for 2:4 and 4:8 on the Verilator RTL and for 2:4 on
Spike (no 4:8 Spike log was kept). The later code review found those tests could pass with sparse mode broken, so they
are being reworked.

## Design

- **What's pruned:** the stationary weights in weight-stationary (WS) mode, along K, independently for each output column.
  This matches NVIDIA's 2:4 semantics for a layer `y = x·W`.
- **Compressed format:** a K×J weight matrix becomes (K·N/M)×J kept values plus a same-shape index array. Each index is
  the row inside its M-group, log2(M) bits. A squashed DIM×DIM weight tile covers 2·DIM original rows.
- **Hardware** (`nm_sparsity = Some((n, m))` in `GemminiArrayConfig`; `None` leaves the dense hardware as it was):
  - Each PE holds a log2(M)-bit index next to its weight, double-buffered like the c1/c2 weight registers, and a mux
    that picks one of the M activations of its group.
  - The activation row is 2·DIM wide. The low half comes through the A port. The high half comes through the bias (b)
    port, so sparse mode has no bias input; preload the bias into the accumulator instead.
  - Indexes travel down the columns alongside the weights during preload.
  - Index rows come in with a new command (`NM_META_CMD`, funct 26). The Controller hands them straight to a 4-tile FIFO
    in the ExecuteController, skipping the reservation station. Each real sparse preload pops one tile, garbage
    (weight-reuse) preloads don't, and a preload stalls if its tile hasn't arrived.
  - `config_ex` rs1[10] turns sparse mode on.
- **New configs:** `GemminiNMRocketConfig` (2:4) and `GemminiNM48RocketConfig` (4:8), defined in
  `generators/gemmini/chipyard/GemminiConfigs.scala`, so the Chipyard repo itself is untouched.

## Tests (`gemmini-rocc-tests/bareMetalC`)

| Test | What it checks |
|---|---|
| `nm_sparse_sw` | CPU only: prune → compress → decompress → matmul round trip for 2:4, 4:8 and 1:2 |
| `nm_sparse_debug` | one sparse tile; scores the output against the correct result and 5 "broken this way" guesses |
| `nm_sparse_matmul` | 32×64×32 dense vs sparse on Gemmini, both checked against the CPU reference |
| `nm_sparse_perf` | 64×128×32 timing: dense, dense+bias, sparse (2 orderings), with/without weight reuse, plus CPU-only issue cost |

`./run-flow.sh tests` builds each as `*_24-baremetal` (`-DNM_N=2 -DNM_M=4`) and `*_48-baremetal` (`-DNM_N=4 -DNM_M=8`),
and checks that each compile really used that pattern.

## Original benchmark results: WITHDRAWN, kept only as a historical record

> **Withdrawn. Don't cite anything in this section.** These numbers came from the original test loop, which slowed
> down normal (dense) mode more than sparse mode. The later "fair" benchmark that replaced it has also been withdrawn,
> pending a corrected re-run (see the README). The 1.44× / 1.36× speed-ups below are not valid results.

64×128×32 matmul, int8 in, int32 accumulate; weights pruned to the pattern for both dense and sparse runs. "Array
busy" is the execute controller's compute-state cycles (`EXE_ACTIVE_CYCLE`).

| Variant | 2:4 total | 2:4 array busy | 4:8 total | 4:8 array busy |
|---|---|---|---|---|
| dense (no weight reuse) | 2217 | 1800 | 2248 | 1800 |
| sparse (no weight reuse) | 2977 | **960** | 3513 | **960** |
| dense, weight reuse | 3623 | 1344 | 3761 | 1344 |
| sparse, weight reuse | **2508** | **672** | **2771** | **672** |
| CPU-only issue, dense | 1551 | – | 1568 | – |
| CPU-only issue, sparse | 1995 | – | 2685 | – |

What this shows:
- **Array level: the sparse array does the same matmul in half the busy cycles** (1344 → 672 with reuse, the
  theoretical 2×; 1.9× without reuse). Same for 2:4 and 4:8.
- **End to end with weight reuse** (how Gemmini's real kernels run): **1.44× faster for 2:4, 1.36× for 4:8.**
- **Without reuse, sparse is slower end to end.** These bare-metal loops are bound by Rocket issuing RoCC commands:
  with no accelerator at all, just building the command stream takes 67–86% of the runtime (computed from the
  original logs by `fixes-wip/numbers.py`). Sparse adds 4 (2:4) or 8
  (4:8) metadata commands per tile, each 2 loads plus a RoCC. Moving metadata out of the reservation station (the FIFO
  commit) fixed correctness and ordering but not this, because the cost is on the CPU side.
- `nm_sparse_matmul` (32×64×32, small) shows the same thing: dense 543 vs sparse 815 cycles (2:4), 554 vs 1031 (4:8).

## Problems hit during the sparsity work

| Problem | Fix |
|---|---|
| Scala type errors (`flatten(r)` parsed as an implicit argument; `Vec` invariance on the now-generic `a` port) | Index a flattened local; wrap shifted outputs in `VecInit` |
| **RTL ignored the indexes** (hardware matched "index always 0", 256/256) | Scala initialization order: `ComputeCntlSignals` was built before `nm_row_bits` was defined, so the field was `UInt<0>`, which firtool constant-folds away. Found in the `.fir`; moved the width definitions above the bundle |
| Early sparse timing hugely inflated | Index packing was inside the timed loop; it's weight prep, so it moved out (`nm_pack_meta` / `nm_send_meta`) |
| Hardware counters reading more than the elapsed cycles | Some counters tick on stale control signals while idle; take a snapshot right when the work fences |
| Spike segfault / heap corruption after adding state fields | **Existing Gemmini bug**: `gemmini_state_t::reset()` never initialized `norm_stat_id` or the counter arrays, so out-of-bounds writes depended on leftover heap contents. Fixed in `a14aaa1`, a standalone commit if you want to upstream it. All 54 runnable tests are clean under AddressSanitizer |
| `rm` of a temp log blocked by a safety check (relative path) | Nothing was deleted. Logs now go to absolute paths under `logs/` |

## What I'd do next

1. **Move metadata off the CPU**: put indexes in memory, `mvin` them alongside the weights, and have the preload (or a
   sparse-aware `LOOP_WS` unroller) fetch them. That removes the per-tile RoCC cost, the reason sparse only wins with
   weight reuse today.
2. Support sparse mode in `LoopMatmul` so `tiled_matmul_auto` can use it (there's no hardware-loop path yet).
3. Pack the index metadata in DRAM (it's stored as int8 in the tests' C arrays, but only log2(M) bits are needed per weight).
4. Area/timing: the PE adds a log2(M)-bit register pair plus an M:1 mux; worth a synthesis run before scaling DIM.

## Re-running everything

`./run-flow.sh` in this folder (see `./run-flow.sh` with no arguments for the steps). Typical:

```bash
./run-flow.sh check          # env sanity
./run-flow.sh spike-lib      # build the Spike model (2:4; spike-lib nm48 for 4:8)
./run-flow.sh tests          # build tests incl. the _24 / _48 sparse variants
./run-flow.sh spike          # quick functional check (spike nm48 after spike-lib nm48)
./run-flow.sh sim nm24       # or nm48; sim dense only from Berkeley's base commits
./run-flow.sh fair           # the fair benchmark, once per seed -> verification/runs/fair-<stamp>/
./run-flow.sh bench nm24     # the original benchmark -> verification/runs/bench-nm24-<stamp>/
```

The Spike model's N:M is fixed at compile time (default 2:4); `spike-lib nm48` passes `NM_N=4 NM_M=8` to
libgemmini's Makefile.
