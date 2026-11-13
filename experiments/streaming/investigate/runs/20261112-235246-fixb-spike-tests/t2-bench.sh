#!/bin/bash
set -uo pipefail
S="$(cd "$(dirname "$0")" && pwd)"; T="$1"; O=$S/t2/bench; mkdir -p $O
set +u; source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh > /dev/null; set -u
export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
: > $O/jobs.txt
for f in $T/fair/fair_perf_24-baremetal $T/fair/fair_perf_dense_only-baremetal $T/sbench/*/*_24_loop-baremetal; do echo "$f $S/libgemmini-nm24/libgemmini.so" >> $O/jobs.txt; done
for f in $T/fair/fair_perf_48-baremetal $T/sbench/*/*_48_loop-baremetal; do echo "$f $S/libgemmini-nm48/libgemmini.so" >> $O/jobs.txt; done
run1() { local b; b=$(basename "$1" -baremetal); local rc=0; timeout 7200 spike --extlib="$2" --extension=gemmini "$1" > "$O/$b.log" 2>&1 || rc=$?; echo "$b rc=$rc"; }
export -f run1; export O
xargs -P 8 -L 1 bash -c 'run1 "$@"' _ < $O/jobs.txt | sort > $O/rc.txt
echo done > $O/STATUS
