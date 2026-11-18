#!/bin/bash
# mkjobs.sh <progs dir>: jobs list (chip binary seed timeout), long streaming jobs started early, tests next
P=$1
st() { for c in 24 48; do echo "nm$c $P/stream/${1}_${c}_keeperfixa-baremetal $2 $3"; echo "nm$c $P/stream/${1}_${c}_v1fixa-baremetal $2 $3"; done; }
for c in 24 48; do echo "nm$c $P/tests/nm_sparse_spad_$c-baremetal 1 20000000"; done
st bert_qkv 1 30000000
for s in 1 2 3; do for c in 24 48; do echo "nm$c $P/fair/fair_perf_$c-baremetal $s 150000000"; done; done
for c in 24 48; do
  for t in nm_sparse_debug nm_sparse_matmul nm_sparse_perf nm_sparse_protocol nm_sparse_sw; do echo "nm$c $P/tests/${t}_$c-baremetal 1 20000000"; done
  for n in 4 7 9 10 14; do echo "nm$c $P/tests/proto_neg${n}_$c-baremetal 1 20000000"; done
  for n in $(seq 21 37); do echo "nm$c $P/tests/spad_neg${n}_$c-baremetal 1 20000000"; done
done
for s in 2 3; do st bert_qkv $s 30000000; done
for s in 1 2 3; do st small $s 15000000; done
for s in 1 2 3; do st edge $s 15000000; done
