cd ~/chipyard/sims/verilator
N=generated-src-banksplit-dense/chipyard.harness.TestHarness.GemminiRocketConfig/gen-collateral
O=generated-src-fixb-dense/chipyard.harness.TestHarness.GemminiRocketConfig/gen-collateral
K=generated-src/chipyard.harness.TestHarness.GemminiRocketConfig/gen-collateral
norm() { sed -E 's/ *\/\/ @\[[^]]*\]//; s/@\[[^]]*\]//g; s/\.scala:[0-9]+(:[0-9]+)?/.scala/g' "$1"; }
echo "== LdA new vs fixb"; diff <(norm $O/LoopMatmulLdA.sv) <(norm $N/LoopMatmulLdA.sv)
echo "== LdA new vs stock"; diff <(norm $K/LoopMatmulLdA.sv) <(norm $N/LoopMatmulLdA.sv) | head -30
echo "== LoopMatmul new vs stock"; diff <(norm $K/LoopMatmul.sv) <(norm $N/LoopMatmul.sv)
