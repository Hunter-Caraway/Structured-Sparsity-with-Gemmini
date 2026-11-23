# rot180-rerun

Goal: rerun Berkeley dense test `conv_with_input_dilation_and_rot180` on the STOCK chip (seed 1) with a higher cap.
Previous: timed out at 300M on both chips inside "CPU conv..." (no "CPU conv took"):
`investigate/runs/20261117-111223-convbudget-stock-srv/stock.conv_with_input_dilation_and_rot180.seed1.log`,
`investigate/runs/20261117-110726-convbudget-srv`. Only test missing from the 54-test dense list on stock.

## Launch (2026-11-23 14:33 EST)
- Server run folder: `~/sinv/runs/20261123-143334-rot180-stock-srv` (run.info, jobs.tsv, build.info, driver.sh, jobs-in.txt)
- Launcher: `~/fixb/run_jobs.sh` via `driver.sh` (PAR=1), same as convbudget-stock run; `nohup setsid`. STATUS written at end.
- Simulator: `simulator-chipyard.harness-GemminiRocketConfig` sha256 `84c2264a...b75e4` (run.info `sim.stock`, unchanged, not rebuilt).
- Binary: sha256 `c9db16e4...c65b0`, identical to convbudget-stock `bin/` and `src/` copies (checked on server, sha matched).
- Sim PID 886498 (+ bash wrappers 886496/886497), `+max-cycles=2000000000`, `+verilator+seed+1`. Alive after 75 s at 100% CPU; log shows
  "Input dimensions: 17 by 17 / Randomize inputs..." (program output is buffered, log grows slowly).
- No nm24/nm48 simulator used.

## Cap choice: 2,000,000,000
- Source (`bareMetalC/conv_with_input_dilation_and_rot180.c`): non-FAST dims batch 2, 17x17 in (33x33 dilated), 18 in-ch, 19 out-ch, 3x3, so
  inner CPU-conv iterations = 2*33*33*19*9*18 = 6.70M [E, from source].
- Sibling CPU conv: dilation 103,792,927 cycles, neg_padding 82,741,500 cycles (convbudget stock logs) = 15.5 and 12.4 cycles/iter [E].
- rot180 differs from `conv_with_input_dilation.c` only by an extra weights_rot180 copy pass and a per-iteration ternary; yet it passed 300M (>= 44.8 cycles/iter [E]).
  True cost unknown, so no tight estimate; 2B gives >= 6.7x headroom over the known lower bound. Gemmini part is ~0.1M (siblings: 107,704 / 70,300 cycles).

## Speed and ETA [E]
- From convbudget stock jobs.tsv (3 jobs in parallel): rot180 300M in 207,123 s = ~1,450 cyc/s; dilation ~104M+ in 137,094 s = ~760 cyc/s;
  neg_padding ~83M+ in 105,014 s = ~790 cyc/s (cycles = CPU-conv cycles + small boot; so approximate).
- Box was idle at launch (load 0.01), PAR=1, so speed may be at the high end.
- If it needs 300-600M cycles: ~2.4-8 days. Absolute worst (hit 2B cap): ~16-30 days. Do not kill for time.

## RESUME HERE
Running: `~/sinv/runs/20261123-143334-rot180-stock-srv`, sim PID 886498. Done when `STATUS` contains `ALL_DONE` and `SHA256SUMS` exists.
Next:
1. Check: `ssh ... 'cat <run>/STATUS; tail <run>/stock.*.log; cat <run>/jobs.tsv'`.
2. Copy back to `experiments/streaming/investigate/runs/20261123-143334-rot180-stock-srv/`: `ssh ... cat` each file (bin/, src/, logs, run.info, jobs.tsv, build.info, driver.sh, jobs-*.txt, run.out, STATUS, SHA256SUMS).
3. `sha256sum -c SHA256SUMS` in the copied folder.
4. `verification/verify_all.py --mode run` on the folder.
5. Pass only if log ends with `Verilog $finish`, has no `FAILED`, and the test output check says verified. Record "CPU conv took" and "Gemmini conv took" cycles.
6. If it hits the 2B cap (FAILED timeout), record that; do not rerun without a new decision.
README table / paper numbers: change only with user approval.
