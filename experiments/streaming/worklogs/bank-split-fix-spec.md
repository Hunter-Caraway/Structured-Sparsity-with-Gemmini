STATUS: DRAFT (2026-11-17). Not frozen; the user freezes it. No code may be written from it until then.

# bank-split-fix spec: put a_lo and a_hi of the sparse LOOP_WS loop in different scratchpad banks

Author: spec agent, 2026-11-17. Read-only against RTL `sparse-loop-fix`, libgemmini `sparse-loop-fix`, gemmini-rocc-tests `sparse-loop-fix`.
Builds on `fix-b-spec.md` (FROZEN; changes here go into its changelog once this spec is frozen). Background: `loop-bank-check.md`.
Tags: [M] read in source or measured (cited), [E] estimate (reasoning given), [Q] open question.

## 0. Summary and recommendation

Problem in one line: the sparse loop reads two 16-row activation tiles per compute (a_lo and a_hi). They sit next to each other, so
they are in the same scratchpad bank. One bank gives one row per cycle, so the two reads take turns: 32 cycles per compute instead of 16.
The "2x fewer computes" of sparsity is paid back in waiting.

Recommended (design 1, "pair layout"): inside the sparse loop only, store even K tiles (a_lo) in one bank and odd K tiles (a_hi) in the
other bank of the loop's half. No new instruction, no new ISA field, no change to dense builds. Changed code: the sparse side of
`LoopMatmul.scala` (our code) and one small gated edit in Berkeley's `LoopMatmulLdA`. Capacity cost is about zero (section 3.1).
Effort 5 to 6 working days [E]. Before any RTL work, measure the gain with two simulations on the existing nm24 and nm48 simulators (section 8).

Not possible: a software-only fix. The loop computes `a_hi = a_lo + DIM` itself and A tiles are 32-row aligned, so a_lo and a_hi can
never straddle a 4096-row bank boundary, whatever address the software picks (section 2.4). Also not possible: a scheduler-only fix in
`ExecuteController` (section 2.3).

## 1. Problem (with citations)

- Bank = high address bits: `LocalAddr.scala:33` (`sp_bank` = `data(spAddrBits-1, spBankRowBits)`). Config: 4 banks x 4096 rows, single-ported (`Configs.scala:44, 47`) [M].
- Loop address: `LoopMatmul.scala:616` `a_lo = a_addr_start + (i*max_k + 2k)*DIM`; `:620` (the `comp_cmd_rs2.local_addr` line) `a_hi = a_lo + block_size`. A tile (i,c) sits at row `(i*max_k + c)*DIM` from the half start, so it is 16-row aligned and a_lo is the tile with an even c [M].
- a_hi travels in the B operand stream: `ExecuteController.scala:361` (`b_address = b_address_rs2 + b_fire_counter`) [M].
- Stall rule: `ExecuteController.scala:426-466`. `same_bank()` (:426-436) is true when two operands read the same bank; `must_wait_for` (:461-466) = `(same_bank && higher_priority && same_counter) || one_ahead`. A has priority 0, B priority 1, D priority 2 (:448-450). So B (a_hi) waits for A (a_lo) every row, and A and B alternate: 2 cycles per row [M code reading].
- Tile (i,2k) starts at a multiple of 32 rows and tile (i,2k+1) ends at a multiple of 32 rows; 4096 is a multiple of 32, so the pair is always inside one bank [E, arithmetic]. Hence every loop, any shape, any `a_addr_start`, runs same-bank.
- Counter evidence [M] `investigate/runs/20261113-160015-fixb-srv`, `nm24.bert_qkv_24_loop.seed1.log` line 23: `sparse_loop total 305747 ex_active=290794`; `nm24.bert_qkv_24_full.seed1.log` (Berkeley loop, dense): `ex_active=292031, total 317206` (per `loop-bank-check.md`). Sparse does half the computes at the same ex_active as dense: consistent with 2x cycles per compute [E, inferred, not isolated].
- Direct measurement of the effect exists only for the per-tile path, not the loop [M] `investigate/runs/20261109-192612-micro2`: `sp_same_tight` 32.20 cycles/compute, `sp_diff_tight` 16.19, `dense_tight` 16.15 on nm24 (`worklogs/investigate.md` section 5). Tiler test: BANKSPLIT cut ex_active 8,836 to 5,469 (-38%), `investigate.md` section 4 [M, small layer, CPU-bound tiler so total got worse].
- The wait counters `spad_a_wait` / `spad_b_wait` do NOT show this stall: they count cycles where the operand fired but the mesh was not ready (`ExecuteController.scala:1265-1268`), not cycles blocked in `must_wait_for`. So the `spad_b_wait=1340` of the fair_perf log in `loop-bank-check.md` neither supports nor contradicts the claim. Use `ex_active` and cycles per compute.
- Expected gain [E, estimate only, not measured]: caller estimate about 35% lower `ex_active`; ideal 50% (32 to 16 cycles per compute). Total time is limited by DMA too: same log line 23 shows `rdma_active=162216`, `load_active=104121`, so total will fall less than ex_active.

## 2. Candidate designs

### 2.1 Design 1 (recommended): pair layout in the sparse loop (new address map for A inside the loop)
Idea: K tile parity picks the bank. Sparse loop only (`nm` = LOOP_WS rs1[3]).
- Region E (even K tiles, the a_lo tiles) at the bottom of the loop's half (bank 0 of the half). Region O (odd K tiles, the a_hi tiles) in the second bank of the half.
- Address of A tile (i, c): `base(c & 1) + (i*kb + (c >> 1))*DIM`, with kb = max_k/2 (max_k even, assert N6). `base(0) = a_addr_start`, `base(1) = o_start`.
- Compute: `a_lo = E + (i*kb + k)*DIM`, `a_hi = a_lo + a_hi_off` with the loop constant `a_hi_off = o_start - a_addr_start` (replaces `+ block_size`).
- LdA (Berkeley module `LoopMatmulLdA`, `LoopMatmul.scala:28-110`): new address formula and 1-tile mvins in nm mode (the 4-tile block mvin writes consecutive rows, which would not match the split layout). The LdA request needs an `nm` bit and `o_start`: generated only on N:M builds (`nm_sparsity.isDefined`).
- Layout of the half (rows from the half start, bank size S = 4096), Ea = I*kb*DIM, Bsz = kb*J*DIM, idx = kb*J*R:
  `[0, Ea)` E | `[Ea, Ea+Bsz)` B (contiguous, may cross the bank boundary; tile aligned because Ea and S are multiples of DIM) | `[o_start, o_start+Ea)` O with `o_start = max(S, Ea+Bsz)` | `[2S - idx, 2S)` index rows (one bank, as today, 2.5.4 of fix-b-spec).
  Legal when `Ea <= S` and `o_start + Ea <= 2S - idx`.
- Worked example, the qkv tile (I=5, J=6, K=48; log line 22) [E, arithmetic]: Ea = 5*24*16 = 1920, Bsz = 24*6*16 = 2304, idx = 24*6*4 = 576 (R=4 for 2:4). Ea+Bsz = 4224 >= S so o_start = 4224, O ends at 6144 <= 8192-576 = 7616. Fits, same tile as today.
- Where the readers end up: a_lo reads in bank 0, a_hi in bank 1. B (weights, read by D during a preload) straddles both banks, so a preload row can meet a_lo or a_hi in the same bank. D has the lowest priority, so D waits, not A or B. How much that costs is open (Q4); the micro-test (section 8) measures it.
- Pros: only sparse-loop code and a gated LdA edit; no new ISA; dense builds unchanged; Spike changes are address formulas; works for 2:4, 4:8, 8:16 (independent of m); capacity about unchanged; compatible with the 4x design (section 6).
- Cons: loop and Spike must agree on a new internal address map (a mistake gives wrong results, not a stall, so Spike tests catch it); 1-tile LdA mvins raise the mvin count in nm loops [E: LdA moves up to 4 tiles per mvin today (`max_block_len`); 1 tile per mvin means up to 4x the A mvin commands, each 16 rows; DMA time should be bandwidth-bound, but measure]; `nm_loop_fits` per-bank rules change.
- Berkeley lines touched: `LoopMatmulLdA` (`LoopMatmul.scala:28-110`: `sp_addr` :68, `max_blocks` :62, new req fields :15-26, the LdA instantiation and req wiring in the unroller); the remaining edits are on `// changed: sparse-loop-fix` lines already ours (`:597-620` region).
- Dense impact: all new logic under `nm_sparsity.isDefined`; dense LdA keeps `Mux`-free original formula. Check by the dense-Verilog diff method of `dense-verilog-diff.md` (normalised line bag identical, no new regs). Rule: the dense build must stay logic-equivalent.
- Spike impact: `libgemmini/gemmini.cc` loop code: A mvin destination (the `A_sp_addr` computation near :1053-1063) and the compute rs2 (`A_sp_addr + DIM` at :1112) take the pair formulas; N9 capacity check (:957) gets the new per-bank rule. Spike has no timing, so results are unchanged; only address consistency and asserts matter.
- Scratchpad capacity cost: about zero when `Ea + Bsz >= S` (as above, same total). If `Ea + Bsz < S`, the O region starts at the bank boundary and the gap [Ea+Bsz, S) is unused: small loops only [E]. New hard limit `Ea <= S`, i.e. `I*K/2*16 <= 4096`; with the existing `A+B+idx <= 8192` bound this removes only shapes with I*K > 512 A tiles that were already almost the whole half.
- Software: `nm_loop_spad_rows`, `nm_loop_fits`, `nm_loop_tiles` in `gemmini_nm.h:~600-640` get the new rule; `tiled_matmul_nm_loop` call shape unchanged; config_ld block stride is not used by nm LdA.

### 2.2 Design 2: bank hash in the scratchpad address decode (RTL, all accesses)
Idea: swap the bank bit with the tile-parity bit: bank bit 0 = `addr[12] ^ addr[4]` (row bit 4 = parity of the 16-row tile). The split is then in hardware for every tile, in the loop and out of it, with no layout or tiler change.
- Pros: no capacity cost, no tiler change, per-tile path also split for free.
- Cons: touches `LocalAddr.sp_bank/sp_row` (`LocalAddr.scala:33-34`) used by the scratchpad, DMA, LoadController, ExecuteController; every access on an N:M chip changes, including dense computes on nm chips (their cycle counts move; dense-vs-nm comparisons on the same chip change meaning). The Fix A rule "all n*R index rows in one bank" no longer holds for ranges over 16 rows or a 12-row 4:8 LOAD crossing a 16-row boundary (`fix-a-spec.md` LOAD bank rule): rework of Fix A. Many Berkeley lines (shared by all consumers). Spike must model the hash for the one-bank asserts. High risk for the dense-equivalence check.
- Effort 8 to 10 days [E]. Rejected unless Q2 asks for a chip-wide fix.

### 2.3 Design 3 (rejected): change the read scheduling in `ExecuteController`
`must_wait_for` is correct: a single-ported bank gives one row per cycle, and a compute needs 32 rows (16 a_lo + 16 a_hi) from the same bank. Removing the wait only moves the conflict into the scratchpad read queue (same bank, same cycle). A scheduler change cannot make a bank deliver two rows per cycle [E, from `Configs.scala:44, 47`]. The only scheduler-level gain is overlapping a_lo and a_hi of different computes, which is already what the pipeline does. Rejected.
A two-row-wide bank read (256-bit port) would work but changes the scratchpad memory macro: out of scope for this window.

### 2.4 Design 4 (rejected): software-only
- Per-tile path (Fix A, `gemmini_nm.h:504-506`): software already can place a_lo/a_hi in any banks (`investigate/src/nm_stream_v2.h` V2_BANKSPLIT, 2-tile mvins with `block_mvin_stride = BANK_ROWS`). Not the loop.
- Loop: `a_hi = a_lo + block_size` is hardwired (`LoopMatmul.scala:620`) and `a_addr_start` is fixed by the loop id (Berkeley `a_addr_start = i*max_addr/2`, `fix-b-spec.md` 2.5.4). With A at a 16-row-aligned address the pair never crosses a bank boundary (section 1). `a_spad_id`/`b_spad_id` only pick the half. No existing instruction changes this. A software workaround would be to stop using the loop: loses Fix B.

### 2.5 Comparison
| design | RTL files (Berkeley, gated) | dense equivalence risk | capacity | effort [E] |
|---|---|---|---|---|
| 1 pair layout | LoopMatmul (LdA + our sparse side) | low | about 0 | 5-6 d |
| 2 bank hash | LocalAddr, Scratchpad, LoadController, ExecuteController, Fix A rules | medium-high | 0 | 8-10 d |
| 3 scheduler | none | n/a | n/a | impossible |
| 4 software | none | n/a | n/a | impossible |

## 3. Design 1 in detail (what RTL and Spike both implement)

### 3.1 Semantics
Inputs as in fix-b-spec 2.5 (A as dense in DRAM, B compressed, index tiles). New internal A map (above). Nothing visible to software changes except: sparse loops need `Ea <= 4096` and the new fit rule.
Order of operations, LdA/LdB lookahead gates (`a_hi_tile = Cat(k,1)`, :597), LOAD rule and index FIFO rules are unchanged: they use tile counters, not addresses.
Accumulator, C, bias: untouched.
`a_hi_off` is computed once per loop start from the request (`max_i`, `max_k`, `max_j`) in the unroller, not per compute.

### 3.2 Asserts (messages start with the feature name `"bank-split-fix: ..."`; Spike aborts with the same text) and NEG tests
| id | assert | NEG test (software, in `bareMetalC/nm_sparse_loop.c`, `-DNEG=<n>`) |
|---|---|---|
| BS1 | E region exceeds one bank (`Ea > 4096`) | none possible: `Ea > 4096` means A = 2*Ea > 8192 rows, which N9 (total fits the half) already aborts. Dropped as an assert; N9 NEG 90 covers it [E, arithmetic] |
| BS2 | O region end overlaps the index region | none new: if `Ea+Bsz >= 4096` it is the N9 total rule; else `Ea + idx < Ea + Bsz < 4096` (idx < Bsz since R < DIM), so it fits [E, arithmetic]. Covered by N9 NEG 90/91 with a shape near the limit |
| BS3 | internal: a_lo and a_hi banks must differ at every sparse compute | cannot be triggered from software (loop constants). Verified by mutant M2 (section 7) and a Spike-side check of `bank(a_lo) != bank(a_hi)` that the mutant trips |
| BS4 | LdA in nm mode with an odd tile column (c odd as first tile of a pair run) cannot happen (N6) | covered by existing NEG 60 |
Note: BS1/BS2 are implied by N9 (arithmetic above), so only BS3 is a new assert; the implementer re-checks the arithmetic against the real code. N9's message text gets the per-bank wording (Q6).

### 3.3 What does not change
ISA, encodings (funct 26/27/28, rs1[3]), index loader, PE, mesh, accumulator, dense chips, per-tile path, Berkeley's dense loop.

## 4. Spike impact (summary)
Same address maps in `gemmini.cc` loop code; capacity rule; BS asserts. Spike tests: existing `nm_sparse_loop.c` (all cases), plus new cases with layouts where E ends exactly at a bank, B straddles the bank boundary, `Ea+Bsz < S` (gap). Run on 2:4 and 4:8 (and 8:16 now that nm816 exists), Spike built only in a scratch dir with `--extlib`.

## 5. Risks
- LdA 1-tile mvins may slow the DMA side [E]; measured in section 8 case "loop mvin" (optional) and in the server run after the rebuild.
- Weights straddling both banks: D waits behind A/B in one of them (Q4).
- The existing 2x loop results change; README table / paper numbers need re-measuring with user approval (AGENTS: README and paper numbers change only with approval) (Q3).
- Fix B spec is FROZEN: needs a changelog entry (Q5).

## 6. Interaction with `wide-act-fix-spec.md` (4x design, DRAFT)
- Compatible. Parity layout generalises: tile c goes to E if c is even, O if odd. In the 4x design phase p uses tiles (4k+2p, 4k+2p+1): both phases get (even, odd) = (E, O), so every phase is split.
- Edits collide: both specs change `LoopMatmul.scala:616` (`a_lo`), `:620`, and `:597` (`a_hi_tile`). Order: bank-split first (wide-act Q1 recommends the same). Then wide-act 3.4 formulas become `a_lo(ph) = E + (i*kb + 2k + ph)*DIM`, `a_hi(ph) = a_lo(ph) + a_hi_off` (kb = max_k/2 still counts tile pairs); K stepping by 4 tiles is unchanged. Its `a_hi_tile` lookahead is address-free.
- The bank-split makes 4x array time 2 computes x 16 cycles = 32 per 64 K (wide-act 0 and 3). Without bank-split the same would be 64 (wide-act "same-bank" row of its table).
- wide-act option A (4 operand streams, 4 banks) needs all 4 banks but a loop state owns only 2 banks (half = 8192 rows): bank-split does not block option A and does not help it either. wide-act's capacity numbers (B quarter size) combine with the Ea rule: Ea = I*max_k/2*16 still applies.
- Wide-act changes `max_k_b = max_k >> log2(ratio)`; `Ea` uses A tile count only, independent of that.
- The wide-act "Not verified (2)" (loop at 2 cycles/row) is answered by code reading here; the sims in section 8 are the measurement.

## 7. Mutant plan and verification
Mutants (built in scratch dirs only; the RTL mutant is Chisel-elaborated only with approval, Spike mutants are cheap):
- M1 (Spike and RTL): `a_hi_off = DIM` (old layout). Layout-consistent tests still pass; the bank assert BS3 must fire; the section 8 micro result must not change (it is hand-laid). Detects: forgotten wiring.
- M2 (Spike): a_hi from O region but LdA writes the odd tiles to E (mismatch). The data check in `nm_sparse_loop.c` must fail (wrong C).
- M3 (Spike): drop the N9 capacity check. NEG 90 must then fail to abort (exit 0 = not caught).
- M4 (Spike): O region base `+16` rows off. The data check must fail.
Done criteria (AGENTS "Done means"): Spike tests pass on 2:4 and 4:8; every assert has a NEG; new tests fail on M1-M4; Berkeley's 54 dense tests pass (unchanged Berkeley Makefile list, `matmul_spad` and `mvin_mvout_spad` excluded); then server Verilator confirms.

## 8. Micro-test plan: measure the gain before any RTL change (no rebuild)

What is and is not measurable: the loop itself cannot be forced into a split layout without an RTL change (section 2.4). So the micro-test replays the loop's command stream with per-tile instructions, with the activations hand-placed in different layouts. It measures the array (EX) side with the CPU feed made tight; it does NOT measure the DMA/LdA side or the real loop's end-to-end gain. For those, the first real number comes after the RTL rebuild.

Simulator: the existing Fix B simulators on the server, no rebuild: nm24 `GemminiNMRocketConfig` (sha256 `1042fc92...` per `runs/20261113-160015-fixb-srv/run.info`) and nm48 (`f4a3642c...`). They are the sparse-loop-fix builds, so the per-tile path (Fix A) is available. Server only (AGENTS: server runs need the usual approval and a quota; 2 sims here).

Test: a new bench `investigate/src/micro_loop.c` (new file, derived from `investigate/src/micro2.c` `tight()`: precomputed rs1/rs2 array, 2 loads + 1 RoCC per command, warm index tiles). Not part of the Berkeley tree. Build with `investigate/scripts/build_one.sh`, -DNM_N/-DNM_M, like micro2.
- Schedule: the loop's execute order (fix-b-spec 1.5): for (k = 0..kb-1) for (j) for (i): preload (real at i==0, GARBAGE otherwise), compute (`compute_preloaded` at i==0 then `compute_accumulated`), C accumulate when k != 0. One loop call shape per case.
- Shapes: S_A = the qkv full tile, I=5, J=6, K=48 tiles (kb=24, 720 computes; log line 22 of `nm24.bert_qkv_24_loop.seed1.log`); S_B = the qkv remainder tile I=3, J=6, K=48 (432 computes).
- Layouts (A placement, rows within banks 0-3 of the whole chip; each runs the same data):
  - L0 same: a_hi = a_lo + DIM, region as the loop today (bank 0); B top of bank 1; index rows in a bank-3 staging area as in micro2. (current loop)
  - L1 pair, B with a_lo: E bank 0, O bank 1, B in bank 0 after E (or in bank 2 if it does not fit)
  - L2 pair, B with a_hi: E bank 0, O bank 1, B in bank 1
  - L3 pair, B straddling (the design-1 layout): sizes as section 2.1 (needs the 2-bank half: E at 0, B at 1920.., O at 4224, all in banks 0-1)
  - L4 upper bound: E bank 0, O bank 1, B bank 2 (not available inside one loop half; shows what is lost to B conflicts)
  - Dense reference in the same binary and same chip (dense mode on nm24, K = 96 tiles, 1440 computes): ceiling `dense_tight`, so the comparison stays within one build.
- Placement: A tiles moved in with `gemmini_extended_mvin` (1 tile per mvin) before the timed window; W and index rows also staged before the window (as micro2). The timed window holds only the compute stream, up to the fence, then C mvout after it (untimed).
- Counters (`gemmini_counter.h`, as micro2): `ex_active`, `pre_haz`, `overlap_haz`, `rs_busy`, total cycles to fence; per case print cycles/compute. Warm-up pass then measured pass (micro2 convention).
- Expected [E, from micro2 `sp_same_tight` 32.20 and `sp_diff_tight` 16.19, `investigate.md` section 5]: L0 about 32 cycles/compute (S_A about 23,000 ex_active), L1-L3 about 16-20 (S_A about 11,500-14,400); dense about 16 per compute but 1440 computes (about 23,000). L2 or L3 may show D stalls from preloads (that is the point of the B-placement cases). If L3 is not close to L4, Q4 is decided against the straddling layout.
- Verification: every case dumps C (acc to DRAM with mvout) and is compared to a CPU reference computed from the same compressed weights with `nm_ref_sparse` (`gemmini_nm.h:95-180`) plus the dense reference for the dense case; a case prints `verified` or `FAILED`; a failed or missing line makes the run invalid (AGENTS rule 4: cycle count counts only if verified). Use full-range int8 data and poison C first (as `nm_sparse_loop.c`).
- Sims: S1 = nm24 `micro_loop_24` (all cases, both shapes, seed 1); S2 = nm48 `micro_loop_48` (4:8, same cycles expected since same compute count). Optional S3 = nm24 with a preload-heavy shape I=1, J=6, K=48 (TI=1 per preload, shows the B-placement cost at its worst). Run folder `~/sinv/runs/<stamp>-banksplit-micro-srv` copied back to `experiments/streaming/investigate/runs/` with `run.info`, `jobs.tsv`, `SHA256SUMS` (AGENTS). Cost: well under an hour of sim time each [E, micro2's 512-compute runs took minutes; ~10x more computes here].
- Spike first: the same binary runs on Spike (2:4, 4:8) to check that the data verifies before any sim.
- Effort: 1 day to write and Spike-test, 0.5 day server and parse [E].

## 9. Test plan
1. Spec frozen; Spike agent and RTL agent implement the same spec (section 3).
2. Spike (scratch dir, `--extlib`): `nm_sparse_loop.c` all cases + new layout cases + N9 NEG 90/91, 2:4, 4:8, 8:16; mutants M1-M4.
3. `sbt` compile on the RTL branch after each edit (no elaboration on the laptop).
4. Dense Verilog diff on the server (approved build) as in `dense-verilog-diff.md`: dense netlist logic-equivalent.
5. Verilator on the server after approved rebuild (backup the simulator and `generated-src` first): `nm_sparse_loop` full set, bert_qkv/ffn1/ffn2 loop vs the pre-fix numbers (same build comparison only: before = `runs/20261113-160015-fixb-srv`, after = new run; rule 4 allows cross-chip ratios per the 2026-11-12 ruling).
6. Compare `ex_active` and total per layer; report the measured gain; README/paper numbers only with user approval.

## 10. Effort (agent working days, excluding waiting on user and builds) [E]
Micro-test 1.5; spec freeze review 0.5; RTL 1.5; Spike 1; software tiler/tests 1; NEG and mutants 1; server verification 1. Total design 1 about 7.5 days including the micro-test; RTL-side work about 5 to 6 (the 2-day figure in `wide-act-fix-spec.md` section "Cut line" counted only RTL edits). Design 2 about 8 to 10 days.

## 11. Open questions for the user
- Q1. Go with design 1 (pair layout in the sparse loop)? Design 2 (chip-wide bank hash) only if you also want dense computes on nm chips split.
- Q2. Run the two micro-test sims (nm24, nm48; optional third) on the server first? No rebuild is needed.
- Q3. A fix changes every existing 2x loop number (qkv 305,747 etc.). May the agent re-measure afterwards and propose README/paper updates for your approval?
- Q4. B placement: let the micro-test (L1-L4) decide between "straddle" (default), "with a_lo" and "with a_hi"? Or fix the straddling layout now?
- Q5. Fix B spec is FROZEN. OK to add a changelog entry (new A address map inside sparse loops, new per-bank fit rule)?
- Q6. BS1 and BS2 look implied by N9: OK to extend the N9 message text instead of adding new asserts?
- Q7. LdA 1-tile mvins in nm loops: accept (and measure) or require 2-tile mvins with a block stride (needs more RTL)?
- Q8. Do this before the wide-act (4x) work? (Recommended: yes, the 4x array gain depends on it.)

## Changelog
- 2026-11-17: first draft.
