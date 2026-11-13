# fixb-server worklog (sparse-loop-fix server gate, merge-plan step 3)
Scratch (laptop): /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-srv/
Server scratch: ~/fixb/
Sources of truth: RTL 0db6cd09, libgemmini d048776, rocc-tests 22158bf (laptop clean).

## Step 0: sync (done)
- Server trees were Fix A working trees (no git on server). Compared sha256 of all tracked+untracked files (list.sh):
  12 gemmini-repo files differed/missing; 11 pre-existing ones backed up to ~/fixb/backup-src (+ ~/fixb/backup-src.sha),
  new ones staged in ~/fixb/new-src, then copied into ~/chipyard/generators/gemmini.
- After: laptop vs server list of all 231 gemmini-repo files: identical (laptop-before.sha vs server-after.sha in scratch).
  Server gemmini_params.h is now the laptop committed one (old generated 4:8 one saved in ~/fixb/backup-src).

## Step 1 (dense Verilog check)
- Script ~/fixb/dense_elab.sh: make verilog CONFIG=GemminiRocketConfig generated_src_name=generated-src-fixb-dense (separate gen dir, no Verilator);
  backs up/restores gemmini_params.h (elaboration rewrites it), checksums stock sim + stock generated-src before/after. Log ~/fixb/logs/dense-elab.log, status ~/fixb/logs/DENSE_STATUS. Started 15:10:12.

## Step 3 (programs, laptop build, done)
- Scratch .../scratchpad/fixb-srv/{tests,sbench,fair}: `SCRATCH_DIR=$S ./run-flow.sh tests` rc 0 ("134 bare-metal tests built (54 dense ...)", tests-build.out);
  `BIN_DIR=$S/sbench build.sh` 6 layers rc 0 (sbench-build.out); fair/ via cc.sh (fair_perf_24/48, dense_only, berkeley_dense_perf) from verification/*.c.
- Copied to ~/fixb/progs; 186 files, sha256 laptop-progs.sha == server-progs.sha (cmp identical).

## Step 1 result (dense Verilog check): NOT identical to stock
- ~/fixb/logs/DENSE_STATUS: DENSE_ELAB_EXIT=0 (3 min). gen dir ~/chipyard/sims/verilator/generated-src-fixb-dense (separate). Stock sim sha 84c2264a... and stock generated-src (1422 files, ~/fixb/stock-gensrc.sha vs logs/stock-gensrc.after) unchanged; gemmini_params.h restored (3758ae96...).
- 17 of 633 .sv/.v differ (summary ~/fixb/dense-diff/summary.txt, full.diff, *.stripped.diff). 9 differ only by `@[src:line]` comments (LoopMatmulLd*/StC*, PE_256, RocketTile, TagQueue, Tile).
  Assert source-line numbers only: LoadController, LoopMatmulExecute, Mesh, LoopMatmul, ReservationStation (+ signal renames is_loop_config_cmd -> _ws, wraps_around_sum_1 -> _2).
  After normalising comments/renames/assert line numbers: LoopMatmul, LoopMatmulExecute, ReservationStation, Mesh 0 diff lines.
  Real logic diffs: Gemmini.sv (NM_META_CMD funct 26 dense-build assert + RS alloc gating, from d12b0840/47f5f15f), ExecuteController.sv (442 stripped lines) and MeshWithDelays.sv (4694 stripped lines, new `mesh_io_in_a_RegShifted*` regs) (from sparse-nm commits before sparse-loop-fix; Fix B does not touch ExecuteController/MeshWithDelays/Mesh/PE/Tile).
  So the sparse-loop-fix delta alone (d12b0840..0db6cd09) is not separable without a second elaboration; dense GemminiRocketConfig differs from stock already at d12b0840 (spec of Fix A "dense build unchanged" is not met at the Verilog level).
- Decision: reported in hand-back; continued with steps 2-5 (independent).

## Step 2 (backup + rebuild): ~/fixb/backup_build.sh, nohup setsid, status ~/fixb/logs/BUILD_STATUS, log ~/fixb/logs/chain.log; backup ~/backup-prefixB-20261113 (SHA256SUMS).
- Backup ~/backup-prefixB-20261113 verified (sims nm24 c9664cc0..., nm48 4b414e5a... + generated-src 1461 files nm48; SHA256SUMS inside; logs ~/fixb/logs/bk-*.sha, chain.log).
- BUILD FAILED at elaboration of GemminiNMRocketConfig (15 s): `java.util.UnknownFormatConversionException: Conversion = 'Unescaped % ...'
  fmt = "sparse-loop-fix: sparse loop needs an even K tile count and pad_K == 0 (K % 2*DIM)"` at gemmini.LoopMatmul (LoopMatmul.scala:1371). Log ~/fixb/logs/build-GemminiNMRocketConfig.log:91-97.
  Cause: Chisel assert message is a printf format; `%` must be `%%`. RTL bug in pushed commit 0db6cd09; the Spike abort text (gemmini.cc:953) and run-flow loop_neg_msg 6) use the same text, so a fix must keep the printed text "(K % 2*DIM)".
  No source edited by this agent. The Spike-only fixb-final-spike run could not catch it.
- State after failure: server sims unchanged (nm24 c9664cc0, nm48 4b414e5a, stock 84c2264a); nm24 generated-src partly rewritten by the failed elaboration (backup holds the original; the nm24 sim binary is unchanged); gemmini_params.h restored to the committed one (3758ae96).

## RESUME HERE
Done: step 0 sync (231 files match), step 1 dense elaboration + diff (differs from stock, see above), step 2 backup (verified), step 3 programs built and copied (sha match).
Blocked: step 2 rebuild fails on the `%` assert format bug above. Needs an RTL fix on sparse-loop-fix (user/coordinator), re-sync the fixed LoopMatmul.scala (and Spike/tests if text changes), then:
  `ssh ... 'cd ~/fixb; nohup setsid ./backup_build.sh ...'` (change BK dir name or skip the backup part: backup is already taken; delete the backup block, keep the build loop).
Prepared and ready: ~/fixb/jobs-fixb.txt (224 jobs: stock 12, nm24 106, nm48 106), ~/fixb/run_jobs.sh (stock|nm24|nm48; run with `nohup setsid ~/fixb/run_jobs.sh ~/sinv/runs/<stamp>-fixb-srv ~/fixb/jobs-fixb.txt`).
  NOTE: the tests/NEG binaries may need a rebuild if the fix changes the assert text; programs in ~/fixb/progs (laptop scratch fixb-srv/).
Not started: steps 4 and 5 (no simulation run).
