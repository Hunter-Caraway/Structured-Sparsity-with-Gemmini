# Berkeley issues (reported, not fixed)

Issues found in UC Berkeley's unmodified code while working on this project. AGENTS.md rule 6: report, do not fix.
Bases: Gemmini RTL `8c3f9923`, libgemmini (Spike model) `ea8f7ed`, gemmini-rocc-tests `7c540b3`.

## B1. `matmul_spad` and `mvin_mvout_spad` fail on Berkeley's own Spike model

Found 2026-11-13. Evidence run: `investigate/runs/20261113-143811-dense-spad-stock/` (logs, `run.info`, `SHA256SUMS`);
worklog `worklogs/dense-spad-check.md`.

**Observed.** Both tests, built from Berkeley's unmodified tests (`7c540b3`) with the stock dense `gemmini_params.h`
(sha256 `3758ae96...da924`), run on Spike with Berkeley's unmodified libgemmini (`ea8f7ed`), end with
`*** FAILED *** (tohost = 1337)`, exit 57 (`logs/matmul_spad.stocklib.stockbin.log`,
`logs/mvin_mvout_spad.stocklib.stockbin.log`). Same result in all four lib x binary combinations (stock or ours).
Control: stock lib + stock `mvin_mvout` passes (`logs/sanity.mvin_mvout.stocklib.stockbin.log`). `LD_DEBUG=libs`
showed only the intended lib loaded.

**Cause (by reading the code).** Both tests issue `gemmini_mvout_spad` (funct 23, `k_MVOUT_SPAD`,
gemmini-rocc-tests `include/gemmini.h:60`, `:228-231`; used at `bareMetalC/matmul_spad.c:182`, `:392`).
libgemmini `ea8f7ed` has no funct 23 handler: dispatch ends at `gemmini.cc:1638-1640`, which prints a `dprintf`
(debug builds only, so it is absent from the logs) and raises `illegal_instruction`. The bare-metal trap handler then
exits with tohost 1337. The RTL does decode it (`StoreController.scala:87`, `mvout_spad_rs1`), so this is a gap in
Berkeley's Spike model, not a hardware bug.

**Berkeley knows.** Their `bareMetalC/Makefile:70-71` filters both tests out of the run list with the comment
"Nornaml configs dont have ext spad" (sic).

**Not ours.** Our diffs add functs 26, 27, 28 only; nothing adds or removes funct 23.

**What we do.** The dense regression uses Berkeley's filtered list: 54 tests (AGENTS.md "Done means";
`run-flow.sh` derives the list from that Makefile line and dies unless 54). Earlier worklogs that say "56 tests,
2 pre-existing failures" (`fix-a-sw.md:70`, `fixb-spike.md:25`) refer to this issue.

**Paper.** If the paper states the dense regression, say "54 of Berkeley's dense tests (Berkeley's own run list;
`matmul_spad` and `mvin_mvout_spad` are excluded by Berkeley and fail on its unmodified Spike model)".

## B2. `LoopMatmul.scala:459` `ldb_ahead` tests LdA's k in a B condition

`io.ldb_completed || io.ld_kb > k || (io.ld_ka === k && io.ld_j > j)`: the third term uses `ld_ka` where `ld_kb`
looks intended. Dense path left as is; the sparse branch uses its own gate. Source: `worklogs/fixb-rtl.md:21-29`,
spec H9 (`fix-b-spec.md:285`). Not measured.

## B3. `LoopMatmul.scala:185` condition is never true

`Mux(max_row_iterator === max_row_iterator-1.U, row_pad, 0.U)` compares a value with itself minus 1, so LdB always
loads DIM rows (row padding never applied). Harmless for the sparse loop (pad_K == 0, assert N6). Source:
`worklogs/fixb-rtl.md:30-31`. Not measured.

## B4. `gemmini_counter` fails on Berkeley's stock RTL

Found 2026-11-15. Fails the same way on Berkeley's unmodified chip (`GemminiRocketConfig`) and on our nm24/nm48 chips.
Logs (all under `investigate/runs/`): `20261115-225958-fixbfail-srv/stock.gemmini_counter.seed1.log`,
`20261113-160015-fixb-srv/nm24.gemmini_counter.seed1.log`, `.../nm48.gemmini_counter.seed1.log`.

**Observed.** All three print `Counter values changed too little after snapshot reset; check if counter continues properly`
and fail at the same simulation time `[132145000]`. Same binary on all (sha256 prefix `39b7db84`, `fixb-verify.md` step D(ii)).

**Cause.** Berkeley-side: `gemmini_counter.c`, `gemmini.h`, `gemmini_params.h`, `gemmini_testutils.h` are byte-identical
between base `7c540b3` and our `22158bf` (`git diff` empty, `fixb-verify.md` D(ii)). The test fails on stock hardware; the
exact internal reason was not investigated.

**Not ours.** Nothing in our diffs touches the counters. Spike passes it (`20261113-145855-fixb-final-spike`, dense54 rc 0).

**What we do.** Count it as a known Berkeley RTL failure. Do not report it as a regression of the N:M chips.

## B5. `global_average` prints `Fail` although Output equals Gold (stock too)

Found 2026-11-15. Logs: `20261113-160015-fixb-srv/{nm24,nm48}.global_average.seed1.log`,
`20261115-225958-fixbfail-srv/stock.global_average.seed1.log`.

**Observed.** All three chips print `Fail`, yet the printed Output rows equal the Gold rows (2 rows, string-equal, whole
program output identical across the three). All fail at simulation time `[1037035000]` (`fixb-verify.md` D(iii)).

**Cause (inference, not instrumented).** `gemmini.h` `tiled_global_average` (`include/gemmini.h:3402-3420`) and
`sp_tiled_global_average` (`:3358+`) contain no `gemmini_fence()`. `global_average.c:46-53` compares right after the WS call.
A race with the last mvout is the likely cause. Not proven; we did not instrument it.

**Not ours.** Source unchanged from Berkeley; stock chip fails identically.

## B6. `tiled_matmul_ws_igelu`, `_layernorm`, `_softmax` test nothing on these configs

Found 2026-11-17. These three are in Berkeley's 54-test list but exit 0 before testing.
`bareMetalC/tiled_matmul_ws_igelu.c:55-56`, `tiled_matmul_ws_layernorm.c:61`, `tiled_matmul_ws_softmax.c:52`:
`#if defined(FAST) || !defined(HAS_NORMALIZATIONS)` then `exit(0)`. Our params header does not define `HAS_NORMALIZATIONS`
(`fixb-verify.md` F), so they pass in 3-10 s without running any matmul. Same on Berkeley's config.

**What we do.** Their "pass" is not evidence. Paper: do not count them as tested (51 of 54 meaningful on the dense list).

## B7. `conv_with_input_dilation_and_rot180` is long on RTL (note, not a bug)

Found 2026-11-23. Worklog `worklogs/rot180-diag.md`; logs in `experiments/streaming/build-scratch/rot180-diag/logs/`
(gitignored).

**Observed.** Non-FAST build timed out at 300M sim cycles (= 150M core cycles; 2 sim cycles per core cycle) inside the CPU
reference on stock and nm24 (`20261117-111223-convbudget-stock-srv`, `20261117-110726-convbudget-srv`). On Spike the same
binary finishes and verifies: CPU conv 124,071,345 instr, 1.87x `conv_with_input_dilation` (66,378,922). gcc keeps the
bounds check and the `wrot180` ternary in the inner loop (18 vs 9 instr/iteration). Estimated ~390M sim cycles [E].

**Why Berkeley never sees it.** Their RTL CI (`.github/scripts/run-tests-rtl.sh`) builds with `CFLAGS=-DFAST`, which
compiles out the CPU `conv()` (`#ifndef FAST`). Only their Spike CI runs the full reference. Not a bug.

**Quirk.** `conv_with_input_dilation.c` has a nested `#ifdef FAST` (17x23 dims) inside the outer `#else` of `#ifdef FAST`,
so it is unreachable. Cosmetic.

**What we do.** Rerun with a 2B sim-cycle cap (`rot180-rerun.md`). Set sim caps >= 2 x expected core cycles.
