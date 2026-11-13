#!/usr/bin/env python3
"""Count instructions of the first q3_dense_icount counted region (dense_icount) in a `spike -l` trace read from stdin.

usage: spike -l ... 2>&1 | q3_trace_count.py <layer.log>

The region is delimited by the program's rdinstret instructions (csrrs rd, instret, x0): from the first one
(inclusive, Spike's instret read excludes the reading instruction itself) to the second one (exclusive). The count
must equal instret= in the q3 line of <layer.log> (the untraced run); exit 1 if not. Also counts the RoCC commands
(custom3, opcode 0x7b) in the region by funct7. Exits as soon as the second rdinstret is seen.
"""
import re
import sys

LINE = re.compile(r"^core\s+\d+: 0x([0-9a-f]+) \(0x([0-9a-f]+)\)")
CUSTOM3 = 0x7B


def is_rdinstret(insn):
    # csrrs rd, 0xc02, x0
    return insn & 0xFFFFF07F == 0xC0202073


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: q3_trace_count.py <layer.log>  (trace on stdin)")
    want = None
    with open(sys.argv[1]) as f:
        for n, line in enumerate(f, 1):
            m = re.match(r"q3 dense_icount: .* instret=(\d+) .* verified$", line)
            if m:
                want, want_line = int(m.group(1)), n
    if want is None:
        sys.exit("error: no verified 'q3 dense_icount' line in %s" % sys.argv[1])

    seen = 0
    count = 0
    lines = 0
    rocc = {}
    for line in sys.stdin:
        m = LINE.match(line)
        if not m:
            continue
        lines += 1
        insn = int(m.group(2), 16)
        if is_rdinstret(insn):
            seen += 1
            if seen == 2:
                break
        if seen == 1:
            count += 1
            if insn & 0x7F == CUSTOM3 and insn & 3 == 3:
                funct = insn >> 25
                rocc[funct] = rocc.get(funct, 0) + 1
    if seen != 2:
        sys.exit("error: trace ended after %d rdinstret (need 2), %d trace lines" % (seen, lines))
    print("trace lines before region end: %d" % lines)
    print("trace instructions in region: %d" % count)
    print("rdinstret delta in %s:%d: %d" % (sys.argv[1], want_line, want))
    print("rocc commands in region: %d, by funct7: %s"
          % (sum(rocc.values()), " ".join("%d:%d" % kv for kv in sorted(rocc.items()))))
    if count != want:
        print("MISMATCH")
        sys.exit(1)
    print("match")


if __name__ == "__main__":
    main()
