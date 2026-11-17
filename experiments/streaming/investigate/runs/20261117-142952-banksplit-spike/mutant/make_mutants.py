# make_mutants.py <gemmini.cc> <out_dir>: Spike mutants of bank-split-fix-spec.md section 7 (M1-M4) plus M5
import sys, os
src = open(sys.argv[1]).read()
O_LINE = "const uint32_t nm_o_off = nm_b_off + nm_bsz > BANK_ROWS ? nm_b_off + nm_bsz : BANK_ROWS;"
MV_HI = "(rows << 48) | (cols << 32) | A_hi_sp_addr, 0);"
RS2_HI = "nm ? (A_rows << 48) | ((uint64_t)DIM << 32) | A_hi_sp_addr :"
N9 = "nm_loop_abort(\"A, B and index regions do not fit"
muts = {
    # M1: old layout, a_hi = a_lo + DIM (forgotten wiring): BS3 must fire
    "m1": [(O_LINE, "const uint32_t nm_o_off = DIM;")],
    # M2: LdA writes the odd tiles next to a_lo (old place), compute reads them from O: data check must fail
    "m2": [(MV_HI, "(rows << 48) | (cols << 32) | (A_sp_addr + DIM), 0);")],
    # M3: N9 dropped: NEG 90 / 92 must not abort with the N9 text
    "m3": [(N9, "if (0) " + N9)],
    # M4: compute reads the O region one tile (16 rows) off: data check must fail
    "m4": [(RS2_HI, "nm ? (A_rows << 48) | ((uint64_t)DIM << 32) | (A_hi_sp_addr + DIM) :")],
    # M5: O always at the second bank, ignoring B's end: O overlaps a straddling B; only the new bank cases see it
    "m5": [(O_LINE, "const uint32_t nm_o_off = BANK_ROWS;")],
}
for name, subs in muts.items():
    s = src
    for old, new in subs:
        assert s.count(old) == 1, (name, old)
        s = s.replace(old, new)
    d = os.path.join(sys.argv[2], name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "gemmini.cc"), "w").write(s)
    print(name, "written")
