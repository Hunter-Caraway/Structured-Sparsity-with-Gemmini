#!/bin/bash
# Server side of the area flow; started by synth_area.sh under nohup setsid.
# Usage: area_remote.sh <config> <lib> <run dir> <expected sim count>
set -euo pipefail
CFG=$1 LIBNAME=$2 RUN=$3 SIMS_EXPECTED=$4
TOP=Gemmini
FLOW=$HOME/area/flow
GEN=$HOME/chipyard/sims/verilator/generated-src/chipyard.harness.TestHarness.$CFG
SRC=$GEN/gen-collateral
case $LIBNAME in
  nangate45) LIB=$HOME/area/pdk/nangate45/NangateOpenCellLibrary_typical.lib ;;
  sky130hd)  LIB=$HOME/area/pdk/sky130hd/sky130_fd_sc_hd__tt_025C_1v80.lib ;;
  *) echo "unknown lib $LIBNAME"; exit 2 ;;
esac
fail() { echo "FAIL $*" > "$RUN/STATUS.tmp"; mv "$RUN/STATUS.tmp" "$RUN/STATUS"; exit 1; }
trap 'fail "line $LINENO rc=$?"' ERR

source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate yosys
ulimit -v 8388608   # 8 GiB, user approval 2026-11-17

# The -lib macro file must be the one firtool wrote for this config.
MACROS=$(ls "$SRC"/chipyard.harness.TestHarness.$CFG.top.mems.v)
[ -f "$LIB" ] || fail "missing liberty $LIB"

python3 -I "$FLOW/verilog_closure.py" "$SRC" "$TOP" "$MACROS" "$RUN/closure"
grep -q '^macro_not_in_closure mem_1_ext$' "$RUN/closure.txt" || fail "mem_1_ext inside $TOP"
# Sources are only read in place; their hashes pin what was synthesized.
xargs -a "$RUN/closure.files" sha256sum > "$RUN/verilog.sha256"
sha256sum "$MACROS" "$LIB" "$GEN/chipyard.harness.TestHarness.$CFG.mems.conf" > "$RUN/inputs.sha256"
# Yosys 0.71 rejects firtool's packed-array patterns ('{...}), so sv2v
# (approved 2026-11-17) lowers the closure to Verilog-2005 first.
WORK=$HOME/area/work/$(basename "$RUN")
mkdir -p "$WORK"
xargs -a "$RUN/closure.files" zachjs-sv2v -DSYNTHESIS > "$WORK/top_sv2v.v" 2> "$RUN/sv2v.log" \
  || fail "sv2v rc=$?"
echo "read_verilog $WORK/top_sv2v.v" > "$RUN/read_files.ys"
sed -e "s|@MACROS@|$MACROS|g" -e "s|@READ_SCRIPT@|$RUN/read_files.ys|g" \
    -e "s|@TOP@|$TOP|g" -e "s|@LIB@|$LIB|g" -e "s|@OUT@|$RUN|g" \
    "$FLOW/synth_area.ys.in" > "$RUN/synth.ys"

{
  echo "config=$CFG"
  echo "lib=$LIBNAME $LIB"
  echo "lib_sha256=$(sha256sum "$LIB" | cut -d' ' -f1)"
  echo "top=$TOP"
  echo "host=$(hostname) core=$(taskset -pc $$ | awk '{print $NF}') nice=$(nice)"
  echo "ulimit_v_kb=$(ulimit -v)"
  echo "yosys=$(yosys -V)"
  echo "yosys_abc=$(command -v yosys-abc)"
  echo "sv2v=$(zachjs-sv2v --version) $(command -v zachjs-sv2v)"
  echo "sv2v_out_sha256=$(sha256sum < "$WORK/top_sv2v.v" | cut -d' ' -f1) $WORK/top_sv2v.v"
  echo "flow_sha256=$(cd "$FLOW" && sha256sum area_remote.sh synth_area.ys.in verilog_closure.py | tr '\n' ' ')"
  echo "verilog_files=$(wc -l < "$RUN/closure.files") list_sha256=$(sha256sum < "$RUN/verilog.sha256" | cut -d' ' -f1)"
  echo "sims_expected=$SIMS_EXPECTED sims_at_start=$(pgrep -fc '^[^ ]*simulator-chip' || true)"
  echo "memavail_kb_at_start=$(awk '/MemAvailable/{print $2}' /proc/meminfo)"
  echo "start=$(date -Is)"
} > "$RUN/run.info"
printf 'job\tconfig\tlib\ttop\tlog\n1\t%s\t%s\t%s\tyosys.log\n' "$CFG" "$LIBNAME" "$TOP" > "$RUN/jobs.tsv"

NOW=$(pgrep -fc '^[^ ]*simulator-chip' || true)
[ "$NOW" = "$SIMS_EXPECTED" ] || fail "sim count changed $SIMS_EXPECTED -> $NOW before synthesis"

T0=$(date +%s)
yosys -q -l "$RUN/yosys.log" -s "$RUN/synth.ys" > "$RUN/yosys.stdout" 2>&1 || fail "yosys rc=$?"
T1=$(date +%s)
{
  echo "end=$(date -Is)"
  echo "yosys_wall_s=$((T1 - T0))"
  echo "sims_at_end=$(pgrep -fc '^[^ ]*simulator-chip' || true)"
} >> "$RUN/run.info"
[ -s "$RUN/stat.json" ] || fail "no stat.json"
grep -q 'End of script' "$RUN/yosys.log" || fail "yosys log has no End of script"
python3 -I "$FLOW/parse_area.py" --lib "$LIB" \
  --mems-conf "$GEN/chipyard.harness.TestHarness.$CFG.mems.conf" "$RUN" > "$RUN/area.txt" || fail "parse_area"
trap - ERR
(cd "$RUN" && find . -type f ! -name SHA256SUMS ! -name STATUS ! -name nohup.out -printf '%P\n' | sort \
   | xargs sha256sum > SHA256SUMS)
echo DONE > "$RUN/STATUS"
