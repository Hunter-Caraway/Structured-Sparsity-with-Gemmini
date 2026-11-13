# fixb-final-spike worklog
Scratch: /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final. Start 2026-11-13T14:54:43-05:00

## Progress (14:57:24)
- Step 1 done: 4 libs rc 0, sha match expected (log /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final/spike-lib-*.out). RISCV libgemmini.so sha 34578eb7...a592a before.
- Step 2 done: tests rc 0, "134 bare-metal tests built (54 dense ...)" (/tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final/run-flow-tests.out).
- Step 3 done: spike nm24/nm48 rc 0, 45 pass each (/tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final/spike-nm24.out, spike-nm48.out). NOTE: run-flow spike runs only 2 dense tests
  and used STALE verification/build/fair_perf_* (dated 11-03); so I ran 54 dense myself on both libs: /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final/dense54/ (all rc 0), and fresh fair_perf in /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final/fair.
- Step 4 running: /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final/t2.sh (round1, out /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final/t2/), /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final/r2root/r2tests/r2.sh (round2, out /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final/r2out/). t2.sh needed mkdir t2 first.
- Step 5 running: /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final/bench.sh -> /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/fixb-final/bench/ (52 programs).
- Step 4 done: round1 16 mutants + N1-N14 all KILLED (t2/mutants.summary); round2 n13-start-only, pad-j-ignored KILLED (r2/mutants.summary). pos r2: 22/22 cases both pats.
- Step 5 done: 52 programs rc 0, all verified/passed (bench/); fair_perf 8/8, 8/8, 3/3 match incl dense_loop, sparse_loop. collect synth rc0 12/12, raw rc1 0/12, notiles rc1 11/12, parse_fixa rc0.
- Step 6 done: instret identical to RUN3 on all 12 layer/pattern rows (experiments/streaming/investigate/runs/20261113-145855-fixb-final-spike/instret.tsv).
- Run folder: experiments/streaming/investigate/runs/20261113-145855-fixb-final-spike. RISCV libgemmini.so sha unchanged.

## RESUME HERE
All steps done; nothing running. Only remaining: coordinator reads hand-back. Anomaly: run-flow spike uses stale verification/build/fair_perf_* (dated 11-03); only 2 dense tests in spike step.
