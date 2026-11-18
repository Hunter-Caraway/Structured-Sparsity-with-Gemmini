// scratch-only smoke test of the Spike sparse LOOP_WS model (sparse-loop-fix); not a repo test
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include "include/gemmini_testutils.h"
#include "include/gemmini_nm.h"

#define MM 48
#define MN 80
#define MK 128
#define MKC (MK / NM_M * NM_N)
#define MT_ ((MKC / DIM) * (MN / DIM))

static elem_t a[MM][MK] row_align(1);
static elem_t w[MK][MN];
static elem_t wc[MKC][MN] row_align(1);
static nm_idx_t idx[MKC][MN];
static uint8_t meta_sp[MT_][NM_META_SPAD_BYTES] row_align(1);
static uint8_t meta_loop[MT_][NM_META_SPAD_BYTES] __attribute__((aligned(64)));
static acc_t bias[MM][MN] row_align_acc(1);
static acc_t gold[MM][MN];
static acc_t c_out[MM][MN] row_align_acc(1);

static unsigned rs = 20261112;
static int rnd(int lo, int hi) { rs = rs * 1103515245u + 12345u; return lo + (int)((rs >> 8) % (unsigned)(hi - lo + 1)); }

static int run_case(size_t M, size_t N, size_t K, size_t ti, size_t tj, size_t tk, int bmode) {
  const size_t NT = (N + DIM - 1) / DIM, KBT = K / (2 * DIM);
  for (size_t y = 0; y < M; y++) for (size_t z = 0; z < K; z++) a[y][z] = rnd(-128, 127);
  for (size_t z = 0; z < K; z++) for (size_t x = 0; x < N; x++) w[z][x] = rnd(-128, 127);
  for (size_t y = 0; y < M; y++) for (size_t x = 0; x < N; x++) bias[y][x] = rnd(-100000, 100000);
  nm_prune(K, N, &w[0][0], MN, NM_N, NM_M);
  nm_compress(K, N, &w[0][0], MN, &wc[0][0], &idx[0][0], MN, NM_N, NM_M);
  nm_ref_dense(M, K, N, &a[0][0], MK, &w[0][0], MN, &gold[0][0], MN);
  for (size_t y = 0; y < M; y++) for (size_t x = 0; x < N; x++) {
    if (bmode == 1) gold[y][x] += bias[y][x];
    if (bmode == 2) gold[y][x] += bias[0][x];
    c_out[y][x] = 0x5A5A5A5A;
  }
  for (size_t t = 0; t < KBT; t++) for (size_t jt = 0; jt < NT; jt++) {
    const size_t cols = N - jt * DIM < DIM ? N - jt * DIM : DIM;
    nm_pack_meta_spad(&idx[t * DIM][jt * DIM], MN, DIM, cols, NM_M, meta_sp[t * NT + jt]);
  }
  if (ti == 0) nm_loop_tiles(M, N, K, &ti, &tj, &tk);
  nm_loop_order_idx(N, K, tj, tk, &meta_sp[0][0], &meta_loop[0][0]);
  tiled_matmul_nm_loop(M, N, K, &a[0][0], MK, &wc[0][0], MN, bmode ? &bias[0][0] : NULL, MN, bmode == 2,
                       &meta_loop[0][0], &c_out[0][0], MN, ti, tj, tk);
  int bad = 0;
  for (size_t y = 0; y < M; y++) for (size_t x = 0; x < N; x++) if (c_out[y][x] != gold[y][x]) bad++;
  printf("case M=%d N=%d K=%d tiles %dx%dx%d bias=%d: %s (%d wrong)\n", (int)M, (int)N, (int)K, (int)ti, (int)tj, (int)tk,
         bmode, bad ? "FAIL" : "ok", bad);
  return bad != 0;
}

int main(void) {
  gemmini_flush(0);
  int f = 0;
  f += run_case(16, 16, 32, 1, 1, 2, 0);   // T = 1
  f += run_case(20, 16, 64, 2, 1, 4, 0);   // T = 2, J = 1, I = 2
  f += run_case(16, 48, 32, 1, 3, 2, 1);   // T = 3
  f += run_case(16, 64, 32, 1, 4, 2, 2);   // T = 4
  f += run_case(16, 80, 32, 1, 5, 2, 0);   // T = 5 (n = 1 tail)
  f += run_case(40, 50, 96, 3, 4, 6, 1);   // one loop, T = 12, partial I and J tiles
  f += run_case(40, 50, 128, 2, 3, 4, 2);  // several loops with tails
  f += run_case(48, 80, 128, 0, 0, 0, 0);  // tiler's own sizes
  f += run_case(48, 80, 128, 3, 5, 8, 1);  // T = 20 in one loop
#ifdef DENSE_AFTER
#endif
  if (f) { printf("smoke_loop: %d case(s) FAILED\n", f); exit(1); }
  printf("smoke_loop passed\n");
  exit(0);
}
