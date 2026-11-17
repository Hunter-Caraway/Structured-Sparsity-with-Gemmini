#!/usr/bin/env bash
# launch_micro_loop_srv.sh <spike_run_dir> [s3]: start the micro_loop RTL runs (bank-split-fix-spec.md section 8) on
# the server with the existing Fix B nm24 / nm48 simulators (never builds one). Binaries come from the Spike run
# folder's bin/ (already verified there). S1 = nm24 micro_loop_24, S2 = nm48 micro_loop_48, S3 (with "s3") = nm24
# micro_loop_24_s1. Refuses to start if the simulators' sha256 differ from the Fix B run or if the new sims would
# push the server over 12. Run folder ~/sinv/runs/<stamp>-microloop-srv, launched with ~/fixb/run_jobs.sh under
# nohup setsid (writes jobs.tsv, SHA256SUMS, STATUS); run.info is written here first so run_jobs.sh keeps it.
set -euo pipefail
src="$(cd "$1" && pwd)"; want_s3="${2:-}"
SSH=(ssh -o ControlPath=/tmp/claude-1000/cm-%C -o BatchMode=yes -o ConnectTimeout=20 ai-user@ai-1769.floridapoly.org)
SIM24=1042fc926288a463c829cdfe654a5515b6243ca56ae19b425fd7d542bf237891
SIM48=f4a3642cf572de929c758c3fd2a1f2320ee286ce45787aca13a7d0ac1018ed34
bins=(micro_loop_24 micro_loop_48)
[ "$want_s3" = s3 ] && bins+=(micro_loop_24_s1)
nsim=${#bins[@]}

timeout 60 "${SSH[@]}" true || { echo "ssh socket down: reconnect first" >&2; exit 3; }
busy=$(timeout 60 "${SSH[@]}" 'ps -eo comm | grep -c ^simulator-chip || true')
[ "$busy" -le $((12 - nsim)) ] || { echo "server busy: $busy simulators running, need <= $((12 - nsim))" >&2; exit 4; }
sims=$(timeout 60 "${SSH[@]}" 'cd ~/chipyard/sims/verilator; sha256sum simulator-chipyard.harness-GemminiNMRocketConfig simulator-chipyard.harness-GemminiNM48RocketConfig')
grep -q "^$SIM24  simulator-chipyard.harness-GemminiNMRocketConfig$" <<<"$sims" || { echo "nm24 simulator changed: $sims" >&2; exit 5; }
grep -q "^$SIM48  simulator-chipyard.harness-GemminiNM48RocketConfig$" <<<"$sims" || { echo "nm48 simulator changed: $sims" >&2; exit 5; }

stamp="$(date +%Y%m%d-%H%M%S)-microloop-srv"
run="/home/ai-user/sinv/runs/$stamp" progs="/home/ai-user/microloop/progs-$stamp"
timeout 60 "${SSH[@]}" "mkdir -p '$progs' '$run'"
for b in "${bins[@]}"; do
  timeout 300 "${SSH[@]}" "cat > '$progs/$b-baremetal'" < "$src/bin/$b-baremetal"
  l=$(sha256sum "$src/bin/$b-baremetal" | cut -d' ' -f1)
  r=$(timeout 60 "${SSH[@]}" "sha256sum '$progs/$b-baremetal'" | cut -d' ' -f1)
  [ "$l" = "$r" ] || { echo "copy of $b differs ($l vs $r)" >&2; exit 6; }
done
jobs=""
for b in "${bins[@]}"; do
  case "$b" in *_48*) chip=nm48 ;; *) chip=nm24 ;; esac
  jobs+="$chip $progs/$b-baremetal 1 80000000"$'\n'
done
info="stamp=$stamp
purpose=bank-split-fix-spec.md section 8 micro-test (micro_loop.c), no simulator rebuild
sim.nm24=GemminiNMRocketConfig sha256=$SIM24 (same as runs/20261113-160015-fixb-srv)
sim.nm48=GemminiNM48RocketConfig sha256=$SIM48 (same as runs/20261113-160015-fixb-srv)
programs=from laptop investigate/runs/$(basename "$src")/bin (Spike-verified there), copied with ssh cat, sha256 checked:
$(cd "$src/bin" && for b in "${bins[@]}"; do sha256sum "$b-baremetal"; done)
sources=$(grep -A3 '^sources:' "$src/run.info" | tail -3 | tr '\n' ';')
make=run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 via ~/fixb/run_jobs.sh (RANDOM_SEED 1, TIMEOUT_CYCLES 80000000)
servers_busy_at_launch=$busy"
timeout 60 "${SSH[@]}" "cat > '$run/run.info'" <<<"$info"
timeout 60 "${SSH[@]}" "cat > '$run/jobs-in.txt'" <<<"$jobs"
timeout 60 "${SSH[@]}" "cd ~ && PAR=$nsim nohup setsid ~/fixb/run_jobs.sh '$run' '$run/jobs-in.txt' > '/home/ai-user/microloop/$stamp.out' 2>&1 < /dev/null & echo launched"
echo "$run"
