// micro2.c (micro.c + tight-issue cases; main runs only those):\n// micro.c: execute-unit microbenchmark for the n:m sparse Gemmini (investigation of the streaming result).
// All operands already sit in the scratchpad, so DRAM is out of the picture. Each case issues NC compute
// instructions as blocks of TI computes that share one real preload (TI=1: every compute has its own weights;
// TI=8: the streaming tiler's weight reuse). The values are junk: only the timing matters.
//   dense         preload W (bank 2) + compute A (bank 0), DIM-deep K per compute
//   sp_same       sparse, a_lo and a_hi in the SAME bank (what tiled_matmul_nm does: a_hi = a_lo + DIM rows)
//   sp_diff       sparse, a_lo in bank 0, a_hi in bank 1 (what fair_perf.c does)
//   sp_diff_cold  sp_diff, but every index tile is a different one, read from DRAM after an L2 eviction
//   sp_diff_b4    sp_diff_cold, index tiles sent in batches of 4 ahead (like tiled_matmul_nm)
// sparse cases send each real preload's index tile right before it (warm cases reuse one packed tile).
// prints: total cycles to the fence, ex_active, and cycles per compute.
// build: -DNM_N/-DNM_M. -DDENSE_ONLY: only the dense case (stock chip; a volatile flag, .text identical).
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include "include/gemmini_testutils.h"
#include "include/gemmini_counter.h"
#include "include/gemmini_nm.h"

#ifdef DENSE_ONLY
static volatile int dense_only = 1;
#else
static volatile int dense_only = 0x100;
#endif

#define NC 512
#define NTILE_MAX NC
#define MW (2 * ((DIM + 2 * (64 / (DIM * NM_LOG2_M)) - 1) / (2 * (64 / (DIM * NM_LOG2_M)))))
#define JUNK_BYTES (2u << 20)
static uint64_t meta_cold[NTILE_MAX][MW] __attribute__((aligned(64)));
static uint64_t meta_warm[MW] __attribute__((aligned(64)));
static elem_t junk[JUNK_BYTES] __attribute__((aligned(64)));
static elem_t fill[4 * DIM][DIM] row_align(1);

#define NCTR 6
static const int ctr_ids[NCTR] = { EXE_ACTIVE_CYCLE, EXE_PRELOAD_HAZ_CYCLE, EXE_OVERLAP_HAZ_CYCLE,
  SCRATCHPAD_A_WAIT_CYCLE, SCRATCHPAD_B_WAIT_CYCLE, RESERVATION_STATION_ACTIVE_CYCLES };
static const char * ctr_names[NCTR] = { "ex_active", "pre_haz", "overlap_haz", "spA_wait", "spB_wait", "rs_busy" };

static void evict_l2(void) {
  gemmini_config_ld(MAX_BLOCK_LEN * DIM);
  for (uint32_t off = 0; off < JUNK_BYTES; off += DIM * MAX_BLOCK_LEN * DIM)
    gemmini_extended_mvin(junk + off, 3 * BANK_ROWS + (off / DIM) % BANK_ROWS, MAX_BLOCK_LEN * DIM, DIM);
  gemmini_fence();
}

enum { DENSE, SP_SAME, SP_DIFF, SP_DIFF_COLD, SP_DIFF_B4 };
static const char * case_names[] = { "dense", "sp_same", "sp_diff", "sp_diff_cold", "sp_diff_b4" };

// ---- tight issue: every command's rs1/rs2 precomputed into ops[] (L1-hot), issued with 2 loads + 1 rocc each.
// TI = 8 only. dense: per tile 8 x (preload, compute). sparse: + the tile's index rows (warm, MW/2 cmds) first.
#define T_TI 8
static uint64_t ops[NC * 2 * 2 + (NC / T_TI) * MW] __attribute__((aligned(64)));
#define RI(f, p) ROCC_INSTRUCTION_RS1_RS2(XCUSTOM_ACC, (p)[0], (p)[1], f)
static void tight(int cs) {
  const uint32_t acc = (uint32_t)1 << (ADDR_LEN - 1), accum = (uint32_t)1 << (ADDR_LEN - 2);
  const int sparse = cs != DENSE, ntile = NC / T_TI;
  size_t n = 0;
  for (int t = 0; t < ntile; t++) {
    if (sparse) for (int w = 0; w < MW; w++) ops[n++] = meta_warm[w];
    const uint32_t wad = 2 * BANK_ROWS + (t % 64) * DIM;
    for (int i = 0; i < T_TI; i++) {
      const uint32_t c = acc | accum | (uint32_t)(((t * T_TI + i) % 32) * DIM);
      const uint32_t a = (uint32_t)(((t * T_TI + i) % 128) * 2 * DIM);
      const uint32_t b = !sparse ? GARBAGE_ADDR : cs == SP_SAME ? a + DIM : BANK_ROWS + a;
      const uint64_t sz = ((uint64_t)DIM << (ADDR_LEN + 16)) | ((uint64_t)DIM << ADDR_LEN);
      ops[n++] = sz | (i == 0 ? wad : GARBAGE_ADDR); ops[n++] = sz | c;  // preload
      ops[n++] = sz | a; ops[n++] = sz | b;                               // compute
    }
  }
  if (sparse) { gemmini_nm_reset(); gemmini_nm_config_ex(1, NO_ACTIVATION, 0, ACC_SCALE_IDENTITY, 1, 1); }
  else { gemmini_fence(); gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0); }
  gemmini_fence();
  counter_reset();
  for (int i = 0; i < NCTR; i++) counter_configure(i, ctr_ids[i]);
  const uint64_t t0 = read_cycles();
  const uint64_t * p = ops;
  for (int t = 0; t < ntile; t++) {
    if (sparse) { for (int w = 0; w < MW; w += 2) { RI(k_NM_META, p); p += 2; } }
    RI(k_PRELOAD, p); RI(k_COMPUTE_PRELOADED, p + 2); p += 4;
#pragma GCC unroll 8
    for (int i = 1; i < T_TI; i++) { RI(k_PRELOAD, p); RI(k_COMPUTE_ACCUMULATE, p + 2); p += 4; }
  }
  const uint64_t t1 = read_cycles();
  gemmini_fence();
  const uint64_t t2 = read_cycles();
  uint32_t v[NCTR];
  for (int i = 0; i < NCTR; i++) v[i] = counter_read(i);
  if (sparse) { gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0); }
  printf("micro case=%s_tight TI=%d computes=%d total=%llu issue=%llu cyc_per_compute_x100=%llu", case_names[cs], T_TI, NC,
         (unsigned long long)(t2 - t0), (unsigned long long)(t1 - t0), (unsigned long long)((t2 - t0) * 100 / NC));
  for (int i = 0; i < NCTR; i++) printf(" %s=%u", ctr_names[i], v[i]);
  printf("\n");
}

static void one(int cs, int TI) {
  const uint32_t acc = (uint32_t)1 << (ADDR_LEN - 1), accum = (uint32_t)1 << (ADDR_LEN - 2);
  const int sparse = cs != DENSE, ntile = NC / TI;
  if (cs == SP_DIFF_COLD || cs == SP_DIFF_B4) evict_l2();
  if (sparse) { gemmini_nm_reset(); gemmini_nm_config_ex(1, NO_ACTIVATION, 0, ACC_SCALE_IDENTITY, 1, 1); }
  else { gemmini_fence(); gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0); }
  gemmini_fence();
  counter_reset();
  for (int i = 0; i < NCTR; i++) counter_configure(i, ctr_ids[i]);
  const uint64_t t0 = read_cycles();
  for (int t = 0; t < ntile; t++) {
    if (cs == SP_DIFF_B4) {
      if (t % 4 == 0) for (int u = t; u < t + 4 && u < ntile; u++) nm_send_meta(meta_cold[u], NM_M);
    } else if (cs == SP_DIFF_COLD) { nm_send_meta(meta_cold[t], NM_M); }
    else if (sparse) { nm_send_meta(meta_warm, NM_M); }
    const uint32_t w = 2 * BANK_ROWS + (t % 64) * DIM;
    for (int i = 0; i < TI; i++) {
      const uint32_t c = acc | accum | (uint32_t)(((t * TI + i) % 32) * DIM);
      const uint32_t a = (uint32_t)(((t * TI + i) % 128) * 2 * DIM);
      const uint32_t ahi = cs == SP_SAME ? a + DIM : BANK_ROWS + a;
      if (i == 0) { gemmini_extended_preload(w, c, DIM, DIM, DIM, DIM); }
      else { gemmini_extended_preload(GARBAGE_ADDR, c, DIM, DIM, DIM, DIM); }
      if (sparse) {
        if (i == 0) { gemmini_extended_compute_preloaded(a, ahi, DIM, DIM, DIM, DIM); }
        else { gemmini_extended_compute_accumulated(a, ahi, DIM, DIM, DIM, DIM); }
      } else {
        if (i == 0) { gemmini_extended_compute_preloaded(a, GARBAGE_ADDR, DIM, DIM, DIM, DIM); }
        else { gemmini_extended_compute_accumulated(a, GARBAGE_ADDR, DIM, DIM, DIM, DIM); }
      }
    }
  }
  const uint64_t t1 = read_cycles();
  gemmini_fence();
  const uint64_t t2 = read_cycles();
  uint32_t v[NCTR];
  for (int i = 0; i < NCTR; i++) v[i] = counter_read(i);
  if (sparse) { gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0); }
  printf("micro case=%s TI=%d computes=%d total=%llu issue=%llu cyc_per_compute_x100=%llu", case_names[cs], TI, NC,
         (unsigned long long)(t2 - t0), (unsigned long long)(t1 - t0), (unsigned long long)((t2 - t0) * 100 / NC));
  for (int i = 0; i < NCTR; i++) printf(" %s=%u", ctr_names[i], v[i]);
  printf("\n");
}

int main(void) {
  gemmini_flush(0);
  for (int y = 0; y < 4 * DIM; y++) for (int x = 0; x < DIM; x++) fill[y][x] = (elem_t)(y * 7 + x * 3 - 50);
  for (int t = 0; t < NTILE_MAX; t++) for (int w = 0; w < MW; w++) meta_cold[t][w] = 0x9249249249249249ULL * (t + w + 1) & ~0ULL;
  for (int w = 0; w < MW; w++) meta_warm[w] = 0x1B1B1B1B1B1B1B1BULL;
  // fill banks 0..2 (A lo, A hi, W) with data so nothing reads uninitialised rows (verilator would not care)
  gemmini_config_ld(DIM * sizeof(elem_t));
  for (uint32_t b = 0; b < 3; b++)
    for (uint32_t r = 0; r < 4096 && r < BANK_ROWS; r += 4 * DIM)
      for (int q = 0; q < 4; q++) gemmini_mvin(&fill[q * DIM][0], b * BANK_ROWS + r + q * DIM);
  gemmini_fence();
  printf("micro: DIM=%d BANK_ROWS=%d NM=%d:%d MW=%d dense_only=%d\n", DIM, BANK_ROWS, NM_N, NM_M, (int)MW, dense_only & 1);
  for (int rep = 0; rep < 2; rep++) {
    if (rep == 1) printf("(measured follows)\n");
    tight(DENSE);
    if (!(dense_only & 1)) { tight(SP_SAME); tight(SP_DIFF); }
  }
  printf("micro done\n");
  exit(0);
}
