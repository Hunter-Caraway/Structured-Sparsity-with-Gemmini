# sweep-a: code-quality sweep, review agent A (2026-11-12)

Scope: files in codefiles-A.txt (verification/*, analysis/*, tools/report-builders/*, run-flow.sh, .gitignore,
fixes-wip/*, experiments/area-nofraig/*), as of commit e06b436. Quota: 0 sims, no server, no rebuilds.
Deleted in HEAD (skipped): analysis/make_charts.py, verification/rerun.sh, run_berkeley.sh, run_fair.sh.

## Log
- step 0: worklog created.
- step 1 (review read-through) done: nmdata, verify_all, compare_runs, cross_check, paper_data, fair_perf.c,
  berkeley_dense_perf.c, analysis/{chart_all_data,split,advanced_visuals,area}.py, area-nofraig/*, fixes-wip/*,
  report-builders (diff + unused imports), run-flow.sh, .gitignore.
- findings so far (to report, not fixed unless listed under edits):
  - chart_all_data.py / advanced_visuals.py chart logs without checking passed/failed (rule 4). split.py checks
    `passed` but not `failed`. -> fix planned (small): shared nmdata helper, exit 1.
  - fixes-wip/numbers.py crashes with current nmdata (fair["nm24_sameprog"], fair[chip]["perf"], load_original gone).
  - experiments/area-nofraig/run_area_nofraig.py: its assert fails against current area.py (synth.ys already has
    -noabc and -script); fails loudly. area_corrected.py header describes an area.py bug that area.py now guards.
  - tools/report-builders/build_paper.py reads verification/paper_data.json + paper_chart.png; paper_data.py now writes
    <run>/derived/. Templates per their README.
  - cross_check.py looks for logs/runs/bench-<cfg>-<test>-<stamp>.log + results/cycles.csv; run-flow.sh bench now
    writes verification/runs/bench-<cfg>-<stamp>/<test>.seed<S>.log + cycles.csv; rerun writes orig-<c>-<t>.seed<S>.log
    but cross_check wants orig-<c>-<t>.log. verify_all section A always SKIPs for new data.
  - run-flow.sh: `set -eo pipefail` (no -u; help text sed keys on '^set -eo'); spike-lib installs into $RISCV/lib,
    tests runs build.sh into gemmini-rocc-tests/build, restore_params_h does git checkout, sim nm24/nm48 rebuild
    with no backup, PAR defaults to nproc (> 12 quota), parallel make in sims/ -- all conflict with AGENTS.md.
  - verify_all/paper_data/figures write <run>/derived/ inside the run folder (rule 2 question).
- step 2 (edits, all verified locally; scratch copies of verification/runs/fair-20261103-151404 only, the
  recorded folder was not touched):
  - verification/nmdata.py:45 new die_unpassed(fair, what): exit 1 if any log lacks 'passed' or has a failure line.
  - verification/paper_data.py:94 uses it (same message as before).
  - analysis/advanced_visuals.py:302-306, analysis/chart_all_data.py:88 now call it (before: charted failed logs, rc 0).
  - analysis/split.py:41 also rejects logs with a failure line (before: only checked 'passed').
  - verification/compare_runs.py:26-38 duplicate (log, seed) now exits 1 (before: later log silently replaced earlier).
  - dead imports/functions removed: build_paper.py Spacer + pct(), build_changes.py Flowable, build_report.py TA_LEFT.
  - checks: py_compile all edited files; bash -n run-flow.sh; paper_data/advanced_visuals/chart_all_data/split
    outputs (stdout, csv, md, json) byte-identical before/after on a scratch copy; NEG: mutated copy (missing
    'passed', added 'mismatch' line) -> all four exit 1, HEAD versions of chart_all_data/advanced_visuals/split
    exit 0 (mutant); duplicate-log NEG for compare_runs: new rc 1, HEAD rc 0. verify_all --skip-patches on the
    scratch copy: ALL CHECKS PASSED (75 checks, 4 skipped).
  - C: no edits; gcc -fsyntax-only not run (headers are in gemmini-rocc-tests, off limits).

## RESUME HERE
- Done: review of all files in codefiles-A.txt; edits above; worklog findings list (step 1) is the report basis.
- Running: nothing.
- Open (need user/coordinator decision, not changed): run-flow.sh policy conflicts (no -u, spike-lib install,
  tests overwrite build/, git checkout in restore_params_h, sim rebuild w/o backup, PAR default nproc, parallel make
  in sims/); cross_check.py out of sync with run-flow bench/rerun layout; <run>/derived/ written inside run folders;
  numbers.py / run_area_nofraig.py / build_paper.py stale; advanced_visuals.py imports numpy (stdlib+matplotlib rule).
