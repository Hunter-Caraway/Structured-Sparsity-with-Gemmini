# Code review findings (2026-10-08)

Read-only review by four Opus 5.5 max-effort agents. Each section below is one agent's report, condensed. Nothing
in the repo or the forks was modified.

## 1. This repo: scripts, benchmark, docs

`verify_all.py` in the scratchpad: 19 pass, 1 skip. A host-compiled differential test of `gemmini_nm.h` against
numpy found 0 mismatches in 80 full-range cases. All four `verification/bin` binaries rebuild byte-identical.

### Confirmed

1. **[methodology, highest] Headline "whole job" ratios compare two different binaries.**
   - Berkeley's numbers come from the `-DDENSE_ONLY` build, ours from the full build. `dense_*` code is
     instruction-identical in both, but sits at different addresses.
   - On the same chip and with the same code, `dense` runs 1604 cycles in one binary vs 1648 in the other, and
     `dense_reuse` 1628 vs 1750 (+7.5%).
   - Same-binary ratios: 2:4 reuse is **1.04× faster** (README says 0.96×), 4:8 reuse is 0.92× (README 0.85×).
   - `build_paper.py:105-109` admits the effect; the README and NEXT-STEPS don't.
   - **Fix:** warm up each loop untimed, `-falign-functions=64`, use one binary with a `.data` flag instead of
     `-DDENSE_ONLY`, and report same-binary ratios with a noise band.
2. **[bug] `fair_perf.c:73-87, 214-220`: `check()` can't catch a variant that writes nothing.**
   - Neither the accumulator nor `c_out` is cleared between runs, and all four variants produce the same gold
     output, so only the first check is independent.
   - **Fix:** fill `c_out` with a sentinel and overwrite the accumulator tiles before each run.
3. **[verification gap] `verify_all.py` checks no README number,** although `README.md:83` says it re-checks every
   number. Section E skips (the PDF is absent), and `cross_check.py:98-119` checks only the superseded quotes.
   - **Fix:** parse the README table and recompute it from `nmdata.summary()` and `load_fidelity()`.
4. **[weak or tautological checks]**
   - `verify_all.py:103` (`tiles*2`) can't fail.
   - `verify_all.py:104` is a one-sided bound.
   - `verify_all.py:106-110` uses a 1% tolerance for a "cycle for cycle" claim.
   - `verify_all.py:111-117` derives both sides from the same logs and skips silently if the JSON is missing.
   - `cross_check.py:85` is `say(True, …)`, which always passes.
   - `compare_runs.py:39-40` skips missing logs, so "ALL RUNS MATCH (1 logs compared)" exits 0.
5. **[overclaim] `README.md:36` says "cycle for cycle".** The reuse row is 1628 vs 1622, and the internal counters
   differ. `NEXT-STEPS.md:69-70` contradicts itself. Say "within 0.4%".
6. **[mislabel] The "Multiplier grid working time" row is the reuse variant only.**
   - With fresh weights it is 1305 → 960 (1.36×).
   - `ex_active` counts `control_state === compute`, not multiplier activity.
   - fig1 and fig3 (`advanced_visuals.py:92, 142`) also omit "(weights reused)".
7. **[mislabel] "Weights kept" is really energy (sum of squares) kept** (`README.md:41-42`, fig5 x-label at
   `advanced_visuals.py:225`). The weights are synthetic Gaussian/Laplace data, not a trained model. The "answer
   error" column is just √(1−kept).
8. **[chart mislabel] fig9 (`chart_all_data.py:142-143`).**
   - The wait counters tick while idle: `spad_a_wait` (1612) exceeds the total (1551) in a CPU-only run.
   - `rs_full` is `!alloc.ready`, which is not the same as "full".
9. **[bug] `run-flow.sh:296`: `(exit $?)` always prints 0,** because `$(date)` resets it. `fails`
   (`run-flow.sh:304`) is counted but never checked.
   - **Fix:** `sim_run … || rc=$?`, print `$rc`, then `[ "$fails" -eq 0 ] || die`.
10. **[bug] Aborting `fair` leaves simulations running without the sleep inhibitor.** `cleanup()`
    (`run-flow.sh:106-111`) doesn't kill the jobs (confirmed with a mock).
    - **Fix:** validate everything before launching, `kill "${pids[@]}"; wait` in `cleanup`, and
      `trap 'exit 130' INT TERM`.
11. **[likely race] `run-flow.sh:300-303`: concurrent `make` runs without `BREAK_SIM_PREREQ` for the sparse
    simulators.** Two of them share a CONFIG and build directory, which can mean concurrent sbt runs after a branch
    switch. **Fix:** build serially first, then run every job with `BREAK_SIM_PREREQ=1`.
12. **[bug] `run-flow.sh:140-146` (`rv_cc`): a failed gcc leaves the stale binary behind and still passes.**
    **Fix:** `rm -f "$out"` first, then check `${PIPESTATUS[0]}`.
13. **[likely bug] The `sim dense` guard (`run-flow.sh:248-251`) only protects an existing simulator.**
    - If none exists, it silently builds "Berkeley" from sparse-nm.
    - **Fix:** require the base commits and clean trees before building.
    - `all` never builds the stock simulator, so `fair all` fails on a fresh machine.
14. **[bug, low] `run-flow.sh:389`: a `paper_data.py` failure is masked by `&& echo`.**
15. **[inconsistency] `bench` appends to `results/cycles.csv`,** which is in the MANIFEST and must have exactly 26
    rows. This contradicts "never overwrite". `chart_all_data.py:24-30` picks the latest logs, while the other
    scripts pin stamps.
16. **[bug] All four report builders hard-code `PROJ = Path("/home/hunter/Structured 4:8 Sparsity with Gemmini")`,**
    which doesn't exist (`build_paper.py:16`, `build_changes.py:17`, `build_explained.py:17`,
    `build_report.py:16`). **Fix:** `Path(__file__).resolve().parents[2]`.
17. **[inconsistency] The MANIFEST misses files.** `logs/runs/spike-20261006-165950.log`, `paper_data.json`,
    `rerun-logs/status.txt` and `figure_data.csv` aren't covered, and new files never fail check G.
18. **[overstated] `independent_math_check.py` doesn't test `gemmini_nm.h` packing,** and its faults are injected
    into its own model. Add the differential harness described at the top of this section.
19. **[test gap] All RTL tests use values in [-8, 7].** Full-range int8 is never exercised on the RTL.
20. **[doc nits]**
    - `chipyard-setup-notes.md:205-212` still presents 1.44×/1.36× with no superseded note, and quotes 65–85%
      where `cross_check.py` computes 67–86%.
    - `chipyard-setup-notes.md:123, 150` say nothing was pushed.
    - The Chipyard version is really `1.14.0-36-gbfa5699f`.
    - `NEXT-STEPS.md:87-88` and `run-flow.sh:44` mention a ':' in the folder name, which is no longer there.
21. **[dead code]**
    - `make_charts.py:38-41`: `idle_gap` is never used.
    - `make_charts.py:26` and `chart_all_data.py:56`: `groupby().last()` can mix runs.
    - `verify_all.py:94-96`: the "log missing" branch is dead.
    - `paper_data.py:80` produces labels like "0.96× slower".
22. **[optimization]** `step_checks` runs `math` and `patterns` twice. `checks` and `figures` dirty tracked files
    with timestamps.

### Plausible (not verified)

- **P1.** Cause of #1: no warm-up, so the cold I-cache and branch predictor land inside the timed region. Function
  order also differs between the builds.
- **P2.** The NEXT-STEPS "unexplained stall" (~30 vs ~20 cycles/tile with fresh weights): compute and preload only
  overlap when the next preload and its index tile are already queued. With 6–10 RoCC commands per sparse tile, the
  CPU starves the queue.
- **P3.** `berkeley` and `nm24_sameprog` stage the same binary to the same temp path (`run-flow.sh:295, 302-303`).
  The bytes are identical and the window is milliseconds.
- **P4.** `gemmini_fence()` and the RoCC asm lack a `"memory"` clobber (`gemmini.h:309`). That's fine in the
  recorded binaries, but fragile.
- **P5.** `stay_awake` reports "sleep blocked" even if `systemd-inhibit` exits immediately.

### Verified correct

- The README table values and ratios match the logs exactly.
- The DENSE_ONLY binary contains no funct-26 instructions.
- The binaries rebuild byte-identical.
- Timing placement is correct (`config_ex`, then a fence, then the counters).
- `check()` covers all 2048 outputs against an independent reference.
- The meta send order and the scratchpad layout are correct.
- The `pattern_fidelity` masks are energy-optimal (brute force).
- The simulations are deterministic.
- `BREAK_SIM_PREREQ` works.
- The README diff stats match git.
- `bash -n` and shellcheck are clean.

## 2. Hardware (RTL) changes

The datapath is correct by inspection. Index, weight and activation alignment holds through MeshWithDelays, Mesh,
Tile and PE. NM_META_CMD bypasses the reservation station: it goes from `unrolled_cmd` straight into the
ExecuteController FIFO (`Controller.scala:514-517`). No builds or simulations were run.

### Confirmed

1. **[hang] A full meta FIFO deadlocks dispatch.**
   - Where: `Controller.scala:514-517`, `ExecuteController.scala:206,221`.
   - The last row-command of a 5th outstanding tile blocks in-order dispatch, including the preloads that would
     drain the FIFO.
   - Only the 10M-cycle assert at `Controller.scala:536` catches it, and Spike's deque is unbounded.
   - **Fix:**
     - Add a fail-fast assert for "meta blocked while the RS and EC are idle".
     - Bound Spike's queue to 4.
     - Document "at most 4 tiles ahead".
     - Longer term, fetch indexes from the scratchpad.
2. **[silent wrong results or hang] Sparse mode with LOOP_WS / LOOP_CONV_WS.**
   - Where: `LoopMatmul.scala:446,992-994`.
   - `garbage_addr` zeroes a_hi, NM_META_CMD is held while a loop is configured, and more than 4 real weight tiles
     hang.
   - **Fix:** reject loop commands while sparse mode is on, as the RS does for a_transpose
     (`ReservationStation.scala:409-416`).
3. **[likely bug] The meta stream can never be resynchronized.**
   - Where: `ExecuteController.scala:206-208,224-227`.
   - Only reset clears `nm_asm_row` and the FIFO. One extra or missing meta command, meta sent for a GARBAGE
     preload, or a process killed mid-sequence shifts every later tile.
   - **Fix:** a tile-start marker in `inst.rd`, and optionally a clear on FLUSH at dispatch. Do not clear at
     config_ex execution time.
4. **[silent wrong results] The RTL doesn't restrict sparse mode to WS without transposes.**
   - Where: `ExecuteController.scala:611-613`, `MeshWithDelays.scala:161,178-181,203,205`.
   - Under OS, the PE picks slot 0. With a_transpose, a_hi bypasses the transposer. With b_transpose, every index
     ends up 0.
   - **Fix:** `nm_sparse_mode := nm_sparse && WS && !a_transpose && !b_transpose`, plus an assert.
5. **[model ≠ RTL] `ExecuteController.scala:300-301`: a_hi ignores A_stride** (also found in section 3).
6. **[area] The activation path is m× wider in every PE and in the skew, even in dense mode.**
   - Where: `Mesh.scala:64`, `PE.scala:104`, `MeshWithDelays.scala:199-200`.

     | | Extra flops | Rough increase over the base array |
     |---|---|---|
     | 2:4 | ~13.5K | ~+40% |
     | 4:8 | ~28K | ~+80% |

   - **Fix:** with sorted indexes, the PE only needs n+1 values (3 for 2:4, 5 for 4:8) plus a relative index.
7. **[nit] `ExecuteController.scala:228-233`: dense builds silently accept sparse programs.** Add an assert.

### Plausible

- **P8. [timing] `PE.scala:94-96`: the M:1 mux sits in front of the multiplier in every PE,** even with sparsity
  off. The MAC is the critical path, so this probably costs fmax; matching cycle counts don't show it. **Fix:**
  one-hot select, or move the select into the a pipeline stage.
- **P9.** The mode isn't tracked per weight buffer, so toggling rs1[10] between a preload and its compute mixes
  modes.
- **P10.** Builds with no sparsity still instantiate `nm_meta_q` and the extra control fields; dead-code elimination
  probably removes them.

### Index overhead (commands with no weight reuse)

| | Total commands | Commands per preload+compute pair |
|---|---|---|
| Dense | 128 | 2 |
| 2:4 | 192 | 6 |
| 4:8 | 320 | 10 |

- **Bound:** sparse stays array-bound only if the CPU issues one command in ≤3.5 cycles (2:4) or ≤2.1 cycles (4:8).
  Rocket needs about 3 or more.
- **A. Bit-stream packing:** 4:8 goes from 8 to 6 commands per tile (−20%). 2:4 already fills every bit.
- **B. Joint encoding of the sorted indexes:** 2:4 drops to 3 commands per tile (192 → 160 total) and 4:8 to 4
  (320 → 192). Needs a decoder after the FIFO.
- **C. A deeper FIFO:** gains nothing while issue-bound.
- **D. Indexes from the scratchpad:**
  - The preload fetches them implicitly, with bulk mvin, giving about 2.3 commands per pair (~72–76 total, fewer
    than dense).
  - That recovers most of the 1.87× array speedup end-to-end, and also fixes #1, #3 and LOOP_WS support.
  - Cost: 4 or 6 extra spad row reads per preload; put the indexes in another bank to hide them.
- **E. Index table by preload slot** (spare rs1[63:53] bits): 2:4 goes from 192 to 96 commands and 4:8 from 320 to
  128. LoopMatmul fills those bits with DontCare, so honor them only in sparse mode.

### Verified correct

- Index and d-path alignment at every stage.
- Row order (`DIM-1-d_fire_counter_mulpre`).
- Column order (LSB-first).
- Activation grouping.
- Mode captured per row.
- An empty FIFO stalls safely, with exactly one pop per real preload.
- Bit widths and packing.
- rs1[10] is free.
- funct 26 isn't in the loop decode ranges.
- Dense-mode FSM timing is identical.
- Partial tiles.
- Reset.

## 3. Spike model and tests

All four tests pass on Spike for 2:4 and 4:8. The index layout and the compute math match the RTL. Mutant Spike
builds are in the session scratchpad (`mutA/`, `mutB/`, `mutE/`).

### Confirmed

1. **[test bug] `nm_sparse_matmul.c:124,150`: the sparse run reuses the dense run's accumulator rows,** so it passes
   even when sparse writes nothing (mutA passed). **Fix:** fill the accumulator and `c_sparse` with a poison value
   before the sparse run, or give it its own accumulator region.
2. **[test bug] `nm_sparse_perf.c:250-259`: the `sparse_nat` and `sparse_reuse` checks read stale data.**
   - `dense_reuse`'s output is never checked.
   - Mutant B (sparse never writes) and mutant E (writes dropped after 32 computes) pass all 4 tests.
   - **Fix:** poison before each run and compare every run against a reference.
3. **[model ≠ RTL] `gemmini.cc:628,635`: Spike reads a_hi at `bd_addr_real + a_stride*i`.**
   - The RTL reads `b_address_rs2 + b_fire_counter` (stride 1).
   - A test with A_stride=2 gave 238/256 wrong outputs. The current tests use a stride of 1, so this is latent.
   - **Fix:** use `bd_addr_real + i`.
4. **[model ≠ RTL] `gemmini.cc:765-767`: Spike's index FIFO is unbounded.** The RTL is 4 deep, and more than 4 tiles
   outstanding deadlocks it (from reading the code). **Fix:** abort when the queue size is ≥ 4, and document the
   limit at `gemmini_nm.h:156-160`.
5. **[likely bug] `gemmini.cc:15-73`: the reset fix is incomplete.**
   - `acc_act` is read uninitialized at `:423` and `:498`; if it happens to hold 4, the activation silently becomes
     SOFTMAX. Several other fields are also never reset.
   - **Fix:** `*this = gemmini_state_t{};`, then set the non-zero defaults.
6. **[helper bug] `gemmini_nm.h:74,137`: when K isn't a multiple of M, `nm_compress`, `nm_decompress` and
   `nm_ref_sparse` drop the tail group.** **Fix:** assert, or zero-pad and use `ceil(k/m)` groups.
7. **[counters] `ExecuteController.scala:1092-1097`: the spad-wait events aren't gated by `cntl_valid`,** so they
   count idle cycles, which biases the comparison against sparse. There is also no "index wait" counter.
8. **[integration] `bareMetalC/Makefile:60-63`: the nm tests are built for every config,** so they fail on non-sparse
   RTL. Gate them on `HAS_NM_SPARSITY`.
9. **[minor model ≠ RTL] `gemmini.cc:395-405,574-577`:** a dense preload followed by `config_ex(sparse)` and then a
   compute behaves differently from the RTL. Zero `preload_meta` on dense preloads.
10. **[nits]**
    - Spike has no `static_assert` on the N:M parameters.
    - A 4:8 program on a 2:4 Spike gives silently wrong results.
    - `nm_compress` keeps the first n nonzeros, not the largest.
    - A prune that zeroes everything would pass `nm_sparse_sw`.
    - `nm_sparse_perf.c` lacks the bank-capacity `#error`s.
    - No test covers partial tiles.
    - `NM_MAX_M` overflows when m > 16.

### Plausible

- **P1.** Spike's empty-FIFO abort message (`gemmini.cc:399`) is probably wrong: the RTL likely just waits.
- **P2.** Spike latches indexes at the preload but reads weights at the compute, so the two can diverge if the
  scratchpad is overwritten in between.
- **P3.** With garbage A and a real a_hi, the RTL feeds stale SRAM data while Spike uses 0.
- **P4.** Neither Spike nor the RTL can clear stale or half-assembled index tiles.

### Optimizations

- **Index reuse when weights are reused** works on today's hardware, since garbage preloads don't pop. A tiled
  wrapper with the `run_reuse` loop order cuts index commands per compute by a factor of IT. Spike instruction counts
  per compressed tile:

  | | 2:4 | 4:8 |
  |---|---|---|
  | No reuse | 55 | 71 |
  | With reuse | 32 | 36 |

- **Encoding (needs RTL changes):** an M-bit mask per group gives 4:8 4 commands per tile instead of 8. Rank
  encoding gives 3 for 2:4 and 4 for 4:8.
- **Biggest win:** let the preload read the index tile from the scratchpad, loaded in bulk with mvin, which removes
  per-tile index commands.
- **Software:** unroll `nm_send_meta`, which spends about 6-8 instructions per command against a minimum of about 3.

## 4. Whole project (overlaps with 1-3; only the new items are listed)

- **[bug] The `-DNM_N`/`-DNM_M` flags lose to the generated `gemmini_params.h`.**
  - Elaboration writes `#define NM_N`, which overrides `-D` (confirmed with gcc).
  - `step_fair_build` (`run-flow.sh:222-224`) doesn't restore the header, so `sim nm48` followed by `fair-build`
    builds a 4:8 binary named `fair_perf_24`.
  - **Fix:** restore the header, or use `#ifndef` plus an `#error` on mismatch.
- **[bug] `run-flow.sh:191-192` (`step_spike_lib`) masks make failures with `|| true`.**
- **[likely bug] `ExecuteController.scala:203-234,611-613`: `config_ex` never clears `nm_asm_row` or `nm_meta_q`,**
  so a partial index sequence misaligns every later sparse preload until reset. Flush on `config_ex` in both the RTL
  and Spike.
- **[likely bug] `MeshWithDelays.scala:178-192`: no RTL guard against `a_transpose`/`b_transpose` in sparse mode,**
  which silently gives wrong results (Spike asserts). Add an assert near `ExecuteController.scala:141`.
- **[doc]**
  - `chipyard-setup-notes.md:158` claims 4:8 passes on Spike, but no log shows it.
  - The README gotcha "rebuild with -DNM_N=4" isn't possible, because `libgemmini/Makefile:12` has no CXXFLAGS hook.
  - `verify_all.py:27` hard-codes `~/chipyard` and ignores `CHIPYARD_DIR`.
- **[cause of the NEXT-STEPS "unexplained stall"] It isn't the sparse hardware.**
  - `third_instruction_needed` (`ExecuteController.scala:277`) requires 3 ex commands to be visible before compute
    and preload can overlap. A slow CPU loop falls back to a single compute plus a single preload (16 + 16 rows).
  - `sparse_nometa`, which sends no indexes, also shows `ex_active=960`.
- **[optimization, plausible] `fair_perf.c:143-148` sends the next tile's indexes between `preload(t)` and
  `compute(t)`, which puts them on the critical path.** The natural order was 11.6% faster in the original
  benchmark; the estimate is 2:4 fresh at ~2778 → ~2460.
- **[optimization] Estimates for cutting the index cost** (about 8.2 cycles per index command with fresh weights,
  about 7.1 when reused):

  | Change | Fresh weights | Weights reused |
  |---|---|---|
  | Pack 4:8 into 6 commands | 4:8 3827 → ~3300 | — |
  | One command per tile that reads indexes from the scratchpad | ~1990 for both | ~1515 (~1.07× faster than Berkeley) |
  | Index pointer in spare preload rs1 bits | ~1730 | ~1460 |

  - Unrolling `nm_send_meta` saves ~200–600 cycles.
  - **Area:** activations become Vec(m) in every PE, which is about 6k extra flops for 2:4 and 14k for 4:8. Run
    synthesis before scaling up.
- **Verified correct:**
  - Index and weight skew alignment.
  - Index row order.
  - Mode switching is safe mid-pipeline.
  - NM_META bypass ordering.
  - The bit layout agrees across RTL, Spike and C.
  - Dense mode is identical.
  - Berkeley's simulator has no `nm_*` signals.
  - The rerun logs are genuinely independent.

### Section 4 follow-up (second pass, scoped to your code only)

- **#21 parallel make race: confirmed, but it can't trigger on the tree as it stands.**
  - Where: `run-flow.sh:300-303`; the same pattern is in `step_rerun` (`:315-325`), `verification/rerun.sh` and
    `verification/run_fair.sh`.
  - Any source mtime change (for example, the README's "check out master, build Berkeley, switch back") would start
    three sbt assemblies of the same jar at once. Two of them would also elaborate and build `GemminiNMRocketConfig`
    into the same `generated-src`.
  - **Fix:** run `make CONFIG=<cfg>` once per config, one at a time, then launch every run with
    `BREAK_SIM_PREREQ=1`.
- **#22 meta order: still unconfirmed, and the earlier explanation is refuted.**
  - For 2:4, natural order won in all four original runs, by 102 to 344 cycles. But the tails are equal (~73) and
    `ex_active=960` in both orders, so the gap is CPU issue cost, not array overlap.
  - For 4:8, natural order costs more over its CPU-only time (+1084 vs +803).
  - The original variants are confounded by different code generation (inlined vs. called `send_meta`).
  - The comment "so the hardware can overlap them" (`fair_perf.c:144`, `nm_sparse_matmul.c:142-144`) is contradicted
    by the logs; delete it.
  - **To settle it:** add a lean natural-order variant to `fair_perf.c`.
- **#23 counter and cycle differences between simulators: explained (measurement method).**
  - The Verilator flags are identical across the stock, NM24 and NM48 simulators, with RANDOMIZE_REG_INIT and
    RANDOMIZE_MEM_INIT on.
  - No seed is passed, so the runs are deterministic. But each design consumes the shared `$random` stream
    differently, so the stock and NM builds start from different random states.
  - All files outside Gemmini are identical between builds.
  - The B-wait counts (Berkeley 192, NM24 0, NM48 190) come from the stale contents of the randomised control queue.
  - The 6-cycle reuse gap (1628 vs 1622) is likely random initial state too (not isolated).
  - So "cycle for cycle" is luck, not a property of the design. **Fix:** run several `RANDOM_SEED=<n>` values per
    chip and report ranges.
- **Scope:** the earlier suggestion to gate the counters with `cntl_valid` in the RTL is withdrawn, because that is
  Berkeley's code. The in-scope fix is relabelling or dropping the fig8/fig9 captions.
- **N1 [nit] `run-flow.sh:125-128, 292-303`: the berkeley and nm24_sameprog runs both `cp` the same binary to one
  `$tmpbin` path.** Skip the copy if the file is already there, or use a subfolder per run.
- **N2 [inconsistency] `README.md:178-179`: `bin/` lacks the six original `nm_sparse_*` binaries,** and the Spike
  log isn't in the manifest. **Fix:** copy the binaries into `verification/bin`, then run
  `verify_all.py --write-manifest`.
- **Checked fine:**
  - funct 26 is unique and matches `k_NM_META`.
  - The bench binaries in Chipyard are the ones that produced the logs.
  - The re-runs reproduced 5 of 6 logs byte-for-byte; the sixth differs only in output interleaving.

### Section 3 follow-up (second pass, scoped to your code only)

Every check here ran on Spike and the host, not Verilator. The test programs are in the session scratchpad
(`src/p1..p4, f9, remainder.c`; `host/edge_pack.c, exhaustive.c, dims.c`).

- **P4 → confirmed (likely bug): leftover index state can't be cleared.**
  - The test left a whole tile or half a tile, then turned sparse mode off, flushed and fenced. The next sparse run
    got only 0–1 of 256 outputs right, on both 2:4 and 4:8.
  - In the RTL, `nm_meta_q` and `nm_asm_row` are cleared only by reset.
  - **Fix:** a clear bit (e.g. `config_ex` rs1[11]) in both the RTL and Spike, plus an `nm_reset()` wrapper. Spike
    should warn when sparse mode is turned off with state still pending.
- **P2 → confirmed (model ≠ RTL, low): Spike latches indexes at the preload but reads weights at the compute.** In
  the test, mvin of W2 between the preload and the compute gave W2 weights with idx1 indexes (256/256). The RTL holds
  W1 because of the RS write-after-read dependency. **Fix:** latch the D tile in `preload()`.
- **P1 → confirmed on Spike: the abort message at `gemmini.cc:398-400` is wrong.** The RTL most likely accepts
  indexes sent after their preload. Keep the check, but reword it to "index tile must be sent before its preload"
  and document the rule.
- **P3 → confirmed on Spike: with a GARBAGE A, Spike uses a_lo = 0 (`gemmini.cc:629-632`).** The RTL probably feeds
  stale bank data instead. Document "A must not be GARBAGE in sparse mode", and have Spike assert.
- **#9 (dense preload, switch to sparse, compute) → confirmed on Spike:** it uses the stale indexes (256/256), where
  the RTL uses 0.
- **N1 [helper bug] `gemmini_nm.h:191-206, 216-220`: `nm_pack_meta` and `nm_load_meta` always read a full DIM×DIM
  block.**
  - On a bottom-right edge tile, a guard-page test crashed with SIGSEGV; the top-right tile picked up the next row's
    indexes.
  - **Fix:** add `rows, cols` arguments and pad with zeros.
- **N2 [nit] `gemmini_nm.h:183-184`: `nm_meta_cmds` divides by zero (SIGFPE) when DIM·log2(M) > 64.** **Fix:**
  `_Static_assert`s for DIM·log2(M) ≤ 64, M == 2N and DIM % N == 0.
- **Verified correct:**
  - Remainder tiles in the Spike model: 8 cases (I=20, J=24, K=40/48/56, plus I=5, K=24, J=3, each on 2:4 and 4:8)
    gave 0 mismatches.
  - Exhaustive helper tests (4,096 2:4 groups and 390,625 4:8 groups) gave 0 failures. They cover top-n with ties
    going to the lower row, strictly increasing indexes, exact compress/decompress round-trips, and sparse
    dot = dense dot.
  - Index packing matches Spike's decoder at DIM 4, 8 and 32 (2:4) and DIM 4 and 8 (4:8).
- **#23 addendum (from the whole-project agent's final hand-back):** on the same binary, the array time is identical
  on both chips (`ex_active` 1305 fresh, 1257 reused), and so are the tails (74, 66).
  - The 6-cycle reuse gap is entirely in the CPU issue phase (1562 vs 1556). `spad_b_wait` is non-zero only in each
    program's first Gemmini run.
  - Suggested wording: "identical array time; whole job within 6 cycles (0.4%)".
  - #22's "~2778 → ~2460" estimate is withdrawn.

### Section 1 follow-up (second pass, scoped to your code only)

Every check here was static analysis plus mocks, with no simulation. Scripts are in the session scratchpad
(`checks/coldlines.py`).

- **P1 → confirmed (static): timed regions include first-touch I-cache misses.** The 32 KiB I-cache has no prefetch,
  so all misses are cold misses.

  | Binary | dense (cold lines → cycles) | dense_reuse (cold lines → cycles) |
  |---|---|---|
  | `fair_perf_dense_only` | 2 → 1604 | 3 → 1628 |
  | `fair_perf_24` | 3 → 1648 | 5 → 1750 |
  | `fair_perf_48` | 2 → 1601 | 4 → 1768 |

  - About 44 cycles per extra cold line for `dense`.
  - The `cpu_*` runs come later with 0 cold lines, so the "processor-only" time is measured warm.
  - **Fix:** run each loop once untimed before timing it, and/or align the hot functions.
- **NEW: the cold-cache effect is biased against sparse.**
  - `sparse_fresh` touches 8 (2:4) or 9 (4:8) cold lines, against 2 for Berkeley's `dense`.
  - `sparse_reuse` touches 6 or 7, against 3.
  - The 3 extra lines in 2:4 reuse could exceed the whole 64-cycle gap behind the README's 0.96× (plausible; how
    many misses are hidden behind Gemmini work was not simulated).
- **P2 → confirmed (code reading): the NEXT-STEPS "unexplained stall" comes from `fair_perf.c`'s issue order.**
  - Overlap needs P(t+1) and C(t+1) queued behind C(t) (`ExecuteController.scala:641,656`, with
    `third_instruction_needed` always true).
  - `fair_perf.c:143-148` puts the k index commands between them, and the CPU is slower than the array, so it falls
    back to a single preload plus compute: 960/32 = 30 cycles per tile, against about 20 when overlapped.
  - **To try:** send the indexes for up to 4 tiles in a batch (the FIFO depth), then issue those tiles' P/C pairs
    back to back. The gain is unmeasured.
  - This is consistent with section 4's #22: neither of the two original orders overlapped, since both have
    `ex_active=960`.
- **P5 → confirmed (nit): `run-flow.sh:114-120` prints "sleep blocked" even if `systemd-inhibit` failed.** **Fix:**
  `sleep 0.2; kill -0 "$inhibitor"` and warn if it's gone.
- **NEW: `fair-build` builds 4:8 programs under the 2:4 names after `sim nm48`.** This independently confirms
  section 4's finding.
  - `GemminiConfigs.scala:527-528` writes unguarded `#define NM_N/NM_M`, and `step_fair_build` doesn't restore the
    header.
- **NEW [bug, low] `run-flow.sh:370`: in `bench`, `grep … | while` trips errexit when there are no rows.** The script
  exits without a summary after it has already appended rows to `results/cycles.csv`. **Fix:**
  `{ grep … || true; } | while`.
- **NEW [provenance] `run-flow.sh:319`: `rerun` times whatever is currently built.** The six original binaries
  aren't archived (same as section 4's N2).
- **P3 refuted (benign):** the double `cp` happens milliseconds before the ELF is opened. **P4 withdrawn** (it's
  upstream code).
- **Verified correct:**
  - The baseline numbers in `chipyard-setup-notes.md` match the logs.
  - The selftest logs show the bench runs passing.
  - There are no false failures from the "mismatch" heuristic in `parse_log`.
  - The report builders fail only because of the `PROJ` path and the missing `cap/` files.

### Section 2 follow-up (second pass, sparse diff only; checked against the generated Verilog)

- **P8 → confirmed (structure): the activation mux sits on the multiplier's operand path, even with sparsity off.**
  - Stock is `.io_in_a(io_in_a)`; NM48 is an 8:1 mux indexed by `prop ? m2 : m1`.
  - That adds about 4 (2:4) or 5 (4:8) logic levels on a register-to-register path. The fmax cost needs synthesis.
- **P9 → confirmed reachable: any full `config_ex` silently turns sparse mode off,** because no upstream macro sets
  rs1[10] (`gemmini.h:260-261`). The WS config flush doesn't swap buffers (`ExecuteController.scala:103-105,248`),
  so the weights survive.
  - Example: `preload(Wc); compute_preloaded; gemmini_extended_config_ex(WS,…); preload(GARBAGE);
    compute_accumulated` makes the last compute use the sparse weights with dense routing. The result is silently
    wrong.
  - With sparse mode off, real preloads also don't pop the FIFO, so the indexes desync (finding 3).
  - **Fix:**
    - Latch a per-buffer mode bit in MeshWithDelays and assert that each compute's mode matches it.
    - Or make rs1[10] sticky.
    - At minimum, document "every full config_ex must set rs1[10] again".
- **Finding 6 corrected (exact flop counts from the generated SV):**

  | Build | Array flops (PE + Mesh + MeshWithDelays) | Total added flops |
  |---|---|---|
  | Stock | 39,473 | – |
  | 2:4 | 50,306 (**+27%**) | +13,564 |
  | 4:8 | 63,242 (**+60%**) | +27,860 |

  - These replace the earlier +40%/+80% estimates.
  - The fixes (skew the raw 2·DIM activations before grouping, and use sorted n+1 windows) remove about 25% (2:4) or
    40% (4:8) of the added flops.
- **N1 [nit] Sparse programs silently fall back to 2:4.**
  - Both NM configs write the same `gemmini_params.h`, and libgemmini's copy is never regenerated.
  - `gemmini_nm.h` and `gemmini.h` default to `NM_N 2` with no warning, so a default build on the 4:8 chip packs
    2:4 indexes: wrong results and a desynchronized FIFO.
  - **Fix:** a distinct header name per config, plus `#ifndef HAS_NM_SPARSITY` → `#error`.
- **P10 refuted (high confidence, indirect):** firtool removes this kind of unused logic. What's left in dense builds
  is the funct-26 decode and an always-ready port.
- **Verified correct in the generated Verilog:**
  - 4:8 activation-group wiring, with the mux before the skew.
  - The m1/m2 index registers are written exactly when c1/c2 are.
  - Dense-mode gating, for OS and WS, with or without transposes.
  - 4:8 index-row assembly, which wraps after 8 commands.
  - The FIFO is flops, with no new SRAM macros.
  - im2col is disabled, so it doesn't interact with sparse mode.

## Fix round status (stopped at 90% usage, 2026-10-08)

Three xhigh agents (RTL / Spike, helpers and benchmark / scripts and docs) were started to fix the findings above.
All three were stopped early to save usage. **No fixes have landed. All four repos are back to their committed
state**; only the untracked `NEXT-STEPS.md`, `REVIEW-FINDINGS.md` and `fixes-wip/` remain.

Saved in `fixes-wip/` (the scratchpad in /tmp may not survive a reboot):
- `libgemmini-gemmini.h.partial.patch`: the Spike agent's half-done header change. It adds the N:M `#error`s and
  `static_assert`s, `NM_META_FIFO_DEPTH`, the mode-latch fields, the preload D-latch fields and the
  `nm_meta_clear()` declaration.
  - It was reverted because it requires a `-DNM_N/-DNM_M` Makefile hook that doesn't exist yet, so libgemmini
    wouldn't build.
  - Re-apply it with `git -C ~/chipyard/generators/gemmini/software/libgemmini apply <patch>` once the Makefile hook
    and the `gemmini.cc` side are written.
- `fixlog-*.md`: each agent's plan and baseline.
  - RTL: a 7-item checklist, nothing done.
  - Scripts: baseline checks. The MANIFEST verifies 66/66, `verify_all.py` gives 19 pass / 1 skip, and the 62
    protected record files were snapshotted.
  - Spike: a baseline that reproduces the review's mutant results, plus the overflow proof below.
- `numbers.py` / `numbers.out`: doc numbers computed from the recorded logs.

**Useful result from the Spike agent (by reasoning, not run):** full-range int8 data is safe in `fair_perf`.
- One array column sums at most 16 products plus a bias: ≤ 128 + 16·128·128 = 262,272 < 2^19, which fits the
  SInt(20) array output.
- The accumulator sums 8 tiles: ≤ 2,098,176 < 2^31.
- So the RTL tests can move off the [-8, 7] range without overflow.

**Next session:** restart the three fix agents with the same split and the shared protocol spec (clear = NM_META_CMD
with rd==1, mode latched per weight buffer, sparse only with WS and no transposes or loops, FIFO depth 4, a_hi stride
1, `GEMMINI_HW_NM_N/M` header macros). Point them at `fixes-wip/`. Then rebuild the sparse simulators and re-run
`fair` with several `RANDOM_SEED`s before any README numbers change.
