# rot180-diag

Goal: decide from laptop evidence whether Berkeley dense test `conv_with_input_dilation_and_rot180` (a) needs N more
cycles, (b) hangs, or (c) slows for another reason. Diagnose only; no fixes. Server quota 0; do not touch the running
server sim (`~/sinv/runs/20261123-143334-rot180-stock-srv`). Scratch (gitignored, on disk):
`experiments/streaming/build-scratch/rot180-diag/` (= S). Abbreviations: CB = `investigate/runs/20261117-111223-convbudget-stock-srv`,
CB24 = `investigate/runs/20261117-110726-convbudget-srv`, FB = `investigate/runs/20261113-160015-fixb-srv`.

## Verdict: (a). It needs more cycles; it does not hang
The 300M cap counts TestDriver clock ticks at 1 GHz. The core runs at 500 MHz. So 300M sim cycles = 150M core cycles,
not 300M. rot180's CPU reference needs about 194M core cycles [E] = about 390M sim cycles [E].

## Step 1: inputs
- CB rot180 binary sha256 `c9db16e4...ac65b0` (bin/ = src/; same sha as the running rerun per rot180-rerun.md).
  dilation `9f0f8b22...`, neg_padding `1905f4fe...`.
- CB rot180 log ends `*** FAILED *** (timeout) after 300000001 simulation cycles` after "CPU conv..."
  (CB/stock.conv_with_input_dilation_and_rot180.seed1.log). Siblings: CPU conv 103,792,927 and 82,741,500 core cycles
  (CB/stock.conv_with_input_dilation.seed1.log, CB/stock.conv_with_input_dilation_and_neg_padding.seed1.log).

## Step 2: source diff (gemmini-rocc-tests bareMetalC, no diff from Berkeley base 7c540b3 for these 3 files)
- Same non-FAST dims (batch 2, 17x17 in, 33x33 dilated, 18 in-ch, 19 out-ch, 3x3). rot180 adds a weights_rot180
  copy pass (3,078 elements) and `w = wrot180 ? weights_rot180[...] : weights[...]` in the inner loop.
- Inner iterations: 2*33*33*19*9*18 = 6,703,884 (dilation, rot180); neg_padding 2*29*29*19*9*18 = 5,177,196.

## Step 3: disassembly (S/dis/*.conv.s, riscv64-unknown-elf-objdump -d of the CB bin/ files)
- dilation and neg_padding: gcc moves the bounds check out of the kch loop. Inner loop = 9 instructions
  (3 add, 2 lb, addi, mulw, addw, bne).
- rot180: the bounds check and the `wrot180` test stay in the kch loop. An in-bounds iteration runs 18 instructions with
  4 taken jumps (bnez -> 0x80002512, j -> 0x80002404, beqz s6 not taken, j -> 0x80002410, bne back).
- One `divu` per binary, in the prologue of conv (runs once). No div/rem in the loops. No RoCC, CSR or fence in conv.

## Step 4: Spike, same binaries (stock libgemmini ea8f7ed built in S/lib-stock, sha256 06c85602...daad1, `--extlib`)
Installed `$RISCV/lib/libgemmini.so` sha unchanged (34578eb7...). Spike rdcycle = instret.
| test | CPU conv instret | instr/iter | exit | log |
|---|---|---|---|---|
| dilation | 66,378,922 | 9.90 | rc=0 | S/logs/conv_with_input_dilation.spike.log |
| neg_padding | 52,787,899 | 10.20 | rc=0 | S/logs/conv_with_input_dilation_and_neg_padding.spike.log |
| rot180 | 124,071,345 | 18.51 | rc=0 | S/logs/conv_with_input_dilation_and_rot180.spike.log |
- rot180 finishes, and its output check passes: rc=0, and the test returns 1 on a mismatch. So it does not hang functionally. 1.87x the instructions of dilation.
- Instructions before the CPU-conv rdcycle (0x8000301e, just before `jal conv`): 195,032 for both (S/logs/pre-conv-instret.txt).

## Step 5: cache model (Spike `--ic=64:8:64 --dc=64:8:64` = Rocket huge core: 32 KiB 8-way 64 B lines, from
rocket-chip Configs.scala WithNHugeCores and the stock dts)
- D$ read misses / write misses: rot180 2,453 / 2,675; dilation 2,357 / 2,638; neg_padding 1,876 / 2,262. D$ read
  accesses rot180 14,097,771 vs dilation 14,142,980. I$ misses 102-106. (S/logs/*.spike-cache.log)
- So the cause is not cache thrash: same loads, same misses.

## Step 6: clock ratio (the main finding)
- Stock harness (laptop generated-src of GemminiRocketConfig, TestHarness.sv:282-294): ClockSourceAtFreqMHz PERIOD 2.0
  (500 MHz) drives ChipTop `clock_uncore`, the only functional clock into DigitalTop. PERIOD 10.0 (100 MHz) drives
  the harness binders. TestDriver `clock` uses `CLOCK_PERIOD ?= 1.0` (sims/common-sim-flags.mk:29), and `+max-cycles`
  counts that clock (TestDriver.v:128,137). So 1 core cycle = 2 sim cycles. Tile is excluded from the "uncore" group name
  (AbstractConfig.scala:140-142), but DigitalTop has no other clock input.
- Check on recorded runs: at a 150M sim cap, nm24 and nm48 dilation and neg_padding also timed out
  (FB/nm24.conv_with_input_dilation_and_neg_padding.seed1.log etc., "after 150000001 simulation cycles"). neg_padding
  needs only 82.7M core cycles, so a 1:1 ratio is ruled out. A 2:1 ratio explains it: 165.5M sim cycles are needed.
- Speeds in CB jobs.tsv (3 jobs in parallel) at 2:1 agree: dilation 2*103.79M/137,094 s = 1,514 sim cyc/s,
  neg_padding 1,576, rot180 300M/207,123 = 1,448. At 1:1 (rot180-rerun.md) they disagreed (757, 788 vs 1,448).

## Step 7: Berkeley CI
- `.github/scripts/run-tests-rtl.sh` builds with `CFLAGS=-DFAST`. Under FAST, `conv()` is compiled out (`#ifndef FAST`)
  and the dims shrink to 9x9, 5->7 ch. So Berkeley never runs this CPU reference on RTL. Only Spike CI
  (`run-tests-spike.sh`, no FAST) runs it, and it passes there. bareMetalC/Makefile does not exclude it (lines 29-31,
  65-71). This is not a Berkeley bug. Side note: `conv_with_input_dilation.c` has an unreachable nested `#ifdef FAST`
  (17x23 dims); cosmetic only.

## Estimate [E]
- rot180 CPU conv = 124,071,345 instr x sibling RTL CPI (103,792,927/66,378,922 = 1.564; 82,741,500/52,787,899 = 1.567)
  = ~194M core cycles [E]. The mix differs (more ALU ops and taken jumps, the same loads and muls), so CPI is uncertain.
  Range [E]: CPI 1.21 (lower bound: 300M sim = 150M core already passed) to ~2.5 -> 150-310M core cycles.
- Rest of program: ~0.2M instr before, Gemmini conv ~0.1M core cycles (siblings 107,704), plus the check: <~1M core cycles [E].
- Total sim cycles = 2 x core: central ~390M [E], range 300-620M [E]. At ~1,450 sim cyc/s: central ~3.1 days
  (~Nov 26 evening; launch 2026-11-23 14:33), upper ~5.0 days (~Nov 28).
- 2B cap = 1B core cycles = CPI 8.1 for this loop: >4x headroom over the central estimate. Worst case if it never ended:
  2B/1,450 = 16.0 days (Dec 9); at 760 sim cyc/s (loaded box) 30.5 days.

## Recommendation
Keep the running 2B job. Do not relaunch. The cap matters only for a hang, and Spike shows a verified finish.
If no `$finish` by ~800M sim cycles (~6.4 days, ~Nov 30), the estimate is wrong: investigate then, but do not kill.
Fix the ETA in rot180-rerun.md (it assumed 1:1). Future caps: sim cap >= 2 x expected core cycles + margin.
Record in berkeley-issues.md as a note, not a bug: the test is long on RTL because Berkeley's RTL CI uses -DFAST.

## RESUME HERE
Done: all steps above. Nothing running (laptop Spike only; server untouched).
Open: the coordinator decides on the rot180-rerun.md ETA fix and the berkeley-issues.md note. Then check the rerun at about
Nov 26-28 using rot180-rerun.md RESUME steps. When it finishes, compare its CPU conv cycles with the ~194M estimate.
