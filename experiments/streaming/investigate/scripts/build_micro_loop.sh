#!/usr/bin/env bash
# build_micro_loop.sh <out_dir>: micro_loop.c (bank-split-fix-spec.md section 8) for 2:4 and 4:8.
# headers: a `git archive` snapshot of gemmini-rocc-tests include/ at the sparse-loop-fix commit (ROCC_REF, default
# 22158bf), so edits in the rocc-tests working tree do not leak in (include/ is searched first); rocc-software and
# riscv-tests (submodules) from the working tree.
# per pattern: <out>/data<nm>/ (gen_micro_loop.py), micro_loop_<nm>-baremetal (RTL: SHAPE_MASK 3),
#   micro_loop_<nm>_s1-baremetal (RTL S3: SHAPE_MASK 4), micro_loop_<nm>_ref-baremetal (Spike: + CPU_REF).
# the three differ only in volatile flags (.data); the script checks their .text sections are identical.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cy="${CHIPYARD_DIR:-$HOME/chipyard}"
tests_dir="$cy/generators/gemmini/software/gemmini-rocc-tests"
ref="${ROCC_REF:-22158bf}"
base="$(conda info --base 2>/dev/null || echo "$HOME/miniforge3")"
set +u
source "$base/etc/profile.d/conda.sh"; conda deactivate 2>/dev/null || true
source "$cy/env.sh" > /dev/null
set -u

rm -rf "$out/rt"; mkdir -p "$out/rt"
git -C "$tests_dir" archive "$ref" include | tar -x -C "$out/rt"
echo "headers: gemmini-rocc-tests $ref include/ -> $out/rt (gemmini_nm.h sha256 $(sha256sum "$out/rt/include/gemmini_nm.h" | cut -c1-16))"

rv_pre=(-DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common -fno-builtin-printf
        -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc)
rv_inc=(-I"$out/rt" -I"$tests_dir" -I"$tests_dir/riscv-tests" -I"$tests_dir/riscv-tests/env"
        -I"$tests_dir/riscv-tests/benchmarks/common" -DID_STRING= -DPRINT_TILE=0)
c="$tests_dir/riscv-tests/benchmarks/common"

for p in "24 2 4" "48 4 8"; do
  read -r nm n m <<<"$p"
  python3 -I "$here/src/gen_micro_loop.py" "$out/data$nm" "$n" "$m"
  for v in "micro_loop_$nm:-DSHAPE_MASK=3" "micro_loop_${nm}_s1:-DSHAPE_MASK=4" "micro_loop_${nm}_ref:-DSHAPE_MASK=3 -DCPU_REF"; do
    name="${v%%:*}"; flags="${v#*:}"; bin="$out/$name-baremetal"
    rm -f "$bin"
    # shellcheck disable=SC2086
    riscv64-unknown-elf-gcc $flags -DNM_N="$n" -DNM_M="$m" -DMICRO_LOOP_DATA="\"$out/data$nm/data.h\"" "${rv_pre[@]}" \
      -lm -lgcc "${rv_inc[@]}" -nostdlib -nostartfiles -static -T "$c/test.ld" -DBAREMETAL=1 \
      "$here/src/micro_loop.c" -o "$bin" "$c/syscalls.c" "$c/crt.S" 2>&1 | { grep -v RWX || true; }
    [ -s "$bin" ] || { echo "compile failed: $bin" >&2; exit 1; }
    riscv64-unknown-elf-objcopy -O binary -j .text "$bin" "$out/$name.text"
    echo "built $bin sha256 $(sha256sum "$bin" | cut -c1-16) text $(sha256sum "$out/$name.text" | cut -c1-16)"
  done
  for name in "micro_loop_${nm}_s1" "micro_loop_${nm}_ref"; do
    cmp -s "$out/micro_loop_$nm.text" "$out/$name.text" || { echo ".text of $name differs from micro_loop_$nm" >&2; exit 1; }
  done
done
echo "all built; .text identical within each pattern"
