# Worklog: code-quality sweep C (review agent C, 2026-11-12)

Scope: code files of commit e06b436 under experiments/streaming/{fixa-srv-scratch,analytics-check,speedup-scratch,
densegap-scratch}/ (list: coordinator scratch `codefiles-C.txt`). Code files reviewed: fixa-srv-scratch/{parse.py,
table.py,list.sh,spike_check.sh,watch.sh}, speedup-scratch/{cc.sh,itrace.py}, analytics-check/recollect-20261109-144252/
remote/run.sh, densegap-scratch/src-snap/*.{c,h}. The rest of the list is data (.out/.list/.sha256/.itrace/.dis) or the
generated gemmini_params.h (not read). No server, no sims, no git operations.

## Step 1: which scripts produced records (done)
- parse.py: fix-a-server.md:168 (parse.out), anomalies.md section 6. table.py: fix-a-server.md:171 (table.out, the
  table at fix-a-server.md "Streaming"). list.sh: fix-a-server.md:40,49. spike_check.sh: fix-a-server.md:97.
  cc.sh, itrace.py: speedup.md:15-20 (logs/*.itrace). run.sh: byte-identical copy of runs/20261109-144252/remote/run.sh
  (recorded run). src-snap: dense-gap.md:6 (frozen source copy).
- watch.sh: monitor only, no number traced to it.
- Decision: all record-tied scripts are report-only. watch.sh has no provably dead code. So no file was edited.

## Step 2: review findings (done)
- parse.py (sha256 000ad782...) is the anomalies-agent rewrite, identical to tools/parse_fixa.py. parse.out was made by
  the older parser (sha256 a174f909..., anomalies.md:19). That original exists only in the old session scratchpad
  `/tmp/claude-1000/-home-hunter-gemmini-sparsity/02a1660a-afd8-4d63-b078-262a0414bff5/scratchpad/anom/parse.py.orig`
  (also anom/parse_fixa.out, anom/parse-mut/ cited by anomalies.md:30-31); not in the repo.
- parse.py: exit 0 even with FAIL rows; jobs.tsv rows with no log skipped silently; a missing jobs.tsv row gives
  rc '?' which passes the NEG `rc != '0'` test; fair/stream "ranges" include rows that are not ok (unverified totals);
  `layer` (line 113) unused.
- table.py: reads `total` lines with no check of `-> verified` / `sbench passed`; hard-coded comparison numbers;
  cross-build ratios (rule 4): v1 "FixA vs dense" uses dense from pre-Fix-A sims (runs/20261109-144252), "FixA vs
  Berkeley" uses the stock build, "push vs recorded" uses keeper3 / v1 builds.
- cc.sh: S points to the old session scratchpad (hdr now at speedup-scratch/hdr); `| grep -v RWX || true` hides a gcc
  failure and `[ -s "$o" ]` then passes on a stale binary; `set -eo` without -u.
- itrace.py: an unclosed region at EOF is dropped silently; no regions -> prints nothing, exit 0; subprocess calls
  without check (missing objdump -> misleading assert).
- list.sh, spike_check.sh, watch.sh, run.sh: no `set -euo pipefail`. run.sh runs 5 `make run-binary-fast` in
  sims/verilator at once (BREAK_SIM_PREREQ=1, so no rebuild), writes ALL_DONE regardless of exit codes, unknown chip
  -> empty CONFIG. watch.sh: hard-coded run path and job total 98; a half-written jobs.tsv line is counted once.
- micro2.c:1, micro3.c:1: literal `\n` inside the first comment line (sed artefact). micro*.c do not verify output
  (junk operands, timing only, by design).

## Step 3: duplicates (done)
- fixa-srv-scratch/parse.py == tools/parse_fixa.py.
- analytics-check/recollect-20261109-144252/ == runs/20261109-144252/ except summary.md (incl. remote/run.sh).
- densegap-scratch/src-snap/* == investigate/src/* (all 6 files byte-identical today).
- speedup-scratch/hdr/{24,48}/include/gemmini_params.h == investigate/runs/20261111-183018-fixa-srv/hdr/{24,48}/.

## RESUME HERE
- Done: steps 1-3. No file edited (all code is tied to records, or has no provably dead code).
- Running: nothing.
- Next (coordinator): decide whether to copy anom/parse.py.orig (+ parse_fixa.out, parse-mut/) from the old scratchpad
  into the repo before /tmp is cleared; decide on the rule-4 cross-build ratios in fix-a-server.md.
