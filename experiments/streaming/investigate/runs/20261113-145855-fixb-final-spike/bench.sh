#!/bin/bash
set +u; source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh >/dev/null; set -u
export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
O=$1; run1(){ b=$(basename "$1" -baremetal); rc=0; timeout 7200 spike --extlib="$2" --extension=gemmini "$1" > "$O/$b.log" 2>&1 || rc=$?; echo "$b rc=$rc"; }
export -f run1; export O
xargs -P 6 -L 1 bash -c 'run1 "$@"' _ < $O/jobs.txt | sort > $O/rc.txt; echo done > $O/STATUS
