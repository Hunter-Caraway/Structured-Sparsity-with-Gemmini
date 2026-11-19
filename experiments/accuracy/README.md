# Accuracy of N:M sparse BERT on GLUE MRPC

Accuracy axis of the speed / accuracy / area Pareto study. Prunes `bert-base-uncased` to each N:M pattern,
retrains with the mask fixed (NVIDIA ASP recipe), and evaluates in fp32 and in Gemmini-style int8.

## Python exemption
The repo rule "Python: standard library plus matplotlib only" does **not** apply to this directory.
The user approved laptop training with torch, transformers and datasets on 2026-11-17. These run only from
the venv `~/venvs/sparsity-acc` (outside the repo, never system-wide). Packages and licenses are listed in
`experiments/streaming/worklogs/accuracy.md`. `collect.py` uses the standard library only.

## Files
| File | Purpose |
|---|---|
| `nm_acc.py` | N:M mask (matches `nm_prune` in `gemmini_nm.h`), N:M check, training loop, Gemmini-style int8 layer |
| `run_config.py` | One config + seed: train or retrain, verify N:M, eval fp32 and int8, write a run folder |
| `test_nm.py` | Mask vs a port of `nm_prune` (with ties), plus a NEG test of the N:M check |
| `run_queue.sh` | Runs a list of configs one at a time under `nice`, writes `STATUS` |
| `collect.py` | Builds `results/mrpc_accuracy.csv` from run folders; fails on a missing or unfinished run |

## Run folders
`runs/<YYYYMMDD-HHMMSS>-mrpc-<pattern>-s<seed>/`: `run.info` (package versions, git sha, script sha256,
hparams, seed, parent run), `train.log` (the `RESULT` lines are the source of every CSV number),
`result.json`, `SHA256SUMS`, `DONE`. Smoke tests go to `runs/smoke/` and never feed the CSV.
Checkpoints go to `checkpoints/` (git-ignored).

## Method (short)
- Pruned: the 72 `nn.Linear` layers inside `bert.encoder` (not embeddings, pooler, classifier).
- Groups of M consecutive weights along `in` per output row; keep the N largest |w|; ties to lower index.
- Sparse seed s starts from dense seed s. 25% patterns (1:4, 2:8, 4:16) start from the 50% pattern with the
  same M (2:4, 4:8, 8:16) of the same seed, then prune and retrain again.
- Int8: per-tensor symmetric weights and inputs of each pruned Linear, exact integer accumulate, one float
  scale per layer; max calibration on 512 train examples. Everything else stays fp32.

## CSV
`results/mrpc_accuracy.csv` from `collect.py` (run with any python3). Two rows per run (fp32, int8).
`epochs` is the epoch count of the run's own training stage (3). A 25% pattern has also had the 50%
stage (3) and the dense fine-tune (3) before it; the parent chain is in each `run.info`.
