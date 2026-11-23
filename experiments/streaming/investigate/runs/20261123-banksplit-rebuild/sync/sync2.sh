set -eo pipefail
source ~/miniforge3/etc/profile.d/conda.sh; source ~/chipyard/env.sh >/dev/null
B=~/sinv/banksplit-sync
G=~/chipyard/generators/gemmini
bk=$B/old-working-tree; mkdir -p $bk
for p in gem:$G lib:$G/software/libgemmini rt:$G/software/gemmini-rocc-tests; do
  n=${p%%:*}; r=${p#*:}
  cd $r
  echo "== $n $(git rev-parse --short HEAD) branch $(git branch --show-current)"
  if [ ! -e $bk/$n.uncommitted.diff ]; then
    git diff HEAD --binary --ignore-submodules=all > $bk/$n.uncommitted.diff
    git ls-files --others --exclude-standard > $bk/$n.untracked.list
    mkdir -p $bk/$n.untracked
    while read -r f; do [ -z "$f" ] || { mkdir -p "$bk/$n.untracked/$(dirname "$f")"; mv "$f" "$bk/$n.untracked/$f"; }; done < $bk/$n.untracked.list
  fi
  git checkout -q -- .
  git fetch -q --no-recurse-submodules $B/$n.bundle current-working-branch:current-working-branch
  git checkout -q --no-recurse-submodules current-working-branch
  echo "$n HEAD $(git rev-parse --short HEAD) status:"; git status --short --ignore-submodules=none
done
