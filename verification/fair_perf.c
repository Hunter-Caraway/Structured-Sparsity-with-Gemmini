// fair benchmark: every variant gets its own lean, dedicated issue loop, written the same way on every chip.
// one 64x128x32 int8 matmul (full-range data), weights pruned NM_N:NM_M, checked against a cpu reference.
// every variant runs once untimed (warm-up: i-cache, d-cache, branch predictor) and then once timed; the
// outputs and the accumulator are filled with a poison value before each run, so a run that writes nothing fails.
// build with -DNM_N=2 -DNM_M=4 or -DNM_N=4 -DNM_M=8. -DDENSE_ONLY only changes the initial value of the
// volatile build_mode flag, so .text is byte-identical to the full 2:4 build; the dense-only build runs on
// berkeley's unmodified gemmini, and a runtime guard stops it from issuing any sparse-mode instruction.
// variants: dense / dense_reuse (berkeley's loops), sparse / sparse_reuse (the same loops, compressed weights),
// sparse_batched (indexes for up to NM_META_FIFO_DEPTH tiles, then their preload/compute pairs), sparse_spad
// (Fix A: the same batches, but the index tiles were moved into the scratchpad once with the weights and each batch
// is one gemmini_nm_load_spad()), and cpu_* runs of the same loops with no gemmini instructions.
// dense_loop / sparse_loop (sparse-loop-fix): the whole matmul as one LOOP_WS hardware loop, dense and n:m sparse.
// unlike the other variants their timed region also moves A, the weights (and the index rows) in from main memory and
// C out to it, so compare the two with each other only.
// prep_cold / prep_warm time the one-time weight preprocessing.

#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include "include/gemmini_testutils.h"
#include "include/gemmini_counter.h"
#include "include/gemmini_nm.h"

#define NM_I (4*DIM)
#define NM_K (8*DIM)
#define NM_J (2*DIM)
#define IT (NM_I / DIM)
#define KT (NM_K / DIM)
#define JT (NM_J / DIM)
#define KC (NM_K / NM_M * NM_N)
#define KCT (KC / DIM)

// both values are non-zero so the flag sits in .sdata in both builds (a zero would move it to .sbss)
#define MODE_DENSE_ONLY 0x0D
#define MODE_FULL 0x5F
#ifdef DENSE_ONLY
#define BUILD_MODE MODE_DENSE_ONLY
#else
#define BUILD_MODE MODE_FULL
#endif
static volatile int build_mode = BUILD_MODE;

static elem_t a[NM_I][NM_K] row_align(1);
static elem_t w[NM_K][NM_J] row_align(1);
static elem_t wc[KC][NM_J] row_align(1);
static nm_idx_t idx[KC][NM_J];
static uint64_t meta[KCT][JT][2 * DIM];
static uint8_t meta_sp[JT][KCT][NM_META_SPAD_BYTES] row_align(1); // Fix A: scratchpad format, the KCT tiles of a jt back to back
static uint8_t meta_loop[KCT][JT][NM_META_SPAD_BYTES] row_align(1); // sparse-loop-fix: the same tiles in the loop's (k', j) order
static acc_t c_out[NM_I][NM_J] row_align_acc(1);
static acc_t gold[NM_I][NM_J];
static acc_t poison_tile[DIM][DIM] row_align_acc(1);
#define POISON ((acc_t)0x5A5A5A5A)

#define A_SP(it, kt) (((kt) % 2) * BANK_ROWS + ((it) * (KT / 2) + (kt) / 2) * DIM)
#define W_SP(kt, jt) (2 * BANK_ROWS + ((kt) * JT + (jt)) * DIM)
#define WC_SP(t, jt) (3 * BANK_ROWS + ((t) * JT + (jt)) * DIM)
// Fix A index rows: bank 2 (the dense weights' bank, which the sparse runs do not read), above the dense weights
#define IDX_SP(jt, t) (2 * BANK_ROWS + BANK_ROWS / 2 + ((jt) * KCT + (t)) * NM_SPAD_ROWS_PER_TILE)
#define ACC_BIT ((uint32_t)1 << (ADDR_LEN - 1))
#define ACCUM_BIT ((uint32_t)1 << (ADDR_LEN - 2))
#define FULL_BIT ((uint32_t)1 << (ADDR_LEN - 3))
#define C_ACC(it, jt) (((it) * JT + (jt)) * DIM)

static int cpu_only = 0;
// set by a variant whose result is already in c_out (the hardware loops store C themselves)
static int c_in_dram = 0;
static int quiet = 0;
#define SINK(x, y) asm volatile ("" :: "r"((uint64_t)(x)), "r"((uint64_t)(y)))
#define PRELOAD(b, c) do { if (cpu_only) SINK(b, c); else { gemmini_preload(b, c); } } while (0)
#define COMPUTE_PRE(a, bd) do { if (cpu_only) SINK(a, bd); else { gemmini_compute_preloaded(a, bd); } } while (0)
#define COMPUTE_ACC(a, bd) do { if (cpu_only) SINK(a, bd); else { gemmini_compute_accumulated(a, bd); } } while (0)
#define LOAD_SPAD(row, n) do { if (cpu_only) SINK(row, n); else { gemmini_nm_load_spad(row, n); } } while (0)
static inline void send_meta(const uint64_t * packed) {
  if (!cpu_only) { nm_send_meta(packed, NM_M); return; }
  for (int i = 0; i < nm_meta_cmds(NM_M); i++) SINK(packed[2 * i], packed[2 * i + 1]);
}

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

// stops a dense-only build (berkeley's chip) before it issues any sparse-mode instruction
static void need_sparse(const char * name) {
  if (build_mode == MODE_FULL) return;
  printf("%s: sparse run requested in a dense-only build; fair_perf FAILED\n", name);
  exit(3);
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
static int check(const char * name, int silent) {
  if (!c_in_dram) store_c();
  for (int y = 0; y < NM_I; y++)
    for (int x = 0; x < NM_J; x++)
      if (c_out[y][x] != gold[y][x]) {
        printf("%s%s mismatch at (%d,%d): got %d want %d\n", name, silent ? " (warm-up)" : "", y, x, c_out[y][x], gold[y][x]);
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
      if (c_out[y][x] != POISON) { printf("poison did not reach the accumulator at (%d,%d); fair_perf FAILED\n", y, x); return 1; }
  printf("poison reaches the accumulator (%d values)\n", NM_I * NM_J);
  return 0;
}

// ---- dense: berkeley's loops ----
static void dense_fresh(const char * name) {
  gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0);
  gemmini_fence();
  ctr_start();
  uint64_t start = read_cycles();
  for (int it = 0; it < IT; it++)
    for (int jt = 0; jt < JT; jt++)
      for (int kt = 0; kt < KT; kt++) {
        uint32_t c = ACC_BIT | (kt > 0 ? ACCUM_BIT : 0) | C_ACC(it, jt);
        PRELOAD(W_SP(kt, jt), c);
        COMPUTE_PRE(A_SP(it, kt), GARBAGE_ADDR);
      }
  uint64_t issued = read_cycles();
  gemmini_fence();
  uint64_t end = read_cycles();
  ctr_stop();
  report(name, start, issued, end, IT * JT * KT);
}
static void dense_reuse(const char * name) {
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

// ---- sparse: the same loops with the compressed weights and their index tiles ----
static void sparse_begin(const char * name) {
  need_sparse(name);
  gemmini_nm_reset();
  gemmini_nm_config_ex(1, NO_ACTIVATION, 0, ACC_SCALE_IDENTITY, 1, 1);
  gemmini_fence();
}
static void sparse_end(void) {
  gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0);
  gemmini_fence();
}
static void sparse_fresh(const char * name) {
  const int ntiles = IT * JT * KCT;
  sparse_begin(name);
  ctr_start();
  uint64_t start = read_cycles();
  send_meta(meta[0][0]);
  for (int it = 0; it < IT; it++)
    for (int jt = 0; jt < JT; jt++)
      for (int t = 0; t < KCT; t++) {
        uint32_t c = ACC_BIT | (t > 0 ? ACCUM_BIT : 0) | C_ACC(it, jt);
        PRELOAD(WC_SP(t, jt), c);
        // the next tile's indexes go between this preload and its compute
        if (t + 1 < KCT) send_meta(meta[t + 1][jt]);
        else if (jt + 1 < JT) send_meta(meta[0][jt + 1]);
        else if (it + 1 < IT) send_meta(meta[0][0]);
        COMPUTE_PRE(A_SP(it, 2 * t), A_SP(it, 2 * t + 1));
      }
  uint64_t issued = read_cycles();
  gemmini_fence();
  uint64_t end = read_cycles();
  ctr_stop();
  report(name, start, issued, end, ntiles);
  sparse_end();
}
// a tile counts against the fifo until its compute is issued; every batch starts with all earlier computes issued
static void sparse_batched(const char * name) {
  const int ntiles = IT * JT * KCT;
  sparse_begin(name);
  ctr_start();
  uint64_t start = read_cycles();
  for (int it = 0; it < IT; it++)
    for (int jt = 0; jt < JT; jt++)
      for (int t0 = 0; t0 < KCT; t0 += NM_META_FIFO_DEPTH) {
        const int t1 = t0 + NM_META_FIFO_DEPTH < KCT ? t0 + NM_META_FIFO_DEPTH : KCT;
        for (int t = t0; t < t1; t++) send_meta(meta[t][jt]);
        for (int t = t0; t < t1; t++) {
          uint32_t c = ACC_BIT | (t > 0 ? ACCUM_BIT : 0) | C_ACC(it, jt);
          PRELOAD(WC_SP(t, jt), c);
          COMPUTE_PRE(A_SP(it, 2 * t), A_SP(it, 2 * t + 1));
        }
      }
  uint64_t issued = read_cycles();
  gemmini_fence();
  uint64_t end = read_cycles();
  ctr_stop();
  report(name, start, issued, end, ntiles);
  sparse_end();
}
// Fix A: as sparse_batched, but each batch of index tiles is one load from the scratchpad
static void sparse_spad(const char * name) {
  const int ntiles = IT * JT * KCT;
  sparse_begin(name);
  ctr_start();
  uint64_t start = read_cycles();
  for (int it = 0; it < IT; it++)
    for (int jt = 0; jt < JT; jt++)
      for (int t0 = 0; t0 < KCT; t0 += NM_META_FIFO_DEPTH) {
        const int t1 = t0 + NM_META_FIFO_DEPTH < KCT ? t0 + NM_META_FIFO_DEPTH : KCT;
        LOAD_SPAD(IDX_SP(jt, t0), t1 - t0);
        for (int t = t0; t < t1; t++) {
          uint32_t c = ACC_BIT | (t > 0 ? ACCUM_BIT : 0) | C_ACC(it, jt);
          PRELOAD(WC_SP(t, jt), c);
          COMPUTE_PRE(A_SP(it, 2 * t), A_SP(it, 2 * t + 1));
        }
      }
  uint64_t issued = read_cycles();
  gemmini_fence();
  uint64_t end = read_cycles();
  ctr_stop();
  report(name, start, issued, end, ntiles);
  sparse_end();
}
static void sparse_reuse(const char * name) {
  const int blocks = JT * KCT;
  sparse_begin(name);
  ctr_start();
  uint64_t start = read_cycles();
  send_meta(meta[0][0]);
  for (int b = 0; b < blocks; b++) {
    const int jt = b / KCT, t = b % KCT;
    for (int it = 0; it < IT; it++) {
      uint32_t c = ACC_BIT | (t > 0 ? ACCUM_BIT : 0) | C_ACC(it, jt);
      if (it == 0) { PRELOAD(WC_SP(t, jt), c); }
      else { PRELOAD(GARBAGE_ADDR, c); }
      if (it == IT - 1 && b + 1 < blocks) send_meta(meta[(b + 1) % KCT][(b + 1) / KCT]);
      if (it == 0) { COMPUTE_PRE(A_SP(it, 2 * t), A_SP(it, 2 * t + 1)); }
      else { COMPUTE_ACC(A_SP(it, 2 * t), A_SP(it, 2 * t + 1)); }
    }
  }
  uint64_t issued = read_cycles();
  gemmini_fence();
  uint64_t end = read_cycles();
  ctr_stop();
  report(name, start, issued, end, blocks * IT);
  sparse_end();
}

// ---- sparse-loop-fix: one LOOP_WS for the whole matmul, main memory to main memory ----
_Static_assert((IT * KT + KT * JT) * DIM <= BANK_NUM * BANK_ROWS / 2 && IT * JT * DIM <= ACC_ROWS / 2, "one loop has to hold the matmul");
static void loop_config(const char * name, int stride_b) {
  if (cpu_only) { printf("%s: hardware loop issued in a cpu-only run; fair_perf FAILED\n", name); exit(3); }
  gemmini_config_st(NM_J * sizeof(acc_t));
  gemmini_extended3_config_ld(NM_K * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 0);
  gemmini_extended3_config_ld(stride_b * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 1);
  gemmini_extended3_config_ld(NM_J * sizeof(acc_t), MVIN_SCALE_IDENTITY, false, 2);
  gemmini_fence();
}
static void dense_loop(const char * name) {
  gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0);
  loop_config(name, NM_J);
  ctr_start();
  uint64_t start = read_cycles();
  gemmini_loop_ws(IT, JT, KT, 0, 0, 0, &a[0][0], &w[0][0], NULL, &c_out[0][0], NM_K, NM_J, NM_J, NM_J,
                  false, false, true, false, false, NO_ACTIVATION, 0, 0, false);
  uint64_t issued = read_cycles();
  gemmini_fence();
  uint64_t end = read_cycles();
  ctr_stop();
  report(name, start, issued, end, IT * JT * KT);
  c_in_dram = 1;
}
static void sparse_loop(const char * name) {
  _Static_assert(KT % 2 == 0, "a sparse loop needs an even K tile count");
  sparse_begin(name);
  loop_config(name, NM_J);
  NM_REQUIRE(nm_loop_fits(IT, JT, KT));
  ctr_start();
  uint64_t start = read_cycles();
  gemmini_loop_ws_nm(IT, JT, KT, 0, 0, 0, &a[0][0], &wc[0][0], NULL, &c_out[0][0], NM_K, NM_J, NM_J, NM_J,
                     false, false, true, false, false, NO_ACTIVATION, 0, 0, false, &meta_loop[0][0][0]);
  uint64_t issued = read_cycles();
  gemmini_fence();
  uint64_t end = read_cycles();
  ctr_stop();
  report(name, start, issued, end, IT * JT * KCT);
  sparse_end();
  c_in_dram = 1;
}

// cpu cost of issuing only the index tiles of the sparse loop (cpu only: index tiles with no preloads would fill the fifo)
static void meta_only(const char * name) {
  const int ntiles = IT * JT * KCT;
  need_sparse(name);
  if (!cpu_only) { printf("%s: cpu-only run issued with gemmini on; fair_perf FAILED\n", name); exit(3); }
  ctr_start();
  uint64_t start = read_cycles();
  for (int it = 0; it < IT; it++)
    for (int jt = 0; jt < JT; jt++)
      for (int t = 0; t < KCT; t++)
        send_meta(meta[t][jt]);
  uint64_t end = read_cycles();
  ctr_stop();
  report(name, start, end, end, ntiles);
}

// one-time cpu preprocessing (prune, compress, pack the index tiles); pruning pruned weights changes nothing
static void prep(const char * name) {
  uint64_t t0 = read_cycles();
  nm_prune(NM_K, NM_J, &w[0][0], NM_J, NM_N, NM_M);
  uint64_t t1 = read_cycles();
  nm_compress(NM_K, NM_J, &w[0][0], NM_J, &wc[0][0], &idx[0][0], NM_J, NM_N, NM_M);
  uint64_t t2 = read_cycles();
  for (int t = 0; t < KCT; t++)
    for (int jt = 0; jt < JT; jt++)
      nm_pack_meta(&idx[t * DIM][jt * DIM], NM_J, DIM, DIM, NM_M, meta[t][jt]);
  uint64_t t3 = read_cycles();
  printf("%-14s prep %8llu  prune %8llu  compress %8llu  pack_meta %8llu  weights %d\n", name,
    (unsigned long long)(t3 - t0), (unsigned long long)(t1 - t0), (unsigned long long)(t2 - t1),
    (unsigned long long)(t3 - t2), NM_K * NM_J);
}

// untimed warm-up, then the timed run; gemmini runs are poisoned first and checked after both passes
static int run(void (*variant)(const char *), const char * name) {
  int fails = 0;
  if (!cpu_only) poison();
  quiet = 1;
  c_in_dram = 0;
  variant(name);
  quiet = 0;
  if (!cpu_only) { fails += check(name, 1); poison(); }
  c_in_dram = 0;
  variant(name);
  if (!cpu_only) fails += check(name, 0);
  return fails;
}

int main() {
  if (build_mode != MODE_FULL && build_mode != MODE_DENSE_ONLY) { printf("bad build_mode %d; fair_perf FAILED\n", build_mode); exit(3); }
  const int sparse = build_mode == MODE_FULL;
  printf("fair_perf: %d:%d, i=%d k=%d j=%d\n", NM_N, NM_M, NM_I, NM_K, NM_J);
  printf("fair_perf build: %s\n", sparse ? "full (dense + sparse runs)" : "dense-only (no sparse-mode instructions)");
  gemmini_flush(0);
  for (int y = 0; y < NM_I; y++)
    for (int z = 0; z < NM_K; z++)
      a[y][z] = (rand() % 256) - 128;
  for (int z = 0; z < NM_K; z++)
    for (int x = 0; x < NM_J; x++)
      w[z][x] = (rand() % 256) - 128;
  for (int y = 0; y < DIM; y++)
    for (int x = 0; x < DIM; x++) poison_tile[y][x] = POISON;
  prep("prep_cold");
  prep("prep_warm");
  nm_ref_dense(NM_I, NM_K, NM_J, &a[0][0], NM_K, &w[0][0], NM_J, &gold[0][0], NM_J);

  gemmini_config_ld(NM_K * sizeof(elem_t));
  for (int it = 0; it < IT; it++)
    for (int kt = 0; kt < KT; kt++)
      gemmini_mvin(&a[it * DIM][kt * DIM], A_SP(it, kt));
  gemmini_config_ld(NM_J * sizeof(elem_t));
  for (int kt = 0; kt < KT; kt++)
    for (int jt = 0; jt < JT; jt++)
      gemmini_mvin(&w[kt * DIM][jt * DIM], W_SP(kt, jt));
  for (int t = 0; t < KCT; t++)
    for (int jt = 0; jt < JT; jt++)
      gemmini_mvin(&wc[t * DIM][jt * DIM], WC_SP(t, jt));
  if (sparse) {
    // Fix A: the index tiles in the scratchpad format, moved in once next to the weights (16 byte rows)
    for (int jt = 0; jt < JT; jt++)
      for (int t = 0; t < KCT; t++)
        nm_pack_meta_spad(&idx[t * DIM][jt * DIM], NM_J, DIM, DIM, NM_M, meta_sp[jt][t]);
    gemmini_config_ld(DIM * sizeof(elem_t));
    nm_mvin_meta_spad(&meta_sp[0][0][0], IDX_SP(0, 0), JT * KCT, 0);
    for (int t = 0; t < KCT; t++)
      for (int jt = 0; jt < JT; jt++)
        nm_pack_meta_spad(&idx[t * DIM][jt * DIM], NM_J, DIM, DIM, NM_M, meta_loop[t][jt]);
  }
  gemmini_fence();

  int fails = poison_selftest();
  fails += run(dense_fresh, "dense");
  fails += run(dense_reuse, "dense_reuse");
  if (sparse) {
    fails += run(sparse_fresh, "sparse");
    fails += run(sparse_reuse, "sparse_reuse");
    fails += run(sparse_batched, "sparse_batched");
    fails += run(sparse_spad, "sparse_spad");
  }
  // last: a hardware loop loads its own operands over the scratchpad rows the runs above read
  fails += run(dense_loop, "dense_loop");
  if (sparse) fails += run(sparse_loop, "sparse_loop");

  printf("cpu only (no gemmini instructions issued):\n");
  cpu_only = 1;
  run(dense_fresh, "cpu_dense");
  run(dense_reuse, "cpu_dense_reuse");
  if (sparse) {
    run(sparse_fresh, "cpu_sparse");
    run(sparse_reuse, "cpu_sparse_reuse");
    run(sparse_batched, "cpu_sparse_batched");
    run(sparse_spad, "cpu_sparse_spad");
    run(meta_only, "cpu_meta_only");
  }
  cpu_only = 0;

  if (fails) { printf("fair_perf FAILED\n"); exit(1); }
  printf("fair_perf passed\n");
  exit(0);
}
