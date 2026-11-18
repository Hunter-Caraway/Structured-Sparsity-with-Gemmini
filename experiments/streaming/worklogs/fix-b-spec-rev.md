# fix-b-spec-rev worklog (spec agent, 2026-11-12)

Task: revise fix-b-spec.md for user decisions Q1 (bias needed, new route), Q2 (K % 2*DIM == 0), Q3 (yes, other agent measures,
placeholder in 5.1 -> worklogs/fixb-q3-spike.md), Q4 (Fix B), Q5 (no faster-than-Berkeley claim needed). Read-only on source.

## Steps
1. Read AGENTS.md, fix-b-spec.md, fix-a-spec.md. DONE
2. Read Berkeley code: GemminiISA.scala (functs 0-26, 126 used; 27, 28 free), LoopMatmul.scala (LdD uses LOAD3_CMD id 2,
   arb = Arbiter(5), config decode, rs1[3] free), LoadController.scala (per-id stride/scale/block_stride regs, load_states = 3),
   ReservationStation.scala (LOAD3 at 277/296/323). DONE
   Finding: all three mvin ids (A=0, B=1, D=2) are configured by config_ld before a loop (gemmini.h:760-762), so index rows
   cannot use any of them with a 16 B stride. Chosen: new funct 27 LOAD_IDX_CMD with hardwired constants (no config state).
3. Wrote revised spec. IN PROGRESS
3. Revised fix-b-spec.md: 2.5 (ISA, load path, spad, asserts N1-N14 / I1-I3), H11-H14, Spike 7-10, 5.1 Q3 placeholder, 6.1/6.3/6.4, section 8 (Q1-Q5 decided, "Ready to freeze?"), changelog. DONE
   No source edited, nothing built/run.

## RESUME HERE
Done: all of the above. Open: C1, C2, C6 (RTL reads), user answers R1-R3 (see spec section 8). Q3 numbers pending from coordinator (worklogs/fixb-q3-spike.md).
Next: user answers R1-R3, then freeze line 1 and spawn RTL/Spike/software agents.

## Freeze step (2026-11-12)
R1-R3 ticked with answers; Q3 numbers verified against R/rt/logs/*.log:4 and trace.txt:4 and filled in 5.1; line 1 = FROZEN; changelog entry added. Spec only.
## RESUME HERE
Spec FROZEN. Next: RTL/Spike/software agents from 2.5, 3, 4, 6; C1, C2, C6 first.
