#!/usr/bin/env bash
# q3_dense_icount.sh <out_dir> [layer ...]: Spike instruction count of Berkeley's dense tiled_matmul_auto per layer.
# Builds, all inside <out_dir> (never $RISCV, never the Berkeley trees):
#   lib-stock/libgemmini.so   Berkeley's Spike model at the base commit (git show, read-only), stock Makefile command
#   bin/q3_<layer>-baremetal  src/q3_dense_icount.c with the layer's 2:4 data header (A and dense W are used)
# Q3_CONST_ONLY=1 builds with -DQ3_CONST_ONLY (only the constant-dimension call; see the source).
# Runs each on Spike (--extlib before --extension, see worklogs/spike-meta-rd.md) -> logs/<layer>.log, then
# XCHECK_LAYERS (default: the same layers) again with `spike -l`, piped to tools/q3_trace_count.py, which stops Spike
# after the first counted region (dense_icount) -> logs/<layer>.trace.txt. Fails on any missing, failed or unverified log.
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: $0 <out_dir> [layer ...]" >&2; exit 2; }
out="$(mkdir -p "$1" && cd "$1" && pwd)"; shift
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cy="${CHIPYARD_DIR:-$HOME/chipyard}"
sw="$cy/generators/gemmini/software"
tests_dir="$sw/gemmini-rocc-tests"
lib_base="${LIBGEMMINI_BASE:-ea8f7ed}"      # Berkeley base of libgemmini (AGENTS.md)
tests_base="${TESTS_BASE:-7c540b3}"         # Berkeley base of gemmini-rocc-tests
layers=("$@"); [ ${#layers[@]} -gt 0 ] || layers=(edge small bert_qkv rn50_conv bert_ffn1 bert_ffn2)
extra=(); [ "${Q3_CONST_ONLY:-0}" = 1 ] && extra=(-DQ3_CONST_ONLY)
read -r -a xcheck <<<"${XCHECK_LAYERS-${layers[*]}}"

set +u
base="$(conda info --base 2>/dev/null || echo "$HOME/miniforge3")"
# shellcheck disable=SC1091
source "$base/etc/profile.d/conda.sh"; conda deactivate 2>/dev/null || true
# shellcheck disable=SC1091
source "$cy/env.sh" > /dev/null
set -u
export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
die() { echo "error: $*" >&2; exit 1; }
sha() { sha256sum "$1" | cut -d' ' -f1; }

# the headers the program compiles against must be Berkeley's (byte-identical to the base commit)
for h in gemmini_params.h gemmini.h gemmini_testutils.h; do
  git -C "$tests_dir" show "$tests_base:include/$h" | cmp -s - "$tests_dir/include/$h" || die "include/$h differs from $tests_base"
done

lib="$out/lib-stock"; mkdir -p "$lib" "$out/bin" "$out/logs"
for f in gemmini.cc gemmini.h gemmini_params.h; do git -C "$sw/libgemmini" show "$lib_base:$f" > "$lib/$f"; done
cmp -s "$lib/gemmini_params.h" "$tests_dir/include/gemmini_params.h" || die "model and test gemmini_params.h differ"
# the g++ command of Berkeley's Makefile at $lib_base
g++ -L "$RISCV/lib" -Wl,-rpath,"$RISCV/lib" -shared -o "$lib/libgemmini.so" -std=c++17 -I "$RISCV/include" -fPIC -O3 \
  "$lib/gemmini.cc" > "$lib/build.log" 2>&1 || { tail "$lib/build.log" >&2; die "libgemmini build failed"; }
inst_before="$(sha "$RISCV/lib/libgemmini.so")"

rv_pre=(-DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common -fno-builtin-printf
        -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc)
rv_inc=(-I"$tests_dir/riscv-tests" -I"$tests_dir/riscv-tests/env" -I"$tests_dir"
        -I"$tests_dir/riscv-tests/benchmarks/common" -DID_STRING= -DPRINT_TILE=0)
c="$tests_dir/riscv-tests/benchmarks/common"

info="$out/run.info"
{
  echo "q3 dense instruction count, $(date '+%Y-%m-%d %H:%M:%S %Z'), host $(uname -n)"
  echo "spike: $(command -v spike) sha256 $(sha "$(command -v spike)")"
  echo "lib (stock, libgemmini $lib_base, built here): $lib/libgemmini.so sha256 $(sha "$lib/libgemmini.so")"
  echo "lib source gemmini.cc sha256 $(sha "$lib/gemmini.cc")"
  echo "installed lib (not used): $RISCV/lib/libgemmini.so sha256 $inst_before"
  echo "gemmini_params.h: $tests_dir/include/gemmini_params.h sha256 $(sha "$tests_dir/include/gemmini_params.h") (== $tests_base)"
  echo "gemmini.h sha256 $(sha "$tests_dir/include/gemmini.h"), gemmini_testutils.h sha256 $(sha "$tests_dir/include/gemmini_testutils.h") (== $tests_base)"
  echo "source: $here/src/q3_dense_icount.c sha256 $(sha "$here/src/q3_dense_icount.c")"
  echo "gcc: $(riscv64-unknown-elf-gcc --version | head -1)"
  echo "compile: riscv64-unknown-elf-gcc ${extra[*]} -DSBENCH_DATA=<data.h> ${rv_pre[*]} -lm -lgcc ${rv_inc[*]} -nostdlib -nostartfiles -static -T $c/test.ld -DBAREMETAL=1 q3_dense_icount.c syscalls.c crt.S"
} > "$info"

for L in "${layers[@]}"; do
  data="$here/build/data/$L/24/data.h"; [ -f "$data" ] || die "missing $data (run scripts/build.sh $L)"
  bin="$out/bin/q3_$L-baremetal"; log="$out/logs/$L.log"; rm -f "$bin" "$log"
  msgs="$(riscv64-unknown-elf-gcc "${extra[@]}" -DSBENCH_DATA="\"$data\"" "${rv_pre[@]}" -lm -lgcc "${rv_inc[@]}" -nostdlib \
    -nostartfiles -static -T "$c/test.ld" -DBAREMETAL=1 "$here/src/q3_dense_icount.c" -o "$bin" "$c/syscalls.c" "$c/crt.S" 2>&1)" \
    || { echo "$msgs" >&2; die "compile failed: $L"; }
  [ -s "$bin" ] || die "no binary: $bin"
  cmd=(spike --extlib="$lib/libgemmini.so" --extension=gemmini "$bin")
  rc=0; timeout "${SPIKE_TIMEOUT:-3600}" "${cmd[@]}" > "$log" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] || { tail -5 "$log" >&2; die "$L: spike exit $rc ($log)"; }
  grep -q '^q3 passed$' "$log" || die "$L: no 'q3 passed' in $log"
  grep -q '^q3 dense_icount: .* verified$' "$log" || die "$L: dense_icount not verified in $log"
  [ ${#extra[@]} -gt 0 ] || grep -q '^q3 dense_icount_rt: .* verified$' "$log" || die "$L: dense_icount_rt not verified in $log"
  {
    echo "layer $L: binary $bin sha256 $(sha "$bin"); data.h sha256 $(sha "$data")"
    echo "  cmd: ${cmd[*]} > $log 2>&1   (exit $rc)"
  } >> "$info"
  grep -n '^q3 dense_icount' "$log" | sed "s|^|$L.log:|"
done

for L in "${xcheck[@]}"; do
  [ -n "$L" ] || continue
  bin="$out/bin/q3_$L-baremetal"; [ -s "$bin" ] || die "xcheck: no binary for $L"
  tr="$out/logs/$L.trace.txt"; rm -f "$tr"
  cmd=(spike -l --extlib="$lib/libgemmini.so" --extension=gemmini "$bin")
  # the parser exits after the region; Spike then dies on the closed pipe, which is expected (hence || true)
  { timeout "${SPIKE_TIMEOUT:-3600}" "${cmd[@]}" 2>&1 || true; } | python3 "$here/tools/q3_trace_count.py" "$out/logs/$L.log" > "$tr" \
    || { cat "$tr" >&2; die "$L: trace cross-check failed ($tr)"; }
  echo "  xcheck $L cmd: ${cmd[*]} 2>&1 | python3 $here/tools/q3_trace_count.py $out/logs/$L.log > $tr" >> "$info"
  sed "s|^|$L.trace.txt: |" "$tr"
done

[ "$(sha "$RISCV/lib/libgemmini.so")" = "$inst_before" ] || die "installed libgemmini.so changed"
(cd "$out" && sha256sum run.info logs/* bin/* lib-stock/libgemmini.so lib-stock/gemmini.cc > SHA256SUMS)
echo "done: $out"
