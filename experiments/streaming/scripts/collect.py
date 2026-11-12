#!/usr/bin/env python3
"""collect.py <run_dir> [...]: parse the Verilator logs of streaming-benchmark run folders into
<first run_dir>/results.csv and <first run_dir>/summary.md.

Per log (<chip>.<program>.seed<S>.log): the sbench header, one "total" line per variant (cycles + 8 Gemmini
counters), one "check" line per variant, "sbench passed". A row is verified=yes only if ALL of:
  - the binary printed "-> verified" for that variant (its own hash + 8 sampled rows compare)
  - the hash it printed equals the host reference hash in <run_dir>/ref/<layer>_<pat>.json (copied from build/data at run time) (independent of the
    expected value compiled into the binary), and so does the expected value it printed
  - sampled rows 8/8, the log ends with "sbench passed", and the seed in the make command line
    (+verilator+seed+S) equals the seed in the file name
Rows from logs that did not finish (timeout, crash) are reported with verified=no and empty cycle columns.
Every number in the outputs comes from the logs; nothing is typed in.
"""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CHIP_CFG = {"stock": "GemminiRocketConfig", "nm24": "GemminiNMRocketConfig", "nm48": "GemminiNM48RocketConfig"}
CTRS = ["ex_active", "rdma_active", "wdma_active", "load_active", "store_active", "rs_full", "loop_matmul_active",
        "rdma_bytes"]
COLS = ["layer", "M", "K", "N", "chip", "program", "pattern", "build", "variant", "seed", "total_cycles",
        "cpu_issue_done"] + CTRS + ["TI", "TJ", "hash", "hash_ref", "sampled_rows_ok", "verified", "sim_wall_s",
                                   "sim_end_cycle", "host", "sim_sha256", "log"]
LOGNAME = re.compile(r"^(stock|nm24|nm48)\.(.+)\.seed(\d+)\.log$")
HDR = re.compile(r"^sbench: layer=(\S+) M=(\d+) K=(\d+) N=(\d+) pattern=(\d+):(\d+) build=(\S+) run_mask=(\d+) "
                 r"TI=(\d+) TJ=(\d+)")
TOT = re.compile(r"^(berkeley|dense_stream|sparse_stream)\s+total\s+(\d+)\s+cpu_issue_done\s+(\d+) \|(.*)$")
CHK = re.compile(r"^(berkeley|dense_stream|sparse_stream) check: hash (0x[0-9a-f]{16}) expected (0x[0-9a-f]{16}), "
                 r"sampled rows (\d+)/(\d+) -> (verified|MISMATCH)$")
MASK_VARIANTS = {1: "berkeley", 2: "dense_stream", 4: "sparse_stream"}


def hosts(run):
    """(chip, program, seed) -> (host, simulator sha256). Laptop jobs: run.info; jobs run elsewhere are listed in
    remote/jobs.tsv with that host's remote/host.info (copied back with their logs)."""
    info = dict(l.split("=", 1) for l in (run / "run.info").read_text().splitlines() if "=" in l)
    local_host = info.get("host", "laptop").split()[0]
    local = {c: re.search(r"sha256=(\w+)", info.get(f"sim.{c}", "")) for c in CHIP_CFG}
    local = {c: (m.group(1) if m else "") for c, m in local.items()}
    out = {"_default": (local_host, local)}
    rj, rh = run / "remote" / "jobs.tsv", run / "remote" / "host.info"
    if rj.exists() and rh.exists():
        lines = rh.read_text().splitlines()
        rhost = lines[0].strip()
        rsha = {}
        for l in lines:
            m = re.match(r"sim\.(\w+) sha256=(\w+)", l)
            if m:
                rsha[m.group(1)] = m.group(2)
        for r in csv.DictReader(rj.open(), delimiter="\t"):
            out[(r["chip"], r["program"], r["seed"])] = (rhost, rsha.get(CHIP_CFG[r["chip"]], ""))
    return out


def wall_times(run):
    out = {}
    for f in (run / "jobs.tsv", run / "remote" / "jobs.tsv"):
        if f.exists():
            for r in csv.DictReader(f.open(), delimiter="\t"):
                out[(r["chip"], r["program"], r["seed"])] = int(r["wall_s"])
    return out


def parse(log, walls):
    m = LOGNAME.match(log.name)
    if not m:
        return []
    chip, prog, seed = m.group(1), m.group(2), m.group(3)
    text = log.read_text(errors="replace")
    lines = text.splitlines()
    hdr = next((HDR.match(l) for l in lines if HDR.match(l)), None)
    seed_ok = re.search(r"\+verilator\+seed\+%s(\s|$)" % seed, text) is not None
    cfg_ok = CHIP_CFG[chip] in text.split("\n", 12)[-1] or CHIP_CFG[chip] in text
    passed = any(l.startswith("sbench passed") for l in lines)
    end = next((int(l.split()[-1]) for l in lines if l.startswith("sbench end cycle")), None)
    layer = prog.rsplit("_", 2)[0]
    pat = prog.rsplit("_", 2)[1]
    ref = json.loads((log.parent / "ref" / f"{layer}_{pat}.json").read_text())  # copied at run time
    base = {"layer": layer, "M": ref["M"], "K": ref["K"], "N": ref["N"], "chip": chip, "program": prog,
            "pattern": f'{ref["n"]}:{ref["m"]}', "seed": seed, "hash_ref": ref["hash"],
            "sim_wall_s": walls.get((chip, prog, seed), ""), "sim_end_cycle": end if end is not None else "",
            "log": log.name}
    if hdr:
        base.update(build=hdr.group(7), TI=hdr.group(9), TJ=hdr.group(10))
        expect = [v for b, v in MASK_VARIANTS.items() if int(hdr.group(8)) & b]
    else:
        expect = []
    tots = {t.group(1): t for t in map(TOT.match, lines) if t}
    chks = {c.group(1): c for c in map(CHK.match, lines) if c}
    rows = []
    for v in expect or ["(no output)"]:
        r = dict(base, variant=v)
        t, c = tots.get(v), chks.get(v)
        if t:
            r["total_cycles"], r["cpu_issue_done"] = int(t.group(2)), int(t.group(3))
            kv = dict(x.split("=") for x in t.group(4).split())
            for k in CTRS:
                r[k] = int(kv[k])
        if c:
            r["hash"], r["sampled_rows_ok"] = c.group(2), f"{c.group(4)}/{c.group(5)}"
        ok = bool(t and c and c.group(6) == "verified" and c.group(2) == ref["hash"] and c.group(3) == ref["hash"]
                  and c.group(4) == c.group(5) == str(len(ref["sample_rows"])) and passed and seed_ok and cfg_ok)
        r["verified"] = "yes" if ok else "no"
        rows.append(r)
    return rows


def fmt_range(vals):
    lo, hi = min(vals), max(vals)
    return f"{lo:,}" if lo == hi else f"{lo:,}-{hi:,}"


def main():
    runs = [Path(a).resolve() for a in sys.argv[1:]]
    if not runs:
        sys.exit("usage: collect.py <run_dir> [...]")
    rows = []
    for run in runs:
        walls = wall_times(run)
        hs = hosts(run)
        for log in sorted(run.glob("*.log")):
            got = parse(log, walls)
            for r in got:
                key = (r["chip"], r["program"], r["seed"])
                if key in hs:
                    r["host"], r["sim_sha256"] = hs[key]
                else:
                    r["host"], r["sim_sha256"] = hs["_default"][0], hs["_default"][1][r["chip"]]
            rows += got
    out = runs[0]
    with (out / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLS})
    # summary: per layer, chip, variant -> cycles over seeds, ratio vs berkeley on the stock chip
    agg = defaultdict(list)
    bad = [r for r in rows if r["verified"] != "yes"]
    for r in rows:
        if r["verified"] == "yes":
            agg[(r["layer"], r["chip"], r["variant"])].append(r)
    order = ["edge", "small", "bert_qkv", "bert_ffn1", "bert_ffn2", "rn50_conv"]
    md = ["# Streaming benchmark results (generated by scripts/collect.py from the logs)", "",
          f"Run folder(s): {', '.join(str(r.relative_to(HERE)) for r in runs)}", "",
          f"Rows: {len(rows)}, verified: {len(rows) - len(bad)}, NOT verified: {len(bad)}", ""]
    if bad:
        md += ["## NOT verified", ""] + [f"- {r['log']} {r['variant']}" for r in bad] + [""]
    md += ["## Total cycles (first mvin .. last mvout + fence), min-max over seeds", "",
           "| layer | chip | variant | seeds | total cycles | vs Berkeley best (stock) | cpu_issue_done | ex_active | "
           "rdma_active | wdma_active | rs_full | rdma_bytes |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    layers = sorted({k[0] for k in agg}, key=lambda x: order.index(x) if x in order else 99)
    for L in layers:
        base = agg.get((L, "stock", "berkeley"))
        bmean = sum(r["total_cycles"] for r in base) / len(base) if base else None
        for chip in ("stock", "nm24", "nm48"):
            for v in ("berkeley", "dense_stream", "sparse_stream"):
                rs = agg.get((L, chip, v))
                if not rs:
                    continue
                tot = [r["total_cycles"] for r in rs]
                mean = sum(tot) / len(tot)
                ratio = f"{bmean / mean:.3f}x" if bmean else ""
                md.append(f"| {L} | {chip} | {v} | {','.join(sorted(r['seed'] for r in rs))} | {fmt_range(tot)} | "
                          f"{ratio} | {fmt_range([r['cpu_issue_done'] for r in rs])} | "
                          f"{fmt_range([r['ex_active'] for r in rs])} | {fmt_range([r['rdma_active'] for r in rs])} | "
                          f"{fmt_range([r['wdma_active'] for r in rs])} | {fmt_range([r['rs_full'] for r in rs])} | "
                          f"{fmt_range([r['rdma_bytes'] for r in rs])} |")
    md += ["", "vs Berkeley best = mean Berkeley-best cycles on the stock chip / mean cycles of this row (>1 = faster).",
           ""]
    sp = [r for r in rows if r.get("sim_end_cycle") and r.get("sim_wall_s")]
    seen = set()
    md += ["## Simulation speed", "", "| log | simulated cycles (read_cycles at exit) | wall s | cycles/s |",
           "|---|---|---|---|"]
    for r in sp:
        if r["log"] in seen:
            continue
        seen.add(r["log"])
        md.append(f"| {r['log']} | {r['sim_end_cycle']:,} | {r['sim_wall_s']} | "
                  f"{r['sim_end_cycle'] / max(1, r['sim_wall_s']):,.0f} |")
    (out / "summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    print(f"\nwrote {out / 'results.csv'} ({len(rows)} rows) and {out / 'summary.md'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
