#!/bin/bash
# run_jobs.sh <run_dir> <jobs_file>: Verilator runs (never builds a simulator), PAR at a time (default 12).
#   jobs lines: <chip> <binary path> <seed> <timeout_cycles>   chip = nm24 | nm48 (the stock chip is not used here)
#   -> run_dir/<chip>.<binary basename w/o -baremetal>.seed<S>.log, run_dir/bin/, jobs.tsv, run.info, SHA256SUMS
# same make invocation as investigate/scripts/run_bins.sh and run-flow.sh: run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1
set -o pipefail
cy=~/chipyard run="$1" jobs="$2" par="${PAR:-12}"
[ -n "$run" ] && [ -f "$jobs" ] || { echo "usage: run_jobs.sh <run_dir> <jobs_file>" >&2; exit 2; }
mkdir -p "$run/bin"
source ~/miniforge3/etc/profile.d/conda.sh; source $cy/env.sh > /dev/null
cfg_of() { case "$1" in nm24) echo GemminiNMRocketConfig ;; nm48) echo GemminiNM48RocketConfig ;; *) return 1 ;; esac; }
while read -r chip b seed tmo; do
  [ -z "$chip" ] || [[ "$chip" == \#* ]] && continue
  cfg_of "$chip" > /dev/null && [ -f "$b" ] && [[ "$seed" =~ ^[0-9]+$ ]] || { echo "bad job: $chip $b $seed" >&2; exit 2; }
done < "$jobs"
if [ ! -f "$run/run.info" ]; then
  {
    echo "stamp=$(basename "$run")"
    echo "host=$(hostname) $(uname -r) nproc=$(nproc)"
    for r in "$HOME/gemmini-sparsity" "$cy/generators/gemmini" "$cy/generators/gemmini/software/libgemmini" \
             "$cy/generators/gemmini/software/gemmini-rocc-tests"; do
      echo "git.$(basename "$r")=$(git -C "$r" rev-parse HEAD 2>/dev/null || echo none)$(git -C "$r" diff --quiet HEAD 2>/dev/null && echo '' || echo ' (uncommitted changes)') diff.sha256=$(git -C "$r" diff HEAD --binary 2>/dev/null | sha256sum | cut -c1-64)"
    done
    for c in stock nm24 nm48; do
      case $c in stock) cf=GemminiRocketConfig ;; *) cf=$(cfg_of $c) ;; esac
      s="$cy/sims/verilator/simulator-chipyard.harness-$cf"
      echo "sim.$c=$cf mtime=$(date -r "$s" '+%Y-%m-%dT%H:%M:%S') sha256=$(sha256sum "$s" | cut -d' ' -f1)"
    done
    echo "gemmini_nm.h.sha256=$(sha256sum "$cy/generators/gemmini/software/gemmini-rocc-tests/include/gemmini_nm.h" | cut -d' ' -f1)"
    echo "make=run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 (RANDOM_SEED, TIMEOUT_CYCLES per job)"
    echo "flags=~/fixa/build_progs.sh (run-flow.sh rv_cc flags, -I<generated gemmini_params.h dir> first, -DNM_N/-DNM_M); see build.info"
  } > "$run/run.info"
fi
cp "$jobs" "$run/jobs-$(date +%Y%m%d-%H%M%S).txt"
[ -f "$run/jobs.tsv" ] || printf 'chip\tbinary\tseed\ttimeout\tstart\tend\twall_s\texit\n' > "$run/jobs.tsv"
one() {
  local chip="$1" b="$2" seed="$3" tmo="$4" name log t0 t1 rc
  name="$(basename "$b")"; cp -n "$b" "$run/bin/"
  log="$run/$chip.${name%-baremetal}.seed$seed.log"; [ ! -e "$log" ] || return 0
  t0=$(date +%s)
  (cd "$cy/sims/verilator" && make CONFIG="$(cfg_of "$chip")" run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 \
     TIMEOUT_CYCLES="$tmo" BINARY="$run/bin/$name" RANDOM_SEED="$seed" EXTRA_SIM_OUT_NAME="fixa.$chip.seed$seed.$(basename "$run")") > "$log" 2>&1
  rc=$?; t1=$(date +%s)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$chip" "$name" "$seed" "$tmo" "$t0" "$t1" "$((t1-t0))" "$rc" >> "$run/jobs.tsv"
  echo "  done $chip $name seed $seed exit $rc $((t1-t0)) s ($(date +%H:%M:%S))"
}
while read -r chip b seed tmo; do
  [ -z "$chip" ] || [[ "$chip" == \#* ]] && continue
  while [ "$(jobs -rp | wc -l)" -ge "$(cat "$run/PAR" 2>/dev/null || echo "$par")" ]; do wait -n || true; done
  one "$chip" "$b" "$seed" "$tmo" &
  sleep 1
done < "$jobs"
wait
(cd "$run" && find . -type f ! -name SHA256SUMS -printf '%P\0' | sort -z | xargs -0 sha256sum) > "$run/SHA256SUMS"
echo "ALL_DONE $(date)" > "$run/STATUS"
echo "done: $run"
