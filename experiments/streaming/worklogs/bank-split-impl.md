# bank-split-impl worklog (design 1 of bank-split-fix-spec.md, RTL + Spike + tests)

Agent: bank-split impl agent. Started 2026-11-17. Laptop only (no elaboration, no Verilator, no server).

## Steps
1. Read bank-split-fix-spec.md (FROZEN), fix-b-spec.md, loop-bank-check.md, wide-act-fix-spec.md, nm816-config.md, AGENTS.md.
2. Branches `bank-split-fix` from `sparse-loop-fix`: gemmini (11cc20cd + cherry-pick of nm816-config f37093d7 as adb9d640, to keep
   the 8:16 config so the Spike run can cover nm816), libgemmini (d048776), gemmini-rocc-tests (22158bf).
3. RTL (gemmini `bank-split-fix` ec91f132), LoopMatmul.scala only: LdA (Berkeley) gets gated req fields nm/o_start, 1-tile
   mvins and the E/O address in nm mode (dense: renamed max_blocks_dense/sp_addr_dense, same logic); ex req a_hi_off/idx_start,
   a_lo = A + (i*kb + k)*DIM, a_hi = a_lo + o_off, BS3 assert; unroller defs a_base/nm_ea/nm_bsz/nm_b_off/nm_o_off/nm_b_end
   (straddle = nm_b_off/nm_o_off pair), LdB/ex B end = A base + ea + bsz, LdIdx unchanged; N9 text extended (condition unchanged).
   sbt `;project gemmini; compile; project chipyard; compile` both [success] (log copied to run folder later).
   Arithmetic re-check (spec 3.2 BS1/BS2): under N9 (2ea + bsz + idx <= 2S, idx < bsz since R <= 8 < 16): ea <= S; if ea+bsz >= S then
   O end = A+B <= 2S-idx; else O = [S, S+ea), S+ea+idx < S+ea+bsz < 2S. So straddle needs no new condition; nm_loop_fits unchanged.
   Spec note: "E ends exactly at a bank" (ea = S) is unreachable (A = 2S leaves no room for B); tested instead: B ends exactly at S.
   Anomaly (Berkeley, not ours): LOOP_WS_CONFIG_SPAD_AB can set a non bank-aligned a_addr_start; Spike ignores SPAD_AB. A sparse loop
   with such a start would trip BS3 in RTL (not silent). Software never issues SPAD_AB.
4. Spike (libgemmini `bank-split-fix` e33244f): gemmini.cc loop_ws: nm_ea/nm_bsz/nm_b_off/nm_o_off (same straddle pair as RTL),
   B start = A start + ea, index start taken before B moves, A mvin (i*KB+k) to E and odd tile to E + o_off, compute rs2 = a_hi,
   BS3 check (abort text "GEMMINI: bank-split-fix: internal: a_lo and a_hi of a sparse loop compute are in the same scratchpad bank"),
   N9 text extended (prefix unchanged, so run-flow's grep -F still matches).
5. Tests (rocc-tests `bank-split-fix` 95a6a73): nm_sparse_loop.c 3 new cases (B ends at bank, B straddles + pads, 2 straddling loops),
   NEG 92 (ea > 1 bank -> N9); gemmini_nm.h comment only (nm_loop_fits unchanged, proof in step 3).
6. Run folder experiments/streaming/investigate/runs/20261117-142952-banksplit-spike/. SCRATCH_DIR=build-scratch/banksplit.
   spike-lib x6 OK; tests 174 built; `run-flow.sh spike nm24|nm48|nm816`: 97 pass / 0 FAIL each
   (logs/runs/spike-20261117-142923.log, -142929, -142935; summaries build-scratch/banksplit/spike-nm*.summary, copied later).
   NEG 92 + 90/91 text on nm and dense libs: run folder neg/ (all abort with the extended N9 text; dense lib: N14).
7. Spike mutants (scratchpad, sources as diffs in run folder mutant/): M1 BS3 abort (detected, 3 patterns); M2, M4 data fail
   22/22 old + 3/3 new cases (detected); M3 NEG 90/92 lose the N9 text (detected); M5 (O = S always, overlaps a straddling B):
   MISSED by Spike: Spike's loop_ws loads each tile just in time, so overlapping regions never corrupt. RTL-only mutant.
   fair_perf sparse_loop still verifies under M2: verification/fair_perf.c:56 A_SP puts odd A tiles at BANK_ROWS + (it*KT/2+kt/2)*DIM
   = the new O rows, stale data from the per-tile variants matches. nm_sparse_loop is the layout test, not fair_perf.
8. Comment wording (no history): gemmini d185001a (sbt [success], run folder sbt-final.log), libgemmini 4886238 (6 libs rebuilt:
   byte-identical sha256). Submodule pointers bumped in gemmini: 26813f12, 59d8f546, 7b19c038.
9. RTL timeout risk: nm_sparse_loop_24 Spike instructions 23,101,494 (old) -> 82,292,574 (95a6a73) -> 59,512,572 after shrinking M in the
   bank cases (rocc-tests 2ad1fd3); run folder icount/nm_sparse_loop_24.txt. Final pass re-ran spike nm24/48/816 (97/0 each,
   logs/runs/spike-20261117-144351.log, -144357, -144402), NEG and mutants (same outcome as pass 1; pass 1 kept in pass1-tests-95a6a73/).
10. Benches (bench.sh, 6 layers x {24,48,816} x full/fixa/loop): 54/54 verified (bench/summary.txt, STATUS PASS). Spike counts of the
   loop variant unchanged where a pre-fix run exists (8:16 all 6 layers equal to runs/20261117-115410-nm816-spike, e.g. bert_qkv_816_loop
   total 1459 both). Spike has no timing: these are instruction counts, not speed.
11. fix-b-spec.md changelog entry 2026-11-17 added (Q5). run-flow.sh not edited (N9 grep -F matches the old prefix; NEG 92 run by
   neg_mutants.sh in the run folder instead of adding it to loop_neg).

## RESUME HERE
- Done: RTL, Spike, tests, NEG 92, Spike mutants M1-M5, run folder investigate/runs/20261117-142952-banksplit-spike/ (run.info, SHA256SUMS ok).
  Commits (not pushed): gemmini bank-split-fix 7b19c038 (RTL ec91f132 + d185001a; nm816 cherry-pick adb9d640), libgemmini 4886238,
  rocc-tests 2ad1fd3. gemmini-sparsity: fix-b-spec.md changelog, this worklog, run folder uncommitted (coordinator commits).
- Running: nothing.
- Findings: (a) Spike cannot catch region overlaps (M5 missed: loop_ws loads tiles just in time) -> RTL mutant rtl-mutant/rtl-m5.patch.
  (b) fair_perf sparse_loop is not a layout test (verification/fair_perf.c:56 leaves the O rows filled with the right tiles).
  (c) run-flow.sh prog_timeout pattern `nm_sparse_loop_[0-9][0-9]-baremetal` misses `_816` (150M default) - pre-existing.
  (d) nm_sparse_loop is 2.6x the Spike instructions it was; RTL may need TIMEOUT_CYCLES 600M (estimate, not measured).
  (e) Berkeley LOOP_WS_CONFIG_SPAD_AB can set a non-bank-aligned a_addr_start; BS3 would fire (not silent). Not used by software.
- Next (server, needs user approval): sync the three repos to the commits above, rebuild nm24/nm48 (+ nm816 first build),
  dense Verilog diff vs stock, RTL rerun of nm_sparse_loop + NEG 90/91/92 + bench loop layers; optional RTL mutants M1/M5.
