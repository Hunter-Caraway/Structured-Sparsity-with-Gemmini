#!/usr/bin/env bash
# run_bins.sh <run_dir> <jobs_file>: Verilator runs of arbitrary binaries, PAR at a time (never builds a simulator).
#   jobs lines: <chip> <binary path> <seed> <timeout_cycles>   chip = stock | nm24 | nm48
#   -> run_dir/<chip>.<binary basename>.seed<S>.log, run_dir/bin/, run_dir/jobs.tsv, run_dir/run.info, SHA256SUMS
set -o pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cy="${CHIPYARD_DIR:-$HOME/chipyard}"
run="$1" jobs="$2" par="${PAR:-4}"
[ -n "$run" ] && [ -f "$jobs" ] || { echo "usage: run_bins.sh <run_dir> <jobs_file>" >&2; exit 2; }
mkdir -p "$run/bin"
base="$(conda info --base 2>/dev/null || echo "$HOME/miniforge3")"
source "$base/etc/profile.d/conda.sh"; conda deactivate 2>/dev/null || true
source "$cy/env.sh" > /dev/null
cfg_of() { case "$1" in stock) echo GemminiRocketConfig ;; nm24) echo GemminiNMRocketConfig ;; nm48) echo GemminiNM48RocketConfig ;; *) return 1 ;; esac; }
sim_of() { echo "$cy/sims/verilator/simulator-chipyard.harness-$(cfg_of "$1")"; }
if [ ! -f "$run/run.info" ]; then
  {
    echo "stamp=$(basename "$run")"
    echo "host=$(hostname) $(uname -r) nproc=$(nproc)"
    for r in "$HOME/gemmini-sparsity" "$cy/generators/gemmini" "$cy/generators/gemmini/software/libgemmini" \
             "$cy/generators/gemmini/software/gemmini-rocc-tests"; do
      echo "git.$(basename "$r")=$(git -C "$r" rev-parse HEAD)$(git -C "$r" diff --quiet HEAD && echo '' || echo ' (uncommitted changes)')"
    done
    for c in stock nm24 nm48; do s="$(sim_of "$c")"; echo "sim.$c=$(cfg_of "$c") mtime=$(date -r "$s" '+%Y-%m-%dT%H:%M:%S') sha256=$(sha256sum "$s" | cut -d' ' -f1)"; done
    echo "gemmini_nm.h.sha256=$(sha256sum "$cy/generators/gemmini/software/gemmini-rocc-tests/include/gemmini_nm.h" | cut -d' ' -f1)"
    for f in "$here"/src/*; do echo "src.$(basename "$f").sha256=$(sha256sum "$f" | cut -d' ' -f1)"; done
    echo "make=run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 (RANDOM_SEED, TIMEOUT_CYCLES per job)"
    echo "flags=investigate/scripts/build_one.sh (= scripts/build.sh rv_cc flags) + -DNM_N/-DNM_M"
  } > "$run/run.info"
fi
cp "$jobs" "$run/jobs-$(date +%Y%m%d-%H%M%S).txt"
[ -f "$run/jobs.tsv" ] || printf 'chip\tbinary\tseed\ttimeout\tstart\tend\twall_s\texit\n' > "$run/jobs.tsv"
one() {
  local chip="$1" b="$2" seed="$3" tmo="$4" name log t0 t1 rc
  name="$(basename "$b")"; cp -n "$b" "$run/bin/"
  echo "bin.$name.sha256=$(sha256sum "$b" | cut -d' ' -f1)" >> "$run/run.info"
  log="$run/$chip.${name%-baremetal}.seed$seed.log"; [ ! -e "$log" ] || return 0
  t0=$(date +%s)
  (cd "$cy/sims/verilator" && make CONFIG="$(cfg_of "$chip")" run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 \
     TIMEOUT_CYCLES="$tmo" BINARY="$run/bin/$name" RANDOM_SEED="$seed" EXTRA_SIM_OUT_NAME="inv.$chip.seed$seed.$(basename "$run")") > "$log" 2>&1
  rc=$?; t1=$(date +%s)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$chip" "$name" "$seed" "$tmo" "$t0" "$t1" "$((t1-t0))" "$rc" >> "$run/jobs.tsv"
  echo "  done $chip $name seed $seed exit $rc $((t1-t0)) s"
}
while read -r chip b seed tmo; do
  [ -z "$chip" ] || [[ "$chip" == \#* ]] && continue
  while [ "$(jobs -rp | wc -l)" -ge "$par" ]; do wait -n; done
  one "$chip" "$b" "$seed" "$tmo" &
  sleep 1
done < "$jobs"
wait
(cd "$run" && find . -type f ! -name SHA256SUMS -printf '%P\0' | sort -z | xargs -0 sha256sum) > "$run/SHA256SUMS"
echo "done: $run"
