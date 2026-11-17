# loop-bank-check (investigation, read-only)
Claim: sparse LOOP_WS puts a_lo/a_hi in the same spad bank, 2 cycles/row. Result: CONFIRMED by RTL reading [M-code]; array cost in the loop is INFERRED from counters, not isolated.
RTL (branch sparse-loop-fix): LocalAddr.scala:33 bank = high address bits (4 banks x 4096 rows); LoopMatmul.scala:616 a_lo, a_hi=a_lo+block_size (:597 a_hi_tile);
ExecuteController.scala:361 a_hi read via B stream; :426-466 same_bank/must_wait_for/one_ahead -> A and B alternate = 2 cycles/row.
Logs: runs/20261113-160015-fixb-srv nm24.bert_qkv_24_loop (sparse_loop ex_active=290794 total 305747) vs nm24.bert_qkv_24_full (berkeley ex_active=292031 total 317206); fair_perf_24 sparse_loop spad_a_wait=0 spad_b_wait=1340.
investigate.md sec 3/4 (micro2, BANKSPLIT -38% ex_active in tiler).
## RESUME HERE
Done. Next: decide on bank-split micro test on server (needs user approval).
