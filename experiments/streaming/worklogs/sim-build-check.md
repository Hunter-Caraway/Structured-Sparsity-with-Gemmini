# sim-build-check worklog

Task: collect.py and stream_analysis.py detect >1 sim_sha256 per chip. Default exit non-zero (names chip, sha, row count);
`--allow-mixed-sims` continues and the outputs state the mix. Cross-chip / laptop-vs-server comparison stays allowed (rule 4).

## Steps
1. scripts/collect.py: sim_mix(), flag parse, check before results.csv is written, "## WARNING: mixed simulator builds" in summary.md.
2. analysis/stream_analysis.py: same check in load_results(); flag in tables.md and numbers.json (key `mixed_sim_builds`, only when mixed).
3. py_compile both: ok.
4. Tests in scratch .../scratchpad/sbc (copies; recorded runs untouched; analysis run from a scratch repo tree so analysis/out was not touched):
   - collect.py mixed, no flag: rc=1, 6 chip/sha lines. With flag: rc=0, results.csv byte-identical to recorded, summary.md differs only by run-folder line + WARNING block.
   - collect.py single-build (remote/ removed): rc=0, no WARNING.
   - stream_analysis.py mixed no flag: rc=1. With flag: stream_table.csv, area_norm.csv byte-identical; tables.md and numbers.json differ only by run path + disclosure.
   - single-build: rc=0 (numbers differ from recorded only in the hosts column, as expected).

## RESUME HERE
Done: both scripts, all tests. Running: nothing. Not done: deliverables/** copies not updated (frozen); nothing committed.

- 2026-11-12 housekeeping: added build-scratch/ to .gitignore; stripped "changed: sim-build-check" comments (whole trailing comment incl. reason text) from collect.py, stream_analysis.py. py_compile OK.
