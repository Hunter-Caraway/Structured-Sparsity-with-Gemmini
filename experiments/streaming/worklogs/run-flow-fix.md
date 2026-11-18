# run-flow-fix worklog (agent, 2026-11-12)
Scope: run-flow.sh only. No build/sim/spike/make run (quota 0).

## Done (all 8 items)
1. `set -euo pipefail`; JOBS/RISCV/CONDA_DEFAULT_ENV defaulted; env.sh/conda.sh sourced under `set +u`; help sed keys on `^set -euo`.
2. spike-lib builds libgemmini out-of-tree (make -f lib Makefile -C scratch VPATH=lib, target libgemmini.so, never `install`) into build-scratch/libgemmini-<pat>/; spike/check use --extlib / that path.
3. tests: no build.sh (it has no output option; writes gemmini-rocc-tests/build). Builds matmul, mvin_mvout, nm_* with rv_cc into build-scratch/tests/bareMetalC (bm moved). Berkeley's other 54 tests are not built by this flow.
4. restore_params_h: git show HEAD:file -> scratch, cmp, cp (current file saved aside first).
5. sim: FORCE_REBUILD=1 required; backup_sim copies binary + generated-src to build-scratch/sim-backups/<stamp>-<cfg> with SHA256SUMS; stock refused unless all 3 repos at base (check now independent of FORCE).
6. clamp_par: default nproc, max 12, validates integer.
7. all make in sims/ via sims_make (flock). Runs are serialized (par forced 1) because sim_run goes through make; direct-binary parallel run not implemented (cannot validate flags without a sim run).
8. bench: log_num dies on missing number; row needs "<test> passed" line; zero perf rows dies.
Verified: bash -n, shellcheck clean, `help`/unknown step, log_num/clamp_par unit-tested standalone.

## Round 2 (2026-11-12)
T1 step_tests: dense list read from gemmini-rocc-tests/bareMetalC/Makefile (awk, read-only, excludes nm_*), must be 56 else die; all built with rv_cc into build-scratch/tests/bareMetalC. Ran `SCRATCH_DIR=/tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/spike-lib-test ./run-flow.sh tests` -> /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/spike-lib-test/tests.log: rc 0, 78 binaries (56 dense + 10 nm + 12 neg), no compile failures (only gcc warnings). gemmini_params.h was already committed; Berkeley repos untouched.
T2 `./run-flow.sh spike-lib` (same SCRATCH_DIR): built /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/spike-lib-test/libgemmini-nm24/libgemmini.so, log logs/runs/libgemmini-20261112-143742.log. $RISCV/lib/libgemmini.so before/after identical (mtime 2026-11-03 15:13:59, sha256 34578eb7...a592a): /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/spike-lib-test/riscv-before.txt, riscv-after.txt.
--extlib runs (/tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/spike-lib-test/spike-run.log, spike-run2.log): matmul rc0, mvin_mvout rc0, nm_sparse_sw_24 passed. FAIL: nm_sparse_matmul_24, nm_sparse_debug_24, nm_sparse_protocol_24 abort "GEMMINI: NM_META_CMD (funct 26): rd values 3..31 are reserved (rd = 0)"; nm_sparse_perf_24 tohost=1337.
Same failure with a plain in-dir build (copybuild/) so it is NOT the VPATH build. Cause is in libgemmini.so built from sparse-nm HEAD 2a6ff44 gemmini.cc:1801-1805 (rd==0 should match nm_meta_push_rd=0 yet falls to the else). Not fixed (Spike source out of scope). Installed .so (Nov 3) is pre-Fix-A (no "rd values" string).

## RESUME HERE
Done: all 8 round-1 items; tests builds 56 dense; VPATH libgemmini build verified working, toolchain untouched. Open: Spike model rejects rd=0 meta cmds (see above; needs spike agent); parallel runs; build-scratch/ not in .gitignore.

## Round 3 (spike --extlib order)
step_spike: --extlib now before --extension in all spike calls (incl NEG); added smoke run under LD_DEBUG=libs that dies if installed $RISCV/lib/libgemmini.so is loaded or the scratch lib is not. Help text line 11 says extlib must come first. bash -n + shellcheck clean.
Run: SCRATCH_DIR=/tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/spike-lib-test ./run-flow.sh spike -> /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/spike-lib-test/spike-step.log, rc 0: all 10 tests + NEG 4,6,7,9,10,14 pass. Installed .so sha256 unchanged (34578eb7...a592a).
Negative check of the detector: old order (--extension first) maps the installed lib (grep count shown in report).
Note: one accidental run without SCRATCH_DIR created repo build-scratch/; removed.
## RESUME HERE
Done: all above. Open: build-scratch/ not in .gitignore; parallel sims; spike log logs/runs/*.log untracked.
