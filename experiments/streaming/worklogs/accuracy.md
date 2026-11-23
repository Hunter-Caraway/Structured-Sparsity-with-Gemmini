# accuracy: N:M pruning accuracy on BERT/MRPC (laptop CPU)

Agent worklog. Brief: Claude Docs https://claude.ai/artifact/GKLYX8MXGiapowrRLqmHat ("How we replicate it").
Recipe from the coordinator, user-approved laptop training 2026-11-17.

## Discrepancy noted
- Brief says SST-2; coordinator recipe says GLUE MRPC (newer, user-approved). Using MRPC. Reports accuracy and F1.

## Setup (2026-11-17)
- venv `~/venvs/sparsity-acc` (outside repo), system Python 3.14.7. Nothing installed system-wide.
- Packages (direct): purpose / license
  - torch 2.15.0+cpu (CPU wheel, download.pytorch.org/whl/cpu): training, pruning masks, int8 sim / BSD-3-Clause
  - transformers 5.23.0: bert-base-uncased model + tokenizer / Apache-2.0
  - datasets 5.2.0: GLUE MRPC loader (`nyu-mll/glue`, `mrpc`) / Apache-2.0
  - pulled in: tokenizers, safetensors, huggingface_hub (Apache-2.0); numpy, pandas (BSD-3); pyarrow (Apache-2.0); others are their deps.
  - scikit-learn installed then removed (F1 computed by hand).
- HF cache: `~/.cache/huggingface` (model + dataset, not in repo).
- Code: `experiments/accuracy/` (`nm_acc.py` lib, `run_config.py` one run, `test_nm.py` mask test,
  `run_queue.sh` queue, `collect.py` CSV builder). README there states the stdlib-only exemption.

## Method decisions
- Pruned layers: all 72 `nn.Linear` under `bert.encoder.` (Q,K,V,attn-out,FFN in/out x 12). Not embeddings, pooler, classifier.
- Mask: per output row, groups of M along `in`; keep N largest |w|; stable sort so ties go to lower index.
  `test_nm.py` checks this against a port of `nm_prune` (gemmini_nm.h:61) with heavy ties: PASS.
- Hparams (dense and every retrain): AdamW lr 2e-5, bs 32, 3 epochs, wd 0.01, warmup 10% then linear decay,
  grad clip 1.0, max_len 128, dynamic padding.
- Seeds 1,2,3. Sparse seed s starts from dense seed s. 25% patterns: 1:4 from 2:4, 2:8 from 4:8, 4:16 from 8:16
  (the 50% retrained model of the same seed = the recipe's "prune to 2N:M, retrain" stage, reused).
- Int8: the 72 pruned Linears only. Weights symmetric per-tensor (max|w|/127), inputs symmetric per-tensor
  (max|x| over 512 calibration train examples /127), round half-to-even, clamp [-128,127], exact integer
  accumulate (float64; overflow >= 2^31 raises), output = acc * s_w*s_x + float bias. Attention matmuls
  (QK^T, AV), LayerNorm, GELU, softmax, embeddings, pooler, classifier stay fp32.
- N:M verified after retrain on fp32 weights and again on int8 weights; failure raises.

## Log
- 2026-11-17 14:45 venv + downloads done. test_nm.py PASS.
- 14:49-14:56 smoke tests (runs/smoke/, never in CSV): dense s1 30 steps, then 2:4 s1 5 steps (parent = smoke dense), then 1:4 s1 5 steps (parent = smoke 2:4). All finished; N:M verify OK (kept_frac 0.500000 / 0.250000).
  Logs: experiments/accuracy/runs/smoke/20261117-144914-mrpc-dense-s1-smoke/train.log and the 2:4 / 1:4 smoke folders next to it.
  First smoke attempt (runs/smoke/20261117-144845-mrpc-dense-s1-smoke) crashed: datasets 5 returns a Column, not a list; fixed with list().

## Timing
- Measured: 30 train steps = 118.8 s, 8 threads, nice 10, Spike agent also running (smoke dense train.log "train total secs=118.8 steps=30"). ~3.96 s/step.
- Measured: fp32 eval 13 s, calibrate+int8 eval 58 s (same log, timestamps 14:51:17 -> 14:52:28).
- Projection [E]: 115 steps/epoch x 3 epochs = 345 steps x 3.96 s = ~23 min train + ~1.5 min eval => ~25 min per run.
- Runs: dense 3 + (2:4, 4:8) 6 = 9 priority runs => ~3.8 h [E]; + 8:16 3 runs ~1.3 h [E]; + 1:4, 2:8, 4:16 9 runs ~3.8 h [E].
  Total 21 runs ~8.8 h [E]. Fits Nov 28 easily even at 2x slowdown from CPU contention.
- Checkpoints: dense + 50% patterns saved (12 x ~440 MB [E]) in experiments/accuracy/checkpoints/ (git-ignored).

## Resume check (2026-11-17 16:41, new agent after predecessor died on network error)
- Queue runner `run_queue.sh full1` alive (pid 2107270, nohup setsid), all 21 jobs in priority order:
  dense 1-3, 2:4 1-3, 4:8 1-3, 8:16 1-3, 1:4 1-3, 2:8 1-3, 4:16 1-3. Continues without an agent.
  Status: `experiments/accuracy/queues/full1/STATUS`; `STATUS.final` written as DONE or FAILED at the end.
  Stops the whole queue on the first failed job or MemAvailable < 3000 MB.
- Measured per-run wall time (queues/full1/STATUS START/END): dense s1 26.4 min, s2 37.3 min, s3 37.9 min.
  train_secs (result.json): 1462.9 / 2051.5 / 2089.4. Slower than the smoke estimate (load avg ~7.9 from other work).
- 2:4 s1 running: 20 steps in 128.8 s = 6.4 s/step (runs/20261117-163756-mrpc-2_4-s1/train.log) => ~37 min train [E].

## Relaunch (2026-11-18 23:20)
- Found: queue full1 dead, no run_queue.sh process. Laptop had rebooted/suspended (uptime 7 min at 23:20; `queues/full1/STATUS` last line `START 2:4 1 2026-11-17T16:37:53`, no END, no STATUS.final).
- 2:4 s1 partial died mid epoch 2: runs/failed/20261117-163756-mrpc-2_4-s1/train.log last line `[17:05:13] train epoch=2 step=260/345`. Moved (mv, contents untouched) to experiments/accuracy/runs/failed/. 3 dense folders untouched, `sha256sum -c SHA256SUMS` OK for all 3.
- Relaunch from experiments/accuracy (queue name full2, 18 jobs: 2:4, 4:8, 8:16, 1:4, 2:8, 4:16 x seeds 1-3, priority order):
  `nohup setsid systemd-inhibit --what=sleep:idle --who=accuracy-queue --why="MRPC training queue" ./run_queue.sh full2 "2:4 1" "2:4 2" "2:4 3" "4:8 1" ... "4:16 3" > queues-full2.nohup 2>&1 &`
  systemd-inhibit (no sudo) blocks suspend/idle sleep; `systemd-inhibit --list` shows it. Does not survive a reboot.
- PID: systemd-inhibit 9569, run_queue.sh 9577, started 2026-11-18 23:20:19 (queues/full2/STATUS).
- New run folder: experiments/accuracy/runs/20261118-232021-mrpc-2_4-s1. Check 1 train.log 23:21:36 `step=20/345 elapsed=70.5s`; check 2 at 23:22:26 process alive. Speed ~3.5 s/step (load low, laptop otherwise idle) => ~20-25 min/run [E].

## collect-skip-failed (2026-11-18)
- experiments/accuracy/collect.py:18 `SKIP = ("smoke", "failed")`; :41-43 print one stderr line per existing skipped dir; :44 loop filters `p.name not in SKIP`. Docstring updated. Any other run dir without DONE still dies (exit 1).
- Tested on scratch copy .../scratchpad/collect-test/ (1 DONE run copied from runs/20261117-145622-mrpc-dense-s1, smoke/, failed/x/, incomplete/): (a) incomplete present -> exit 1 "no DONE"; (b) removed -> "wrote 2 rows", exit 0, smoke+failed skip lines on stderr. Real runs/ not touched, collect.py not run on it.

## MRPC results, 21 runs (2026-11-23)
Checks: `sha256sum -c SHA256SUMS` OK in all 21 run dirs; `collect.py` exit 0, "wrote 42 rows" (experiments/accuracy/results/mrpc_accuracy.csv, 21 runs x fp32/int8; source of every number below, each row cites its train.log; also result.json per run). Queue: queues/full2/STATUS `DONE 2026-11-19T05:59:11-05:00`, 18 END lines.
Eval set n=408. Cells: mean (min-max) over seeds 1-3, from results/mrpc_accuracy.csv. Delta = pattern mean minus dense mean of same precision.

| pattern | prec | acc mean (min-max) | F1 mean (min-max) | d acc | d F1 | per seed acc/F1 (s1 s2 s3) |
|---|---|---|---|---|---|---|
| dense | fp32 | 0.8538 (0.8431-0.8676) | 0.8973 (0.8904-0.9062) | 0 | 0 | 0.843/0.890 0.868/0.906 0.850/0.895 |
| dense | int8 | 0.7222 (0.6863-0.7794) | 0.7607 (0.7217-0.8256) | 0 | 0 | 0.686/0.722 0.701/0.735 0.779/0.826 |
| 2:4 | fp32 | 0.8472 (0.8431-0.8505) | 0.8931 (0.8889-0.8956) | -0.0065 | -0.0043 | 0.848/0.896 0.850/0.895 0.843/0.889 |
| 2:4 | int8 | 0.7181 (0.6642-0.7623) | 0.7644 (0.6976-0.8145) | -0.0041 | +0.0037 | 0.664/0.698 0.762/0.815 0.728/0.781 |
| 4:8 | fp32 | 0.8521 (0.8382-0.8603) | 0.8955 (0.8862-0.9002) | -0.0016 | -0.0019 | 0.838/0.886 0.858/0.900 0.860/0.900 |
| 4:8 | int8 | 0.7672 (0.7402-0.7990) | 0.8225 (0.7863-0.8571) | +0.0449 | +0.0618 | 0.740/0.786 0.799/0.857 0.762/0.824 |
| 8:16 | fp32 | 0.8554 (0.8480-0.8627) | 0.8981 (0.8924-0.9031) | +0.0016 | +0.0007 | 0.855/0.899 0.848/0.892 0.863/0.903 |
| 8:16 | int8 | 0.7672 (0.7574-0.7843) | 0.8213 (0.8040-0.8423) | +0.0449 | +0.0606 | 0.760/0.804 0.784/0.842 0.757/0.818 |
| 1:4 | fp32 | 0.6977 (0.6936-0.7034) | 0.8073 (0.8052-0.8086) | -0.1560 | -0.0901 | 0.696/0.808 0.703/0.805 0.694/0.809 |
| 1:4 | int8 | 0.6871 (0.6642-0.7108) | 0.7971 (0.7772-0.8134) | -0.0351 | +0.0364 | 0.664/0.777 0.711/0.801 0.686/0.813 |
| 2:8 | fp32 | 0.7377 (0.7328-0.7426) | 0.8339 (0.8331-0.8357) | -0.1160 | -0.0634 | 0.733/0.833 0.743/0.836 0.738/0.833 |
| 2:8 | int8 | 0.6397 (0.5637-0.7083) | 0.7042 (0.6009-0.7973) | -0.0825 | -0.0565 | 0.647/0.714 0.708/0.797 0.564/0.601 |
| 4:16 | fp32 | 0.7296 (0.7230-0.7353) | 0.8290 (0.8275-0.8307) | -0.1242 | -0.0684 | 0.723/0.827 0.735/0.831 0.730/0.829 |
| 4:16 | int8 | 0.6895 (0.6078-0.7328) | 0.7693 (0.6639-0.8284) | -0.0327 | +0.0086 | 0.728/0.828 0.608/0.664 0.733/0.816 |

Anomalies:
- Collapse: 1:4 fp32 (acc 0.694-0.703, F1 0.805-0.809) sits at the majority-class level. MRPC dev majority = 0.684 acc / F1 0.812 (predict all "paraphrase"; 279/408 positives is the standard MRPC dev count, [E] not taken from our logs). 1:4 int8 is the same or below. Treat 1:4 as collapsed, not a measured accuracy.
- 2:8 and 4:16 fp32 (0.72-0.74 acc, F1 0.83) are only 4-6 points above majority; training did not recover. Seeds agree tightly (spread <= 0.013), so it is systematic, not a bad seed.
- 4:8 and 8:16 fp32 match dense within seed noise (|d| <= 0.0065, dense seed spread 0.0245). 2:4 fp32 -0.0065, within noise too. No sparse-beats-dense in fp32.
- int8 of 4:8 and 8:16 beats dense int8 by +0.045 acc / +0.06 F1. Not a real gain: it is the PTQ damage varying (dense int8 range 0.686-0.779, 4:8 0.740-0.799). Do not report as sparse > dense.
- Large int8 seed spread: 2:8 s3 int8 acc 0.564 / F1 0.601 and 4:16 s2 int8 acc 0.608 are well below majority (below-chance degradation from int8, not collapse of training; their fp32 is 0.738 and 0.735).
- fp32 pct_kept in CSV 0.25/0.25/0.5 etc matches pattern (verify lines in train.log).

int8 PTQ drop (fp32 mean - int8 mean, from CSV): dense 0.1316; 2:4 0.1291; 4:8 0.0849; 8:16 0.0882; 2:8 0.0980; 4:16 0.0401; 1:4 0.0106.
- Holds on every pattern whose fp32 is not collapsed: 2:4 and dense ~13 points, 4:8/8:16 ~8.5-9, 2:8 ~10. It is not a dense-only artifact. Smaller drop on 1:4/4:16 is only because fp32 is already near majority (floor effect).
- Per-seed int8 spread is 5-15 points in every pattern, so int8 numbers are noisy; the PTQ recipe looks unstable or poorly calibrated. Not changed, not rerun (task rule). Still open for coordinator/user decision.

## RESUME HERE
Done: all 21 MRPC runs (dense x3 from full1, 6 sparse patterns x3 from full2) checksummed OK, collect.py exit 0 -> results/mrpc_accuracy.csv; table and anomalies in section "MRPC results, 21 runs" above. Committed on current-working-branch.
Running: nothing.
Findings: 4:8, 8:16, 2:4 fp32 match dense; 1:4 collapsed to majority; 2:8 and 4:16 degrade ~12 points; int8 PTQ drop (~8-13 pts) holds across non-collapsed patterns, seed-noisy.
Open / next: decision on int8 PTQ recipe (not touched); decide whether 1:4/2:8/4:16 need longer/other training (e.g. more epochs, LR) or are reported as-is; README results table and paper numbers need user approval.
