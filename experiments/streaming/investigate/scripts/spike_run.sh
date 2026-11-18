#!/usr/bin/env bash
# spike_run.sh <nm24|nm48> <binary> <log>: run one program on Spike with the scratch Gemmini extension; exit = spike's
set -o pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cy="${CHIPYARD_DIR:-$HOME/chipyard}"
base="$(conda info --base 2>/dev/null || echo "$HOME/miniforge3")"
source "$base/etc/profile.d/conda.sh"; conda deactivate 2>/dev/null || true
source "$cy/env.sh" > /dev/null
export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
timeout "${SPIKE_TIMEOUT:-3600}" spike --extlib="$here/build/spike/$1/libgemmini.so" --extension=gemmini "$2" > "$3" 2>&1
