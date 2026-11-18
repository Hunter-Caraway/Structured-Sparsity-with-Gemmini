#!/usr/bin/env python3
# checks the original benchmark pipeline (./run-flow.sh bench, nm_sparse_perf.c; superseded by fair) against its raw logs:
# in the layout run-flow.sh writes: verification/runs/bench-<cfg>-<stamp>/<test>.seed<S>.log + cycles.csv, and
# verification/runs/rerun-<stamp>/orig-<cfg>-<test>.seed<S>.log. A number counts only if its log says verified.
#   1. every bench log (every test, every seed) exists and passed its own check
#   2. the folder's cycles.csv equals the logs, row for row, in both directions, every row status 'passed'
#   3. a re-run folder (verification/runs/rerun-*, newest or --rerun) reproduces every number exactly, per seed
# run: ~/chipyard/.conda-env/bin/python verification/cross_check.py [--bench DIR ...] [--rerun DIR]
# exit 0 = all checks pass, 1 = a check failed (missing/unverified log included), 2 = no bench run exists at all.
import argparse, csv, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nmdata  # noqa: E402

CFGS = {"nm24": "GemminiNMRocketConfig", "nm48": "GemminiNM48RocketConfig"}
TESTS = ("nm_sparse_debug", "nm_sparse_matmul", "nm_sparse_perf", "nm_sparse_protocol")
BENCH_DIR_RE = re.compile(r"^bench-(nm24|nm48)-(\d{8}-\d{6})$")
LOG_RE = re.compile(r"^(nm_sparse_\w+?)\.seed(\d+)\.log$")
RERUN_RE = re.compile(r"^orig-(nm24|nm48)-(nm_sparse_\w+?)\.seed(\d+)\.log$")
fails = 0


def say(ok, msg):
    global fails
    fails += not ok
    print(("  ok    " if ok else "  FAIL  ") + msg)


def verified(r):
    return r is not None and r["passed"] and not r["failed"]


def find_bench(dirs=None):
    """{cfg: (stamp, folder)}: the given bench folders, else the newest bench-<cfg>-<stamp> per config."""
    found = {}
    cands = [Path(d) for d in dirs] if dirs else (sorted(nmdata.RUNS.glob("bench-*")) if nmdata.RUNS.is_dir() else [])
    for d in cands:
        m = BENCH_DIR_RE.match(d.name)
        if d.is_dir() and m and (m[1] not in found or m[2] > found[m[1]][0]):
            found[m[1]] = (m[2], d)
        elif dirs and not (d.is_dir() and m):
            nmdata.die_no_results(f"{d} is not a bench-<nm24|nm48>-<stamp> folder")
    return found


def read_logs(folder):
    """{(test, seed): parsed log} of the logs in a bench folder."""
    return {(m[1], m[2]): nmdata.parse_log(p) for p in sorted(folder.glob("*.log")) if (m := LOG_RE.match(p.name))}


def want_rows(logs, stamp, cfg):
    """{(seed, test, variant): (total, busy, tiles)} that cycles.csv must hold, from verified logs only."""
    want = {}
    for (t, seed), r in logs.items():
        if not verified(r):
            continue
        if t == "nm_sparse_matmul":
            want.update({(seed, t, v): (n, "", "") for v, n in r["matmul"].items()})
        elif t == "nm_sparse_perf":
            want.update({(seed, t, v): (p["total"], p.get("ex_active", ""), p["pairs"]) for v, p in r["perf"].items()})
    return want


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", nargs="+", type=Path, help="bench-<cfg>-<stamp> folder(s) (default: newest per config in verification/runs)")
    ap.add_argument("--rerun", type=Path, help="re-run folder (default: newest verification/runs/rerun-*)")
    a = ap.parse_args()
    bench = find_bench(a.bench)
    if not bench:
        nmdata.die_no_results(f"no bench run (bench-<cfg>-<stamp>/) in {nmdata.RUNS}; run ./run-flow.sh bench nm24|nm48")
    data = {cfg: (stamp, d, read_logs(d)) for cfg, (stamp, d) in bench.items()}

    print("1. every bench test passed its own correctness check, on every seed")
    for cfg, (stamp, d, logs) in sorted(data.items()):
        info = d / "run.info"
        listed = set(re.findall(r"^seeds=(.*)$", info.read_text(), re.M)[0].split()) if info.exists() and re.search(r"^seeds=", info.read_text(), re.M) else set()
        seeds = sorted({s for _, s in logs} | listed, key=int)
        say(bool(seeds), f"{cfg} ({d.name}): {len(logs)} logs found, seeds {','.join(seeds) or 'none'}")
        for s in seeds:
            for t in TESTS:
                r = logs.get((t, s))
                say(verified(r), f"{cfg} {t} seed {s}: " + ("log missing" if r is None else "printed 'passed' and no failure line"))

    print("\n2. bench cycles.csv matches the logs, row for row")
    for cfg, (stamp, d, logs) in sorted(data.items()):
        csv_path = d / "cycles.csv"
        rows = list(csv.DictReader(open(csv_path))) if csv_path.exists() else []
        if not rows:
            say(False, f"{cfg}: {csv_path} missing or empty")
            continue
        mine = [r for r in rows if r["timestamp"] == stamp and r["config"] == CFGS[cfg]]
        say(len(mine) == len(rows), f"{cfg}: every csv row has timestamp {stamp} and config {CFGS[cfg]} ({len(rows)} rows)")
        say(all(r["status"] == "passed" for r in mine), f"{cfg}: every csv row has status 'passed'")
        want = want_rows(logs, stamp, cfg)
        try:
            got = {(r["seed"], r["test"], r["variant"]): (int(r["total_cycles"]), int(r["array_busy_cycles"]) if r["array_busy_cycles"] else "",
                                                          int(r["tiles"]) if r["tiles"] else "") for r in mine}
        except (ValueError, KeyError) as e:
            say(False, f"{cfg}: {csv_path} unreadable ({e!r})")
            continue
        say(len(mine) == len(got), f"{cfg} {stamp}: no duplicate csv rows ({len(mine)} rows)")
        for k in sorted(set(want) | set(got), key=lambda k: (int(k[0]), k[1], k[2])):
            say(want.get(k) == got.get(k), f"{cfg} seed {k[0]} {k[1]} {k[2]}: log {want.get(k, 'missing')}, csv {got.get(k, 'missing')}")

    print("\n3. re-run reproduces the bench numbers exactly, seed by seed")
    try:
        rerun = a.rerun or sorted((d for d in nmdata.RUNS.glob("rerun-*") if d.is_dir()), key=lambda d: d.name)[-1]
    except IndexError:
        rerun = None
    if rerun is None:
        print("  skip  no verification/runs/rerun-* folder (./run-flow.sh rerun); nothing to compare")
    else:
        for cfg, (stamp, d, logs) in sorted(data.items()):
            for (t, s), a_ in sorted(logs.items(), key=lambda kv: (kv[0][0], int(kv[0][1]))):
                p = rerun / f"orig-{cfg}-{t}.seed{s}.log"
                if not p.exists():
                    say(False, f"{cfg} {t} seed {s}: {p} missing")
                    continue
                b = nmdata.parse_log(p)
                say(verified(b), f"{cfg} {t} seed {s}: re-run passed")
                n = sum(len(v) for v in a_["perf"].values()) + len(a_["matmul"]) + len(a_["debug"])
                say(verified(a_) and all(a_[k] == b[k] for k in ("perf", "matmul", "debug")),
                    f"{cfg} {t} seed {s}: all {n} numbers identical to bench {stamp}")

    print(f"\n{'ALL CHECKS PASSED' if not fails else str(fails) + ' CHECK(S) FAILED'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
