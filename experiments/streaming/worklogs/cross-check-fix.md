# cross-check-fix worklog
- cross_check.py rewritten to the run-flow.sh layout: bench-<cfg>-<stamp>/<test>.seed<S>.log + cycles.csv (seed,status
  columns) + run.info seeds=; rerun-<stamp>/orig-<c>-<t>.seed<S>.log. Tests now include nm_sparse_protocol.
- verify_all.py: section A wiring unchanged (rc 2 -> SKIP with reason, else check); sameprog missing counter -> FAIL.
- Tests (scratch /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/cc, synthetic bench):
  positive rc 0 (34 checks); NEG rc 1: csv mismatch, log w/o 'passed', 'mismatch' line, missing log, missing seed,
  rerun differs, rerun missing, csv status failed, csv missing; no bench -> rc 2. verify_all --skip-patches on scratch
  copy of fair-20261103-151404 (conda python): ALL CHECKS PASSED (75 checks, 4 skipped); bench mutant -> FAIL in A.

## RESUME HERE
- Done: all above. Running: nothing. Next: none; real bench run (./run-flow.sh bench) not yet available to test against.
