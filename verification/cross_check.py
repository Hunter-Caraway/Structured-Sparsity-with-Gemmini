#!/usr/bin/env python3
# checks the original benchmark pipeline (./run-flow.sh bench, nm_sparse_perf.c; superseded by fair) against its raw logs:
#   1. every bench log of the newest stamp per config passed its own check
#   2. results/cycles.csv rows of that stamp equal the logs, row for row, in both directions
#   3. a re-run folder (verification/runs/rerun-*, newest or --rerun) reproduces every number exactly
# run: ~/chipyard/.conda-env/bin/python verification/cross_check.py [--logs DIR] [--csv FILE] [--rerun DIR]
# exit 0 = all checks pass, 1 = a check failed, 2 = no bench logs to check.
import argparse, csv, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nmdata  # noqa: E402

CFGS = {"nm24": "GemminiNMRocketConfig", "nm48": "GemminiNM48RocketConfig"}
TESTS = ("nm_sparse_debug", "nm_sparse_matmul", "nm_sparse_perf")
BENCH_RE = re.compile(r"^bench-(nm24|nm48)-(nm_sparse_\w+?)-(\d{8}-\d{6})\.log$")
fails = 0


def say(ok, msg):
    global fails
    fails += not ok
    print(("  ok    " if ok else "  FAIL  ") + msg)


def newest_bench(logdir):
    """{cfg: (stamp, {test: parsed})} for the newest stamp of each config."""
    stamps = {}
    for p in logdir.glob("bench-*.log") if logdir.is_dir() else []:
        m = BENCH_RE.match(p.name)
        if m:
            stamps.setdefault(m[1], {}).setdefault(m[3], {})[m[2]] = p
    return {c: (max(s), {t: nmdata.parse_log(p) for t, p in s[max(s)].items()}) for c, s in stamps.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=nmdata.ROOT / "logs/runs", type=Path)
    ap.add_argument("--csv", default=nmdata.ROOT / "results/cycles.csv", type=Path)
    ap.add_argument("--rerun", type=Path, help="re-run folder (default: newest verification/runs/rerun-*)")
    a = ap.parse_args()
    bench = newest_bench(a.logs)
    if not bench:
        nmdata.die_no_results(f"no bench logs (bench-<cfg>-<test>-<stamp>.log) in {a.logs}; run ./run-flow.sh bench nm24|nm48")

    print("1. every bench test passed its own correctness check")
    for cfg, (stamp, logs) in sorted(bench.items()):
        for t in TESTS:
            r = logs.get(t)
            say(r is not None and r["passed"] and not r["failed"], f"{cfg} {t} ({stamp}): " +
                ("log missing" if r is None else "printed 'passed' and no failure line"))

    print(f"\n2. {a.csv} matches the logs, row for row")
    rows = list(csv.DictReader(open(a.csv))) if a.csv.exists() else []
    if not rows:
        say(False, f"{a.csv} missing or empty")
    for cfg, (stamp, logs) in sorted(bench.items()):
        mine = [r for r in rows if r["timestamp"] == stamp and r["config"] == CFGS[cfg]]
        want = {("nm_sparse_matmul", v): (n, "", "") for v, n in logs.get("nm_sparse_matmul", {"matmul": {}})["matmul"].items()}
        want.update({("nm_sparse_perf", v): (p["total"], p["ex_active"], p["pairs"])
                     for v, p in logs.get("nm_sparse_perf", {"perf": {}})["perf"].items()})
        got = {(r["test"], r["variant"]): (int(r["total_cycles"]), int(r["array_busy_cycles"]) if r["array_busy_cycles"] else "",
                                           int(r["tiles"]) if r["tiles"] else "") for r in mine}
        say(len(mine) == len(got), f"{cfg} {stamp}: no duplicate csv rows ({len(mine)} rows)")
        for k in sorted(set(want) | set(got)):
            say(want.get(k) == got.get(k), f"{cfg} {k[0]} {k[1]}: log {want.get(k, 'missing')}, csv {got.get(k, 'missing')}")

    print("\n3. re-run reproduces the bench numbers exactly")
    try:
        rerun = a.rerun or sorted((d for d in nmdata.RUNS.glob("rerun-*") if d.is_dir()), key=lambda d: d.name)[-1]
    except IndexError:
        rerun = None
    if rerun is None:
        print("  skip  no verification/runs/rerun-* folder (./run-flow.sh rerun); nothing to compare")
    else:
        for cfg, (stamp, logs) in sorted(bench.items()):
            for t, a_ in sorted(logs.items()):
                p = rerun / f"orig-{cfg}-{t}.log"
                if not p.exists():
                    say(False, f"{cfg} {t}: {p} missing")
                    continue
                b = nmdata.parse_log(p)
                say(b["passed"] and not b["failed"], f"{cfg} {t}: re-run passed")
                n = sum(len(v) for v in a_["perf"].values()) + len(a_["matmul"]) + len(a_["debug"])
                say(all(a_[k] == b[k] for k in ("perf", "matmul", "debug")), f"{cfg} {t}: all {n} numbers identical to bench {stamp}")

    print(f"\n{'ALL CHECKS PASSED' if not fails else str(fails) + ' CHECK(S) FAILED'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
