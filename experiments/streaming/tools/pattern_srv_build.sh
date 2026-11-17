#!/usr/bin/env bash
# pattern_srv_build.sh <config> <make -j> : rebuild one N:M Verilator simulator on the server. Only started by
# `APPROVED_REBUILD=1 run-flow.sh pattern <pat>`, which copies this script and src_sha_list.sh (run-flow.sh's own
# src_sha_list, so laptop and server lists are made by the same code) into ~/sinv/builds/<stamp>-<config>/ and starts
# it with nohup setsid. Writes STATUS (BUILD_DONE / BUILD_FAILED <why>) in that folder.
# - never builds Berkeley's stock simulator (GemminiRocketConfig), and refuses while a simulation of <config> runs
# - backs up the old simulator, its generated-src and its source list first (AGENTS rule 3), with SHA256SUMS
# - takes the source list right before make and writes <simulator>.src.sha256 (list + "# sim sha256=") after it
set -euo pipefail
cfg="${1:?config}" jobs="${2:?make -j}"
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cy="$HOME/chipyard"
sims="$cy/sims/verilator"
sim="$sims/simulator-chipyard.harness-$cfg"
gen="$sims/generated-src/chipyard.harness.TestHarness.$cfg"
fail() { echo "BUILD_FAILED $* $(date)" > "$dir/STATUS"; echo "error: $*" >&2; exit 1; }
[ "$cfg" != GemminiRocketConfig ] || fail "refusing to build the stock simulator"
[[ "$jobs" =~ ^[0-9]+$ ]] || fail "make -j must be a number"
if pgrep -f "^[^ ]*simulator-chipyard.harness-$cfg( |$)" > /dev/null; then fail "a $cfg simulation is running"; fi
echo "BUILDING $$ $(date)" > "$dir/STATUS"
set +u
# shellcheck disable=SC1091
source "$HOME/miniforge3/etc/profile.d/conda.sh"
# shellcheck disable=SC1091
source "$cy/env.sh" > /dev/null
set -u
# shellcheck disable=SC1091
source "$dir/src_sha_list.sh"
gem="$cy/generators/gemmini" lib_dir="$gem/software/libgemmini" tests_dir="$gem/software/gemmini-rocc-tests"
export gem lib_dir tests_dir

b="$dir/backup"
mkdir -p "$b"
if [ -e "$sim" ]; then cp -a "$sim" "$b/" || fail "backup of $sim"; fi
if [ -e "$gen" ]; then cp -a "$gen" "$b/" || fail "backup of $gen"; fi
if [ -e "$sim.src.sha256" ]; then cp -a "$sim.src.sha256" "$b/" || fail "backup of the source list"; fi
(cd "$b" && find . -type f -printf '%P\0' | sort -z | xargs -0 -r sha256sum > SHA256SUMS) || fail "backup checksums"
echo "backed up to $b"

src_sha_list > "$dir/src.before-build.sha256" || fail "source list"
echo "make -j$jobs CONFIG=$cfg in $sims ($(date))"
mkdir -p "$HOME/sinv"
if ! (cd "$sims" && flock "$HOME/sinv/sims-make.lock" make -j"$jobs" CONFIG="$cfg") > "$dir/build.log" 2>&1; then
  tail -20 "$dir/build.log" >&2
  fail "make failed, see $dir/build.log"
fi
[ -x "$sim" ] || fail "make succeeded but $sim is missing"
{ cat "$dir/src.before-build.sha256"; echo "# sim sha256=$(sha256sum "$sim" | cut -d' ' -f1)"; } > "$sim.src.sha256"
cp "$sim.src.sha256" "$dir/"
echo "BUILD_DONE $(date) sim sha256=$(sha256sum "$sim" | cut -d' ' -f1)" > "$dir/STATUS"
