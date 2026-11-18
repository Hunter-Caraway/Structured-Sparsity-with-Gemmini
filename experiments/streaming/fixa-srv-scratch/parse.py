#!/usr/bin/env python3
"""parse.py <run_dir>: judge every log of a Fix A server run and print tables (tests, fair_perf, streaming).
Numbers are copied from the log lines; nothing is computed except min/max over seeds and ratios.
NEG builds pass only if every RTL assert they print is an expected (message, Controller/ExecuteController.scala line)
pair for that case (see NEG below); the message alone is not enough, since the "at <file>:<line>" line echoes the
assert's source text."""
import re, sys, os, csv, collections

run = sys.argv[1]
jobs = {}
with open(os.path.join(run, 'jobs.tsv')) as f:
    for r in csv.DictReader(f, delimiter='\t'):
        jobs[(r['chip'], r['binary'].replace('-baremetal', ''), r['seed'])] = r

# Expected RTL assert(s) per NEG case: (message text, source file:line). A NEG log passes only if it has at least one
# "Assertion failed: <msg>" line, every such line is followed by an "at <File>.scala:<line>" line, and every
# (message, source) pair it prints is one of the case's accepted pairs (same pair: message AND source line).
# Lines = generators/gemmini/src/main/scala/gemmini/{Controller,ExecuteController}.scala of the Fix A build
# (gemmini 639a5068 + uncommitted diff sha256 27c66ae5..., the diff the 2:4 / 4:8 sims of 20261111-183018 were built
# from; fix-a-server.md "Results"). Expected cases: fix-a-spec.md section 7, fix-a-sw.md "For the server rebuild",
# run-flow.sh neg_msg. Two-entry cases are the same-cycle double asserts of fix-a-review.md M6.
C, E = 'Controller.scala', 'ExecuteController.scala'
M_RD = ('rd values 3..31 are reserved', C + ':551')
M_CNT = ('tile count rs2[7:0] must be 1..4', C + ':604')
M_HI = ('rs1[63:32] and rs2[63:8] must be 0', C + ':605')
M_ADDR = ('rs1 must be a scratchpad row address', C + ':606')
M_BANK = ('the index rows must all lie in one scratchpad bank', C + ':608')
M_HALF = ('while a register-path index tile is half sent', C + ':610')
M_BUDGET = ('more than 4 index tiles ahead of their preloads', C + ':611')
M_DEAD = ('n:m index fifo deadlock', C + ':575')
M_MODE = ('differs from the mode its weights were preloaded in', E + ':949')
NEG = {
    'spad_neg21': [M_RD], 'spad_neg22': [M_RD],
    'spad_neg23': [M_CNT],
    'spad_neg24': [M_CNT, M_BUDGET],
    'spad_neg25': [M_HI], 'spad_neg26': [M_HI],
    'spad_neg27': [M_ADDR],
    'spad_neg28': [M_ADDR, M_BANK],
    'spad_neg29': [M_ADDR],
    'spad_neg30': [M_BANK], 'spad_neg31': [M_BANK],
    'spad_neg32': [M_HALF],
    'spad_neg33': [M_BUDGET], 'spad_neg34': [M_BUDGET],
    'spad_neg35': [('register rows (rd == 0) after a scratchpad index load', C + ':622')],
    'spad_neg36': [('clear (rd == 1) between a sparse preload and its compute', C + ':617')],
    'spad_neg37': [('n:m sparse preload with no index tile sent', C + ':629')],
    # nm_sparse_protocol (run-flow.sh neg_msg); NEG 4: the deadlock counter (:575) or, if the program-order model
    # catches the 5th tile at dispatch first, the budget assert (:611)
    'proto_neg4': [M_DEAD, M_BUDGET],
    'proto_neg7': [M_MODE],
    'proto_neg9': [('needs weight stationary dataflow', E + ':677')],
    'proto_neg10': [('issued while n:m sparse mode', C + ':281')],
    'proto_neg14': [M_MODE],
}


def assert_pairs(lines):
    """(message, 'File.scala:line' or None) for every 'Assertion failed: <msg>' line; the source is the next
    non-empty line if it reads 'at <File>.scala:<line> ...'."""
    out = []
    for i, l in enumerate(lines):
        if 'Assertion failed:' not in l:
            continue
        msg = l.rsplit('Assertion failed:', 1)[1].strip()
        src = None
        for k in range(i + 1, min(i + 4, len(lines))):
            if lines[k].strip():
                mm = re.match(r'\s*at (\w+\.scala):(\d+)\b', lines[k])
                src = '%s:%s' % mm.groups() if mm else None
                break
        out.append((msg, src))
    return out

logs = sorted(f for f in os.listdir(run) if f.endswith('.log'))
tests, fair, stream = [], [], []
for f in logs:
    m = re.match(r'(nm24|nm48)\.(.+)\.seed(\d+)\.log$', f)
    if not m:
        continue
    chip, name, seed = m.groups()
    text = open(os.path.join(run, f), errors='replace').read()
    j = jobs.get((chip, name, seed), {})
    rc = j.get('exit', '?'); wall = j.get('wall_s', '?')
    asserts = [l.strip() for l in text.splitlines() if 'Assertion failed' in l]
    base = re.sub(r'_(24|48)$', '', name)
    if base.startswith(('spad_neg', 'proto_neg')):
        exp = NEG[base]
        pairs = assert_pairs(text.splitlines())
        good = [p for p in pairs if any(e in p[0] and p[1] == s for e, s in exp)]
        caught = 'NOT caught' not in text
        ok = rc != '0' and bool(pairs) and len(good) == len(pairs) and caught
        detail = ('; '.join('%s @ %s' % (p[1], p[0][:90]) for p in pairs) if pairs else
                  ([l for l in text.splitlines() if 'NOT caught' in l or 'Error' in l] or ['(no assert)'])[0][:160])
        if not ok and pairs:
            detail += '  [expected one of: %s]' % ', '.join(s for _, s in exp)
        tests.append((chip, name, seed, 'PASS' if ok else 'FAIL', rc, wall, detail, f))
    elif base.startswith('nm_sparse'):
        ok = rc == '0' and re.search(r'^%s passed$' % base, text, re.M) is not None and not asserts
        last = [l for l in text.splitlines() if 'passed' in l or 'FAIL' in l or 'mismatch' in l or 'Assertion' in l]
        tests.append((chip, name, seed, 'PASS' if ok else 'FAIL', rc, wall, (last or ['(none)'])[-1][:160], f))
    elif base.startswith('fair_perf'):
        rows = {mm.group(1): int(mm.group(2)) for mm in re.finditer(r'^(\w+)\s+total\s+(\d+)', text, re.M)}
        ok = rc == '0' and 'fair_perf passed' in text and not asserts
        hdr = re.search(r'^fair_perf: (\S+),', text, re.M)
        nmatch = len(re.findall(r'matches the cpu reference', text))
        fair.append((chip, seed, ok, hdr.group(1) if hdr else '?', rows, nmatch, f))
    else:
        rows = {}
        for mm in re.finditer(r'^(\w+)\s+total\s+(\d+)\s+cpu_issue_done\s+(\d+) \| ex_active=(\d+)', text, re.M):
            rows[mm.group(1)] = tuple(int(x) for x in mm.groups()[1:])
        ver = re.findall(r'^(\w+) check: .* -> (\w+)', text, re.M)
        sp = re.search(r'^sbench passed \((\d+) of (\d+) runs verified\)', text, re.M)
        ok = rc == '0' and sp is not None and sp.group(1) == sp.group(2) and not asserts
        layer = re.search(r'layer=(\w+)', text)
        stream.append((chip, name, seed, ok, rows, ver, sp.group(0) if sp else '(no sbench passed)', f, asserts))

print('== tests')
for t in sorted(tests):
    print('%-5s %-28s s%s %-4s rc=%-3s %5ss  %s' % (t[0], t[1], t[2], t[3], t[4], t[5], t[6]))
print('tests: %d PASS, %d FAIL' % (sum(t[3] == 'PASS' for t in tests), sum(t[3] != 'PASS' for t in tests)))

print('\n== fair_perf')
for chip, seed, ok, hdr, rows, nmatch, f in sorted(fair):
    print('%s seed %s %s pattern=%s matches=%d %s' % (chip, seed, 'ok' if ok else 'FAIL', hdr, nmatch,
          ' '.join('%s=%d' % kv for kv in rows.items())))
by = collections.defaultdict(list)
for chip, seed, ok, hdr, rows, nmatch, f in fair:
    for k, v in rows.items():
        by[(chip, k)].append(v)
print('fair ranges (seeds):')
for (chip, k), v in sorted(by.items()):
    print('  %s %-20s min %7d max %7d n=%d' % (chip, k, min(v), max(v), len(v)))

print('\n== streaming')
for chip, name, seed, ok, rows, ver, sp, f, asserts in sorted(stream):
    print('%s %-24s s%s %s %s | %s' % (chip, name, seed, 'ok' if ok else 'FAIL', sp,
          '  '.join('%s total=%d cpu=%d ex=%d' % ((k,) + v) for k, v in rows.items())))
    if asserts:
        print('   ASSERT:', asserts[0][:200])
sb = collections.defaultdict(list)
for chip, name, seed, ok, rows, ver, sp, f, asserts in stream:
    for k, v in rows.items():
        sb[(chip, name, k)].append(v[0])
print('stream ranges (total, seeds):')
for (chip, name, k), v in sorted(sb.items()):
    print('  %s %-24s %-14s min %9d max %9d n=%d' % (chip, name, k, min(v), max(v), len(v)))
