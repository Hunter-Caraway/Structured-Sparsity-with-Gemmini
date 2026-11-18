#!/usr/bin/env bash
# spike_all.sh [layer ...]: every program on Spike (2:4 programs on the 2:4 model, then 4:8 on the 4:8 model).
# logs -> build/spike-logs/<stamp>/<program>.log; fails if any run does not end with "sbench passed".
set -o pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
layers=("${@}"); [ ${#layers[@]} -gt 0 ] || layers=(edge small bert_qkv bert_ffn1 bert_ffn2 rn50_conv)
out="$here/build/spike-logs/$(date +%Y%m%d-%H%M%S)"; mkdir -p "$out"
fails=0
for pat in 24 48; do
  pids=(); names=()
  for L in "${layers[@]}"; do
    for b in "$here/build/bin/$L/${L}_${pat}_"*-baremetal; do
      n="$(basename "$b" -baremetal)"
      "$here/scripts/spike_run.sh" "nm$pat" "$b" "$out/$n.log" & pids+=($!); names+=("$n")
    done
  done
  for i in "${!pids[@]}"; do
    wait "${pids[i]}"; rc=$?
    if [ $rc -eq 0 ] && grep -q '^sbench passed' "$out/${names[i]}.log"; then echo "pass  ${names[i]}  $(grep -c ' -> verified' "$out/${names[i]}.log") verified"
    else echo "FAIL  ${names[i]} (rc $rc)"; fails=$((fails + 1)); fi
  done
done
echo "logs: $out"
[ $fails -eq 0 ]
