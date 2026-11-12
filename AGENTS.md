# AGENTS.md: rules for AI agents on the Gemmini N:M sparsity project

## Project
Adds 2:4 and 4:8 structured sparsity to UC Berkeley's Gemmini (Chipyard 1.14.0, `1.14.0-36-gbfa5699f`) and
measures it in Verilator against Berkeley's unmodified ("stock") chip. Output: a research paper due Mon 15 Dec 2026.
Accuracy of results is the top priority.

| Repo | Path | Branch | Berkeley base |
|---|---|---|---|
| This repo (benchmarks, scripts, docs, results) | `~/gemmini-sparsity` | `main` (work on branches) | - |
| Gemmini RTL fork | `~/chipyard/generators/gemmini` | `sparse-nm` | `8c3f9923` |
| Spike model | `.../gemmini/software/libgemmini` | `sparse-nm` | `ea8f7ed` |
| Tests and helpers (`gemmini_nm.h`) | `.../gemmini/software/gemmini-rocc-tests` | `sparse-nm` | `7c540b3` |

Key paths: worklogs and specs `experiments/streaming/worklogs/`; recorded runs `experiments/streaming/investigate/runs/`
and `experiments/streaming/runs/`; tools `experiments/streaming/tools/`. Background: `HANDOFF.md`,
`worklogs/fix-a-spec.md` (spad-index-fix), `worklogs/fix-b-spec.md` (sparse-loop-fix, draft).

## Hard rules
1. Every number in a doc, report or worklog cites the log it came from. No estimates presented as measurements.
2. Never modify recorded run folders, logs, or `verification/bin/`.
3. Never rebuild or overwrite a simulator without user approval. Berkeley's stock simulator
   (`GemminiRocketConfig`) is never built from modified sources.
4. Compare cycle counts only within the same build. A cycle count counts only if the output check says verified.
5. Git: never commit, push, stash, reset or checkout without asking. Never commit directly to `main`; use a
   branch and a PR. Commit messages: short, say what and why.
6. Scope: only the user's sparsity code (the diff from each Berkeley base, plus this repo). Read Berkeley code only
   to understand ours. Report bugs in Berkeley code; do not fix them.
7. Never handle the server password.

## Spec before code
Any ISA, protocol or hardware-behaviour change needs a spec in `experiments/streaming/worklogs/<fix>-spec.md`
marked `STATUS: FROZEN` before code is written. RTL and Spike implement the same spec. Later changes go in the
spec's changelog with a date.

## Done means
- Spike tests pass on 2:4 and 4:8 (Spike built only in a scratch dir, run with `--extlib`; never install it into
  the toolchain or overwrite `gemmini-rocc-tests/build`).
- Every new check or assert has a negative (NEG) test that triggers it.
- The new tests fail on a deliberately broken (mutant) build.
- Berkeley's 56 dense tests still pass.
- Then Verilator runs on the server confirm it (with user approval for any rebuild).

## Comments
- In Berkeley's code, every added or modified line carries `// changed: <why>`, tagged with the fix name, e.g.
  `// changed: spad-index-fix, completions from the index loader`. This repo's own code is exempt.
- Comments explain why and constraints, never what the code plainly does. One line where possible.
- No history in comments ("was X, now Y"); that goes in git and worklogs.
- Never delete or reword an existing comment unless the task requires it.

## Style
- All languages: match the surrounding code. Never run a formatter on existing files. New Python files follow PEP 8.
- Chisel/Scala: new hardware is generated only on N:M configs; the dense build must stay unchanged. Every illegal
  use gets a sim-time `assert` whose message starts with the feature name (`"n:m index loader: ..."`). `sbt`
  compile must pass after each edit. No elaboration or Verilator on the laptop.
- C: never change an existing benchmark variant or its output line format; add new variants. Index-row mvins
  count inside the timed region unless the variant name says otherwise. Every benchmark verifies its output
  against the CPU reference. Hardware macros use the `GEMMINI_HW_NM_*` prefix.
- Python: standard library plus matplotlib only. To add a package, write the case in your worklog (what it does
  that stdlib/matplotlib can't, its license) and ask the user first. Scripts exit non-zero on a missing, failed
  or unverified log; never skip one silently. Every computed number traces to a log line.
- bash: `set -euo pipefail`. A failed compile or sim stops the script. Never run `make` in `sims/` in parallel.
  Long server jobs run under `nohup setsid` and write a `STATUS` file when done.

## Server (ai-1769.floridapoly.org, user ai-user)
- Use only the existing SSH socket:
  `ssh -o ControlPath=/tmp/claude-1000/cm-%C -o BatchMode=yes ai-user@ai-1769.floridapoly.org '<cmd>'`.
  If it is down, stop and report. Needs the Florida Poly VPN.
- Env: `source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh`. No tar/rsync on the server
  (see `worklogs/server.md`).
- At most 12 simulations at once across all agents; respect the quota you were given.
- Each run goes in a new folder `~/sinv/runs/<YYYYMMDD-HHMMSS>-<tag>-srv` with `run.info`, `jobs.tsv`,
  `SHA256SUMS`, and is copied back to `experiments/streaming/investigate/runs/` with checksums verified.
- Back up a simulator and its `generated-src` before any approved rebuild.

## Naming
- Fixes get a 1-2 word name describing the problem plus `-fix`. Code identifiers use underscores.
- Benchmark variants: `<mode>_<fix>`. Worklogs: `<topic>.md`. Specs: `<fix>-spec.md`.

| Old name | Name | Notes |
|---|---|---|
| Fix A | `spad-index-fix` | index rows loaded from the scratchpad (funct 26, rd=2). Variant `sparse_fixa` and `fix-a-*.md` names kept where recorded logs use them. |
| Fix B | `sparse-loop-fix` | sparse mode in the `LOOP_WS` hardware loop. Draft spec. |

## Worklogs and reports
- One worklog per agent in `experiments/streaming/worklogs/`, updated after every step, so work survives an
  interruption. Before stopping, add a `## RESUME HERE` section: done, running (paths), findings, next steps.
- The README results table and paper numbers change only with user approval.
- Hand-back report: under 50 lines. Brief overview of what you did, changes as `file:line`, results with log
  paths, anomalies, open questions. No filler.
- Only the coordinator edits `AGENTS.md` and `CLAUDE.md`, and only with the user's OK.
