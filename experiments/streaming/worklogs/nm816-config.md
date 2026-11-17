# nm816-config worklog (8:16 N:M build)

Agent: nm816 config agent. Started 2026-11-17. Laptop only (no elaboration, no Verilator, no server).
Bases: gemmini 11cc20cd, libgemmini d048776, rocc-tests 22158bf (all `sparse-loop-fix`). New branches: `nm816-config`.

## Steps
1. Read AGENTS.md, located 4:8 config: `src/main/scala/gemmini/Configs.scala:246` (nm48SparseConfig),
   `chipyard/GemminiConfigs.scala:25` (GemminiNM48RocketConfig), run-flow.sh `cfg_name/pat_nm/lib_nm` (l.128-149).
   8:16 math at DIM 16 int8: idx bits 4, index row 16*4 = 64 bits (at the require limit), tile 1024 bits = 8 spad rows,
   LdIdx tiles_per_mvin = 16/8 = 2.
2. Audit for m-specific code (semantic gaps). RTL: PE/Tile/Mesh/MeshWithDelays group by (n,m) generically
   (a_groups g = r/n, lanes g*m+i <= 31 since m = 2n); ExecuteController nm_rows_per_reg = 64/64 = 1 (same as 4:8),
   index loader widths log2Up(R)=3, irow log2Up(7R+1); LoopMatmul rows_per_tile 8 <= block_size 16, tiles_per_mvin 2.
   Constants 4 in the diff are the fifo depth, not m. Spike (gemmini.cc/h): nm_log2_ceil(16)=4, shifts <= 60, kd = (r/n)*m+idx.
   gemmini_nm.h: NM_MAX_M 16, NM_LOG2_M 4, row_bits 64 handled (mask special-case in nm_meta_regs_to_spad).
   Tests: only nm_sparse_spad.c has 2:4/4:8-only spec bytes (#if-guarded; not in run-flow's list). No semantic gap found.
3. Branch `nm816-config` in gemmini (from sparse-loop-fix 11cc20cd). Edits: Configs.scala:247 nm816SparseConfig,
   chipyard/GemminiConfigs.scala:31-36 GemminiNM816RocketConfig. libgemmini / rocc-tests: no edits needed (no branch).
4. sbt `;project gemmini; compile; project chipyard; compile` -> both [success]. Log worklogs/nm816-sbt.log.
5. Config construction (no hardware elaboration; scala runner on gemmini classpath): requires hold; rows_per_tile 24:4,
   48:6, 816:8. generateHeader() for 816 -> GEMMINI_HW_NM_N 8 / M 16 / SPAD_ROWS_PER_TILE 8 (saved to run folder).
6. run-flow.sh (branch fixb-results-test): cfg_name/pat_nm/lib_nm nm816|dense816, check lists, tests build _816,
   build_fair builds fair_perf_816 only when called with pat nm816 (spike nm816), sim usage. bash -n ok.
7. Spike proof, run folder experiments/streaming/investigate/runs/20261117-115410-nm816-spike/ (run.info, SHA256SUMS ok):
   spike-lib x6, tests (174 programs), spike nm816 97 pass / 0 FAIL (flow-logs/spike-20261117-115553.log), nm_sparse_loop
   22/22 cases ok, fair_perf_816 8/8 variants match CPU ref. Regression spike nm24 / nm48 97/0 each; their 4 libs are
   byte-identical (sha256) to runs/20261113-145855-fixb-final-spike. Bench (bench816.sh): 18/18 sbench passed (6 layers x
   full/fixa/loop). Mutants m1 (m-1-idx) and m2 (idx & 7) at gemmini.cc:635: 12/14 runs fail (only nm_sparse_sw passes:
   pure software); mutant libs deleted. Extra: nm_sparse_spad_816 passed (spec byte example skipped, #if m 4/8 only).
   Bench .bin/binaries moved to build-scratch/nm816-bench (48 MB), sha256 in run.info.

## RESUME HERE
- Done: all 6 verification items. Nothing running. No commits (coordinator commits).
- Uncommitted: gemmini `nm816-config` (Configs.scala, chipyard/GemminiConfigs.scala); gemmini-sparsity `fixb-results-test`
  (run-flow.sh, this worklog, nm816-sbt.log, run folder). libgemmini / rocc-tests unchanged (generic; no branch made).
- Findings: no semantic gap. Coverage gap only: nm_sparse_spad.c spec-example bytes exist for 2:4 / 4:8, not 8:16.
- Next (server, needs user approval): elaborate + build GemminiNM816RocketConfig (`FORCE_REBUILD=1 ./run-flow.sh sim nm816`);
  run-flow `fair` / `rerun` / `bench` still list only nm24 / nm48 (not extended); RTL runs of nm_sparse_*_816 + NEG.
