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

## RESUME HERE
Done (3/21 runs, DONE + SHA256SUMS OK, table in previous version unchanged):
- dense s1 experiments/accuracy/runs/20261117-145622-mrpc-dense-s1 (fp32 0.843137/0.890411, int8 0.686275/0.721739)
- dense s2 experiments/accuracy/runs/20261117-152243-mrpc-dense-s2 (fp32 0.867647/0.906250, int8 0.700980/0.734783)
- dense s3 experiments/accuracy/runs/20261117-160001-mrpc-dense-s3 (fp32 0.850490/0.895369, int8 0.779412/0.825581)
  (each from that folder's train.log / result.json)
Failed: experiments/accuracy/runs/failed/20261117-163756-mrpc-2_4-s1 (partial, power/suspend).
Running: queue full2 (pid 9577), log queues/full2/STATUS, stdout queues-full2.nohup, per-job queues/full2/job-*.out; current run runs/20261118-232021-mrpc-2_4-s1.
Remaining 18 jobs in order: 2:4 s1-3, 4:8 s1-3, 8:16 s1-3, 1:4 s1-3, 2:8 s1-3, 4:16 s1-3.
ETA [E]: ~25-38 min/run (earlier runs 26-38 min per full1/STATUS; 2:4 s1 now ~3.5 s/step) => 18 runs ~7.5-11 h, done ~07:00-10:30 Nov 19; priority 6 (2:4, 4:8) ~2.5-3.8 h.
Next steps:
1. When queues/full2/STATUS.final = DONE: run collect.py (it now skips runs/smoke and runs/failed, see section collect-skip-failed).
2. If FAILED or process gone: read last START line, move partial folder to runs/failed/ (add suffix if name exists), relaunch the same way with remaining jobs.
3. Open: int8 PTQ drop 7-16 points vs fp32 on dense (anomaly from before, undiagnosed, awaiting coordinator/user decision).
