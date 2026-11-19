#!/usr/bin/env bash
# Run accuracy configs one at a time (CPU shared with Spike agents). Writes STATUS in this dir's queue folder.
# Usage: nohup setsid ./run_queue.sh <queue-name> "dense 1" "dense 2" "2:4 1" ... &
# Each job is "<pattern> <seed>". Parent run = latest finished non-smoke run of the parent pattern, same seed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HOME/venvs/sparsity-acc/bin/python"
name="$1"; shift
Q="$HERE/queues/$name"
mkdir -p "$Q"
STATUS="$Q/STATUS"
echo "RUNNING started $(date -Is)" > "$STATUS"

parent_of() {  # pattern -> parent pattern
  case "$1" in
    2:4|4:8|8:16) echo dense ;;
    1:4) echo 2:4 ;; 2:8) echo 4:8 ;; 4:16) echo 8:16 ;;
    *) echo "" ;;
  esac
}

fail() { echo "FAILED $* $(date -Is)" >> "$STATUS"; echo "FAILED" > "$Q/STATUS.final"; exit 1; }

for job in "$@"; do
  read -r pat seed <<< "$job"
  avail_mb=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
  if (( avail_mb < 3000 )); then fail "$job low RAM ${avail_mb}MB"; fi
  args=(--pattern "$pat" --seed "$seed")
  case "$pat" in dense|2:4|4:8|8:16) args+=(--save) ;; esac
  ppat="$(parent_of "$pat")"
  if [[ -n "$ppat" ]]; then
    ptag="${ppat/:/_}"
    pdir="$(ls -d "$HERE"/runs/*-mrpc-"$ptag"-s"$seed" 2>/dev/null | sort | tail -1 || true)"
    [[ -n "$pdir" && -f "$pdir/DONE" ]] || fail "$job no finished parent $ppat s$seed"
    args+=(--parent "$pdir")
  fi
  echo "START $job $(date -Is) avail=${avail_mb}MB" >> "$STATUS"
  if ! nice -n 10 "$PY" "$HERE/run_config.py" "${args[@]}" > "$Q/job-${pat/:/_}-s$seed.out" 2>&1; then
    fail "$job (see $Q/job-${pat/:/_}-s$seed.out)"
  fi
  echo "END $job $(date -Is) $(tail -1 "$Q/job-${pat/:/_}-s$seed.out")" >> "$STATUS"
done
echo "DONE $(date -Is)" >> "$STATUS"
echo "DONE" > "$Q/STATUS.final"
