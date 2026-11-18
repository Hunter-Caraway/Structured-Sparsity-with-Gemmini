#!/usr/bin/env python3
# Runs analysis/area.py UNCHANGED except for the abc step, one chip at a time, into this folder.
# Why: with yosys 0.69 (conda-forge), the default abc script's `&fraig -x` step does not finish on Berkeley's
# LoopConvLdWeight module (a chain of 16..64-bit multipliers): >85 min on one core in synth's internal abc,
# and >300 s standalone, while the same script without `&get -n; &fraig -x; &put` maps it in 19 s.
# Change (identical for all three chips):
#   synth -top Gemmini            -> synth -top Gemmini -noabc
#   abc -liberty LIB              -> abc -liberty LIB -script +<ABC_SCRIPT>
#   ABC_SCRIPT = yosys's default liberty script minus the `&get -n; &fraig -x; &put` step.
# Everything else (inputs, black boxes, sram identity check, dfflibmap, stat, tables, chart) is area.py's own code.
# Waits for >= 3 GiB MemAvailable before each chip (another agent runs Verilator on this machine).
# run: ~/chipyard/.conda-env/bin/python experiments/area-nofraig/run_area_nofraig.py
import json, sys, time, concurrent.futures as cf
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "analysis"))
import area

ABC_SCRIPT = "strash;scorr;dc2;dretime;strash;&get,-n;&dch,-f;&nf;&put"
MIN_AVAIL_GIB = 3.0
area.OUT = HERE
area.ThreadPoolExecutor = lambda n: cf.ThreadPoolExecutor(1)

def avail_gib():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable:"): return int(l.split()[1]) / 2**20

_prepare = area.prepare
def prepare(chip, cfg):
    work, ys, h, mems = _prepare(chip, cfg)
    lines, n_synth, n_abc = [], 0, 0
    for l in ys.read_text().split("\n"):
        if l == f"synth -top {area.TOP}": l += " -noabc"; n_synth += 1
        elif l == f"abc -liberty {area.LIB}": l += f" -script +{ABC_SCRIPT}"; n_abc += 1
        lines.append(l)
    assert n_synth == 1 and n_abc == 1, "area.py's synth.ys changed; update this wrapper"
    ys.write_text("\n".join(lines))
    return work, ys, h, mems
area.prepare = prepare

_synth = area.synth
def synth(chip, cfg):
    while avail_gib() < MIN_AVAIL_GIB:
        print(f"{chip}: waiting, MemAvailable {avail_gib():.1f} GiB", flush=True); time.sleep(60)
    print(f"{chip}: start {time.strftime('%H:%M:%S')}, MemAvailable {avail_gib():.1f} GiB", flush=True)
    return _synth(chip, cfg)
area.synth = synth

area.main()
note = (f"Method change vs analysis/area.py: `synth -noabc`, then `abc -liberty <lib> -script +{ABC_SCRIPT}` "
        "(yosys's default liberty abc script without `&get -n; &fraig -x; &put`, which does not finish on "
        "LoopConvLdWeight). Same for all three chips. Produced by experiments/area-nofraig/run_area_nofraig.py.")
meta = json.loads((HERE / "area-meta.json").read_text())
meta["method_change"] = {"synth": f"synth -top {area.TOP} -noabc", "abc_script": ABC_SCRIPT, "note": note,
                         "wrapper": "experiments/area-nofraig/run_area_nofraig.py"}
(HERE / "area-meta.json").write_text(json.dumps(meta, indent=2) + "\n")
md = (HERE / "area.md").read_text().split("\n")
md.insert(3, "**" + note + "**\n")
(HERE / "area.md").write_text("\n".join(md))
print("method note added to area.md and area-meta.json")
