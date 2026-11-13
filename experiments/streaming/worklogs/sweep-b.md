# sweep-b: code-quality sweep, agent B (2026-11-12)

Scope: code files in commit e06b436 under experiments/streaming/{investigate,tools,src,gen,scripts,deliverables,analysis}/,
excluding runs/. List: scratchpad codefiles-B.txt. No server, no sims, no Berkeley code.

## Steps
1. Duplicate check: analysis/*.{py,sh} identical to deliverables/.../scripts/*; investigate/scripts/{collect.py,run_rtl.sh,
   spike_lib.sh,spike_run.sh} identical to scripts/. Deliverable folder has SHA256SUMS: treat as frozen, do not edit.
2. Read all assigned scripts, Python and C (investigate/build/*.out, *.dis, stamp files are runner logs/outputs, not code: skipped).
   Baseline: tools/parse_fixa.py on investigate/runs/20261111-183018-fixa-srv -> rc 0, "tests: 56 PASS, 0 FAIL"
   (saved to scratchpad parse_before.out for the before/after diff).
3. Planned edits (small, safe): build.sh die msg; build_one.sh stale-binary; run_bins.sh provenance hash;
   parse_fixa.py dead var + exit code + verified-only ranges; collect.py redundant cfg_ok clause + sparse_fixa parsing.
4. Coordinator message (sweep C findings on parse_fixa.py): do (1) non-zero exit on FAIL, (2) jobs row with no log = FAIL,
   (3) rc '?' must not pass NEG, (5) dead `layer`; (4) verified-only ranges = report only (not changed).
5. Edits done (all verified):
   - tools/parse_fixa.py:90-91 NEG ok needs rc not in ('0','?'); :113 dead `layer` removed; :146-154 MISSING LOG
     lines + sys.exit non-zero on any FAIL/not-ok/missing log or zero logs judged (message to stderr).
     Recorded run investigate/runs/20261111-183018-fixa-srv: stdout byte-identical to before, rc 0. Scratch copies:
     log removed -> "MISSING LOG", exit 1; jobs row of spad_neg21 removed -> "tests: 55 PASS, 1 FAIL", exit 1;
     no logs -> exit 1.
   - scripts/collect.py:32-36 TOT/CHK/MASK_VARIANTS parse sparse_fixa (bit 8 of src/stream_bench.c), was silently
     dropped; :79 redundant first clause of cfg_ok removed (subset of the second); :163 summary lists sparse_fixa.
     Scratch copies of runs/20261109-140015 and -144252: results.csv and summary.md byte-identical to HEAD's
     collect.py output and to the recorded files; regexes match real sparse_fixa lines of the fixa-srv logs.
   - scripts/build.sh:58 die message also prints the _24_ds hash ($t).
   - investigate/scripts/build_one.sh:18 rm -f "$out" before gcc (gcc status is masked by `| grep -v RWX || true`,
     so a failed compile passed `[ -s "$out" ]` on a stale binary).
   - investigate/scripts/run_bins.sh:36-37 run.info hashes $run/bin/$name (the file simulated; cp -n keeps an older
     file of the same name, so hashing "$b" could record a binary that never ran).
   - bash -n and py_compile pass. No C edited (gcc -fsyntax-only needs Berkeley headers: not run).
   - Not edited: deliverables/.../scripts (frozen, in SHA256SUMS); analysis/* (identical to the deliverable copies).

## Findings (reported, not changed)
- HIGH rule 4: runs/20261109-144252/results.csv mixes simulator builds per chip (laptop "fortnite" vs AI-1769, different
  sim_sha256 for stock, nm24, nm48). stream_analysis.py compares across them: bert_ffn1/ffn2 nm48 sparse_stream (server)
  vs stock berkeley/dense_stream (laptop). Neither collect.py nor stream_analysis.py checks one sim_sha256 per chip.
- Open question rule 4: every "vs Berkeley" ratio compares stock-chip cycles with nm24/nm48-chip cycles (different builds
  by design). Need the user's reading of "same build".
- MED rule 1: analysis/build_stream_paper.py hard-codes 37% / 42% / 8% (investigation), contradicting "No number was typed
  by hand"; deliverable PDF carries them.
- MED parse_fixa.py:125-145 fair/stream ranges include not-ok rows (unchanged on the recorded run; report only).
- MED investigate/src/micro*.c: outputs not verified ("values are junk"); their cycle counts are unverified (rule 4).
- MED verification is against the host (numpy) reference, not a CPU reference as AGENTS.md says (stream_bench.c).
- MED stdlib+matplotlib rule: gen/gen_data.py uses numpy; build_stream_paper.py uses reportlab + PIL; stream_analysis.py
  imports verification/nmdata.py.
- LOW investigate/scripts/run_rtl.sh, collect.py, spike_*.sh are copies of scripts/; here=investigate/, so run_rtl.sh
  provenance reads investigate/scripts/build.sh and investigate/gen/gen_data.py (missing) and hashes investigate/src/stream_bench.c.
- LOW bash: run_rtl.sh, run_bins.sh, spike_all.sh, spike_run.sh lack -e/-u; build.sh, build_one.sh, spike_lib.sh lack -u.
  -e would break the `cmd; rc=$?` pattern; -u around `source env.sh` untested. No STATUS file in run_rtl/run_bins
  (fix-a-server.md: written by the wrapper). PAR / PAR file have no cap at 12.
- LOW collect.py writes results.csv/summary.md into the run dir after run_rtl.sh wrote SHA256SUMS: SHA256SUMS goes stale
  unless redone by hand (bench.md 11 did it by hand).
- LOW run_bins.sh does not validate tmo/sims/binaries up front (run_rtl.sh does); spike_all.sh starts every program at once.
- LOW investigate/src/stream_bench.c: PRETOUCH_META/TI_SET/CTRSET2 builds print the same header line as fair builds.
- Style: parse_fixa.py, stream_analysis.py, build_stream_paper.py not PEP 8 (multi-imports, one-line ifs, lambdas).
- Dead but left: stream_analysis.py:268-272 the `fmt` element of the s3 panel tuples (in the frozen deliverable copy too).

## RESUME HERE
Done: sweep complete, edits above, outputs verified unchanged on recorded runs. Running: nothing. Next: coordinator/user
decide on the HIGH cross-build finding and the open questions; nothing committed.
