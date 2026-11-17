#!/usr/bin/env bash
# bench.sh <out_dir>: streaming-bench data + programs + Spike runs for 2:4, 4:8, 8:16 on the bank-split-fix libgemmini
# (SCRATCH build-scratch/banksplit). Copy of 20261117-115410-nm816-spike/bench816.sh, generalised to three patterns.
# data: gen_data.py with PATTERNS = {24, 48, 816} (same seeds; source not edited).
# programs per layer and pattern: _full (RUN_MASK=7: berkeley, dense_stream, sparse_stream), _fixa (8), _loop (16).
set -euo pipefail
here="$HOME/gemmini-sparsity/experiments/streaming"
cy="$HOME/chipyard"; tests_dir="$cy/generators/gemmini/software/gemmini-rocc-tests"
py="$cy/.conda-env/bin/python"; O="$1"; LIBDIR="${LIBDIR:-$HOME/gemmini-sparsity/build-scratch/banksplit}"
layers=(edge small bert_qkv bert_ffn1 bert_ffn2 rn50_conv)
pats=("24 2 4" "48 4 8" "816 8 16")
set +u; source "$HOME/miniforge3/etc/profile.d/conda.sh"; conda deactivate 2>/dev/null || true; source "$cy/env.sh" > /dev/null; set -u
export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p "$O/data" "$O/bin" "$O/logs"
"$py" -I -c "import sys; sys.path.insert(0, '$here/gen'); import gen_data as g; g.PATTERNS = {'24': (2, 4), '48': (4, 8), '816': (8, 16)}; sys.argv = ['gen_data.py', '$O/data']; g.main()" > "$O/gen_data.out"
rv_pre=(-DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common -fno-builtin-printf
        -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc)
rv_inc=(-I"$tests_dir/riscv-tests" -I"$tests_dir/riscv-tests/env" -I"$tests_dir"
        -I"$tests_dir/riscv-tests/benchmarks/common" -DID_STRING= -DPRINT_TILE=0)
c="$tests_dir/riscv-tests/benchmarks/common"
rv_cc() {  # rv_cc <out> <data.h> <n> <m> [flags...]
  local out="$1" data="$2" n="$3" m="$4" got; shift 4
  riscv64-unknown-elf-gcc "$@" -DNM_N="$n" -DNM_M="$m" -DSBENCH_DATA="\"$data\"" "${rv_pre[@]}" -lm -lgcc \
    "${rv_inc[@]}" -nostdlib -nostartfiles -static -T "$c/test.ld" -DBAREMETAL=1 "$here/src/stream_bench.c" -o "$out" \
    "$c/syscalls.c" "$c/crt.S" 2>&1 | { grep -v RWX || true; }
  [ -s "$out" ] || { echo "compile failed: $out"; exit 1; }
  got="$(riscv64-unknown-elf-gcc "$@" -DNM_N="$n" -DNM_M="$m" -DSBENCH_DATA="\"$data\"" "${rv_pre[@]}" "${rv_inc[@]}" \
    -DBAREMETAL=1 -dM -E "$here/src/stream_bench.c" | awk '$2=="NM_N"{n=$3} $2=="NM_M"{m=$3} END{print n ":" m}')"
  [ "$got" = "$n:$m" ] || { echo "$out compiles as '$got'"; exit 1; }
}
: > "$O/jobs.txt"
for pnm in "${pats[@]}"; do
  read -r p n m <<<"$pnm"
  for L in "${layers[@]}"; do
    d="$O/data/$L/$p/data.h"
    rv_cc "$O/bin/${L}_${p}_full-baremetal" "$d" "$n" "$m" -DRUN_MASK=7
    rv_cc "$O/bin/${L}_${p}_fixa-baremetal" "$d" "$n" "$m" -DRUN_MASK=8
    rv_cc "$O/bin/${L}_${p}_loop-baremetal" "$d" "$n" "$m" -DRUN_MASK=16
    for v in full fixa loop; do echo "$p $O/bin/${L}_${p}_${v}-baremetal" >> "$O/jobs.txt"; done
  done
done
run1() { local b rc=0; b=$(basename "$2" -baremetal); timeout 7200 spike --extlib="$LIBDIR/libgemmini-nm$1/libgemmini.so" --extension=gemmini "$2" > "$O/logs/$b.log" 2>&1 || rc=$?; echo "$b rc=$rc"; }
export -f run1; export O LIBDIR
xargs -P 6 -L 1 bash -c 'run1 "$@"' _ < "$O/jobs.txt" | sort > "$O/rc.txt"
while read -r p b; do
  nme=$(basename "$b" -baremetal); l="$O/logs/$nme.log"
  if grep -q "^$nme rc=0$" "$O/rc.txt" && grep -q '^sbench passed' "$l"; then echo "pass  $nme  $(grep '^sbench passed' "$l")"
  else echo "FAIL  $nme ($(grep "^$nme " "$O/rc.txt"))"; fi
done < "$O/jobs.txt" > "$O/summary.txt"
if grep -q '^FAIL' "$O/summary.txt"; then echo "STATUS: FAIL" > "$O/STATUS"; else echo "STATUS: PASS" > "$O/STATUS"; fi
cat "$O/STATUS"
