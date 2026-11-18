// scratch-only: one illegal use per build (-DNEG=n); Spike must abort with the fix-b-spec.md 2.5.6 text
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include "include/gemmini_testutils.h"
#include "include/gemmini_nm.h"

static elem_t a[DIM][2 * DIM] row_align(1);
static elem_t wc[DIM][DIM] row_align(1);
static uint8_t meta[4][NM_META_SPAD_BYTES] __attribute__((aligned(64)));
static acc_t c_out[DIM][DIM] row_align_acc(1);
static uint64_t regs[2 * DIM];
static nm_idx_t zidx[DIM][DIM];

#define RAW(f, x, y) ROCC_INSTRUCTION_RS1_RS2(XCUSTOM_ACC, (uint64_t)(x), (uint64_t)(y), f)
// LOOP_WS of I x J x K tiles; rs1 extra bits r1, rs2 bits r2; cfg: issue funct 28 with (c1, c2)
static void loop(int I, int J, int K, int padK, uint64_t r1, uint64_t r2, int cfg, uint64_t c1, uint64_t c2) {
  RAW(k_LOOP_WS_CONFIG_BOUNDS, (uint64_t)padK << 32, ((uint64_t)K << 32) | ((uint64_t)J << 16) | I);
  RAW(k_LOOP_WS_CONFIG_ADDRS_AB, a, wc);
  RAW(k_LOOP_WS_CONFIG_ADDRS_DC, 0, c_out);
  RAW(k_LOOP_WS_CONFIG_STRIDES_AB, 2 * DIM, DIM);
  RAW(k_LOOP_WS_CONFIG_STRIDES_DC, 0, DIM);
  if (cfg) RAW(k_LOOP_WS_CONFIG_NM, c1, c2);
  RAW(k_LOOP_WS, r1 | 2, r2);
}
#define NMB ((uint64_t)1 << 3)

int main(void) {
  gemmini_flush(0);
  gemmini_nm_reset();
  gemmini_extended_config_st(DIM * sizeof(acc_t), NO_ACTIVATION, ACC_SCALE_IDENTITY);
  gemmini_extended3_config_ld(2 * DIM, MVIN_SCALE_IDENTITY, false, 0);
  gemmini_extended3_config_ld(DIM, MVIN_SCALE_IDENTITY, false, 1);
  gemmini_extended3_config_ld(DIM * sizeof(acc_t), MVIN_SCALE_IDENTITY, false, 2);
#if NEG == 1 || NEG == 4
  gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0);
#elif NEG == 14
  gemmini_nm_config_ex(1, NO_ACTIVATION, 0, ACC_SCALE_IDENTITY, 1, 2);
#else
  gemmini_nm_config_ex(1, NO_ACTIVATION, 0, ACC_SCALE_IDENTITY, 1, 1);
#endif
#if NEG == 0     // legal
  loop(1, 1, 2, 0, NMB, 0, 1, (uint64_t)meta, 0);
#elif NEG == 1   // N1 flag without sparse mode
  loop(1, 1, 2, 0, NMB, 0, 1, (uint64_t)meta, 0);
#elif NEG == 2   // N2
  RAW(k_LOOP_CONV_WS, 0, 0);
#elif NEG == 3   // N3
  loop(1, 1, 2, 0, NMB, 0, 0, 0, 0);
#elif NEG == 4   // N4
  loop(1, 1, 2, 0, 0, 0, 1, (uint64_t)meta, 0);
#elif NEG == 5   // N5 zero
  loop(1, 1, 2, 0, NMB, 0, 1, 0, 0);
#elif NEG == 6   // N5 unaligned
  loop(1, 1, 2, 0, NMB, 0, 1, (uint64_t)meta + 8, 0);
#elif NEG == 7   // N5 rs2
  loop(1, 1, 2, 0, NMB, 0, 1, (uint64_t)meta, 1);
#elif NEG == 8   // N6 odd K
  loop(1, 1, 3, 0, NMB, 0, 1, (uint64_t)meta, 0);
#elif NEG == 9   // N6 pad_K
  loop(1, 1, 2, 1, NMB, 0, 1, (uint64_t)meta, 0);
#elif NEG == 10  // N7 A_transpose
  loop(1, 1, 2, 0, NMB, 1, 1, (uint64_t)meta, 0);
#elif NEG == 11  // N7 B_transpose
  loop(1, 1, 2, 0, NMB, 2, 1, (uint64_t)meta, 0);
#elif NEG == 12  // N7 resadd
  loop(1, 1, 2, 0, NMB, 4, 1, (uint64_t)meta, 0);
#elif NEG == 13  // N7 low_D
  loop(1, 1, 2, 0, NMB | 4, 0, 1, (uint64_t)meta, 0);
#elif NEG == 26  // N7 spad-only
  loop(1, 1, 2, 0, NMB, 0x200, 1, (uint64_t)meta, 0);
#elif NEG == 14  // N8
  loop(1, 1, 2, 0, NMB, 0, 1, (uint64_t)meta, 0);
#elif NEG == 15  // N9 does not fit
  loop(30, 1, 20, 0, NMB, 0, 1, (uint64_t)meta, 0);
#elif NEG == 16  // N10 tile pending
  nm_pack_meta(&zidx[0][0], DIM, DIM, DIM, NM_M, regs); nm_send_meta(regs, NM_M);
  loop(1, 1, 2, 0, NMB, 0, 1, (uint64_t)meta, 0);
#elif NEG == 17  // N12 cols
  gemmini_nm_extended_load_idx(meta, 100, 15, 4);
#elif NEG == 18  // N12 rows 0
  gemmini_nm_extended_load_idx(meta, 100, 16, 0);
#elif NEG == 19  // N12 rows 17
  gemmini_nm_extended_load_idx(meta, 100, 16, 17);
#elif NEG == 20  // N13 accumulator
  gemmini_nm_load_idx(meta, (uint32_t)1 << 31, 4);
#elif NEG == 21  // N13 GARBAGE
  gemmini_nm_load_idx(meta, GARBAGE_ADDR, 4);
#elif NEG == 22  // N13 runs off the scratchpad
  gemmini_nm_load_idx(meta, BANK_NUM * BANK_ROWS - 2, 4);
#elif NEG == 23  // N11 (dense build lib)
  gemmini_nm_load_idx(meta, 100, 4);
#elif NEG == 24  // N14 (dense build lib)
  RAW(k_LOOP_WS_CONFIG_NM, meta, 0);
#elif NEG == 25  // legal CPU-issued LOAD_IDX at the last rows
  gemmini_nm_load_idx(meta, BANK_NUM * BANK_ROWS - 4, 4);
#endif
  gemmini_fence();
  printf("smoke_neg NEG=%d: not caught\n", NEG);
  exit(0);
}
