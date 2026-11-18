# Preprocessing vs. runtime (fair-20261103-151404)

Cycles from `fair_perf.c` (i=64 k=128 j=32), min-max over seeds. Preprocessing is one-time CPU work per weight set (warm = second pass, cold = first pass with cache misses); runtime is one timed matmul. Index issue is estimated from the CPU-only `cpu_meta_only` run.

| Chip | Weights | Seeds | Runtime | Index issue | Other issue | Drain | Prep (warm) | Prep (cold) | Runs to repay prep |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Berkeley | fresh weights | 3 | 1,555 | 0 | 1,493 | 62 | 0 | 0 |  |
| Berkeley | weights reused | 3 | 1,541 | 0 | 1,474 | 67 | 0 | 0 |  |
| ours, sparsity off | fresh weights | 3 | 1,555 | 0 | 1,493 | 62 | 0 | 0 |  |
| ours, sparsity off | weights reused | 3 | 1,541 | 0 | 1,474 | 67 | 0 | 0 |  |
| ours 2:4 | fresh weights | 3 | 2,281 | 960 | 1,262 | 59 | 335,734 | 340,863 | never |
| ours 2:4 | fresh weights, batched | 3 | 2,110 | 960 | 1,078 | 72 | 335,734 | 340,863 | never |
| ours 2:4 | weights reused | 3 | 1,395 | 240 | 1,094 | 61 | 335,734 | 340,863 | 2797.8 |
| ours 4:8 | fresh weights | 3 | 3,170 | 1,493 | 1,618 | 59 | 514,867 | 520,777 | never |
| ours 4:8 | fresh weights, batched | 3 | 2,964 | 1,493 | 1,406 | 65 | 514,867 | 520,777 | never |
| ours 4:8 | weights reused | 3 | 1,607 | 373 | 1,176 | 58 | 514,867 | 520,777 | never |

'Runs to repay prep' compares each sparse run with the same chip's own dense run of the same matmul in the same log; 'never' means the sparse run is not faster, so the preprocessing is never paid back.
