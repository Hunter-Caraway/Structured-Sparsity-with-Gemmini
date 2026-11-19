#!/bin/bash
# Launch one out-of-context Yosys area run of the Gemmini module on the server.
# Usage: synth_area.sh <Config> <nangate45|sky130hd>
#   e.g. synth_area.sh GemminiNMRocketConfig nangate45
# Uses the config's existing generated Verilog on the server (never elaborates).
# Prints the run folder; fetch it with fetch_area.sh once STATUS exists.
# Env: AREA_CORE (default 13), MIN_AVAIL_GB (default 12).
set -euo pipefail
[ $# -eq 2 ] || { sed -n '2,8p' "$0"; exit 2; }
CFG=$1 LIBNAME=$2
HERE=$(cd "$(dirname "$0")" && pwd)
H=ai-user@ai-1769.floridapoly.org
SSH=(ssh -o ControlPath=/tmp/claude-1000/cm-%C -o BatchMode=yes -o ConnectTimeout=15 "$H")
CORE=${AREA_CORE:-13}
MIN_AVAIL_GB=${MIN_AVAIL_GB:-12}

"${SSH[@]}" true || { echo "ssh socket down; reconnect VPN + ControlMaster first"; exit 1; }

# Upload the flow files; the server copy must hash-match this repo.
"${SSH[@]}" 'mkdir -p ~/area/flow ~/area/runs'
for f in area_remote.sh synth_area.ys.in verilog_closure.py parse_area.py; do
  "${SSH[@]}" "cat > ~/area/flow/$f" < "$HERE/$f"
  want=$(sha256sum < "$HERE/$f" | cut -d' ' -f1)
  got=$("${SSH[@]}" "sha256sum < ~/area/flow/$f" | cut -d' ' -f1)
  [ "$want" = "$got" ] || { echo "upload mismatch $f"; exit 1; }
done

# Preflight: one synthesis at a time, enough RAM left for the sims.
"${SSH[@]}" "pgrep -f '[a]rea_remote.sh' >/dev/null" && { echo "another area run is active"; exit 1; }
"${SSH[@]}" "[ -d ~/chipyard/sims/verilator/generated-src/chipyard.harness.TestHarness.$CFG/gen-collateral ]" \
  || { echo "no generated Verilog for $CFG on the server"; exit 1; }
avail_kb=$("${SSH[@]}" "awk '/MemAvailable/{print \$2}' /proc/meminfo")
[ "$avail_kb" -ge $((MIN_AVAIL_GB * 1024 * 1024)) ] || { echo "MemAvailable ${avail_kb} kB < ${MIN_AVAIL_GB} GB"; exit 1; }
sims=$("${SSH[@]}" "pgrep -fc '^[^ ]*simulator-chip' || true")

RUN=runs/$(date +%Y%m%d-%H%M%S)-$CFG-$LIBNAME-area
# Only the nohup line is backgrounded, so ssh returns at once.
"${SSH[@]}" "mkdir ~/area/$RUN || exit 1; cd ~/area/$RUN || exit 1; nohup setsid nice -n 10 taskset -c $CORE \
  bash ~/area/flow/area_remote.sh $CFG $LIBNAME \$HOME/area/$RUN $sims > nohup.out 2>&1 < /dev/null &"
echo "launched ~/area/$RUN (core $CORE, sims $sims, MemAvailable ${avail_kb} kB)"
echo "$RUN"
