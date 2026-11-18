#!/usr/bin/env bash
# spike_lib.sh: build the Gemmini Spike extension (current libgemmini working tree) for 2:4 and 4:8 into
# build/spike/nm24 and build/spike/nm48 (copies; never installs into $RISCV, never touches the libgemmini tree).
set -eo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cy="${CHIPYARD_DIR:-$HOME/chipyard}"; src="$cy/generators/gemmini/software/libgemmini"
base="$(conda info --base 2>/dev/null || echo "$HOME/miniforge3")"
source "$base/etc/profile.d/conda.sh"; conda deactivate 2>/dev/null || true
source "$cy/env.sh" > /dev/null
for p in "nm24 2 4" "nm48 4 8"; do
  read -r name n m <<<"$p"; d="$here/build/spike/$name"; rm -rf "$d"; mkdir -p "$d"
  cp "$src/gemmini.cc" "$src/gemmini.h" "$src/gemmini_params.h" "$src/Makefile" "$d/"
  make -C "$d" NM_N="$n" NM_M="$m" libgemmini.so > "$d/build.log" 2>&1 || { tail "$d/build.log"; exit 1; }
  echo "built $d/libgemmini.so ($n:$m) sha256 $(sha256sum "$d/libgemmini.so" | cut -c1-16)"
done
