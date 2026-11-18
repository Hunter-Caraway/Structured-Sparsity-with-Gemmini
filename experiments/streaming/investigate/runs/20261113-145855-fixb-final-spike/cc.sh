#!/usr/bin/env bash
# cc.sh <src> <out|-> [flags]: the gemmini-rocc-tests compile line; out "-" = -Wall syntax check only
set -eo pipefail
cy=$HOME/chipyard; t=$cy/generators/gemmini/software/gemmini-rocc-tests; c=$t/riscv-tests/benchmarks/common
source "$HOME/miniforge3/etc/profile.d/conda.sh"; conda deactivate 2>/dev/null || true
source "$cy/env.sh" > /dev/null
src=$1; out=$2; shift 2
pre=(-DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common -fno-builtin-printf -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc)
inc=(-I$t/riscv-tests -I$t/riscv-tests/env -I$t -I$c -DID_STRING= -DPRINT_TILE=0)
if [ "$out" = - ]; then riscv64-unknown-elf-gcc "$@" "${pre[@]}" "${inc[@]}" -DBAREMETAL=1 -Wall -Wextra -fsyntax-only "$src"
else riscv64-unknown-elf-gcc "$@" "${pre[@]}" -lm -lgcc "${inc[@]}" -nostdlib -nostartfiles -static -T $c/test.ld -DBAREMETAL=1 "$src" -o "$out" $c/syscalls.c $c/crt.S 2>&1 | grep -v RWX || true; [ -s "$out" ]; fi
