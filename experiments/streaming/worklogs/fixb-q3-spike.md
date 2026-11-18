# fixb-q3-spike: Spike instruction count of Berkeley's dense tiled_matmul_auto (fix-b-spec.md [Q3]), 2026-11-12

Scope: laptop, Spike only. No server, Verilator, simulator rebuild or git write. fix-b-spec.md not edited.
Run folder (all numbers below): `experiments/streaming/investigate/runs/20261112-205136-q3-spike/` (= R).

## Steps
1. Read AGENTS.md, fix-b-spec.md 5, spike-meta-rd.md, run-flow-fix.md. Layers = gen/gen_data.py LAYERS (M, K, N):
   edge 36x128x64, small 64x256x128, bert_qkv 128x768x768, rn50_conv 196x2304x256, bert_ffn1 128x768x3072,
   bert_ffn2 128x3072x768.
2. Headers: gemmini-rocc-tests `include/gemmini_params.h`, `gemmini.h`, `gemmini_testutils.h` are byte-identical to
   Berkeley base 7c540b3 (script checks with `git show | cmp`, dies otherwise). params.h sha256 3758ae96...8da924
   (R/rt/run.info). DIM 16, so the same parameters as the stock chip.
3. Lib choice: the installed `$RISCV/lib/libgemmini.so` (sha256 34578eb7...a592a) is the project's pre-spad-index-fix
   N:M model, not Berkeley's. For a stock count the script builds Berkeley's model from libgemmini base ea8f7ed
   (`git show`, read-only) with the g++ command of that commit's Makefile, into the scratchpad
   (sha256 54876c3a...eec12, R/rt/run.info). `$RISCV` untouched (script compares the installed lib's sha before/after).
   The instruction count is a CPU-side number, so it should not depend on the model; checked: edge and bert_qkv on the
   pre-spad-index-fix 2:4 model give the same instret (400 and 3212, R/rt/logs-nm24lib/{edge,bert_qkv}.log:2).
4. New files (this repo only): `src/q3_dense_icount.c`, `scripts/q3_dense_icount.sh`, `tools/q3_trace_count.py`
   (stdlib). The call is the one stream_bench.c's `berkeley` variant makes (WS, full_C int32, no bias). Two counts:
   `dense_icount` (constant dims) and `dense_icount_rt` (dims from volatiles). Each is verified twice: every value of
   C against a CPU matmul, and the host hash + sampled rows of data.h. Spike: `--extlib` before `--extension`.
5. Ran all six layers (about 55 s total; no layer needed scaling). All verified, rc 0.
6. Cross-check with `spike -l` for all six layers: trace instructions between the two rdinstret == rdinstret delta
   ("match" in R/rt/logs/<layer>.trace.txt). The same trace gives the RoCC command counts by funct7.
7. Extra: `-DQ3_CONST_ONLY` build (one call site; gcc inlines and folds the tile-size search): R/const-only/.

## Results [M] (Spike, CPI 1; cycles = rdcycle delta, 2 more than instret because the rdcycle pair sits outside the
rdinstret pair)
| layer | M x K x N | instret rt | cycles rt | instret const-dims | instret const-only build | LOOP_WS calls | RoCC cmds | verified |
|---|---|---|---|---|---|---|---|---|
| edge | 36x128x64 | 397 | 399 | 400 | 125 | 1 | 11 | yes |
| small | 64x256x128 | 463 | 465 | 466 | 124 | 1 | 11 | yes |
| bert_qkv | 128x768x768 | 3,209 | 3,211 | 3,212 | 1,991 | 20 | 125 | yes |
| rn50_conv | 196x2304x256 | 4,827 | 4,829 | 4,831 | 4,151 | 36 | 221 | yes |
| bert_ffn1 | 128x768x3072 | 11,994 | 11,996 | 11,998 | 7,619 | 78 | 473 | yes |
| bert_ffn2 | 128x3072x768 | 10,051 | 10,053 | 10,055 | 8,889 | 80 | 485 | yes |
Sources: rt = R/rt/logs/<layer>.log:4; const-dims = R/rt/logs/<layer>.log:2; const-only = R/const-only/logs/<layer>.log:2;
calls (funct7 8 = k_LOOP_WS) and RoCC commands = R/rt/logs/<layer>.trace.txt:4. The gemmini_fence after the call adds 3
instructions (instret_with_fence, same lines). RoCC commands = 5 configs (funct 0) + 6 per LOOP_WS call (functs 8-13).

## Against fix-b-spec.md 5.1 (derived from the table and the spec's Fix A 2:4 baseline numbers)
- Spec assumed 40-100 instr per call, 4-30 calls, 0.2-3k instr per layer. Measured: 1-80 calls, 0.4k-12k instr per
  layer, about 126-160 instr per call on the multi-call layers (rt instret / calls: qkv 160, rn50 134, ffn1 154,
  ffn2 126). The estimate is too low for the four big layers (qkv 3.2k vs <=3k, ffn1 12.0k = 4x the upper bound).
- Berkeley dense rt instret as a share of the Fix A 2:4 count in spec 5.1: edge 397/2,469 = 16.1%; small 463/7,743 =
  6.0%; bert_qkv 3,209/287,902 = 1.11%; rn50_conv 4,827/488,259 = 0.99%; bert_ffn1 11,994/1,153,201 = 1.04%;
  bert_ffn2 10,051/1,120,035 = 0.90%. So ">99% removed" holds only for rn50_conv and ffn2 (99.0%, 99.1%); qkv and
  ffn1 are 98.9% and 99.0%; small 94.0%; edge 83.9%. The conclusion (CPU issue cost nearly gone on big layers) stands.

## Caveats
- This is Berkeley's dense loop, not Fix B. A sparse LOOP_WS call would add commands (index addresses), and the tile
  split may differ, so the Fix B count is still [E].
- Spike counts instructions, not Rocket cycles; RoCC commands block on a real chip.
- The count depends on the compiler: gcc 16.1.0 -O2 (R/rt/run.info). With one inlined call site and constant dims it
  drops to the const-only column; the recorded stream_bench `berkeley` variant passes dims at run time, so rt is the
  comparable number.
- Verified data is the 2:4 data set (dense W with the pruned zeros); a dense instruction count does not depend on values.
- Binaries and the stock lib stay in the session scratchpad (sha256 in run.info); rebuild with the script.
- shellcheck: one SC2054 false positive on `-Wa,-march=rv64gc` (same line as build.sh).

## RESUME HERE
Done: all six layers measured and verified, trace cross-check matches on all six, logs + SHA256SUMS in R.
Running: nothing.
Findings: table above; spec 5.1 call count and per-layer estimate are low by up to 4x on big layers, ">99%" is ~99%.
Next (spec agent / coordinator): update fix-b-spec.md 5.1 and [Q3] from this worklog; decide whether the three new
files get committed (untracked now).
