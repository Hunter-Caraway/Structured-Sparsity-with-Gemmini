# spike-meta-rd: why Spike aborts "funct 26: rd values 3..31 reserved (rd = 0)" (read-only investigation)

Root cause: NOT a model bug. run-flow.sh:500 and :508 pass `--extension=gemmini` BEFORE `--extlib=...`.
spike_main/spike.cc:398 handles --extension immediately (find_extension -> dlopen("libgemmini.so") via spike RPATH =
the installed Nov 3 $RISCV/lib/libgemmini.so, pre-spad-index-fix); the --extlib (spike.cc:408) is dlopen'd RTLD_GLOBAL
afterwards. Both libs are then mapped; the installed lib's gemmini_t object (old, smaller layout) is dispatched through the
installed gemmini_custom, which calls gemmini_t::custom3 resolved (symbol interposition) to the NEW lib. New code reads
`const unsigned nm_meta_*_rd` members at this+0x3d0.. of an old-layout object = garbage (gdb: 1,8,9) -> rd 0 matches none -> abort.
Evidence: gdb bt at abort: frame1 custom3 in scratch .so, frame2 gemmini_custom in $RISCV/lib/libgemmini.so;
info sharedlibrary lists both. Sources in scratch copybuild == repo HEAD 2a6ff44 (diff -q clean); test binaries encode
funct 26 rd=0 (0x34f7b07b), rd=1 (0x34f7b0fb) correctly.
Fix check (1 run each, extlib first): nm_sparse_matmul_24, debug_24, protocol_24, perf_24 all pass rc=0.
Recorded Fix-A scripts all use extlib first (spike_run.sh:10 both copies, fixa-srv-scratch/spike_check.sh:7, dense-gap.md:82,
old-run/fixlog-spike.md:5 "extlib must come first") -> recorded results unaffected.

## RESUME HERE
Done: root cause found, confirmed by 5 spike runs total. Next (caller): swap arg order in run-flow.sh:500,508 (and
fixes-wip/fixlog-rocc-tests.md:29 text); no libgemmini/spec change. Optional hardening: step_spike could fail if
`spike -l`/ldd shows 2 libgemmini mapped. No spec changelog needed.
