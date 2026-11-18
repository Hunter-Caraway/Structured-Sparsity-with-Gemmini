# Merge plan: sparse-loop-fix into main (2026-11-13)

State at push (2026-11-13):

| Repo | Branch pushed | Commit | Target | Ahead / behind target |
|---|---|---|---|---|
| gemmini (RTL) | `fork/sparse-loop-fix` | 0db6cd09 | `sparse-nm` (d12b0840) | 1 / 0 |
| libgemmini | `fork/sparse-loop-fix` | d048776 | `sparse-nm` (2a6ff44) | 1 / 0 |
| gemmini-rocc-tests | `fork/sparse-loop-fix` | 22158bf | `sparse-nm` (25a6611) | 1 / 0 |
| gemmini-sparsity | `origin/spad-index-fix` | 7fd60dc (+ run-flow gap fix pending) | `main` | 2 / 0 |

All targets are direct ancestors, so every merge is a fast-forward (no conflicts).

## Gate (all must hold before merging)
1. Spike: done, `investigate/runs/20261113-145855-fixb-final-spike/` (all pass).
2. run-flow.sh gaps fixed (fair_perf rebuilt from source, all 54 dense tests in `spike`), re-run passes, committed on spad-index-fix.
3. Server, from the pushed commits (user approved nm24/nm48 rebuilds 2026-11-12):
   a. Dense config from sparse-loop-fix must be logic-equivalent to stock: differences allowed only in names, @[file:line], assert line numbers, the two dense-build asserts required by fix-b-spec 2.5.7, and the funct-26 RS bypass (Controller.scala:536-568, Fix A, known deviation; dense code never issues funct 26). User decision 2026-11-13 (option a); evidence worklogs/dense-verilog-diff.md. Paper says "logic-equivalent", not "identical Verilog". Done for 0db6cd09 by textual normalisation.
   b. Back up nm24/nm48 simulators and generated-src, rebuild.
   c. Verilator: 54 dense tests, nm_sparse_loop (22 cases incl. pad_J), RTL NEG N1-N10, N12, N13 (skip 110/140: Spike-only), benches incl. `_loop` programs, all output-verified.
   d. Copy back with checksums; parse_fixa.py / collect.py / verify_all.py rc 0.
4. User reviews results.

## Merge order (with user OK at each step)
1. libgemmini: `git checkout sparse-nm && git merge --ff-only sparse-loop-fix && git push fork sparse-nm`
2. gemmini-rocc-tests: same.
3. gemmini RTL: same (its submodule pointers already name the commits from 1 and 2).
4. gemmini-sparsity: PR `spad-index-fix` into `main` (AGENTS rule 5: no direct commits to main), merge after review.
5. Final run: one clean server run from the merged heads (stock + nm24 + nm48), recorded as the paper's run of record.

If a server run fails: fix on sparse-loop-fix (spec changelog first if semantics change), re-run Spike and the failing server step, then resume the gate.
