#!/bin/bash
# t2.sh: tests agent's nm_sparse_loop NEG builds, mutants and benches on the scratch libs; output in $S/t2/
set -uo pipefail
S="$(cd "$(dirname "$0")" && pwd)"; T="$1"; O=$S/t2; B=$T/tests/bareMetalC
set +u; source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh > /dev/null; set -u
export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
L=~/chipyard/generators/gemmini/software/libgemmini
msg() { case "$(($1 / 10))" in
    1) echo "sparse-loop-fix: LOOP_WS nm flag (rs1[3]) differs from n:m sparse mode (config_ex rs1[10])" ;;
    2) echo "sparse-loop-fix: LOOP_CONV_WS issued while n:m sparse mode (config_ex rs1[10]) is on" ;;
    3) echo "sparse-loop-fix: LOOP_WS with rs1[3] set needs LOOP_WS_CONFIG_NM (funct 28) first" ;;
    4) echo "sparse-loop-fix: LOOP_WS_CONFIG_NM (funct 28) without LOOP_WS rs1[3]" ;;
    5) echo "sparse-loop-fix: LOOP_WS_CONFIG_NM needs a non-zero 16-byte aligned rs1 and rs2 == 0" ;;
    6) echo "sparse-loop-fix: sparse loop needs an even K tile count and pad_K == 0 (K % 2*DIM)" ;;
    7) echo "sparse-loop-fix: sparse loop does not support transposes, resadd, low_D or spad-only" ;;
    8) echo "sparse-loop-fix: sparse loop needs A_stride == 1" ;;
    9) echo "sparse-loop-fix: A, B and index regions do not fit in the loop's scratchpad half (or index region exceeds one bank)" ;;
    10) echo "sparse-loop-fix: sparse loop started with index tiles pending in the FIFO: gemmini_nm_reset() first" ;;
    11) echo "sparse-loop-fix: LOAD_IDX (funct 27) on a dense build (nm_sparsity = None)" ;;
    12) echo "sparse-loop-fix: LOAD_IDX needs cols == 16 and 1..16 rows" ;;
    13) echo "sparse-loop-fix: LOAD_IDX destination must be a scratchpad row address" ;;
    14) echo "sparse-loop-fix: LOOP_WS_CONFIG_NM (funct 28) on a dense build (nm_sparsity = None)" ;; esac; }  # copy of run-flow.sh loop_neg_msg
neg1() { # neg1 <n> <pat> <lib> <logdir> -> prints verdict
  local n=$1 p=$2 lib=$3 d=$4 rc=0 log; mkdir -p "$d"; log=$d/nm_sparse_loop_neg${n}_$p.log
  timeout 300 spike --extlib="$lib" --extension=gemmini "$B/nm_sparse_loop_neg${n}_$p-baremetal" > "$log" 2>&1 || rc=$?
  if [ $rc -ne 0 ] && grep -qF "GEMMINI: $(msg "$n")" "$log"; then echo "pass NEG=$n $p rc=$rc expected text"
  elif [ $rc -eq 0 ]; then echo "NOTCAUGHT NEG=$n $p rc=0"
  else echo "WRONGTEXT NEG=$n $p rc=$rc: $(grep -m1 '^GEMMINI: [^w]' "$log")"; fi; }
{ for p in 24 48; do
    for n in 10 11 20 30 40 50 51 52 60 61 70 71 72 73 74 80 90 91 100 120 121 122 130 131 132; do neg1 $n $p $S/libgemmini-nm$p/libgemmini.so $O/neg; done
    for n in 110 140; do echo "dense-lib: $(neg1 $n $p $S/libgemmini-dense$p/libgemmini.so $O/neg-dense)"; echo "nm-lib:    $(neg1 $n $p $S/libgemmini-nm$p/libgemmini.so $O/neg-nmlib)"; done
  done; } > $O/neg.summary
# mutants: positive test must fail (m1-m6); per-assert mutants: the assert's NEG must no longer show its text
mk() { local name=$1 n=$2 m=$3 extra=$4; shift 4; local d=$O/mutants/$name; mkdir -p $d; cp $L/gemmini.cc $L/gemmini.h $L/gemmini_params.h $d/
  sed -i "$@" $d/gemmini.cc; cmp -s $d/gemmini.cc $L/gemmini.cc && { echo "$name: SED CHANGED NOTHING"; return 1; }
  (cd $d && g++ -L $RISCV/lib -Wl,-rpath,$RISCV/lib -shared -o libgemmini.so -std=c++17 -I $RISCV/include -fPIC -O3 -DNM_N=$n -DNM_M=$m $extra gemmini.cc 2> build.log) || { echo "$name: BUILD FAIL"; return 1; }; }
pos() { local name=$1 p=$2 d=$O/mutants/$1 rc=0
  timeout 900 spike --extlib=$d/libgemmini.so --extension=gemmini $B/nm_sparse_loop_$p-baremetal > $d/nm_sparse_loop_$p.log 2>&1 || rc=$?
  echo "$name nm_sparse_loop_$p rc=$rc: $([ $rc -ne 0 ] && echo KILLED || echo SURVIVED); $(grep -c ' FAIL ' $d/nm_sparse_loop_$p.log) cases FAIL; $(grep -m1 '^GEMMINI: [^w]' $d/nm_sparse_loop_$p.log)"; }
{ for pm in "24 2 4" "48 4 8"; do set -- $pm; p=$1 n=$2 m=$3
  mk m1-ahi-base-$p $n $m "" 's/nm ? (A_rows << 48) | ((uint64_t)DIM << 32) | (A_sp_addr + DIM) :/nm ? (A_rows << 48) | ((uint64_t)DIM << 32) | (A_sp_addr) :/' && pos m1-ahi-base-$p $p
  mk m2-idx-stride32-$p $n $m "" 's/dram_addr + row\*16 + col/dram_addr + row*32 + col/' && pos m2-idx-stride32-$p $p
  mk m3-stc-k-not-halved-$p $n $m "" 's/loop_ws_C != 0 \&\& k == KB-1/loop_ws_C != 0 \&\& k == K-1/' && pos m3-stc-k-not-halved-$p $p
  mk m4-idx-over-b-$p $n $m "" 's/(BANK_NUM \* BANK_ROWS \/ 2) - KB \* J \* DIM - nm_idx_rows;/(BANK_NUM * BANK_ROWS \/ 2) - KB * J * DIM - nm_idx_rows + nm_R;/' && pos m4-idx-over-b-$p $p
  mk m5-no-budget-gate-$p $n $m "" 's/nm_loaded - ((size_t)k\*J + j + 1) <= 2)/true)/' && pos m5-no-budget-gate-$p $p
  mk m6-nm-flag-not-latched-$p $n $m "" 's/const bool nm = (rs1 >> 3) \& 1;/const bool nm = false;/' && pos m6-nm-flag-not-latched-$p $p
  mk m7-idx-rows-8-$p $n $m "" 's/const size_t nm_R = nm_spad_rows_per_tile;/const size_t nm_R = 8;/' && pos m7-idx-rows-8-$p $p
  mk m8-load-idx-uses-id2-stride-$p $n $m "" 's/dram_addr + row\*16 + col/dram_addr + row*gemmini_state.load_strides[2] + col/' && pos m8-load-idx-uses-id2-stride-$p $p
  done
  # one mutant per assert on 2:4: the check removed; its NEG must then not be a pass
  for a in "1 10" "1 11" "2 20" "3 30" "4 40" "5 50" "6 60" "6 61" "7 70" "8 80" "9 90" "10 100" "11 110" "12 120" "13 130" "14 140"; do set -- $a; N=$1 neg=$2
    name=a-N$N-removed; extra=""; case $N in 11|14) extra=-DNM_DENSE_BUILD;; esac
    if [ ! -f $O/mutants/$name/libgemmini.so ]; then
      if [ $N = 2 ]; then mk $name 2 4 "" 's/^  if (st.nm_sparse) {$/  if (false) {/' || continue
      else t="$(msg ${N}0 | sed 's/^sparse-loop-fix: //; s/[][*.^$\\\/]/\\&/g')"; mk $name 2 4 "$extra" "s/nm_loop_abort(\"$t\");/(void)0;/" || continue; fi; fi
    r="$(neg1 $neg 24 $O/mutants/$name/libgemmini.so $O/mutants/$name)"; case "$r" in pass*) echo "$name NEG=$neg: SURVIVED ($r)";; *) echo "$name NEG=$neg: KILLED ($r)";; esac
  done; } > $O/mutants.summary 2>&1
echo done > $O/STATUS-negmut
