#!/usr/bin/env bash
# run-flow.sh: the whole Gemmini N:M (2:4 / 4:8) sparsity flow, from environment check to verified figures.
#
# usage: ./run-flow.sh <step> [args]          (./run-flow.sh with no step lists them)
#
#  setup
#    env               print the commands to set up a fresh terminal by hand
#    check             tools, simulators, branches, python libraries
#  build (one at a time; never run two builds at once)
#    spike-lib [pat]   build the Gemmini Spike extension (libgemmini) in a scratch dir (never installed) for
#                      pat = nm24 (default) | nm48 | nm816 | dense24 | dense48 | dense816 (the model of a dense chip, NM_DENSE_BUILD=1;
#                      `spike` needs it for the N11 / N14 checks); loaded with --extlib, which must come before --extension
#    tests             build the programs this flow uses into a scratch dir (never gemmini-rocc-tests/build): Berkeley's
#                      54 dense tests for normal configs, plus nm_sparse_*_24 / _48 / _816 built with explicit -DNM_N/-DNM_M
#    fair-build        build the fair benchmark (and berkeley_dense_perf) into verification/build/, check each
#                      program's N:M, and compare it with the old programs in verification/bin/
#    sim <cfg>         build a Verilator simulator. cfg = nm24 | nm48 | nm816 | dense (see the note on dense below);
#                      needs FORCE_REBUILD=1 and backs up the old simulator + generated-src first
#  simulate (slow; sleep is blocked while these run; every run uses BREAK_SIM_PREREQ=1, so build sims first)
#    spike [pat]       functional tests on Spike for pat = nm24 (default) | nm48 | nm816: Berkeley's 54 dense tests and the
#                      nm_sparse_* tests from `tests`, plus the fair benchmark, which it builds from the current
#                      source into scratch (never verification/build or bin). needs spike-lib <pat>, spike-lib
#                      dense24 | dense48 | dense816 (same pattern) and tests
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
#  one N:M chip end to end (pat = a row of nm_table below: nm24 | nm48 | nm816 | ...)
#    pattern <pat>     1. spike stage on the laptop: spike-lib <pat> + dense<suffix>, tests, spike <pat>, and the
#                         streaming bench (<layer>_<suffix>_full/_fixa/_loop, stock's _dense) generated, built and
#                         verified on Spike; every program the server runs goes to <flow>/bin
#                      2. server simulator check: the server's gemmini sources must equal the laptop's, and the
#                         simulator must carry a build-time source list (<sim>.src.sha256) of those sources. Else it
#                         stops and prints the rebuild command; APPROVED_REBUILD=1 rebuilds (backup first; never stock)
#                      3. server Verilator run: 54 dense tests, nm_sparse_*, RTL NEG, benches and fair_perf on the
#                         pattern chip, plus stock benches unless a recorded run on the same stock simulator has the
#                         same program verified (tools/pattern_flow.py reuse); jobs ordered longest first from
#                         recorded wall times, predicted schedule printed; launched under nohup setsid in
#                         ~/sinv/runs/<stamp>-<pat>-srv (tools/pattern_srv_driver.sh), not waited for
#                      -> experiments/streaming/investigate/runs/<stamp>-<pat>-flow/ (DRY_RUN=1: build-scratch/)
#    pattern-finish <pat> <flow>   when the server STATUS is ALL_DONE (else prints progress, exit 3): copy back with
#                      sha256 checks, parse_fixa.py, collect.py and verify_all.py (staging copies, rc 0 required),
#                      the area flow (AREA_FLOW), and <flow>/summary.md (tools/pattern_flow.py summary)
#  pipelines
#    all               spike-lib (nm24, dense24), tests, fair-build, spike, sim nm24, sim nm48, fair all, checks
#                      (needs Berkeley's stock simulator already built; see the note on dense below)
#
# environment variables
#   CHIPYARD_DIR    where chipyard lives (default ~/chipyard; no spaces or ':' allowed)
#   JOBS            make -j for simulator builds (default: picked from free RAM, ~2.5 GB per job)
#   SEEDS           Verilator RANDOM_SEED values for fair / rerun / bench (default "1 2 3"); recorded in run.info
#   PAR             how many simulations run at once (default: number of CPUs, capped at 12). Runs go through
#                      make in sims/verilator, which must never run in parallel, so they are serialized for now
#                      (`spike` does run its dense tests PAR at a time: no make is involved)
#   FORCE_REBUILD=1 required by `sim nm24|nm48|nm816` (a rebuild replaces the simulator; the old one is backed up first)
#   SCRATCH_DIR     scratch for libgemmini, test programs and backups (default <repo>/build-scratch)
#   TIMEOUT_CYCLES  simulation cycle limit (default 150M; chipyard's own 10M is too short)
#   FAIR_BIN        folder with the fair benchmark programs (default verification/build, from fair-build;
#                   verification/bin holds the old programs that produced the withdrawn results). `spike` ignores
#                   it and runs its own fresh build in scratch
#   AREA_YOSYS      yosys for `area` (default ~/gemmini-fixwork/eda/bin/yosys)
#   AREA_LIB        sky130 hd liberty file for `area` (default ~/gemmini-fixwork/pdk/sky130hd/...tt_025C_1v80.lib)
#   PYTHON          python to use (default: chipyard's conda env, which has numpy/pandas/matplotlib)
#   FORCE=1         allow `sim dense` to replace an existing stock simulator (still only from Berkeley's sources)
#   pattern / pattern-finish:
#   STAGES          stages of `pattern` to run (default "spike sim srv"; srv needs sim in the same call)
#   FLOW            existing flow folder to continue (its bin/ from an earlier spike stage is used)
#   DRY_RUN=1       server stages only read (ls, sha256sum, pgrep, source lists) and print every command and the
#                   predicted schedule; no upload, launch or build. Outputs go to build-scratch/pattern-dryrun-*
#   APPROVED_REBUILD=1  allows the server rebuild of the pattern simulator (user approval; AGENTS rule 3)
#   SRV_JOBS        make -j of that rebuild (default 4)
#   QUOTA           simulations this run may hold at once (default: free slots of 12 now); the driver also never
#                   starts a job while 12 simulator-chip* processes run on the server; changeable live (<run>/QUOTA)
#   SCHED_HINTS     schedule hints, one "<program regex>=<factor>:<source>" per line (see default_hints)
#   SPIKE_BENCH_TIMEOUT  seconds per Spike bench run (default 7200)
#   AREA_FLOW       area flow called as "$AREA_FLOW <config> <lib>" (default experiments/streaming/area/synth_area.sh)
#   AREA_LIBS       libraries for it (default nangate45)
#
# notes learned the hard way
#   * Berkeley's stock simulator (GemminiRocketConfig) must be built from UNMODIFIED Gemmini sources: `sim dense`
#     refuses unless all three Gemmini repos sit cleanly at Berkeley's base commits. Chipyard rebuilds a simulator
#     whenever the Scala changes, so every run uses BREAK_SIM_PREREQ=1 and never rebuilds anything.
#   * every elaboration rewrites gemmini_params.h; tests and fair-build copy the committed one back first (no git state change).
#   * the laptop suspends on lid close / idle, which pauses simulations; long steps hold a sleep inhibitor.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cy="${CHIPYARD_DIR:-$HOME/chipyard}"
gem="$cy/generators/gemmini"
lib_dir="$gem/software/libgemmini"
tests_dir="$gem/software/gemmini-rocc-tests"
scratch="${SCRATCH_DIR:-$here/build-scratch}"
bm="$scratch/tests/bareMetalC"  # never gemmini-rocc-tests/build (Berkeley's tree stays as is)
ver="$here/verification"
logs="$here/logs"
runs="$ver/runs"
py="${PYTHON:-$cy/.conda-env/bin/python}"
fair_bin="${FAIR_BIN:-$ver/build}"
[[ "$fair_bin" = /* ]] || fair_bin="$here/$fair_bin"
fair_spike="$scratch/fair"  # `spike` builds the fair benchmark here on every run, so it can't be older than its source
seeds="${SEEDS:-1 2 3}"
stamp="$(date +%Y%m%d-%H%M%S)"
nm_tests=(nm_sparse_debug nm_sparse_matmul nm_sparse_perf nm_sparse_protocol nm_sparse_loop)
# nm_sparse_protocol -DNEG=<n>: illegal uses that must stop the run (Spike abort / RTL assert); 6 is Spike only
neg_spike=(4 6 7 9 10 14) neg_rtl=(4 7 9 10 14)
# the RTL assert message each NEG case must trigger
neg_msg() {
  case "$1" in
    4) echo "index fifo deadlock" ;;
    7|14) echo "differs from the mode its weights were preloaded in" ;;
    9) echo "needs weight stationary dataflow" ;;
    10) echo "sparse-loop-fix: LOOP_WS nm flag (rs1[3]) differs from n:m sparse mode (config_ex rs1[10])" ;;  # N1 of fix-b-spec.md 2.5.6, which took over the LOOP_WS half of the older assert
  esac
}
# nm_sparse_loop -DNEG=<n> (sparse-loop-fix): n / 10 = the assert N1..N14 of fix-b-spec.md 2.5.6 it must trigger.
# 110 and 140 (N11, N14) are illegal only on a dense build and Spike only (fix-b-spec.md changelog 2026-11-13 D1):
# `spike` runs them on the dense libgemmini, never on the n:m libs or on RTL
loop_neg=(10 11 20 30 40 50 51 52 60 61 70 71 72 73 74 80 90 91 92 100 120 121 122 130 131 132 133) loop_neg_dense=(110 140)
# the message (same text in the RTL assert and the Spike abort) each of them must show
loop_neg_msg() {
  case "$(($1 / 10))" in
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
    14) echo "sparse-loop-fix: LOOP_WS_CONFIG_NM (funct 28) on a dense build (nm_sparsity = None)" ;;
    *) die "no sparse-loop-fix message for NEG=$1" ;;
  esac
}
# Berkeley's base commits (what Chipyard 1.14.0 pins); the stock simulator is built only from these
base_gem=8c3f9923 base_lib=ea8f7ed base_tests=7c540b3

say()  { printf '\n== %s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
# the N:M patterns this flow knows, one row each: name, n, m, chipyard config of its chip. A new pattern (e.g. 1:4 once
# its config exists) is one new row; tests, spike-lib, spike, sim and pattern read the table. The suffix of a pattern's
# programs is its name without "nm" (nm24 -> _24); dense<suffix> names the dense-chip model of libgemmini
nm_table="
nm24   2  4  GemminiNMRocketConfig
nm48   4  8  GemminiNM48RocketConfig
nm816  8 16  GemminiNM816RocketConfig
"
pat_names() { awk 'NF {print $1}' <<<"$nm_table"; }
pat_field() { awk -v p="$1" -v f="$2" '$1 == p {print $f; found = 1} END {exit !found}' <<<"$nm_table"; }
cfg_name() {
  [ "$1" = dense ] && { echo GemminiRocketConfig; return; }
  pat_field "$1" 4 || die "unknown config '$1' (want dense or one of: $(pat_names | xargs))"
}
pat_nm() {
  local n m
  if ! n="$(pat_field "$1" 2)" || ! m="$(pat_field "$1" 3)"; then die "unknown pattern '$1' (want one of: $(pat_names | xargs))"; fi
  echo "$n $m"
}
# pattern of a libgemmini build; dense<suffix> (dense24, dense48, ...) models a dense chip but still compiles with a pattern
lib_nm() {
  case "$1" in
    dense*) pat_nm "nm${1#dense}" ;;
    *) pat_nm "$1" ;;
  esac
}
sim_path() { echo "$cy/sims/verilator/simulator-chipyard.harness-$1"; }
# sha256 list of the sources a simulator was built from, written by `sim` at build time next to the simulator
src_list_path() { echo "$(sim_path "$1").src.sha256"; }

case "$cy" in *" "*|*:*) die "chipyard path '$cy' has a space or ':' in it; it has to live somewhere plain" ;; esac
[ -f "$cy/env.sh" ] || die "no env.sh in $cy; did build-setup.sh run? (see README.md, section 1. Install Chipyard)"
for s in $seeds; do [[ "$s" =~ ^[0-9]+$ ]] || die "SEEDS must be whole numbers, got '$s'"; done

# ---------------------------------------------------------------- helpers
# fedora / rhel: conda deactivate first, then env.sh (the chipyard docs say so)
load_env() {
  local base
  base="$(conda info --base 2>/dev/null || echo "$HOME/miniforge3")"
  # conda.sh and env.sh read unset variables, so -u is off while they run
  set +u
  # shellcheck disable=SC1091
  source "$base/etc/profile.d/conda.sh"
  conda deactivate 2>/dev/null || true
  # shellcheck disable=SC1091
  source "$cy/env.sh"
  set -u
  [ -n "${RISCV:-}" ] || die "RISCV not set after sourcing env.sh"
  export LD_LIBRARY_PATH="$RISCV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
}

# libgemmini is built per pattern into scratch and loaded with --extlib; nothing is installed into the toolchain
libgemmini_path() { echo "$scratch/libgemmini-$1/libgemmini.so"; }

need_py() { [ -x "$py" ] || die "no python at $py (set PYTHON=...)"; }
need_sim() { [ -x "$(sim_path "$1")" ] || die "no simulator for $1 at $(sim_path "$1") (./run-flow.sh sim ...)"; }

# verilator compiles take ~2.5 GB each on gemmini
pick_jobs() {
  if [ -n "${JOBS:-}" ]; then echo "$JOBS"; return; fi
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
# copy-based (a read-only `git show` into scratch, then cp): no git state is touched
restore_params_h() {
  local f="$tests_dir/include/gemmini_params.h" ref="$scratch/gemmini_params.h.committed"
  mkdir -p "$scratch"
  git -C "$tests_dir" show HEAD:include/gemmini_params.h > "$ref" || die "can't read the committed gemmini_params.h"
  cmp -s "$ref" "$f" && return 0
  echo "  restoring the committed include/gemmini_params.h (the last elaboration rewrote it); the current one is saved in build-scratch/"
  cp "$f" "$scratch/gemmini_params.h.before-restore-$stamp"
  cp "$ref" "$f"
}

# all make in sims/verilator goes through one lock: two makes there at once corrupt the build tree
sims_make() {
  command -v flock >/dev/null || die "flock is needed to serialize make in sims/ (util-linux)"
  mkdir -p "$scratch"
  (cd "$cy/sims/verilator" && flock "$scratch/sims-make.lock" make "$@")
}

# cycle limit of one program: TIMEOUT_CYCLES (default 150M), raised for the tests known to need more
prog_timeout() {
  local t="${TIMEOUT_CYCLES:-150000000}" need=0
  case "$(basename "$1")" in
    # full 22 cases passed at 600M (investigate/runs/20261115-225958-fixbfail-srv); cases 7-17 alone took 28,576,528 / 29,693,573 cycles (20261115-230636-fixbfail2-srv CYC lines)
    # bank-split-fix sources: nm_sparse_loop_24 estimated ~162M sim cycles, 600M floor = 3.7x margin (worklogs/pattern-flow.md step 2)
    nm_sparse_loop_[0-9]*-baremetal) [[ "$(basename "$1")" =~ ^nm_sparse_loop_[0-9]+-baremetal$ ]] && need=600000000 ;;
    # never finished within 150M on any chip (investigate/runs/20261113-160015-fixb-srv, fixb-verify.md Verdict); unresolved
    # sim caps count a 1 GHz clock, the chip runs at 500 MHz (worklogs/rot180-diag.md Step 6): rot180 needs ~390M, neg_padding ~165M sim cycles [E]
    conv_with_input_dilation*-baremetal) need=1000000000 ;;
  esac
  [ "$t" -ge "$need" ] && echo "$t" || echo "$need"
}

# run one binary on one (already built) simulator: sim_run <cfg> <binary> <log> [extra make args...]
sim_run() {
  local cfg="$1" bin="$2" log="$3"; shift 3
  sims_make CONFIG="$cfg" run-binary-fast LOADMEM=1 BREAK_SIM_PREREQ=1 \
     TIMEOUT_CYCLES="$(prog_timeout "$bin")" BINARY="$bin" "$@" > "$log" 2>&1
}

# simulation queue: queue <name> <cfg> <binary> <log> <seed> <expected lines (grep -E, one per line)>
q_name=() q_cfg=() q_bin=() q_log=() q_seed=() q_expect=() q_mode=()
# 7th arg "fail": the run must exit non-zero (an RTL assert), and the expected lines must still be there
queue() {
  case "$3$4" in *" "*|*:*) die "make can't take paths with spaces or ':': $3 / $4" ;; esac
  [ -f "$3" ] || die "missing program $3"
  q_name+=("$1"); q_cfg+=("$2"); q_bin+=("$3"); q_log+=("$4"); q_seed+=("$5"); q_expect+=("$6"); q_mode+=("${7:-pass}")
}

# PAR: default nproc, never more than 12 simulations at once (project limit)
clamp_par() {
  local p="${PAR:-$(nproc)}"
  [[ "$p" =~ ^[0-9]+$ ]] && [ "$p" -ge 1 ] || die "PAR must be a whole number >= 1, got '$p'"
  [ "$p" -le 12 ] || { echo "  note: PAR=$p clamped to 12" >&2; p=12; }
  echo "$p"
}

# run the queue, PAR at a time; fail if any run exits non-zero or lacks an expected line
run_queue() {
  local par n="${#q_name[@]}" i fails=0
  par="$(clamp_par)"
  # every run is a make in sims/ (serialized by sims_make), so more than one at a time only adds waiting
  [ "$par" -le 1 ] || { echo "  note: PAR=$par requested; runs are serialized (make in sims/ must not run in parallel)"; par=1; }
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
  local run="$1" r c s l kv; shift
  {
    echo "stamp=$stamp"
    echo "seeds=$seeds"
    echo "timeout_cycles=${TIMEOUT_CYCLES:-150000000} (raised per program by prog_timeout: nm_sparse_loop_NN, conv_with_input_dilation* >= 300000000)"
    for kv in "$@"; do echo "$kv"; done
    for r in "$here" "$gem" "$lib_dir" "$tests_dir"; do
      echo "git.$(basename "$r")=$(git -C "$r" rev-parse HEAD)$(git -C "$r" diff --quiet HEAD && echo '' || echo ' (uncommitted changes)')"
    done
    for c in "${q_cfg[@]}"; do echo "$c"; done | sort -u | while read -r c; do
      s="$(sim_path "$c")"
      echo "sim.$c=$(date -r "$s" '+%Y-%m-%dT%H:%M:%S') sha256:$(sha256sum "$s" | cut -c1-16)"
      # the list `sim` took at build time; it names the simulator it belongs to, so a stale list is flagged
      l="$(src_list_path "$c")"
      if [ ! -f "$l" ]; then echo "src.$c.sha256list=none (simulator not built by ./run-flow.sh sim)"
      elif [ "$(sed -n 's/^# sim sha256=//p' "$l")" = "$(sha256sum "$s" | cut -d' ' -f1)" ]; then
        echo "src.$c.sha256list=$(sha256sum "$l" | cut -d' ' -f1) ($l, taken at build time)"
      else echo "src.$c.sha256list=STALE ($l does not name this simulator's sha256)"; fi
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
  echo "CONDA_DEFAULT_ENV=${CONDA_DEFAULT_ENV:-}"
  echo "RISCV=$RISCV"
  for t in spike verilator firtool riscv64-unknown-elf-gcc; do
    printf '  %-24s %s\n' "$t" "$(command -v "$t" || echo MISSING)"
  done
  for c in nm24 nm48 nm816 dense24 dense48 dense816; do
    if [ -f "$(libgemmini_path "$c")" ]; then echo "  libgemmini $c built: $(libgemmini_path "$c")"
    else echo "  libgemmini $c MISSING (run spike-lib $c)"; fi
  done
  say "simulators"
  local c s
  for c in dense nm24 nm48 nm816; do
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
  local pat="${1:-nm24}" n m log="$logs/runs/libgemmini-$stamp.log" out dense=""
  lib_nm "$pat" > /dev/null
  read -r n m <<<"$(lib_nm "$pat")"
  case "$pat" in dense*) dense=1 ;; esac
  load_env
  mkdir -p "$logs/runs"
  out="$(dirname "$(libgemmini_path "$pat")")"
  mkdir -p "$out"
  say "building libgemmini (spike extension) for $n:$m${dense:+, dense chip model} in ${out#"$here"/}, not installed -> ${log#"$here"/}"
  # -B: the .so only depends on gemmini.cc, so a pattern change alone would not rebuild it; VPATH builds outside the source tree
  make -B -f "$lib_dir/Makefile" -C "$out" VPATH="$lib_dir" libgemmini.so NM_N="$n" NM_M="$m" NM_DENSE_BUILD="$dense" > "$log" 2>&1 ||
    { tail -20 "$log" >&2; die "libgemmini build failed, see $log"; }
  [ -s "$out/libgemmini.so" ] || die "libgemmini.so wasn't built in $out"
  # make ignores a variable its Makefile does not know, so the compile line is the proof of which model was built
  if grep -q -- '-DNM_DENSE_BUILD' "$log"; then [ -n "$dense" ] || die "$pat libgemmini was compiled with -DNM_DENSE_BUILD, see $log"
  else [ -z "$dense" ] || die "$pat libgemmini was compiled without -DNM_DENSE_BUILD (libgemmini Makefile lacks NM_DENSE_BUILD?), see $log"; fi
  echo "  built $out/libgemmini.so ($n:$m${dense:+, dense chip model}); spike loads it with --extlib"
}

# Berkeley's dense tests for normal configs -> the global dense_list (54 names); used by `tests` and `spike`
dense_list=()
dense_tests() {
  local t all no_spad
  # Berkeley's dense list is read from its Makefile (never edited), so it can't drift; nm_* are built below with explicit patterns
  mapfile -t all < <(awk '/^tests = /{f=1;next} f&&/^$/{exit} f{gsub(/[\\\t ]/,""); if ($0 !~ /^nm_/) print}' "$tests_dir/bareMetalC/Makefile")
  # the same Makefile drops the tests that need the external scratchpad on normal configs (its second
  # `runs_baremetal := $(filter-out ...)`); that filter is read too, since they fail on Berkeley's own stock Spike lib
  mapfile -t no_spad < <(sed -n 's/^runs_baremetal := \$(filter-out \(.*\),\$(runs_baremetal))[[:space:]]*$/\1/p' "$tests_dir/bareMetalC/Makefile" |
    tr -s ' \t' '\n\n' | sed -n 's/-baremetal\.run$//p')
  [ "${#no_spad[@]}" -gt 0 ] || die "no 'runs_baremetal := \$(filter-out ...)' line found in gemmini-rocc-tests/bareMetalC/Makefile"
  dense_list=()
  for t in "${all[@]}"; do
    [[ " ${no_spad[*]} " == *" $t "* ]] || dense_list+=("$t")
  done
  [ "${#dense_list[@]}" -eq 54 ] || die "expected 54 dense tests in gemmini-rocc-tests/bareMetalC/Makefile (normal configs: ${#all[@]} listed, without ${no_spad[*]}), found ${#dense_list[@]}"
  dense_no_spad="${no_spad[*]}"
}

# builds only what this flow runs, into scratch: gemmini-rocc-tests' build.sh has no output dir option and would overwrite its build/
step_tests() {
  local t n built
  load_env
  mkdir -p "$bm"
  say "building the flow's test programs into ${bm#"$here"/} (gemmini-rocc-tests/build is left alone)"
  restore_params_h
  dense_tests
  for t in "${dense_list[@]}"; do rv_cc "$tests_dir/bareMetalC/$t.c" "$bm/$t-baremetal"; done
  # every pattern of the sparse tests, with explicit -D flags so they don't depend on the last elaboration
  local p pn pm ps sfxs=()
  for p in $(pat_names); do
    read -r pn pm <<<"$(pat_nm "$p")"; ps="${p#nm}"; sfxs+=("_$ps")
    for t in nm_sparse_sw "${nm_tests[@]}"; do
      rv_cc_nm "$tests_dir/bareMetalC/$t.c" "$bm/${t}_$ps-baremetal" "$pn" "$pm"
    done
    for n in "${neg_spike[@]}"; do
      rv_cc_nm "$tests_dir/bareMetalC/nm_sparse_protocol.c" "$bm/nm_sparse_protocol_neg${n}_$ps-baremetal" "$pn" "$pm" -DNEG="$n"
    done
    for n in "${loop_neg[@]}" "${loop_neg_dense[@]}"; do
      rv_cc_nm "$tests_dir/bareMetalC/nm_sparse_loop.c" "$bm/nm_sparse_loop_neg${n}_$ps-baremetal" "$pn" "$pm" -DNEG="$n"
    done
  done
  built=("$bm"/*-baremetal)
  echo "${#built[@]} bare-metal tests built (${#dense_list[@]} dense, without $dense_no_spad; nm_sparse_*$(printf ' / %s' "${sfxs[@]}" | cut -c4-), N:M checked)"
}

# the four fair benchmark programs from the current source: build_fair <out dir> [pat]
# a pattern other than nm24 / nm48 also builds its own fair_perf_<suffix> (only `spike <pat>` and `pattern <pat>` ask;
# fair-build and the RTL fair runs stay 2:4 / 4:8)
build_fair() {
  local out="$1" pat="${2:-}" pn pm extra=""
  mkdir -p "$out"
  restore_params_h
  rv_cc_nm "$ver/fair_perf.c" "$out/fair_perf_24-baremetal" 2 4
  rv_cc_nm "$ver/fair_perf.c" "$out/fair_perf_48-baremetal" 4 8
  if [ -n "$pat" ] && [ "$pat" != nm24 ] && [ "$pat" != nm48 ]; then
    read -r pn pm <<<"$(pat_nm "$pat")"
    rv_cc_nm "$ver/fair_perf.c" "$out/fair_perf_${pat#nm}-baremetal" "$pn" "$pm"
    extra=" fair_perf_${pat#nm} = $pn:$pm,"
  fi
  rv_cc_nm "$ver/fair_perf.c" "$out/fair_perf_dense_only-baremetal" 2 4 -DDENSE_ONLY
  rv_cc_nm "$ver/berkeley_dense_perf.c" "$out/berkeley_dense_perf-baremetal" 2 4
  echo "  N:M checked: fair_perf_24 = 2:4, fair_perf_48 = 4:8,$extra fair_perf_dense_only = berkeley_dense_perf = 2:4"
}

step_fair_build() {
  local out="$ver/build" n=0 same=0 b
  load_env
  say "building the fair benchmark into ${out#"$here"/}"
  build_fair "$out"
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

# copy the simulator binary and its generated-src aside before a rebuild: backup_sim <config name>
backup_sim() {
  local cfg="$1" b="$scratch/sim-backups/$stamp-$1" s g
  s="$(sim_path "$cfg")"; g="$cy/sims/verilator/generated-src/chipyard.harness.TestHarness.$cfg"
  [ -e "$s" ] || [ -e "$g" ] || { echo "  no existing $cfg simulator or generated-src; nothing to back up"; return 0; }
  mkdir -p "$b"
  if [ -e "$s" ]; then cp -a "$s" "$b/" || die "backup of $s failed"; fi
  if [ -e "$g" ]; then cp -a "$g" "$b/" || die "backup of $g failed"; fi
  if [ -e "$(src_list_path "$cfg")" ]; then cp -a "$(src_list_path "$cfg")" "$b/" || die "backup of the source list failed"; fi
  (cd "$b" && find . -type f -printf '%P\0' | sort -z | xargs -0 sha256sum > SHA256SUMS) || die "checksums of the backup failed"
  echo "  backed up the old $cfg simulator and generated-src to ${b#"$here"/}"
}

# sha256 of every tracked and untracked (not ignored) file of the three gemmini repos, plus their HEADs
src_sha_list() {
  local r
  for r in "$gem" "$lib_dir" "$tests_dir"; do
    echo "# git.$(basename "$r")=$(git -C "$r" rev-parse HEAD)"
    (cd "$r" && git ls-files -co --exclude-standard -z | sort -z |
       while IFS= read -r -d '' f; do if [ -f "$f" ] && [ ! -L "$f" ]; then printf '%s\0' "$f"; fi; done |
       xargs -0 -r sha256sum | sed "s|  |  $(basename "$r")/|")
  done
}

step_sim() {
  local which="${1:-}" cfg jobs log s
  [ -n "$which" ] || die "usage: ./run-flow.sh sim nm24|nm48|nm816|dense"
  cfg="$(cfg_name "$which")"
  s="$(sim_path "$cfg")"
  if [ "$which" = dense ]; then
    if ! { at_base "$gem" "$base_gem" && at_base "$lib_dir" "$base_lib" && at_base "$tests_dir" "$base_tests"; }; then
      die "the stock simulator must be built from Berkeley's unmodified sources: check out $base_gem (gemmini),
$base_lib (libgemmini) and $base_tests (gemmini-rocc-tests) with clean trees, build, then switch back to sparse-nm"
    fi
    [ ! -x "$s" ] || [ "${FORCE:-0}" = 1 ] || die "$cfg already exists; FORCE=1 to rebuild it (from the base sources)"
  fi
  # a rebuild replaces the simulator that recorded results came from: explicit opt-in only
  [ "${FORCE_REBUILD:-0}" = 1 ] || die "sim $which rebuilds a simulator; set FORCE_REBUILD=1 to confirm (the old one is backed up first)"
  # stock must never come from modified sources, whatever FORCE/FORCE_REBUILD say
  if [ "$cfg" = GemminiRocketConfig ] && ! { at_base "$gem" "$base_gem" && at_base "$lib_dir" "$base_lib" && at_base "$tests_dir" "$base_tests"; }; then
    die "refusing to build GemminiRocketConfig (stock) from modified sources"
  fi
  load_env
  mkdir -p "$logs/runs"
  jobs="$(pick_jobs)"
  log="$logs/runs/sim-$cfg-$stamp.log"
  backup_sim "$cfg"
  # source list taken right before the build, so run.info can cite what this simulator was really built from
  src_sha_list > "$log.src.sha256" || die "can't list the gemmini sources"
  stay_awake "building $cfg"
  say "building verilator sim $cfg with -j$jobs -> ${log#"$here"/}"
  if ! sims_make -j"$jobs" CONFIG="$cfg" > "$log" 2>&1; then
    # the OOM killer shows up as a killed compiler; retry slower once
    if grep -qiE "killed|signal 9|out of memory" "$log" && [ "$jobs" -gt 2 ]; then
      say "looks like it ran out of memory, retrying with -j2"
      sims_make -j2 CONFIG="$cfg" >> "$log" 2>&1 || die "sim build failed, see $log"
    else
      die "sim build failed, see $log"
    fi
  fi
  [ -x "$s" ] || die "make succeeded but there is no simulator at $s"
  { cat "$log.src.sha256"; echo "# sim sha256=$(sha256sum "$s" | cut -d' ' -f1)"; } > "$(src_list_path "$cfg")"
  echo "  source list (taken at build time): $(src_list_path "$cfg")"
  ls -la "$s"
}

# ---------------------------------------------------------------- simulate
# spike_loop_neg <extlib> <note> <n>...: each nm_sparse_loop NEG program must abort with exactly its own message
# (grep -F: the texts hold [ ] and *). reads the caller's sfx and log, counts into the caller's fails
spike_loop_neg() {
  local lib="$1" note="$2" n t msg out; shift 2
  for n in "$@"; do
    t="$bm/nm_sparse_loop_neg${n}${sfx}-baremetal"; msg="$(loop_neg_msg "$n")"
    [ -f "$t" ] || die "missing $t (./run-flow.sh tests)"
    if out="$(timeout 120 spike --extlib="$lib" --extension=gemmini "$t" 2>&1)"; then echo "FAIL  loop NEG=$n not caught$note"; fails=$((fails + 1))
    elif grep -qF -- "$msg" <<<"$out"; then echo "pass  loop NEG=$n aborts$note: $msg"
    else echo "FAIL  loop NEG=$n stopped without '$msg'$note"; fails=$((fails + 1)); fi
    echo "$out" >> "$log"
  done
}

step_spike() {
  local pat="${1:-nm24}" sfx log="$logs/runs/spike-$stamp.log" fails=0 t extlib dlib par i ddir spec prog want w miss
  sfx="_${pat#nm}"; pat_nm "$pat" > /dev/null
  load_env
  mkdir -p "$logs/runs"
  extlib="$(libgemmini_path "$pat")"
  [ -f "$extlib" ] || die "missing $extlib (./run-flow.sh spike-lib $pat)"
  dlib="$(libgemmini_path "dense${pat#nm}")"
  [ -f "$dlib" ] || die "missing $dlib (./run-flow.sh spike-lib dense${pat#nm})"
  dense_tests
  for t in "${dense_list[@]}"; do [ -f "$bm/$t-baremetal" ] || die "missing $bm/$t-baremetal (./run-flow.sh tests)"; done
  say "building the fair benchmark for spike into ${fair_spike#"$here"/} (current source; verification/build is not used)"
  build_fair "$fair_spike" "$pat"
  say "spike tests ($pat; libgemmini from ${extlib#"$here"/}) -> ${log#"$here"/}"
  # --extlib must come before --extension or spike also dlopens the installed $RISCV/lib/libgemmini.so (old layout, garbage state)
  # smoke run: the installed lib must never be mapped
  local ld="$scratch/ld-debug.$stamp"
  LD_DEBUG=libs LD_DEBUG_OUTPUT="$ld" spike --extlib="$extlib" --extension=gemmini "$bm/mvin_mvout-baremetal" > /dev/null 2>&1 ||
    die "spike smoke run failed"
  cat "$ld".* 2>/dev/null | grep -q "$RISCV/lib/libgemmini" && die "spike loaded the installed $RISCV/lib/libgemmini.so; results would be wrong"
  grep -q "$extlib" "$ld".* || die "spike did not load $extlib"
  rm -f "$ld".*
  # Berkeley's 54 dense tests on the n:m lib, PAR at a time (plain spike, no make); one output file each, so the
  # log keeps the list order
  par="$(clamp_par)"; ddir="$scratch/spike-dense.$stamp"; mkdir -p "$ddir"
  for ((i = 0; i < ${#dense_list[@]}; i += par)); do
    pids=()
    for t in "${dense_list[@]:i:par}"; do
      ( rc=0; timeout 600 spike --extlib="$extlib" --extension=gemmini "$bm/$t-baremetal" > "$ddir/$t.out" 2>&1 || rc=$?
        echo "$rc" > "$ddir/$t.rc" ) &
      pids+=($!)
    done
    wait "${pids[@]}" || true
    pids=()
  done
  for t in "${dense_list[@]}"; do
    [ -f "$ddir/$t.rc" ] || die "no result for dense test $t in $ddir"
    if [ "$(cat "$ddir/$t.rc")" = 0 ]; then echo "pass  $t"
    else echo "FAIL  $t (exit $(cat "$ddir/$t.rc"))"; fails=$((fails + 1)); fi
    cat "$ddir/$t.out" >> "$log"
  done
  rm -rf "$ddir"
  for t in "$bm/nm_sparse_sw${sfx}-baremetal" \
           "$bm/nm_sparse_matmul${sfx}-baremetal" "$bm/nm_sparse_debug${sfx}-baremetal" "$bm/nm_sparse_perf${sfx}-baremetal" \
           "$bm/nm_sparse_protocol${sfx}-baremetal" "$bm/nm_sparse_loop${sfx}-baremetal"; do
    [ -f "$t" ] || die "missing $t (./run-flow.sh tests)"
    if spike --extlib="$extlib" --extension=gemmini "$t" >> "$log" 2>&1; then echo "pass  $(basename "$t" -baremetal)"
    else echo "FAIL  $(basename "$t" -baremetal)"; fails=$((fails + 1)); fi
  done
  # fair benchmark (the fresh build): a zero exit is not enough, each LOOP_WS variant the program has must be verified
  local out
  for spec in "fair_perf${sfx} dense_loop sparse_loop" "fair_perf_dense_only dense_loop" "berkeley_dense_perf"; do
    read -r prog want <<<"$spec"
    miss=""
    if out="$(spike --extlib="$extlib" --extension=gemmini "$fair_spike/$prog-baremetal" 2>&1)"; then
      for w in $want; do grep -q "^$w matches the cpu reference" <<<"$out" || miss+=" $w"; done
      if [ -z "$miss" ]; then echo "pass  $prog${want:+ ($want verified)}"
      else echo "FAIL  $prog: no 'matches the cpu reference' line for$miss"; fails=$((fails + 1)); fi
    else echo "FAIL  $prog"; fails=$((fails + 1)); fi
    echo "$out" >> "$log"
  done
  # illegal uses: Spike must abort with a GEMMINI: message (not a warning)
  local n
  for n in "${neg_spike[@]}"; do
    t="$bm/nm_sparse_protocol_neg${n}${sfx}-baremetal"
    [ -f "$t" ] || die "missing $t (./run-flow.sh tests)"
    if out="$(timeout 120 spike --extlib="$extlib" --extension=gemmini "$t" 2>&1)"; then echo "FAIL  NEG=$n not caught"; fails=$((fails + 1))
    elif grep -q '^GEMMINI: [^w]' <<<"$out"; then echo "pass  NEG=$n aborts: $(grep -m1 '^GEMMINI: [^w]' <<<"$out")"
    else echo "FAIL  NEG=$n stopped without a GEMMINI abort"; fails=$((fails + 1)); fi
    echo "$out" >> "$log"
  done
  spike_loop_neg "$extlib" "" "${loop_neg[@]}"
  # N11 / N14 exist only in the dense model: the same programs, on the dense libgemmini of this pattern
  spike_loop_neg "$dlib" " (dense lib ${dlib#"$here"/})" "${loop_neg_dense[@]}"
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
  say "fair benchmark ($which, seeds: $seeds) -> ${run#"$here"/}   (each takes ~15-40 min; $(nproc) CPUs, PAR=$(clamp_par))"
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
    for n in "${loop_neg[@]}"; do
      [ -f "$bm/nm_sparse_loop_neg${n}_${c#nm}-baremetal" ] || die "missing loop NEG=$n program (./run-flow.sh tests)"
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
        "$(printf '%s\n' 'Assertion failed' "$(neg_msg "$n" | sed 's/[][()*.?+{}|^$\\]/\\&/g')")" fail
    done
    # the expected lines are grep -E patterns: the message goes in with its ERE specials escaped (above too)
    for n in "${loop_neg[@]}"; do
      cp "$bm/nm_sparse_loop_neg${n}${sfx}-baremetal" "$run/bin/"
      queue "$c-loopneg$n" "$(cfg_name $c)" "$run/bin/nm_sparse_loop_neg${n}${sfx}-baremetal" "$run/loopneg-$c-$n.seed$s.log" "$s" \
        "$(printf '%s\n' 'Assertion failed' "$(loop_neg_msg "$n" | sed 's/[][()*.?+{}|^$\\]/\\&/g')")" fail
    done
  done
  write_info "$run" "step=rerun"
  stay_awake "re-running the RTL tests"
  say "RTL tests: ${nm_tests[*]} + ${#neg_rtl[@]} + ${#loop_neg[@]} illegal-use asserts, nm24 and nm48 (seeds: $seeds) -> ${run#"$here"/}"
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
  sims_make CONFIG=GemminiRocketConfig run-binary BREAK_SIM_PREREQ=1 \
     BINARY="$bm/matmul-baremetal" TIMEOUT_CYCLES="${TIMEOUT_CYCLES:-150000000}" > "$log" 2>&1 ||
    die "baseline simulation failed, see $log"
  grep -E "PASSED|FAILED|Completed after" "$log" || true
  grep -q "PASSED" "$log" || die "baseline log has no PASSED line, see $log"
}

# last number matching a grep -oP pattern in a file (or stdin: log_num <pat> [file]); aborts when there is none
log_num() {
  local v
  if [ "$#" -ge 2 ]; then v="$(grep -oP "$1" "$2" | tail -1 || true)"; else v="$(grep -oP "$1" | tail -1 || true)"; fi
  [[ "$v" =~ ^[0-9]+$ ]] || die "no number matching '$1' in ${2:-the row}"
  echo "$v"
}

# the ORIGINAL benchmark (its loop slowed dense mode more than sparse; superseded by `fair`), into its own run folder
step_bench() {
  local which="${1:-nm24}" cfg sfx run t s log tmp rows
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
  # cycles.csv from the logs, written to a temp file first so an abort never leaves half a table; a missing number aborts
  tmp="$(mktemp "$run/.cycles.XXXXXX")"
  echo "timestamp,config,test,variant,seed,status,total_cycles,array_busy_cycles,tiles" > "$tmp"
  for s in $seeds; do
    log="$run/nm_sparse_matmul.seed$s.log"
    # a row counts only if the program verified its output
    grep -q '^nm_sparse_matmul passed$' "$log" || die "no 'nm_sparse_matmul passed' in $log"
    echo "$stamp,$cfg,nm_sparse_matmul,dense,$s,passed,$(log_num 'dense\s+cycles: \K[0-9]+' "$log"),,"
    echo "$stamp,$cfg,nm_sparse_matmul,sparse,$s,passed,$(log_num 'sparse cycles: \K[0-9]+' "$log"),,"
    log="$run/nm_sparse_perf.seed$s.log"
    grep -q '^nm_sparse_perf passed$' "$log" || die "no 'nm_sparse_perf passed' in $log"
    rows=0
    while read -r name _ total _ _ _ tiles _ _ rest; do
      [[ "$total" =~ ^[0-9]+$ && "$tiles" =~ ^[0-9]+$ ]] || die "unparsable total/tiles for '$name' in $log"
      echo "$stamp,$cfg,nm_sparse_perf,$name,$s,passed,$total,$(log_num 'ex_active=\K[0-9]+' <<<"$rest"),$tiles"
      rows=$((rows + 1))
    done < <(grep -E '^[a-z_]+ +total' "$log" || true)
    [ "$rows" -gt 0 ] || die "no '<variant> total ...' rows in $log"
  done >> "$tmp"
  mv "$tmp" "$run/cycles.csv"
  write_sums "$run"
  echo "all runs passed; $(($(wc -l < "$run/cycles.csv") - 1)) rows in ${run#"$here"/}/cycles.csv"
}

# ---------------------------------------------------------------- pattern: one N:M chip end to end
# ./run-flow.sh pattern <pat>: Spike stage on the laptop, server simulator check (rebuild only with APPROVED_REBUILD=1),
# Verilator run on the server (launched, not waited for); ./run-flow.sh pattern-finish <pat> <flow folder> later copies
# the run back, runs the parsers and the area flow and writes the summary. See the header for the variables.
streaming="$here/experiments/streaming"
tools="$streaming/tools"
srv_host="ai-user@ai-1769.floridapoly.org"
srv_opts=(-o "ControlPath=/tmp/claude-1000/cm-%C" -o BatchMode=yes)
srv_cy="/home/ai-user/chipyard"
srv_runs="/home/ai-user/sinv/runs"
srv_cap=12  # project limit: simulations at once on the server, all agents together
bench_layers=(edge small bert_qkv bert_ffn1 bert_ffn2 rn50_conv)
# schedule hints (predicted wall time only, never a cycle budget): <program regex>=<factor>:<source>. SCHED_HINTS (one
# per line) replaces them; clear it once a run on the current sources is recorded, or the factor counts twice
default_hints="nm_sparse_loop_[0-9]+=2.576:bank-split-impl.md step 9, nm_sparse_loop_24 Spike instructions 59,512,572 (rocc-tests 2ad1fd3) / 23,101,494 (22158bf)"
# gemmini_params.h is rewritten by every elaboration (see restore_params_h); it is an output, so source comparisons skip it
src_skip='  gemmini-rocc-tests/include/gemmini_params.h$'

dry() { [ "${DRY_RUN:-0}" = 1 ]; }
srv() { ssh "${srv_opts[@]}" "$srv_host" "$@"; }
srv_up() {
  ssh "${srv_opts[@]}" -O check "$srv_host" 2>/dev/null && return 0
  die "the SSH socket to $srv_host is down (VPN dropped?). Stop here; reconnect with
  sudo -E gpclient connect --browser default vpn.floridapoly.edu
  ssh -o ControlMaster=yes -o ControlPath=/tmp/claude-1000/cm-%C -o ControlPersist=12h -fN $srv_host"
}
# stdin script run by bash on the server with the chipyard env loaded (read-only uses)
srv_env='set +u; source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh > /dev/null; set -u'
srv_src_list() {
  { echo "$srv_env"
    echo "gem=$srv_cy/generators/gemmini lib_dir=$srv_cy/generators/gemmini/software/libgemmini tests_dir=$srv_cy/generators/gemmini/software/gemmini-rocc-tests"
    declare -f src_sha_list
    echo src_sha_list; } | srv 'bash -s'
}
src_files() { grep -v '^#' "$1" | grep -v -- "$src_skip" | sort || true; }
in_stages() { [[ " ${STAGES:-spike sim srv} " == *" $1 "* ]]; }

# the streaming bench for one pattern: data, programs (_full/_fixa/_loop on the pattern chip, _dense for stock) and a
# Spike run of each, all verified. pattern_bench_spike <out> <pat>
pattern_bench_spike() {
  local out="$1" pat="$2" n m sfx d L v data b want got rc fails=0 par i extlib dlib t
  read -r n m <<<"$(pat_nm "$pat")"; sfx="${pat#nm}"
  d="$out/bench"; mkdir -p "$d/data" "$d/bin" "$d/logs" "$d/ref"
  say "streaming bench for $n:$m: data, programs and Spike runs -> ${d#"$here"/}"
  # gen_data.py with only this pattern in PATTERNS: its data is the same as in a full run (pruning is per pattern, the
  # random draws are per layer)
  "$py" -I -c "import sys; sys.path.insert(0, sys.argv[1]); import gen_data as g; g.PATTERNS = {sys.argv[2]: (int(sys.argv[3]), int(sys.argv[4]))}; sys.argv = ['gen_data.py', sys.argv[5]]; g.main()" \
    "$streaming/gen" "$sfx" "$n" "$m" "$d/data" > "$d/gen_data.out" || die "gen_data.py failed, see $d/gen_data.out"
  restore_params_h
  for L in "${bench_layers[@]}"; do
    data="$d/data/$L/$sfx/data.h"
    [ -f "$data" ] || die "gen_data.py wrote no $data"
    cp "$d/data/$L/$sfx/ref.json" "$d/ref/${L}_$n$m.json"  # collect.py reads ref/<layer>_<n><m>.json
    rv_cc_nm "$streaming/src/stream_bench.c" "$d/bin/${L}_${sfx}_full-baremetal" "$n" "$m" -DSBENCH_DATA=\""$data"\" -DRUN_MASK=7
    rv_cc_nm "$streaming/src/stream_bench.c" "$d/bin/${L}_${sfx}_fixa-baremetal" "$n" "$m" -DSBENCH_DATA=\""$data"\" -DRUN_MASK=8
    rv_cc_nm "$streaming/src/stream_bench.c" "$d/bin/${L}_${sfx}_loop-baremetal" "$n" "$m" -DSBENCH_DATA=\""$data"\" -DRUN_MASK=16
    rv_cc_nm "$streaming/src/stream_bench.c" "$d/bin/${L}_${sfx}_dense-baremetal" "$n" "$m" -DSBENCH_DATA=\""$data"\" -DRUN_MASK=3 -DDENSE_ONLY
    # the four builds differ only in volatile flags (as in scripts/build.sh): same .text, so one program is measured
    want=""
    for v in full fixa loop dense; do
      b="$(mktemp)"; riscv64-unknown-elf-objcopy -O binary -j .text "$d/bin/${L}_${sfx}_$v-baremetal" "$b"
      got="$(sha256sum < "$b" | cut -c1-16)"; rm -f "$b"
      [ -n "$want" ] || want="$got"
      [ "$got" = "$want" ] || die "$L: .text of ${L}_${sfx}_$v differs from ${L}_${sfx}_full ($got vs $want)"
    done
    echo "  $L: 4 programs (_full _fixa _loop _dense), .text identical (sha256 $want)"
  done
  extlib="$(libgemmini_path "$pat")"; dlib="$(libgemmini_path "dense$sfx")"
  par="$(clamp_par)"
  local progs=()
  for L in "${bench_layers[@]}"; do for v in full fixa loop dense; do progs+=("${L}_${sfx}_$v"); done; done
  for ((i = 0; i < ${#progs[@]}; i += par)); do
    pids=()
    for t in "${progs[@]:i:par}"; do
      # _dense is the stock chip's program: it runs on the dense-chip model of the same pattern
      lib="$extlib"; [[ "$t" == *_dense ]] && lib="$dlib"
      ( rc=0; timeout "${SPIKE_BENCH_TIMEOUT:-7200}" spike --extlib="$lib" --extension=gemmini "$d/bin/$t-baremetal" \
          > "$d/logs/$t.log" 2>&1 || rc=$?; echo "$rc" > "$d/logs/$t.rc" ) &
      pids+=($!)
    done
    wait "${pids[@]}" || true
    pids=()
  done
  for t in "${progs[@]}"; do
    rc="$(cat "$d/logs/$t.rc" 2>/dev/null || echo none)"
    got="$(grep -E '^sbench passed \(([0-9]+) of \1 runs verified\)$' "$d/logs/$t.log" || true)"
    if [ "$rc" = 0 ] && [ -n "$got" ]; then echo "pass  $t  $got"
    else echo "FAIL  $t (exit $rc; see ${d#"$here"/}/logs/$t.log)"; fails=$((fails + 1)); fi
  done
  [ "$fails" -eq 0 ] || die "$fails Spike bench run(s) failed"
}

# Spike stage: libs, test programs, `spike <pat>`, the bench; then every program the server runs goes to <out>/bin
pattern_spike() {
  local out="$1" pat="$2" sfx t n f
  sfx="${pat#nm}"
  export PAR="${PAR:-4}"  # the laptop CPU is shared
  step_spike_lib "$pat"; cp "$logs/runs/libgemmini-$stamp.log" "$out/libgemmini-$pat.log"
  step_spike_lib "dense$sfx"; cp "$logs/runs/libgemmini-$stamp.log" "$out/libgemmini-dense$sfx.log"
  step_tests
  step_spike "$pat"
  cp "$logs/runs/spike-$stamp.log" "$out/spike.log"
  pattern_bench_spike "$out" "$pat"
  say "programs for the server -> ${out#"$here"/}/bin"
  mkdir -p "$out/bin"
  dense_tests
  local files=()
  for t in "${dense_list[@]}"; do files+=("$bm/$t-baremetal"); done
  for t in nm_sparse_sw "${nm_tests[@]}"; do files+=("$bm/${t}_$sfx-baremetal"); done
  for n in "${neg_rtl[@]}"; do files+=("$bm/nm_sparse_protocol_neg${n}_$sfx-baremetal"); done
  for n in "${loop_neg[@]}"; do files+=("$bm/nm_sparse_loop_neg${n}_$sfx-baremetal"); done
  files+=("$fair_spike/fair_perf_$sfx-baremetal" "$fair_spike/fair_perf_dense_only-baremetal" "$fair_spike/berkeley_dense_perf-baremetal")
  files+=("$out/bench/bin/"*-baremetal)
  for f in "${files[@]}"; do [ -f "$f" ] || die "missing program $f"; cp "$f" "$out/bin/"; done
  (cd "$out/bin" && sha256sum -- *-baremetal) > "$out/bin.sha256"
  {
    echo "stamp=$stamp"; echo "pattern=$pat"
    for t in "$pat" "dense$sfx"; do echo "libgemmini.$t=$(sha256sum "$(libgemmini_path "$t")" | cut -d' ' -f1)"; done
    for f in "$here" "$gem" "$lib_dir" "$tests_dir"; do
      echo "git.$(basename "$f")=$(git -C "$f" rev-parse HEAD)$(git -C "$f" diff --quiet HEAD && echo '' || echo ' (uncommitted changes)')"
    done
    echo "spike.log=spike.log ($(grep -c '^' "$out/spike.log") lines); programs=$(wc -l < "$out/bin.sha256") (bin.sha256)"
  } > "$out/spike.info"
  touch "$out/spike.ok"
  echo "  Spike stage passed; $(wc -l < "$out/bin.sha256") programs in ${out#"$here"/}/bin"
}

# simulator check on the server; sets sim_ok=1 when the pattern simulator was built by pattern_srv_build.sh from
# exactly the sources the laptop has (gemmini_params.h aside). Otherwise stops, or rebuilds with APPROVED_REBUILD=1
pattern_sim() {
  local out="$1" pat="$2" cfg="$3" s ndiff msg="" cmd
  srv_up
  s="$srv_cy/sims/verilator/simulator-chipyard.harness-$cfg"
  say "server simulator check: $cfg"
  src_sha_list > "$out/src.laptop.sha256"
  srv_src_list > "$out/src.server.sha256" || die "could not list the server's gemmini sources"
  diff <(src_files "$out/src.laptop.sha256") <(src_files "$out/src.server.sha256") > "$out/src.diff-laptop-server.txt" || true
  ndiff="$(grep -c '^[<>]' "$out/src.diff-laptop-server.txt" || true)"
  echo "  laptop sources: $(src_files "$out/src.laptop.sha256" | wc -l) files; server: $(src_files "$out/src.server.sha256" | wc -l) files; differing lines: $ndiff (${out#"$here"/}/src.diff-laptop-server.txt)"
  sim_sha="$(srv "sha256sum $s 2>/dev/null | cut -d' ' -f1" || true)"
  rm -f "$out/src.simbuild.sha256"
  srv "cat $s.src.sha256 2>/dev/null" > "$out/src.simbuild.sha256" || rm -f "$out/src.simbuild.sha256"
  [ -s "$out/src.simbuild.sha256" ] || rm -f "$out/src.simbuild.sha256"
  sim_ok=0
  if [ "$ndiff" -gt 0 ]; then
    echo "  the server's gemmini sources differ from the laptop's ($ndiff lines in ${out#"$here"/}/src.diff-laptop-server.txt)"
  fi
  if [ -z "$sim_sha" ]; then msg="no $cfg simulator on the server"
  elif [ ! -f "$out/src.simbuild.sha256" ]; then msg="the $cfg simulator has no build-time source list ($s.src.sha256), so its sources are not proven"
  elif [ "$(sed -n 's/^# sim sha256=//p' "$out/src.simbuild.sha256")" != "$sim_sha" ]; then msg="$s.src.sha256 names another simulator (stale list)"
  elif ! diff -q <(src_files "$out/src.simbuild.sha256") <(src_files "$out/src.server.sha256") > /dev/null; then
    msg="the $cfg simulator was built from other sources than the server has now"
  else sim_ok=1; fi
  [ -z "$msg" ] || echo "  simulator: $msg"
  if [ "$ndiff" -gt 0 ]; then
    sim_ok=0
    msg="sync the server's three gemmini repos to the laptop's commits first (this script does not sync), then rerun"
    dry && { echo "  [dry-run] would STOP: $msg"; return 0; }
    die "$msg"
  fi
  if [ "$sim_ok" = 1 ]; then echo "  ok: $cfg sha256 $sim_sha was built from the current sources (build-time list matches)"; return 0; fi
  cmd="STAGES=\"sim srv\" FLOW=$out APPROVED_REBUILD=1 ./run-flow.sh pattern $pat"
  if [ "${APPROVED_REBUILD:-0}" != 1 ] || dry; then
    if dry; then echo "  [dry-run] would STOP: $msg. Rebuild (user approval needed): $cmd"; pattern_rebuild "$out" "$cfg"; return 0; fi
    die "$msg.
  A rebuild replaces the simulator (backup of it and its generated-src first). With the user's approval run:
    $cmd"
  fi
  pattern_rebuild "$out" "$cfg"
  pattern_sim "$out" "$pat" "$cfg"
  [ "$sim_ok" = 1 ] || die "the rebuilt $cfg simulator still does not match the sources"
}

pattern_rebuild() {
  local out="$1" cfg="$2" d="/home/ai-user/sinv/builds/$stamp-$2" st j="${SRV_JOBS:-4}"
  [ "$cfg" != GemminiRocketConfig ] || die "refusing to build the stock simulator"
  say "rebuilding $cfg on the server in $d (make -j$j; backup first)"
  declare -f src_sha_list > "$out/src_sha_list.sh"
  if dry; then
    echo "  [dry-run] ssh: mkdir -p $d; copy pattern_srv_build.sh and src_sha_list.sh there"
    echo "  [dry-run] ssh: cd $d && nohup setsid bash pattern_srv_build.sh $cfg $j > build.out 2>&1 < /dev/null &"
    echo "  [dry-run] then wait for $d/STATUS = BUILD_DONE (polled every 60 s), and check the simulator again"
    return 0
  fi
  srv "mkdir -p $d"
  srv "cat > $d/pattern_srv_build.sh" < "$tools/pattern_srv_build.sh"
  srv "cat > $d/src_sha_list.sh" < "$out/src_sha_list.sh"
  srv "cd $d && (nohup setsid bash pattern_srv_build.sh $cfg $j > build.out 2>&1 < /dev/null &)" < /dev/null
  echo "  started; waiting for $d/STATUS (an SSH drop stops this wait, not the build)"
  while :; do
    sleep 60
    st="$(srv "cat $d/STATUS 2>/dev/null" || die "lost the server while waiting for the build ($d keeps running)")"
    case "$st" in
      BUILD_DONE*) echo "  $st"; break ;;
      BUILD_FAILED*) die "server build failed: $st (see $d/build.log)" ;;
    esac
  done
  echo "  backup and logs: $d"
}

# the job plan of one pattern (TSV, see tools/pattern_flow.py): pattern chip and stock
pattern_plan() {
  local pat="$1" cfg="$2" sfx t n L v s s1 p
  sfx="${pat#nm}"; s1="${seeds%% *}"
  dense_tests
  printf 'chip\tcfg\tprogram\tseed\ttimeout\tkind\texpect\n'
  row() { printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$(prog_timeout "$3")" "$5" "${6:-}"; }
  for t in "${dense_list[@]}"; do row "$pat" "$cfg" "$t-baremetal" "$s1" dense; done
  for t in nm_sparse_sw "${nm_tests[@]}"; do row "$pat" "$cfg" "${t}_$sfx-baremetal" "$s1" sparse "^$t passed$"; done
  for n in "${neg_rtl[@]}"; do row "$pat" "$cfg" "nm_sparse_protocol_neg${n}_$sfx-baremetal" "$s1" neg "$(neg_msg "$n")"; done
  for n in "${loop_neg[@]}"; do row "$pat" "$cfg" "nm_sparse_loop_neg${n}_$sfx-baremetal" "$s1" neg "$(loop_neg_msg "$n")"; done
  for L in "${bench_layers[@]}"; do
    for v in full fixa loop; do row "$pat" "$cfg" "${L}_${sfx}_$v-baremetal" "$s1" bench; done
    row stock GemminiRocketConfig "${L}_${sfx}_dense-baremetal" "$s1" bench
  done
  for s in $seeds; do
    row "$pat" "$cfg" "fair_perf_$sfx-baremetal" "$s" fair
    # sameprog: our chip with sparsity off, Berkeley's program (verify_all.py section D)
    row "$pat" "$cfg" "fair_perf_dense_only-baremetal" "$s" fair
    for p in fair_perf_dense_only berkeley_dense_perf; do row stock GemminiRocketConfig "$p-baremetal" "$s" fair; done
  done
}

# server stage: plan, stock reuse, schedule, upload, launch (nothing launched under DRY_RUN=1)
pattern_srv() {
  local out="$1" pat="$2" cfg="$3" bindir="$4" sfx rrun info running free quota slots hist=() hints=() h progs=()
  sfx="${pat#nm}"
  srv_up
  [ -f "$(dirname "$bindir")/spike.ok" ] || die "no passed Spike stage at $(dirname "$bindir") (run the spike stage, or FLOW=<flow folder>)"
  say "server Verilator stage: $pat ($cfg) + stock"
  pattern_plan "$pat" "$cfg" > "$out/jobs.plan.tsv"
  info="$(srv "for c in $cfg GemminiRocketConfig; do s=$srv_cy/sims/verilator/simulator-chipyard.harness-\$c; if [ -x \$s ]; then echo \"\$c \$(date -r \$s +%Y-%m-%dT%H:%M:%S) \$(sha256sum \$s | cut -d' ' -f1)\"; else echo \"\$c MISSING MISSING\"; fi; done")"
  read -r _ sim_mtime sim_sha <<<"$(grep "^$cfg " <<<"$info")"
  read -r _ stock_mtime stock_sha <<<"$(grep '^GemminiRocketConfig ' <<<"$info")"
  [ "$stock_sha" != MISSING ] || die "no stock simulator on the server"
  echo "  $cfg: $sim_mtime sha256 $sim_sha; stock: $stock_mtime sha256 $stock_sha"
  "$py" "$tools/pattern_flow.py" reuse --plan "$out/jobs.plan.tsv" --bin "$bindir" --runs-root "$streaming/investigate/runs" \
    --stock-sha "$stock_sha" --objcopy "$(command -v riscv64-unknown-elf-objcopy)" \
    --out "$out/jobs.after-reuse.tsv" --reused "$out/stock-reused.tsv" || die "stock reuse check failed"
  running="$(srv "pgrep -fc '^[^ ]*simulator-chip' || true")"
  free=$((srv_cap - running))
  quota="${QUOTA:-$free}"
  [[ "$quota" =~ ^[0-9]+$ ]] || die "QUOTA must be a whole number"
  [ "$quota" -le "$srv_cap" ] || quota="$srv_cap"
  slots="$quota"
  echo "  server: $running simulation(s) running, $free free slot(s) of $srv_cap; quota $quota"
  if [ "$quota" -lt 1 ]; then
    dry || die "no free simulation slot on the server; pass QUOTA=<n> to queue (the driver starts a job only below $srv_cap machine-wide)"
    slots="$srv_cap"; echo "  [dry-run] no free slot now; the schedule below assumes $slots slots"
  fi
  for h in "$streaming"/investigate/runs/*-srv; do [ -f "$h/jobs.tsv" ] && hist+=("$h"); done
  while IFS= read -r h; do [ -z "$h" ] || hints+=(--hint "$h"); done <<<"${SCHED_HINTS-$default_hints}"
  "$py" "$tools/pattern_flow.py" schedule --plan "$out/jobs.after-reuse.tsv" --slots "$slots" --sfx "$sfx" \
    --history "${hist[@]}" "${hints[@]}" --last '^conv_with_(input|kernel)_dilation' --out "$out/jobs.ordered.tsv" | tee "$out/schedule.txt"
  rrun="$srv_runs/$stamp-$pat-srv"
  mapfile -t progs < <(tail -n +2 "$out/jobs.ordered.tsv" | cut -f3 | sort -u)
  # run.info: what this run is made of, taken now (the simulator's own source list was taken at its build)
  {
    echo "stamp=$(basename "$rrun")"
    echo "pattern=$pat n:m=$(pat_nm "$pat" | tr ' ' ':') config=$cfg"
    echo "host=$(srv 'echo "$(hostname) $(uname -r) nproc=$(nproc)"')"
    echo "quota=$quota (QUOTA file; the driver never starts a job while $srv_cap simulator-chip* processes run)"
    for f in "$here" "$gem" "$lib_dir" "$tests_dir"; do
      echo "git.laptop.$(basename "$f")=$(git -C "$f" rev-parse HEAD)$(git -C "$f" diff --quiet HEAD && echo '' || echo ' (uncommitted changes)')"
    done
    echo "src.laptop.sha256list=$(sha256sum < "$out/src.laptop.sha256" | cut -c1-64) (src.laptop.sha256)"
    echo "src.server.sha256list=$(sha256sum < "$out/src.server.sha256" | cut -c1-64) (src.server.sha256, taken at launch)"
    echo "src.server_vs_laptop=$([ -s "$out/src.diff-laptop-server.txt" ] && echo DIFFERENT || echo identical) ($(src_files "$out/src.laptop.sha256" | wc -l) files; include/gemmini_params.h not compared: elaboration output)"
    if [ -f "$out/src.simbuild.sha256" ]; then
      echo "src.$cfg.build_list=$(sha256sum < "$out/src.simbuild.sha256" | cut -c1-64) (sim.src.sha256: taken right before make by pattern_srv_build.sh; names sim sha256 $(sed -n 's/^# sim sha256=//p' "$out/src.simbuild.sha256"))"
    else echo "src.$cfg.build_list=none"; fi
    echo "sim.$pat=$cfg mtime=$sim_mtime sha256=$sim_sha"
    echo "sim.stock=GemminiRocketConfig mtime=$stock_mtime sha256=$stock_sha"
    echo "timeout_cycles=${TIMEOUT_CYCLES:-150000000} per job, raised by prog_timeout (nm_sparse_loop_<NN> >= 600000000, conv_with_input_dilation* >= 1000000000); per-job value in jobs.tsv"
    echo "runner=pattern_srv_driver.sh: the simulator is called directly with make run-binary-fast LOADMEM=1 arguments (no make in sims/)"
    echo "programs=built on the laptop by run-flow.sh (tests, build_fair, pattern_bench_spike), Spike stage passed; sha256 in bin.sha256, checked on the server before launch"
    echo "stock_reused=$(($(wc -l < "$out/stock-reused.tsv") - 1)) job(s), recorded logs listed in stock-reused.tsv"
  } > "$out/srv.run.info"
  awk 'NR == FNR {want[$1]; next} ($2 in want)' <(printf '%s\n' "${progs[@]}") "$(dirname "$bindir")/bin.sha256" > "$out/srv.bin.sha256"
  [ "$(wc -l < "$out/srv.bin.sha256")" -eq "${#progs[@]}" ] || die "bin.sha256 lacks some of the ${#progs[@]} programs"
  echo "$quota" > "$out/QUOTA"
  if dry; then
    say "[dry-run] would create $rrun and launch (nothing done)"
    echo "  [dry-run] ssh: mkdir -p $rrun/bin $rrun/ref"
    echo "  [dry-run] upload ${#progs[@]} programs (tar | python3 tarfile on the server) to $rrun/bin, then: cd $rrun && sha256sum -c --quiet bin.sha256"
    echo "  [dry-run] upload run.info, jobs.ordered.tsv, QUOTA, bin.sha256, src.*.sha256, ref/*.json, pattern_srv_driver.sh"
    echo "  [dry-run] ssh: cd $rrun && nohup setsid bash pattern_srv_driver.sh > driver.out 2>&1 < /dev/null &"
    echo "  dry-run outputs: ${out#"$here"/}/ (jobs.plan.tsv, jobs.after-reuse.tsv, stock-reused.tsv, jobs.ordered.tsv, schedule.txt, srv.run.info)"
    return 0
  fi
  srv "[ ! -e $rrun ]" || die "$rrun already exists on the server"
  srv "mkdir -p $rrun/bin $rrun/ref"
  (cd "$bindir" && tar -cf - -- "${progs[@]}") |
    srv "python3 -c 'import sys, tarfile; tarfile.open(fileobj=sys.stdin.buffer, mode=\"r|\").extractall(\"$rrun/bin\", filter=\"data\")'" ||
    die "program upload failed"
  srv "cat > $rrun/run.info" < "$out/srv.run.info"
  srv "cat > $rrun/jobs.ordered.tsv" < "$out/jobs.ordered.tsv"
  srv "cat > $rrun/QUOTA" < "$out/QUOTA"
  srv "cat > $rrun/bin.sha256" < "$out/srv.bin.sha256"
  srv "cat > $rrun/src.laptop.sha256" < "$out/src.laptop.sha256"
  srv "cat > $rrun/src.server.sha256" < "$out/src.server.sha256"
  [ ! -f "$out/src.simbuild.sha256" ] || srv "cat > $rrun/sim.src.sha256" < "$out/src.simbuild.sha256"
  for h in "$(dirname "$bindir")"/bench/ref/*.json; do srv "cat > $rrun/ref/$(basename "$h")" < "$h"; done
  srv "cat > $rrun/pattern_srv_driver.sh" < "$tools/pattern_srv_driver.sh"
  srv "cd $rrun/bin && sha256sum -c --quiet ../bin.sha256" || die "program checksums differ on the server"
  srv "cd $rrun && (nohup setsid bash pattern_srv_driver.sh > driver.out 2>&1 < /dev/null &)" < /dev/null  # a bare trailing & keeps the ssh channel open and the flow hangs
  sleep 10
  echo "  server STATUS: $(srv "cat $rrun/STATUS" || echo none)"
  { echo "pattern=$pat"; echo "cfg=$cfg"; echo "srv_run=$rrun"; echo "launched=$(date '+%Y-%m-%dT%H:%M:%S')"; } > "$out/flow.state"
  echo "launched $rrun ($(($(wc -l < "$out/jobs.ordered.tsv") - 1)) jobs). Check: ssh ... 'cat $rrun/STATUS'
then: ./run-flow.sh pattern-finish $pat ${out#"$here"/}"
}

step_pattern() {
  local pat="${1:-}" cfg out bindir
  [ -n "$pat" ] || die "usage: ./run-flow.sh pattern <$(pat_names | xargs | tr ' ' '|')>"
  pat_nm "$pat" > /dev/null; cfg="$(cfg_name "$pat")"
  [ "$cfg" != GemminiRocketConfig ] || die "pattern needs an N:M chip"
  load_env; need_py
  if dry; then out="$scratch/pattern-dryrun-$stamp-$pat"
  else out="${FLOW:-$streaming/investigate/runs/$stamp-$pat-flow}"; fi
  [[ "$out" = /* ]] || out="$here/$out"
  bindir="${FLOW:-$out}/bin"; [[ "$bindir" = /* ]] || bindir="$here/$bindir"
  mkdir -p "$out"
  exec > >(tee -a "$out/pattern.out") 2>&1
  say "pattern $pat ($cfg), stages: ${STAGES:-spike sim srv}${DRY_RUN:+, DRY_RUN=$DRY_RUN} -> ${out#"$here"/}"
  stay_awake "pattern $pat"
  if in_stages spike; then pattern_spike "$out" "$pat"; fi
  if in_stages sim; then pattern_sim "$out" "$pat" "$cfg"; fi
  if in_stages srv; then
    in_stages sim || dry || die "the srv stage needs the sim stage in the same call (it proves the simulator first)"
    pattern_srv "$out" "$pat" "$cfg" "$bindir"
  fi
}

# copy back, parsers, area, summary. pattern-finish <pat> <flow folder>
step_pattern_finish() {
  local pat="${1:-}" flow="${2:-${FLOW:-}}" rrun cfg st dest name rc_all=0 rc f s L lib area_out=() stage=() chip
  [ -n "$pat" ] && [ -n "$flow" ] || die "usage: ./run-flow.sh pattern-finish <pat> <flow folder>"
  [[ "$flow" = /* ]] || flow="$here/$flow"
  [ -f "$flow/flow.state" ] || die "no $flow/flow.state (was the server stage launched from this folder?)"
  rrun="$(sed -n 's/^srv_run=//p' "$flow/flow.state")"; cfg="$(sed -n 's/^cfg=//p' "$flow/flow.state")"
  [ "$(sed -n 's/^pattern=//p' "$flow/flow.state")" = "$pat" ] || die "$flow is not a $pat flow"
  load_env; need_py
  srv_up
  st="$(srv "cat $rrun/STATUS 2>/dev/null" || true)"
  if [[ "$st" != ALL_DONE* ]]; then
    echo "server run $rrun: STATUS '${st:-none}'; $(srv "tail -n +2 $rrun/jobs.tsv 2>/dev/null | wc -l") of $(($(wc -l < "$flow/jobs.ordered.tsv") - 1)) jobs done; $(srv "pgrep -fc '^[^ ]*simulator-chip' || true") simulations running on the machine"
    exit 3
  fi
  exec > >(tee -a "$flow/finish.out") 2>&1
  name="$(basename "$rrun")"; dest="$streaming/investigate/runs/$name"
  say "copy back $rrun -> ${dest#"$here"/}"
  if dry; then echo "  [dry-run] would copy back, check, parse, run the area flow and summarize"; return 0; fi
  [ ! -e "$dest" ] || die "$dest already exists"
  srv "python3 -c 'import sys, tarfile; t = tarfile.open(fileobj=sys.stdout.buffer, mode=\"w|\"); t.add(\"$rrun\", arcname=\"$name\"); t.close()'" |
    tar -xf - -C "$streaming/investigate/runs" || die "copy back failed"
  (cd "$dest" && sha256sum -c --quiet SHA256SUMS) || die "SHA256SUMS check failed in $dest"
  srv "cd $rrun && find . -type f -printf '%P\0' | sort -z | xargs -0 sha256sum" > "$flow/copyback.server.sha256"
  (cd "$dest" && find . -type f -printf '%P\0' | sort -z | xargs -0 sha256sum) > "$flow/copyback.local.sha256"
  diff "$flow/copyback.server.sha256" "$flow/copyback.local.sha256" || die "server and local file lists differ after copy back"
  echo "  $(wc -l < "$flow/copyback.local.sha256") files, sha256 identical on both ends; SHA256SUMS ok"

  say "parsers"
  rc=0; "$py" "$tools/parse_fixa.py" "$dest" > "$flow/parse_fixa.out" 2>&1 || rc=$?
  stage+=("parse_fixa.py rc=$rc (${flow#"$here"/}/parse_fixa.out)"); [ "$rc" -eq 0 ] || rc_all=1
  # collect.py writes into its run folder: it gets a staging copy of the bench logs (recorded run untouched)
  local c="$flow/collect"; rm -rf "$c"; mkdir -p "$c/ref"
  cp "$dest"/ref/*.json "$c/ref/"
  for L in "${bench_layers[@]}"; do cp "$dest"/*."${L}_${pat#nm}"_*.seed*.log "$c/" 2>/dev/null || true; done
  # (awk: empty TSV fields would collapse under read)
  awk -F'\t' 'NR > 1 && $6 == "bench" {print $3, $4, $8}' "$flow/stock-reused.tsv" | while read -r f s log; do
    cp "$log" "$c/stock.${f%-baremetal}.seed$s.log"; done
  grep -E '^(host|sim\.)' "$dest/run.info" > "$c/run.info"
  { printf 'chip\tprogram\tseed\twall_s\n'; tail -n +2 "$dest/jobs.tsv" | awk -F'\t' -v OFS='\t' '{sub(/-baremetal$/, "", $2); print $1, $2, $3, $7}'; } > "$c/jobs.tsv"
  rc=0; "$py" "$streaming/scripts/collect.py" "$c" > "$flow/collect.out" 2>&1 || rc=$?
  stage+=("collect.py rc=$rc (${flow#"$here"/}/collect.out, staging ${c#"$here"/})"); [ "$rc" -eq 0 ] || rc_all=1
  # verify_all.py --mode run: integrity of the recorded run itself (reads only); reused stock logs are checked in their own folders
  local xargs_=()
  while read -r log; do xargs_+=(--extra-log "$log"); done < <(awk -F'\t' 'NR > 1 {print $8}' "$flow/stock-reused.tsv")
  rc=0; "$py" "$ver/verify_all.py" --mode run "$dest" "${xargs_[@]}" > "$flow/verify_all.out" 2>&1 || rc=$?
  stage+=("verify_all.py --mode run rc=$rc (${flow#"$here"/}/verify_all.out)"); [ "$rc" -eq 0 ] || rc_all=1

  say "area (${AREA_FLOW:-$streaming/area/synth_area.sh})"
  local area_flow="${AREA_FLOW:-$streaming/area/synth_area.sh}"
  if [ ! -x "$area_flow" ]; then
    echo "  error: the area flow is missing or not executable: $area_flow (interface: worklogs/area-run.md; set AREA_FLOW)"
    stage+=("area: MISSING $area_flow"); rc_all=1
  else
    for lib in ${AREA_LIBS:-nangate45}; do
      rc=0; "$area_flow" "$cfg" "$lib" > "$flow/area-$lib.out" 2>&1 || rc=$?
      area_out+=("$flow/area-$lib.out")
      stage+=("area $cfg $lib rc=$rc (${flow#"$here"/}/area-$lib.out)"); [ "$rc" -eq 0 ] || rc_all=1
    done
  fi
  say "summary -> ${flow#"$here"/}/summary.md"
  local sargs=()
  for s in "${stage[@]}"; do sargs+=(--stage "$s"); done
  rc=0; "$py" "$tools/pattern_flow.py" summary --run "$dest" --plan "$flow/jobs.ordered.tsv" --reused "$flow/stock-reused.tsv" \
    --pattern "$pat" --cfg "$cfg" --root "$here" --area "${area_out[@]}" "${sargs[@]}" --out "$flow/summary.md" || rc=$?
  [ "$rc" -eq 0 ] || rc_all=1
  [ "$rc_all" -eq 0 ] || die "pattern $pat: not all checks passed (see ${flow#"$here"/}/summary.md)"
  echo "pattern $pat: everything passed (${flow#"$here"/}/summary.md)"
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
  pattern)    step_pattern "$@" ;;
  pattern-finish) step_pattern_finish "$@" ;;
  all)
    step_spike_lib nm24
    step_spike_lib dense24
    step_tests
    step_fair_build
    step_spike nm24
    step_sim nm24
    step_sim nm48
    step_fair all
    step_checks
    ;;
  ""|-h|--help|help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown step '$step'"; sed -n '/^#  setup/,/^#$/p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
