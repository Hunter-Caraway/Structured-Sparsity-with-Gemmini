#!/usr/bin/env bash
# build.sh [layer ...]: data (if missing) + bare-metal programs for every layer, into build/bin/<layer>/
#   <layer>_24_full    2:4 data, berkeley + dense_stream + sparse_stream   (run on the 2:4 chip)
#   <layer>_24_dense   2:4 data, -DDENSE_ONLY, berkeley + dense_stream     (run on Berkeley's stock chip)
#   <layer>_24_sparse  2:4 data, sparse_stream only
#   <layer>_24_ds      2:4 data, dense_stream + sparse_stream               (2:4 chip, big layers)
#   <layer>_48_full    4:8 data, all three                                  (run on the 4:8 chip)
#   <layer>_48_sparse  4:8 data, sparse_stream only
# the _24_* programs differ only in two volatile .sdata flags: their .text is checked byte-identical.
# compile flags = run-flow.sh's rv_cc (the gemmini-rocc-tests flags), with explicit -DNM_N/-DNM_M, checked via -dM -E.
set -eo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cy="${CHIPYARD_DIR:-$HOME/chipyard}"
tests_dir="$cy/generators/gemmini/software/gemmini-rocc-tests"
py="${PYTHON:-$cy/.conda-env/bin/python}"
layers=("${@:-small bert_qkv bert_ffn1 bert_ffn2 rn50_conv edge}")
# shellcheck disable=SC2206
layers=(${layers[*]})

base="$(conda info --base 2>/dev/null || echo "$HOME/miniforge3")"
# shellcheck disable=SC1091
source "$base/etc/profile.d/conda.sh"; conda deactivate 2>/dev/null || true
# shellcheck disable=SC1091
source "$cy/env.sh" > /dev/null

rv_pre=(-DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common -fno-builtin-printf
        -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc)
rv_inc=(-I"$tests_dir/riscv-tests" -I"$tests_dir/riscv-tests/env" -I"$tests_dir"
        -I"$tests_dir/riscv-tests/benchmarks/common" -DID_STRING= -DPRINT_TILE=0)
c="$tests_dir/riscv-tests/benchmarks/common"

die() { echo "error: $*" >&2; exit 1; }
rv_cc() {  # rv_cc <out> <n> <m> <data.h> [flags...]
  local out="$1" n="$2" m="$3" data="$4" msgs rc=0 got; shift 4
  rm -f "$out"
  msgs="$(riscv64-unknown-elf-gcc "$@" -DNM_N="$n" -DNM_M="$m" -DSBENCH_DATA="\"$data\"" "${rv_pre[@]}" -lm -lgcc \
    "${rv_inc[@]}" -nostdlib -nostartfiles -static -T "$c/test.ld" -DBAREMETAL=1 "$here/src/stream_bench.c" -o "$out" \
    "$c/syscalls.c" "$c/crt.S" 2>&1)" || rc=$?
  [ -z "$msgs" ] || grep -v RWX <<<"$msgs" >&2 || true
  [ "$rc" -eq 0 ] && [ -s "$out" ] || die "compile failed (gcc exit $rc): $out"
  got="$(riscv64-unknown-elf-gcc "$@" -DNM_N="$n" -DNM_M="$m" -DSBENCH_DATA="\"$data\"" "${rv_pre[@]}" "${rv_inc[@]}" \
    -DBAREMETAL=1 -dM -E "$here/src/stream_bench.c" | awk '$2=="NM_N"{n=$3} $2=="NM_M"{m=$3} END{print n ":" m}')"
  [ "$got" = "$n:$m" ] || { rm -f "$out"; die "$out meant to be $n:$m but compiles as '$got'"; }
}
text_sha() { local t; t="$(mktemp)"; riscv64-unknown-elf-objcopy -O binary -j .text "$1" "$t"; sha256sum "$t" | cut -c1-16; rm -f "$t"; }

for L in "${layers[@]}"; do
  [ -f "$here/build/data/$L/24/data.h" ] && [ -f "$here/build/data/$L/48/data.h" ] || "$py" "$here/gen/gen_data.py" "$here/build/data" "$L"
  out="${BIN_DIR:-$here/build/bin}/$L"; mkdir -p "$out"
  d24="$here/build/data/$L/24/data.h" d48="$here/build/data/$L/48/data.h"
  rv_cc "$out/${L}_24_full-baremetal"   2 4 "$d24" -DRUN_MASK=7
  rv_cc "$out/${L}_24_dense-baremetal"  2 4 "$d24" -DRUN_MASK=3 -DDENSE_ONLY
  rv_cc "$out/${L}_24_sparse-baremetal" 2 4 "$d24" -DRUN_MASK=4
  rv_cc "$out/${L}_24_ds-baremetal"     2 4 "$d24" -DRUN_MASK=6
  rv_cc "$out/${L}_48_full-baremetal"   4 8 "$d48" -DRUN_MASK=7
  rv_cc "$out/${L}_48_sparse-baremetal" 4 8 "$d48" -DRUN_MASK=4
  a="$(text_sha "$out/${L}_24_full-baremetal")"; b="$(text_sha "$out/${L}_24_dense-baremetal")"; s="$(text_sha "$out/${L}_24_sparse-baremetal")"; t="$(text_sha "$out/${L}_24_ds-baremetal")"
  [ "$a" = "$b" ] && [ "$a" = "$s" ] && [ "$a" = "$t" ] || die "$L: .text differs between the _24 builds ($a / $b / $s)"
  echo "$L: built 6 programs; _24_full/_24_dense/_24_sparse/_24_ds .text identical (sha256 $a); _48 .text $(text_sha "$out/${L}_48_full-baremetal")"
done
