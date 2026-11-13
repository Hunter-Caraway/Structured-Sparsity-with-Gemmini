# dense-verilog-diff
Question: why does dense GemminiRocketConfig Verilog (fork 0db6cd09) differ from stock (8c3f9923)? Read-only; server diff in ~/fixb/dense-diff (server).

## Findings
- Gemmini.sv: is_nm_meta (funct 0x1A) added; RS alloc_valid gated `& funct != 0x1A`; cmd_q deq_ready `| is_nm_meta`; new assert "NM_META_CMD (funct 26) on a dense build". Controller.scala:536 (47f5f15f8, is_nm_meta), :565 (47f5f15f8 branch), :566-568 (d12b0840f assert). No nm_sparsity guard on the branch itself, only the assert is `if (nm_sparsity.isEmpty)`. Dense behaviour differs only on funct 26 (stock: RS assert; fork: dequeue + fatal).
- ExecuteController.sv: only new assert "config_ex rs1[10] ... dense build" (ExecuteController.scala:681-683, d12b0840f, inside else of nm_sparsity.isDefined) plus renumbered _GEN_*, _RANDOM init packing, line numbers. Reg set identical (checked reg names mod numbering), bag of normalised lines identical except assert/$fatal/_RANDOM.
- MeshWithDelays.sv: 4694 stripped lines = rename only. 2347 removed / 2347 added lines; reg counts equal; normalised line bags equal except _RANDOM init packing. Cause: `case None => mesh.io.in_a := VecInit(shifted(...))` (MeshWithDelays.scala, 01f14010) wraps shifted() so firtool names the shift regs mesh_io_in_a_RegShifted_* instead of RegShifted_*. No new state.
- LoadController.sv 4 lines: assert text `block_stride` -> `ld_block_stride` and line numbers (0db6cd09). ld_sel returns plain regs on dense.
- Others (LoopMatmul*, Mesh, RS, PE, Tile...): @[file:line], assert line numbers, _1 -> _2 temp renames.
## RESUME HERE
Done. Report handed to coordinator.
