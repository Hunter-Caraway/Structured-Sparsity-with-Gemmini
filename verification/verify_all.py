#!/usr/bin/env python3
"""One command that re-checks the claims of the N:M sparsity work against a fair benchmark run.

  A  original benchmark pipeline: bench logs, results/cycles.csv, re-run     (cross_check.py; skip if no bench logs)
  B  independent math check: sparse math == dense math, injected faults caught (independent_math_check.py)
  C  pattern comparison reproduces pattern_fidelity.out exactly                (pattern_fidelity.py)
  D  fair run: every log passed, every gemmini variant matched the cpu reference, current fair_perf.c (warm-up,
     poison), right build per chip, same seeds on every chip, pair counts computed from the problem size,
     array time near N/M of the same chip's dense time, our chip with sparsity off within 1% of Berkeley
  E  the paper summary PDF prints the run's numbers                            (skip if there is no PDF)
  F  the code patches in the zip rebuild the sparse-nm branches                 (skip if there is no zip)
  G  integrity: run-folder SHA256SUMS (if any) and verification/MANIFEST.sha256 of the static files (if any)
  H  README: the table between <!-- results:begin --> and <!-- results:end --> equals paper_data.readme_table()

usage: ~/chipyard/.conda-env/bin/python verification/verify_all.py [RUN ...] [--skip-patches] [--write-manifest]
RUN = fair run folder(s), default the newest in verification/runs. Report: <first RUN>/derived/verify_all_report.md.
exit 0 = every check passed, 1 = a check failed, 2 = no fair results (B and C still run).

--mode run RUN ... [--extra-log LOG ...]: only the integrity of any server run folder (<chip>.<program>.seed<S>.log,
jobs.tsv, run.info, SHA256SUMS), for any N:M chip of run-flow.sh nm_table; no paper, README or recorded-number check
(A-H above are --mode paper, the default). Writes nothing. --extra-log adds a log reused from another recorded run
(checked against its own folder's run.info, jobs.tsv and SHA256SUMS).
  I  SHA256SUMS of each run folder (and of each extra log's folder)
  S  run.info has sim.<chip>=<config> sha256=<64 hex> for every chip with a log; the config is the chip's run-flow.sh
     config; every log names that config; one simulator build per chip
  J  jobs.tsv and the logs match one to one; every job exited 0, or is a NEG build or known Berkeley failure that
     parse_fixa.py accepts; parse_fixa.py rc 0
  V  every streaming bench log: every variant "-> verified" (hash == expected, all sampled rows), "sbench passed (k of k)",
     header pattern = the chip's pattern, hash == ref/<layer>_<pat>.json when the run has ref/
  R  fair logs: passed, every gemmini variant matched the cpu reference, build and pattern of the program, pair counts
     from the problem size, same seeds on every chip; ratios recomputed from the log lines: sparse/dense array time
     near N/M, sparsity-off vs stock within 1%; streaming cycles vs Berkeley on stock (printed as INFO, not checked)
exit 0 = every check passed, 1 = a check failed, 2 = no job logs.
"""
import argparse, csv, hashlib, json, os, re, subprocess, sys, tempfile, zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nmdata  # noqa: E402
import paper_data  # noqa: E402

ROOT, VER = nmdata.ROOT, nmdata.VER
PY = sys.executable
GEM = Path(os.environ.get("CHIPYARD_DIR") or Path.home() / "chipyard") / "generators/gemmini"
REPOS = {"gemmini": (GEM, "8c3f9923"), "libgemmini": (GEM / "software/libgemmini", "ea8f7ed"),
         "gemmini-rocc-tests": (GEM / "software/gemmini-rocc-tests", "7c540b3")}
MANIFEST = VER / "MANIFEST.sha256"
MANIFEST_GLOBS = ["logs/**/*.log", "logs/**/*.txt", "logs/**/*.patch", "verification/bin/*-baremetal",
                  "verification/*.c", "verification/*.out"]
GRID_TOL = 0.10      # sparse/dense array time (weights reused, same chip) may differ from N/M by this fraction
SAMEPROG_TOL = 0.01  # our chip with sparsity off vs Berkeley, same program: every pair of seeds within this
EXPECT = {"berkeley": ("dense-only", "2:4", ["dense", "dense_reuse"]),
          "sameprog": ("dense-only", "2:4", ["dense", "dense_reuse"]),
          "nm24": ("full", "2:4", ["dense", "dense_reuse", "sparse", "sparse_reuse", "sparse_batched"]),
          "nm48": ("full", "4:8", ["dense", "dense_reuse", "sparse", "sparse_reuse", "sparse_batched"])}
# sparse-loop-fix variants of fair_perf.c: required in every log of a run as soon as one log has one
LOOP_EXPECT = {"dense-only": ["dense_loop"], "full": ["dense_loop", "sparse_loop"]}
# --mode run
RUN_LOG_RE = re.compile(r"^([^.]+)\.(.+)\.seed(\d+)\.log$")
STOCK_CFG = "GemminiRocketConfig"  # run-flow.sh cfg_name dense
# files a server run writes after its SHA256SUMS: STATUS (~/fixb/run_jobs.sh) and the driver's own stdout
# (tools/pattern_srv_driver.sh leaves driver.out out of SHA256SUMS)
UNLISTED_OK = ("STATUS", "driver.out")
BENCH_NAME_RE = re.compile(r"^(\w+?)_(\d+)_(full|loop|fixa|dense|ds)$")
SBENCH_HDR_RE = re.compile(r"^sbench: layer=(\S+) .*?pattern=(\d+):(\d+) build=(\S+) run_mask=(\d+)", re.M)
SBENCH_TOT_RE = re.compile(r"^(\w+)\s+total\s+(\d+)\s+cpu_issue_done\s+(\d+) \|", re.M)
SBENCH_CHK_RE = re.compile(r"^(\w+) check: hash (0x[0-9a-f]{16}) expected (0x[0-9a-f]{16}), sampled rows (\d+)/(\d+) -> (\w+)$", re.M)
BDP_HDR_RE = re.compile(r"^berkeley_dense_perf: [^,]*, (\d+):(\d+) pruned weights, i=(\d+) k=(\d+) j=(\d+)", re.M)
PF_TEST_RE = re.compile(r"^(\S+)\s+(\S+)\s+s(\S+) (PASS|FAIL|KNOWN-BERKELEY FAIL) rc=")

results = []   # (section, ok, message); ok is None for a skipped check


def check(section, ok, msg):
    results.append((section, bool(ok), msg))
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
    return ok


def skip(section, msg):
    results.append((section, None, msg))
    print(f"  SKIP  {msg}")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


def sec_a():
    print("\nA. original benchmark pipeline (cross_check.py)")
    r = run([PY, str(VER / "cross_check.py")])
    if r.returncode == 2:
        return skip("A", r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "no bench logs")
    n_ok = r.stdout.count("\n  ok ")
    fails = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("FAIL")]
    check("A", r.returncode == 0 and not fails, f"cross_check.py: {n_ok} checks ok, {len(fails)} failed")
    for f in fails:
        check("A", False, f)


def sec_b():
    print("\nB. independent math check (numpy model, no shared code with the C tests)")
    r = run([PY, str(VER / "independent_math_check.py")])
    out = r.stdout.splitlines()
    eq = [l for l in out if "== dense" in l and "every case" in l]
    det = [re.search(r"detected in (\d+)/(\d+)", l) for l in out if "injected fault" in l]
    check("B", r.returncode == 0 and len(eq) == 2, f"sparse math equals dense math in every random case (2:4 and 4:8): {len(eq)}/2 patterns")
    check("B", len(det) == 8 and all(m and m[1] == m[2] for m in det), f"every injected hardware fault detected: {sum(1 for m in det if m and m[1] == m[2])}/8 fault types")
    check("B", out == (VER / "independent_math_check.out").read_text().splitlines(), "output identical to verification/independent_math_check.out")


def sec_c():
    print("\nC. pattern comparison (2:4 vs 4:8 vs paired 4:8, synthetic weights)")
    r = run([PY, str(VER / "pattern_fidelity.py")])
    check("C", r.returncode == 0 and r.stdout == (VER / "pattern_fidelity.out").read_text(), "pattern_fidelity.py reproduces pattern_fidelity.out exactly")
    fid = nmdata.load_fidelity()
    for dist in ("bell curve", "heavy tail"):
        k = [fid[(dist, rl)][0] for rl in ("paired 4:8", "2:4", "4:8", "no pattern")]
        check("C", k == sorted(k), f"{dist}: energy kept ranks paired 4:8 <= 2:4 <= 4:8 <= no pattern ({' <= '.join(f'{v:.1f}%' for v in k)})")


def expected_pairs(h, variant):
    dense = (h["i"] // nmdata.DIM) * (h["k"] // nmdata.DIM) * (h["j"] // nmdata.DIM)
    return dense * h["n"] // h["m"] if variant.startswith(("sparse", "cpu_sparse", "cpu_meta")) else dense


def sec_d(fair):
    print("\nD. fair benchmark (same lean loops on every chip)")
    seeds = {c: tuple(v) for c, v in fair.items()}
    check("D", len(set(seeds.values())) == 1, "every chip ran the same seeds: " + "; ".join(f"{c}={','.join(v)}" for c, v in seeds.items()))
    check("D", "sameprog" in fair, "our chip ran Berkeley's exact program with sparsity off (sameprog log present)")
    has_loop = any(v.endswith("_loop") for logs in fair.values() for f in logs.values() for v in f["perf"])
    for c, logs in fair.items():
        build, pat, gem = EXPECT[c]
        for seed, f in logs.items():
            tag = f"{c} seed {seed}"
            check("D", f["passed"] and not f["failed"], f"{tag}: printed 'passed' and no failure line")
            check("D", f["build"] == build and f["poison_ok"] and set(f["prep"]) == {"prep_cold", "prep_warm"},
                  f"{tag}: log from the current fair_perf.c ({build} build, warm-up, poison reaches the accumulator, prep lines)"
                  + ("" if f["build"] else ": OLD-FORMAT LOG"))
            missing = [v for v in gem if v not in f["perf"]]
            unchecked = [v for v in f["perf"] if not v.startswith("cpu_") and v not in f["ref_ok"]]
            check("D", not missing and not unchecked and sorted(f["ref_ok"]) == sorted(set(f["ref_ok"])),
                  f"{tag}: every gemmini variant matched the cpu reference ({len(f['ref_ok'])} results, 2,048 values each)"
                  + (f"; missing {missing}" if missing else "") + (f"; unchecked {unchecked}" if unchecked else ""))
            if has_loop:
                want = LOOP_EXPECT[build]
                got_loop = sorted(v for v in f["perf"] if v.endswith("_loop"))
                bad_loop = [v for v in want if v not in f["perf"] or f["ref_ok"].count(v) != 1]
                check("D", got_loop == sorted(want) and not bad_loop,
                      f"{tag}: hardware-loop variants of a {build} build ({', '.join(want)}) each ran and matched the cpu reference"
                      + (f"; log has {got_loop or 'none'}" if got_loop != sorted(want) else "")
                      + (f"; missing or unmatched {bad_loop}" if bad_loop else ""))
            h = f["header"]
            got = f"{h['n']}:{h['m']}" if h else None
            check("D", got == pat, f"{tag}: program built for {got} (expected {pat})")
            if h:
                bad = [f"{v} {p['pairs']} (expected {expected_pairs(h, v)})" for v, p in f["perf"].items() if p["pairs"] != expected_pairs(h, v)]
                check("D", not bad, f"{tag}: pair counts equal the count computed from i={h['i']} k={h['k']} j={h['j']} and {got}"
                      + (f": {'; '.join(bad)}" if bad else ""))
    s = nmdata.summary(fair)
    for pat in ("2:4", "4:8"):
        if pat not in s or "busy_reuse" not in s[pat]:
            continue
        n, m = map(int, pat.split(":"))
        lo, hi = nmdata.ratio(s[pat]["busy_reuse"], s["off_" + pat]["busy_reuse"])
        ok = all(abs(r / (n / m) - 1) <= GRID_TOL for r in (lo, hi))
        check("D", ok, f"{pat}: array time with reused weights is {lo:.3f}-{hi:.3f} of the same chip's dense time "
              f"(ideal {n / m:.3f} +-{GRID_TOL:.0%}): {nmdata.fmt_stat(s['off_' + pat]['busy_reuse'])} -> {nmdata.fmt_stat(s[pat]['busy_reuse'])}")
    if "sameprog" in s:
        o, b = s["sameprog"], s["berkeley"]
        for k in ("busy_reuse", "busy_fresh", "reuse", "fresh"):
            if k not in o or k not in b:
                check("D", False, f"our chip, sparsity off, Berkeley's program: counter {k} missing in {'sameprog' if k not in o else 'berkeley'} logs")
                continue
            worst = max(abs(x - y) / y for x in o[k]["values"] for y in b[k]["values"])
            check("D", worst <= SAMEPROG_TOL, f"our chip, sparsity off, Berkeley's program: {k} {nmdata.fmt_stat(o[k])} vs Berkeley "
                  f"{nmdata.fmt_stat(b[k])}, worst seed pair {worst * 100:.2f}% apart (limit {SAMEPROG_TOL:.0%})")
    return s


def sec_e(s):
    print("\nE. the paper summary PDF prints the run's numbers")
    pdf = ROOT / "N-M-Sparsity-Paper-Summary.pdf"
    if not pdf.exists():
        return skip("E", f"{pdf.name} not found (rebuild with tools/report-builders/build_paper.py)")
    txt = run(["pdftotext", "-layout", str(pdf), "-"]).stdout.replace(" ", " ")
    need = {f"{c} {k}": nmdata.fmt_stat(s[c][k]) for c in ("berkeley", "2:4", "4:8") for k in ("busy_reuse", "reuse", "fresh")}
    missing = [f"{k} ({v})" for k, v in need.items() if v not in txt]
    check("E", not missing, f"all {len(need)} key numbers appear in the PDF" + (f"; missing: {', '.join(missing)}" if missing else ""))


def sec_f():
    print("\nF. code patches in the zip rebuild the sparse-nm branches from Berkeley's code")
    zips = sorted(ROOT.glob("Gemmini-NM-Sparsity-*.zip"))
    if not zips:
        return skip("F", "no Gemmini-NM-Sparsity-*.zip in the project folder")
    if not GEM.exists():
        return check("F", False, f"{GEM} not found (needs the local chipyard checkout; set CHIPYARD_DIR)")
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(zips[-1]) as z:
        z.extractall(tmp, [n for n in z.namelist() if "/code-patches/" in n])
        pdir = next(Path(tmp).rglob("code-patches"))
        for name, (repo, base) in REPOS.items():
            patches = sorted((pdir / name).glob("*.patch"))
            clone = Path(tmp) / f"clone-{name}"
            ok = run(["git", "clone", "-q", "--no-checkout", str(repo), str(clone)]).returncode == 0
            ok = ok and run(["git", "-C", str(clone), "checkout", "-q", base]).returncode == 0
            am = run(["git", "-C", str(clone), "-c", "user.name=verify", "-c", "user.email=verify@localhost", "am", "-q", *map(str, patches)])
            tree = run(["git", "-C", str(clone), "rev-parse", "HEAD^{tree}"]).stdout.strip()
            want = run(["git", "-C", str(repo), "rev-parse", "sparse-nm^{tree}"]).stdout.strip()
            check("F", ok and am.returncode == 0 and tree == want, f"{name}: {len(patches)} patches from {zips[-1].name} apply to {base} and match sparse-nm exactly")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def manifest_files():
    return sorted({p for g in MANIFEST_GLOBS for p in ROOT.glob(g) if p.is_file()})


def write_manifest():
    lines = [f"{sha(p)}  {p.relative_to(ROOT)}" for p in manifest_files()]
    MANIFEST.write_text("\n".join(lines) + "\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)} ({len(lines)} files)")


def sec_g(runs):
    print("\nG. integrity of the run folders and the static files")
    for d in runs:
        sums = d / "SHA256SUMS"
        if not sums.exists():
            skip("G", f"{d.name}: no SHA256SUMS in the run folder, so its logs cannot be checked for later edits")
            continue
        rec = dict(reversed(l.split("  ", 1)) for l in sums.read_text().splitlines() if l)
        files = {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and p.name != "SHA256SUMS" and "derived" not in p.relative_to(d).parts}
        bad = [n for n, h in rec.items() if not (d / n).exists() or sha(d / n) != h]
        extra = sorted(files - set(rec))
        check("G", not bad and not extra, f"{d.name}: all {len(rec)} files match SHA256SUMS" if not bad and not extra
              else f"{d.name}: changed or missing {bad[:5]}; not listed {extra[:5]}")
    if not MANIFEST.exists():
        return skip("G", "no verification/MANIFEST.sha256 for the static files (bin/, logs/, *.c, *.out); --write-manifest records one")
    rec = dict(reversed(l.split("  ", 1)) for l in MANIFEST.read_text().splitlines() if l)
    changed = [n for n, h in rec.items() if not (ROOT / n).exists() or sha(ROOT / n) != h]
    new = [str(p.relative_to(ROOT)) for p in manifest_files() if str(p.relative_to(ROOT)) not in rec]
    check("G", not changed, f"all {len(rec)} recorded static files unchanged" if not changed else
          f"{len(changed)} of {len(rec)} recorded files changed or missing: {', '.join(changed[:5])}")
    check("G", not new, "no static files outside the manifest" if not new else f"{len(new)} static file(s) not in the manifest, e.g. {new[0]}")


def sec_h(fair):
    print("\nH. README results table")
    m = re.search(r"<!-- results:begin -->\n(.*?)<!-- results:end -->", (ROOT / "README.md").read_text(), re.S)
    if not m:
        return skip("H", "README.md has no <!-- results:begin --> ... <!-- results:end --> block, so it states no results to check")
    check("H", m[1].strip() == paper_data.readme_table(paper_data.build_data(fair)).strip(),
          "README results table equals paper_data.readme_table() of this run")


def chip_table():
    """chip -> (n, m, config): the nm_table rows of run-flow.sh, plus stock (n, m None)."""
    m = re.search(r'^nm_table="\n(.*?)^"', (ROOT / "run-flow.sh").read_text(), re.M | re.S)
    if not m:
        sys.exit("verify_all.py: no nm_table in run-flow.sh, so the N:M chips are unknown")
    out = {"stock": (None, None, STOCK_CFG)}
    for l in m[1].splitlines():
        if l.split():
            name, n, mm, cfg = l.split()
            out[name] = (int(n), int(mm), cfg)
    return out


def run_info_sims(d):
    """chip -> (config, sha256 or None) from <d>/run.info sim.<chip>= lines."""
    out = {}
    p = d / "run.info"
    for l in (p.read_text().splitlines() if p.exists() else []):
        m = re.match(r"sim\.(\w+)=(\S+)(.*)$", l)
        if m:
            h = re.search(r"\bsha256=([0-9a-f]{64})\b", m[3])
            out[m[1]] = (m[2], h[1] if h else None)
    return out


def jobs_rows(d):
    """(chip, program, seed) -> exit status from <d>/jobs.tsv (program column 'binary' or 'program')."""
    out = {}
    with (d / "jobs.tsv").open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            prog = (r.get("binary") or r.get("program") or "").replace("-baremetal", "")
            out[(r["chip"], prog, r["seed"])] = r.get("exit", "?")
    return out


def sums_of(d):
    p = d / "SHA256SUMS"
    return dict(reversed(l.split("  ", 1)) for l in p.read_text().splitlines() if l) if p.exists() else None


def run_sec_i(folders, extra):
    print("\nI. integrity: SHA256SUMS of the run folders")
    for d in folders:
        rec = sums_of(d)
        if rec is None:
            check("I", False, f"{d.name}: no SHA256SUMS, so its logs cannot be checked for later edits")
            continue
        files = {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and p.name != "SHA256SUMS" and "derived" not in p.relative_to(d).parts}
        bad = [n for n, h in rec.items() if not (d / n).exists() or sha(d / n) != h]
        extra_f = sorted(files - set(rec))
        allowed = [f for f in extra_f if f in UNLISTED_OK]
        extra_f = [f for f in extra_f if f not in UNLISTED_OK]
        check("I", not bad and not extra_f, (f"{d.name}: all {len(rec)} files match SHA256SUMS" if not bad and not extra_f
              else f"{d.name}: changed or missing {bad[:5]}; not listed {extra_f[:5]}")
              + (f" (not listed, written after it: {', '.join(allowed)})" if allowed else ""))
    for p in extra:
        rec = sums_of(p.parent)
        h = rec.get(p.name) if rec else None
        check("I", h is not None and sha(p) == h, f"extra log {p.parent.name}/{p.name}: " + (
              "no SHA256SUMS in its folder" if rec is None else "not in its folder's SHA256SUMS" if h is None
              else "matches its folder's SHA256SUMS" if sha(p) == h else "CHANGED since its folder's SHA256SUMS"))


def run_sec_s(logs, table):
    print("\nS. simulators: run.info sim lines, the chip's run-flow.sh config, the config named in every log")
    by_chip = {}
    for L in logs:
        by_chip.setdefault(L["chip"], []).append(L)
    for chip, ls in by_chip.items():
        want = table.get(chip)
        if not want:
            check("S", False, f"{chip}: {len(ls)} log(s) of a chip that is neither stock nor in run-flow.sh nm_table")
            continue
        builds = {}
        for L in ls:
            cfg, h = run_info_sims(L["dir"]).get(chip, (None, None))
            builds.setdefault((L["dir"].name, cfg, h), []).append(L)
        for (dn, cfg, h), group in builds.items():
            check("S", cfg == want[2] and h is not None, f"{chip}: {dn}/run.info sim.{chip}=" + (
                  f"{cfg} sha256={h}" if cfg else "MISSING") + ("" if cfg == want[2] else f" (run-flow.sh config {want[2]})")
                  + ("" if cfg is None or h else " (no 64-hex sha256)"))
            unnamed = [L["name"] for L in group if not re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(want[2]), L["text"])]
            check("S", not unnamed, f"{chip}: all {len(group)} log(s) from {dn} name {want[2]}"
                  + (f"; not in {len(unnamed)}: {', '.join(unnamed[:5])}" if unnamed else ""))
        shas = {h for (_, _, h) in builds}
        check("S", len(shas) == 1, f"{chip}: one simulator build for all {len(ls)} log(s)"
              + ("" if len(shas) == 1 else f": {len(shas)} builds {sorted(map(str, shas))}"))


def run_sec_j(folders, logs, extra):
    print("\nJ. jobs: jobs.tsv vs logs, exit status, parse_fixa.py")
    for d in folders:
        if not (d / "jobs.tsv").exists():
            check("J", False, f"{d.name}: no jobs.tsv")
            continue
        jobs = jobs_rows(d)
        mine = {(L["chip"], L["prog"], L["seed"]): L for L in logs if L["dir"] == d and not L["extra"]}
        no_log = sorted(f"{c}.{p}.seed{s}.log" for (c, p, s) in jobs if (c, p, s) not in mine)
        no_job = sorted(L["name"] for k, L in mine.items() if k not in jobs)
        check("J", not no_log and not no_job, f"{d.name}: {len(jobs)} jobs.tsv rows and {len(mine)} logs match one to one"
              + (f"; rows with no log: {', '.join(no_log[:5])}" if no_log else "") + (f"; logs with no row: {', '.join(no_job[:5])}" if no_job else ""))
        r = run([PY, str(ROOT / "experiments/streaming/tools/parse_fixa.py"), str(d)])
        judged = {}
        for l in r.stdout.splitlines():
            m = PF_TEST_RE.match(l)
            if m:
                judged[(m[1], m[2], m[3])] = m[4]
        n0 = sum(1 for k in jobs if jobs[k] == "0")
        neg, known, bad = [], [], []
        for (c, p, s), ex in sorted(jobs.items()):
            if ex == "0":
                continue
            j = judged.get((c, p, s))
            if j == "PASS" and re.search(r"neg\d+", p):
                neg.append(p)
            elif j == "KNOWN-BERKELEY FAIL":
                known.append(f"{c} {p}")
            else:
                bad.append(f"{c}.{p}.seed{s}.log exit {ex} (parse_fixa: {j or 'not judged'})")
        check("J", not bad, f"{d.name}: {n0} jobs exited 0, {len(neg)} NEG jobs exited non-zero on their expected assert text"
              + (f", {len(known)} known Berkeley failure(s) ({', '.join(known)}; berkeley-issues.md, not counted)" if known else ""))
        for b in bad:
            check("J", False, f"{d.name}: {b}")
        fails = [l for l in r.stdout.splitlines() + r.stderr.splitlines() if re.search(r"\bFAIL\b|MISSING LOG|^parse_fixa:", l)
                 and "KNOWN-BERKELEY" not in l]
        check("J", r.returncode == 0, f"{d.name}: parse_fixa.py rc {r.returncode}" + (f" ({fails[-1].strip()})" if r.returncode and fails else ""))
    for L in extra:
        d = L["dir"]
        ex = jobs_rows(d).get((L["chip"], L["prog"], L["seed"])) if (d / "jobs.tsv").exists() else None
        check("J", ex == "0", f"extra log {d.name}/{L['name']}: exit {ex if ex is not None else 'unknown (no jobs.tsv row)'} in its folder's jobs.tsv")


def run_sec_v(logs, table):
    print("\nV. streaming bench logs: every variant verified")
    benches = [L for L in logs if BENCH_NAME_RE.match(L["prog"]) or "sbench:" in L["text"]]
    if not benches:
        return skip("V", "no streaming bench logs (<layer>_<pat>_<build> programs) in the run")
    rows = []
    for L in benches:
        t, tag = L["text"], f"{L['dir'].name}/{L['name']}"
        h = SBENCH_HDR_RE.search(t)
        if not h:
            check("V", False, f"{tag}: no sbench header (did not start or not a bench log)")
            continue
        tots = {m[1]: int(m[2]) for m in SBENCH_TOT_RE.finditer(t)}
        chks = {m[1]: m for m in SBENCH_CHK_RE.finditer(t)}
        k = bin(int(h[5])).count("1")
        sp = re.search(r"^sbench passed \((\d+) of (\d+) runs verified\)", t, re.M)
        n, m = table.get(L["chip"], (None, None, None))[:2]
        pat = f"{h[2]}:{h[3]}"
        refp = L["dir"] / "ref" / f"{h[1]}_{h[2]}{h[3]}.json"
        ref = json.loads(refp.read_text())["hash"] if refp.exists() else None
        bad = [v for v in tots if not (v in chks and chks[v][6] == "verified" and chks[v][2] == chks[v][3]
                                        and chks[v][4] == chks[v][5] and (ref is None or chks[v][2] == ref))]
        loop_ok = "sparse_loop" not in tots or len(re.findall(r"^sparse_loop tiles: ", t, re.M)) == 1
        pat_ok = n is None or pat == f"{n}:{m}"
        ok = len(tots) == k and not bad and sp and sp[1] == sp[2] == str(k) and loop_ok and pat_ok
        check("V", ok, f"{tag}: {len(tots) - len(bad)}/{k} variants verified ({', '.join(tots)}), pattern {pat}"
              + (", hash == ref/" + refp.name if ref else ", no ref/ (hash == the binary's expected value)")
              + (f"; NOT verified {bad}" if bad else "") + ("" if sp and sp[1] == sp[2] == str(k) else "; no 'sbench passed (k of k)'")
              + ("" if loop_ok else "; sparse_loop tiles line count != 1") + ("" if pat_ok else f"; chip pattern {n}:{m}"))
        if ok:
            rows += [(h[1], L["chip"], v, c, L["name"]) for v, c in tots.items()]
    # ratios recomputed from the total lines (printed, not checked): mean cycles vs Berkeley's best on the stock chip
    base = {}
    for layer, chip, v, c, f in rows:
        if chip == "stock" and v == "berkeley":
            base.setdefault(layer, []).append(c)
    agg = {}
    for layer, chip, v, c, f in rows:
        agg.setdefault((layer, chip, v), []).append((c, f))
    for (layer, chip, v), cs in sorted(agg.items()):
        mean = sum(c for c, _ in cs) / len(cs)
        b = base.get(layer)
        print(f"  INFO  {layer} {chip} {v}: total {nmdata.fmt_stat(nmdata.stat(c for c, _ in cs))}"
              + (f", stock berkeley {nmdata.fmt_stat(nmdata.stat(b))} -> {sum(b) / len(b) / mean:.3f}x" if b else ", no stock berkeley log")
              + f" ({', '.join(f for _, f in cs)})")


def run_sec_r(logs, table):
    print("\nR. fair logs (fair_perf_*, berkeley_dense_perf) and their ratios")
    fair = [L for L in logs if L["prog"].startswith("fair_perf") or L["prog"] == "berkeley_dense_perf"]
    if not fair:
        return skip("R", "no fair_perf / berkeley_dense_perf logs in the run")
    groups = {}
    for L in fair:
        f = nmdata.parse_log(L["path"])
        L["fair"] = f
        groups.setdefault((L["chip"], L["prog"]), {})[L["seed"]] = f
        tag = f"{L['dir'].name}/{L['name']}"
        n, m, _ = table.get(L["chip"], (None, None, None))
        unchecked = [v for v in f["perf"] if not v.startswith("cpu_") and f["ref_ok"].count(v) != 1]
        check("R", f["passed"] and not f["failed"] and f["perf"] and not unchecked,
              f"{tag}: passed, no failure line, every gemmini variant matched the cpu reference once ({len(f['ref_ok'])})"
              + (f"; unmatched {unchecked}" if unchecked else ""))
        if L["prog"] == "berkeley_dense_perf":
            bh = BDP_HDR_RE.search(L["text"])
            h = dict(zip(("n", "m", "i", "k", "j"), map(int, bh.groups()))) if bh else None
            build = None
        else:
            h, build = f["header"], ("dense-only" if L["prog"] == "fair_perf_dense_only" else "full")
            # an N:M chip's full program is fair_perf_<n><m>
            sfx_ok = build == "dense-only" or (n is not None and L["prog"] == f"fair_perf_{n}{m}")
            pat_ok = h is not None and (build == "dense-only" or (h["n"], h["m"]) == (n, m))
            check("R", f["build"] == build and f["poison_ok"] and set(f["prep"]) == {"prep_cold", "prep_warm"} and sfx_ok and pat_ok,
                  f"{tag}: {build} build of the current fair_perf.c (warm-up, poison, prep lines), program built for "
                  f"{h['n']}:{h['m']}" if h else f"{tag}: no fair_perf header")
        if h:
            bad = [f"{v} {p['pairs']} (expected {expected_pairs(h, v)})" for v, p in f["perf"].items() if p["pairs"] != expected_pairs(h, v)]
            check("R", not bad, f"{tag}: pair counts equal the count computed from i={h['i']} k={h['k']} j={h['j']} and {h['n']}:{h['m']}"
                  + (f": {'; '.join(bad)}" if bad else ""))
    progs = {}
    for (chip, prog), seeds in groups.items():
        progs.setdefault("fair_perf_dense_only" if prog == "fair_perf_dense_only" else "berkeley_dense_perf"
                         if prog == "berkeley_dense_perf" else "fair_perf_<nm>", {})[chip] = tuple(seeds)
    for prog, chips in sorted(progs.items()):
        check("R", len(set(chips.values())) == 1, f"{prog}: every chip ran the same seeds: "
              + "; ".join(f"{c}={','.join(s)}" for c, s in sorted(chips.items())))
    for (chip, prog), seeds in sorted(groups.items()):
        n, m, _ = table.get(chip, (None, None, None))
        if n is None or prog != f"fair_perf_{n}{m}":
            continue
        sp, dn = nmdata.metric(seeds, "sparse_reuse", "ex_active"), nmdata.metric(seeds, "dense_reuse", "ex_active")
        if not sp or not dn:
            check("R", False, f"{chip}: sparse_reuse or dense_reuse ex_active missing in {prog} logs")
            continue
        lo, hi = nmdata.ratio(sp, dn)
        ok = all(abs(r / (n / m) - 1) <= GRID_TOL for r in (lo, hi))
        check("R", ok, f"{chip} {n}:{m}: array time with reused weights is {lo:.3f}-{hi:.3f} of the same chip's dense time "
              f"(ideal {n / m:.3f} +-{GRID_TOL:.0%}): {nmdata.fmt_stat(dn)} -> {nmdata.fmt_stat(sp)} ({prog}, seeds {','.join(seeds)})")
    stock = groups.get(("stock", "fair_perf_dense_only"))
    for (chip, prog), seeds in sorted(groups.items()):
        if chip == "stock" or prog != "fair_perf_dense_only":
            continue
        if not stock:
            check("R", False, f"{chip}: sparsity-off log (fair_perf_dense_only) but no stock fair_perf_dense_only log to compare (pass it with --extra-log)")
            continue
        o, b = nmdata._row(seeds, "dense"), nmdata._row(stock, "dense")
        for k in ("busy_reuse", "busy_fresh", "reuse", "fresh"):
            if k not in o or k not in b:
                check("R", False, f"{chip} sparsity off vs stock, same program: counter {k} missing")
                continue
            worst = max(abs(x - y) / y for x in o[k]["values"] for y in b[k]["values"])
            check("R", worst <= SAMEPROG_TOL, f"{chip} sparsity off vs stock, same program (fair_perf_dense_only): {k} "
                  f"{nmdata.fmt_stat(o[k])} vs {nmdata.fmt_stat(b[k])}, worst seed pair {worst * 100:.2f}% apart (limit {SAMEPROG_TOL:.0%})")
    nm_chips = {c for (c, _) in groups if c != "stock"}
    for chip in sorted(nm_chips):
        if (chip, "fair_perf_dense_only") not in groups:
            skip("R", f"{chip}: no fair_perf_dense_only log, so sparsity off vs stock is not checked for this chip")


def main_run(a):
    print(f"verify_all.py --mode run  {datetime.now():%Y-%m-%d %H:%M}  project: {ROOT}")
    table = chip_table()
    folders = [Path(r).resolve() for r in a.runs]
    missing = [str(d) for d in folders if not d.is_dir()]
    if not folders or missing:
        sys.exit(f"verify_all.py --mode run: give existing server run folder(s); missing: {', '.join(missing) or 'none given'}")
    logs, extra = [], []
    for d, paths, is_extra in [(d, sorted(d.glob("*.log")), False) for d in folders] + [
            (Path(p).resolve().parent, [Path(p).resolve()], True) for p in a.extra_log]:
        for p in paths:
            m = RUN_LOG_RE.match(p.name)
            if not p.is_file() or not m:
                check("J", False, f"{p}: " + ("missing" if not p.is_file() else "not a <chip>.<program>.seed<S>.log name"))
                continue
            L = {"dir": d, "name": p.name, "path": p, "chip": m[1], "prog": m[2], "seed": m[3], "extra": is_extra,
                 "text": p.read_text(errors="replace")}
            logs.append(L)
            if is_extra:
                extra.append(L)
    if not logs:
        print(f"\nNO JOB LOGS in {', '.join(map(str, folders))}")
        sys.exit(2)
    print(f"{len(logs)} logs ({len(extra)} extra) of chips {', '.join(sorted({L['chip'] for L in logs}))}; "
          f"run-flow.sh chips: {', '.join(table)}")
    run_sec_i(folders, [L["path"] for L in extra])
    run_sec_s(logs, table)
    run_sec_j(folders, logs, extra)
    run_sec_v(logs, table)
    run_sec_r(logs, table)
    n_fail = sum(1 for _, ok, _ in results if ok is False)
    n_skip = sum(1 for _, ok, _ in results if ok is None)
    print(f"\n{'ALL CHECKS PASSED' if n_fail == 0 else f'{n_fail} CHECK(S) FAILED'}  ({len(results) - n_skip} checks, {n_skip} skipped)")
    sys.exit(1 if n_fail else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("runs", nargs="*", help="fair run folder(s); default: the newest in verification/runs")
    ap.add_argument("--skip-patches", action="store_true", help="skip section F (git clone + am)")
    ap.add_argument("--write-manifest", action="store_true", help="record SHA-256 fingerprints of the static files first")
    ap.add_argument("--mode", choices=("paper", "run"), default="paper",
                    help="paper (default): sections A-H against the run of record; run: integrity of any server run folder")
    ap.add_argument("--extra-log", action="append", default=[], help="--mode run: a log reused from another recorded run")
    a = ap.parse_args()
    if a.mode == "run":
        return main_run(a)
    if a.extra_log:
        ap.error("--extra-log needs --mode run")
    print(f"verify_all.py  {datetime.now():%Y-%m-%d %H:%M}  project: {ROOT}")
    if a.write_manifest:
        write_manifest()
    no_results, runs, fair = None, [], None
    try:
        runs = nmdata.find_runs(a.runs or None)
        fair = nmdata.load_fair(runs)
    except nmdata.NoResults as e:
        no_results = str(e)
    sec_a(); sec_b(); sec_c()
    if fair:
        s = sec_d(fair)
        sec_e(s)
    else:
        print(f"\nD. fair benchmark\n  NONE  {no_results}")
    if not a.skip_patches:
        sec_f()
    sec_g(runs)
    if fair:
        sec_h(fair)

    n_fail = sum(1 for _, ok, _ in results if ok is False)
    n_skip = sum(1 for _, ok, _ in results if ok is None)
    verdict = ("NO FAIR RESULTS" if no_results else "ALL CHECKS PASSED") if n_fail == 0 else f"{n_fail} CHECK(S) FAILED"
    tail = f"{len(results) - n_skip} checks, {n_skip} skipped"
    print(f"\n{verdict}  ({tail})" + (f"\n{no_results}" if no_results else ""))
    if runs and fair:
        names = {"A": "Original benchmark pipeline", "B": "Independent math check", "C": "Pattern comparison", "D": "Fair benchmark",
                 "E": "Paper summary PDF", "F": "Code patches in the zip", "G": "File integrity", "H": "README results table"}
        md = ["# Verification report", "", f"Run {datetime.now():%Y-%m-%d %H:%M} with `verification/verify_all.py` on "
              f"{', '.join(f'`{r.name}`' for r in runs)}. **{verdict}** ({tail}).", ""]
        for sec, name in names.items():
            rows = [(ok, msg) for s_, ok, msg in results if s_ == sec]
            if rows:
                md += [f"## {sec}. {name}", ""] + [f"- {'SKIP' if ok is None else 'PASS' if ok else '**FAIL**'}: {msg}" for ok, msg in rows] + [""]
        out = runs[0] / "derived"
        out.mkdir(exist_ok=True)
        (out / "verify_all_report.md").write_text("\n".join(md))
        print(f"report: {out / 'verify_all_report.md'}")
    sys.exit(1 if n_fail else 2 if no_results else 0)


if __name__ == "__main__":
    main()
