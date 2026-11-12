// streaming benchmark: one real-size int8 layer, C (M x N int32) = A (M x K) * W (K x N), data in main memory.
// variants (each: untimed warm-up on a small sub-problem, then one timed run):
//   berkeley       Berkeley's tiled_matmul_auto(..., WS), full_C (int32) output: the LOOP_WS hardware loop
//   dense_stream   tiled_matmul_stream_dense(): the hand-written streaming tiler (gemmini_nm.h), dense weights
//   sparse_stream  tiled_matmul_nm(): the same tiler with the n:m compressed weights + packed index tiles
//   sparse_fixa    tiled_matmul_nm_spad() (Fix A): as sparse_stream, but the index tiles are mvin'd with the weights
//                  and each batch of up to 4 is one scratchpad index load (funct 26 rd 2); needs a Fix A chip
// all data and the reference come from the host (gen/gen_data.py -> data.h). the cpu only hashes C (64-bit FNV-1a
// over every value) and compares the sampled rows.
// before every run (warm-up and timed): C and the whole accumulator are filled with a poison value; before every
// timed run the L2 is evicted (DMA read of a 2 MiB junk buffer), so every timed run starts from cold caches.
// timed region: read_cycles() right before the call (configs included) .. last mvout + gemmini_fence().
// build: -DNM_N/-DNM_M (must equal the data header's pattern), -DSBENCH_DATA=\"<.../data.h>\",
//        -DDENSE_ONLY (stock chip: only flips the volatile build_mode flag, .text stays byte-identical),
//        -DRUN_MASK=<bits> (1 berkeley, 2 dense_stream, 4 sparse_stream, 8 sparse_fixa; a volatile flag too)

#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include "include/gemmini_testutils.h"
#include "include/gemmini_counter.h"
#include "include/gemmini_nm.h"
#include SBENCH_DATA

#if L_NM_N != NM_N || L_NM_M != NM_M
#error "data header pattern differs from -DNM_N/-DNM_M"
#endif

#define MODE_DENSE_ONLY 0x0D
#define MODE_FULL 0x5F
#ifdef DENSE_ONLY
#define BUILD_MODE MODE_DENSE_ONLY
#else
#define BUILD_MODE MODE_FULL
#endif
#ifndef RUN_MASK
#define RUN_MASK 7
#endif
#define RUN_BERKELEY 1
#define RUN_DENSE 2
#define RUN_SPARSE 4
#define RUN_SPARSE_FIXA 8
// both non-zero so they sit in .sdata in every build
static volatile int build_mode = BUILD_MODE;
static volatile int run_mask = RUN_MASK | 0x100;

#define POISON ((acc_t)0x5A5A5A5A)
#define JUNK_BYTES (2u << 20)

static acc_t c_out[L_M][L_N] row_align_acc(1);
static acc_t poison_tile[DIM][DIM] row_align_acc(1);
static elem_t junk[JUNK_BYTES] __attribute__((aligned(64)));
static size_t TI, TJ;

#define NCTR 8
static const int ctr_ids[NCTR] = {
  EXE_ACTIVE_CYCLE, RDMA_ACTIVE_CYCLE, WDMA_ACTIVE_CYCLE, LOAD_ACTIVE_CYCLE,
  STORE_ACTIVE_CYCLE, RESERVATION_STATION_FULL_CYCLES, LOOP_MATMUL_ACTIVE_CYCLES, RDMA_BYTES_REC
};
static const char * ctr_names[NCTR] = {
  "ex_active", "rdma_active", "wdma_active", "load_active", "store_active", "rs_full", "loop_matmul_active", "rdma_bytes"
};
static uint32_t ctr_vals[NCTR];
static void ctr_start(void) { counter_reset(); for (int i = 0; i < NCTR; i++) counter_configure(i, ctr_ids[i]); }
// read live, after the fence (everything idle, so nothing still counts). no snapshot: Berkeley's CounterFile picks
// external vs internal for the whole snapshot by the snapshot command's own counter index (0), so a snapshot
// returns the wrong value for the external counter rdma_bytes (seen as 0 in the pilot run)
static void ctr_stop(void) { for (int i = 0; i < NCTR; i++) ctr_vals[i] = counter_read(i); }

// every accumulator row = POISON (mvin of a poison tile), then all of C = POISON by mvouts of poisoned acc tiles
// (the DMA writes C much faster than the cpu could; poison_selftest() checks it once)
static void poison(void) {
  const uint32_t acc = (uint32_t)1 << (ADDR_LEN - 1), full = (uint32_t)1 << (ADDR_LEN - 3);
  gemmini_config_ld(DIM * sizeof(acc_t));
  for (uint32_t r = 0; r < ACC_ROWS; r += DIM) gemmini_mvin(&poison_tile[0][0], acc | r);
  gemmini_config_st(L_N * sizeof(acc_t));
  for (size_t y = 0; y < L_M; y += DIM)
    for (size_t x = 0; x < L_N; x += DIM)
      gemmini_extended_mvout(&c_out[y][x], acc | full | (uint32_t)(((y / DIM * (L_N / DIM) + x / DIM) * DIM) % ACC_ROWS),
                             DIM, L_M - y < DIM ? L_M - y : DIM);
  gemmini_fence();
}

// once: every value of C reads back as POISON after poison() (C first set to something else by the cpu)
static int poison_selftest(void) {
  for (size_t y = 0; y < L_M; y++)
    for (size_t x = 0; x < L_N; x++) c_out[y][x] = 0;
  poison();
  for (size_t y = 0; y < L_M; y++)
    for (size_t x = 0; x < L_N; x++)
      if (c_out[y][x] != POISON) { printf("poison did not reach C at (%d,%d); sbench FAILED\n", (int)y, (int)x); return 0; }
  printf("poison reaches all of C (%d values)\n", L_M * L_N);
  return 1;
}

// push A, W and C out of the L2 (512 KiB, 8 ways, random replacement) and so out of the L1s (the L2 is inclusive):
// 2 MiB = 4x the L2, so a line survives with p ~ (7/8)^32 = 1.4%.
static void evict_l2(void) {
  gemmini_config_ld(MAX_BLOCK_LEN * DIM);
  for (uint32_t off = 0; off < JUNK_BYTES; off += DIM * MAX_BLOCK_LEN * DIM)
    gemmini_extended_mvin(junk + off, (off / DIM) % BANK_ROWS, MAX_BLOCK_LEN * DIM, DIM);
  gemmini_fence();
}

// 64-bit FNV-1a in 4 interleaved lanes over C read as uint64 words (two int32 each, little-endian), lanes folded
// with FNV-1a at the end; gen_data.py computes the same. 4 lanes hide the multiply latency.
static uint64_t hash_c(void) {
  const uint64_t P = 0x100000001B3ULL;
  const uint64_t * w = (const uint64_t *)&c_out[0][0];
  const size_t nw = (size_t)L_M * L_N / 2;
  uint64_t h0 = 0xCBF29CE484222325ULL, h1 = h0 + 1, h2 = h0 + 2, h3 = h0 + 3;
  for (size_t i = 0; i < nw; i += 4) {
    h0 = (h0 ^ w[i]) * P; h1 = (h1 ^ w[i + 1]) * P; h2 = (h2 ^ w[i + 2]) * P; h3 = (h3 ^ w[i + 3]) * P;
  }
  uint64_t h = 0xCBF29CE484222325ULL;
  h = (h ^ h0) * P; h = (h ^ h1) * P; h = (h ^ h2) * P; h = (h ^ h3) * P;
  return h;
}
_Static_assert(((size_t)L_M * L_N) % 8 == 0, "hash_c needs M*N to be a multiple of 8");

// 1 if C is right: hash of all of C + full compare of the sampled rows
static int verify(const char * name) {
  const uint64_t h = hash_c();
  int rows_ok = 0, first_bad = 1;
  for (int s = 0; s < L_NSAMPLE; s++) {
    const int r = l_sample_rows[s];
    int ok = 1;
    for (size_t x = 0; x < L_N; x++)
      if (c_out[r][x] != l_SREF[s * L_N + x]) {
        if (first_bad) { printf("%s mismatch at (%d,%d): got %d want %d\n", name, r, (int)x, c_out[r][x], l_SREF[s * L_N + x]); first_bad = 0; }
        ok = 0;
        break;
      }
    rows_ok += ok;
  }
  const int good = h == L_HASH && rows_ok == L_NSAMPLE;
  printf("%s check: hash 0x%016llx expected 0x%016llx, sampled rows %d/%d -> %s\n", name, (unsigned long long)h,
         (unsigned long long)L_HASH, rows_ok, L_NSAMPLE, good ? "verified" : "MISMATCH");
  return good;
}

// ---- the three variants: (M, N, K) may be a sub-problem (warm-up); strides are the full layer's ----
static void v_berkeley(size_t m, size_t n, size_t k) {
  tiled_matmul_auto(m, n, k, (const elem_t *)l_A, (const elem_t *)l_W, NULL, &c_out[0][0],
                    L_K, L_N, L_N, L_N, MVIN_SCALE_IDENTITY, MVIN_SCALE_IDENTITY, MVIN_SCALE_IDENTITY,
                    NO_ACTIVATION, ACC_SCALE_IDENTITY, 0, false, false, false, true, false, 0, WS);
}
static void v_dense(size_t m, size_t n, size_t k) {
  tiled_matmul_stream_dense(m, n, k, (const elem_t *)l_A, L_K, (const elem_t *)l_W, L_N, &c_out[0][0], L_N, TI, TJ);
}
static void v_sparse(size_t m, size_t n, size_t k) {
  if (build_mode != MODE_FULL) { printf("sparse run requested in a dense-only build; sbench FAILED\n"); exit(3); }
  tiled_matmul_nm(m, n, k, (const elem_t *)l_A, L_K, (const elem_t *)l_WC, L_N, l_META, &c_out[0][0], L_N, TI, TJ);
}

// Fix A: the index tiles in the scratchpad format. 2:4: byte for byte the register format, so l_META itself;
// 4:8: repacked once at start (untimed) from l_META (rows packed tight instead of one per 64-bit word)
#define L_NTILES ((size_t)(L_K / 2 / DIM) * (L_N / DIM))
#if NM_M != 4
static uint8_t meta_sp_buf[L_NTILES * NM_META_SPAD_BYTES] __attribute__((aligned(64)));
#endif
static const uint8_t * meta_sp;
static void prep_meta_sp(void) {
#if NM_M == 4
  _Static_assert(NM_META_SPAD_BYTES == 2 * 4 * sizeof(uint64_t), "2:4 tile = the 8 nm_pack_meta words");
  meta_sp = (const uint8_t *)l_META;
#else
  for (size_t u = 0; u < L_NTILES; u++) nm_meta_regs_to_spad(l_META + u * L_META_WORDS, NM_M, meta_sp_buf + u * NM_META_SPAD_BYTES);
  meta_sp = meta_sp_buf;
#endif
}
static void v_sparse_fixa(size_t m, size_t n, size_t k) {
  if (build_mode != MODE_FULL) { printf("sparse run requested in a dense-only build; sbench FAILED\n"); exit(3); }
  tiled_matmul_nm_spad(m, n, k, (const elem_t *)l_A, L_K, (const elem_t *)l_WC, L_N, meta_sp, &c_out[0][0], L_N, TI, TJ);
}

static int run(void (*v)(size_t, size_t, size_t), const char * name) {
  // warm-up: same code path on a small corner of the layer (i-cache, branch predictors), untimed, unchecked
  poison();
  v(L_M < 2 * DIM ? L_M : 2 * DIM, L_N < 128 ? L_N : 128, L_K < 128 ? L_K : 128);
  gemmini_fence();
  // timed run from cold caches
  const uint64_t p0 = read_cycles();
  poison();
  const uint64_t p1 = read_cycles();
  evict_l2();
  const uint64_t p2 = read_cycles();
  ctr_start();
  const uint64_t start = read_cycles();
  v(L_M, L_N, L_K);
  const uint64_t issued = read_cycles();
  gemmini_fence();
  const uint64_t end = read_cycles();
  ctr_stop();
  printf("%-13s total %10llu  cpu_issue_done %10llu |", name, (unsigned long long)(end - start),
         (unsigned long long)(issued - start));
  for (int i = 0; i < NCTR; i++) printf(" %s=%u", ctr_names[i], ctr_vals[i]);
  printf("\n");
  const int good = verify(name);
  printf("%s overhead (untimed): poison %llu  evict_l2 %llu  check %llu cycles\n", name, (unsigned long long)(p1 - p0),
         (unsigned long long)(p2 - p1), (unsigned long long)(read_cycles() - end));
  return good;
}

int main(void) {
  if (build_mode != MODE_FULL && build_mode != MODE_DENSE_ONLY) { printf("bad build_mode %d; sbench FAILED\n", build_mode); exit(3); }
  const int mask = run_mask & 15;
  nm_stream_tiles(L_M, L_N, &TI, &TJ);
  printf("sbench: layer=%s M=%d K=%d N=%d pattern=%d:%d build=%s run_mask=%d TI=%d TJ=%d data_seed=%d\n", L_NAME, L_M,
         L_K, L_N, NM_N, NM_M, build_mode == MODE_FULL ? "full" : "dense-only", mask, (int)TI, (int)TJ, L_SEED);
  gemmini_flush(0);
  for (int y = 0; y < DIM; y++)
    for (int x = 0; x < DIM; x++) poison_tile[y][x] = POISON;

  if (!poison_selftest()) exit(1);
  int ran = 0, good = 0;
  if (mask & RUN_BERKELEY) { ran++; good += run(v_berkeley, "berkeley"); }
  if (mask & RUN_DENSE) { ran++; good += run(v_dense, "dense_stream"); }
  if (mask & RUN_SPARSE) { ran++; good += run(v_sparse, "sparse_stream"); }
  if (mask & RUN_SPARSE_FIXA) { prep_meta_sp(); ran++; good += run(v_sparse_fixa, "sparse_fixa"); }

  printf("sbench end cycle %llu\n", (unsigned long long)read_cycles());
  if (ran == 0 || good != ran) { printf("sbench FAILED (%d of %d runs verified)\n", good, ran); exit(1); }
  printf("sbench passed (%d of %d runs verified)\n", good, ran);
  exit(0);
}
