# Fix A review (read-only): N:M index tiles loaded from the scratchpad

Reviewed 2026-11-11 against the frozen spec `fix-a-spec.md`, the RTL log `fix-a.md`, the SW log `fix-a-sw.md`, the
uncommitted Gemmini `src/` diff, the libgemmini and gemmini-rocc-tests diffs (plus the untracked
`bareMetalC/nm_sparse_spad.c`), and the Fix A changes in `verification/fair_perf.c`,
`experiments/streaming/src/stream_bench.c` and `experiments/streaming/investigate/src/`.

Method: code reading only. Nothing outside this file was edited and nothing was built, elaborated or simulated. A
scratch Python model of the RTL's flat index view
(`/tmp/claude-1000/-home-hunter-gemmini-sparsity/02a1660a-afd8-4d63-b078-262a0414bff5/scratchpad/specvec.py`)
reproduced the spec's section 9 hex vectors byte for byte for 2:4 and 4:8. No finding depends on Spike behaviour
that needed a run, so Spike was not rebuilt.

## Summary

- Blockers: 0
- Major: 0
- Minor: 8 (6 confirmed, 2 suspected)

The RTL, Spike and the C helpers agree on the bit layout, the hazard ordering, the assert set and the dense build.
The most important item is M1. Spec rule P5 ("placement is free") is wrong for a LOAD placed between a preload and
its compute: the reservation station issues execute commands in order, so such a LOAD can deadlock the RTL (Spike
completes the same program) and can break the preload/compute overlap. The fix is a spec and doc change. The
current benchmarks never use that placement.

## Confirmed findings

### M1 (minor; spec/doc): a LOAD between a preload and its compute can deadlock, and P5 says this placement is free

- **Where.**
  - `fix-a-spec.md:146-149` (P5: "between a preload and its compute ... Only P1..P4 constrain it").
  - `gemmini-rocc-tests/include/gemmini_nm.h:200-201` ("a load may sit anywhere between other commands").
  - `ReservationStation.scala:340` (load queue is in order), `:342-344` (a load waits for older ex entries that read
    or write its rows: WAR/WAW), `:351-353` (an ex entry, including the LOAD, waits for older loads that write its
    rows: RAW), `:355` (ex entries issue in order).
  - `ExecuteController.scala:711` (a preload fires only when `cmd.valid(1)`), `:739` (a compute fires alone, so only
    preloads need a following command).
- **Evidence.** In the RS, the LOAD is an ordinary ex-queue entry. Every later ex entry waits until the LOAD has
  been issued (`:355`). The LOAD cannot be issued until the mvins of its rows complete (`:351-353`). The preload in
  front of it cannot fire in the execute unit until its compute arrives as the next command (`:711`). The LOAD is
  diverted at `io.cmd` (`ExecuteController.scala:76-100`), so it never stands in for that compute.
- **Failure scenario.** This uses a single-buffered weight prefetch, which is legal in program order:
  1. `gemmini_preload(W_SP, C)` (P reads weight rows `W_SP..`).
  2. `gemmini_mvin(next_w, W_SP)`. This is M1; it WAR-waits for P to complete (`:342-344`).
  3. `nm_mvin_meta_spad(next_meta, IDX, ...)`. This is M2; the load queue is in order, so it waits for M1 to issue (`:340`).
  4. `gemmini_nm_load_spad(IDX, 1)`. This is L; it RAW-waits for M2 to complete (`:351-353`).
  5. `gemmini_compute_preloaded(A_SP, ...)`. This is C; it waits for L to issue (`:355`).

  P needs C in the execute queue (`:711`), so the wait is circular: P→C→L→M2→M1→P. Spike runs the program to
  completion. The RTL hangs until the RS `"pipeline stall"` assert (`ReservationStation.scala:579`, `gemmini_timeout`
  10000 cycles). The cycle also closes when M2 alone overwrites P's weight rows or WAW-hits P's output rows.

  A second, milder effect has the same cause. A LOAD between a preload and its compute, whose index mvin is still in
  flight, holds back that compute. The pair then cannot overlap with the previous compute: mul_pre needs
  `cmd.valid(2)`, `:726`, and `third_instruction_needed` is always true here. So P5's "without breaking the
  compute/preload overlap" holds only if the index mvins have already completed.
- **Context.** Stock Gemmini has the same hazard class for compute operands. With P, then a WAR-on-P mvin, then the
  A mvin, then C, stock Gemmini also deadlocks. Berkeley's software avoids it by issuing every mvin a compute needs
  before that compute's preload. Fix A extends that rule to the LOAD, but the spec states the opposite.
- **Suggested fix.** Doc and spec only; no RTL change is needed for the rebuild.
  - Replace P5 with: "A LOAD issues in order with execute commands. Do not place a LOAD between a preload and its
    compute unless its index rows were moved in before that preload. Placing it after a compute, as the keeper tiler
    does, is always safe."
  - Update the `gemmini_nm.h:200-201` comment to match.
  - Optionally add a positive Spike-and-RTL test of the safe placement, and note the deadlock case in the spec's
    hazard section.

### M2 (minor; process): Controller.scala has never been elaborated

- **Where.** `fix-a.md:45-47`. The new Controller logic is at `Controller.scala:445-461` (4-input completion
  arbiter), `:534-557` (dispatch), `:569-576` and `:581-649` (program-order model, asserts, busy).
- **Evidence.** The RTL agent ran `sbt compile` (type-check only). It elaborated the execute unit and the RS
  standalone, but the full-SoC elaboration was denied by the permission classifier. Chisel errors that only appear
  at elaboration (width inference, unconnected or doubly-driven sinks, a 4th arbiter input on a 3-input build,
  direction mistakes on `nm_ld_completed`) are therefore unchecked in the Controller.
- **Failure scenario.** The first server rebuild fails at elaboration, after the rebuild slot has been booked. That
  costs a rebuild cycle of hours.
- **Suggested fix.** Before the server rebuild, run one CHIRRTL-only full-SoC elaboration of the 2:4, 4:8 and dense
  configs from a scratch CWD with a scratch target dir. This needs user approval.

### M4 (minor; benchmark scope): fair_perf `sparse_spad` keeps the index mvins out of the timed region

- **Where.** `verification/fair_perf.c:370` (`nm_mvin_meta_spad(..., IDX_SP(0, 0), JT * KCT, 0)` once in `main()`,
  before both the warm-up and the timed pass). Compare `:242-251` (only `LOAD_SPAD` is timed) and `:56`
  (`IDX_SP` in bank 2, upper half).
- **Evidence.** The register-path sparse variants move their index data inside the timed region, because the CPU
  reads it from memory and pushes it. `sparse_spad` times only the spad-to-FIFO LOADs. Its index bytes reach the
  scratchpad untimed. The file says so, so this is a scope issue, not a hidden bias.
- **Failure scenario.** A paper table quotes `sparse_spad` next to `sparse_batched` or the fresh-weights rows as an
  end-to-end comparison. It then understates Fix A's real cost by the index DMA time.
- **Suggested fix.** Label `sparse_spad` as "indexes resident in the scratchpad" in every table. Take end-to-end
  and fresh-weights claims only from the streaming keeper bench. That bench times the index mvins:
  `tiled_matmul_nm_v2.h:110-112` runs inside `stream_bench.c:240-244`.

### M5 (minor; spec wording): "it never delays an operand read request" is slightly too strong

- **Where.** `fix-a-spec.md:160-161`. The loader issue condition is at `ExecuteController.scala:1189-1191`. The bank
  read pipeline is in `Scratchpad.scala` (bank output queue and `ex_read_pipe`, about `:510-564`).
- **Evidence.** The loader only issues when the operand logic does not want the port and the bank is ready. But its
  read stays in flight for about `spad_read_delay + 2` cycles in the same in-order bank pipeline. If the operand
  path back-pressures while a loader response is queued behind an operand response, that loader response holds a
  pipeline slot. The bank's `req.ready` can then drop one cycle earlier for the next operand read.
- **Failure scenario.** In rare back-pressure cycles an operand read is delayed by about 1 cycle. Correctness is
  unaffected.
- **Suggested fix.** Reword to "it never takes a cycle an operand read wants; under read back-pressure an in-flight
  loader read can occupy one pipeline slot". No RTL change.

### M6 (minor; test harness): some NEG cases fire two RTL asserts in the same cycle

- **Where.** `bareMetalC/nm_sparse_spad.c:334-335` (NEG 24) and `:342-343` (NEG 28). The asserts are at
  `Controller.scala:600-611`.
- **Evidence.**
  - NEG 24 (n = 5) fails `:604` (tile count 1..4) and `:611` (`ld_n <= nm_room`, and room is at most 4).
  - NEG 28 (`GARBAGE_ADDR`) fails `:600` (not a spad row) and `:601-602` (the rows leave the bank).
  - Each firtool assert prints and calls `$fatal` in its own always block. Verilator's order between them is
    unspecified, so the printed message may be either one, and sometimes only one is printed.
  - NEG 31 legitimately reports the bank message (spec `:186` lists it for "run off the end"), which differs in
    wording from Spike's abort.
- **Failure scenario.** The server NEG matrix greps for one exact message per case. It marks NEG 24 or 28 as
  failing on a correct chip.
- **Suggested fix.** In the matrix, accept any message from a per-case list (24: `:604` or `:611`; 28: `:600` or
  `:601-602`). Alternatively, judge RTL negatives by "sim aborted with an `NM_META_CMD` or `n:m` assert" and check
  the exact text only for single-assert cases.

### M8 (minor; harmless): warm-up runs index the meta array with the sub-problem's NT

- **Where.** The keeper bench warm-up `investigate/src/stream_bench.c:226` calls the variant with `N = 128`. Inside,
  `tiled_matmul_nm_v2.h:111` (Fix A) and `:156` (register path) address the index tiles as
  `(k0 / 2 + c) * NT + j0` with `NT` from the sub-problem, but the arrays are laid out with the full layer's NT. The
  v1 bench (`experiments/streaming/src/stream_bench.c`) has the same pattern.
- **Evidence.** The warm-up fetches the wrong index tiles, so its result is garbage. It is untimed and unchecked,
  and `poison()` plus `evict_l2()` run before the timed pass. The protocol stays legal: tile counts come from the
  same sub-problem.
- **Failure scenario.** None for correctness or timing. The only effect is that the warm-up touches different
  index cache lines than the timed run, which `evict_l2()` makes moot.
- **Suggested fix.** None needed. Optionally pass the full-layer NT (or `ldb`) to the tiler so the warm-up computes
  real values.

## Suspected findings (need a trace or a timing run to confirm)

### M3 (minor; performance): the cross-step early LOAD reads a bank the previous step is still reading

- **Where.** `investigate/src/tiled_matmul_nm_v2.h:184` (LOAD of step g's first batch, issued after step g-1's last
  `compute_preloaded`), `:186-189` (the remaining `ti - 1` garbage-preload/compute pairs of step g-1), and `:67-70`
  (bank map). Bank arbitration is at `ExecuteController.scala:1189-1191`.
- **Evidence.** Index rows go in bank 3 for even buffers and bank 1 for odd ones (`:67`). Per `:95`, even steps
  read banks 0, 1, 2 and odd steps read banks 2, 3, 0, with A_hi in bank 1 or 3. So step g's index rows sit in
  the bank step g-1 reads as A_hi. The cross-step LOAD runs during step g-1's last `ti - 1` computes, so the loader
  only gets bank-3 (or bank-1) cycles between A_hi reads. The LOADs inside a step are fine, because step g never
  reads its own index bank.
- **Failure scenario.** Step g's first preload waits for tile 0. That costs up to about R + 6 cycles per step
  boundary, plus whatever the A_hi stream leaves no gaps for. This reduces the overlap Fix A is meant to buy.
  Expected size: tens of cycles per step.
- **Suggested fix.** Check with `V3_TRACE` or loader-wait counts. If confirmed, put each step's first index batch
  in the bank step g-1 does not read (bank 1 for even g, bank 3 for odd g) and keep later batches where they are.
  Or issue the cross-step LOAD before step g-1's last tile.

### M7 (minor; timing): the loader adds logic on the execute unit's SRAM read-request path

- **Where.** `ExecuteController.scala:537` (`nm_op_rd` = the operand request), `:1189-1191` (`port_free`/`issue`
  use `nm_op_rd` and the bank's `req.ready`), and the `when (mine)` override of `req.valid`/`addr`/`fromDMA` in the
  same block. The RTL agent flags it too (`fix-a.md:57-58`).
- **Evidence.** The loader's `req.valid` depends combinationally on the operand request logic and on the bank's
  `req.ready`. There is no loop: the bank's `req.ready` comes from registered queue state and `resp.ready`, not from
  `req.valid`. firtool found no loops in the standalone execute unit, but the loop check through `Scratchpad.scala`
  only happens at SoC level (see M2). The AND plus the 2:1 mux sit on a path that was already deep.
- **Failure scenario.** fmax drops in the area/timing run, or a combinational loop shows up at SoC level.
- **Suggested fix.** Include this path in the area/timing run. If it is critical, register the loader's issue
  decision one cycle earlier (issue in cycle t+1 when the port was free in cycle t and `nm_op_rd` is still low).

## Checked and found correct

1. **RS hazards.**
   - The LOAD's range is `[addr, addr + n*R)`, with wrap at the last row via `add_with_overflow`
     (`ReservationStation.scala:198-199`, `:226-235`). `op2` copies `op1` (`:244`, `:250-251`), so dependence checks
     that read `opb` see the same range.
   - Older mvins to any of those rows block the LOAD (RAW, `:351-353`). This covers multi-row mvins, the 24-row 4:8
     case split over two mvins, and ranges up to a bank end.
   - Later mvins wait for the LOAD's completion (WAR, `:342-344`). Completion comes only after its last tile is in
     the FIFO, so every read response has already returned. No stale read and no early overwrite is possible.
   - Bank crossing is excluded by assert (`Controller.scala:601-602`). On the single-ported SRAM, DMA writes win and
     the loader respects `req.ready`.
2. **Read-port sharing.**
   - The loader issues only when the operand logic does not want the bank, the bank is ready and the per-bank owner
     queue has room (`:1189-1191`). `nm_op_rd` equals the operand `req.valid` exactly (`:537`).
   - Owner queues of depth `spad_read_delay + 6` exceed the roughly 6 reads that can be outstanding. `readValid`
     hides loader responses from the operand path (`:963`). The loader takes its response the cycle it reaches the
     head, so the in-order bank pipe never stalls on it.
   - A FIFO slot is reserved before a tile's first read, so a chunk write never blocks. "FIFO full, LOAD pending,
     preload waiting" cannot deadlock: the loader holds no responses, and preloads pop the FIFO independently.
   - Im2col is excluded by `require(!hasIm2Col)`.
3. **Bit layout.** Four views agree for 2:4 and 4:8: the RTL flat view (Cat of R 128-bit rows with row 0 lowest,
   then `asTypeOf(Vec(cols, UInt(b)))`, LSB first; `ExecuteController.scala:260-268`, `:1047`), the spec's S layout,
   the Spike decode (LSB first, little-endian bytes), and `nm_pack_meta_spad`. In 2:4, the spad bytes equal
   `nm_pack_meta` bytes. In 4:8, the 3-bit index that straddles the 128-bit row boundary (bits 126-128) is handled
   by the flat Cat. The spec's section 9 vectors reproduce exactly.
4. **Asserts and back-pressure.**
   - The RTL asserts (`Controller.scala:536`, `:551`, `:575`, `:600-611`, `:616-617`, `:622`, `:629`, `:639`) use
     the same program-order model and conditions as Spike's aborts. P4 is RTL-only by design (spec `:143-145`).
   - The FIFO-budget asserts are evaluated at dispatch on the program-order model, never on hardware occupancy, so
     legal back-pressure cannot fire them. The loader's internal asserts are unreachable given its slot reservation.
   - NEG 36 works on the RTL: the RS reports not-busy when its only entry is a preload
     (`ReservationStation.scala:140`, `solitary_preload`). So `gemmini_nm_reset()`'s fence completes and the CLEAR
     reaches the `:617` assert.
5. **Dense build (nm = None).**
   - `funct_is_nm_ld` is a constant false.
   - The completion arbiter keeps 3 inputs.
   - `nm_ld_q`, the owner queues and the loader are not generated; the `readValid` term is constant true.
   - Funct 26 with any `rd` still asserts and is dropped (`Controller.scala:536`), as before Fix A.
   - Berkeley paths are untouched.
6. **Benchmark fairness (streaming keeper).**
   - All variants compute the same layer.
   - Outputs are poisoned before every run and checked by a hash of all of C plus a full compare of sampled rows
     (`stream_bench.c:150-168`, `:225-259`).
   - The timed region covers the whole tiler call, including the index mvins (`tiled_matmul_nm_v2.h:110-112`).
   - The 4:8 repack into the spad format is a one-time untimed format conversion (`stream_bench.c:208-216`),
     analogous to the offline `nm_pack_meta` the other variants rely on.
   - The keeper never places a LOAD between a preload and its compute. Each LOAD's index mvins go out at least an
     iteration earlier, so M1 does not apply and the RS ex queue sees no head-of-line stall.
   - Only the `fair_perf` scope caveat (M4) remains.
