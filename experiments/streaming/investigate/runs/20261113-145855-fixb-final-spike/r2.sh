#!/bin/bash
# r2.sh <outdir>: round 2 of the sparse-loop-fix tests. builds nm_sparse_loop (+ every NEG) for 2:4 and 4:8 out of
# tree, runs them on the scratch Spike libs, then two mutant libs. nothing is installed; --extlib before --extension
set -uo pipefail
T="$(cd "$(dirname "$0")" && pwd)"; S="$(dirname "$T")"; O="$1"; B=$T/bareMetalC; LIBS=$S/libs
t=$HOME/chipyard/generators/gemmini/software/gemmini-rocc-tests; L=$HOME/chipyard/generators/gemmini/software/libgemmini
mkdir -p "$O"/{pos,neg,neg-dense,neg-nmlib,mutants} "$B"
NM_NEGS="10 11 20 30 40 50 51 52 60 61 70 71 72 73 74 80 90 91 100 120 121 122 130 131 132 133"; DENSE_NEGS="110 140"
# ---- build
rm -f "$B"/*-baremetal
{ for pm in "24 2 4" "48 4 8"; do set -- $pm
    bash $T/cc.sh $t/bareMetalC/nm_sparse_loop.c $B/nm_sparse_loop_$1-baremetal -DNM_N=$2 -DNM_M=$3 || echo "BUILDFAIL pos $1"
    for n in $NM_NEGS $DENSE_NEGS; do
      bash $T/cc.sh $t/bareMetalC/nm_sparse_loop.c $B/nm_sparse_loop_neg${n}_$1-baremetal -DNM_N=$2 -DNM_M=$3 -DNEG=$n || echo "BUILDFAIL NEG=$n $1"; done
  done; echo "built: $(ls $B | wc -l) programs"; } > "$O/build.log" 2>&1
set +u; source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh > /dev/null; set -u
export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
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
neg1() { # neg1 <n> <pat> <lib> <logdir> -> verdict line
  local n=$1 p=$2 lib=$3 d=$4 rc=0 log; mkdir -p "$d"; log=$d/nm_sparse_loop_neg${n}_$p.log
  timeout 300 spike --extlib="$lib" --extension=gemmini "$B/nm_sparse_loop_neg${n}_$p-baremetal" > "$log" 2>&1 || rc=$?
  if [ $rc -ne 0 ] && grep -qF "GEMMINI: $(msg "$n")" "$log"; then echo "pass NEG=$n $p rc=$rc expected text"
  elif [ $rc -eq 0 ]; then echo "NOTCAUGHT NEG=$n $p rc=0"
  else echo "WRONGTEXT NEG=$n $p rc=$rc: $(grep -m1 '^GEMMINI: [^w]' "$log")"; fi; }
pos1() { # pos1 <pat> <lib> <logdir> -> verdict line
  local p=$1 lib=$2 d=$3 rc=0 log; mkdir -p "$d"; log=$d/nm_sparse_loop_$p.log
  timeout 1800 spike --extlib="$lib" --extension=gemmini "$B/nm_sparse_loop_$p-baremetal" > "$log" 2>&1 || rc=$?
  echo "nm_sparse_loop_$p rc=$rc: $(grep -c ' ok (0/' "$log") cases ok, $(grep -c ' FAIL (' "$log") FAIL, pad_J cases ok $(grep -c '^pad_J:.* ok (0/' "$log") of $(grep -c '^pad_J:' "$log"), $(grep -c '^nm_sparse_loop passed$' "$log") passed line"; }
# ---- positive
for p in 24 48; do pos1 $p $LIBS/libgemmini-nm$p/libgemmini.so "$O/pos"; done > "$O/pos.summary"
# ---- NEG: n:m lib; N11 / N14 on the dense lib (and on the n:m lib, where they are legal and must run through)
{ for p in 24 48; do
    for n in $NM_NEGS; do neg1 $n $p $LIBS/libgemmini-nm$p/libgemmini.so "$O/neg"; done
    for n in $DENSE_NEGS; do echo "dense-lib: $(neg1 $n $p $LIBS/libgemmini-dense$p/libgemmini.so "$O/neg-dense")"
                              echo "nm-lib (legal there): $(neg1 $n $p $LIBS/libgemmini-nm$p/libgemmini.so "$O/neg-nmlib")"; done
  done; } > "$O/neg.summary"
# ---- mutants (copies of libgemmini in the run folder's scratch; the tree is not touched)
mk() { local name=$1 n=$2 m=$3; shift 3; local d=$S/mutants/$name; mkdir -p $d "$O/mutants/$name"; cp $L/gemmini.cc $L/gemmini.h $L/gemmini_params.h $d/
  sed -i "$@" $d/gemmini.cc; cmp -s $d/gemmini.cc $L/gemmini.cc && { echo "$name: SED CHANGED NOTHING"; return 1; }
  diff -u $L/gemmini.cc $d/gemmini.cc > "$O/mutants/$name/mutation.diff"
  (cd $d && g++ -L $RISCV/lib -Wl,-rpath,$RISCV/lib -shared -o libgemmini.so -std=c++17 -I $RISCV/include -fPIC -O3 -DNM_N=$n -DNM_M=$m gemmini.cc 2> "$O/mutants/$name/build.log") || { echo "$name: BUILD FAIL"; return 1; }; }
{ for pm in "24 2 4" "48 4 8"; do set -- $pm; p=$1
    # N13 with the range part taken out (start address only): 133 must get through, 130..132 must still abort
    name=n13-start-only-$p
    if mk $name $2 $3 's/if (base_row_addr + rows > (reg_t)BANK_NUM \* BANK_ROWS)/if (base_row_addr >= (reg_t)BANK_NUM * BANK_ROWS)/'; then
      for n in 130 131 132 133; do r="$(neg1 $n $p $S/mutants/$name/libgemmini.so "$O/mutants/$name")"
        case "$r" in pass*) echo "$name NEG=$n: mutant not seen ($r)";; *) echo "$name NEG=$n: KILLED ($r)";; esac; done; fi
    # pad_J ignored by the loop: the pad_J cases must fail
    name=pad-j-ignored-$p
    if mk $name $2 $3 's/const uint16_t pad_J = gemmini_state.loop_ws_pad_J;/const uint16_t pad_J = 0;/'; then
      r="$(pos1 $p $S/mutants/$name/libgemmini.so "$O/mutants/$name")"; log="$O/mutants/$name/nm_sparse_loop_$p.log"
      echo "$name: $([ "$(grep -c '^nm_sparse_loop passed$' "$log")" = 0 ] && echo KILLED || echo SURVIVED); pad_J cases FAIL $(grep -c '^pad_J:.* FAIL (' "$log") of $(grep -c '^pad_J:' "$log"); $r"; fi
  done; } > "$O/mutants.summary" 2>&1
echo done > "$O/STATUS"
