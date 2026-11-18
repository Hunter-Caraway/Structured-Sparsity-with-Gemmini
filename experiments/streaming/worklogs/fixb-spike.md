# fixb-spike: Spike model of sparse-loop-fix (Fix B), agent worklog, 2026-11-12

Scope: `~/chipyard/generators/gemmini/software/libgemmini/gemmini.cc`, `gemmini.h` (branch `sparse-loop-fix`, HEAD 2a6ff44,
uncommitted). Spec: `fix-b-spec.md` (FROZEN 2026-11-12) section 4 and 2.5.6. No server, no sims, no git writes.
Evidence folder (new, copied from scratch): `experiments/streaming/investigate/runs/20261112-234336-fixb-spike/` (= RUN below).

## Steps
1. Read spec, gemmini.cc/.h, run-flow-fix.md, spike-meta-rd.md. Installed lib sha256 before: 34578eb7...a592a (RUN/riscv-before.txt).
2. Edits (diff: RUN/libgemmini.diff):
   - gemmini.h:154-155 state `loop_ws_idx_dram`, `loop_ws_nm_cfg_seen`; :182-183 `load_idx`, `loop_ws_config_nm`; :223-224 functs 27, 28.
   - gemmini.cc:865 N2 text in `nm_forbid_loop` (now only LOOP_CONV_WS calls it); :870-874 `nm_loop_abort`;
     :876-899 `load_idx` (funct 27; N11, N12, N13); :901-911 `loop_ws_config_nm` (funct 28; N14, N5);
     :913-920 LOOP_WS rs1[3], N1, N3, N4, cfg_seen cleared; :941-962 sparse sizes and N7, N6, N8, N9, N10;
     :964, :971, :975 B has K/2 tiles and sits below the index region; :1026-1040 index mvins (LOAD_IDX, g = 16/R tiles each) and
     LOAD helper, initial LOAD(min(4, T)); :1042-1047 k loop over K/2, A tile 2k; :1063, :1069-1070 A mvins for tiles 2k and 2k+1;
     :1112 compute rs2 = a_hi; :1114-1116 rolling LOAD(2) after the last compute of a tile when loaded - pre <= 2;
     :1121 mvout at k == K/2 - 1; :1902-1905 dispatch of functs 27, 28.
   - Loop LOADs go through the unchanged Fix A `nm_meta_load_spad`, so its budget / bank aborts and `nm_ld_since_clear` apply.
3. Built out-of-tree with `SCRATCH_DIR=<scratch>/fixb-spike ./run-flow.sh spike-lib nm24|nm48` (logs
   `logs/runs/libgemmini-20261112-233820.log`, `...-233824.log`). sha256: nm24 0d30970a...b640, nm48 9c5894d4...440f (RUN/run.info).
   Baseline libs from `git show HEAD:` sources and a `-DNM_DENSE_BUILD` lib (7617dce5...3745) built by hand in scratch.
4. Tests built with `SCRATCH_DIR=... ./run-flow.sh tests` (78 binaries) plus nm_sparse_spad and its NEG 21-37 for 2:4 and 4:8
   (RUN/regress.sh; the flow does not build them). 114 binaries.
5. Regression (RUN/reg-fixb/summary.txt, logs RUN/reg-fixb/logs/): 112 pass, 2 fail of 114.
   - Dense: 54 of 56 pass. Fail: matmul_spad, mvin_mvout_spad (tohost 1337). Same 2 fail on the baseline lib
     (RUN/reg-base/summary.txt) and are the known pre-existing failures (fix-a-sw.md:70).
   - nm_* positive (sw, debug, matmul, perf, protocol, spad; 2:4 and 4:8): 12 of 12 pass.
   - NEG (protocol 4,6,7,9,10,14; spad 21-37; both patterns): 46 of 46 abort with a GEMMINI message.
   - `diff reg-base/summary.txt reg-fixb/summary.txt` (first run, same binaries): only protocol NEG10 differs: old text
     "LOOP_WS is not supported in sparse mode", new text N1. The spec requires this (2.5.6: N1 replaces it). (The first run's summary
     misfiled conv_with_input_dilation_and_neg_padding as a NEG; classifier fixed, reg-fixb re-run; reg-base keeps the old label, rc=0.)
6. Scratch smoke test of the sparse loop (RUN/smoke/smoke_loop.c, uses the tests agent's uncommitted `tiled_matmul_nm_loop`):
   9 shapes (T = 1, 2, 3, 4, 5, 12, 20; multi-call; partial I/J tiles; no bias, per-row bias, repeating bias) all match the CPU
   reference on 2:4 and 4:8 (RUN/smoke/smoke_loop_24.log, smoke_loop_48.log).
7. Scratch NEG per assert (RUN/smoke/smoke_neg.c, RUN/smoke/neg24.summary, neg48.summary): N1-N10, N12, N13 abort with the 2.5.6
   text on the nm24 lib; N11, N14 on the NM_DENSE_BUILD lib; NEG 0 and 25 (legal) run through.
8. Scratch mutants, each run on smoke_loop_24 (RUN/mutants/*.log): wrong a_hi base, LOAD_IDX stride 32, mvout K not halved: 9 of 9
   cases wrong; index region shifted over B: Fix A bank abort; budget gate removed: Fix A budget abort; nm flag not latched: N1.
9. Installed lib sha256 after: 34578eb7...a592a, identical (RUN/riscv-after.txt).

10. Coordinator ruling on A9: tagged every added line inside the new blocks with `// changed: sparse-loop-fix, <why>` (70 lines,
    comments only, no line added or removed, so the file:line list of step 2 still holds). gemmini.cc sha256 now 8224264c...11a4.
    Rebuilt nm24, nm48, dense24 (logs `logs/runs/libgemmini-20261112-234515.log`, `...-234519.log`): lib sha256 unchanged
    (0d30970a...b640, 9c5894d4...440f, 7617dce5...3745). Re-ran smoke_loop (both patterns), the NEG summaries and the 114-binary
    regression: output identical to the first run (112 pass, same 2 known fails). Evidence: `experiments/streaming/investigate/runs/20261112-234540-fixb-spike-tags/`.
    Installed lib still 34578eb7...a592a (run.info there).

11. Tests agent's binaries (scratch `.../scratchpad/fixb-tests`, hashes in RUN3/run.info) on the step-10 libs.
    RUN3 = `experiments/streaming/investigate/runs/20261112-235246-fixb-spike-tests/`. No libgemmini edit was needed.
    - nm_sparse_loop_24 / _48: pass, 17 of 17 cases each (RUN3/pos/).
    - NEG: 25 builds x 2 patterns = 50 of 50 abort with the run-flow.sh `loop_neg_msg` text (RUN3/neg.summary, RUN3/neg/).
      NEG 110 / 140: abort with the N11 / N14 text on the `-DNM_DENSE_BUILD` libs (dense48 built now, 8eb89b8a...), and run through
      (rc 0, "NOT caught") on the nm libs, where they are legal (RUN3/neg-dense/, RUN3/neg-nmlib/).
    - Mutants (RUN3/mutants.summary, per-mutant logs and mutation.diff in RUN3/mutants/): the 6 from step 8 plus idx rows 8 and
      LOAD_IDX using the id-2 stride, on 2:4 and 4:8: 16 of 16 killed by nm_sparse_loop. One mutant per assert N1-N14 (check
      removed, 2:4): 16 of 16 NEG runs no longer pass (N1 with NEG 10 and 11, N6 with NEG 60 and 61).
    - Benches (RUN3/bench.summary, RUN3/bench/): fair_perf_24, _48, _dense_only print `fair_perf passed`; all 12
      `<layer>_{24,48}_loop` print `sbench passed (2 of 2 runs verified)`. Spike timed-region counts (not cycles) berkeley /
      sparse_loop: edge 402 / 363 (2:4), 378 (4:8); small 468 / 469, 487; bert_qkv 3214 / 1451, 1516; rn50_conv 4833 / 1871, 1893;
      bert_ffn1 12000 / 4404, 4613; bert_ffn2 10057 / 3327, 3460.
    - `./run-flow.sh spike nm24|nm48` end to end: rc 0, 42 pass lines each (RUN3/run-flow-spike-nm24.out, -nm48.out; logs
      `logs/runs/spike-20261112-235226.log`, `-235227.log`, copies in RUN3). Needs a scratch holding the test binaries and the libs
      (`.../fixb-spike/flow`) and a FAIR_BIN with berkeley_dense_perf-baremetal; the tests agent's fair dir lacks that file, I
      copied the one from verification/build (built 2026-11-03).

## Spec ambiguities / notes (reported, not diverged)
- A1. No dense Spike build exists (gemmini.h needs NM_N/NM_M). N11/N14 are compiled in only with `-DNM_DENSE_BUILD` (not a Makefile
  option; Makefile is not my file). That build still models funct 26 and config_ex rs1[10].
- A2. N9 second half (idx_rows > 4096) cannot be reached at DIM 16: it needs more than 4096/R tiles, whose B rows alone exceed the half.
- A3. Spike puts the regions by spad id like its dense loop (A at 0 or 8192, B/index end at 8192 or 16384), not by the RTL's
  alternating loop slot. Invisible to software. N9 uses the sum bound of 2.5.4.
- A4. Sparse loop with `loop_ws_B == 0` (B reuse): Spike still loads the index rows and issues LOADs. Spec does not say.
- A5. N10 is checked at LOOP_WS decode in Spike (RTL: at the first LOAD). Check order when several are violated:
  N1, N3, N4, then N7, N6, N8, N9, N10.
- A6. LOAD_IDX with DRAM address 0 loads zeros (as every mvin). Spec does not say.
- A7. spad-only (N7) is LOOP_WS rs2[9] (RTL LoopMatmul.scala:1097). Spike has no functs 24/25 (illegal instruction, as before).
- A8. I1-I3 are not modelled (spec section 4 item 10).
- A9. CLOSED (step 10): every added line now carries the tag.

## Round 2 (2026-11-13, spec changelog D1, D4)
R2 = `experiments/streaming/investigate/runs/20261113-144754-fixb-r2-spike/` (run.info, SHA256SUMS, smoke/summary.txt).
12. D4 (N13 range check): already in the round 1 code, no edit. gemmini.cc:887 aborts with the N13 text when
    `base_row_addr + rows > BANK_NUM * BANK_ROWS` (16384, gemmini_params.h:10-11). addr = rs2[31:0], rows = raw rs2[63:48], 64-bit sum
    (reg_t), so no wrap; addr + rows == 16384 is legal; accumulator (bit 31) and GARBAGE addresses exceed the bound. Same as the RTL
    rule the coordinator sent (Controller.scala:610-612). gemmini.cc sha256 still 8224264c...11a4 (R2/run.info).
    Check order: N12 (gemmini.cc:885) before N13 (gemmini.cc:887); Spike aborts at the first, so a command breaking both prints
    only the N12 text, while the RTL fires both asserts in one cycle.
    Evidence (R2/smoke/summary.txt): tests agent's NEG 130, 131, 132 abort with the N13 text on 2:4 and 4:8; scratch smoke_neg
    NEG 22 (row 16382 + 4 rows) aborts with N13, NEG 25 (row 16380 + 4 rows, exact fit) runs through (rc 0), both patterns.
13. D1 (Makefile switch): libgemmini/Makefile:13-17 adds `NM_DENSE_BUILD` (unset or 0: n:m lib; anything else: `-DNM_DENSE_BUILD`),
    Makefile:22 passes `$(NM_DENSE_FLAG)` to g++ (R2/Makefile.diff). One `# changed:` comment for the block, like the NM_N block.
    A dense lib still needs NM_N/NM_M (gemmini.h:27) and still models funct 26 and config_ex rs1[10] (note A1).
14. Libs built in scratch `.../scratchpad/fixb-r2/libs/libgemmini-{nm24,nm48,dense24,dense48}/` with the run-flow.sh spike-lib make
    line (R2/build/*.build.log). sha256 (R2/run.info): nm24 0d30970a...b640, nm48 9c5894d4...440f, dense24 7617dce5...3745,
    dense48 8eb89b8a...fef7: identical to the round 1 libs (RUN3/run.info), so the default build is unchanged and the switch gives
    the same lib as the hand `-DNM_DENSE_BUILD` build. `NM_DENSE_BUILD=0` gives the nm24 hash. Installed lib 34578eb7...a592a
    before and after.
15. Smoke (R2/smoke/): nm_sparse_loop_24 and _48 (RUN3 binaries, hashes in R2/run.info) rc 0, `nm_sparse_loop passed`, 17 of 17
    cases ok each. NEG 110 / 140 abort with the N11 / N14 text on the dense24 / dense48 libs.
16. run-flow.sh has no dense spike-lib (pat_nm takes nm24 / nm48 only; t2.sh called g++ by hand). Command for its owner, same line
    as step_spike_lib plus one variable, into its own dir so it never replaces the n:m lib:
    `make -B -f "$lib_dir/Makefile" -C "$out" VPATH="$lib_dir" libgemmini.so NM_N="$n" NM_M="$m" NM_DENSE_BUILD=1`

## RESUME HERE
Done: round 1 (section 4 items 0-10, asserts N1-N14, tagged) and round 2 (D4 confirmed in place, D1 Makefile switch, scratch libs,
smoke; steps 12-16, evidence in R2). Nothing committed. Uncommitted in libgemmini: gemmini.cc, gemmini.h (round 1), Makefile (round 2).
Installed lib untouched (34578eb7...a592a, R2/run.info).
Running: nothing.
Findings: N12 is checked before N13 in Spike (one abort); RTL fires both. No NEG test in gemmini-rocc-tests has a destination that
starts inside the scratchpad and runs past its end (NEG 132 starts at row 16384); only the scratch smoke_neg NEG 22 covers it.
Next: full re-verification by another agent (RUN/regress.sh, RUN3/t2.sh, RUN3/t2-bench.sh with the libs of step 14; t2.sh's hand
g++ dense build can become the step 16 command). run-flow.sh owner adds the dense spike-lib. A1, A2, A4 are with the user; A5-A7
with the RTL agent. Scratch libs are lost with the session; rebuild with step 16 / step 14.
