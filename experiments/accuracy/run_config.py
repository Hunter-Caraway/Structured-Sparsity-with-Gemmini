"""Train (or retrain) one config + seed, then evaluate fp32 and Gemmini-style int8 on MRPC validation.

Usage (inside ~/venvs/sparsity-acc):
  run_config.py --pattern dense --seed 1
  run_config.py --pattern 2:4 --seed 1 --parent runs/<dense run dir>
  run_config.py --pattern 1:4 --seed 1 --parent runs/<2:4 run dir>   # 25%: parent is the 2N:M run
Writes runs/<YYYYMMDD-HHMMSS>-<tag>/ with run.info, train.log, result.json, SHA256SUMS, DONE.
"""

import argparse
import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATTERNS = {"dense": None, "2:4": (2, 4), "4:8": (4, 8), "8:16": (8, 16),
            "1:4": (1, 4), "2:8": (2, 8), "4:16": (4, 16)}


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", required=True, choices=list(PATTERNS))
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--parent", help="run dir whose checkpoint is the starting point (sparse only)")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--max-steps", type=int, help="smoke test: stop training after this many steps")
    ap.add_argument("--save", action="store_true", help="save checkpoint (needed if this run is a parent)")
    ap.add_argument("--tag", help="run folder tag (default derived from pattern/seed)")
    args = ap.parse_args()

    import torch
    import transformers
    import datasets
    import nm_acc as A

    torch.set_num_threads(args.threads)
    nm = PATTERNS[args.pattern]
    pat_tag = args.pattern.replace(":", "_")
    tag = args.tag or f"mrpc-{pat_tag}-s{args.seed}" + ("-smoke" if args.max_steps else "")
    root = HERE / "runs" / ("smoke" if args.max_steps else "")
    run = root / f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{tag}"
    run.mkdir(parents=True, exist_ok=False)
    logf = open(run / "train.log", "w", buffering=1)

    def log(msg):
        line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
        print(line, flush=True)
        logf.write(line + "\n")

    parent_info = None
    if nm is not None:
        if not args.parent:
            sys.exit("sparse pattern needs --parent")
        pdir = Path(args.parent).resolve()
        parent_info = json.loads((pdir / "result.json").read_text())
        n, m = nm
        if parent_info["seed"] != args.seed:
            sys.exit(f"parent seed {parent_info['seed']} != {args.seed}")
        want = "dense" if n / m >= 0.5 else f"{2 * n}:{m}"
        if parent_info["pattern"] != want:
            sys.exit(f"parent pattern {parent_info['pattern']} != required {want}")
        ckpt = parent_info.get("checkpoint")
        if not ckpt or not Path(ckpt).is_dir():
            sys.exit(f"parent checkpoint missing: {ckpt}")

    try:
        git_sha = subprocess.run(["git", "-C", str(HERE), "rev-parse", "HEAD"],
                                 capture_output=True, text=True, check=True).stdout.strip()
        git_dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain", "."],
                                   capture_output=True, text=True, check=True).stdout.strip()
    except Exception as e:  # noqa: BLE001
        git_sha, git_dirty = f"unknown ({e})", ""
    info = {
        "model": A.MODEL_NAME, "task": A.TASK, "pattern": args.pattern, "seed": args.seed,
        "parent": str(Path(args.parent).resolve()) if args.parent else None,
        "max_steps": args.max_steps, "threads": args.threads, "hparams": A.HPARAMS,
        "git_head": git_sha, "git_dirty_accuracy_dir": git_dirty.splitlines(),
        "script_sha256": {f: sha256(HERE / f) for f in ("nm_acc.py", "run_config.py")},
        "python": sys.version.split()[0], "platform": platform.platform(),
        "torch": torch.__version__, "transformers": transformers.__version__,
        "datasets": datasets.__version__, "argv": sys.argv,
    }
    (run / "run.info").write_text(json.dumps(info, indent=2) + "\n")
    log(f"run dir {run}")
    log("run.info " + json.dumps(info))

    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(A.MODEL_NAME)
    train_data, val_data = A.load_data(tok)
    log(f"data train={len(train_data)} val={len(val_data)}")

    A.set_seed(args.seed)
    src = A.MODEL_NAME if nm is None else parent_info["checkpoint"]
    model = AutoModelForSequenceClassification.from_pretrained(src, num_labels=2)
    log(f"loaded model from {src}")

    if nm is not None:
        n, m = nm
        A.apply_nm(model, n, m)
        cnt, frac = A.verify_nm(model, n, m)
        log(f"nm pruned {args.pattern}: layers={cnt} kept_frac={frac:.6f} (before retrain)")

    t0 = time.time()
    epoch_secs, steps = A.train(model, train_data, tok.pad_token_id, args.seed, log, args.max_steps)
    train_secs = time.time() - t0
    log(f"train total secs={train_secs:.1f} steps={steps}")

    pct_kept = 1.0
    if nm is not None:
        A.finalize_masks(model)
        cnt, pct_kept = A.verify_nm(model, n, m)
        log(f"nm verify after retrain {args.pattern}: layers={cnt} kept_frac={pct_kept:.6f} OK")

    ckpt_dir = None
    if args.save:
        ckpt_dir = HERE / "checkpoints" / run.name
        model.save_pretrained(ckpt_dir)
        log(f"checkpoint {ckpt_dir}")

    res = {"model": A.MODEL_NAME, "task": A.TASK, "pattern": args.pattern, "seed": args.seed,
           "pct_kept": pct_kept, "epochs": A.HPARAMS["epochs"], "max_steps": args.max_steps,
           "train_secs": train_secs, "epoch_secs": epoch_secs, "steps": steps,
           "checkpoint": str(ckpt_dir) if ckpt_dir else None, "eval": {}}

    r = A.evaluate(model, val_data, tok.pad_token_id)
    res["eval"]["fp32"] = r
    log(f"RESULT precision=fp32 pattern={args.pattern} seed={args.seed} "
        f"accuracy={r['accuracy']:.6f} f1={r['f1']:.6f} n={r['n']}")

    # calibration: first calib_examples of a seed-fixed shuffle of train
    g = torch.Generator().manual_seed(1000 + args.seed)
    calib_idx = torch.randperm(len(train_data), generator=g)[:A.HPARAMS["calib_examples"]].tolist()
    amax = A.calibrate(model, [train_data[i] for i in calib_idx], tok.pad_token_id)
    A.quantize_int8(model, amax)
    cnt = A.verify_nm_int8(model, *(nm or (1, 1)))
    log(f"int8 quantized layers={cnt} calib_examples={len(calib_idx)}")
    r = A.evaluate(model, val_data, tok.pad_token_id)
    res["eval"]["int8"] = r
    log(f"RESULT precision=int8 pattern={args.pattern} seed={args.seed} "
        f"accuracy={r['accuracy']:.6f} f1={r['f1']:.6f} n={r['n']}")

    (run / "result.json").write_text(json.dumps(res, indent=2) + "\n")
    log("DONE")
    logf.close()
    sums = "".join(f"{sha256(run / f)}  {f}\n" for f in ("run.info", "train.log", "result.json"))
    (run / "SHA256SUMS").write_text(sums)
    (run / "DONE").write_text("ok\n")
    print(run)


if __name__ == "__main__":
    main()
