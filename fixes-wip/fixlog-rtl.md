# RTL fix log (sparse-nm @ 639a5068, gemmini src/ only) - session 2026-11-03

Base: previous agent's patch (discarded-fixes-20261103-081930/gemmini.patch, src/ only) applied with
`git apply --include='src/*'`, then reviewed. No commits, no sims, no elaboration.

## Review of the previous patch
- Item 2 (mode latch) was WRONG: indexed buffers by cntl.prop, but the PE select is MeshWithDelays.in_prop,
  which XORs pe_control.propagate on every mesh req. Redo with an exact mirror of in_prop.
- Item 3 loop assert fired on loop config functs too (9-13, 16-21, 24-25); spec only names LOOP_WS / LOOP_CONV_WS.
- Dense-build nm_meta_in assert in EX duplicated the Controller funct-26 assert; drop the EX one.
- Rest reused (clear, FIFO flush, deadlock check, header macros, legality, dense config_ex assert).

## Progress
- [x] 1 clear: Controller.scala:530-538 (rd==1 -> io.nm_clear, consumed at dispatch, never enqueued);
      ExecuteController.scala:25 (nm_clear IO), :207-209 (Queue hasFlush), :231-233 (nm_asm_row := 0)
- [x] 2 mode latch: ExecuteController.scala:884-900, REWRITTEN. nm_mesh_prop mirrors MeshWithDelays.in_prop
      (XOR of pe_control.propagate on every mesh req fire); compute asserts buf(p) == cntl.nm_sparse; real preload
      writes buf(~p). Dense preloads zero indexes already (MeshWithDelays gate + nm_meta_row Mux).
- [x] 3 legality: ExecuteController.scala:618-624 (assert + force off); Controller.scala:272-284 loop assert now
      only on LOOP_WS (8) / LOOP_CONV_WS (15) triggers.
- [x] 4 deadlock: Controller.scala:552-559. nm_ex_quiet removed (redundant: blocked meta + !RS.busy already proves
      no preload can pop). 8-bit counter, asserts at 255 cycles. FIFO depth comment at ExecuteController.scala:200-203.
- [x] 5 a_hi comment: ExecuteController.scala:306 (one line).
- [x] 7 header: GemminiConfigs.scala:523-527 HAS_NM_SPARSITY / GEMMINI_HW_NM_N / GEMMINI_HW_NM_M.
- [x] 8 dense: Controller.scala:528-530 (funct 26), ExecuteController.scala:625-628 (full config_ex rs1[10]);
      duplicate EX nm_meta_in assert removed.
- [x] cleanup: unused nm_n / nm_m removed (GemminiConfigs.scala:120); comments shortened in EX, PE, MeshWithDelays.
- sbt compile after all edits: [success] (only pre-existing warnings).
