#!/usr/bin/env python3
# itrace.py <binary> <spike -l trace> [--lines]: per timed run() region (start rdcycle .. issued rdcycle), count
# instructions, RoCC commands by funct (funct 26 split by rd), and instructions per source line (needs -g).
import sys, re, subprocess, collections
binf, tr = sys.argv[1], sys.argv[2]
lines = '--lines' in sys.argv
OD = 'riscv64-unknown-elf-objdump'
dis = subprocess.run([OD, '-d', binf], capture_output=True, text=True).stdout
# locate run(): the jalr followed by rdcycle; start = last rdcycle before it
fun = None; insns = []
for l in dis.splitlines():
    m = re.match(r'^([0-9a-f]+) <(\S+)>:', l)
    if m: fun = m.group(2); continue
    m = re.match(r'^\s+([0-9a-f]+):\s+[0-9a-f]+\s+(\S+)\s*(.*)', l)
    if m and fun == 'run': insns.append((int(m.group(1), 16), m.group(2), m.group(3)))
start_pc = issued_pc = None
for k, (pc, op, a) in enumerate(insns):
    if op == 'jalr' and k + 1 < len(insns) and insns[k + 1][1] == 'rdcycle':
        prev = [p for p, o, _ in insns[:k] if o == 'rdcycle']
        start_pc, issued_pc = prev[-1], insns[k + 1][0]
assert start_pc, 'run() timed region not found'
# symbol ranges
syms = []
for l in subprocess.run(['riscv64-unknown-elf-nm', '-S', '--defined-only', binf], capture_output=True, text=True).stdout.splitlines():
    p = l.split()
    if len(p) == 4 and p[2] in 'tT': syms.append((int(p[0], 16), int(p[0], 16) + int(p[1], 16), p[3]))
syms.sort()
def sym(pc):
    for a, b, n in syms:
        if a <= pc < b: return n
    return '?'
names = {0:'CONFIG',1:'MVIN2',2:'MVIN',3:'MVOUT',4:'COMPUTE_PRELOADED',5:'COMPUTE_ACCUMULATE',6:'PRELOAD',7:'FLUSH',8:'LOOP_WS',14:'MVIN3',126:'COUNTER'}
rx = re.compile(r'^core\s+0: 0x([0-9a-f]+) \(0x([0-9a-f]+)\)')
regions = []; cur = None
for l in open(tr):
    m = rx.match(l)
    if not m: continue
    pc = int(m.group(1), 16)
    if pc == start_pc: cur = {'n': 0, 'f': collections.Counter(), 'pcs': collections.Counter()}; continue
    if cur is None: continue
    if pc == issued_pc: regions.append(cur); cur = None; continue
    w = int(m.group(2), 16)
    cur['n'] += 1; cur['pcs'][pc] += 1
    if w & 0x7f == 0x7b:
        f = w >> 25; rd = (w >> 7) & 31
        cur['f'][names.get(f, str(f)) + (f'/rd{rd}' if f == 26 else '')] += 1
for i, r in enumerate(regions):
    nc = sum(r['f'].values())
    print(f'region {i}: {r["n"]} instructions, {nc} rocc cmds')
    for k, v in sorted(r['f'].items(), key=lambda x: -x[1]): print(f'   {k:22s} {v}')
    bysym = collections.Counter()
    for pc, c in r['pcs'].items(): bysym[sym(pc)] += c
    print('   by function:', ', '.join(f'{k} {v}' for k, v in bysym.most_common(8)))
    if lines:
        pcs = sorted(r['pcs'])
        out = subprocess.run(['riscv64-unknown-elf-addr2line', '-e', binf] + [hex(p) for p in pcs], capture_output=True, text=True).stdout.split('\n')
        byline = collections.Counter()
        for p, s in zip(pcs, out): byline[re.sub(r'.*/', '', s.split(' ')[0])] += r['pcs'][p]
        for k, v in byline.most_common(30): print(f'      {k:40s} {v}')
