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
"""
import argparse, hashlib, os, re, subprocess, sys, tempfile, zipfile
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("runs", nargs="*", help="fair run folder(s); default: the newest in verification/runs")
    ap.add_argument("--skip-patches", action="store_true", help="skip section F (git clone + am)")
    ap.add_argument("--write-manifest", action="store_true", help="record SHA-256 fingerprints of the static files first")
    a = ap.parse_args()
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
