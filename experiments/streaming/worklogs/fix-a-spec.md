STATUS: FROZEN (2026-11-11). Semantics below must not change without a changelog entry at the end.

# Fix A spec: N:M index tiles loaded from the scratchpad

Shared contract for the RTL agent (Gemmini `src/`) and the Spike/C agent (libgemmini, gemmini-rocc-tests, benchmarks).
Builds on the protocol already in place (HANDOFF.md section 5: clear, mode latch, legality, FIFO depth 4, a_hi
stride 1, index-before-preload, header macros, dense-build asserts). Nothing in that protocol changes except where
this file says so.

## 1. What changes

Today every index tile is pushed through registers: `NM_META_CMD` (funct 26) with rd == 0 carries two 64-bit words
of index rows, so a tile costs 4 commands (2:4) or 8 commands (4:8), each with two CPU loads.

Fix A adds one sub-command, **LOAD** (funct 26, rd == 2): "read `n` index tiles (1..4) from the scratchpad, starting
at row `addr`, and append them to the index FIFO". Software moves the packed index tiles into the scratchpad with
ordinary `mvin`s, next to the weights. One LOAD per 1..4 tiles replaces 4n or 8n register pushes. The register path
(rd == 0) and the clear (rd == 1) keep working unchanged.

The index FIFO, the row assembler register, the preload pop, the mode latch and the PE side are all unchanged. A
tile from LOAD is indistinguishable from the same tile pushed through registers.

## 2. Instruction encoding

`NM_META_CMD` = funct7 26 on custom-3 (XCUSTOM_ACC), R-type. The **rd field (bits 11:7) is a sub-opcode**; it is not
a destination register. Always xs1 = xs2 = 1, xd = 0 (funct3 = 0x3), so Rocket expects no response.

| rd | name | rs1 | rs2 | status |
|---|---|---|---|---|
| 0 | PUSH | index rows (low word) | index rows (high word) | existing, unchanged |
| 1 | CLEAR | ignored (0) | ignored (0) | existing, unchanged except new assert (section 7) |
| 2 | **LOAD** | see below | see below | **new** |
| 3..31 | reserved | | | **new**: RTL sim-asserts and drops the command; Spike aborts. (Before Fix A these acted as PUSH; no software used them.) |

LOAD operands:

| field | bits | meaning |
|---|---|---|
| `addr` | rs1[31:0] | Gemmini local address of the first index row. Must be a plain scratchpad row number: rs1[31:spAddrBits] == 0, where spAddrBits = log2(sp_banks * sp_bank_entries) = 14 on the 256 KiB, 4-bank, DIM 16 chips (rows 0..16383). Accumulator addresses and GARBAGE_ADDR are illegal. |
| reserved | rs1[63:32] | must be 0 |
| `n` | rs2[7:0] | number of index tiles, 1..4 |
| reserved | rs2[63:8] | must be 0 |

Assembly (software): `.insn r CUSTOM_3, 0x3, 26, x2, <rs1 reg>, <rs2 reg>` (the `x2` is the rd field = 2), the
same form `gemmini_nm_reset()` already uses with `x1`. Suggested C name: `gemmini_nm_load_spad(spad_addr, n)`.

Dense chips (`nm_sparsity = None`): every funct 26, any rd, is illegal. The RTL sim-asserts (existing message
"NM_META_CMD (funct 26) on a dense build (nm_sparsity = None)") and drops it. Software must never issue it there.

## 3. Scratchpad layout of an index tile

Constants (DIM = 16, int8 inputs, so one scratchpad row = 128 bits = 16 bytes):

| | b = log2(M) | bits per index row (DIM*b) | bits per tile (DIM*DIM*b) | bytes per tile | **R = rows per tile** |
|---|---|---|---|---|---|
| 2:4 | 2 | 32 | 512 | 64 | **4** |
| 4:8 | 3 | 48 | 768 | 96 | **6** |

General formula: R = ceil(DIM*DIM*b / (DIM * 8)) (ceil of tile bits over scratchpad row bits). If the tile does not
fill its last row, the unused high bits of that row are ignored (does not happen for DIM 16).
The generated header gains `#define GEMMINI_HW_NM_SPAD_ROWS_PER_TILE <R>` at the next elaboration; until then
software computes R itself.

**Bit packing ("tight", little-endian bit stream).** A tile is one bit string S of DIM*DIM*b bits. Index
`idx[r][c]` (r = row 0..DIM-1 of the preloaded weight tile, c = column 0..DIM-1; value 0..M-1 = position of the kept
weight inside its M-group, exactly as on the register path) occupies bits

    S[p .. p+b-1],  p = (r*DIM + c) * b,  least significant bit of idx at S[p].

S is stored in R consecutive scratchpad rows: bit p of S is bit (p mod 128) of scratchpad row `base + p/128`.
Inside a scratchpad row, bit k is bit (k mod 8) of byte (column) k/8, and byte j of the row is the byte at DRAM
address `src + j` of the `mvin` that wrote it. Equivalently: **the tile in DRAM is S as a little-endian byte array**
(byte i = S[8i .. 8i+7]), 64 B (2:4) or 96 B (4:8), mvin'd as R rows of 16 int8 columns with a 16-byte row stride.

- 2:4: S is byte-for-byte the 8 `uint64_t` words `nm_pack_meta()` already produces (2 rows per word). Reuse it.
- 4:8: **different from `nm_pack_meta()`**, which pads each 48-bit row into its own 64-bit word (16 words). The
  spad format packs rows back to back (12 words). An index can straddle a 128-bit row boundary (example in
  section 9). Software needs a new packer; reference:

```c
// tight packer: out must hold R*16 bytes, zeroed first; rows/cols beyond the valid part stay 0
static void nm_pack_meta_spad(const nm_idx_t *idx, size_t stride, size_t rows, size_t cols, int m, uint8_t *out) {
  const int b = nm_idx_bits(m);
  for (size_t r = 0; r < DIM && r < rows; r++)
    for (size_t c = 0; c < DIM && c < cols; c++) {
      const unsigned v = idx[r * stride + c] & ((1u << b) - 1);
      const size_t p = (r * DIM + c) * b;
      for (int k = 0; k < b; k++)
        if (v >> k & 1) out[(p + k) / 8] |= (uint8_t)(1u << ((p + k) % 8));
    }
}
```

Tile t (0-based) of a LOAD occupies scratchpad rows `addr + t*R .. addr + t*R + R - 1`; the n tiles are back to
back, rows `addr .. addr + n*R - 1`, tile 0 first. Tile t is appended to the FIFO before tile t+1.

**Bank rule.** All n*R rows must lie in one scratchpad bank:
`addr / sp_bank_entries == (addr + n*R - 1) / sp_bank_entries` (sp_bank_entries = 4096 on these chips, so banks
start at rows 0, 4096, 8192, 12288). This also forbids running past the last row. (Reason: the loader keeps its
responses in order per bank.)

**mvin of index rows.** Plain int8 mvins (`gemmini_extended_mvin` / mvin2 / mvin3 with a load config of stride 16
bytes, scale 1, no shrink), cols = 16, rows <= DIM (16) per mvin (Gemmini's mvin row limit), so a 4-tile 4:8 batch
(24 rows) needs two mvins. Edge tiles: pack only the valid part, the rest is 0 (same as `nm_pack_meta`).

## 4. Semantics of LOAD (what Spike implements, in program order)

At a LOAD with operands (addr, n), Spike does, in this order:
1. Legality checks of section 7 (abort on failure).
2. For t = 0..n-1: read rows addr+t*R .. addr+t*R+R-1 of the scratchpad as bytes, form S, decode
   idx[r][c] = S[(r*DIM+c)*b .. +b-1], and push the tile at the back of the index FIFO model.
3. Set `ld_since_clear = true` (see rule P3).

The RTL gives the same result: the LOAD goes through the reservation station as an execute-queue command whose
operand is scratchpad rows [addr, addr + n*R). So it waits for every earlier mvin (or `mvout` to scratchpad) that
writes any of those rows (RAW), and every later mvin that writes any of them waits until the LOAD has read all its
rows (WAR). Spike reading synchronously at the instruction is therefore exact for mvin-written index rows.

Not tracked by the RTL (illegal, undefined result; Spike need not check): index rows that are written by the C
output of a matmul (C to scratchpad) that is still in flight, or overwritten by the C output of a later matmul while
the LOAD is still outstanding. Index rows must come from mvin.

The FIFO is popped exactly as before: each real (non-GARBAGE D) preload issued while sparse mode is on pops the
oldest tile. Tiles enter the FIFO in program order of the PUSH-completed tiles and LOAD tiles.

## 5. Ordering and hazard rules (software contract)

P1. **FIFO accounting (strict, unchanged model).** Keep the existing program-order model: `q` = tiles delivered
    (PUSH tiles completed + LOAD tiles) minus tiles popped by real sparse preloads; `in_flight` = a real sparse
    preload has popped a tile and no compute has been issued since (any compute clears it).
    - At a LOAD with n tiles: require `q + in_flight + n <= 4`; then q += n.
    - At the PUSH that completes a tile: require `q + in_flight + 1 <= 4` (existing check); then q += 1.
    - At a real sparse preload: require q >= 1 ("index tile must be sent before its preload"); q -= 1;
      in_flight = true.
    - At any compute: in_flight = false.
    - At CLEAR: q = 0 (in_flight must be false).
    `NM_META_FIFO_DEPTH` stays 4.
P2. **No half tile.** A LOAD is illegal while a PUSH tile is half sent (some but not all PUSH commands of a tile
    issued). (Spike: `nm_asm_row != 0`.)
P3. **One path per clear.** After a LOAD, a PUSH is illegal until the next CLEAR (`gemmini_nm_reset()`, which fences
    first). PUSH then LOAD (with no half tile) is legal. (Reason: a LOAD waits in the reservation station for its
    mvins while a later PUSH would skip ahead into the FIFO.)
P4. **CLEAR after LOAD needs a fence.** A CLEAR while a LOAD is still outstanding in the hardware (issued, not all
    tiles in the FIFO) is illegal. `gemmini_nm_reset()` fences first, so it always satisfies this. Spike cannot see
    fences and does not check it; the RTL asserts it.
P5. **Not between a preload and its compute.** A LOAD must not be placed between a preload and its paired
    compute; issue it before the preload (or after the compute). Reason: the reservation station issues execute
    commands in order (`ReservationStation.scala:355`), and a preload fires only once its compute is queued
    (`ExecuteController.scala:711`). If the LOAD's index mvin waits behind an mvin that depends on that preload,
    the RTL deadlocks while Spike completes; even without a deadlock it serializes the preload/compute overlap.
    Elsewhere in the stream (e.g. between a compute and the next preload) placement is constrained only by P1..P4.
P6. **Mode.** A LOAD works in either mode; its tiles wait in the FIFO until real sparse preloads pop them (same as
    PUSH). The existing Spike warning for "sparse mode turned off with tiles pending" applies unchanged.
P7. Loops: LOOP_WS / LOOP_CONV_WS remain illegal in sparse mode (unchanged); they never generate funct 26.

## 6. Timing (RTL behaviour; Spike has no timing)

- The LOAD reaches the loader as soon as the reservation station issues it (after its RAW dependences), usually
  several commands before the execute unit gets to the preloads that need it. A side queue holds up to 4 LOADs
  (one active + 3 waiting); under rule P1 at most 4 can be outstanding at a point where it matters, so the side
  queue never blocks the command stream of a legal program.
- The loader reads one row per cycle, **only in cycles where the execute unit's own operand reads do not use that
  bank's read port** (lowest priority; it never takes a cycle an operand read wants, but under read back-pressure an in-flight
  loader read can hold a bank pipeline slot and delay an operand read by about one cycle). Per tile: R reads, plus about
  spad_read_delay + 2 = 6 cycles from the last read to the tile being in the FIFO.
- Before reading the first row of a tile it reserves a FIFO slot (FIFO count + tiles in progress < 4). If the FIFO
  is full it simply waits; it never holds a read response it cannot accept, so it cannot block operand reads.
- The LOAD's reservation-station entry completes when its last tile is in the FIFO. While any LOAD is outstanding,
  Gemmini reports busy (so `gemmini_fence()` waits for it).
- A preload whose tile is not in the FIFO yet waits, as before. To avoid that wait, issue a LOAD a few commands
  before the first preload that needs it, and preferably keep index rows in a bank the overlapping computes do not
  read (the loader only gets cycles that bank is free). Example patterns that satisfy P1:
  - batch of 4: `LOAD(t..t+3)` right after the compute of the preload that popped tile t-1 (q = 0, in_flight = 0);
  - rolling batch of 2: `LOAD(t+2, t+3)` right after compute(t) for even t (q = 1).
- Cost per tile on the CPU side: 1/n RoCC command for the LOAD plus the mvin(s) of index rows (one mvin covers up
  to 16 rows = 4 tiles of 2:4 or 2 tiles of 4:8), instead of 4 (2:4) or 8 (4:8) RoCC commands with 2 loads each.

## 7. Illegal use: RTL sim asserts (Spike must abort on the same conditions unless noted)

All checked in program order at the point the command is dispatched by the controller (Controller.scala).

| condition | RTL assert message | Spike |
|---|---|---|
| funct 26 on a dense build | `NM_META_CMD (funct 26) on a dense build (nm_sparsity = None)` (existing) | n/a (dense) |
| rd in 3..31 | `NM_META_CMD (funct 26): rd values 3..31 are reserved` | abort |
| LOAD, n == 0 or n > 4 | `NM_META_CMD rd == 2: tile count rs2[7:0] must be 1..4` | abort |
| LOAD, rs1[63:32] != 0 or rs2[63:8] != 0 | `NM_META_CMD rd == 2: rs1[63:32] and rs2[63:8] must be 0` | abort |
| LOAD, rs1[31:spAddrBits] != 0 | `NM_META_CMD rd == 2: rs1 must be a scratchpad row address (not accumulator, not GARBAGE)` | abort |
| LOAD, rows cross a bank (or run off the end) | `NM_META_CMD rd == 2: the index rows must all lie in one scratchpad bank` | abort |
| LOAD with a PUSH tile half sent (P2) | `NM_META_CMD rd == 2 while a register-path index tile is half sent` | abort |
| LOAD or PUSH tile over the FIFO budget (P1) | `n:m index fifo: more than 4 index tiles ahead of their preloads` | abort (existing message for PUSH is fine) |
| PUSH after LOAD without CLEAR (P3) | `NM_META_CMD register rows (rd == 0) after a scratchpad index load (rd == 2): gemmini_nm_reset() first` | abort |
| CLEAR while a LOAD is outstanding (P4) | `NM_META_CMD clear (rd == 1) while a scratchpad index load is outstanding: fence first` | not checked |
| CLEAR between a real sparse preload and its compute | `NM_META_CMD clear (rd == 1) between a sparse preload and its compute: fence first` | abort (existing) |
| real sparse preload with q == 0 | `n:m sparse preload with no index tile sent: index tile must be sent before its preload` | abort (existing) |

The three asserts on the last rows mirror checks Spike already has; the RTL gains them because Fix A needs the same
program-order model anyway. Internal RTL consistency asserts (owner queue overflow, FIFO full at enqueue) never
fire in a legal program.

## 8. RTL structure (for reviewers; not part of the software contract)

- Controller: funct 26 rd == 2 goes to the reservation station (rd 0/1 still bypass it). Program-order model of
  section 5 for the asserts. A 4th input on the completion arbiter for the loader. Busy while a LOAD is
  outstanding.
- ReservationStation: LOAD is an ex-queue command with operand rows [addr, addr + n*R).
- ExecuteController: LOAD is diverted at `io.cmd` into a 4-entry side queue (never enters the in-order queue). The
  loader issues reads on free cycles of its bank's read port, tags them in a small per-bank owner queue (so its
  responses are hidden from the operand path), writes each 128-bit response into the existing row assembler
  register at chunk position j (flat bit view), enqueues the tile into the existing index FIFO after chunk R-1, and
  reports the LOAD's ROB id when all n tiles are in. No new tile register, no new SRAM port, no change to the
  preload/compute FSM.

## 9. Worked example (one 16x16 tile)

Index pattern: `idx[r][c] = (3*r + c*c + (r*c)/4) mod M` (integer division), DIM = 16.

### 2:4 (b = 2, R = 4)
idx row 0 = 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1; idx row 2 = 2 3 3 0 0 1 1 2 2 3 3 0 0 1 1 2.
DRAM bytes (64), shown as the 4 scratchpad rows, byte 0 first:

    row base+0: 44 44 44 44 33 44 99 ee 3e 94 3e 94 29 d4 83 7e
    row base+1: 28 28 28 28 d7 28 7d 82 d2 78 d2 78 cd b8 67 12
    row base+2: cc cc cc cc bb cc 11 66 b6 1c b6 1c a1 5c 0b f6
    row base+3: a0 a0 a0 a0 5f a0 f5 0a 5a f0 5a f0 45 30 ef 9a

Check: row 0 byte 0 = idx[0][0..3] = 0,1,0,1 -> 0 | 1<<2 | 0<<4 | 1<<6 = 0x44. idx[2][10] = 3 sits at S bit
(2*16+10)*2 = 84 = scratchpad row base+0, bits 84..85 (byte 10 = 0x3e, bits 4..5 = 0b11). These 64 bytes equal
`nm_pack_meta()` output for the same tile.

### 4:8 (b = 3, R = 6)
idx row 0 = 0 1 4 1 0 1 4 1 0 1 4 1 0 1 4 1; idx row 2 = 6 7 3 0 0 1 5 2 2 3 7 4 4 5 1 6.

    row base+0: 08 83 30 08 83 30 e3 c9 a2 75 ec eb fe 80 54 da
    row base+1: c9 c6 91 c9 e6 07 a5 bd b4 00 99 b4 00 99 4f 47
    row base+2: 0b d9 6b 50 62 0e bd 46 47 2f 3d 47 4f ab 22 06
    row base+3: 18 8e e1 18 8e e1 f3 c4 73 45 e9 b8 ce 8d 05 ea
    row base+4: c4 97 a1 c4 b7 17 a0 6e 84 0d 4a 84 0d 4a 5f 42
    row base+5: d8 e9 66 01 72 0b 6e 56 42 fc 0d 42 1c bb 2f d7

Straddling index: idx[2][10] = 7 = 0b111 starts at S bit (2*16+10)*3 = 126: bits 126, 127 are the top two bits of
row base+0 (byte 15 = 0xda, bits 6..7 = 1,1) and bit 128 is bit 0 of row base+1 (byte 0 = 0xc9, bit 0 = 1).

### Command sequence (2:4, one tile, weight tile W at spad row 0, index tile at spad row 12288 = bank 3)

    gemmini_nm_reset();                                   // fence + funct 26 rd=1
    gemmini_nm_config_ex(1, NO_ACTIVATION, 0, 1, 1, 1);    // sparse on, WS
    gemmini_config_ld(16);                                 // 16-byte DRAM row stride
    gemmini_extended_mvin(W_dram, 0, 16, 16);              // squashed weights, rows 0..15
    gemmini_extended_mvin(idx_dram, 12288, 16, 4);         // the 64 bytes above, rows 12288..12291
    gemmini_nm_load_spad(12288, 1);                        // funct 26 rd=2, rs1 = 12288, rs2 = 1
    preload(W at row 0, C at acc row ...)                  // pops the tile (real sparse preload)
    compute_preloaded(a_lo, a_hi)
    gemmini_fence();

Model state: after the LOAD q = 1; the preload makes q = 0, in_flight = 1; the compute clears in_flight. In the RTL
the LOAD waits in the reservation station until the index mvin completes, is diverted to the loader, reads rows
12288..12291 on free bank-3 cycles, and the tile enters the FIFO; the preload pops it as it fires.

## 10. Alternatives considered

| | design | why not |
|---|---|---|
| **A (chosen)** | funct 26 rd=2 "load n tiles from scratchpad" through the reservation station; diverted at the execute unit's input to a background loader that uses free scratchpad read cycles and fills the existing assembler and FIFO | Small: a 4-entry side queue (~40 bits each), per-bank 1-bit owner queues (10 deep), a few counters, a 2:1 mux per assembler bit, ~12 bits of protocol-model state. Reuses the FIFO, the assembler register and the execute unit's read ports. Preload/compute FSM untouched. |
| B | the preload reads its own index rows (4th operand) | R extra reads per preload compete with the A/a_hi/D reads every preload: a new stall on the preload path. No spare field in preload rs1/rs2 for the address. |
| C | LOAD as an ordinary in-order execute command handled at the queue head | Stalls the array for n*R + ~6 cycles per LOAD. Between a compute and the next preload it breaks their overlap; between a preload and its compute it hides that compute from the RAW check (`raw_hazard_pre` looks at queue head 1). |
| D | mvin straight into the index FIFO (DMA to execute unit) | New DMA response path from Scratchpad to the execute unit and cross-queue ordering; far more Berkeley code touched. |
| E | index base pointer that auto-increments per preload | Reads are not tracked by the reservation station: RAW/WAR against mvins would need software fences. |
| F | register-format packing in the scratchpad (4:8 rows padded to 64 bits, 8 rows/tile) | Lets 4:8 reuse `nm_pack_meta`, but 33% more index bytes and reads for 4:8 (4 vs 3 bits per kept weight; ~9% more weight-side DRAM traffic on the weight-dominated layers). Identical for 2:4. |
| G | deeper FIFO or execute-queue lookahead | Not needed: the loader starts as soon as the reservation station issues the LOAD. Each extra FIFO entry costs DIM*DIM*b flops (512 / 768). |

## Changelog
- 2026-11-11: first version, frozen.
- 2026-11-11 (no software-visible change): the RTL adds `require(!hasIm2Col)` for n:m builds, because im2col shares the
  execute unit's scratchpad read ports. `hasIm2Col` is hard-coded false in GemminiConfigs, so no config changes.
- 2026-11-11 (documentation only, no semantic change to RTL or Spike): P5 reworded; a LOAD must not sit between a
  preload and its paired compute (possible RTL deadlock, else lost preload/compute overlap). Section 6 loader
  wording softened: it can delay an operand read by about one cycle under read back-pressure.
- 2026-11-12 (documentation only, no semantic change): HANDOFF.md was removed from the tree; its section 5 ("Plan for the fix round", which holds the "Shared protocol spec") is now at `git show e06b436:HANDOFF.md`. The "HANDOFF.md section 5" citation in the header refers to that.
