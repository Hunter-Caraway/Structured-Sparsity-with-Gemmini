#!/usr/bin/env python3
"""parse.py <run_dir>: judge every log of a Fix A / sparse-loop-fix server run and print tables (tests, fair_perf,
streaming). Numbers are copied from the log lines; nothing is computed except min/max over seeds and ratios.
NEG builds pass only if every RTL assert they print carries one of the case's expected message texts (see NEG below)
and its own "at <File>.scala:<line>" line. The message is read from the "Assertion failed: <msg>" line only, never
from the "at" line, which echoes the assert's source text. Source line numbers are printed, not checked: they move
with every RTL edit.
Berkeley's dense tests (DENSE below) print no pass line of their own; they are judged on the simulator's ending.
Logs of all three chips (nm24, nm48, stock) are judged; KNOWN_BERKELEY failures are listed apart and not counted."""
import re, sys, os, csv, collections

run = sys.argv[1]
jobs = {}
with open(os.path.join(run, 'jobs.tsv')) as f:
    for r in csv.DictReader(f, delimiter='\t'):
        # the program column is named 'binary' in the server runs and 'program' in older job tables
        prog = r['binary'] if 'binary' in r else r['program']
        jobs[(r['chip'], prog.replace('-baremetal', ''), r['seed'])] = r

# Expected RTL assert message(s) per NEG case. A NEG log passes only if it has at least one
# "Assertion failed: <msg>" line, every such line is followed by an "at <File>.scala:<line>" line, and every message
# it prints contains one of the case's accepted texts. Expected cases: fix-a-spec.md section 7, fix-a-sw.md "For the
# server rebuild", run-flow.sh neg_msg. Two-entry cases are the same-cycle double asserts of fix-a-review.md M6.
M_RD = 'NM_META_CMD (funct 26): rd values 3..31 are reserved'
M_CNT = 'NM_META_CMD rd == 2: tile count rs2[7:0] must be 1..4'
M_HI = 'NM_META_CMD rd == 2: rs1[63:32] and rs2[63:8] must be 0'
M_ADDR = 'NM_META_CMD rd == 2: rs1 must be a scratchpad row address'
M_BANK = 'NM_META_CMD rd == 2: the index rows must all lie in one scratchpad bank'
M_HALF = 'NM_META_CMD rd == 2 while a register-path index tile is half sent'
M_BUDGET = 'n:m index fifo: more than 4 index tiles ahead of their preloads'
M_DEAD = 'n:m index fifo deadlock: more than 4 index tiles sent ahead of their preloads'
M_MODE = 'n:m sparse mode of a compute differs from the mode its weights were preloaded in'
# LOOP_WS with no nm flag while sparse mode is on. Before sparse-loop-fix one assert covered LOOP_WS and
# LOOP_CONV_WS; N1 of fix-b-spec.md 2.5.6 replaces its LOOP_WS half (spec line "N2 replaces the LOOP_CONV_WS half
# ... the LOOP_WS half is replaced by N1"), so a log shows whichever text its build has.
M_LOOP_OLD = 'LOOP_WS / LOOP_CONV_WS issued while n:m sparse mode (config_ex rs1[10]) is on'
M_LOOP_N1 = 'sparse-loop-fix: LOOP_WS nm flag (rs1[3]) differs from n:m sparse mode (config_ex rs1[10])'
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
    'spad_neg35': ['NM_META_CMD register rows (rd == 0) after a scratchpad index load'],
    'spad_neg36': ['NM_META_CMD clear (rd == 1) between a sparse preload and its compute'],
    'spad_neg37': ['n:m sparse preload with no index tile sent'],
    # nm_sparse_protocol (run-flow.sh neg_msg); NEG 4: the deadlock counter or, if the program-order model catches
    # the 5th tile at dispatch first, the budget assert
    'proto_neg4': [M_DEAD, M_BUDGET],
    'proto_neg7': [M_MODE],
    'proto_neg9': ['n:m sparse mode (config_ex rs1[10]) needs weight stationary dataflow'],
    'proto_neg10': [M_LOOP_OLD, M_LOOP_N1],
    'proto_neg14': [M_MODE],
}
# the same nm_sparse_protocol -DNEG=<n> builds are named proto_neg<n> or nm_sparse_protocol_neg<n>, by run
PROTO_NEG_RE = re.compile(r'nm_sparse_protocol_neg(\d+)$')

# Berkeley's 54 dense tests: the `tests` list of gemmini-rocc-tests/bareMetalC/Makefile (22158bf) without nm_* and
# without the two its normal-config filter drops (matmul_spad, mvin_mvout_spad); the list run-flow.sh dense_tests
# derives. A dense log passes when jobs.tsv has exit 0, its last line is the simulator's "Verilog $finish", and it
# has none of DENSE_BAD.
DENSE = frozenset("""
mvin_mvout mvin_mvout_zeros mvin_mvout_stride mvin_mvout_block_stride mvin_mvout_acc mvin_mvout_acc_zero_stride
mvin_mvout_acc_stride mvin_mvout_acc_full mvin_mvout_acc_full_stride matmul_os matmul_ws matmul raw_hazard aligned
padded mvin_scale conv conv_stride conv_rect conv_rect_pool conv_with_pool conv_with_rot180 conv_with_kernel_dilation
conv_with_input_dilation conv_with_input_dilation_and_rot180 conv_with_input_dilation_and_neg_padding
conv_trans_output_1203 conv_trans_weight_1203 conv_trans_weight_0132 conv_trans_input_3120
conv_trans_input_3120_with_kernel_dilation conv_first_layer conv_dw conv_perf conv_dw_perf tiled_matmul_os
tiled_matmul_ws tiled_matmul_ws_At tiled_matmul_ws_Bt tiled_matmul_ws_full_C tiled_matmul_ws_low_D
tiled_matmul_ws_igelu tiled_matmul_ws_layernorm tiled_matmul_ws_softmax tiled_matmul_ws_perf tiled_matmul_cpu
tiled_matmul_option transpose matrix_add resadd resadd_stride global_average gemmini_counter template
""".split())
assert len(DENSE) == 54
DENSE_BAD = ('*** FAILED ***', 'Assertion', '%Error', '%Fatal', 'Verilog $stop')
# KNOWN-BERKELEY allowlist: dense tests that fail the same way on Berkeley's unmodified stock chip
# (worklogs/berkeley-issues.md B4, B5). A log matching its signature is printed as KNOWN-BERKELEY FAIL and does not
# count toward the exit status; any other failure of these tests still fails. conv_with_input_dilation* are NOT here:
# their timeouts are unresolved.
KNOWN_BERKELEY = {
    'gemmini_counter': ('B4', ('Counter values changed too little after snapshot reset', '*** FAILED *** (tohost = 1)')),
    'global_average': ('B5', ('\nFail\n', '*** FAILED *** (tohost = 1)')),
}
# berkeley-issues.md B6: these exit 0 before testing anything on our configs, so their PASS is not evidence
VACUOUS = frozenset(('tiled_matmul_ws_igelu', 'tiled_matmul_ws_layernorm', 'tiled_matmul_ws_softmax'))

# sparse-loop-fix NEG builds (nm_sparse_loop -DNEG=<n>, n / 10 = assert N1..N14 of fix-b-spec.md 2.5.6; same texts as
# run-flow.sh loop_neg_msg). The source lines are not pinned here: a case passes if every assert it prints carries its
# own text and an "at <File>.scala:<line>" line. N11 and N14 are Spike-only (spec changelog 2026-11-13 D1), so an RTL
# log of NEG 110 / 140 fails.
LOOP_MSG = {
    1: 'sparse-loop-fix: LOOP_WS nm flag (rs1[3]) differs from n:m sparse mode (config_ex rs1[10])',
    2: 'sparse-loop-fix: LOOP_CONV_WS issued while n:m sparse mode (config_ex rs1[10]) is on',
    3: 'sparse-loop-fix: LOOP_WS with rs1[3] set needs LOOP_WS_CONFIG_NM (funct 28) first',
    4: 'sparse-loop-fix: LOOP_WS_CONFIG_NM (funct 28) without LOOP_WS rs1[3]',
    5: 'sparse-loop-fix: LOOP_WS_CONFIG_NM needs a non-zero 16-byte aligned rs1 and rs2 == 0',
    6: 'sparse-loop-fix: sparse loop needs an even K tile count and pad_K == 0 (K % 2*DIM)',
    7: 'sparse-loop-fix: sparse loop does not support transposes, resadd, low_D or spad-only',
    8: 'sparse-loop-fix: sparse loop needs A_stride == 1',
    9: "sparse-loop-fix: A, B and index regions do not fit in the loop's scratchpad half (or index region exceeds one bank)",
    10: 'sparse-loop-fix: sparse loop started with index tiles pending in the FIFO: gemmini_nm_reset() first',
    12: 'sparse-loop-fix: LOAD_IDX needs cols == 16 and 1..16 rows',
    13: 'sparse-loop-fix: LOAD_IDX destination must be a scratchpad row address',
}
LOOP_NEG_RE = re.compile(r'(?:nm_sparse_)?loop_?neg(\d+)$')
LOOP_TILES_RE = re.compile(r'^sparse_loop tiles: tile_I=(\d+) tile_J=(\d+) tile_K=(\d+)$', re.M)


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
    m = re.match(r'(nm24|nm48|stock)\.(.+)\.seed(\d+)\.log$', f)
    if not m:
        continue
    chip, name, seed = m.groups()
    text = open(os.path.join(run, f), errors='replace').read()
    j = jobs.get((chip, name, seed), {})
    rc = j.get('exit', '?'); wall = j.get('wall_s', '?')
    asserts = [l.strip() for l in text.splitlines() if 'Assertion failed' in l]
    base = re.sub(r'_(24|48)$', '', name)
    pm = PROTO_NEG_RE.match(base)
    if pm:
        base = 'proto_neg' + pm.group(1)
    if base.startswith(('spad_neg', 'proto_neg')):
        exp = NEG.get(base, [])  # a case with no entry has no expected assert and fails
        pairs = assert_pairs(text.splitlines())
        good = [p for p in pairs if p[1] and any(e in p[0] for e in exp)]
        caught = 'NOT caught' not in text
        # rc '?' = no jobs.tsv row: the exit status is unknown, so the expected failure is not shown
        ok = rc not in ('0', '?') and bool(pairs) and len(good) == len(pairs) and caught
        detail = ('; '.join('%s @ %s' % (p[1], p[0][:90]) for p in pairs) if pairs else
                  ([l for l in text.splitlines() if 'NOT caught' in l or 'Error' in l] or ['(no assert)'])[0][:160])
        if not ok and pairs:
            detail += '  [expected one of: %s]' % (' | '.join(exp) or 'no RTL assert is listed for this case')
        tests.append((chip, name, seed, 'PASS' if ok else 'FAIL', rc, wall, detail, f))
    elif LOOP_NEG_RE.match(base):
        exp = LOOP_MSG.get(int(LOOP_NEG_RE.match(base).group(1)) // 10)
        pairs = assert_pairs(text.splitlines())
        good = [p for p in pairs if exp and exp in p[0] and p[1]]
        caught = 'NOT caught' not in text
        ok = rc not in ('0', '?') and bool(pairs) and len(good) == len(pairs) and caught
        detail = ('; '.join('%s @ %s' % (p[1], p[0][:90]) for p in pairs) if pairs else
                  ([l for l in text.splitlines() if 'NOT caught' in l or 'Error' in l] or ['(no assert)'])[0][:160])
        if not ok:
            detail += '  [expected: %s]' % (exp or 'no RTL assert exists for this case (Spike-only or unknown NEG)')
        tests.append((chip, name, seed, 'PASS' if ok else 'FAIL', rc, wall, detail, f))
    elif base.startswith('nm_'):
        # nm_sparse_* print "<base> passed"; case-subset builds of them (e.g. nm_loop7 = nm_sparse_loop cases 7-17)
        # print their parent's "nm_sparse_<x> passed". Both must end on the simulator's "Verilog $finish".
        pline = re.escape(base) if base.startswith('nm_sparse') else r'nm_sparse_\w+'
        ll = [l for l in text.splitlines() if l.strip()]
        fin = bool(ll) and 'Verilog $finish' in ll[-1]
        ok = rc == '0' and re.search(r'^%s passed$' % pline, text, re.M) is not None and not asserts and fin
        last = [l for l in text.splitlines() if 'passed' in l or 'FAIL' in l or 'mismatch' in l or 'Assertion' in l]
        tests.append((chip, name, seed, 'PASS' if ok else 'FAIL', rc, wall, (last or ['(none)'])[-1][:160], f))
    elif name in DENSE:
        ll = [l for l in text.splitlines() if l.strip()]
        bad = [l for l in ll if any(b in l for b in DENSE_BAD)]
        fin = bool(ll) and 'Verilog $finish' in ll[-1]
        ok = rc == '0' and fin and not bad
        detail = 'dense: ' + (bad[0].strip() if bad else 'Verilog $finish' if fin else
                              'no Verilog $finish at the end: ' + (ll[-1].strip() if ll else '(empty log)'))
        status = 'PASS' if ok else 'FAIL'
        kb = KNOWN_BERKELEY.get(name)
        if not ok and kb and rc not in ('0', '?') and all(sig in text for sig in kb[1]):
            status = 'KNOWN-BERKELEY FAIL'
            detail = '%s (berkeley-issues.md %s, not counted)' % (detail[:110], kb[0])
        elif ok and name in VACUOUS:
            detail += ' [NOTE berkeley-issues.md B6: exits before testing, vacuous pass]'
        tests.append((chip, name, seed, status, rc, wall, detail[:180], f))
    elif base.startswith('fair_perf') or base == 'berkeley_dense_perf':
        rows = {mm.group(1): int(mm.group(2)) for mm in re.finditer(r'^(\w+)\s+total\s+(\d+)', text, re.M)}
        # every Gemmini variant's total line counts only with its own reference match (cpu_* rows have none)
        loop_bad = [k for k in rows if not k.startswith('cpu_')
                    and not re.search(r'^%s matches the cpu reference' % k, text, re.M)]
        pname = 'berkeley_dense_perf' if base == 'berkeley_dense_perf' else 'fair_perf'
        ok = rc == '0' and re.search(r'^%s passed$' % pname, text, re.M) is not None and not asserts and not loop_bad
        hdr = re.search(r'^fair_perf: (\S+),', text, re.M)
        nmatch = len(re.findall(r'matches the cpu reference', text))
        if base == 'berkeley_dense_perf':
            hdr = re.search(r'^berkeley_dense_perf: [^,]*, (\S+)', text, re.M)
        # stock runs two programs that share row names (dense, dense_reuse): label them apart; nm fair_perf_24/48 keep
        # the bare chip label
        label = chip if base == 'fair_perf' else '%s %s' % (chip, base)
        fair.append((label, seed, ok, hdr.group(1) if hdr else '?', rows, nmatch, f))
    else:
        rows = {}
        for mm in re.finditer(r'^(\w+)\s+total\s+(\d+)\s+cpu_issue_done\s+(\d+) \| ex_active=(\d+)', text, re.M):
            rows[mm.group(1)] = tuple(int(x) for x in mm.groups()[1:])
        ver = re.findall(r'^(\w+) check: .* -> (\w+)', text, re.M)
        sp = re.search(r'^sbench passed \((\d+) of (\d+) runs verified\)', text, re.M)
        ok = rc == '0' and sp is not None and sp.group(1) == sp.group(2) and not asserts
        note = sp.group(0) if sp else '(no sbench passed)'
        if 'sparse_loop' in rows:
            # its total needs its own "-> verified" check line and the one tiles line the program prints
            tiles = LOOP_TILES_RE.findall(text)
            if dict(ver).get('sparse_loop') != 'verified' or len(tiles) != 1:
                ok = False
                note += ' [sparse_loop: check line %s, %d tiles lines]' % (dict(ver).get('sparse_loop', 'missing'), len(tiles))
            else:
                note += ' [sparse_loop tiles I=%s J=%s K=%s]' % tiles[0]
        stream.append((chip, name, seed, ok, rows, ver, note, f, asserts))

print('== tests')
for t in sorted(tests):
    print('%-5s %-28s s%s %-4s rc=%-3s %5ss  %s' % (t[0], t[1], t[2], t[3], t[4], t[5], t[6]))
known = [t for t in tests if t[3] == 'KNOWN-BERKELEY FAIL']
print('tests: %d PASS, %d FAIL' % (sum(t[3] == 'PASS' for t in tests), sum(t[3] == 'FAIL' for t in tests))
      + (', %d KNOWN-BERKELEY FAIL (not counted)' % len(known) if known else ''))
if known:
    print('\n== KNOWN-BERKELEY FAIL (fail on stock RTL too; berkeley-issues.md; not counted in the exit status)')
    for t in sorted(known):
        print('%-5s %-28s s%s rc=%-3s %s' % (t[0], t[1], t[2], t[4], t[6]))

print('\n== fair_perf')
# the file name breaks ties (two fair programs on one chip and seed), so the row dicts are never compared
for chip, seed, ok, hdr, rows, nmatch, f in sorted(fair, key=lambda r: (r[0], r[1], r[2], r[3], r[6])):
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

# jobs.tsv rows with no log (e.g. a log not copied back) fail the run
missing = sorted('%s.%s.seed%s.log' % k for k in jobs if '%s.%s.seed%s.log' % k not in logs)
for f in missing:
    print('MISSING LOG', f)
nfail = (sum(t[3] == 'FAIL' for t in tests) + sum(not r[2] for r in fair) + sum(not r[3] for r in stream)
         + len(missing))
if nfail or not (tests or fair or stream):
    sys.exit('parse_fixa: %d failed or missing logs, %d logs judged' % (nfail, len(tests) + len(fair) + len(stream)))
