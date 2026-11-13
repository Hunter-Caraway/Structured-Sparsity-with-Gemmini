#!/usr/bin/env python3
"""Check a run folder, and compare it number for number with a reference run folder.

Every log in RUN (fair logs <chip>[.seed<S>].log and re-run logs orig-<cfg>-<test>.log, see nmdata.py) must have
passed with no failure line. With REFERENCE, each (log, seed) must exist in both folders and every number
(perf rows, counters, prep, matmul, debug, reference checks) must be identical: a simulation with a given seed is
deterministic. Without REFERENCE only the pass checks run (there are no recorded results to compare with).

usage: ~/chipyard/.conda-env/bin/python verification/compare_runs.py RUN [REFERENCE]
exit 0 = all good, 1 = a log failed or differs, 2 = RUN has no logs.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nmdata  # noqa: E402

ORIG_RE = re.compile(r"^(orig-(?:nm24|nm48)-nm_sparse_\w+?)(?:[.-]seed(\w+))?\.log$")
NUMBERS = ("perf", "prep", "matmul", "debug", "ref_ok")


def logs(run):
    """{(name, seed): parsed log} for every fair and re-run log in run."""
    out = {}

    def add(key, d):
        if key in out:
            sys.exit(f"two {key[0]} logs with seed {key[1]}: {out[key]['path']} and {d['path']}")
        out[key] = d
    for chip, name_seed, p in nmdata.fair_logs(run):
        d = nmdata.parse_log(p)
        add((chip, d["seed"] or name_seed or "default"), d)
    for p in sorted(run.glob("orig-*.log")):
        m = ORIG_RE.match(p.name)
        if m:
            d = nmdata.parse_log(p)
            add((m[1], d["seed"] or m[2] or "default"), d)
    return out


def diff(a, b):
    lines = []
    for v in sorted(set(a["perf"]) | set(b["perf"])):
        ra, rb = a["perf"].get(v), b["perf"].get(v)
        if ra is None or rb is None:
            lines.append(f"{v}: only in the {'reference' if rb is None else 'new run'}")
        elif ra != rb:
            lines.append(f"{v}: " + ", ".join(f"{k} {ra.get(k)} -> {rb.get(k)}" for k in sorted(set(ra) | set(rb)) if ra.get(k) != rb.get(k)))
    for k in NUMBERS[1:]:
        if a[k] != b[k]:
            lines.append(f"{k}: reference {a[k]}, new {b[k]}")
    return lines


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    try:
        run = nmdata.find_runs([sys.argv[1]])[0]
        ref = nmdata.find_runs([sys.argv[2]])[0] if len(sys.argv) == 3 else None
    except nmdata.NoResults as e:
        nmdata.die_no_results(e)
    new = logs(run)
    if not new:
        nmdata.die_no_results(f"no recognised logs in {run}")
    fails = 0
    print(f"checking {run}" + (f" against {ref}" if ref else " (no reference run given: pass checks only)"))
    for key, d in sorted(new.items()):
        ok = d["passed"] and not d["failed"]
        fails += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {key[0]} seed {key[1]}: {'passed' if ok else 'DID NOT PASS'}, "
              f"{d['ref_checks']} result(s) matched the cpu reference")
    if ref:
        old = logs(ref)
        for key in sorted(set(old) | set(new)):
            if key not in new or key not in old:
                fails += 1
                print(f"  FAIL  {key[0]} seed {key[1]}: only in {'the reference' if key in old else 'the new run'}")
                continue
            lines = diff(old[key], new[key])
            n = sum(len(v) for v in old[key]["perf"].values()) + len(old[key]["prep"]) + len(old[key]["matmul"]) + len(old[key]["debug"])
            fails += bool(lines)
            print(f"  {'FAIL' if lines else 'PASS'}  {key[0]} seed {key[1]}: " + (f"all {n} numbers identical" if not lines else "differs"))
            for l in lines:
                print(f"        {l}")
    print(f"\n{'ALL GOOD' if not fails else f'{fails} PROBLEM(S)'}  ({len(new)} logs checked{', compared with ' + ref.name if ref else ''})")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
