# dense-spad-check
Question: are matmul_spad / mvin_mvout_spad failing on Spike Berkeley pre-existing or our regression?
Run: experiments/streaming/investigate/runs/20261113-143811-dense-spad-stock (logs, run.info, SHA256SUMS). Scratch: /tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/stock-spad

## Steps (done)
1. Extracted libgemmini ea8f7ed and gemmini-rocc-tests 7c540b3 (+3 nested submodules) via git archive; built stock lib; built our nm24 lib and tests via run-flow.
2. Built both spad tests from stock source with stock dense params (sha256 3758ae967af3a179497660970201093a7fb624be00173990ce33d3f5c38da924).
3. 2x2 matrix, both tests, all 4 cells: FAIL, tohost=1337, exit 57 (logs/*.log). Sanity: stock lib + stock mvin_mvout PASS (logs/sanity.*).
4. Cause: neither lib handles funct 23 (k_MVOUT_SPAD, tests include/gemmini.h:60); stock gemmini.cc:1639 falls to "unknown instruction". Berkeley bareMetalC/Makefile:70-71 excludes both tests from runs ("normal configs dont have ext spad").

## RESUME HERE
Done. Verdict: Berkeley pre-existing. Nothing running. run-flow also wrote untracked logs/runs/libgemmini-*.log in repo.
