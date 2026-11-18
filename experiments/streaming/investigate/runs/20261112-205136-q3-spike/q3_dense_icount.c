// q3_dense_icount: retired-instruction count of Berkeley's dense tiled_matmul_auto (WS, full_C int32 output) for one
// layer, C (M x N) = A (M x K) * W (K x N). Meant for Spike (CPI 1, so cycles == instructions there).
// Only Berkeley's headers are used (no gemmini_nm.h); the call is the same as stream_bench.c's "berkeley" variant.
// counted region: rdcycle, rdinstret | tiled_matmul_auto(...) | rdinstret, rdcycle | gemmini_fence() | rdinstret.
// two counts per layer: dense_icount (dimensions are constants) and dense_icount_rt (dimensions known at run time).
// No warm-up and no cache eviction: an instruction count does not depend on cache state.
// checks (both must pass for "verified"): every value of C against a CPU matmul computed here, and the host's
// 64-bit hash + sampled rows from data.h (gen/gen_data.py).
// -DQ3_CONST_ONLY: only the first call, so gcc can inline it and fold the tile-size search at compile time.
// build: -DSBENCH_DATA=\"<.../data.h>\" (see scripts/q3_dense_icount.sh)

#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include "include/gemmini_testutils.h"
#include SBENCH_DATA

#define POISON ((acc_t)0x5A5A5A5A)

static acc_t c_out[L_M][L_N] row_align_acc(1);
static acc_t ref_row[L_N];

static inline uint64_t read_instret(void) {
  uint64_t n;
  asm volatile ("rdinstret %0" : "=r" (n));
  return n;
}

// same hash as stream_bench.c hash_c() / gen_data.py
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

// number of values of C that differ from the CPU matmul (one reference row at a time)
static size_t cpu_mismatches(void) {
  size_t bad = 0;
  for (size_t y = 0; y < L_M; y++) {
    for (size_t x = 0; x < L_N; x++) ref_row[x] = 0;
    for (size_t k = 0; k < L_K; k++) {
      const acc_t a = l_A[y * L_K + k];
      const int8_t * w = &l_W[k * L_N];
      for (size_t x = 0; x < L_N; x++) ref_row[x] += a * w[x];
    }
    for (size_t x = 0; x < L_N; x++)
      if (c_out[y][x] != ref_row[x]) {
        if (bad == 0) printf("q3 mismatch at (%d,%d): got %d want %d\n", (int)y, (int)x, c_out[y][x], ref_row[x]);
        bad++;
      }
  }
  return bad;
}

static int host_rows_ok(void) {
  int rows_ok = 0;
  for (int s = 0; s < L_NSAMPLE; s++) {
    const int r = l_sample_rows[s];
    int ok = 1;
    for (size_t x = 0; x < L_N; x++)
      if (c_out[r][x] != l_SREF[s * L_N + x]) { ok = 0; break; }
    rows_ok += ok;
  }
  return rows_ok;
}

// 1 if C is right; prints the check line
static int check(const char * name) {
  const size_t bad = cpu_mismatches();
  const uint64_t h = hash_c();
  const int rows = host_rows_ok();
  const int good = bad == 0 && h == L_HASH && rows == L_NSAMPLE;
  printf("q3 check %s: layer=%s cpu_ref mismatches %lu of %lu, hash 0x%016llx expected 0x%016llx, sampled rows %d/%d -> %s\n",
         name, L_NAME, (unsigned long)bad, (unsigned long)((size_t)L_M * L_N), (unsigned long long)h,
         (unsigned long long)L_HASH, rows, L_NSAMPLE, good ? "verified" : "MISMATCH");
  return good;
}

static void poison(void) {
  for (size_t y = 0; y < L_M; y++)
    for (size_t x = 0; x < L_N; x++) c_out[y][x] = POISON;
}

// the compiler cannot see these, so the tile-size search of tiled_matmul_auto runs on the CPU (dense_icount_rt)
#ifndef Q3_CONST_ONLY
static volatile size_t rt_m = L_M, rt_n = L_N, rt_k = L_K;
#endif

int main(void) {
  gemmini_flush(0);

  // dense_icount: dimensions are compile-time constants (gcc may fold tiled_matmul_auto's tile-size search)
  poison();
  const uint64_t c0 = read_cycles();
  const uint64_t i0 = read_instret();
  tiled_matmul_auto(L_M, L_N, L_K, (const elem_t *)l_A, (const elem_t *)l_W, NULL, &c_out[0][0],
                    L_K, L_N, L_N, L_N, MVIN_SCALE_IDENTITY, MVIN_SCALE_IDENTITY, MVIN_SCALE_IDENTITY,
                    NO_ACTIVATION, ACC_SCALE_IDENTITY, 0, false, false, false, true, false, 0, WS);
  const uint64_t i1 = read_instret();
  const uint64_t c1 = read_cycles();
  gemmini_fence();
  const uint64_t i2 = read_instret();
  const int good = check("dense_icount");
  printf("q3 dense_icount: layer=%s M=%d K=%d N=%d DIM=%d instret=%llu cycles=%llu instret_with_fence=%llu %s\n",
         L_NAME, L_M, L_K, L_N, DIM, (unsigned long long)(i1 - i0), (unsigned long long)(c1 - c0),
         (unsigned long long)(i2 - i0), good ? "verified" : "UNVERIFIED");

#ifdef Q3_CONST_ONLY
  // single call site: gcc inlines tiled_matmul_auto and folds the tile-size search (lower bound of the CPU cost)
  const int good_rt = 1;
#else
  // dense_icount_rt: the same call with dimensions only known at run time
  poison();
  const size_t m = rt_m, n = rt_n, k = rt_k;
  const uint64_t d0 = read_cycles();
  const uint64_t j0 = read_instret();
  tiled_matmul_auto(m, n, k, (const elem_t *)l_A, (const elem_t *)l_W, NULL, &c_out[0][0],
                    L_K, L_N, L_N, L_N, MVIN_SCALE_IDENTITY, MVIN_SCALE_IDENTITY, MVIN_SCALE_IDENTITY,
                    NO_ACTIVATION, ACC_SCALE_IDENTITY, 0, false, false, false, true, false, 0, WS);
  const uint64_t j1 = read_instret();
  const uint64_t d1 = read_cycles();
  gemmini_fence();
  const uint64_t j2 = read_instret();
  const int good_rt = check("dense_icount_rt");
  printf("q3 dense_icount_rt: layer=%s M=%d K=%d N=%d DIM=%d instret=%llu cycles=%llu instret_with_fence=%llu %s\n",
         L_NAME, L_M, L_K, L_N, DIM, (unsigned long long)(j1 - j0), (unsigned long long)(d1 - d0),
         (unsigned long long)(j2 - j0), good_rt ? "verified" : "UNVERIFIED");
#endif

  if (!good || !good_rt) { printf("q3 FAILED\n"); exit(1); }
  printf("q3 passed\n");
  exit(0);
}
