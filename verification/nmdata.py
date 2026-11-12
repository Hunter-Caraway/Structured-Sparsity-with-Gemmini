"""Shared loader for the N:M sparsity results (verify_all.py, compare_runs.py, paper_data.py, analysis/).

Reads the raw simulator logs of a run folder, verification/runs/<name>/, as run-flow.sh `fair` writes them:
  <chip>.log, <chip>.seed<S>.log or <chip>-seed<S>.log (also one folder level down, e.g. seed3/nm24.log),
  chip = berkeley | sameprog | nm24 | nm48 (nm24_sameprog is read as sameprog).
A log's seed is the +verilator+seed+<S> in its own make command line, else the seed<S> in its file or folder
name, else "default". The newest run folder is the one with the largest YYYYMMDD-HHMMSS stamp in its name.
Several seeds: every number becomes a stat (min / max / mean over seeds). Nothing is hard-coded; with no
results every loader raises NoResults, whose message says what to run. NM_RUNS_DIR overrides verification/runs.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VER = ROOT / "verification"
RUNS = Path(os.environ.get("NM_RUNS_DIR") or VER / "runs")
DIM = 16

CHIPS = ("berkeley", "sameprog", "nm24", "nm48")
ALIASES = {"nm24_sameprog": "sameprog"}
PATTERN = {"nm24": "2:4", "nm48": "4:8"}

PERF_RE = re.compile(r"^(\w+)\s+total\s+(\d+)\s+cpu_issue_done\s+(\d+)\s+pairs\s+(\d+)\s+cyc/pair\s+(\d+)\s*\|(.*)$", re.M)
PREP_RE = re.compile(r"^(prep_\w+)\s+prep\s+(\d+)\s+prune\s+(\d+)\s+compress\s+(\d+)\s+pack_meta\s+(\d+)\s+weights\s+(\d+)", re.M)
HEADER_RE = re.compile(r"^fair_perf: (\d+):(\d+), i=(\d+) k=(\d+) j=(\d+)", re.M)
BUILD_RE = re.compile(r"^fair_perf build: (full|dense-only)", re.M)
SEED_CMD_RE = re.compile(r"\+verilator\+seed\+(\d+)")
SEED_NAME_RE = re.compile(r"seed[-_]?(\w+?)$")
LOG_RE = re.compile(r"^(berkeley|nm24_sameprog|sameprog|nm24|nm48)(?:[.-]seed(\w+))?\.log$")
STAMP_RE = re.compile(r"(\d{8}-\d{6})")
FAIL_RE = re.compile(r"FAILED|mismatch|[Aa]ssertion|TIMEOUT|[Tt]imed out")


class NoResults(Exception):
    """No usable results; the message says what to do."""


def die_no_results(e):
    print(f"no results: {e}", file=sys.stderr)
    sys.exit(2)


def parse_log(path):
    """Everything one benchmark log reports."""
    t = Path(path).read_text(errors="replace")
    out = {"path": str(path), "seed": None, "passed": bool(re.search(r"^\w+ passed$", t, re.M)),
           "failed": bool(FAIL_RE.search(t)), "header": None, "build": None, "perf": {}, "prep": {},
           "ref_ok": [m[1] for m in re.finditer(r"^(\w+) matches the cpu reference", t, re.M)],
           "poison_ok": "poison reaches the accumulator" in t, "matmul": {}, "debug": {}}
    out["ref_checks"] = len(out["ref_ok"])
    s = SEED_CMD_RE.search(t)
    if s:
        out["seed"] = s[1]
    h = HEADER_RE.search(t)
    if h:
        out["header"] = dict(zip(("n", "m", "i", "k", "j"), map(int, h.groups())))
    b = BUILD_RE.search(t)
    if b:
        out["build"] = b[1]
    for m in PERF_RE.finditer(t):
        ctr = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", m[6])}
        out["perf"][m[1]] = {"total": int(m[2]), "issued": int(m[3]), "pairs": int(m[4]), "cyc_pair": int(m[5]), **ctr}
    for m in PREP_RE.finditer(t):
        out["prep"][m[1]] = dict(zip(("prep", "prune", "compress", "pack_meta", "weights"), map(int, m.groups()[1:])))
    for m in re.finditer(r"^(dense|sparse)\s+cycles: (\d+)", t, re.M):
        out["matmul"][m[1]] = int(m[2])
    for m in re.finditer(r"^  (.+?)\s+(\d+) / 256$", t, re.M):
        out["debug"][m[1].strip()] = int(m[2])
    return out


def fair_logs(run):
    """[(chip, seed or None, path)] of the fair logs in a run folder and its direct subfolders."""
    run = Path(run)
    found = []
    for p in sorted(list(run.glob("*.log")) + list(run.glob("*/*.log"))):
        if "derived" in p.relative_to(run).parts:
            continue
        m = LOG_RE.match(p.name)
        if not m:
            continue
        seed = m[2]
        if seed is None and p.parent != run:
            n = SEED_NAME_RE.search(p.parent.name)
            seed = n[1] if n else None
        found.append((ALIASES.get(m[1], m[1]), seed, p))
    return found


def _stamp_key(d):
    m = STAMP_RE.search(d.name)
    return (1, m[1], d.name) if m else (0, f"{d.stat().st_mtime:020.6f}", d.name)


def find_runs(args=None):
    """Run folders to read: the given ones (str or Path, absolute or relative to cwd or the repo), else [newest]."""
    if args:
        out = []
        for a in ([args] if isinstance(args, (str, Path)) else args):
            hit = next((p for p in (Path(a), ROOT / a) if p.is_dir()), None)
            if hit is None:
                raise NoResults(f"run folder '{a}' does not exist")
            out.append(hit.resolve())
        return out
    cands = sorted((d for d in RUNS.iterdir() if d.is_dir() and fair_logs(d)), key=_stamp_key) if RUNS.is_dir() else []
    if not cands:
        raise NoResults(f"no fair benchmark results in {RUNS} (the old results were withdrawn). "
                        "Produce them with ./run-flow.sh fair, or pass a run folder.")
    return [cands[-1]]


def seed_key(s):
    return (0, int(s), "") if s.isdigit() else (1, 0, s)


def load_fair(runs=None, require=("berkeley", "nm24", "nm48")):
    """{chip: {seed: parsed log}} over the given run folders (default: the newest)."""
    res = {}
    folders = find_runs(runs)
    for run in folders:
        for chip, name_seed, p in fair_logs(run):
            log = parse_log(p)
            seed = log["seed"] or name_seed or "default"
            log["seed"] = seed
            if seed in res.get(chip, {}):
                raise NoResults(f"two {chip} logs with seed {seed}: {res[chip][seed]['path']} and {p}")
            res.setdefault(chip, {})[seed] = log
    if not res:
        raise NoResults(f"no fair logs (<chip>.log) in {', '.join(map(str, folders))}")
    missing = [c for c in require if c not in res]
    if missing:
        raise NoResults(f"{', '.join(map(str, folders))}: no log for {', '.join(missing)}")
    return {c: dict(sorted(res[c].items(), key=lambda kv: seed_key(kv[0]))) for c in CHIPS if c in res}


def stat(values):
    v = list(values)
    return {"values": v, "n": len(v), "min": min(v), "max": max(v), "range": max(v) - min(v), "mean": sum(v) / len(v)}


def metric(chip_logs, variant, key="total"):
    """stat over seeds of perf[variant][key]; None if any seed lacks it."""
    try:
        return stat(log["perf"][variant][key] for log in chip_logs.values())
    except KeyError:
        return None


def ratio(num, den):
    """(lowest, highest) of num/den over every pair of seeds."""
    return num["min"] / den["max"], num["max"] / den["min"]


def fmt_stat(s):
    return f"{s['min']:,}" if s["min"] == s["max"] else f"{s['min']:,}-{s['max']:,}"


def fmt_ratio(r):
    return f"{r[0]:.2f}x" if f"{r[0]:.2f}" == f"{r[1]:.2f}" else f"{r[0]:.2f}x-{r[1]:.2f}x"


def _row(logs, k):
    r = {"pairs": metric(logs, k, "pairs"), "busy_fresh": metric(logs, k, "ex_active"),
         "busy_reuse": metric(logs, k + "_reuse", "ex_active"), "fresh": metric(logs, k),
         "reuse": metric(logs, k + "_reuse"), "cpu_fresh": metric(logs, "cpu_" + k),
         "cpu_reuse": metric(logs, "cpu_" + k + "_reuse")}
    if k == "sparse":
        r.update(batched=metric(logs, "sparse_batched"), busy_batched=metric(logs, "sparse_batched", "ex_active"),
                 cpu_batched=metric(logs, "cpu_sparse_batched"), cpu_meta_only=metric(logs, "cpu_meta_only"))
    return {a: b for a, b in r.items() if b is not None}


def summary(fair):
    """{row: {metric: stat}}: berkeley, sameprog, 2:4, 4:8 (sparse on), off_2:4, off_4:8 (same chip, dense loops)."""
    out = {}
    for chip in ("berkeley", "sameprog"):
        if chip in fair:
            out[chip] = _row(fair[chip], "dense")
    for chip, pat in PATTERN.items():
        if chip in fair:
            out[pat] = _row(fair[chip], "sparse")
            out["off_" + pat] = _row(fair[chip], "dense")
    return out


def load_fidelity():
    """pattern_fidelity.out -> {(distribution, rule): (energy_kept_pct, answer_error_pct)}"""
    fid = {}
    for l in (VER / "pattern_fidelity.out").read_text().splitlines():
        m = re.match(r"^(bell curve|heavy tail)\s+(paired 4:8|2:4|4:8|no pattern)\s+([\d.]+)%\s+([\d.]+)%", l)
        if m:
            fid[(m[1], m[2])] = (float(m[3]), float(m[4]))
    return fid
