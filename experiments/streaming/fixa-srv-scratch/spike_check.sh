#!/bin/bash
# spike_check.sh <bindir> <logdir>: run every server-built binary on the laptop Fix A Spike libs (fixa24 / fixa48)
source /home/hunter/gemmini-fixwork/fixa/env.sh
B=$1 O=$2; mkdir -p $O
one() {
  b=$1; n=$(basename $b -baremetal); case $n in *_48*) lib=fixa48 ;; *) lib=fixa24 ;; esac
  timeout 1800 spike --extlib=/home/hunter/gemmini-fixwork/fixa/lib/$lib/libgemmini.so --extension=gemmini $b > $O/$n.log 2>&1
  echo "$n rc=$?"
}
export -f one; export O
find $B -name '*-baremetal' | sort | xargs -P 6 -I{} bash -c 'one {}' | sort > $O/rc.txt
echo done
