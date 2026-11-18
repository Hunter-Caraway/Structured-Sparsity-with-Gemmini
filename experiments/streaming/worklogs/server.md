# Server setup worklog: ai-1769.floridapoly.org (ai-user)

Goal: extra Verilator simulation capacity for the Gemmini N:M project, no root.
Server: AlmaLinux 10.2, glibc 2.39, 16 cores Xeon Gold 5118, 31 GiB RAM, 165 GB free /home.

## 2026-11-09: Miniforge
- `curl` Miniforge3-Linux-x86_64.sh, `bash Miniforge3.sh -b -p ~/miniforge3`. conda 26.9.4. Log `~/logs/miniforge.log`.
- ssh multiplexing: the scratchpad ControlPath was too long (>108 bytes), so the socket is `/tmp/claude-1000/cm-%C`.

## Step 1 (conda env), done by hand like on the laptop
- Base env: `conda install -n base -c conda-forge git conda-lock`.
- `git clone https://github.com/ucb-bar/chipyard.git ~/chipyard; git checkout bfa5699f`.
- The server's glibc (2.39) differs from the pin (2.34), so build-setup.sh would regenerate the lockfile and pick
  different tool versions. To keep Verilator, gcc and firtool identical to the laptop, step 1 runs by hand with
  the committed lockfile:
  `conda-lock install --conda $CONDA_EXE -p ~/chipyard/.conda-env conda-reqs/conda-lock-reqs/conda-requirements-riscv-tools-linux-64.conda-lock.yml`
  Script `~/step1.sh`, log `~/logs/step1.log`.

## Laptop exports (read-only, nothing committed/stashed on the laptop)
Scratchpad `export/{gemmini,libgemmini,rocc-tests}/`: `git format-patch base..sparse-nm`, `git bundle base..sparse-nm`
(gives identical commit hashes, so gemmini's submodule gitlinks resolve), `git diff HEAD --binary`, a tar of the
untracked non-ignored files, and `laptop.sha256` (all tracked and untracked working files).
Counts: gemmini 5 patches, 5 modified files. libgemmini 4 patches, 3 modified. rocc-tests 4 patches, 6 modified, 1 untracked (`bareMetalC/nm_sparse_protocol.c`).

## Step 1 done (13:35 to 13:44, 9 min)
- Chipyard cloned at `~/chipyard`, `git describe` = `1.14.0-36-gbfa5699f`. `.conda-env` is 5.3 GB.
- The server has no `rsync` and no `tar` (minimal image). Files are copied with laptop `tar -cf -` piped over ssh into
  `python3 tarfile` (filter="tar"). The project folder went to `~/gemmini-sparsity`. All 2308 files were checked with
  sha256sum against the laptop and match.
- Steps 2, 3, 5, 10 and 11 run via `~/step2.sh`: the env.sh conda block is written the same way the laptop's was, then
  `./build-setup.sh riscv-tools -s 1 -s 4 -s 6 -s 7 -s 8 -s 9`. Log `~/logs/step2.log`.
  Skipped: 4 (ctags), 6/7 (FireSim), 8/9 (FireMarshal).
- Step 2 (submodules, `--full`) took about 3 min. Step 3 (spike, pk, libgloss, libgemmini) took about 3 min.
  Base commits checked: gemmini `8c3f9923`, libgemmini `ea8f7ed`, gemmini-rocc-tests `7c540b3`.
  Spike: `~/chipyard/.conda-env/riscv-tools/bin/spike`. Stock libgemmini.so is installed in `$RISCV/lib`.
- Note: `git` and `conda` are not on PATH in a plain ssh shell. Use `source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh`.
- Steps 5 (sbt precompile), 10 (CIRCT firtool-1.75.0, matching the laptop) and 11 finished: `Setup complete!`, exit 0.
  build-setup took 13:44 to 13:59 (15 min).

## Simulator builds
- Script `~/buildsim.sh <CONFIG> <jobs>` sources env and runs `make -C sims/verilator -j<jobs> CONFIG=...`.
  It records the lowest MemAvailable seen during the build in `~/logs/minavail.<CONFIG>`. Logs go to `~/logs/build-<CONFIG>.log`.
- GemminiRocketConfig (stock) uses -j12 and was started from clean base trees (gemmini 8c3f9923, libgemmini ea8f7ed,
  rocc-tests 7c540b3, `git status` empty). No patches were applied yet.
- **GemminiRocketConfig (stock) built in 298 s (5 min)** at -j12. Min MemAvailable was 23 GB, so RAM is not tight.
  Binary: `~/chipyard/sims/verilator/simulator-chipyard.harness-GemminiRocketConfig`.
  Check: all 633 generated `.sv`/`.v` files in `gen-collateral` are byte-identical (sha256) to the laptop's stock
  build, and there are 0 files with `nm_sparse|nm_meta|nm_asm`.

## User code applied (after the stock build)
- `~/apply.sh`: in each repo, `git checkout -- .` (undoes the gemmini_params.h rewrite from elaboration), then
  `git fetch <bundle> sparse-nm:sparse-nm`, `git checkout sparse-nm`, `git apply --binary uncommitted.diff`, and
  extract untracked.tar. The bundle's commit count equals the format-patch count. HEADs are identical to the laptop
  (gemmini 639a5068, libgemmini a14aaa15, rocc-tests 61086b43).
- Checksums (all tracked and untracked non-ignored files compared with the laptop): gemmini MATCH (102 files),
  libgemmini MATCH (6), rocc-tests MATCH (121). `git status` is the same as on the laptop.
- The recorded fair binaries were copied to `~/fair-bin/` and their sha256 matches the run's SHA256SUMS.
- Validation runner: `~/runfair.sh <outdir> <chips...>` runs seeds 1 2 3 in parallel with the same make invocation
  as run-flow.sh (`run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 TIMEOUT_CYCLES=150000000 RANDOM_SEED=<s>`).
  Berkeley runs started in `~/validation/berkeley/`. GemminiNMRocketConfig build started (-j12).

## Status at handback (agent stopped early; work still in progress)
- Still running on the server when the agent stopped: the GemminiNMRocketConfig build (`~/logs/build-GemminiNMRocketConfig.log`)
  and the Berkeley validation runs (`~/validation/berkeley/`, `status` file).
- Not started yet: the GemminiNM48RocketConfig build (`bash ~/buildsim.sh GemminiNM48RocketConfig 12`), the nm24, nm48 and
  sameprog validation runs (`~/runfair.sh ~/validation/nm24 nm24 sameprog`, `~/runfair.sh ~/validation/nm48 nm48`),
  and the comparison with the laptop logs (laptop scratchpad `compare.sh berkeley nm24 sameprog nm48`).
- The server is NOT yet marked ready.
- Follow-up: `~/chain.sh` (log `~/logs/chain.log`) now runs the rest on the server without supervision. It waits for the
  2:4 build, starts the nm24 and sameprog runs (`~/validation/nm24/`), builds 4:8 (`~/logs/build-GemminiNM48RocketConfig.log`),
  then runs nm48 (`~/validation/nm48/`). It writes `CHAIN_DONE` or `CHAIN_ABORT`. When it finishes, run the laptop scratchpad
  `compare.sh berkeley nm24 sameprog nm48` and write SERVER READY only if every chip matches.
- GemminiNMRocketConfig (2:4) built in 410 s (-j12), min MemAvailable 23.5 GB. nm24/sameprog runs and the 4:8 build were started by chain.sh.

## Validation (main session, 2026-11-09 ~16:00 laptop time)
`compare.sh berkeley nm24 sameprog nm48`: 12/12 MATCH (4 chips x seeds 1-3), every line from `fair_perf:` to
`fair_perf passed` identical to `verification/runs/fair-20261103-151404`. Totals: berkeley dense=1555 dense_reuse=1541;
nm24 sparse=2281 sparse_reuse=1395 sparse_batched=2110; sameprog dense=1555; nm48 sparse=3170 sparse_reuse=1607
sparse_batched=2964.

SERVER READY
- Simulators: ~/chipyard/sims/verilator/simulator-chipyard.harness-{GemminiRocketConfig,GemminiNMRocketConfig,GemminiNM48RocketConfig}
- Run: `source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh; cd ~/chipyard/sims/verilator;
  make CONFIG=<cfg> run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 TIMEOUT_CYCLES=<n> RANDOM_SEED=1 BINARY=<abs path>`
- ssh helper (laptop): `. <scratchpad>/env.sh; ssh $SSHO $H '<cmd>'`
