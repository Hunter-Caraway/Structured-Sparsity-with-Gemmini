#!/usr/bin/env bash
# run_rtl.sh <run_dir> <jobs_file>: run Verilator simulations listed in jobs_file, PAR at a time, into run_dir.
#   jobs_file lines: <chip> <program> <seed> [timeout_cycles]
#     chip    = stock | nm24 | nm48  (GemminiRocketConfig | GemminiNMRocketConfig | GemminiNM48RocketConfig)
#     program = a name under build/bin/<layer>/ without -baremetal, e.g. small_24_full
#   -> run_dir/<chip>.<program>.seed<S>.log, run_dir/bin/ (copies of the programs), run_dir/jobs.tsv (wall times),
#      run_dir/run.info (provenance; written/extended by this script). Re-using a run_dir appends jobs.
# never builds anything: make run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 (the conventions of run-flow.sh).
# env: PAR (default 4), TIMEOUT_CYCLES (default per job, else 150000000), BIN_ROOT (default build/bin), CHIPYARD_DIR
# also copies each program's host reference (build/data/<layer>/<pat>/ref.json) to run_dir/ref/<layer>_<pat>.json
set -o pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cy="${CHIPYARD_DIR:-$HOME/chipyard}"
run="$1" jobs="$2"
[ -n "$run" ] && [ -f "$jobs" ] || { echo "usage: run_rtl.sh <run_dir> <jobs_file>" >&2; exit 2; }
case "$run" in *" "*|*:*) echo "run dir must not contain spaces or ':'" >&2; exit 2 ;; esac
par="${PAR:-4}"
bin_root="${BIN_ROOT:-$here/build/bin}"
mkdir -p "$run/bin"
stamp="$(basename "$run")"

base="$(conda info --base 2>/dev/null || echo "$HOME/miniforge3")"
# shellcheck disable=SC1091
source "$base/etc/profile.d/conda.sh"; conda deactivate 2>/dev/null || true
# shellcheck disable=SC1091
source "$cy/env.sh" > /dev/null

cfg_of() { case "$1" in stock) echo GemminiRocketConfig ;; nm24) echo GemminiNMRocketConfig ;; nm48) echo GemminiNM48RocketConfig ;; *) return 1 ;; esac; }
sim_of() { echo "$cy/sims/verilator/simulator-chipyard.harness-$(cfg_of "$1")"; }

# validate everything first
while read -r chip prog seed tmo; do
  [ -z "$chip" ] || [[ "$chip" == \#* ]] && continue
  cfg_of "$chip" > /dev/null || { echo "bad chip $chip" >&2; exit 2; }
  [ -x "$(sim_of "$chip")" ] || { echo "missing simulator for $chip" >&2; exit 2; }
  L="${prog%_[24][48]_*}"
  [ -f "$bin_root/$L/$prog-baremetal" ] || { echo "missing program $prog" >&2; exit 2; }
  [[ "$seed" =~ ^[0-9]+$ ]] || { echo "bad seed $seed" >&2; exit 2; }
done < "$jobs"

# provenance (once per run dir)
if [ ! -f "$run/run.info" ]; then
  {
    echo "stamp=$stamp"
    echo "host=$(hostname) $(uname -r) nproc=$(nproc)"
    for r in "$HOME/gemmini-sparsity" "$cy/generators/gemmini" "$cy/generators/gemmini/software/libgemmini" \
             "$cy/generators/gemmini/software/gemmini-rocc-tests"; do
      echo "git.$(basename "$r")=$(git -C "$r" rev-parse HEAD) branch=$(git -C "$r" rev-parse --abbrev-ref HEAD)$(git -C "$r" diff --quiet HEAD && echo '' || echo ' (uncommitted changes)')"
      git -C "$r" diff --stat HEAD | tail -1 | sed "s/^/git.$(basename "$r").diffstat=/"
    done
    echo "chipyard=$(git -C "$cy" describe --tags 2>/dev/null || git -C "$cy" rev-parse HEAD)"
    for c in stock nm24 nm48; do
      s="$(sim_of "$c")"; echo "sim.$c=$(cfg_of "$c") mtime=$(date -r "$s" '+%Y-%m-%dT%H:%M:%S') sha256=$(sha256sum "$s" | cut -d' ' -f1)"
    done
    echo "gemmini_nm.h.sha256=$(sha256sum "$cy/generators/gemmini/software/gemmini-rocc-tests/include/gemmini_nm.h" | cut -d' ' -f1)"
    echo "stream_bench.c.sha256=$(sha256sum "$here/src/stream_bench.c" | cut -d' ' -f1)"
    echo "gen_data.py.sha256=$(sha256sum "$here/gen/gen_data.py" | cut -d' ' -f1)"
    echo "bin_root=$bin_root"
    echo "make=run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 (RANDOM_SEED, TIMEOUT_CYCLES per job: see jobs.tsv)"
    echo "flags=$(grep -o 'rv_pre=(.*' "$here/scripts/build.sh" | head -1) + -DNM_N/-DNM_M, -DRUN_MASK, [-DDENSE_ONLY]"
  } > "$run/run.info"
fi
cp "$jobs" "$run/jobs-$(date +%Y%m%d-%H%M%S).txt"
[ -f "$run/jobs.tsv" ] || printf 'chip\tprogram\tseed\ttimeout_cycles\tstart_epoch\tend_epoch\twall_s\texit\n' > "$run/jobs.tsv"

pids=()
cleanup() { for p in "${pids[@]}"; do pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; done; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

one() {  # one <chip> <prog> <seed> <timeout>
  local chip="$1" prog="$2" seed="$3" tmo="$4" L log t0 t1 rc
  L="${prog%_[24][48]_*}"
  [ -f "$run/bin/$prog-baremetal" ] || cp "$bin_root/$L/$prog-baremetal" "$run/bin/"
  pat="${prog#"$L"_}"; pat="${pat%%_*}"; mkdir -p "$run/ref"
  [ -f "$run/ref/${L}_$pat.json" ] || cp "$here/build/data/$L/$pat/ref.json" "$run/ref/${L}_$pat.json"
  log="$run/$chip.$prog.seed$seed.log"
  [ ! -e "$log" ] || { echo "  skip (exists) $log"; return 0; }
  t0=$(date +%s)
  (cd "$cy/sims/verilator" && make CONFIG="$(cfg_of "$chip")" run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 \
     TIMEOUT_CYCLES="$tmo" BINARY="$run/bin/$prog-baremetal" RANDOM_SEED="$seed" \
     EXTRA_SIM_OUT_NAME="sbench.$chip.seed$seed.$stamp") > "$log" 2>&1
  rc=$?
  t1=$(date +%s)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$chip" "$prog" "$seed" "$tmo" "$t0" "$t1" "$((t1 - t0))" "$rc" >> "$run/jobs.tsv"
  if [ $rc -eq 0 ] && grep -q '^sbench passed' "$log"; then echo "  ok    $chip $prog seed $seed  $((t1 - t0)) s  ($(date +%H:%M:%S))"
  else echo "  FAIL  $chip $prog seed $seed (exit $rc)  $((t1 - t0)) s  ($(date +%H:%M:%S))"; fi
}

while read -r chip prog seed tmo; do
  [ -z "$chip" ] || [[ "$chip" == \#* ]] && continue
  # <run_dir>/PAR, if present, overrides PAR while the queue runs (lets the parallelism follow the machine's load)
  # (PAR_FILE names another file, so a second runner on the same run dir can have its own limit; jobs whose log
  # already exists are skipped, so two runners can share one queue)
  while [ "$(jobs -rp | wc -l)" -ge "$(cat "$run/${PAR_FILE:-PAR}" 2>/dev/null || echo "$par")" ]; do wait -n || sleep 30; done
  one "$chip" "$prog" "$seed" "${tmo:-${TIMEOUT_CYCLES:-150000000}}" &
  pids+=($!)
  echo "  started $chip $prog seed $seed ($(date +%H:%M:%S))"
  sleep 2
done < "$jobs"
wait
pids=()
# checksums of everything in the run folder except derived outputs
(cd "$run" && find . -type f ! -name SHA256SUMS ! -path './derived/*' -printf '%P\0' | sort -z | xargs -0 sha256sum) > "$run/SHA256SUMS"
echo "done: $run"
