# Branch status: `fixb-results-test` (2026-11-17)

Source of every number below: `worklogs/fixb-verify.md` (independent re-check of the raw logs). Run folders are under
`experiments/streaming/investigate/runs/`.

## What this is

A test branch, cut from `spad-index-fix`. It holds the Verilator (RTL simulation) results for **Fix B**
(`sparse-loop-fix`): sparse mode inside Gemmini's `LOOP_WS` hardware loop, so one command runs a whole tiled matmul
instead of the CPU issuing one command group per tile. Nothing here is merged to `main`.

## What the branch has vs `main`

This repo (`git log main..HEAD`, 4 commits; run data and worklogs of this session are still uncommitted and go in the test-branch commit):
- `e06b436` spad-index-fix (Fix A): benchmarks, scripts, run data, agent rules, worklogs.
- `7fd60dc` sparse-loop-fix: benchmarks, run-flow and parser support, spec changes, code sweep fixes, run data.
- `9d7b5e9` run-flow.sh: the Spike step rebuilds `fair_perf` from source and runs all 54 dense tests; merge plan.
- `43b5e0b` CLAUDE.md, AGENTS.md: rule edits.

Fork repos, branch `sparse-loop-fix` vs `sparse-nm` (one commit each; read-only check):
- RTL (`generators/gemmini`): `0db6cd09` adds the sparse mode in `LOOP_WS` (new hardware, only on N:M configs, with
  sim-time asserts). `11cc20cd` escapes `%` in the N6 assert message (Chisel printf format).
- Spike model (`libgemmini`): `d048776` adds funct 27 (`LOAD_IDX`, loads index rows) and funct 28
  (`LOOP_WS_CONFIG_NM`), the sparse `LOOP_WS`, and a `NM_DENSE_BUILD` switch.
- Tests (`gemmini-rocc-tests`): `22158bf` adds the helpers, the `nm_sparse_loop` positive test (22 cases) and the NEG tests
  (tests that must trigger an assert).

## Results

Runs (server, Verilator, three chips: stock = Berkeley's, nm24 = 2:4, nm48 = 4:8):

| Run folder | What | Result |
|---|---|---|
| `20261113-160015-fixb-srv` | 224 jobs (106 nm24, 106 nm48, 12 stock) | 150 exit 0, 74 exit 2; `fixb-verify.md` A, C |
| `20261115-225958-fixbfail-srv` | re-runs at 600M cycles: nm_sparse_loop 24/48, stock gemmini_counter, stock global_average | nm_sparse_loop passes 22/22 on both chips; stock counter and global_average fail |
| `20261115-230636-fixbfail2-srv` | `nm_loop7_24/48` (cases 7-17 only, per-case `CYC` lines) | both exit 0, 11 CYC lines each |

Integrity: R1 `sha256sum -c` 389/389 OK. In the other two, only `run.out` fails its listed hash, and the mismatch is
proven stale by content (all but its last `done:` line hashes to the recorded value) (`fixb-verify.md` A).

NEG tests: the 74 exit-2 jobs are 62 NEG jobs (52 `nm_sparse_loop_negNN`, 10 `nm_sparse_protocol_negN`) plus 12 real
failures. Each of the 62 logs has exactly one assert and the text matches `run-flow.sh` (0 mismatches)
(`fixb-verify.md` C). The 150 exit-0 logs show no hidden failure; all 36 bench logs print a verified line.

Dense tests: 54 per N:M chip (= Berkeley's list). 5 fail on each nm chip (list below), so 49/54 by count of `jobs.tsv`
exit codes in `20261113-160015-fixb-srv/jobs.tsv` (coordinator recount 2026-11-17 against
`20261113-145855-fixb-final-spike/dense54/list.txt`: 49/54 on nm24 and nm48). `fixb-verify.md` "48/54" is a miscount. 3 of the "passes" test nothing (`worklogs/berkeley-issues.md` B6).
The stock chip ran no dense tests in R1.

### Speed-up (same chip, same build, cycles; berkeley / sparse_loop)

Source: `fixb-verify.md` E, from `<chip>.<layer>_<24|48>_{full,loop}.seed1.log` in `20261113-160015-fixb-srv`.
All outputs verified (`-> verified` line per variant).

| chip, layer | berkeley | sparse_loop | berkeley / sparse_loop | sparse_stream / sparse_loop |
|---|---|---|---|---|
| nm24 rn50 | 661,441 | 519,145 | 1.274 | 2.237 |
| nm48 rn50 | 661,155 | 515,414 | 1.283 | 2.619 |
| nm24 ffn1 | 1,438,096 | 1,207,250 | 1.191 | 2.170 |
| nm48 ffn1 | 1,438,269 | 1,234,319 | 1.165 | 2.429 |
| nm24 ffn2 | 1,763,305 | 1,313,347 | 1.343 | 1.931 |
| nm48 ffn2 | 1,761,069 | 1,304,067 | 1.350 | 2.234 |
| nm24 qkv | 317,206 | 305,747 | 1.037 | 2.152 |
| nm48 qkv | 316,584 | 307,018 | 1.031 | 2.420 |

(`fixb-verify.md` also has edge and small, 1.069-1.147 for berkeley/sparse_loop.)
`sparse_stream` is the per-tile streaming tiler (`stream_bench.c:5-7`), not Fix A.

Stock chip, berkeley (`stock.<layer>_24_dense.seed1.log`): rn50 661,820, ffn1 1,438,072, ffn2 1,763,263, qkv 317,164.
Cross-chip (different builds, allowed by the 2026-11-12 ruling, label as cross-chip): nm berkeley vs stock berkeley is
within -0.18% to +0.54% on the big layers; nm48 rows also use 4:8 data, so nm48-vs-stock is cross-data too.

### fair_perf (i=64, k=128, j=32; seeds 1-3 identical)

`sparse_loop` is SLOWER than per-tile dense at this size. Cycles from `fixb-verify.md` E:
- nm24: dense 1,544, dense_loop 3,119, sparse_loop 2,779 (dense_loop / sparse_loop = 1.122, i.e. sparse_loop beats
  dense_loop, the non-sparse `LOOP_WS` loop, but not per-tile dense); sparse_spad 961.
- nm48: dense 1,475, dense_loop 3,126, sparse_loop 2,805 (1.114); sparse_spad 1,037.
The 1.122/1.114 ratios compare sparse_loop with `dense_loop`, not with per-tile `dense` (which is faster than both).

### The 12 failures (non-NEG, R1)

| Job (nm24 and nm48) | Cause class | Label |
|---|---|---|
| nm_sparse_loop_24/48 (timeout at 20,000,001) | job budget too small; passes 22/22 at 600M (`20261115-225958-fixbfail-srv`) | proven (cases 7-17 alone sum to 28.6M / 29.7M CYC, `20261115-230636-fixbfail2-srv`) |
| gemmini_counter | Berkeley bug, fails identically on stock at `[132145000]` | proven (B4) |
| global_average | Berkeley bug, Output == Gold yet `Fail`, stock too at `[1037035000]` | missing fence proven by source; race as cause is inference (B5) |
| conv_with_input_dilation, _and_rot180, _and_neg_padding | timeout at 150,000,001 in the test's own CPU reference conv | estimate only, never run to completion; neg_padding estimate (~127M) is below 150M, so unexplained |

## Production-ready verdict: NOT production ready

Blockers (`fixb-verify.md` Verdict) and what clears each:
1. The three `conv_with_input_dilation*` tests never finished on any chip. Clears: a run with budget >= ~200M cycles.
   User approved a 300M run on nm24 (pending launch; the SSH socket expired 2026-11-17). `fixb-verify.md` also
   recommends stock as a control.
2. Dense tests were not run on the stock chip, so there is no same-run stock baseline. Clears: run the 54 on stock.
3. Source identity is not proven end to end: no source list taken at build time, and `run.info` cites the wrong list.
   Clears: record a post-build source list in the final run.
4. Parser gaps: stock logs not judged at all, `nm_loop7` misjudged as FAIL, gate 3d (parse_fixa/collect/verify_all rc 0) not met.
   Clears: fix `parse_fixa.py`, re-run to rc 0.
5. `nm_sparse_loop` server budget (20M) too low; `run-flow.sh` default 150M is not shown to be enough (full run ~63M is an
   estimate). Clears: use a measured budget (600M passed).
6. The sparse_stream comparison label (below) must be right before any paper use. Clears: use the corrected label.

What is proven: sim and source identity for the sync list, 62/62 NEG asserts, no silent failures, 22/22 nm_sparse_loop at
600M, headline numbers recomputed exactly.

## Known discrepancies

- `run.info` (R1-R3) says `src.gemmini.sha256list=641086db... RTL 0db6cd09`. That is the list taken before the fix
  re-sync; the sims were built from `11cc20cd`. The correct list is `20261113-161500-fixb-srv-sync/server-now.sha`
  (`fixb-verify.md` B).
- Label: earlier text said "Fix B vs Fix A sparse_stream 2.24x/2.62x". The numbers are right (2.237, 2.619) but
  `sparse_stream` is the per-tile streaming tiler, not Fix A; Fix A is `sparse_fixa`, which was not run on rn50
  (`fixb-verify.md` E). Correct wording: "sparse_loop vs the per-tile streaming tiler (sparse_stream)".
- Dense pass count: `fixb-verify.md` says 48/54; the 5 listed failures per chip give 49/54 (`jobs.tsv`). Resolved: 49/54 (coordinator recount, see Results).
- R1 has no `run.out`; R2/R3 `run.out` hash entries are stale (benign).
