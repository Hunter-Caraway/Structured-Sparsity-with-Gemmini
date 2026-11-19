#!/usr/bin/env python3
"""Summarize and compare Yosys area runs (stdlib only).

Summarize one run (server side, needs the Liberty file):
    parse_area.py --lib LIB --mems-conf CONF RUN_DIR  > RUN_DIR/area.txt
Compare runs (laptop side, reads only each run's area.txt):
    parse_area.py --compare BASE_RUN RUN [RUN ...]

The summary recomputes every area from cell counts in stat.json and the
Liberty cell areas, and fails if that disagrees with Yosys's own total.
Every line of area.txt names its source file so numbers trace to a log.
Exits non-zero on a missing file, unknown cell or failed check.
"""

import argparse
import json
import os
import re
import sys

CELL_RE = re.compile(r'^\s*cell\s*\(\s*"?([\w$]+)"?\s*\)', re.M)
AREA_RE = re.compile(r'^\s*area\s*:\s*([0-9.eE+-]+)', re.M)
SEQ_RE = re.compile(r'^\s*(ff|latch|ff_bank|latch_bank)\s*\(', re.M)
REL_TOL = 1e-6
# Modules always listed in the per-module table (matched as name prefixes).
KEY_MODULES = ('ExecuteController', 'MeshWithDelays', 'Mesh', 'Tile', 'PE',
               'LoopMatmul', 'Scratchpad', 'LoadController', 'StoreController',
               'ReservationStation', 'Queue4_Vec16', 'ram_')


def die(msg):
    sys.exit(f'parse_area: {msg}')


def read_liberty(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        text = f.read()
    starts = [(m.start(), m.group(1)) for m in CELL_RE.finditer(text)]
    if not starts:
        die(f'no cells in {path}')
    cells = {}
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        body = text[pos:end]
        area = AREA_RE.search(body)
        if not area:
            die(f'cell {name} has no area in {path}')
        cells[name] = (float(area.group(1)), bool(SEQ_RE.search(body)))
    return cells


def read_mems_conf(path):
    mems = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            tok = line.split()
            if not tok:
                continue
            kv = dict(zip(tok[0::2], tok[1::2]))
            mems[kv['name']] = (int(kv['depth']), int(kv['width']))
    return mems


def summarize(args):
    run = args.run[0]
    stat_path = os.path.join(run, 'stat.json')
    with open(stat_path, encoding='utf-8') as f:
        stat = json.load(f)
    lib = read_liberty(args.lib)
    mems = read_mems_conf(args.mems_conf)
    mods = {k.lstrip('\\'): v for k, v in stat['modules'].items()}
    top_line = stat['invocation'].split()
    top = top_line[top_line.index('-top') + 1].lstrip('\\')

    memo = {}

    def rec(mod):
        """(area, flops, cells, {blackbox: count}) including submodules."""
        if mod in memo:
            return memo[mod]
        area = flops = cells = 0
        bbox = {}
        for ctype, n in mods[mod]['num_cells_by_type'].items():
            ctype = ctype.lstrip('\\')
            if ctype in lib:
                a, seq = lib[ctype]
                area += n * a
                cells += n
                flops += n if seq else 0
            elif ctype in mods:
                sa, sf, sc, sb = rec(ctype)
                area += n * sa
                flops += n * sf
                cells += n * sc
                for k, v in sb.items():
                    bbox[k] = bbox.get(k, 0) + n * v
            elif ctype in mems:
                bbox[ctype] = bbox.get(ctype, 0) + n
            else:
                die(f'unknown cell type {ctype} in module {mod}')
        memo[mod] = (area, flops, cells, bbox)
        return memo[mod]

    area, flops, cells, bbox = rec(top)
    yosys_area = float(mods[top]['area'])
    if abs(area - yosys_area) > REL_TOL * max(1.0, yosys_area):
        die(f'recomputed area {area} != yosys {yosys_area}')

    # Instance count of each module under top (hierarchy weighted).
    inst = {top: 1}
    order = [top]
    for mod in order:
        for ctype, n in mods[mod]['num_cells_by_type'].items():
            ctype = ctype.lstrip('\\')
            if ctype in mods:
                if ctype not in inst:
                    order.append(ctype)
                inst[ctype] = inst.get(ctype, 0) + inst[mod] * n
    if len(order) != len(set(order)):
        die('hierarchy walk revisited a module')

    src = os.path.basename(stat_path)
    print(f'# source: {src} (yosys stat -json), liberty {args.lib}')
    print(f'top {top}')
    print(f'logic_area_um2 {area:.3f}')
    print(f'yosys_area_um2 {yosys_area:.3f}')
    print(f'yosys_sequential_area_um2 {float(mods[top]["sequential_area"]):.3f}')
    print(f'flops {flops}')
    print(f'cells {cells}')
    sram_bits = 0
    for name in sorted(bbox):
        depth, width = mems[name]
        bits = bbox[name] * depth * width
        sram_bits += bits
        print(f'blackbox {name} count {bbox[name]} depth {depth} width {width} bits {bits}')
    print(f'sram_bits {sram_bits}')
    print('# module instances area_each_um2 area_total_um2 flops_total (incl. submodules)')
    for mod in sorted(inst):
        a, f, _c, _b = memo.get(mod) or rec(mod)
        print(f'module {mod} {inst[mod]} {a:.3f} {inst[mod] * a:.3f} {inst[mod] * f}')


def read_area_txt(run):
    path = os.path.join(run, 'area.txt')
    if not os.path.isfile(path):
        die(f'missing {path}')
    status = os.path.join(run, 'STATUS')
    with open(status, encoding='utf-8') as f:
        if f.read().strip() != 'DONE':
            die(f'{status} is not DONE')
    data = {'modules': {}, 'path': path}
    with open(path, encoding='utf-8') as f:
        for line in f:
            tok = line.split()
            if not tok or tok[0].startswith('#'):
                continue
            if tok[0] == 'module':
                data['modules'][tok[1]] = (int(tok[2]), float(tok[4]), int(tok[5]))
            elif tok[0] != 'blackbox':
                data[tok[0]] = tok[1]
    with open(os.path.join(run, 'run.info'), encoding='utf-8') as f:
        info = dict(l.rstrip('\n').split('=', 1) for l in f if '=' in l)
    data['lib'] = info['lib'].split()[0]
    data['config'] = info['config']
    return data


def pct(new, base):
    return f'{100.0 * (new - base) / base:+.2f}%' if base else 'n/a'


def compare(args):
    runs = [read_area_txt(r) for r in args.run]
    base = runs[0]
    for r in runs[1:]:
        if r['lib'] != base['lib']:
            die(f'{r["path"]} lib {r["lib"]} != base lib {base["lib"]}')
    print(f'lib {base["lib"]}; base {base["config"]} ({base["path"]})')
    print('| config | logic um^2 | vs base | flops | vs base | cells | SRAM bits | source |')
    print('|---|---|---|---|---|---|---|---|')
    for r in runs:
        la, ba = float(r['logic_area_um2']), float(base['logic_area_um2'])
        fl, bf = int(r['flops']), int(base['flops'])
        print(f'| {r["config"]} | {la:.1f} | {pct(la, ba)} | {fl} | {pct(fl, bf)} '
              f'| {r["cells"]} | {r["sram_bits"]} | `{r["path"]}` |')
    names = set()
    for r in runs:
        names.update(m for m in r['modules'] if m.startswith(KEY_MODULES))
    print()
    print('| module (total over instances) | ' + ' | '.join(r['config'] for r in runs) + ' |')
    print('|---|' + '---|' * len(runs))
    for m in sorted(names):
        cells = []
        for r in runs:
            v = r['modules'].get(m)
            cells.append(f'{v[1]:.1f} (x{v[0]}, {v[2]} ff)' if v else '-')
        print(f'| {m} | ' + ' | '.join(cells) + ' |')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--lib')
    ap.add_argument('--mems-conf')
    ap.add_argument('--compare', action='store_true')
    ap.add_argument('run', nargs='+')
    args = ap.parse_args()
    if args.compare:
        compare(args)
    elif args.lib and args.mems_conf and len(args.run) == 1:
        summarize(args)
    else:
        ap.error('need --compare, or --lib and --mems-conf with one run dir')


if __name__ == '__main__':
    main()
