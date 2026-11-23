source ~/miniforge3/etc/profile.d/conda.sh >/dev/null 2>&1
cd ~/chipyard/sims/verilator
N=generated-src-banksplit-dense/chipyard.harness.TestHarness.GemminiRocketConfig/gen-collateral
O=generated-src-fixb-dense/chipyard.harness.TestHarness.GemminiRocketConfig/gen-collateral
K=generated-src/chipyard.harness.TestHarness.GemminiRocketConfig/gen-collateral
for d in $N $O $K; do echo "$d: $(ls $d | wc -l) files"; done
norm() { sed -E 's/ *\/\/ @\[[^]]*\]//; s/@\[[^]]*\]//g; s/\.scala:[0-9]+(:[0-9]+)?/.scala/g' "$1"; }
cmpdirs() { # a b label
  local a=$1 b=$2 l=$3 nd=0 nn=0 f
  : > ~/sinv/banksplit-dense/$l.differ
  for f in $(cd $a; ls); do
    [ -f $b/$f ] || { echo "MISSING $f" >> ~/sinv/banksplit-dense/$l.differ; continue; }
    cmp -s $a/$f $b/$f && continue
    nd=$((nd+1))
    if ! diff -q <(norm $a/$f) <(norm $b/$f) >/dev/null; then nn=$((nn+1)); echo "$f $(diff <(norm $a/$f) <(norm $b/$f) | grep -c '^[<>]')" >> ~/sinv/banksplit-dense/$l.differ; fi
  done
  echo "$l: raw-differing $nd, differing after stripping @[..] and .scala:line: $nn"
  for f in $(cd $b; ls); do [ -f $a/$f ] || echo "ONLY in $b: $f"; done | head
}
cmpdirs $N $O new-vs-fixbdense
cmpdirs $N $K new-vs-stock
echo ---; cat ~/sinv/banksplit-dense/new-vs-fixbdense.differ; echo ---; cat ~/sinv/banksplit-dense/new-vs-stock.differ
