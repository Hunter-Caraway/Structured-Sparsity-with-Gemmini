# Verification report

Run 2026-11-09 13:36 with `verification/verify_all.py` on `fair-20261103-151404`. **ALL CHECKS PASSED** (75 checks, 4 skipped).

## A. Original benchmark pipeline

- SKIP: no results: no bench logs (bench-<cfg>-<test>-<stamp>.log) in /home/hunter/gemmini-sparsity/logs/runs; run ./run-flow.sh bench nm24|nm48

## B. Independent math check

- PASS: sparse math equals dense math in every random case (2:4 and 4:8): 2/2 patterns
- PASS: every injected hardware fault detected: 8/8 fault types
- PASS: output identical to verification/independent_math_check.out

## C. Pattern comparison

- PASS: pattern_fidelity.py reproduces pattern_fidelity.out exactly
- PASS: bell curve: energy kept ranks paired 4:8 <= 2:4 <= 4:8 <= no pattern (79.2% <= 86.8% <= 89.7% <= 92.9%)
- PASS: heavy tail: energy kept ranks paired 4:8 <= 2:4 <= 4:8 <= no pattern (86.1% <= 92.1% <= 94.4% <= 96.7%)

## D. Fair benchmark

- PASS: every chip ran the same seeds: berkeley=1,2,3; sameprog=1,2,3; nm24=1,2,3; nm48=1,2,3
- PASS: our chip ran Berkeley's exact program with sparsity off (sameprog log present)
- PASS: berkeley seed 1: printed 'passed' and no failure line
- PASS: berkeley seed 1: log from the current fair_perf.c (dense-only build, warm-up, poison reaches the accumulator, prep lines)
- PASS: berkeley seed 1: every gemmini variant matched the cpu reference (2 results, 2,048 values each)
- PASS: berkeley seed 1: program built for 2:4 (expected 2:4)
- PASS: berkeley seed 1: pair counts equal the count computed from i=64 k=128 j=32 and 2:4
- PASS: berkeley seed 2: printed 'passed' and no failure line
- PASS: berkeley seed 2: log from the current fair_perf.c (dense-only build, warm-up, poison reaches the accumulator, prep lines)
- PASS: berkeley seed 2: every gemmini variant matched the cpu reference (2 results, 2,048 values each)
- PASS: berkeley seed 2: program built for 2:4 (expected 2:4)
- PASS: berkeley seed 2: pair counts equal the count computed from i=64 k=128 j=32 and 2:4
- PASS: berkeley seed 3: printed 'passed' and no failure line
- PASS: berkeley seed 3: log from the current fair_perf.c (dense-only build, warm-up, poison reaches the accumulator, prep lines)
- PASS: berkeley seed 3: every gemmini variant matched the cpu reference (2 results, 2,048 values each)
- PASS: berkeley seed 3: program built for 2:4 (expected 2:4)
- PASS: berkeley seed 3: pair counts equal the count computed from i=64 k=128 j=32 and 2:4
- PASS: sameprog seed 1: printed 'passed' and no failure line
- PASS: sameprog seed 1: log from the current fair_perf.c (dense-only build, warm-up, poison reaches the accumulator, prep lines)
- PASS: sameprog seed 1: every gemmini variant matched the cpu reference (2 results, 2,048 values each)
- PASS: sameprog seed 1: program built for 2:4 (expected 2:4)
- PASS: sameprog seed 1: pair counts equal the count computed from i=64 k=128 j=32 and 2:4
- PASS: sameprog seed 2: printed 'passed' and no failure line
- PASS: sameprog seed 2: log from the current fair_perf.c (dense-only build, warm-up, poison reaches the accumulator, prep lines)
- PASS: sameprog seed 2: every gemmini variant matched the cpu reference (2 results, 2,048 values each)
- PASS: sameprog seed 2: program built for 2:4 (expected 2:4)
- PASS: sameprog seed 2: pair counts equal the count computed from i=64 k=128 j=32 and 2:4
- PASS: sameprog seed 3: printed 'passed' and no failure line
- PASS: sameprog seed 3: log from the current fair_perf.c (dense-only build, warm-up, poison reaches the accumulator, prep lines)
- PASS: sameprog seed 3: every gemmini variant matched the cpu reference (2 results, 2,048 values each)
- PASS: sameprog seed 3: program built for 2:4 (expected 2:4)
- PASS: sameprog seed 3: pair counts equal the count computed from i=64 k=128 j=32 and 2:4
- PASS: nm24 seed 1: printed 'passed' and no failure line
- PASS: nm24 seed 1: log from the current fair_perf.c (full build, warm-up, poison reaches the accumulator, prep lines)
- PASS: nm24 seed 1: every gemmini variant matched the cpu reference (5 results, 2,048 values each)
- PASS: nm24 seed 1: program built for 2:4 (expected 2:4)
- PASS: nm24 seed 1: pair counts equal the count computed from i=64 k=128 j=32 and 2:4
- PASS: nm24 seed 2: printed 'passed' and no failure line
- PASS: nm24 seed 2: log from the current fair_perf.c (full build, warm-up, poison reaches the accumulator, prep lines)
- PASS: nm24 seed 2: every gemmini variant matched the cpu reference (5 results, 2,048 values each)
- PASS: nm24 seed 2: program built for 2:4 (expected 2:4)
- PASS: nm24 seed 2: pair counts equal the count computed from i=64 k=128 j=32 and 2:4
- PASS: nm24 seed 3: printed 'passed' and no failure line
- PASS: nm24 seed 3: log from the current fair_perf.c (full build, warm-up, poison reaches the accumulator, prep lines)
- PASS: nm24 seed 3: every gemmini variant matched the cpu reference (5 results, 2,048 values each)
- PASS: nm24 seed 3: program built for 2:4 (expected 2:4)
- PASS: nm24 seed 3: pair counts equal the count computed from i=64 k=128 j=32 and 2:4
- PASS: nm48 seed 1: printed 'passed' and no failure line
- PASS: nm48 seed 1: log from the current fair_perf.c (full build, warm-up, poison reaches the accumulator, prep lines)
- PASS: nm48 seed 1: every gemmini variant matched the cpu reference (5 results, 2,048 values each)
- PASS: nm48 seed 1: program built for 4:8 (expected 4:8)
- PASS: nm48 seed 1: pair counts equal the count computed from i=64 k=128 j=32 and 4:8
- PASS: nm48 seed 2: printed 'passed' and no failure line
- PASS: nm48 seed 2: log from the current fair_perf.c (full build, warm-up, poison reaches the accumulator, prep lines)
- PASS: nm48 seed 2: every gemmini variant matched the cpu reference (5 results, 2,048 values each)
- PASS: nm48 seed 2: program built for 4:8 (expected 4:8)
- PASS: nm48 seed 2: pair counts equal the count computed from i=64 k=128 j=32 and 4:8
- PASS: nm48 seed 3: printed 'passed' and no failure line
- PASS: nm48 seed 3: log from the current fair_perf.c (full build, warm-up, poison reaches the accumulator, prep lines)
- PASS: nm48 seed 3: every gemmini variant matched the cpu reference (5 results, 2,048 values each)
- PASS: nm48 seed 3: program built for 4:8 (expected 4:8)
- PASS: nm48 seed 3: pair counts equal the count computed from i=64 k=128 j=32 and 4:8
- PASS: 2:4: array time with reused weights is 0.533-0.533 of the same chip's dense time (ideal 0.500 +-10%): 1,260 -> 672
- PASS: 4:8: array time with reused weights is 0.538-0.538 of the same chip's dense time (ideal 0.500 +-10%): 1,248 -> 672
- PASS: our chip, sparsity off, Berkeley's program: busy_reuse 1,260 vs Berkeley 1,260, worst seed pair 0.00% apart (limit 1%)
- PASS: our chip, sparsity off, Berkeley's program: busy_fresh 1,320 vs Berkeley 1,320, worst seed pair 0.00% apart (limit 1%)
- PASS: our chip, sparsity off, Berkeley's program: reuse 1,541 vs Berkeley 1,541, worst seed pair 0.00% apart (limit 1%)
- PASS: our chip, sparsity off, Berkeley's program: fresh 1,555 vs Berkeley 1,555, worst seed pair 0.00% apart (limit 1%)

## E. Paper summary PDF

- SKIP: N-M-Sparsity-Paper-Summary.pdf not found (rebuild with tools/report-builders/build_paper.py)

## G. File integrity

- PASS: fair-20261103-151404: all 16 files match SHA256SUMS
- SKIP: no verification/MANIFEST.sha256 for the static files (bin/, logs/, *.c, *.out); --write-manifest records one

## H. README results table

- SKIP: README.md has no <!-- results:begin --> ... <!-- results:end --> block, so it states no results to check
