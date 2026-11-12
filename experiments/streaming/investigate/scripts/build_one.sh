#!/usr/bin/env bash
# build_one.sh <src.c> <out> <n> <m> [extra gcc flags...]: one bare-metal program, flags = ../../scripts/build.sh's rv_cc
# (the gemmini-rocc-tests flags), -I investigate/src first so nm_stream_v2.h is found.
set -eo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cy="${CHIPYARD_DIR:-$HOME/chipyard}"
tests_dir="$cy/generators/gemmini/software/gemmini-rocc-tests"
base="$(conda info --base 2>/dev/null || echo "$HOME/miniforge3")"
source "$base/etc/profile.d/conda.sh"; conda deactivate 2>/dev/null || true
source "$cy/env.sh" > /dev/null
src="$1" out="$2" n="$3" m="$4"; shift 4
rv_pre=(-DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common -fno-builtin-printf
        -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc)
rv_inc=(-I"$here/src" -I"$tests_dir/riscv-tests" -I"$tests_dir/riscv-tests/env" -I"$tests_dir"
        -I"$tests_dir/riscv-tests/benchmarks/common" -DID_STRING= -DPRINT_TILE=0)
c="$tests_dir/riscv-tests/benchmarks/common"
mkdir -p "$(dirname "$out")"
riscv64-unknown-elf-gcc "$@" -DNM_N="$n" -DNM_M="$m" "${rv_pre[@]}" -lm -lgcc "${rv_inc[@]}" -nostdlib -nostartfiles \
  -static -T "$c/test.ld" -DBAREMETAL=1 "$src" -o "$out" "$c/syscalls.c" "$c/crt.S" 2>&1 | grep -v RWX || true
[ -s "$out" ] || { echo "compile failed: $out" >&2; exit 1; }
echo "built $out"
