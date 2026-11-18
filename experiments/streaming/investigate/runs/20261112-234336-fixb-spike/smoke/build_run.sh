#!/bin/bash
# build_run.sh <src.c> <name> <24|48> <lib> [-Dflags]: compile a scratch test and run it on the given lib
set -uo pipefail
S="$(cd "$(dirname "$0")/.." && pwd)"; src=$1 name=$2 p=$3 lib=$4; shift 4
set +u; source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh > /dev/null; set -u
export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
T=~/chipyard/generators/gemmini/software/gemmini-rocc-tests; c=$T/riscv-tests/benchmarks/common
case $p in 24) n=2 m=4;; 48) n=4 m=8;; esac
o=$S/smoke/$name-baremetal
riscv64-unknown-elf-gcc "$@" -DNM_N=$n -DNM_M=$m -DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common \
  -fno-builtin-printf -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc -lm -lgcc -I"$T/riscv-tests" \
  -I"$T/riscv-tests/env" -I"$T" -I"$c" -DID_STRING= -DPRINT_TILE=0 -nostdlib -nostartfiles -static -T "$c/test.ld" -DBAREMETAL=1 \
  "$src" -o "$o" "$c/syscalls.c" "$c/crt.S" 2> "$o.cc.log" || { echo "compile failed, see $o.cc.log"; tail -5 "$o.cc.log"; exit 2; }
timeout 1800 spike --extlib="$lib" --extension=gemmini "$o" > "$S/smoke/$name.log" 2>&1; rc=$?
echo "$name rc=$rc"; grep -v "^Gemmini extension\|dim =\|n:m sparsity" "$S/smoke/$name.log" | tail -12
