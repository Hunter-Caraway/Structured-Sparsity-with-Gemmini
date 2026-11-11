# Structured Sparsity with Gemmini

Adding 2:4 and 4:8 structured (N:M) sparsity to UC Berkeley's [Gemmini](https://github.com/ucb-bar/gemmini)
AI accelerator in [Chipyard](https://github.com/ucb-bar/chipyard), and measuring it in cycle-accurate RTL
simulation (Verilator) against Berkeley's unmodified design.

## What this accomplishes

In N:M sparsity, every group of M weights keeps only N non-zero values (2 of every 4, or 4 of every 8). The
weights can then be stored compressed at half size, with small "position notes" (indexes) saying which values
were kept. In principle, the hardware does half the multiplications.

This project:

- **Adds a sparse weight-stationary mode to Gemmini's RTL.** Each processing element gets index registers and an
  M:1 mux that picks the right input activation for each kept weight. The indexes are sent with a new
  `NM_META_CMD` instruction (funct 26) into a 4-deep FIFO, and sparse mode is switched on with `config_ex`
  rs1[10]. There are two new chip configs: `GemminiNMRocketConfig` (2:4) and `GemminiNM48RocketConfig` (4:8).
- **Adds a functional model of the sparse mode to Spike** (Gemmini's `libgemmini` extension). Two known
  differences from the RTL (the a_hi address stride and the 4-tile index-queue limit) are being fixed. It also
  initializes more of `gemmini_state_t` in `reset`; some fields are still left uninitialized and are being fixed.
- **Adds software and tests.** `gemmini_nm.h` holds the prune/compress/pack helpers and the sparse-mode
  wrappers. The new tests are `nm_sparse_{sw,matmul,debug,perf}`, and the fair benchmark is
  `verification/fair_perf.c`.
- **Measures it against Berkeley's design.** The benchmark (`verification/fair_perf.c`) runs the same matmul on
  Berkeley's chip and ours, and checks every output against a CPU reference.

### Results: withdrawn, re-run pending

The cycle-count results previously published here have been **withdrawn**. A code review found problems in how
they were measured:

- **Different programs:** the comparison with Berkeley's chip used two different builds of the benchmark. Code
  placement alone changes the timings by several percent.
- **Cold caches:** each timed run included the processor's first-time instruction-cache misses, and these affect
  the sparse runs more.
- **Random starting state:** the "same cycle count as Berkeley with sparsity off" match depended on each
  simulator's random initial state.

The benchmark, the tests and the tooling are being fixed. New results will be published here only after a full
re-run with the corrected benchmark, run across several random seeds. Until then, please don't cite any earlier
numbers from this project, including the 1.44× / 1.36× figures in older drafts.

**Pattern comparison** (`verification/pattern_fidelity.py`; not a timing result): on synthetic Gaussian and
Laplace weights, 4:8 keeps 90–94% of the weights' energy (sum of squares), 2:4 keeps 87–92%, and NVIDIA's paired
4:8 keeps 79–86%.

## Credit: what's Berkeley's and what's ours

This project builds on open-source work from UC Berkeley's Architecture Research group (ucb-bar). All of the
following is **their** work, used under its BSD license:

- **[Gemmini](https://github.com/ucb-bar/gemmini)**: the systolic-array accelerator, its RTL, ISA, and
  configs. Cite: H. Genc et al., "Gemmini: Enabling Systematic Deep-Learning Architecture Evaluation via
  Full-Stack Integration," DAC 2021.
- **[libgemmini](https://github.com/ucb-bar/libgemmini)**: Gemmini's Spike (ISA simulator) extension.
- **[gemmini-rocc-tests](https://github.com/ucb-bar/gemmini-rocc-tests)**: Gemmini's test programs and the
  `gemmini.h` software library.
- **[Chipyard](https://github.com/ucb-bar/chipyard)**: the SoC framework, Rocket core, Verilator flow, and
  toolchain this all runs in.

**Our** work is only the `sparse-nm` commits on top of Berkeley's code, plus everything in this repository. In
the forks, the base commits keep their original Berkeley authors, and every commit on `sparse-nm` after the
branch point is ours:

| Repo | What we added or changed (diff vs. Berkeley's base commit) |
|---|---|
| `gemmini` (from `8c3f9923`) | +277/−20 lines in 10 Scala files: sparse mode in `PE`, `Tile`, `Mesh`, `MeshWithDelays`; index FIFO and `NM_META_CMD` in `ExecuteController`/`Controller`/`GemminiISA`; `GemminiNMRocketConfig` and `GemminiNM48RocketConfig` |
| `libgemmini` (from `ea8f7ed`) | +156/−27 lines in `gemmini.cc` / `gemmini.h`: the Spike model of sparse mode, and the `gemmini_state_t::reset` fix |
| `gemmini-rocc-tests` (from `7c540b3`) | 886 new lines: `include/gemmini_nm.h` and the `bareMetalC/nm_sparse_{sw,matmul,debug,perf}.c` tests |
| This repo | Benchmarks (`verification/fair_perf.c`, `berkeley_dense_perf.c`), the verification and analysis scripts, `run-flow.sh`, and setup notes |

To see exactly what we changed, compare against Berkeley's base, for example
`git diff 8c3f9923 sparse-nm` in the gemmini fork.

## Run it yourself

### 0. Quick checks (no Chipyard needed, seconds)

```bash
git clone https://github.com/Hunter-Caraway/Structured-4-8-Sparsity-with-Gemmini.git
cd Structured-4-8-Sparsity-with-Gemmini
pip install numpy pandas matplotlib
python3 verification/independent_math_check.py  # sparse math == dense math in numpy, with fault injection
python3 verification/pattern_fidelity.py        # share of weight energy kept by 2:4, 4:8, paired 4:8
```

`verify_all.py`, `cross_check.py`, `compare_runs.py` and the chart scripts read the withdrawn result logs. They
won't run until the re-run produces new results.

### 1. Install Chipyard

You need Linux with roughly 16 GB+ of RAM (32 GB+ for the bigger experiments) and about 60 GB of free disk.
Install Chipyard **1.14.0** (tested at commit `bfa5699f`) by following the
[Chipyard docs](https://chipyard.readthedocs.io/). [`chipyard-setup-notes.md`](chipyard-setup-notes.md) covers
the Fedora-specific problems I hit, including a `build-setup.sh` glibc bug.

**Chipyard must live at a path with no spaces or `:`** (the default is `~/chipyard`).

### 2. Switch Gemmini to the sparse-nm branches

The hardware and software changes are on a `sparse-nm` branch in each of three forks of Berkeley's repos. Each branch
starts from the commit that Chipyard 1.14.0 pins, so Berkeley's full history (and authorship) is kept underneath:

| Fork | Upstream | Branched from | Changes |
|---|---|---|---|
| [`Hunter-Caraway/gemmini`](https://github.com/Hunter-Caraway/gemmini/tree/sparse-nm) | `ucb-bar/gemmini` | `8c3f9923` | RTL: sparse PE mode, index FIFO, `NM_META_CMD`, 2:4 / 4:8 configs |
| [`Hunter-Caraway/libgemmini`](https://github.com/Hunter-Caraway/libgemmini/tree/sparse-nm) | `ucb-bar/libgemmini` | `ea8f7ed` | Spike functional model of the sparse mode + `reset` bug fix |
| [`Hunter-Caraway/gemmini-rocc-tests`](https://github.com/Hunter-Caraway/gemmini-rocc-tests/tree/sparse-nm) | `ucb-bar/gemmini-rocc-tests` | `7c540b3` | `gemmini_nm.h` helpers + `nm_sparse_*` tests |

The `gemmini` branch points its `libgemmini` and `gemmini-rocc-tests` submodules at the other two forks, so one
checkout gets all three:

```bash
cd ~/chipyard/generators/gemmini
git remote add nm https://github.com/Hunter-Caraway/gemmini.git
git fetch nm && git checkout -b sparse-nm nm/sparse-nm
git submodule sync software/libgemmini software/gemmini-rocc-tests
git submodule update --init software/libgemmini software/gemmini-rocc-tests
```

### 3. Build and run with `run-flow.sh`

Everything goes through one script (run `./run-flow.sh` alone to list every step). Set `CHIPYARD_DIR` if
Chipyard isn't at `~/chipyard`.

```bash
./run-flow.sh check          # tools, simulators, branches, python
./run-flow.sh spike-lib      # build + install the Gemmini Spike extension
./run-flow.sh tests          # build gemmini-rocc-tests, including the 4:8 variants
./run-flow.sh spike          # quick functional tests on Spike (seconds)
./run-flow.sh sim nm24       # build the 2:4 Verilator simulator (long)
./run-flow.sh sim nm48       # build the 4:8 Verilator simulator (long)
./run-flow.sh fair           # the fair benchmark on all chips (~15-40 min, in parallel)
./run-flow.sh checks         # all python checks + figures
./run-flow.sh all            # or all of the above in one go
```

New simulation runs go to `verification/runs/<stamp>/`. `run-flow.sh` blocks sleep while simulations run. The
steps that compare runs with the recorded results (`fair`, `checks`) will fail until new results are recorded. The
flow script is also being fixed.

**Berkeley's stock simulator.** For the baseline, `GemminiRocketConfig` has to be built from **unmodified**
Gemmini sources (check out `master` in all three repos, build it, then switch back to `sparse-nm`). Chipyard
rebuilds a simulator whenever Gemmini's Scala changes. So `run-flow.sh` runs the stock simulator with
`BREAK_SIM_PREREQ=1` and refuses to rebuild it from the sparse branch unless `FORCE=1` is set.

**Gotchas:**

- Spike's N:M pattern is fixed at compile time (2:4 by default). Rebuild libgemmini with `-DNM_N=4 -DNM_M=8`
  for 4:8.
- Chipyard's default `TIMEOUT_CYCLES` (10M) is too short; the script uses 150M.
- Use `run-binary-fast` with `LOADMEM=1` for timed runs. Plain `run-binary` writes a multi-GB instruction trace.

## Folder layout

| Path | What it is |
|---|---|
| `chipyard-setup-notes.md` | Installing Chipyard on Fedora 44, plus design notes from the sparsity work |
| `run-flow.sh` | The whole flow in one script: env check → Spike extension → tests → simulators → benchmarks |
| `verification/` | The benchmark and every check (see below) |
| `analysis/advanced_visuals.py`, `make_charts.py`, `chart_all_data.py` | Figure scripts. Their figures were withdrawn with the results and will be regenerated after the re-run |
| `logs/setup/` | Chipyard setup and build logs |
| `tools/report-builders/` | Scripts that generate the PDF reports |

### Inside `verification/`

| Path | What it is |
|---|---|
| `fair_perf.c` | The fair benchmark: identical lean loops on every chip (`-DDENSE_ONLY` build for Berkeley's) |
| `verify_all.py` | One command that re-checks the recorded results (needs results; see above) |
| `compare_runs.py` | Compares a new run folder with the recorded results, number for number |
| `nmdata.py` | Shared loader that reads every number straight from the logs |
| `cross_check.py` | Cross-checks logs, CSVs, re-runs and quoted numbers |
| `independent_math_check.py` | Sparse math vs. normal math in numpy, with fault injection |
| `pattern_fidelity.py` | How much of the weight energy 2:4, 4:8, and NVIDIA's paired 4:8 each keep (synthetic weights) |
| `paper_data.py` | Builds the paper's numbers and chart from the results |
| `bin/` | Compiled builds of the fair benchmark and the Berkeley dense benchmark |
| `run_fair.sh`, `run_berkeley.sh`, `rerun.sh` | The original one-off launch scripts (superseded by `run-flow.sh`) |
