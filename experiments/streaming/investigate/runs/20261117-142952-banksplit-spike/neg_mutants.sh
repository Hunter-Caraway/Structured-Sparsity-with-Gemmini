#!/usr/bin/env bash
# neg_mutants.sh <run> <mutant lib dir>: NEG 92 build (run-flow rv_cc flags), NEG 90/91/92 on nm and dense libs, then the
# Spike mutant matrix (nm_sparse_loop, NEG 90/92 per pattern, fair_perf_24) -> <run>/neg, <run>/mutant
set -euo pipefail
R="$1"; MD="$2"; S=/home/hunter/gemmini-sparsity/build-scratch/banksplit; B=$S/tests/bareMetalC
T=$HOME/chipyard/generators/gemmini/software/gemmini-rocc-tests; c=$T/riscv-tests/benchmarks/common
set +u; source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh >/dev/null 2>&1; set -u
N9MSG="sparse-loop-fix: A, B and index regions do not fit in the loop's scratchpad half (or index region exceeds one bank); bank-split-fix: even and odd A K tiles need one bank each"
mkdir -p "$R/neg" "$R/mutant"; : > "$R/neg/summary.txt"
for pnm in "24 2 4" "48 4 8" "816 8 16"; do
  read -r p n m <<<"$pnm"; out=$B/nm_sparse_loop_neg92_$p-baremetal
  riscv64-unknown-elf-gcc -DNEG=92 -DNM_N=$n -DNM_M=$m -DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math \
    -fno-common -fno-builtin-printf -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc -lm -lgcc -I$T/riscv-tests \
    -I$T/riscv-tests/env -I$T -I$c -DID_STRING= -DPRINT_TILE=0 -nostdlib -nostartfiles -static -T $c/test.ld -DBAREMETAL=1 \
    $T/bareMetalC/nm_sparse_loop.c -o $out $c/syscalls.c $c/crt.S 2>&1 | { grep -v RWX || true; }
  [ -s "$out" ] || { echo "compile failed $out"; exit 1; }
  for x in "92 nm" "92 dense" "90 nm" "91 nm"; do
    read -r k lib <<<"$x"; lg=$R/neg/neg${k}_${p}_$lib$p.log; rc=0
    timeout 120 spike --extlib=$S/libgemmini-$lib$p/libgemmini.so --extension=gemmini $B/nm_sparse_loop_neg${k}_$p-baremetal > $lg 2>&1 || rc=$?
    echo "NEG $k $lib$p rc=$rc $(grep -m1 '^GEMMINI:' $lg || echo 'no GEMMINI abort')" >> "$R/neg/summary.txt"
  done
done
out=$R/mutant/summary.txt; : > $out
for mu in m1 m2 m3 m4 m5; do for p in 24 48 816; do
  lib=$MD/$mu/nm$p/libgemmini.so; lg=$R/mutant/$mu.nm$p.log; : > $lg; rc=0
  timeout 600 spike --extlib=$lib --extension=gemmini $B/nm_sparse_loop_$p-baremetal >> $lg 2>&1 || rc=$?
  bad=$(grep -c " FAIL (" $lg || true); bs3=$(grep -c "bank-split-fix: internal" $lg || true); newfail=$(grep -c "^bank: .* FAIL" $lg || true)
  echo "$mu nm$p nm_sparse_loop rc=$rc failing_cases=$bad new_bank_cases_failing=$newfail bs3_abort=$bs3 -> $([ $rc -ne 0 ] && echo DETECTED || echo MISSED)" >> $out
  for k in 90 92; do rc=0; o="$(timeout 120 spike --extlib=$lib --extension=gemmini $B/nm_sparse_loop_neg${k}_$p-baremetal 2>&1)" || rc=$?; echo "$o" >> $lg
    if [ $rc -ne 0 ] && grep -qF -- "$N9MSG" <<<"$o"; then r="aborts with N9 text (NEG passes)"; else r="NEG FAILS (rc=$rc, no N9 text) -> DETECTED"; fi
    echo "$mu nm$p NEG $k: $r" >> $out; done
done; done
for mu in m1 m2 m3 m4 m5; do lg=$R/mutant/$mu.fair24.log; rc=0
  timeout 600 spike --extlib=$MD/$mu/nm24/libgemmini.so --extension=gemmini $S/fair/fair_perf_24-baremetal > $lg 2>&1 || rc=$?
  echo "$mu nm24 fair_perf_24 rc=$rc sparse_loop_verified=$(grep -c '^sparse_loop matches the cpu reference' $lg || true)" >> $out; done
