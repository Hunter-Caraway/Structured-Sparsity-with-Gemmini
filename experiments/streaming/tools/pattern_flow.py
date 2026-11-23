#!/usr/bin/env python3
"""Helpers of `run-flow.sh pattern` / `pattern-finish` (stdlib only).

Job plan files are TSV with the header
    chip  cfg  program  seed  timeout  kind  expect
kind: dense | sparse | neg | bench | fair. expect: for sparse the program's pass line, for neg the RTL assert text
(fixed string), else empty.

Subcommands
  reuse     drop stock jobs whose result already exists in a recorded run on the same stock simulator (sha256),
            from a program with the same loadable image (objcopy -O binary), with exit 0 and a verified log
  schedule  predict each job's wall time from recorded server runs, order longest first (LPT), print the plan
  summary   judge a copied-back run folder against its plan and write summary.md

Every predicted number is labelled with where it came from; predictions are never measurements.
"""
import argparse
import csv
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PLAN_COLS = ["chip", "cfg", "program", "seed", "timeout", "kind", "expect"]
DAY_S = 24 * 3600
MIN_RATE_WALL_S = 3600
# program families for jobs with no history of their own: (regex, replacement); a replacement with "*" takes the
# longest recorded member of the family. _fixa / _loop run one variant of the bench where _full runs three
FAMILIES = [(r"(.+_\d+)_(fixa|loop)$", r"\1_full"),
            (r"(nm_sparse_\w+_neg)\d+(_\d+)$", r"\1*\2")]
TIMEOUT_RE = re.compile(r"\(timeout\) after\s+(\d+) simulation cycles")
END_CYCLE_RE = re.compile(r"^sbench end cycle (\d+)$", re.M)
FAIL_MARKS = ("*** FAILED ***", "Assertion failed", "%Error", "%Fatal", "Verilog $stop")
TOTAL_RE = re.compile(r"^(\w+)\s+total\s+(\d+)\s", re.M)
SB_CHECK_RE = re.compile(r"^(\w+) check: hash \S+ expected \S+, sampled rows (\d+)/(\d+) -> (verified|MISMATCH)$",
                         re.M)
SB_PASS_RE = re.compile(r"^sbench passed \((\d+) of (\d+) runs verified\)$", re.M)
FAIR_MATCH_RE = re.compile(r"^(\w+) matches the cpu reference", re.M)
FAIR_PASS_RE = re.compile(r"^(fair_perf|berkeley_dense_perf) passed$", re.M)
# Berkeley tests that fail on the stock chip too (worklogs/berkeley-issues.md B4, B5); reported apart, still counted
KNOWN_BERKELEY = {"gemmini_counter": "B4", "global_average": "B5"}


def read_plan(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        missing = [c for c in PLAN_COLS if c not in r]
        if missing:
            sys.exit(f"{path}: plan row lacks columns {missing}")
    return rows


def write_plan(path, rows, extra=()):
    cols = PLAN_COLS + list(extra)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read_jobs_tsv(run):
    path = Path(run) / "jobs.tsv"
    if not path.exists():
        return []
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        r["prog"] = (r.get("binary") or r.get("program") or "").replace("-baremetal", "")
    return rows


def log_path(run, chip, prog, seed):
    return Path(run) / f"{chip}.{prog}.seed{seed}.log"


def read_text(path):
    return Path(path).read_text(errors="replace")


def base(prog):
    return prog.replace("-baremetal", "")


# ------------------------------------------------------------------ judging
def last_line(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def judge(kind, prog, expect, text, rc):
    """(ok, note) for one log. rc is the exit code from jobs.tsv (int)."""
    ends = "Verilog $finish" in last_line(text)
    fails = [m for m in FAIL_MARKS if m in text]
    if kind == "neg":
        if rc == 0:
            return False, "exit 0: the illegal use was not caught"
        if "Assertion failed" not in text:
            return False, f"exit {rc} without an RTL assert"
        if expect not in text:
            return False, f"assert text missing: {expect}"
        return True, expect
    if rc != 0:
        return False, f"exit {rc}" + (f" ({fails[0]})" if fails else "")
    if fails:
        return False, f"log has '{fails[0]}'"
    if not ends:
        return False, "last line is not 'Verilog $finish'"
    if kind == "dense":
        return True, ""
    if kind == "sparse":
        if not re.search(expect, text, re.M):
            return False, f"no line matching {expect}"
        return True, ""
    if kind == "bench":
        m = SB_PASS_RE.search(text)
        if not m or m.group(1) != m.group(2):
            return False, "no 'sbench passed (k of k runs verified)'"
        return True, m.group(0)
    if kind == "fair":
        if not FAIR_PASS_RE.search(text):
            return False, "no 'fair_perf passed' / 'berkeley_dense_perf passed'"
        totals = [v for v, _ in TOTAL_RE.findall(text) if not v.startswith("cpu_")]
        matched = FAIR_MATCH_RE.findall(text)
        bad = [v for v in totals if matched.count(v) != 1]
        if bad:
            return False, f"no single 'matches the cpu reference' for {bad}"
        return True, f"{len(totals)} variants matched"
    return False, f"unknown kind {kind}"


def bench_rows(text):
    """variant -> (total cycles, verified flag) from one streaming-bench log."""
    tot = {v: int(c) for v, c in TOTAL_RE.findall(text)}
    chk = {m.group(1): m.group(4) == "verified" and m.group(2) == m.group(3) for m in SB_CHECK_RE.finditer(text)}
    return {v: (c, chk.get(v, False)) for v, c in tot.items()}


def fair_rows(text):
    tot = {v: int(c) for v, c in TOTAL_RE.findall(text)}
    matched = set(FAIR_MATCH_RE.findall(text))
    return {v: (c, v.startswith("cpu_") or v in matched) for v, c in tot.items()}


# ------------------------------------------------------------------ reuse
def load_image_sha(objcopy, path):
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "img")
        subprocess.run([objcopy, "-O", "binary", str(path), out], check=True)
        return hashlib.sha256(Path(out).read_bytes()).hexdigest()


def run_stock_sha(run):
    """sha256 (full or the 16-char prefix run-flow.sh records) of the stock simulator a recorded run used."""
    info = Path(run) / "run.info"
    if not info.exists():
        return None
    for line in info.read_text(errors="replace").splitlines():
        if line.startswith("sim.stock=") or line.startswith("sim.GemminiRocketConfig="):
            m = re.search(r"sha256[=:]([0-9a-f]{16,64})", line)
            if m:
                return m.group(1)
    return None


def cmd_reuse(a):
    plan = read_plan(a.plan)
    runs = sorted(p for p in Path(a.runs_root).iterdir() if (p / "jobs.tsv").exists())
    cands = [r for r in runs if (s := run_stock_sha(r)) and a.stock_sha.startswith(s)]
    img_cache = {}

    def img(path):
        if path not in img_cache:
            img_cache[path] = load_image_sha(a.objcopy, path)
        return img_cache[path]

    keep, reused = [], []
    for j in plan:
        if j["chip"] != "stock":
            keep.append(j)
            continue
        prog = base(j["program"])
        want = img(Path(a.bin) / j["program"])
        hit = None
        for r in reversed(cands):  # newest recorded run first
            rb = r / "bin" / j["program"]
            if not rb.exists() or img(rb) != want:
                continue
            for row in read_jobs_tsv(r):
                if row["chip"] == "stock" and row["prog"] == prog and row["seed"] == j["seed"] and row["exit"] == "0":
                    lp = log_path(r, "stock", prog, j["seed"])
                    if lp.exists() and judge(j["kind"], prog, j["expect"], read_text(lp), 0)[0]:
                        hit = lp
                        break
            if hit:
                break
        if hit:
            reused.append({**j, "log": str(hit)})
        else:
            keep.append(j)
    write_plan(a.out, keep)
    write_plan(a.reused, reused, extra=["log"])
    print(f"stock simulator sha256 {a.stock_sha[:16]}...: {len(cands)} recorded run(s) on the same stock simulator")
    for r in reused:
        print(f"  reuse  stock {base(r['program'])} seed {r['seed']}: {r['log']}")
    n_stock = sum(1 for j in keep if j["chip"] == "stock")
    print(f"  {len(reused)} stock job(s) reused, {n_stock} scheduled")


# ------------------------------------------------------------------ schedule
def history(runs):
    """(chip, prog) -> newest record {wall, timeout, timed_out, rate, run}; plus all measured rates."""
    hist, rates = {}, []
    for run in sorted(runs):
        for r in read_jobs_tsv(run):
            try:
                wall, tmo = int(r["wall_s"]), int(r["timeout"])
            except (KeyError, ValueError):
                continue
            if wall <= 0:
                continue
            lp = log_path(run, r["chip"], r["prog"], r["seed"])
            text = read_text(lp) if lp.exists() else ""
            m = TIMEOUT_RE.search(text)
            e = END_CYCLE_RE.search(text)
            rate = None
            if m:
                rate = int(m.group(1)) / wall
            elif e:
                rate = int(e.group(1)) / wall
            # short jobs are dominated by simulator start-up (DRAM model, loadmem), so only long ones give a rate
            if rate and wall >= MIN_RATE_WALL_S:
                rates.append((rate, f"{lp.parent.name}/{lp.name}", r["chip"]))
            hist[(r["chip"], r["prog"])] = {"wall": wall, "timeout": tmo, "timed_out": bool(m), "rate": rate,
                                            "run": Path(run).name}
    return hist, rates


def analogs(chip, prog, sfx):
    """(chip, prog) keys to try for a job with no history of its own, nearest first: the same chip with the
    program of another pattern, then the 2:4 / 4:8 chips."""
    progs = [prog]
    if sfx and re.search(rf"_{sfx}(_|$)", prog):
        progs += [re.sub(rf"_{sfx}(_|$)", rf"_{o}\1", prog) for o in ("24", "48") if o != sfx]
    for rx, rp in FAMILIES:
        progs += [re.sub(rx, rp, q) for q in list(progs) if re.fullmatch(rx, q)]
    # an N:M chip running a dense-only program (sameprog) is compared with stock last
    chips = [chip] + [c for c in ("nm24", "nm48") if c != chip and chip != "stock"]
    chips += ["stock"] if chip != "stock" else []
    return [(c, p) for c in chips for p in progs]


def predict(j, hist, rates, sfx, hints):
    chip, prog, tmo = j["chip"], base(j["program"]), int(j["timeout"])
    # slowest measured rate of this chip (of any chip if it has none): budget-bound predictions are upper bounds
    own = [r for r in rates if r[2] == chip] or rates
    if own:
        rate_floor, src, _ = min(own)
        rate_src = f"slowest measured, {src}"
    else:
        rate_floor, rate_src = 1000.0, "no measured rate; assumed"
    for k in analogs(chip, prog, sfx):
        if "*" in k[1]:
            rx = re.escape(k[1]).replace(r"\*", r"\d+")
            fam = [(v["wall"], hk) for hk, v in hist.items() if hk[0] == k[0] and re.fullmatch(rx, hk[1])
                   and not v["timed_out"]]
            if not fam:
                continue
            k = max(fam)[1]
        h = hist.get(k)
        if not h:
            continue
        tag = "" if k == (chip, prog) else f" (analog {k[0]}.{k[1]})"
        if h["timed_out"]:
            if tmo <= h["timeout"]:
                sec, src = h["wall"] * tmo / h["timeout"], f"timed out at {h['timeout']:,} in {h['run']}{tag}"
            else:
                rate = h["rate"] or rate_floor
                sec = tmo / rate
                src = f"timed out at {h['timeout']:,} in {h['run']}{tag}; budget {tmo:,} / {rate:.0f} c/s (upper bound)"
        else:
            sec, src = h["wall"], f"wall {h['wall']} s in {h['run']}{tag}"
        break
    else:
        sec = tmo / rate_floor
        src = f"no history; budget {tmo:,} / {rate_floor:.0f} c/s ({rate_src}) (upper bound)"
    for rx, fac, why in hints:
        if re.fullmatch(rx, prog):
            sec *= fac
            src += f"; x{fac:g} hint: {why}"
    return sec, src


def cmd_schedule(a):
    plan = read_plan(a.plan)
    hist, rates = history(a.history)
    hints = []
    for h in a.hint or []:
        rx, rest = h.split("=", 1)
        fac, why = rest.split(":", 1)
        hints.append((rx, float(fac), why))
    for j in plan:
        j["pred_s"], j["pred_src"] = predict(j, hist, rates, a.sfx, hints)
    # --last: Berkeley tests that run for days start after the rest, so they do not hold every slot while the sparse tests wait
    last = re.compile(a.last) if a.last else None
    plan.sort(key=lambda j: (bool(last and last.search(base(j["program"]))), -j["pred_s"], j["chip"], j["program"], int(j["seed"])))
    slots = [0.0] * max(1, a.slots)
    for j in plan:  # list scheduling in LPT order: each job takes the slot that frees first
        i = min(range(len(slots)), key=slots.__getitem__)
        j["start_s"], slots[i] = slots[i], slots[i] + j["pred_s"]
        j["end_s"] = slots[i]
    total = max(slots)
    write_plan(a.out, plan, extra=["pred_s", "pred_src"])
    print(f"predicted schedule: {len(plan)} jobs on {a.slots} slot(s), longest first "
          f"(history: {len(a.history)} run folder(s), {len(rates)} measured cycles/s rates)")
    print(f"{'#':>3} {'chip':6} {'program':48} {'seed':>4} {'timeout':>11} {'pred h':>7} {'start h':>7} "
          f"{'end h':>7}  source")
    long_jobs = []
    for i, j in enumerate(plan, 1):
        flag = "  WARN >24h" if j["pred_s"] > DAY_S else ""
        if flag:
            long_jobs.append(j)
        print(f"{i:>3} {j['chip']:6} {base(j['program']):48} {j['seed']:>4} {int(j['timeout']):>11,} "
              f"{j['pred_s'] / 3600:>7.1f} {j['start_s'] / 3600:>7.1f} {j['end_s'] / 3600:>7.1f}  {j['pred_src']}{flag}")
    print(f"predicted total wall time: {total / 3600:.1f} h ({total / DAY_S:.2f} days) on {a.slots} slot(s)"
          + ("  (over the 24 h target)" if total > DAY_S else "  (within the 24 h target)"))
    for j in long_jobs:
        print(f"  warning: {j['chip']} {base(j['program'])} seed {j['seed']} predicted {j['pred_s'] / 3600:.1f} h "
              f"(> 24 h); it is not killed for time, its cycle budget is {int(j['timeout']):,}")


# ------------------------------------------------------------------ summary
def cmd_summary(a):
    run = Path(a.run)
    plan = read_plan(a.plan)
    reused = read_plan(a.reused) if a.reused and Path(a.reused).exists() else []
    jobs = {(r["chip"], r["prog"], r["seed"]): r for r in read_jobs_tsv(run)}
    res = []  # (job, ok, note, log path)
    for j in plan:
        prog = base(j["program"])
        lp = log_path(run, j["chip"], prog, j["seed"])
        row = jobs.get((j["chip"], prog, j["seed"]))
        if row is None or not lp.exists():
            res.append((j, False, "no jobs.tsv row or no log", lp))
            continue
        ok, note = judge(j["kind"], prog, j["expect"], read_text(lp), int(row["exit"]))
        res.append((j, ok, note, lp))
    for j in reused:
        lp = Path(j["log"])
        ok, note = judge(j["kind"], base(j["program"]), j["expect"], read_text(lp), 0)
        res.append((j, ok, "reused; " + note, lp))

    def rel(p):
        try:
            return str(Path(p).resolve().relative_to(Path(a.root).resolve()))
        except ValueError:
            return str(p)

    out = [f"# Pattern flow summary: {a.pattern} ({a.cfg})", "",
           f"Run folder: `{rel(run)}`. Generated by `tools/pattern_flow.py summary` from the logs; every number below "
           "is copied from the log named next to it.", ""]
    fails = [(j, n, lp) for j, ok, n, lp in res if not ok]

    def count(kind, chip):
        rs = [(j, ok, n, lp) for j, ok, n, lp in res if j["kind"] == kind and j["chip"] == chip]
        return sum(ok for _, ok, _, _ in rs), len(rs), rs

    d_ok, d_n, d_rs = count("dense", a.pattern)
    s_ok, s_n, _ = count("sparse", a.pattern)
    n_ok, n_n, n_rs = count("neg", a.pattern)
    out += ["## Counts", "", "| what | pass | of |", "|---|---|---|",
            f"| Berkeley dense tests on {a.pattern} | {d_ok} | {d_n} |",
            f"| nm_sparse_* tests on {a.pattern} | {s_ok} | {s_n} |",
            f"| RTL NEG asserts on {a.pattern} | {n_ok} | {n_n} |", ""]
    known = [(j, n, lp) for j, ok, n, lp in d_rs if not ok and base(j["program"]) in KNOWN_BERKELEY]
    if known:
        out += ["Dense failures that are known Berkeley bugs (they also fail on stock; counted above as failures):", ""]
        out += [f"- {base(j['program'])} ({KNOWN_BERKELEY[base(j['program'])]}, worklogs/berkeley-issues.md): {n} "
                f"(`{rel(lp)}`)" for j, n, lp in known] + [""]
    out += ["## NEG assert texts", ""]
    out += [f"- {'ok  ' if ok else 'FAIL'} {base(j['program'])}: {n} (`{rel(lp)}`)" for j, ok, n, lp in n_rs] + [""]

    # benches: per layer, the pattern chip's variants and stock's berkeley, from the logs
    out += ["## Streaming benches (total cycles; [v] = verified, [NOT VERIFIED] otherwise)", "",
            "Same-chip ratio = berkeley on the pattern chip / variant (same build). Stock ratio = berkeley on stock / "
            "variant: cross-chip (different builds, labelled per the 2026-11-12 ruling).", "",
            "| layer | chip | variant | cycles | verified | same-chip berkeley / variant | stock berkeley / variant | log |",
            "|---|---|---|---|---|---|---|---|"]
    bench = {}
    for j, ok, n, lp in res:
        if j["kind"] != "bench" or not lp.exists():
            continue
        m = re.match(r"(.+)_\d+_(full|fixa|loop|dense)$", base(j["program"]))
        layer = m.group(1) if m else base(j["program"])
        for v, (c, ver) in bench_rows(read_text(lp)).items():
            bench.setdefault(layer, {})[(j["chip"], v)] = (c, ver and ok, lp)
    for layer in sorted(bench):
        rows = bench[layer]
        own = rows.get((a.pattern, "berkeley"))
        stock = rows.get(("stock", "berkeley"))
        for (chip, v), (c, ver, lp) in sorted(rows.items()):
            same = f"{own[0] / c:.3f}" if own and own[1] and ver and chip == a.pattern else ""
            cross = f"{stock[0] / c:.3f}" if stock and stock[1] and ver and chip == a.pattern else ""
            out.append(f"| {layer} | {chip} | {v} | {c:,} | {'[v]' if ver else '[NOT VERIFIED]'} | {same} | {cross} | "
                       f"`{rel(lp)}` |")
    out += ["", "## Fair benchmark (total cycles per variant; [v] = matched the cpu reference)", ""]
    for j, ok, n, lp in res:
        if j["kind"] != "fair" or not lp.exists():
            continue
        vs = fair_rows(read_text(lp))
        line = ", ".join(f"{v} {c:,}{'' if ver else ' [NOT VERIFIED]'}" for v, (c, ver) in vs.items()
                         if not v.startswith("cpu_"))
        out.append(f"- {j['chip']} {base(j['program'])} seed {j['seed']} {'ok' if ok else 'FAIL'}: {line} (`{rel(lp)}`)")
    out += ["", "## Area", ""]
    if not a.area:
        out.append("- no area output (area stage not run)")
    for f in a.area or []:
        p = Path(f)
        if not p.exists():
            out.append(f"- MISSING area output `{rel(p)}`")
            continue
        lines = [ln for ln in read_text(p).splitlines() if re.search(r"area", ln, re.I)][-20:]
        out.append(f"- `{rel(p)}` (last {len(lines)} lines mentioning area):")
        out += [f"  - {ln.strip()}" for ln in lines]
    out += ["", "## Parsers and stages", ""]
    for s in a.stage or []:
        out.append(f"- {s}")
    out += ["", f"## Failures ({len(fails)})", ""]
    out += [f"- {j['chip']} {base(j['program'])} seed {j['seed']}: {n} (`{rel(lp)}`)" for j, n, lp in fails]
    if not fails:
        out.append("- none")
    text = "\n".join(out) + "\n"
    Path(a.out).write_text(text)
    print(text)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reuse")
    r.add_argument("--plan", required=True)
    r.add_argument("--bin", required=True, help="folder with the new programs")
    r.add_argument("--runs-root", required=True)
    r.add_argument("--stock-sha", required=True)
    r.add_argument("--objcopy", default="riscv64-unknown-elf-objcopy")
    r.add_argument("--out", required=True)
    r.add_argument("--reused", required=True)
    s = sub.add_parser("schedule")
    s.add_argument("--plan", required=True)
    s.add_argument("--history", nargs="*", default=[])
    s.add_argument("--slots", type=int, required=True)
    s.add_argument("--sfx", default="")
    s.add_argument("--hint", action="append", help="<program regex>=<factor>:<reason>")
    s.add_argument("--last", help="regex of programs scheduled after all others")
    s.add_argument("--out", required=True)
    m = sub.add_parser("summary")
    m.add_argument("--run", required=True)
    m.add_argument("--plan", required=True)
    m.add_argument("--reused")
    m.add_argument("--pattern", required=True)
    m.add_argument("--cfg", required=True)
    m.add_argument("--root", default=".")
    m.add_argument("--area", nargs="*")
    m.add_argument("--stage", action="append")
    m.add_argument("--out", required=True)
    a = ap.parse_args()
    rc = {"reuse": cmd_reuse, "schedule": cmd_schedule, "summary": cmd_summary}[a.cmd](a)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
