#!/bin/bash
# list.sh <chipyard root> <project root>: sha256 of every tracked + untracked non-ignored regular file of
# gemmini, libgemmini, gemmini-rocc-tests (relative to chipyard/generators/gemmini), plus the benchmark sources
cy=$1 pr=$2
g=$cy/generators/gemmini
for r in . software/libgemmini software/gemmini-rocc-tests; do
  (cd $g/$r && git ls-files -co --exclude-standard -z | while IFS= read -r -d '' f; do
     [ -f "$f" ] && [ ! -L "$f" ] && printf '%s\0' "$f"; done | xargs -0 sha256sum | sed "s|  |  G/$r/|")
done | sed 's|G/\./|G/|'
(cd $pr && for f in verification/fair_perf.c experiments/streaming/src/* experiments/streaming/investigate/src/*; do sha256sum "$f" | sed 's|  |  P/|'; done)
