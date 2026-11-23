#!/bin/bash
# Elaborate dense GemminiRocketConfig (verilog only, no Verilator) from bank-split-fix sources into a SEPARATE gen dir.
source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh > /dev/null
D=~/sinv/banksplit-dense; mkdir -p $D
V=~/chipyard/sims/verilator
P=~/chipyard/generators/gemmini/software/gemmini-rocc-tests/include/gemmini_params.h
echo "RUNNING $(date)" > $D/STATUS
sha256sum $V/simulator-chipyard.harness-GemminiRocketConfig > $D/stock-sim.before
(cd $V && find generated-src/chipyard.harness.TestHarness.GemminiRocketConfig -type f -print0 | sort -z | xargs -0 sha256sum) > $D/stock-gensrc.before
(cd $V && flock ~/sinv/sims-make.lock make -j8 CONFIG=GemminiRocketConfig generated_src_name=generated-src-banksplit-dense verilog) > $D/elab.log 2>&1
rc=$?
sha256sum $V/simulator-chipyard.harness-GemminiRocketConfig > $D/stock-sim.after
(cd $V && find generated-src/chipyard.harness.TestHarness.GemminiRocketConfig -type f -print0 | sort -z | xargs -0 sha256sum) > $D/stock-gensrc.after
echo "DENSE_ELAB_EXIT=$rc $(date)" > $D/STATUS
