#!/usr/bin/env python3
"""Build results/mrpc_accuracy.csv from finished run folders (stdlib only).

Every number is parsed from the `RESULT` lines of each run's train.log and cross-checked against
result.json and SHA256SUMS. Exits non-zero on an unfinished run, a checksum mismatch, a missing
RESULT line, or an N:M verify line missing for a sparse run. Smoke runs (runs/smoke/) and runs/failed/ are never read.
"""

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
SKIP = ("smoke", "failed")  # smoke runs and partial runs moved aside; neither is read
OUT = HERE / "results" / "mrpc_accuracy.csv"
RESULT_RE = re.compile(r"RESULT precision=(\w+) pattern=(\S+) seed=(\d+) accuracy=([\d.]+) f1=([\d.]+) n=(\d+)")
VERIFY_RE = re.compile(r"nm verify after retrain (\S+): layers=72 kept_frac=([\d.]+) OK")
COLS = ["model", "task", "pattern", "pct_kept", "precision", "seed", "epochs", "accuracy", "f1", "log"]


def die(msg):
    sys.exit(f"collect.py: {msg}")


def check_sums(run):
    sums = run / "SHA256SUMS"
    if not sums.is_file():
        die(f"{run}: no SHA256SUMS")
    for line in sums.read_text().splitlines():
        digest, name = line.split(None, 1)
        if hashlib.sha256((run / name.strip()).read_bytes()).hexdigest() != digest:
            die(f"{run}/{name.strip()}: checksum mismatch")


def main():
    rows = []
    for name in SKIP:
        if (RUNS / name).is_dir():
            print(f"collect.py: skipping {RUNS / name}", file=sys.stderr)
    for run in sorted(p for p in RUNS.iterdir() if p.is_dir() and p.name not in SKIP):
        if not (run / "DONE").is_file():
            die(f"{run}: no DONE (unfinished or failed run; move it out of runs/ or finish it)")
        check_sums(run)
        info = json.loads((run / "run.info").read_text())
        res = json.loads((run / "result.json").read_text())
        if info.get("max_steps"):
            die(f"{run}: smoke run (max_steps set) outside runs/smoke")
        log = (run / "train.log").read_text()
        rel = (run / "train.log").relative_to(HERE.parent.parent)
        pct_kept = 1.0
        if res["pattern"] != "dense":
            v = VERIFY_RE.findall(log)
            if len(v) != 1 or v[0][0] != res["pattern"]:
                die(f"{run}: missing N:M verify line")
            pct_kept = float(v[0][1])
        found = {}
        for prec, pat, seed, acc, f1, n in RESULT_RE.findall(log):
            if pat != res["pattern"] or int(seed) != res["seed"] or int(n) != 408:
                die(f"{run}: RESULT line does not match run ({pat} s{seed} n={n})")
            if abs(float(acc) - res["eval"][prec]["accuracy"]) > 1e-6:
                die(f"{run}: train.log and result.json disagree")
            found[prec] = (acc, f1)
        for prec in ("fp32", "int8"):
            if prec not in found:
                die(f"{run}: no RESULT line for {prec}")
            acc, f1 = found[prec]
            rows.append({"model": res["model"], "task": res["task"], "pattern": res["pattern"],
                         "pct_kept": f"{pct_kept:.6f}", "precision": prec, "seed": res["seed"],
                         "epochs": res["epochs"], "accuracy": acc, "f1": f1, "log": str(rel)})
    if not rows:
        die("no finished runs")
    keys = [(r["pattern"], r["seed"], r["precision"]) for r in rows]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        die(f"duplicate runs for {sorted(dup)}; keep one per pattern/seed in runs/")
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
