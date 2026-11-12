#!/bin/bash
# cc.sh <pat 24|48> <layer> <out> [extra flags...]: laptop build of investigate/src/stream_bench.c with the server's
# flags (build_progs.sh) and the server-generated gemmini_params.h. SRC env overrides the source dir.
set -eo pipefail
S=/tmp/claude-1000/-home-hunter-gemmini-sparsity/02a1660a-afd8-4d63-b078-262a0414bff5/scratchpad/speedup
source /home/hunter/gemmini-fixwork/fixa/env.sh
p=$1 L=$2 o=$3; shift 3
n=${p:0:1} m=${p:1:1}
cy=/home/hunter/chipyard T=$cy/generators/gemmini/software/gemmini-rocc-tests ST=/home/hunter/gemmini-sparsity/experiments/streaming
SRC=${SRC:-$ST/investigate/src}
c=$T/riscv-tests/benchmarks/common
rv_pre=(-DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common -fno-builtin-printf
        -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc)
inc=(-I"$S/hdr/$p" -I"$T/riscv-tests" -I"$T/riscv-tests/env" -I"$T" -I"$c" -DID_STRING= -DPRINT_TILE=0)
riscv64-unknown-elf-gcc -I$SRC -DSBENCH_DATA="\"$ST/build/data/$L/$p/data.h\"" -DUSE_KEEPER "$@" -DNM_N=$n -DNM_M=$m "${rv_pre[@]}" -lm -lgcc "${inc[@]}" -nostdlib -nostartfiles \
    -static -T "$c/test.ld" -DBAREMETAL=1 $SRC/stream_bench.c -o "$o" "$c/syscalls.c" "$c/crt.S" 2>&1 | grep -v RWX || true
[ -s "$o" ]
