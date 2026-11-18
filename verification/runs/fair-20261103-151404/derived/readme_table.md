| Cycles (min-max over seeds) | Berkeley | 2:4 | 4:8 |
|---|---:|---:|---:|
| Array time (cycles in the compute state), weights reused | 1,260 | 672 | 672 |
| Whole job, weights reused | 1,541 | 1,395 | 1,607 |
| Whole job, fresh weights | 1,555 | 2,281 | 3,170 |
| Whole job, fresh weights, indexes batched 4 tiles ahead | – | 2,110 | 2,964 |
| Berkeley / ours: array time (cycles in the compute state), weights reused | – | 1.88x | 1.88x |
| Berkeley / ours: whole job, weights reused | – | 1.10x | 0.96x |
| Berkeley / ours: whole job, fresh weights | – | 0.68x | 0.49x |
| Berkeley / ours: whole job, fresh weights, indexes batched 4 tiles ahead | – | 0.74x | 0.52x |
| same chip dense / sparse (same program): array time (cycles in the compute state), weights reused | – | 1.88x | 1.86x |
| same chip dense / sparse (same program): whole job, weights reused | – | 1.09x | 0.92x |
| same chip dense / sparse (same program): whole job, fresh weights | – | 0.68x | 0.46x |
| same chip dense / sparse (same program): whole job, fresh weights, indexes batched 4 tiles ahead | – | 0.73x | 0.50x |

Seeds: 1, 2, 3. Ratios above 1 mean fewer cycles than the reference column.
