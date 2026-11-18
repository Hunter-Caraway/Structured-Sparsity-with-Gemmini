// dense benchmark for berkeley's unmodified gemmini (GemminiRocketConfig): the dense loops of fair_perf.c plus a
// bias variant, on the same 64x128x32 full-range int8 matmul with weights pruned NM_N:NM_M (build -DNM_N=2 -DNM_M=4).
// every variant runs once untimed (warm-up) and once timed; outputs and accumulator are poisoned before each run,
// and every gemmini result is checked against a cpu reference. it issues no sparse-mode instruction.

#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include "include/gemmini_testutils.h"
#include "include/gemmini_counter.h"
#include "include/gemmini_nm.h"   // only the plain c helpers nm_prune / nm_ref_dense

#define NM_I (4*DIM)
#define NM_K (8*DIM)
#define NM_J (2*DIM)
#define IT (NM_I / DIM)
#define KT (NM_K / DIM)
#define JT (NM_J / DIM)

static elem_t a[NM_I][NM_K] row_align(1);
static elem_t w[NM_K][NM_J] row_align(1);
static acc_t c_out[NM_I][NM_J] row_align_acc(1);
static acc_t gold[NM_I][NM_J];
static acc_t gold_bias[NM_I][NM_J];
static acc_t poison_tile[DIM][DIM] row_align_acc(1);
#define POISON ((acc_t)0x5A5A5A5A)

#define A_SP(it, kt) (((kt) % 2) * BANK_ROWS + ((it) * (KT / 2) + (kt) / 2) * DIM)
#define W_SP(kt, jt) (2 * BANK_ROWS + ((kt) * JT + (jt)) * DIM)
#define ACC_BIT ((uint32_t)1 << (ADDR_LEN - 1))
#define ACCUM_BIT ((uint32_t)1 << (ADDR_LEN - 2))
#define FULL_BIT ((uint32_t)1 << (ADDR_LEN - 3))
#define C_ACC(it, jt) (((it) * JT + (jt)) * DIM)

static int cpu_only = 0;
static int quiet = 0;
static int bias = 0;
#define SINK(x, y) asm volatile ("" :: "r"((uint64_t)(x)), "r"((uint64_t)(y)))
#define PRELOAD(b, c) do { if (cpu_only) SINK(b, c); else { gemmini_preload(b, c); } } while (0)
#define COMPUTE_PRE(a, bd) do { if (cpu_only) SINK(a, bd); else { gemmini_compute_preloaded(a, bd); } } while (0)
#define COMPUTE_ACC(a, bd) do { if (cpu_only) SINK(a, bd); else { gemmini_compute_accumulated(a, bd); } } while (0)

static const int ctr_ids[8] = {
  EXE_ACTIVE_CYCLE, RESERVATION_STATION_FULL_CYCLES, EXE_CONTROL_Q_BLOCK_CYCLE, EXE_OVERLAP_HAZ_CYCLE,
  SCRATCHPAD_A_WAIT_CYCLE, SCRATCHPAD_B_WAIT_CYCLE, SCRATCHPAD_D_WAIT_CYCLE, MAIN_EX_CYCLES
};
static const char * ctr_names[8] = {
  "ex_active", "rs_full", "ctrl_q_block", "overlap_haz",
  "spad_a_wait", "spad_b_wait", "spad_d_wait", "main_ex"
};
static uint32_t ctr_vals[8];
static void ctr_start() { counter_reset(); for (int i = 0; i < 8; i++) counter_configure(i, ctr_ids[i]); }
static void ctr_stop() { counter_snapshot_take(); for (int i = 0; i < 8; i++) ctr_vals[i] = counter_read(i); counter_snapshot_reset(); }
static void report(const char * name, uint64_t start, uint64_t issued, uint64_t end, int pairs) {
  if (quiet) return;
  printf("%-14s total %6llu  cpu_issue_done %6llu  pairs %3d  cyc/pair %4llu |",
    name, (unsigned long long)(end - start), (unsigned long long)(issued - start), pairs,
    (unsigned long long)((end - start) / pairs));
  for (int i = 0; i < 8; i++) printf(" %s=%u", ctr_names[i], ctr_vals[i]);
  printf("\n");
}

static void store_c(void) {
  gemmini_config_st(NM_J * sizeof(acc_t));
  for (int it = 0; it < IT; it++)
    for (int jt = 0; jt < JT; jt++)
      gemmini_mvout(&c_out[it * DIM][jt * DIM], ACC_BIT | FULL_BIT | C_ACC(it, jt));
  gemmini_fence();
}
static void poison(void) {
  for (int y = 0; y < NM_I; y++)
    for (int x = 0; x < NM_J; x++) c_out[y][x] = POISON;
  gemmini_config_ld(DIM * sizeof(acc_t));
  for (int it = 0; it < IT; it++)
    for (int jt = 0; jt < JT; jt++) gemmini_mvin(&poison_tile[0][0], ACC_BIT | C_ACC(it, jt));
  gemmini_fence();
}
static int check(const char * name, acc_t ref[NM_I][NM_J], int silent) {
  store_c();
  for (int y = 0; y < NM_I; y++)
    for (int x = 0; x < NM_J; x++)
      if (c_out[y][x] != ref[y][x]) {
        printf("%s%s mismatch at (%d,%d): got %d want %d\n", name, silent ? " (warm-up)" : "", y, x, c_out[y][x], ref[y][x]);
        return 1;
      }
  if (!silent) printf("%s matches the cpu reference (%d values)\n", name, NM_I * NM_J);
  return 0;
}
// the accumulator must read back as poison after poison(), or the poisoning proves nothing
static int poison_selftest(void) {
  poison();
  for (int y = 0; y < NM_I; y++)
    for (int x = 0; x < NM_J; x++) c_out[y][x] = 0;
  store_c();
  for (int y = 0; y < NM_I; y++)
    for (int x = 0; x < NM_J; x++)
      if (c_out[y][x] != POISON) { printf("poison did not reach the accumulator at (%d,%d); berkeley_dense_perf FAILED\n", y, x); return 1; }
  printf("poison reaches the accumulator (%d values)\n", NM_I * NM_J);
  return 0;
}

// with bias set, each pair adds the A tile (it, kt^1) as its D operand
static void run_dense(const char * name) {
  gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0);
  gemmini_fence();
  ctr_start();
  uint64_t start = read_cycles();
  for (int it = 0; it < IT; it++)
    for (int jt = 0; jt < JT; jt++)
      for (int kt = 0; kt < KT; kt++) {
        uint32_t c = ACC_BIT | (kt > 0 ? ACCUM_BIT : 0) | C_ACC(it, jt);
        PRELOAD(W_SP(kt, jt), c);
        COMPUTE_PRE(A_SP(it, kt), bias ? A_SP(it, kt ^ 1) : GARBAGE_ADDR);
      }
  uint64_t issued = read_cycles();
  gemmini_fence();
  uint64_t end = read_cycles();
  ctr_stop();
  report(name, start, issued, end, IT * JT * KT);
}
static void run_reuse(const char * name) {
  const int blocks = JT * KT;
  gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0);
  gemmini_fence();
  ctr_start();
  uint64_t start = read_cycles();
  for (int b = 0; b < blocks; b++) {
    const int jt = b / KT, kt = b % KT;
    for (int it = 0; it < IT; it++) {
      uint32_t c = ACC_BIT | (kt > 0 ? ACCUM_BIT : 0) | C_ACC(it, jt);
      if (it == 0) { PRELOAD(W_SP(kt, jt), c); }
      else { PRELOAD(GARBAGE_ADDR, c); }
      if (it == 0) { COMPUTE_PRE(A_SP(it, kt), GARBAGE_ADDR); }
      else { COMPUTE_ACC(A_SP(it, kt), GARBAGE_ADDR); }
    }
  }
  uint64_t issued = read_cycles();
  gemmini_fence();
  uint64_t end = read_cycles();
  ctr_stop();
  report(name, start, issued, end, blocks * IT);
}

// untimed warm-up, then the timed run; gemmini runs are poisoned first and checked after both passes
static int run(void (*variant)(const char *), const char * name, acc_t ref[NM_I][NM_J]) {
  int fails = 0;
  if (!cpu_only) poison();
  quiet = 1;
  variant(name);
  quiet = 0;
  if (!cpu_only) { fails += check(name, ref, 1); poison(); }
  variant(name);
  if (!cpu_only) fails += check(name, ref, 0);
  return fails;
}

int main() {
  printf("berkeley_dense_perf: unmodified gemmini, %d:%d pruned weights, i=%d k=%d j=%d\n", NM_N, NM_M, NM_I, NM_K, NM_J);
  gemmini_flush(0);
  for (int y = 0; y < NM_I; y++)
    for (int z = 0; z < NM_K; z++)
      a[y][z] = (rand() % 256) - 128;
  for (int z = 0; z < NM_K; z++)
    for (int x = 0; x < NM_J; x++)
      w[z][x] = (rand() % 256) - 128;
  for (int y = 0; y < DIM; y++)
    for (int x = 0; x < DIM; x++) poison_tile[y][x] = POISON;
  nm_prune(NM_K, NM_J, &w[0][0], NM_J, NM_N, NM_M);
  nm_ref_dense(NM_I, NM_K, NM_J, &a[0][0], NM_K, &w[0][0], NM_J, &gold[0][0], NM_J);
  // bias reference: every pair adds a[y][(kt^1)*DIM + x%DIM], and kt^1 runs over every kt once
  for (int y = 0; y < NM_I; y++)
    for (int x = 0; x < NM_J; x++) {
      acc_t s = gold[y][x];
      for (int kt = 0; kt < KT; kt++) s += a[y][kt * DIM + x % DIM];
      gold_bias[y][x] = s;
    }

  gemmini_config_ld(NM_K * sizeof(elem_t));
  for (int it = 0; it < IT; it++)
    for (int kt = 0; kt < KT; kt++)
      gemmini_mvin(&a[it * DIM][kt * DIM], A_SP(it, kt));
  gemmini_config_ld(NM_J * sizeof(elem_t));
  for (int kt = 0; kt < KT; kt++)
    for (int jt = 0; jt < JT; jt++)
      gemmini_mvin(&w[kt * DIM][jt * DIM], W_SP(kt, jt));
  gemmini_fence();

  int fails = poison_selftest();
  fails += run(run_dense, "dense", gold);
  bias = 1;
  fails += run(run_dense, "dense_bias", gold_bias);
  bias = 0;
  fails += run(run_reuse, "dense_reuse", gold);

  printf("cpu only (no gemmini instructions issued):\n");
  cpu_only = 1;
  run(run_dense, "cpu_dense", gold);
  run(run_reuse, "cpu_dense_reuse", gold);
  cpu_only = 0;

  if (fails) { printf("berkeley_dense_perf FAILED\n"); exit(1); }
  printf("berkeley_dense_perf passed\n");
  exit(0);
}
