#!/usr/bin/env python3
"""List the Verilog files a top module needs, from one firtool gen-collateral dir.

firtool writes one module per file, so the closure is found by scanning module
definitions and instantiation lines. Modules defined only in the macro file
(the SRAM *_ext models) are leaves to be blackboxed by the synthesis script.

Usage: verilog_closure.py <gen-collateral dir> <top> <macro .v> <out prefix>
Writes <out prefix>.files (absolute paths, top-down order) and
<out prefix>.txt (human-readable: modules, blackboxes and their counts).
Exits non-zero on an undefined module or a module defined twice.
"""

import os
import re
import sys

MODULE_RE = re.compile(r'^\s*module\s+(\w+)', re.M)
# firtool instance: "  <Module> <inst> (", or "<Module> #(...) <inst> (" with
# the parameter list over several lines (e.g. plusarg_reader).
INST_RE = re.compile(
    r'^[ \t]*(\w+)\s+(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?(\w+)\s*\(', re.M)
# Verilog keywords that can start a line like "end else if (".
KEYWORDS = {
    'module', 'if', 'else', 'for', 'while', 'case', 'casez', 'casex', 'end',
    'begin', 'assign', 'always', 'always_ff', 'always_comb', 'always_latch',
    'initial', 'final', 'function', 'task', 'wire', 'reg', 'logic', 'input',
    'output', 'inout', 'unique', 'priority', 'automatic', 'return', 'endcase',
    'default', 'assert', 'assume', 'cover', 'property', 'generate', 'repeat',
    'forever', 'fork', 'localparam', 'parameter', 'integer', 'bit', 'byte',
    'int', 'genvar', 'typedef', 'struct', 'import', 'export', 'wait',
}


def strip_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'//[^\n]*', '', text)


def main():
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    src_dir, top, macro_file, out = sys.argv[1:]
    defs = {}
    for name in sorted(os.listdir(src_dir)):
        path = os.path.join(src_dir, name)
        if not (name.endswith('.sv') or name.endswith('.v')):
            continue
        if not os.path.isfile(path) or name.endswith('.mems.v'):
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            text = strip_comments(f.read())
        for mod in MODULE_RE.findall(text):
            if mod in defs:
                sys.exit(f'closure: module {mod} defined in {defs[mod][0]} '
                         f'and {path}')
            defs[mod] = (path, text)
    with open(macro_file, encoding='utf-8') as f:
        macros = set(MODULE_RE.findall(strip_comments(f.read())))

    order, seen, bbox = [], set(), {}
    stack = [top]
    if top not in defs:
        sys.exit(f'closure: top {top} not found in {src_dir}')
    while stack:
        mod = stack.pop()
        if mod in seen:
            continue
        seen.add(mod)
        order.append(mod)
        for sub, _inst in INST_RE.findall(defs[mod][1]):
            if sub in KEYWORDS:
                continue
            if sub in defs:
                stack.append(sub)
            elif sub in macros:
                bbox.setdefault(sub, set()).add(mod)
            else:
                sys.exit(f'closure: {mod} instantiates undefined {sub}')

    files = []
    for mod in order:
        path = defs[mod][0]
        if path not in files:
            files.append(path)
    with open(out + '.files', 'w', encoding='utf-8') as f:
        f.write(''.join(p + '\n' for p in files))
    with open(out + '.txt', 'w', encoding='utf-8') as f:
        f.write(f'top {top}\nmodules {len(order)}\nfiles {len(files)}\n')
        for name in sorted(bbox):
            f.write(f'blackbox {name} used_by {",".join(sorted(bbox[name]))}\n')
        for name in sorted(macros - set(bbox)):
            f.write(f'macro_not_in_closure {name}\n')
        for mod in sorted(order):
            f.write(f'module {mod}\n')


if __name__ == '__main__':
    main()
