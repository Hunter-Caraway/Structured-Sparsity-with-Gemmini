#!/bin/bash
# regress.sh <tag> <lib24> <lib48>: 56 dense + nm_* (+NEG) on the given libgemmini builds; logs in $S/reg-<tag>/
set -euo pipefail
S="$(cd "$(dirname "$0")" && pwd)"; tag="$1" L24="$2" L48="$3"
set +u; source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh > /dev/null; set -u
export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
T=~/chipyard/generators/gemmini/software/gemmini-rocc-tests; c=$T/riscv-tests/benchmarks/common
bm=$S/tests/bareMetalC; X=$S/tests-extra; out=$S/reg-$tag; mkdir -p "$X" "$out/logs"
rv_pre=(-DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common -fno-builtin-printf
        -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc)
inc=(-I"$T/riscv-tests" -I"$T/riscv-tests/env" -I"$T" -I"$c" -DID_STRING= -DPRINT_TILE=0)
cc1() { local n=$1 m=$2 src=$3 o=$4; shift 4; [ -s "$o" ] && return 0
  riscv64-unknown-elf-gcc "$@" -DNM_N=$n -DNM_M=$m "${rv_pre[@]}" -lm -lgcc "${inc[@]}" -nostdlib -nostartfiles -static \
    -T "$c/test.ld" -DBAREMETAL=1 "$src" -o "$o" "$c/syscalls.c" "$c/crt.S" 2> "$o.cc.log" || { echo "compile failed $o"; exit 1; }; }
for p in "2 4 24" "4 8 48"; do set -- $p
  cc1 $1 $2 $T/bareMetalC/nm_sparse_spad.c $X/nm_sparse_spad_$3-baremetal
  for n in $(seq 21 37); do cc1 $1 $2 $T/bareMetalC/nm_sparse_spad.c $X/nm_sparse_spad_neg${n}_$3-baremetal -DNEG=$n; done
done
: > "$out/jobs.txt"
for t in "$bm"/*-baremetal "$X"/*-baremetal; do b=$(basename "$t" -baremetal)
  case "$b" in *_48|*_48_*) lib=$L48;; *) lib=$L24;; esac
  echo "$b $t $lib" >> "$out/jobs.txt"; done
run1() { local b=$1 t=$2 lib=$3 rc=0
  timeout 1800 spike --extlib="$lib" --extension=gemmini "$t" > "$out/logs/$b.log" 2>&1 || rc=$?
  local msg; msg="$(grep -m1 '^GEMMINI: [^w]' "$out/logs/$b.log" || true)"
  case "$b" in
    *_neg[0-9]*) if [ $rc -ne 0 ] && [ -n "$msg" ]; then echo "pass $b rc=$rc $msg"; else echo "FAIL $b rc=$rc (NEG not caught)"; fi;;
    *) if [ $rc -eq 0 ]; then echo "pass $b rc=0"; else echo "FAIL $b rc=$rc $msg"; fi;;
  esac; }
export -f run1; export out
xargs -P 10 -L 1 bash -c 'run1 "$@"' _ < "$out/jobs.txt" | sort > "$out/summary.txt"
echo "$tag: $(grep -c '^pass' "$out/summary.txt") pass, $(grep -c '^FAIL' "$out/summary.txt" || true) FAIL of $(wc -l < "$out/jobs.txt")"
