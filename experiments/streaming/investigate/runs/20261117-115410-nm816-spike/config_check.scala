for ((nm, c) <- Seq(("24", gemmini.GemminiConfigs.nmSparseConfig), ("48", gemmini.GemminiConfigs.nm48SparseConfig), ("816", gemmini.GemminiConfigs.nm816SparseConfig))) {
  println(s"CFG $nm nm=${c.nm_sparsity} idx_bits=${c.nm_idx_bits} tile_bits=${c.nm_tile_bits} sp_width=${c.sp_width} rows_per_tile=${c.nm_spad_rows_per_tile} sp_bank_entries=${c.sp_bank_entries}")
  val h = new java.io.PrintWriter(s"/tmp/claude-1000/-home-hunter-gemmini-sparsity/c2ce7f25-ac80-46aa-8371-9d0155d847ad/scratchpad/gemmini_params_$nm.h"); h.write(c.generateHeader()); h.close()
}
