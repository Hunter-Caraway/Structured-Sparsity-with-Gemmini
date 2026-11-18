#!/bin/bash
# watch.sh: poll the server run every 90 s; print one line per finished job that matters (spad positive, any
# unexpected exit code), a progress line every 10 finished jobs, and exit when STATUS exists.
S="ssh -o ControlPath=/tmp/claude-1000/cm-%C -o BatchMode=yes ai-user@ai-1769.floridapoly.org"
R=sinv/runs/20261111-183018-fixa-srv
seen=${SEEN:-0}
while true; do
  out=$(timeout 60 $S "tail -n +2 ~/$R/jobs.tsv; ls ~/$R/STATUS 2>/dev/null; true" 2>&1) || { echo "ssh problem: $(echo "$out" | head -1)"; sleep 90; continue; }
  n=$(grep -c $'\t' <<<"$out")
  if [ "$n" -gt "$seen" ]; then
    tail -n +$((seen + 1)) <<<"$(grep $'\t' <<<"$out")" | while IFS=$'\t' read -r chip b s t t0 t1 w rc; do
      neg=0; [[ "$b" == *neg* ]] && neg=1
      if [[ "$b" == nm_sparse_spad* ]] || { [ $neg = 1 ] && [ "$rc" = 0 ]; } || { [ $neg = 0 ] && [ "$rc" != 0 ]; }; then
        echo "job: $chip $b seed $s exit $rc ${w}s"; fi
    done
    for k in $(seq $((seen + 1)) $n); do [ $((k % 10)) -eq 0 ] && echo "progress: $k/98 jobs finished"; done
    seen=$n
  fi
  grep -q STATUS <<<"$out" && { echo "ALL_DONE ($n jobs)"; exit 0; }
  sleep 90
done
