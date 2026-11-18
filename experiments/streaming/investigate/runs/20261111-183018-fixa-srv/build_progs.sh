#!/bin/bash
# build_progs.sh <out_dir>: Fix A tests + benchmarks for the 2:4 and 4:8 chips, compiled on the server against the
# gemmini_params.h each elaboration generated (~/fixa/hdr/<24|48>/include/gemmini_params.h, put first on the -I path;
# gemmini.h's #include "include/gemmini_params.h" resolves there). Flags = run-flow.sh rv_cc (gemmini-rocc-tests flags)
# + explicit -DNM_N/-DNM_M (gemmini_nm.h #errors if they disagree with GEMMINI_HW_NM_N/M). Streaming data headers are
# server copies of the laptop data.h with the .incbin path prefix rewritten (bin files sha256-identical to the laptop).
set -eo pipefail
out="$1"; [ -n "$out" ] && [ ! -e "$out" ] || { echo "usage: build_progs.sh <new out_dir>"; exit 2; }
source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh > /dev/null
cy=~/chipyard T=$cy/generators/gemmini/software/gemmini-rocc-tests PR=~/gemmini-sparsity ST=$PR/experiments/streaming
c=$T/riscv-tests/benchmarks/common
rv_pre=(-DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common -fno-builtin-printf
        -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc)
mkdir -p "$out"/{tests,fair,stream} "$out/data"
info="$out/build.info"
echo "built $(date -Iseconds) on $(hostname)" > "$info"
die() { echo "error: $*" | tee -a "$info" >&2; exit 1; }
cc1() {  # cc1 <pat> <src> <out> [flags...]
  local p="$1" src="$2" o="$3" n m H msgs rc=0 got; shift 3
  n=${p:0:1} m=${p:1:1} H=~/fixa/hdr/$p
  local inc=(-I"$H" -I"$T/riscv-tests" -I"$T/riscv-tests/env" -I"$T" -I"$c" -DID_STRING= -DPRINT_TILE=0)
  msgs="$(riscv64-unknown-elf-gcc "$@" -DNM_N=$n -DNM_M=$m "${rv_pre[@]}" -lm -lgcc "${inc[@]}" -nostdlib -nostartfiles \
    -static -T "$c/test.ld" -DBAREMETAL=1 "$src" -o "$o" "$c/syscalls.c" "$c/crt.S" 2>&1)" || rc=$?
  [ -z "$msgs" ] || grep -v RWX <<<"$msgs" >&2 || true
  [ $rc -eq 0 ] && [ -s "$o" ] || die "compile failed: $o"
  got="$(riscv64-unknown-elf-gcc "$@" -DNM_N=$n -DNM_M=$m "${rv_pre[@]}" "${inc[@]}" -DBAREMETAL=1 -dM -E "$src" |
    awk '$2=="NM_N"{n=$3} $2=="NM_M"{m=$3} $2=="GEMMINI_HW_NM_N"{hn=$3} $2=="GEMMINI_HW_NM_M"{hm=$3} $2=="NM_SPAD_ROWS_PER_TILE"{r=$3}
         $2=="GEMMINI_HW_NM_SPAD_ROWS_PER_TILE"{hr=$3} END{print n":"m" hw="hn":"hm" R="hr}')"
  echo "$(sha256sum "$o" | cut -c1-64)  ${o#$out/}  [$got] $*" >> "$info"
  case "$p:$got" in 24:"2:4 hw=2:4 R=4"|48:"4:8 hw=4:8 R=6") ;; *) rm -f "$o"; die "$o: pattern/header check got '$got'";; esac
}
for p in 24 48; do
  H=~/fixa/hdr/$p/include/gemmini_params.h; [ -f $H ] || die "missing $H"
  echo "header $p: $(sha256sum $H)" >> "$info"
  for t in nm_sparse_sw nm_sparse_debug nm_sparse_matmul nm_sparse_perf nm_sparse_protocol nm_sparse_spad; do
    cc1 $p $T/bareMetalC/$t.c "$out/tests/${t}_$p-baremetal"; done
  for n in 4 7 9 10 14; do cc1 $p $T/bareMetalC/nm_sparse_protocol.c "$out/tests/proto_neg${n}_$p-baremetal" -DNEG=$n; done
  for n in $(seq 21 37); do cc1 $p $T/bareMetalC/nm_sparse_spad.c "$out/tests/spad_neg${n}_$p-baremetal" -DNEG=$n; done
  cc1 $p $PR/verification/fair_perf.c "$out/fair/fair_perf_$p-baremetal"
  for L in edge small bert_qkv; do
    mkdir -p "$out/data/$L/$p"
    sed "s|/home/hunter/gemmini-sparsity/|$HOME/gemmini-sparsity/|g" $ST/build/data/$L/$p/data.h > "$out/data/$L/$p/data.h"
    for f in $(grep -o 'incbin \\"[^\\]*' "$out/data/$L/$p/data.h" | sed 's/incbin \\"//'); do [ -f "$f" ] || die "missing $f"; done
    D="$out/data/$L/$p/data.h"
    cc1 $p $ST/investigate/src/stream_bench.c "$out/stream/${L}_${p}_keeperfixa-baremetal" -I$ST/investigate/src \
      -DSBENCH_DATA="\"$D\"" -DUSE_KEEPER -DRUN_MASK=224
    cc1 $p $ST/src/stream_bench.c "$out/stream/${L}_${p}_v1fixa-baremetal" -DSBENCH_DATA="\"$D\"" -DRUN_MASK=12
  done
done
echo "OK $(grep -c baremetal "$info") programs" | tee -a "$info"
