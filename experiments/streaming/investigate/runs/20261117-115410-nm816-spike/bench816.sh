#!/usr/bin/env bash
# bench816.sh <out_dir>: 8:16 streaming-bench data + programs + Spike runs (nm816 libgemmini from build-scratch).
# data: gen_data.py with PATTERNS overridden to {"816": (8, 16)} (same seeds as 2:4 / 4:8; source not edited).
# compile flags: copy of experiments/streaming/scripts/build.sh rv_cc (explicit -DNM_N/-DNM_M, checked via -dM -E).
# programs per layer: _816_full (RUN_MASK=7: berkeley, dense_stream, sparse_stream), _816_fixa (8), _816_loop (16).
set -euo pipefail
here="$HOME/gemmini-sparsity/experiments/streaming"
cy="$HOME/chipyard"; tests_dir="$cy/generators/gemmini/software/gemmini-rocc-tests"
py="$cy/.conda-env/bin/python"; O="$1"; LIB="${LIB:-$HOME/gemmini-sparsity/build-scratch/libgemmini-nm816/libgemmini.so}"
layers=(edge small bert_qkv bert_ffn1 bert_ffn2 rn50_conv)
set +u; source "$HOME/miniforge3/etc/profile.d/conda.sh"; conda deactivate 2>/dev/null || true; source "$cy/env.sh" > /dev/null; set -u
export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p "$O/data" "$O/bin" "$O/logs"
"$py" -I -c "import sys; sys.path.insert(0, '$here/gen'); import gen_data as g; g.PATTERNS = {'816': (8, 16)}; sys.argv = ['gen_data.py', '$O/data']; g.main()" | tee "$O/gen_data.out"
rv_pre=(-DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common -fno-builtin-printf
        -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc)
rv_inc=(-I"$tests_dir/riscv-tests" -I"$tests_dir/riscv-tests/env" -I"$tests_dir"
        -I"$tests_dir/riscv-tests/benchmarks/common" -DID_STRING= -DPRINT_TILE=0)
c="$tests_dir/riscv-tests/benchmarks/common"
rv_cc() {  # rv_cc <out> <data.h> [flags...]
  local out="$1" data="$2" got; shift 2
  riscv64-unknown-elf-gcc "$@" -DNM_N=8 -DNM_M=16 -DSBENCH_DATA="\"$data\"" "${rv_pre[@]}" -lm -lgcc \
    "${rv_inc[@]}" -nostdlib -nostartfiles -static -T "$c/test.ld" -DBAREMETAL=1 "$here/src/stream_bench.c" -o "$out" \
    "$c/syscalls.c" "$c/crt.S" 2>&1 | { grep -v RWX || true; }
  [ -s "$out" ] || { echo "compile failed: $out"; exit 1; }
  got="$(riscv64-unknown-elf-gcc "$@" -DNM_N=8 -DNM_M=16 -DSBENCH_DATA="\"$data\"" "${rv_pre[@]}" "${rv_inc[@]}" \
    -DBAREMETAL=1 -dM -E "$here/src/stream_bench.c" | awk '$2=="NM_N"{n=$3} $2=="NM_M"{m=$3} END{print n ":" m}')"
  [ "$got" = "8:16" ] || { echo "$out compiles as '$got'"; exit 1; }
}
: > "$O/jobs.txt"
for L in "${layers[@]}"; do
  d="$O/data/$L/816/data.h"
  rv_cc "$O/bin/${L}_816_full-baremetal" "$d" -DRUN_MASK=7
  rv_cc "$O/bin/${L}_816_fixa-baremetal" "$d" -DRUN_MASK=8
  rv_cc "$O/bin/${L}_816_loop-baremetal" "$d" -DRUN_MASK=16
  for v in full fixa loop; do echo "$O/bin/${L}_816_${v}-baremetal" >> "$O/jobs.txt"; done
done
run1() { local b rc=0; b=$(basename "$1" -baremetal); timeout 7200 spike --extlib="$LIB" --extension=gemmini "$1" > "$O/logs/$b.log" 2>&1 || rc=$?; echo "$b rc=$rc"; }
export -f run1; export O LIB
xargs -P 6 -L 1 bash -c 'run1 "$@"' _ < "$O/jobs.txt" | sort > "$O/rc.txt"
fails=0
while read -r b; do
  n=$(basename "$b" -baremetal); l="$O/logs/$n.log"
  if grep -q "^$n rc=0$" "$O/rc.txt" && grep -q '^sbench passed' "$l"; then echo "pass  $n  $(grep '^sbench passed' "$l")"
  else echo "FAIL  $n ($(grep "^$n " "$O/rc.txt"))"; fails=$((fails + 1)); fi
done < "$O/jobs.txt" | tee "$O/summary.txt"
grep -q '^FAIL' "$O/summary.txt" && echo "STATUS: FAIL" > "$O/STATUS" || echo "STATUS: PASS" > "$O/STATUS"
cat "$O/STATUS"
