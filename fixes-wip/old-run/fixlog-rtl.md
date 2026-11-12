# RTL fix log (sparse-nm, gemmini src/)

Base: branch sparse-nm HEAD 639a5068, clean at start. User diff: git diff 8c3f9923 sparse-nm -- src/
No commits, no branch switches, no sims/ or generated-src/ touched.

## Progress
- [ ] 1 clear command (funct 26, rd==1)
- [ ] 2 mode latched with weights (per weight buffer) + assert
- [ ] 3 sparse legality (WS, no transposes) + loop-cmd assert
- [ ] 4 meta FIFO deadlock fail-fast assert
- [ ] 5 a_hi stride-1 comment
- [ ] 6 dense build asserts (funct 26, rs1[10])
- [ ] 7 header defines


## Run 2 (edits done, awaiting sbt compile)
Files: Controller.scala, ExecuteController.scala, GemminiConfigs.scala (all uncommitted, src/ only)
- [x] 7 header: GemminiConfigs.scala ~526-528 now GEMMINI_HW_NM_N / GEMMINI_HW_NM_M (+HAS_NM_SPARSITY)
- [x] 1 clear: Controller is_nm_meta branch: inst.rd===1 -> ex_controller.io.nm_clear, consumed at dispatch;
      EX: nm_meta_q hasFlush, nm_asm_row:=0 on clear
- [x] 2 mode latch: EX nm_buf_sparse(2) indexed by row prop (compute uses buf p, preload writes ~p), latched on real preloads, assert on compute
- [x] 3 legality: EX config_ex asserts WS && !a_t && !b_t when rs1[10]; mode forced off if illegal. Controller raw_cmd shadow of rs1[10] -> assert on any loop funct
- [x] 4 deadlock: Controller counter 256 cycles of (meta blocked by full fifo && !RS.busy && ex quiet) ; EX nm_ex_quiet output
- [x] 5 a_hi comment at b_address
- [x] 6 dense: Controller assert(false) in funct-26 branch; EX assert nm_sparse==0 on full config_ex (gated by !set_only_strides because loop unrollers leave bit 10 DontCare)

## sbt compile
`sbt "project gemmini" compile` (PATH=~/chipyard/.conda-env/bin, JAVA_HOME same): [success], only pre-existing warnings. All 7 items done. Nothing elaborated.
