# fixb-verify: independent verification of the Fix B (sparse-loop-fix) Verilator runs

Agent: independent verifier (2026-11-17). Read-only on runs, logs, sources. No sims, rebuilds, commits.
Runs (local, `experiments/streaming/investigate/runs/`):
R1 `20261113-160015-fixb-srv`, R2 `20261115-225958-fixbfail-srv`, R3 `20261115-230636-fixbfail2-srv`.

## Step log

### A. Integrity (2026-11-17)
- `sha256sum -c SHA256SUMS`: R1 389/389 OK. R2 12 OK, `run.out: FAILED`. R3 8 OK, `run.out: FAILED`.
  Sync folder `20261113-161500-fixb-srv-sync` 7/7 OK.
- Only file not listed in each SHA256SUMS: `STATUS` (expected, written after).
- Stale run.out proven by content: `head -n -1 run.out | sha256sum` equals the recorded hash in both R2
  (0644d99b...) and R3 (4c3b6977...). The only post-hash line is `done: /home/ai-user/sinv/runs/<run>`.
  mtimes: R2 SHA256SUMS 14:04:20.700, run.out 14:04:20.705; R3 10:32:38.357 vs 10:32:38.362.
- R1 has no `run.out` file at all (not in SHA256SUMS either). STATUS `ALL_DONE Sun Nov 15 10:57:43 PM EST 2026`.
- R1 jobs: `jobs-20261113-160018.txt` 224 rows == `jobs.tsv` 224 data rows (sorted chip/binary/seed/timeout identical, `diff` empty).
  No duplicate (chip,binary,seed). 106 nm24 + 106 nm48 + 12 stock. Every job has `<chip>.<bin>.seed<N>.log` (224 logs).
  162 binaries in `bin/`. SHA256SUMS 389 = 224 logs + 162 bins + run.info + jobs.tsv + jobs-*.txt.
- R1 exits (jobs.tsv col 8): 150 x 0, 74 x 2. Log endings: 150 `Verilog $finish` (no `$stop`, no assert);
  74 `Verilog $stop` with exactly 1 `Assertion failed`. Exit and ending agree for all 224.

### C. NEG asserts (R1)
- 62 NEG logs (52 nm_sparse_loop_negNN, 10 nm_sparse_protocol_negN): each has exactly one `Assertion failed in` line.
  Message text (after `Assertion failed: `) contains run-flow.sh `loop_neg_msg`/`neg_msg` (working-tree run-flow.sh:90-125) for all 62, 0 mismatches.
- N6 (neg60/61) printed text: `... pad_K == 0 (K % 2*DIM)`, single `%`; no `%%` in any neg6x log.
  (protocol NEG=6 is Spike-only: run-flow.sh:88 `neg_rtl=(4 7 9 10 14)`; not in R1.)
- neg_msg 10 -> N1 text: justified. Protocol NEG==10 at tests 22158bf is `ROCC_INSTRUCTION_RS1_RS2(XCUSTOM_ACC, 0, 0, k_LOOP_WS)`
  after begin(1) (sparse on), i.e. dense LOOP_WS in sparse mode = N1 condition. fix-b-spec.md:232 "N2 replaces the LOOP_CONV_WS half of the
  existing Controller.scala:281 message (the LOOP_WS half is replaced by N1)". No dated changelog line for the run-flow change (not a spec change).

### B. Simulator and source identity
- run.info R1/R2/R3 are byte-identical in sim lines: stock 84c2264a... mtime 2026-11-09T14:04:32; nm24 1042fc92... mtime 2026-11-13T15:56:35;
  nm48 f4a3642c... mtime 2026-11-13T16:00:15. nm24/nm48 equal the post-rebuild values in fixb-server.md:50. Stock equals
  20261111-183018-fixa-srv/run.info and 20261109-204637-keeper3-srv/run.info (`sim.stock=... sha256=84c2264a...`); fix-a-server.md:36,73.
  This is the sha the server script recorded; I cannot re-hash the server binaries (no server access used).
- run.info `git.gemmini=639a5068 (uncommitted changes)` etc. are the server trees' stale HEADs (server copies were synced by file, fixb-server.md:7);
  they prove nothing about content. 639a5068 is the parent of d12b0840 locally.
- run.info `src.gemmini.sha256list=641086db... (~/fixb/server-after.sha)`: reproduced as `grep ' G/' server-after.sha | sha256sum` = 641086db.
  DISCREPANCY: server-after.sha is the step-0 list, BEFORE the 11cc20cd re-sync. It has LoopMatmul.scala becc5117 = `git show 0db6cd09:...` hash,
  not bcf042ea = 11cc20cd. So run.info cites the wrong (pre-fix) list; the line also says "RTL 0db6cd09", but the sims were built from 11cc20cd.
- The correct list is `20261113-161500-fixb-srv-sync/server-now.sha` (cc0145e4..., SHA256SUMS OK, equal to laptop-now.sha).
  Recomputed: for all 231 entries, `git show <commit>:<path> | sha256sum` equals the list hash (gemmini 11cc20cd 102 files, libgemmini d048776 6,
  rocc-tests 22158bf 123), 0 diffs; the set of regular files in the three commits (`git ls-tree -r`, no submodule/symlink entries) is exactly the
  231 listed. 11cc20cd's submodule pointers are d048776 and 22158bf.
- So: PROVEN that the server gemmini tree at the time server-now.sha was taken equals pushed 11cc20cd + d048776 + 22158bf.
  NOT PROVEN (no record): that nothing changed between that list and the nm24/nm48 elaboration, and that non-gemmini Chipyard sources are
  unmodified. No post-build list of the server tree exists in the run folders. Only `--exclude-standard` files are covered.
- Programs: all 162 R1 `bin/` sha256 appear in sync `laptop-progs.sha` (== server-progs.sha). Bench sources in laptop-before.sha (P/ lines)
  equal 7fd60dc (= HEAD) for all 9 files. Binaries were not rebuilt here, so binary-from-source is not re-proven.
- R2 gemmini_counter / global_average / nm_sparse_loop_24/48 binaries: same sha256 as R1 bin/ (39b7db84, 2faaa37c, 2add119a, f0d22fb0).

### C (cont.). Non-NEG failures and silent-failure scan (R1)
- Non-NEG exit 2 = 74 - 62 = 12, exactly: nm_sparse_loop_24/48 (`*** FAILED *** (timeout) after 20000001 simulation cycles`),
  gemmini_counter nm24/nm48 and global_average nm24/nm48 (`*** FAILED *** (tohost = 1)`), conv_with_input_dilation,
  _and_rot180, _and_neg_padding on nm24 and nm48 (`(timeout) after 150000001`, last program line `CPU conv...`).
- Silent-failure scan of the 150 exit-0 logs: no `$stop`, no `Assertion failed`, no timeout text, no FAIL/mismatch/incorrect text
  (only hits: the make recipe's `pipefail` and nm_sparse_protocol `ok (0/256 wrong)` lines). All 150 end with `Verilog $finish`.
- Benches: 24 sbench logs each print `sbench passed (k of k runs verified)` and one `<variant> check: ... -> verified` per variant;
  6 fair_perf + 3 berkeley_dense_perf logs print every `<variant> matches the cpu reference (2048 values)` and `... passed`.
  nm_sparse_perf has no per-variant match line, only `nm_sparse_perf passed` (exit 0).
- 54 dense tests per nm chip == Berkeley base 7c540b3 bareMetalC/Makefile `tests` (56) minus matmul_spad, mvin_mvout_spad (diff empty).
  Note Berkeley also filters tiled_matmul_cpu/option for RTL runs; we run them (both pass). Stock chip ran no dense tests in R1.

### D. Failure classes
- (i) nm_sparse_loop: R2 (600M budget, same bins as R1) both chips print 22 `ok (0/N wrong)` lines + `nm_sparse_loop passed`, exit 0.
  Case names/order equal the 22 `fails += ...` calls in nm_sparse_loop.c@22158bf (lines 214-234, 239-248). R1 died after case 6 at 20,000,001.
  R3 CYC sums (cases 7-17 only): nm24 28,576,528; nm48 29,693,573 (recomputed) > 20M, so a 20M budget cannot pass: PROVEN budget, not hardware.
  nm_loop7 source vs nm_sparse_loop.c@22158bf: `diff` shows only (a) loop_case renamed loop_case_inner + new wrapper printing `CYC`, (b) cases 1-6
  commented out. Data is deterministic (no rand() in the file), so skipping cases does not change later inputs. Binary-from-.txt not re-proven.
- (ii) gemmini_counter: nm24, nm48 (R1) and stock (R2) print identical lines (`Read DMA cycles: 331` ... `Counter values changed too little`)
  and fail at the same sim time `[132145000]`. Same binary sha 39b7db84 on all. gemmini_counter.c, gemmini.h, gemmini_params.h,
  gemmini_testutils.h: `git diff 7c540b3 22158bf` empty. PROVEN Berkeley-side (stock sim + Berkeley-identical source).
- (iii) global_average: nm24, nm48, stock: `Fail`, then Output rows == Gold rows (2 rows, string-equal) in all three; whole program output
  identical across the three chips; all fail at `[1037035000]`. gemmini.h@22158bf:3402-3420 tiled_global_average and sp_tiled_global_average
  (3358+) contain no gemmini_fence(); global_average.c:46-53 compares right after the WS call. PROVEN: no fence, output == gold when printed,
  stock fails too. Race as the cause: strong inference (not instrumented).
- (iv) conv_with_input_dilation*: all 6 logs end `CPU conv...` then timeout at 150,000,001. The test's own CPU conv (conv_with_input_dilation.c:68+)
  loops over every dilated position (no skip), same body as conv_with_rot180.c. Recomputed: rot180 nm24 `CPU conv took 43522319` / 1,779,084 MACs
  (2x17x17x19x162) = 24.46 cyc/MAC. input_dilation / _rot180: 6,703,884 MACs -> 164.0M (> 150M, consistent).
  DISCREPANCY: _neg_padding 29x29 -> 5,177,196 MACs -> 126.7M at 24.46, BELOW 150M; needs >= 28.97 cyc/MAC to time out in CPU conv.
  (conv_with_kernel_dilation measured 40.68 cyc/MAC, and the dilated buffer is 39 KB vs 10 KB, so a higher rate is plausible.) ESTIMATE only:
  none of the 3 has been run to completion on any chip; fixb-srv-failures.md:8 "~6.7M MACs" is right, its 127M for neg_padding does not exceed 150M.

### E. Numbers (recomputed from R1 logs; own parser scratchpad `verify/bench.py`, every count below has its `-> verified` / `matches` line)
Same-build ratios = berkeley (or other variant) / sparse_loop on the same chip. Logs: `<chip>.<layer>_<24|48>_{full,loop}.seed1.log`.
| chip layer | berkeley | dense_stream | sparse_stream | sparse_loop | berk/loop | sstr/loop |
|---|---|---|---|---|---|---|
| nm24 rn50 | 661,441 | 742,284 | 1,161,086 | 519,145 | 1.274 | 2.237 |
| nm48 rn50 | 661,155 | 739,496 | 1,350,011 | 515,414 | 1.283 | 2.619 |
| nm24 ffn1 | 1,438,096 | 1,827,174 | 2,619,183 | 1,207,250 | 1.191 | 2.170 |
| nm48 ffn1 | 1,438,269 | 1,829,836 | 2,998,256 | 1,234,319 | 1.165 | 2.429 |
| nm24 ffn2 | 1,763,305 | 1,763,103 | 2,536,562 | 1,313,347 | 1.343 | 1.931 |
| nm48 ffn2 | 1,761,069 | 1,761,240 | 2,913,160 | 1,304,067 | 1.350 | 2.234 |
| nm24 qkv | 317,206 | 460,620 | 658,031 | 305,747 | 1.037 | 2.152 |
| nm48 qkv | 316,584 | 460,725 | 743,108 | 307,018 | 1.031 | 2.420 |
| nm24 edge | 4,366 | 4,851 | 8,308 | 3,843 | 1.136 | 2.162 |
| nm48 edge | 4,266 | 4,881 | 9,517 | 3,989 | 1.069 | 2.386 |
| nm24 small | 14,793 | 18,523 | 29,775 | 12,899 | 1.147 | 2.308 |
| nm48 small | 14,749 | 18,479 | 35,501 | 13,548 | 1.089 | 2.620 |
Stock (`stock.<layer>_24_dense.seed1.log`): berkeley rn50 661,820, ffn1 1,438,072, ffn2 1,763,263, qkv 317,164, edge 4,470, small 14,713;
dense_stream 741,570 / 1,826,217 / 1,762,231 / 461,101 / 4,828 / 18,597.
- All claimed headline numbers match exactly (rn50 1.274/1.283, ffn2 1.343/1.350, qkv nm24 1.037, stock berkeley rn50/ffn2/qkv).
- DISCREPANCY (label): "Fix B vs Fix A sparse_stream 2.24x/2.62x". The numbers are right (1,161,086/519,145 = 2.237; 1,350,011/515,414 = 2.619)
  but `sparse_stream` is NOT Fix A. stream_bench.c:5-7: sparse_stream = tiled_matmul_nm (per-tile streaming); Fix A = `sparse_fixa`
  (RUN_MASK bit 8). R1 `_full` binaries ran run_mask=7 (no sparse_fixa). No rn50 sparse_fixa exists in 20261111-183018-fixa-srv either.
  Correct label: "sparse_loop vs the per-tile streaming tiler (sparse_stream)".
- Cross-chip (allowed per 2026-11-12 ruling, label as cross-chip): nm berkeley vs stock berkeley within -0.18%..+0.54% on the four big/small
  layers; edge -2.3% (nm24), -4.6% (nm48). dense_stream nm vs stock within -0.64%..+1.10%. `_24_full` vs `_24_dense` binaries: .text and
  .rodata byte-identical (ELF section sha), only .sdata (run_mask/build flags, 16 B) differs, so these are same-code, cross-chip deltas.
  nm48 rows also use 4:8 data (different hash), so nm48-vs-stock is cross-data too.
- fair_perf (i=64 k=128 j=32): seeds 1-3 identical in every variant on every chip (spread 0; expected, fix-seeds.md:27-29).
  nm24: dense 1,544, dense_loop 3,119, sparse_loop 2,779 (dense_loop/sparse_loop 1.122), sparse_spad 961 (dense/sparse_spad 1.607).
  nm48: dense 1,475, dense_loop 3,126, sparse_loop 2,805 (1.114), sparse_spad 1,037 (1.422). At this size sparse_loop is slower than per-tile dense.
  stock fair_perf_dense_only: dense 1,547, dense_reuse 1,508, dense_loop 3,119; cpu_dense 1,103 vs nm24 1,100 with identical .text (CPU-only code
  differs by 3 cycles across chips). berkeley_dense_perf stock: dense 2,125, dense_bias 2,060, dense_reuse 1,471 (all seeds).

### F. Other observations
- Every log's simulator, max-cycles and verilator seed match jobs.tsv (chip->config, timeout, seed); wall_s == end-start for all 224.
- Warnings: only make "overriding recipe" and Verilator "stack size 8192 kb may be too small" (all logs). Benign.
- tiled_matmul_ws_igelu/layernorm/softmax pass vacuously (3-10 s): `#if defined(FAST) || !defined(HAS_NORMALIZATIONS) exit(0);` and the
  params header has no HAS_NORMALIZATIONS. Same as Berkeley on this config, but 3 of the 54 "passes" test nothing.
- Wall-time outliers: conv_with_input_dilation* 121-127 ks (timeouts), conv_with_kernel_dilation 94-99 ks, conv_with_rot180 72-77 ks;
  stock berkeley_dense_perf seed1 6,740 s vs 4,651/4,786 s with identical cycles (host load).
- Stock dense tests were not run on the stock chip in R1 (only 12 stock bench jobs); only gemmini_counter/global_average in R2.
- Spike baseline 20261113-145855-fixb-final-spike: SHA256SUMS 393/393 OK; dense54/rc.txt 108 x rc=0, including gemmini_counter,
  global_average and all 3 conv_with_input_dilation* on both libs (functional only).
- Parser (working-tree parse_fixa.py, read-only run): R1 rc=1 "tests: 170 PASS, 12 FAIL", "12 failed or missing logs, 212 logs judged":
  the 12 stock logs are not judged at all (0 lines mention stock). R2 rc=0 (2 PASS). R3 rc=1: nm_loop7_24/48 "FAIL (no sbench passed)"
  although both logs end `nm_sparse_loop passed`. Gate 3d (parse_fixa/collect/verify_all rc 0) is not met.
- berkeley-issues.md has B1-B3 only; gemmini_counter and global_average RTL failures are not recorded there yet.
- run-flow.sh Verilator default TIMEOUT_CYCLES is 150M (run-flow.sh:52,280); the 20M nm_sparse_loop budget came from the server job file
  (jobs-20261113-160018.txt), not run-flow. Whether 150M covers all 22 cases is not measured (cases 1-6 < 20M, cases 7-17 = 28.6M,
  seq cases 18-22 untimed). Estimate from wall rate (R1 20M in 16,995 s): R2 full run ~63M cycles. Estimate only.
- run.info in R2/R3 repeats R1's server git/diff lines verbatim (server trees unchanged); fine, but both inherit the wrong src list (B).

## Verdict
Proven (from raw logs/files, rule-4 compliant):
- R1 integrity: 389/389 sha OK; 224 jobs == job list, no dups/missing, every job logged; exits 150 x 0 / 74 x 2 agree with log endings.
  R2/R3: all files OK except run.out, proven stale by content (hash of run.out minus its last `done:` line equals the recorded hash).
- Sims: nm24 1042fc92, nm48 f4a3642c (= fixb-server.md:50), stock 84c2264a (unchanged since 2026-11-09); same in R1-R3.
- Source identity: sync `server-now.sha` (231 files) == blob content of 11cc20cd + d048776 + 22158bf, file set exact. Proven for that list.
- 62/62 NEG logs show exactly one assert with the expected run-flow.sh text; N6 prints a single `%`; neg_msg 10 -> N1 matches spec 2.5.6 / :232.
- Exactly 12 non-NEG failures (the expected list). No silent failure in the 150 exit-0 logs. All 36 bench logs verified.
- 54 dense tests == Berkeley's list. 48/54 pass on each nm chip. gemmini_counter: Berkeley (stock identical, source unchanged).
  global_average: stock fails too, Output == Gold, no fence in tiled_global_average. nm_sparse_loop: 22/22 at 600M on both chips; 20M budget provably too small.
- Headline numbers recomputed exactly (table in E).
Estimates (not proven): race as global_average cause; conv_with_input_dilation* as CPU-reference budget timeouts (24.46 cyc/MAC
predicts 164M for two of them, but only 126.7M for _neg_padding, below its 150M budget); ~63-67M cycles for the full nm_sparse_loop.
Discrepancies:
1. run.info (R1-R3) `src.gemmini.sha256list=641086db (~/fixb/server-after.sha); RTL 0db6cd09` names the pre-fix list/commit; the sims were built from 11cc20cd.
2. "Fix B vs Fix A sparse_stream 2.24x/2.62x": sparse_stream is the per-tile streaming tiler, not Fix A (sparse_fixa was not run; stream_bench.c:5-7).
3. fixb-srv-failures.md:8 neg_padding estimate (~127M) does not exceed the 150M budget, so it does not explain that timeout.
4. R1 has no run.out; berkeley-issues.md lacks gemmini_counter/global_average.
Production readiness: NOT production-ready yet. Blockers:
- conv_with_input_dilation, _and_rot180, _and_neg_padding never completed on any chip (nm or stock) on RTL; need a >= ~200M-cycle run, ideally with stock as control.
- Dense tests not run on the stock chip, so the "48/54 on nm" result has no same-run stock baseline except counter/global_average.
- Source identity not proven end-to-end: no post-build source list; run.info cites the wrong list. Final run from merged heads should record a list taken at build time.
- Parser gaps: stock logs not judged; nm_loop7 misjudged; gate 3d (parse_fixa/collect/verify_all rc 0) not met.
- Server job budget for nm_sparse_loop (20M) too low; run-flow.sh default 150M not shown to be enough.
- Label fix for the sparse_stream comparison before any paper use.

## RESUME HERE
Done: A-F checked, verdict written. Nothing running. Scratch: session scratchpad `verify/` (bench.py, elfsec.py, parse.*.out).
Next (coordinator): decide on blockers above; no further verification work pending.
