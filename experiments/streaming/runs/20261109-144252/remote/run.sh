#!/bin/bash
# sbench server runner: same make invocation as experiments/streaming/scripts/run_rtl.sh
source ~/miniforge3/etc/profile.d/conda.sh; conda deactivate 2>/dev/null; source ~/chipyard/env.sh > /dev/null
cd ~/sbench
cfg_of() { case "$1" in stock) echo GemminiRocketConfig ;; nm24) echo GemminiNMRocketConfig ;; nm48) echo GemminiNM48RocketConfig ;; esac; }
[ -f jobs.tsv ] || printf 'chip\tprogram\tseed\ttimeout_cycles\tstart_epoch\tend_epoch\twall_s\texit\n' > jobs.tsv
one() {
  local chip=$1 prog=$2 seed=$3 tmo=$4 log t0 t1 rc
  log=~/sbench/logs/$chip.$prog.seed$seed.log; t0=$(date +%s)
  (cd ~/chipyard/sims/verilator && make CONFIG=$(cfg_of $chip) run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 \
     TIMEOUT_CYCLES=$tmo BINARY=$HOME/sbench/bin/$prog-baremetal RANDOM_SEED=$seed \
     EXTRA_SIM_OUT_NAME=sbench.$chip.seed$seed.20261109-144252) > $log 2>&1
  rc=$?; t1=$(date +%s)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' $chip $prog $seed $tmo $t0 $t1 $((t1-t0)) $rc >> jobs.tsv
}
one nm48 bert_ffn1_48_sparse 1 60000000 &
one nm48 bert_ffn2_48_sparse 1 60000000 &
one nm24 rn50_conv_24_ds 1 30000000 &
one stock rn50_conv_24_dense 1 30000000 &
one nm48 rn50_conv_48_sparse 1 30000000 &
wait
echo ALL_DONE > ~/sbench/STATUS
