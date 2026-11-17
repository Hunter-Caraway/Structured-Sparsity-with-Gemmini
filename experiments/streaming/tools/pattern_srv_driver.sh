#!/usr/bin/env bash
# pattern_srv_driver.sh: runs the jobs of one pattern run folder on the server. `run-flow.sh pattern` copies it into
# ~/sinv/runs/<stamp>-<pattern>-srv/ next to jobs.ordered.tsv and bin/, and starts it with nohup setsid.
#
# - the simulator is called directly with the arguments chipyard's `make run-binary-fast LOADMEM=1` passes (see line 2-7
#   of any log in investigate/runs/20261113-160015-fixb-srv), so no make runs in sims/ (AGENTS: never in parallel);
#   that command is the first line of each log, so the logs keep the `+verilator+seed+S` marker the parsers read
# - at most QUOTA (file in the run folder, re-read before every start, so it can be changed while running) of its own
#   jobs at once, and never a start while 12 or more `simulator-chip*` processes run on the machine (project cap)
# - jobs.tsv: chip binary seed timeout start end wall_s exit (same columns as the earlier server runs)
# - STATUS: RUNNING <pid> while running, ALL_DONE <date> at the end; SHA256SUMS is written last, after STATUS
set -euo pipefail
run="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cy="$HOME/chipyard"
cap=12
jobs_file="$run/jobs.ordered.tsv"
ini="$cy/generators/testchipip/src/main/resources/dramsim2_ini"
[ -f "$jobs_file" ] && [ -f "$run/QUOTA" ] || { echo "missing jobs.ordered.tsv or QUOTA in $run" >&2; exit 2; }
[ -d "$ini" ] || { echo "no dramsim2_ini at $ini" >&2; exit 2; }
set +u
# shellcheck disable=SC1091
source "$HOME/miniforge3/etc/profile.d/conda.sh"
# shellcheck disable=SC1091
source "$cy/env.sh" > /dev/null
set -u
echo "RUNNING $$ $(date)" > "$run/STATUS"
[ -f "$run/jobs.tsv" ] || printf 'chip\tbinary\tseed\ttimeout\tstart\tend\twall_s\texit\n' > "$run/jobs.tsv"

global_sims() { pgrep -fc '^[^ ]*simulator-chip' || true; }
own_sims() { jobs -rp | wc -l; }
quota() { local q; q="$(cat "$run/QUOTA" 2>/dev/null || echo 1)"; [[ "$q" =~ ^[0-9]+$ ]] || q=1; echo "$q"; }

one() {
  local chip="$1" cfg="$2" prog="$3" seed="$4" tmo="$5" sim bin log t0 t1 rc=0
  sim="$cy/sims/verilator/simulator-chipyard.harness-$cfg"
  bin="$run/bin/$prog"
  log="$run/$chip.${prog%-baremetal}.seed$seed.log"
  [ ! -e "$log" ] || return 0
  t0=$(date +%s)
  {
    echo "(set -o pipefail &&  $sim +permissive +dramsim +dramsim_ini_dir=$ini +max-cycles=$tmo  +verilator+seed+$seed +loadmem=$bin  +permissive-off $bin </dev/null)"
    cd "$cy/sims/verilator" && "$sim" +permissive +dramsim +dramsim_ini_dir="$ini" +max-cycles="$tmo" \
      +verilator+seed+"$seed" +loadmem="$bin" +permissive-off "$bin" < /dev/null
  } > "$log" 2>&1 || rc=$?
  t1=$(date +%s)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$chip" "$prog" "$seed" "$tmo" "$t0" "$t1" "$((t1 - t0))" "$rc" >> "$run/jobs.tsv"
  echo "  done $chip $prog seed $seed exit $rc $((t1 - t0)) s ($(date +%H:%M:%S))"
}

n=0
while IFS=$'\t' read -r chip cfg prog seed tmo _; do
  [ "$chip" = chip ] && continue
  [ -n "$chip" ] || continue
  [ -x "$cy/sims/verilator/simulator-chipyard.harness-$cfg" ] && [ -f "$run/bin/$prog" ] && [[ "$seed" =~ ^[0-9]+$ ]] &&
    [[ "$tmo" =~ ^[0-9]+$ ]] || { echo "bad job: $chip $cfg $prog $seed $tmo" >&2; echo "ABORT bad job $(date)" > "$run/STATUS"; exit 2; }
  while [ "$(own_sims)" -ge "$(quota)" ] || [ "$(global_sims)" -ge "$cap" ]; do sleep 30; done
  one "$chip" "$cfg" "$prog" "$seed" "$tmo" < /dev/null &
  n=$((n + 1))
  echo "  started #$n $chip $prog seed $seed timeout $tmo ($(date +%H:%M:%S); own $(own_sims), machine $(global_sims))"
  sleep 5  # lets the new simulator show up in pgrep before the next count
done < "$jobs_file"
wait
echo "all $n jobs finished $(date)"
echo "ALL_DONE $(date)" > "$run/STATUS"
(cd "$run" && find . -type f ! -name SHA256SUMS ! -name SHA256SUMS.tmp ! -name driver.out -printf '%P\0' | sort -z | xargs -0 sha256sum) > "$run/SHA256SUMS.tmp"
mv "$run/SHA256SUMS.tmp" "$run/SHA256SUMS"
