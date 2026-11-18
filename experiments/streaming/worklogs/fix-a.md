# Fix A worklog (RTL agent): index tiles read from the scratchpad

Started 2026-11-11. Spec: `fix-a-spec.md` (same folder, FROZEN). Edits only under `~/chipyard/generators/gemmini/src/`.
Base: gemmini `sparse-nm` @ 639a5068 plus the uncommitted protocol fixes of the 2026-11-03 round (kept, not reverted).
Nothing committed, stashed or reset. No make in sims/, no Verilator, no Verilog.

## Plan
1. Spec first (fix-a-spec.md), freeze it.
2. GemminiConfigs.scala: rows-per-tile constant, fifo depth constant, header define, require(ex_read_from_spad).
3. Controller.scala: route funct 26 rd == 2 into the reservation station; rd >= 3 reserved; program-order model of
   the index fifo (same as Spike) for the protocol asserts; 4th input on the completion arbiter; busy while a load
   is outstanding.
4. ReservationStation.scala: rd == 2 is an ex-queue command reading rows [addr, addr + n*R) (RAW after mvins, WAR
   before later mvins).
5. ExecuteController.scala: divert rd == 2 at io.cmd into a 4-deep side queue (never enters the in-order cmd
   queue); loader issues one spad read per free bank cycle (lowest priority), per-bank owner queues tell its
   responses apart, writes 128-bit chunks into the existing row assembler, reserves a fifo slot per tile, completes
   its ROB entry when all tiles are in the fifo.
6. sbt compile.

## Progress (all done)
- [x] spec written and frozen: fix-a-spec.md
- [x] GemminiConfigs.scala:119 require(ex_read_from_spad); :127-131 nm_tile_bits / nm_spad_rows_per_tile (4 for 2:4,
      6 for 4:8) / nm_meta_fifo_depth = 4; :533 header `GEMMINI_HW_NM_SPAD_ROWS_PER_TILE`
- [x] ReservationStation.scala:195-199 funct_is_nm_ld (constant false on dense builds) + nm_ld_rows; :226,:233-235 op1
      = index rows; :244,:250-251 op2 = copy of op1 (deps read opb.bits without checking valid); :324-325 is_ex
- [x] Controller.scala:444-445 arbiter 4 inputs on nm builds; :457-461 in(3) <> ex nm_ld_completed;
      :543-553 dispatch: rd==2 -> RS alloc, rd 3..31 assert + drop; :578-649 program-order model + all section-7
      asserts (nm_q, nm_in_flight, nm_mode, nm_ld_since_clear, nm_ld_pending) and io.busy while a load is pending
- [x] ExecuteController.scala:26-30 new IO (nm_ld_completed, nm_reg_tile, nm_asm_busy); :76-100 rd==2 diverted at
      io.cmd into nm_ld_q (4 deep); :236 depth from config; :241-247 loader<->assembler wires; :260-268 chunk write into
      the flat assembler; :270-293 enq mux (loader owns enq while busy, register push waits); :537 nm_op_rd per bank;
      :962-963 readValid hides loader responses; :1161-1243 the loader (owner queues, reservation, completion,
      internal asserts, require(!hasIm2Col))

## Checks run
- sbt `;project gemmini; compile` (chipyard launcher, conda java 20): [success], 4 sources, only pre-existing warnings.
  Re-run after the last edit: [success].
- Scratch-only CHIRRTL elaboration (in memory, written to the scratchpad; ExecuteController and ReservationStation
  standalone with GemminiConfigs.defaultConfig / nmSparseConfig / nm48SparseConfig): all 6 OK, no new Chisel warnings.
- firtool `--ir-hw` (HW dialect IR to the scratchpad, NOT Verilog) on EX dense/2:4/4:8 and RS: rc 0, so no
  uninitialized sinks and no combinational loops in those modules.
- Dense EX: 0 loader instances (owner queues / nm_ld_q / loader asserts absent); 2:4 EX +1558 regs vs dense EX in IR
  (that count includes the earlier n:m state, not just Fix A).
- NOT run: full-SoC elaboration (would cover Controller.scala). It writes gemmini_params.h relative to the CWD, so I
  tried it from a scratch CWD; the permission classifier denied it. Controller changes are type-checked by sbt and
  reviewed by hand only. First real elaboration happens at the server rebuild.

## Notes for the Spike/C agent (also in the spec)
- 4:8 spad packing is NOT nm_pack_meta (tight 48-bit rows, 96 B/tile, 6 rows); 2:4 is identical to nm_pack_meta.
- LOAD rows must be in one bank; rd 3..31 now reserved; PUSH after LOAD needs a CLEAR in between.
- New RTL asserts mirror Spike's existing aborts (preload with no tile, clear between preload and compute).

## Open questions
- Should the loader get a perf counter (cycles active / cycles waiting for a free port)? Not added (needs a new
  CounterEvent id, Berkeley file).
- Timing: the loader's issue depends on the operand logic's per-bank request (nm_op_rd), adding a 2:1 mux and an AND
  on the EX->SRAM read request path. Worth checking in the area/timing run.
