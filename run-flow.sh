#!/usr/bin/env bash
# run-flow.sh: the whole Gemmini N:M (2:4 / 4:8) sparsity flow, from environment check to verified figures.
#
# usage: ./run-flow.sh <step> [args]          (./run-flow.sh with no step lists them)
#
#  setup
#    env               print the commands to set up a fresh terminal by hand
#    check             tools, simulators, branches, python libraries
#  build (one at a time; never run two builds at once)
#    spike-lib [pat]   build + install the Gemmini Spike extension (libgemmini) for pat = nm24 (default) | nm48
#    tests             build gemmini-rocc-tests, plus nm_sparse_*_24 / _48 built with explicit -DNM_N/-DNM_M
#    fair-build        build the fair benchmark (and berkeley_dense_perf) into verification/build/, check each
#                      program's N:M, and compare it with the old programs in verification/bin/
#    sim <cfg>         build a Verilator simulator. cfg = nm24 | nm48 | dense (see the note on dense below)
#  simulate (slow; sleep is blocked while these run; every run uses BREAK_SIM_PREREQ=1, so build sims first)
#    spike [pat]       quick functional tests on Spike for pat = nm24 (default) | nm48 (seconds)
#    fair [which]      fair benchmark on RTL, once per seed in SEEDS. which = all (default) | nm24 | nm48 |
#                      berkeley | sameprog. -> verification/runs/fair-<stamp>/<chip>.seed<S>.log + run.info
#    rerun             the nm_sparse_* RTL tests once per seed, plus the NEG asserts -> verification/runs/rerun-<stamp>/
#    baseline          stock matmul-baremetal on Berkeley's simulator (very slow: full instruction trace)
#    bench <cfg>       ORIGINAL benchmark (nm_sparse_perf; superseded loop) on nm24|nm48, once per seed
#                      -> verification/runs/bench-<cfg>-<stamp>/ (logs + cycles.csv)
#  check and report (python; seconds). [run...] = run folders, default the newest fair run
#    verify [args]     verification/verify_all.py
#    compare <run> [ref]  compare a run folder with a reference run, number for number
#    math              independent math check (sparse math == dense math, fault injection)
#    patterns          how much of the weights' energy 2:4, 4:8 and NVIDIA's paired 4:8 keep (synthetic weights)
#    figures [run...]  the paper's numbers + chart, the figures and the time split -> <run>/derived/
#    split [run]       preprocessing vs runtime of a fair run -> <run>/derived/split.*
#    area              chip area of the three simulators' generated verilog (yosys, sky130) -> analysis/area/
#    checks [run...]   math + patterns + verify + figures
#  pipelines
#    all               spike-lib, tests, fair-build, spike, sim nm24, sim nm48, fair all, checks
#                      (needs Berkeley's stock simulator already built; see the note on dense below)
#
# environment variables
#   CHIPYARD_DIR    where chipyard lives (default ~/chipyard; no spaces or ':' allowed)
#   JOBS            make -j for simulator builds (default: picked from free RAM, ~2.5 GB per job)
#   SEEDS           Verilator RANDOM_SEED values for fair / rerun / bench (default "1 2 3"); recorded in run.info
#   PAR             how many simulations run at once (default: number of CPUs)
#   TIMEOUT_CYCLES  simulation cycle limit (default 150M; chipyard's own 10M is too short)
#   FAIR_BIN        folder with the fair benchmark programs (default verification/build, from fair-build;
#                   verification/bin holds the old programs that produced the withdrawn results)
#   AREA_YOSYS      yosys for `area` (default ~/gemmini-fixwork/eda/bin/yosys)
#   AREA_LIB        sky130 hd liberty file for `area` (default ~/gemmini-fixwork/pdk/sky130hd/...tt_025C_1v80.lib)
#   PYTHON          python to use (default: chipyard's conda env, which has numpy/pandas/matplotlib)
#   FORCE=1         allow `sim dense` to replace an existing stock simulator (still only from Berkeley's sources)
#
# notes learned the hard way
#   * Berkeley's stock simulator (GemminiRocketConfig) must be built from UNMODIFIED Gemmini sources: `sim dense`
#     refuses unless all three Gemmini repos sit cleanly at Berkeley's base commits. Chipyard rebuilds a simulator
#     whenever the Scala changes, so every run uses BREAK_SIM_PREREQ=1 and never rebuilds anything.
#   * every elaboration rewrites gemmini_params.h; tests and fair-build put the committed one back first.
#   * the laptop suspends on lid close / idle, which pauses simulations; long steps hold a sleep inhibitor.

set -eo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cy="${CHIPYARD_DIR:-$HOME/chipyard}"
gem="$cy/generators/gemmini"
lib_dir="$gem/software/libgemmini"
tests_dir="$gem/software/gemmini-rocc-tests"
bm="$tests_dir/build/bareMetalC"
ver="$here/verification"
logs="$here/logs"
runs="$ver/runs"
py="${PYTHON:-$cy/.conda-env/bin/python}"
fair_bin="${FAIR_BIN:-$ver/build}"
[[ "$fair_bin" = /* ]] || fair_bin="$here/$fair_bin"
seeds="${SEEDS:-1 2 3}"
stamp="$(date +%Y%m%d-%H%M%S)"
nm_tests=(nm_sparse_debug nm_sparse_matmul nm_sparse_perf nm_sparse_protocol)
# nm_sparse_protocol -DNEG=<n>: illegal uses that must stop the run (Spike abort / RTL assert); 6 is Spike only
neg_spike=(4 6 7 9 10 14) neg_rtl=(4 7 9 10 14)
# the RTL assert message each NEG case must trigger
neg_msg() {
  case "$1" in
    4) echo "index fifo deadlock" ;;
    7|14) echo "differs from the mode its weights were preloaded in" ;;
    9) echo "needs weight stationary dataflow" ;;
    10) echo "issued while n:m sparse mode" ;;
  esac
}
# Berkeley's base commits (what Chipyard 1.14.0 pins); the stock simulator is built only from these
base_gem=8c3f9923 base_lib=ea8f7ed base_tests=7c540b3

say()  { printf '\n== %s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
cfg_name() {
  case "$1" in
    dense) echo GemminiRocketConfig ;;
    nm24)  echo GemminiNMRocketConfig ;;
    nm48)  echo GemminiNM48RocketConfig ;;
    *) die "unknown config '$1' (want nm24, nm48 or dense)" ;;
  esac
}
pat_nm() {
  case "$1" in
    nm24) echo "2 4" ;;
    nm48) echo "4 8" ;;
    *) die "unknown pattern '$1' (want nm24 or nm48)" ;;
  esac
}
sim_path() { echo "$cy/sims/verilator/simulator-chipyard.harness-$1"; }

case "$cy" in *" "*|*:*) die "chipyard path '$cy' has a space or ':' in it; it has to live somewhere plain" ;; esac
[ -f "$cy/env.sh" ] || die "no env.sh in $cy; did build-setup.sh run? (see chipyard-setup-notes.md)"
for s in $seeds; do [[ "$s" =~ ^[0-9]+$ ]] || die "SEEDS must be whole numbers, got '$s'"; done

# ---------------------------------------------------------------- helpers
# fedora / rhel: conda deactivate first, then env.sh (the chipyard docs say so)
load_env() {
  local base
  base="$(conda info --base 2>/dev/null || echo "$HOME/miniforge3")"
  # shellcheck disable=SC1091
  source "$base/etc/profile.d/conda.sh"
  conda deactivate 2>/dev/null || true
  # shellcheck disable=SC1091
  source "$cy/env.sh"
  [ -n "$RISCV" ] || die "RISCV not set after sourcing env.sh"
  export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
}

need_py() { [ -x "$py" ] || die "no python at $py (set PYTHON=...)"; }
need_sim() { [ -x "$(sim_path "$1")" ] || die "no simulator for $1 at $(sim_path "$1") (./run-flow.sh sim ...)"; }

# verilator compiles take ~2.5 GB each on gemmini
pick_jobs() {
  if [ -n "$JOBS" ]; then echo "$JOBS"; return; fi
  local avail_kb jobs
  avail_kb=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
  jobs=$(( avail_kb / (2560 * 1024) ))
  [ "$jobs" -lt 1 ] && jobs=1
  [ "$jobs" -gt "$(nproc)" ] && jobs=$(nproc)
  echo "$jobs"
}

# one cleanup for everything this script starts: running simulations and the sleep inhibitor
inhibitor=""
pids=()
descendants() { local c; for c in $(pgrep -P "$1"); do echo "$c"; descendants "$c"; done; }
kill_tree() { local all; mapfile -t all < <(descendants "$1"); kill "$1" "${all[@]}" 2>/dev/null || true; }
cleanup() {
  local p
  if [ "${#pids[@]}" -gt 0 ]; then
    echo "stopping ${#pids[@]} running simulation(s)" >&2
    for p in "${pids[@]}"; do kill_tree "$p"; done
    wait "${pids[@]}" 2>/dev/null || true
  fi
  [ -n "$inhibitor" ] && kill_tree "$inhibitor"
  return 0
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# hold off suspend/idle sleep until this script exits (a suspend pauses the simulation)
stay_awake() {
  command -v systemd-inhibit >/dev/null || return 0
  [ -n "$inhibitor" ] && return 0
  systemd-inhibit --what=sleep:idle --who="run-flow.sh" --why="$1" sleep infinity &
  inhibitor=$!
  sleep 0.2
  if kill -0 "$inhibitor" 2>/dev/null; then
    echo "sleep blocked while this runs (closing the lid may still suspend, depending on the lid setting)"
  else
    echo "warning: systemd-inhibit exited at once; sleep is NOT blocked" >&2; inhibitor=""
  fi
}

# compile flags of gemmini-rocc-tests, in the order that produced the recorded programs
# shellcheck disable=SC2054
rv_pre=(-DPREALLOCATE=1 -DMULTITHREAD=1 -mcmodel=medany -std=gnu99 -O2 -ffast-math -fno-common -fno-builtin-printf
        -fno-tree-loop-distribute-patterns -march=rv64gc -Wa,-march=rv64gc)
rv_inc=(-I"$tests_dir/riscv-tests" -I"$tests_dir/riscv-tests/env" -I"$tests_dir"
        -I"$tests_dir/riscv-tests/benchmarks/common" -DID_STRING= -DPRINT_TILE=0)

# compile a bare-metal test the same way gemmini-rocc-tests does: rv_cc <src> <out> [-Dflags...]
rv_cc() {
  local src="$1" out="$2" c="$tests_dir/riscv-tests/benchmarks/common" msgs rc=0; shift 2
  rm -f "$out"
  msgs="$(riscv64-unknown-elf-gcc "$@" "${rv_pre[@]}" -lm -lgcc "${rv_inc[@]}" -nostdlib -nostartfiles -static \
    -T "$c/test.ld" -DBAREMETAL=1 "$src" -o "$out" "$c/syscalls.c" "$c/crt.S" 2>&1)" || rc=$?
  [ -z "$msgs" ] || grep -v RWX <<<"$msgs" >&2 || true
  [ "$rc" -eq 0 ] && [ -s "$out" ] || die "compile failed (gcc exit $rc): $src -> $out"
}

# the N:M a compile with these flags really uses ("N:M"; empty for none): rv_nm <src> [-Dflags...]
rv_nm() {
  local src="$1" defs; shift
  defs="$(riscv64-unknown-elf-gcc "$@" "${rv_pre[@]}" "${rv_inc[@]}" -DBAREMETAL=1 -dM -E "$src")" \
    || die "preprocessing failed: $src"
  awk '$1 == "#define" && $2 == "NM_N" {n = $3} $1 == "#define" && $2 == "NM_M" {m = $3}
       END {if (n != "" && m != "") print n ":" m}' <<<"$defs"
}

# compile with an explicit pattern and check the compile really used it: rv_cc_nm <src> <out> <n> <m> [flags...]
rv_cc_nm() {
  local src="$1" out="$2" n="$3" m="$4" got; shift 4
  rv_cc "$src" "$out" "$@" -DNM_N="$n" -DNM_M="$m"
  got="$(rv_nm "$src" "$@" -DNM_N="$n" -DNM_M="$m")"
  [ "$got" = "$n:$m" ] || { rm -f "$out"; die "$(basename "$out") was meant to be $n:$m but compiles as '${got:-none}'"; }
}

# every elaboration rewrites gemmini_params.h (an n:m config adds GEMMINI_HW_NM_N/M); put the committed one back
restore_params_h() {
  git -C "$tests_dir" diff --quiet -- include/gemmini_params.h && return 0
  echo "  restoring the committed include/gemmini_params.h (the last elaboration rewrote it)"
  git -C "$tests_dir" checkout -- include/gemmini_params.h
}

# run one binary on one (already built) simulator: sim_run <cfg> <binary> <log> [extra make args...]
sim_run() {
  local cfg="$1" bin="$2" log="$3"; shift 3
  (cd "$cy/sims/verilator" && make CONFIG="$cfg" run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 \
     TIMEOUT_CYCLES="${TIMEOUT_CYCLES:-150000000}" BINARY="$bin" "$@") > "$log" 2>&1
}

# simulation queue: queue <name> <cfg> <binary> <log> <seed> <expected lines (grep -E, one per line)>
q_name=() q_cfg=() q_bin=() q_log=() q_seed=() q_expect=() q_mode=()
# 7th arg "fail": the run must exit non-zero (an RTL assert), and the expected lines must still be there
queue() {
  case "$3$4" in *" "*|*:*) die "make can't take paths with spaces or ':': $3 / $4" ;; esac
  [ -f "$3" ] || die "missing program $3"
  q_name+=("$1"); q_cfg+=("$2"); q_bin+=("$3"); q_log+=("$4"); q_seed+=("$5"); q_expect+=("$6"); q_mode+=("${7:-pass}")
}

# run the queue, PAR at a time; fail if any run exits non-zero or lacks an expected line
run_queue() {
  local par="${PAR:-$(nproc)}" n="${#q_name[@]}" i fails=0
  local -A job_of=()
  reap() {
    local done_pid rc=0 j pat bad="" p keep=()
    wait -n -p done_pid "${pids[@]}" || rc=$?
    [ -n "$done_pid" ] || die "internal: wait returned no job"
    for p in "${pids[@]}"; do [ "$p" = "$done_pid" ] || keep+=("$p"); done
    pids=("${keep[@]}")
    j="${job_of[$done_pid]}"
    if [ "${q_mode[j]}" = fail ]; then [ "$rc" -ne 0 ] || bad="exit 0 (the illegal use was not caught)"
    else [ "$rc" -eq 0 ] || bad="exit $rc"; fi
    while IFS= read -r pat; do
      [ -z "$pat" ] || grep -qE -- "$pat" "${q_log[j]}" || bad="${bad:+$bad; }no line matching '$pat'"
    done <<<"${q_expect[j]}"
    if [ -z "$bad" ]; then echo "  ok    ${q_name[j]} seed ${q_seed[j]}  ($(date +%H:%M:%S))"
    else echo "  FAIL  ${q_name[j]} seed ${q_seed[j]}: $bad  (see ${q_log[j]#"$here"/})"; fails=$((fails + 1)); fi
  }
  for ((i = 0; i < n; i++)); do
    while [ "${#pids[@]}" -ge "$par" ]; do reap; done
    sim_run "${q_cfg[i]}" "${q_bin[i]}" "${q_log[i]}" RANDOM_SEED="${q_seed[i]}" \
      EXTRA_SIM_OUT_NAME="${q_name[i]}.seed${q_seed[i]}.$stamp" &
    pids+=("$!"); job_of[$!]=$i
    echo "  started ${q_name[i]} seed ${q_seed[i]} on ${q_cfg[i]}"
  done
  while [ "${#pids[@]}" -gt 0 ]; do reap; done
  q_name=() q_cfg=() q_bin=() q_log=() q_seed=() q_expect=() q_mode=()
  [ "$fails" -eq 0 ] || die "$fails of $n simulation(s) failed (see above)"
}

# provenance of a run folder: run.info (key=value) and SHA256SUMS of everything in it
write_info() {
  local run="$1" r c s kv; shift
  {
    echo "stamp=$stamp"
    echo "seeds=$seeds"
    echo "timeout_cycles=${TIMEOUT_CYCLES:-150000000}"
    for kv in "$@"; do echo "$kv"; done
    for r in "$here" "$gem" "$lib_dir" "$tests_dir"; do
      echo "git.$(basename "$r")=$(git -C "$r" rev-parse HEAD)$(git -C "$r" diff --quiet HEAD && echo '' || echo ' (uncommitted changes)')"
    done
    for c in "${q_cfg[@]}"; do echo "$c"; done | sort -u | while read -r c; do
      s="$(sim_path "$c")"
      echo "sim.$c=$(date -r "$s" '+%Y-%m-%dT%H:%M:%S') sha256:$(sha256sum "$s" | cut -c1-16)"
    done
  } > "$run/run.info"
}
write_sums() {
  local tmp; tmp="$(mktemp)"
  (cd "$1" && find . -type f ! -name SHA256SUMS ! -path './derived/*' -printf '%P\0' | sort -z | xargs -0 sha256sum) > "$tmp"
  mv "$tmp" "$1/SHA256SUMS"
}
new_run() { [ ! -e "$1" ] || die "$1 already exists"; mkdir -p "$1/bin"; }

# ---------------------------------------------------------------- setup
step_env() {
  cat <<EOF
# fresh terminal setup (fedora needs the deactivate first)
conda deactivate
cd $cy
source env.sh
EOF
}

step_check() {
  load_env
  say "tools"
  echo "CONDA_DEFAULT_ENV=$CONDA_DEFAULT_ENV"
  echo "RISCV=$RISCV"
  for t in spike verilator firtool riscv64-unknown-elf-gcc; do
    printf '  %-24s %s\n' "$t" "$(command -v "$t" || echo MISSING)"
  done
  [ -f "$RISCV/lib/libgemmini.so" ] && echo "  libgemmini.so installed" || echo "  libgemmini.so MISSING (run spike-lib)"
  say "simulators"
  local c s
  for c in dense nm24 nm48; do
    s="$(sim_path "$(cfg_name $c)")"
    if [ -x "$s" ]; then printf '  %-6s %s  (built %s)\n' "$c" "$(basename "$s")" "$(date -r "$s" '+%Y-%m-%d %H:%M')"
    else printf '  %-6s MISSING (run: ./run-flow.sh sim %s)\n' "$c" "$c"; fi
  done
  say "code branches"
  for r in "$gem" "$lib_dir" "$tests_dir"; do
    printf '  %-20s %s @ %s%s\n' "$(basename "$r")" "$(git -C "$r" branch --show-current)" \
      "$(git -C "$r" rev-parse --short HEAD)" "$(git -C "$r" diff --quiet && echo '' || echo '  (uncommitted changes)')"
  done
  say "python ($py)"
  if [ -x "$py" ]; then "$py" -c "import numpy, pandas, matplotlib; print('  numpy', numpy.__version__, '| pandas', pandas.__version__, '| matplotlib', matplotlib.__version__)"
  else echo "  MISSING"; fi
  say "disk"
  df -h "$HOME" | tail -1
}

# ---------------------------------------------------------------- build
step_spike_lib() {
  local pat="${1:-nm24}" n m log="$logs/runs/libgemmini-$stamp.log"
  pat_nm "$pat" > /dev/null
  read -r n m <<<"$(pat_nm "$pat")"
  load_env
  mkdir -p "$logs/runs"
  say "building libgemmini (spike extension) for $n:$m -> ${log#"$here"/}"
  # -B: the .so only depends on gemmini.cc, so a pattern change alone would not rebuild it
  make -B -C "$lib_dir" install NM_N="$n" NM_M="$m" > "$log" 2>&1 || { tail -20 "$log" >&2; die "libgemmini build failed, see $log"; }
  [ -f "$RISCV/lib/libgemmini.so" ] || die "libgemmini.so didn't install"
  echo "  installed $RISCV/lib/libgemmini.so ($n:$m)"
}

step_tests() {
  local log="$logs/runs/rocc-tests-$stamp.log" t built
  load_env
  mkdir -p "$logs/runs"
  say "building gemmini-rocc-tests -> ${log#"$here"/}"
  restore_params_h
  # a killed make can leave 0-byte binaries that look up to date; clear them first
  [ -d "$tests_dir/build" ] && find "$tests_dir/build" -type f -size 0 -name '*-baremetal' -delete
  (cd "$tests_dir" && ./build.sh) > "$log" 2>&1 || { tail -20 "$log" >&2; die "test build failed, see $log"; }
  # both patterns of the sparse tests, with explicit -D flags so they don't depend on the last elaboration
  for t in nm_sparse_sw "${nm_tests[@]}"; do
    rv_cc_nm "$tests_dir/bareMetalC/$t.c" "$bm/${t}_24-baremetal" 2 4
    rv_cc_nm "$tests_dir/bareMetalC/$t.c" "$bm/${t}_48-baremetal" 4 8
  done
  for n in "${neg_spike[@]}"; do
    rv_cc_nm "$tests_dir/bareMetalC/nm_sparse_protocol.c" "$bm/nm_sparse_protocol_neg${n}_24-baremetal" 2 4 -DNEG="$n"
    rv_cc_nm "$tests_dir/bareMetalC/nm_sparse_protocol.c" "$bm/nm_sparse_protocol_neg${n}_48-baremetal" 4 8 -DNEG="$n"
  done
  built=("$bm"/*-baremetal)
  echo "${#built[@]} bare-metal tests built (including nm_sparse_*_24 / _48, N:M checked)"
}

step_fair_build() {
  local out="$ver/build" n=0 same=0 b
  load_env
  mkdir -p "$out"
  say "building the fair benchmark into ${out#"$here"/}"
  restore_params_h
  rv_cc_nm "$ver/fair_perf.c" "$out/fair_perf_24-baremetal" 2 4
  rv_cc_nm "$ver/fair_perf.c" "$out/fair_perf_48-baremetal" 4 8
  rv_cc_nm "$ver/fair_perf.c" "$out/fair_perf_dense_only-baremetal" 2 4 -DDENSE_ONLY
  rv_cc_nm "$ver/berkeley_dense_perf.c" "$out/berkeley_dense_perf-baremetal" 2 4
  echo "  N:M checked: fair_perf_24 = 2:4, fair_perf_48 = 4:8, fair_perf_dense_only = berkeley_dense_perf = 2:4"
  # compare what the chip actually loads (code + data); the raw files differ in symbol-table temp names
  loadimg() {
    local img; img="$(mktemp)"
    riscv64-unknown-elf-objcopy -O binary "$1" "$img" || { rm -f "$img"; die "objcopy failed on $1"; }
    sha256sum "$img" | cut -c1-16; rm -f "$img"
  }
  for b in "$out"/*-baremetal; do
    [ -f "$ver/bin/$(basename "$b")" ] || continue
    n=$((n + 1))
    if [ "$(loadimg "$b")" = "$(loadimg "$ver/bin/$(basename "$b")")" ]; then
      same=$((same + 1)); echo "  identical code and data to the old program: $(basename "$b")"
    else
      echo "  differs from the old program in verification/bin: $(basename "$b")"
    fi
  done
  echo "$same of $n programs match the old ones (expected to differ after the fair_perf.c fixes)"
}

# true if repo $1 sits exactly at commit $2 with no uncommitted changes to tracked files
at_base() {
  [ "$(git -C "$1" rev-parse HEAD)" = "$(git -C "$1" rev-parse "$2^{commit}" 2>/dev/null)" ] &&
    [ -z "$(git -C "$1" status --porcelain --untracked-files=no)" ]
}

step_sim() {
  local which="${1:-}" cfg jobs log s
  [ -n "$which" ] || die "usage: ./run-flow.sh sim nm24|nm48|dense"
  cfg="$(cfg_name "$which")"
  s="$(sim_path "$cfg")"
  if [ "$which" = dense ]; then
    if ! { at_base "$gem" "$base_gem" && at_base "$lib_dir" "$base_lib" && at_base "$tests_dir" "$base_tests"; }; then
      die "the stock simulator must be built from Berkeley's unmodified sources: check out $base_gem (gemmini),
$base_lib (libgemmini) and $base_tests (gemmini-rocc-tests) with clean trees, build, then switch back to sparse-nm"
    fi
    [ ! -x "$s" ] || [ "${FORCE:-0}" = 1 ] || die "$cfg already exists; FORCE=1 to rebuild it (from the base sources)"
  fi
  load_env
  mkdir -p "$logs/runs"
  jobs="$(pick_jobs)"
  log="$logs/runs/sim-$cfg-$stamp.log"
  stay_awake "building $cfg"
  say "building verilator sim $cfg with -j$jobs -> ${log#"$here"/}"
  if ! (cd "$cy/sims/verilator" && make -j"$jobs" CONFIG="$cfg") > "$log" 2>&1; then
    # the OOM killer shows up as a killed compiler; retry slower once
    if grep -qiE "killed|signal 9|out of memory" "$log" && [ "$jobs" -gt 2 ]; then
      say "looks like it ran out of memory, retrying with -j2"
      (cd "$cy/sims/verilator" && make -j2 CONFIG="$cfg") >> "$log" 2>&1 || die "sim build failed, see $log"
    else
      die "sim build failed, see $log"
    fi
  fi
  [ -x "$s" ] || die "make succeeded but there is no simulator at $s"
  ls -la "$s"
}

# ---------------------------------------------------------------- simulate
step_spike() {
  local pat="${1:-nm24}" sfx log="$logs/runs/spike-$stamp.log" fails=0 t
  sfx="_${pat#nm}"; pat_nm "$pat" > /dev/null
  load_env
  mkdir -p "$logs/runs"
  say "spike tests ($pat; libgemmini must be built for it: ./run-flow.sh spike-lib $pat) -> ${log#"$here"/}"
  for t in "$bm/mvin_mvout-baremetal" "$bm/matmul-baremetal" "$bm/nm_sparse_sw${sfx}-baremetal" \
           "$bm/nm_sparse_matmul${sfx}-baremetal" "$bm/nm_sparse_debug${sfx}-baremetal" "$bm/nm_sparse_perf${sfx}-baremetal" \
           "$bm/nm_sparse_protocol${sfx}-baremetal" "$fair_bin/fair_perf${sfx}-baremetal" \
           "$fair_bin/fair_perf_dense_only-baremetal" "$fair_bin/berkeley_dense_perf-baremetal"; do
    [ -f "$t" ] || die "missing $t (./run-flow.sh tests / fair-build)"
    if spike --extension=gemmini "$t" >> "$log" 2>&1; then echo "pass  $(basename "$t" -baremetal)"
    else echo "FAIL  $(basename "$t" -baremetal)"; fails=$((fails + 1)); fi
  done
  # illegal uses: Spike must abort with a GEMMINI: message (not a warning)
  local n out
  for n in "${neg_spike[@]}"; do
    t="$bm/nm_sparse_protocol_neg${n}${sfx}-baremetal"
    [ -f "$t" ] || die "missing $t (./run-flow.sh tests)"
    if out="$(timeout 120 spike --extension=gemmini "$t" 2>&1)"; then echo "FAIL  NEG=$n not caught"; fails=$((fails + 1))
    elif grep -q '^GEMMINI: [^w]' <<<"$out"; then echo "pass  NEG=$n aborts: $(grep -m1 '^GEMMINI: [^w]' <<<"$out")"
    else echo "FAIL  NEG=$n stopped without a GEMMINI abort"; fails=$((fails + 1)); fi
    echo "$out" >> "$log"
  done
  [ "$fails" -eq 0 ] || die "$fails spike test(s) failed, see $log"
}

step_fair() {
  local which="${1:-all}" run="$runs/fair-$stamp" s spec chip cfg prog nm
  case "$which" in all|nm24|nm48|berkeley|sameprog) ;; *) die "fair: want all|nm24|nm48|berkeley|sameprog" ;; esac
  load_env; need_py
  # chip, config, program, N:M the program must report
  local specs=("nm24 GemminiNMRocketConfig fair_perf_24 2:4" "nm48 GemminiNM48RocketConfig fair_perf_48 4:8"
               "berkeley GemminiRocketConfig fair_perf_dense_only 2:4" "sameprog GemminiNMRocketConfig fair_perf_dense_only 2:4")
  for spec in "${specs[@]}"; do
    read -r chip cfg prog nm <<<"$spec"
    [ "$which" = all ] || [ "$which" = "$chip" ] || continue
    need_sim "$cfg"
    [ -f "$fair_bin/$prog-baremetal" ] || die "missing $fair_bin/$prog-baremetal (./run-flow.sh fair-build)"
  done
  new_run "$run"
  for spec in "${specs[@]}"; do
    read -r chip cfg prog nm <<<"$spec"
    [ "$which" = all ] || [ "$which" = "$chip" ] || continue
    [ -f "$run/bin/$prog-baremetal" ] || cp "$fair_bin/$prog-baremetal" "$run/bin/"
    for s in $seeds; do
      queue "$chip" "$cfg" "$run/bin/$prog-baremetal" "$run/$chip.seed$s.log" "$s" \
        "$(printf '%s\n' "^fair_perf: $nm," '^fair_perf passed$' "\+verilator\+seed\+$s( |$)")"
    done
  done
  write_info "$run" "step=fair $which" "fair_bin=$fair_bin"
  stay_awake "fair benchmark simulations"
  say "fair benchmark ($which, seeds: $seeds) -> ${run#"$here"/}   (each takes ~15-40 min; $(nproc) CPUs, PAR=${PAR:-$(nproc)})"
  run_queue
  write_sums "$run"
  echo "all runs passed; results in ${run#"$here"/} (check them with ./run-flow.sh verify, then figures)"
}

step_rerun() {
  local run="$runs/rerun-$stamp" c t s sfx
  load_env; need_py
  for c in nm24 nm48; do
    need_sim "$(cfg_name $c)"
    for t in "${nm_tests[@]}"; do
      [ -f "$bm/${t}_${c#nm}-baremetal" ] || die "missing $bm/${t}_${c#nm}-baremetal (./run-flow.sh tests)"
    done
    for n in "${neg_rtl[@]}"; do
      [ -f "$bm/nm_sparse_protocol_neg${n}_${c#nm}-baremetal" ] || die "missing NEG=$n program (./run-flow.sh tests)"
    done
  done
  new_run "$run"
  for c in nm24 nm48; do
    sfx="_${c#nm}"
    for t in "${nm_tests[@]}"; do
      cp "$bm/${t}${sfx}-baremetal" "$run/bin/"
      for s in $seeds; do
        queue "$c-$t" "$(cfg_name $c)" "$run/bin/${t}${sfx}-baremetal" "$run/orig-$c-$t.seed$s.log" "$s" "^$t passed$"
      done
    done
    # illegal uses: each must stop the simulation with its own assert (first seed only; the outcome is not timing)
    s="${seeds%% *}"
    for n in "${neg_rtl[@]}"; do
      cp "$bm/nm_sparse_protocol_neg${n}${sfx}-baremetal" "$run/bin/"
      queue "$c-neg$n" "$(cfg_name $c)" "$run/bin/nm_sparse_protocol_neg${n}${sfx}-baremetal" "$run/neg-$c-$n.seed$s.log" "$s" \
        "$(printf '%s\n' 'Assertion failed' "$(neg_msg "$n")")" fail
    done
  done
  write_info "$run" "step=rerun"
  stay_awake "re-running the RTL tests"
  say "RTL tests: ${nm_tests[*]} + ${#neg_rtl[@]} illegal-use asserts, nm24 and nm48 (seeds: $seeds) -> ${run#"$here"/}"
  run_queue
  write_sums "$run"
  echo "all runs passed; results in ${run#"$here"/}"
}

step_baseline() {
  local log="$logs/baseline/baseline_matmul-$stamp.log"
  load_env
  need_sim GemminiRocketConfig
  [ -f "$bm/matmul-baremetal" ] || die "missing $bm/matmul-baremetal (./run-flow.sh tests)"
  mkdir -p "$logs/baseline"
  stay_awake "stock baseline simulation"
  say "stock baseline: matmul-baremetal on Berkeley's GemminiRocketConfig -> ${log#"$here"/}"
  # run-binary (not -fast) logs every instruction: very slow, GB-sized trace in sims/verilator/output
  (cd "$cy/sims/verilator" && make CONFIG=GemminiRocketConfig run-binary BREAK_SIM_PREREQ=1 \
     BINARY="$bm/matmul-baremetal" TIMEOUT_CYCLES="${TIMEOUT_CYCLES:-150000000}") > "$log" 2>&1 ||
    die "baseline simulation failed, see $log"
  grep -E "PASSED|FAILED|Completed after" "$log" || true
  grep -q "PASSED" "$log" || die "baseline log has no PASSED line, see $log"
}

# the ORIGINAL benchmark (its loop slowed dense mode more than sparse; superseded by `fair`), into its own run folder
step_bench() {
  local which="${1:-nm24}" cfg sfx run t s log tmp
  [ "$which" = dense ] && die "bench needs a sparse config (nm24 or nm48)"
  cfg="$(cfg_name "$which")"; sfx="_${which#nm}"
  run="$runs/bench-$which-$stamp"
  load_env
  need_sim "$cfg"
  for t in "${nm_tests[@]}"; do
    [ -f "$bm/${t}${sfx}-baremetal" ] || die "missing $bm/${t}${sfx}-baremetal (./run-flow.sh tests)"
  done
  new_run "$run"
  for t in "${nm_tests[@]}"; do
    cp "$bm/${t}${sfx}-baremetal" "$run/bin/"
    for s in $seeds; do queue "$t" "$cfg" "$run/bin/${t}${sfx}-baremetal" "$run/$t.seed$s.log" "$s" "^$t passed$"; done
  done
  write_info "$run" "step=bench $which"
  stay_awake "original benchmark"
  echo "note: this is the original benchmark (superseded loop). For numbers to cite, use: ./run-flow.sh fair"
  say "${nm_tests[*]} on $cfg (seeds: $seeds) -> ${run#"$here"/}"
  run_queue
  # cycles.csv from the logs, written to a temp file first so an abort never leaves half a table
  tmp="$(mktemp "$run/.cycles.XXXXXX")"
  echo "timestamp,config,test,variant,seed,status,total_cycles,array_busy_cycles,tiles" > "$tmp"
  for s in $seeds; do
    log="$run/nm_sparse_matmul.seed$s.log"
    echo "$stamp,$cfg,nm_sparse_matmul,dense,$s,passed,$(grep -oP 'dense\s+cycles: \K[0-9]+' "$log" | tail -1),,"
    echo "$stamp,$cfg,nm_sparse_matmul,sparse,$s,passed,$(grep -oP 'sparse cycles: \K[0-9]+' "$log" | tail -1),,"
    { grep -E '^[a-z_]+ +total' "$run/nm_sparse_perf.seed$s.log" || true; } | while read -r name _ total _ _ _ tiles _ _ rest; do
      echo "$stamp,$cfg,nm_sparse_perf,$name,$s,passed,$total,$(grep -oP 'ex_active=\K[0-9]+' <<<"$rest"),$tiles"
    done
  done >> "$tmp"
  mv "$tmp" "$run/cycles.csv"
  write_sums "$run"
  echo "all runs passed; $(($(wc -l < "$run/cycles.csv") - 1)) rows in ${run#"$here"/}/cycles.csv"
}

# ---------------------------------------------------------------- check and report (python)
step_verify()   { need_py; say "verify_all.py"; "$py" "$ver/verify_all.py" "$@"; }
step_compare()  { need_py; [ -n "${1:-}" ] || die "usage: ./run-flow.sh compare <run> [reference run]"; "$py" "$ver/compare_runs.py" "$@"; }
step_math()     { need_py; say "independent math check"; "$py" "$ver/independent_math_check.py"; }
step_patterns() { need_py; say "pattern comparison"; "$py" "$ver/pattern_fidelity.py"; }
step_figures() {
  need_py
  say "paper numbers + chart -> <run>/derived/"
  "$py" "$ver/paper_data.py" "$@"
  say "figures -> <run>/derived/figures/"
  "$py" "$here/analysis/advanced_visuals.py" "$@"
  "$py" "$here/analysis/chart_all_data.py" "$@"
  say "preprocessing vs runtime -> <run>/derived/split.*"
  "$py" "$here/analysis/split.py" "$@"
}
step_split()  { need_py; say "preprocessing vs runtime"; "$py" "$here/analysis/split.py" "$@"; }
step_area()   { need_py; say "chip area (yosys synthesis of each simulator's generated verilog; minutes)"; "$py" "$here/analysis/area.py"; }
step_checks() { step_math; step_patterns; step_verify --skip-patches "$@"; step_figures "$@"; }

# ---------------------------------------------------------------- dispatch
step="${1:-}"
shift || true
case "$step" in
  env)        step_env ;;
  check)      step_check ;;
  spike-lib)  step_spike_lib "$@" ;;
  tests)      step_tests ;;
  fair-build) step_fair_build ;;
  sim)        step_sim "$@" ;;
  spike)      step_spike "$@" ;;
  fair)       step_fair "$@" ;;
  rerun)      step_rerun ;;
  baseline)   step_baseline ;;
  bench)      step_bench "$@" ;;
  verify)     step_verify "$@" ;;
  compare)    step_compare "$@" ;;
  math)       step_math ;;
  patterns)   step_patterns ;;
  figures)    step_figures "$@" ;;
  split)      step_split "$@" ;;
  area)       step_area ;;
  checks)     step_checks "$@" ;;
  all)
    step_spike_lib nm24
    step_tests
    step_fair_build
    step_spike nm24
    step_sim nm24
    step_sim nm48
    step_fair all
    step_checks
    ;;
  ""|-h|--help|help) sed -n '2,/^set -eo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown step '$step'"; sed -n '/^#  setup/,/^#$/p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
