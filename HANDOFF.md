# Handoff: review and fix work on the N:M sparsity project (as of 2026-10-08)

Read this first. Together with `REVIEW-FINDINGS.md` it is everything the next session needs.

## 1. The project in one paragraph

The project adds 2:4 and 4:8 structured sparsity to UC Berkeley's Gemmini accelerator inside Chipyard 1.14.0
(`1.14.0-36-gbfa5699f`), and measures it in Verilator against Berkeley's unmodified chip. The README in this repo
describes it, and the work is headed for a **research paper**, so accuracy of results is the top priority.

The headline numbers (README table, `verification/fair_perf.c`, 64×128×32 int8, in cycles):

| | Berkeley | 2:4 | 4:8 |
|---|---|---|---|
| Array time, weights reused | 1257 | 672 | 672 |
| Whole job, weights reused | 1622 | 1686 | 1913 |
| Whole job, fresh weights | 1604 | 2778 | 3827 |

These numbers are known to be methodologically flawed; see section 4.

## 2. Where the code is

| What | Path | Branch / HEAD | Base (Berkeley) commit |
|---|---|---|---|
| This repo (benchmarks, checks, docs, `run-flow.sh`) | `~/gemmini-sparsity` | `main`, clean apart from untracked files | – |
| Gemmini RTL (Scala) | `~/chipyard/generators/gemmini` | `sparse-nm` @ 639a5068 | 8c3f9923 |
| Spike model | `…/gemmini/software/libgemmini` | `sparse-nm` @ a14aaa1 | ea8f7ed |
| Helpers and tests (`gemmini_nm.h`, `nm_sparse_*.c`) | `…/gemmini/software/gemmini-rocc-tests` | `sparse-nm` @ 61086b4 | 7c540b3 |

- The user's own code is the diff from each base commit to `sparse-nm`, plus this repo. **Only that code is in
  scope.** Don't review or fix Berkeley's unmodified code; read it only where needed to understand the user's
  changes.
- All four repos were confirmed clean (nothing uncommitted) at the end of this session.
- Untracked files in this repo: `NEXT-STEPS.md` (the user's own), `REVIEW-FINDINGS.md`, `HANDOFF.md`, `fixes-wip/`.

## 3. What happened this session

1. **Review (done).** Four Opus max-effort read-only reviews (RTL, Spike plus tests, repo scripts, whole project),
   each with a scoped follow-up pass. Everything is in **`REVIEW-FINDINGS.md`**:
   - sections 1–4 are the first-pass reports
   - the "follow-up" sections are the second passes; they upgrade, refute or correct some first-pass items, so read
     them too
   - every item has severity, file:line, evidence and a suggested fix
2. **Fix round (stopped almost immediately at 90% usage; nothing landed).**
   - `fixes-wip/libgemmini-gemmini.h.partial.patch` holds a half-done Spike header change. It was reverted because
     it needs a Makefile `-DNM_N/-DNM_M` hook that doesn't exist yet. Re-apply it only together with that hook and
     the matching `gemmini.cc` changes.
   - `fixes-wip/fixlog-{rtl,spike,scripts}.md` hold each agent's plan and baseline. Key baseline facts:
     - The MANIFEST verifies 66/66.
     - `verify_all.py --skip-patches` gives 19 pass / 1 skip.
     - The old mutant Spike builds reproduce the "tests pass with sparse broken" finding.
     - Full-range int8 data can't overflow at these sizes (proof by reasoning, not run, in `fixlog-spike.md`).
   - `fixes-wip/numbers.py` / `numbers.out`: numbers for the docs, computed from the recorded logs.

## 4. The most important findings (details in REVIEW-FINDINGS.md)

**Results and methodology (fix these before the paper):**
- **Whole-job ratios mix two program builds.** Code placement alone moves the timings 1601–1768. With one build,
  2:4 with weights reused is 1750/1686 = **1.04× faster**, not 0.96×.
- **Timed regions include first-touch I-cache misses** (about 44 cycles per line). Sparse runs touch 6–9 new lines
  against Berkeley's 2–3. Fix: an untimed warm-up of each variant.
- **"Cycle for cycle" is luck.** The two simulators start from different random register states. The array time is
  identical (1305 / 1257); the whole job is within 6 cycles. Use several `RANDOM_SEED`s and report ranges.
- **The 1.87× array speedup is for reused weights only.** With fresh weights it is 1305 → 960 = 1.36×.
- **"Weights kept" is really energy kept, on synthetic weights.**
- **The "unexplained stall" in NEXT-STEPS is explained by `fair_perf.c` issue order.** The index commands sit
  between a preload and its compute, so they never overlap (30 vs ~20 cycles per tile). To try: batch the indexes
  for up to 4 tiles, then issue the preload/compute pairs.

**Tests and correctness:**
- **The tests pass even with sparse mode broken.** Outputs and accumulators aren't cleared between runs. Fix: fill
  them with a poison value before every run.
- **Spike ≠ RTL** on:
  - the a_hi stride (the RTL uses stride 1)
  - the FIFO depth limit (the RTL deadlocks on a 5th tile)
  - when D is latched
  - stale indexes after a dense preload
  - a GARBAGE A operand
- **Spike `reset()` is incomplete**: `acc_act` is read uninitialised.
- **`nm_pack_meta` reads past the end of the array on edge tiles.**

**Hardware protocol gaps:**
- There is no way to clear the meta FIFO or the assembler.
- Sparse mode isn't latched with the weights; a plain `config_ex` silently turns it off.
- There are no guards for OS dataflow, transposes or LOOP_WS.
- A full FIFO deadlocks.
- The generated header's `NM_N` overrides `-D`, so `fair-build` can build 4:8 programs under 2:4 names.

**`run-flow.sh`:**
- Failed compiles and simulations pass silently.
- Background simulations are orphaned on abort.
- Parallel `make` runs race.
- The `sim dense` guard is weak.
- `bench` corrupts `results/cycles.csv`.
- The four report builders hard-code a dead path (`PROJ`).

**Area:** +27% (2:4) / +60% (4:8) array flops (exact counts from the generated Verilog). An M:1 mux sits in front of
every multiplier, even in dense mode; the fmax impact is unmeasured.

## 5. Plan for the fix round (what to restart)

The user asked for **Opus agents at xhigh effort**, split so no two agents edit the same files. Use the same three:

1. **RTL agent:** edits Gemmini `src/` only.
   - It may run `sbt` compile.
   - NO `make` in `sims/`, NO Verilator, NO elaboration. The current simulators produced the recorded results.
2. **Spike / helpers / tests / benchmark agent:** edits libgemmini, gemmini-rocc-tests, and this repo's
   `verification/fair_perf.c` and `berkeley_dense_perf.c` only.
   - Build Spike only into a scratch dir and run it with `spike --extlib=<scratch .so> --extension=gemmini`.
   - Never install into the toolchain or overwrite `gemmini-rocc-tests/build`.
   - Verify on both 2:4 and 4:8.
   - Prove the tests now FAIL on the broken (mutant) Spike builds.
3. **Scripts / docs agent:** edits everything else in this repo.
   - Never modify `logs/`, `results/cycles.csv`, `verification/{fair,berkeley,rerun}-logs/`, or the existing
     `verification/bin/` files.
   - MANIFEST: add entries only, never re-hash existing ones.
   - No numbers in docs unless computed from logs.
   - Don't change the README headline table; add a clearly marked "known methodology issues, re-run pending" note
     instead.

**Shared protocol spec** (the RTL and Spike/C agents must implement it identically):
1. **Clear:** NM_META_CMD (funct 26) with `inst.rd == 1` resets the row assembler and empties the meta FIFO, at
   dispatch.
   - Software must `gemmini_fence()` first.
   - Add a `gemmini_nm_reset()` wrapper.
   - Spike warns if sparse mode is turned off with indexes still pending.
2. **Mode latched with the weights:** each real (non-GARBAGE) preload latches the sparse mode per weight buffer. A
   compute in a different mode triggers an RTL sim assert and a Spike abort. Dense preloads zero the indexes.
3. **Legality:** the effective mode is `sparse && WS && !a_transpose && !b_transpose`; assert or abort otherwise.
   LOOP_WS or LOOP_CONV_WS while sparse also asserts or aborts. Spike aborts on a GARBAGE A in a sparse compute.
4. **FIFO depth:** `NM_META_FIFO_DEPTH 4`.
   - Spike aborts on a 5th tile.
   - The RTL gets a fail-fast deadlock assert that never fires on legitimate back-pressure.
   - Document "at most 4 tiles ahead".
5. **a_hi stride:** stays 1 in the RTL. Fix Spike to `bd_addr_real + i` and document it.
6. **Index-after-preload:** keep the Spike check, but reword it to "index tile must be sent before its preload".
7. **Header macros:**
   - The generated header emits `HAS_NM_SPARSITY`, `GEMMINI_HW_NM_N` and `GEMMINI_HW_NM_M`, never `NM_N`/`NM_M`.
   - `gemmini_nm.h` uses `-DNM_N/M` if given, otherwise `GEMMINI_HW_*`; it errors if neither is defined or if they
     mismatch.
   - Add `static_assert`s.
   - libgemmini Makefile: `NM_N ?= 2`, `NM_M ?= 4`, passed as `-D`; Spike prints N:M at startup.
8. **Dense builds (nm=None):** assert on funct 26 or rs1[10].

**`fair_perf.c` changes:**
- An untimed warm-up of every variant.
- `-DDENSE_ONLY` only changes a `volatile` flag initialiser, so `.text` is byte-identical across builds (verify with
  objdump). The stock chip never executes funct 26.
- Poison outputs and accumulators before every run.
- Full-range int8 data.
- Add a "batched" sparse-fresh variant (≤ 4 tiles ahead).
- Delete the unsupported "so the hardware can overlap them" comment.
- Keep the existing output line format.

**Out of scope unless the user approves** (design changes, not fixes):
- indexes read from the scratchpad (the biggest potential speedup)
- joint index encoding
- area reductions
- the PE mux timing fix
- an index-reuse wrapper

## 6. After the fixes (needs user approval before starting)

1. The user reviews the uncommitted diffs. **Never commit without being asked.**
2. Rebuild the 2:4 and 4:8 Verilator simulators: build serially, then run with `BREAK_SIM_PREREQ=1`.
   - Never rebuild Berkeley's stock simulator from sparse sources.
   - The stock sim must be built from the base commits.
3. Run the RTL tests and `fair` with several `RANDOM_SEED` values; report ranges.
4. Only then update the README table, the figures and `paper_data`, using numbers produced by the scripts.

## 7. How the user likes to work

- Wants agents for heavy work: Opus, at max effort for review and xhigh for fixes. Parallel split agents are fine.
- Watches usage. This session was stopped at 90% mid fix-round, so have agents keep running logs outside /tmp so
  work survives a stop.
- Wants frequent short progress reports. When asked for one, check `fixes-wip/` or the scratchpad fixlogs and
  `git diff --stat` in the four repos.
- Scope is only the user's own sparsity code, not Berkeley's.

## 8. Update: old timing results removed (commit 48bb131, pushed to GitHub main)

- **What was removed:** at the user's request, 99 files of timing results were deleted from the repo and from
  GitHub's current tree with a normal commit, so they are still in git history:
  - `logs/{runs,sparse,baseline}`, the selftest logs, `results/cycles.csv`
  - `verification/{fair,berkeley,rerun}-logs`, `paper_data.json`, `paper_chart.png`, `verify_all_report.md`,
    `cross_check.out`, `MANIFEST.sha256`
  - `analysis/{charts,advanced}`, `analysis/all_data.csv`
- **Private backup:** `~/gemmini-sparsity-old-results/` (same paths, verified byte-identical, never pushed).
  REVIEW-FINDINGS paths like `verification/fair-logs/...` now live there.
- **Still in the repo:** setup logs, the math/pattern `.out` files, `verification/bin`, and all scripts.
- **Now broken until the re-run:** `verify_all.py`, `nmdata.py`, `cross_check.py`, `compare_runs.py` and the chart
  scripts all expect the deleted files. Rework them (point them at the new runs) as part of the scripts fix.
- **README:** fixed in a follow-up commit; the results section now says "withdrawn, re-run pending".
