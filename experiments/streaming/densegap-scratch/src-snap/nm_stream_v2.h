// nm_stream_v2.h: investigation copy of the streaming tiler (gemmini_nm.h nm_stream_impl), with optional changes.
// include AFTER include/gemmini_nm.h. The v1 code in gemmini_nm.h is untouched.
//
// opts bits (each can be tested on its own; the same bit means the same idea for dense and sparse):
//   V2_BANKSPLIT  sparse only: a_lo and a_hi in different scratchpad banks. Each pair of A tiles (2c, 2c+1) is moved
//                 in by ONE 2-tile mvin with block_mvin_stride = BANK_ROWS, so tile 2c lands in bank P and 2c+1 in
//                 bank P+1. Even steps: A_lo bank 0, A_hi bank 1, W bank 2; odd steps: A_lo bank 2, A_hi bank 3,
//                 W bank 0. (dense needs no change: its A and W already sit in different banks and the next
//                 step's mvins go to the two other banks.)
//   V2_INTERLEAVE both: the mvins of step h+1 are spread evenly over the preload/compute stream of step h
//                 (v1 issues them all after step h's computes, so they start only once the RS drains to 8 pairs)
//   V2_META_EARLY sparse only: the index tile of each weight tile is sent as soon as the FIFO has a slot (sliding
//                 window of NM_META_FIFO_DEPTH tiles) instead of in batches of 4 right before 4 tiles' preloads
// requirements as v1; with V2_BANKSPLIT also KSTEP even (it is 4).

#ifndef NM_STREAM_V2_H
#define NM_STREAM_V2_H

#define V2_BANKSPLIT 1
#define V2_INTERLEAVE 2
#define V2_META_EARLY 4

#define V2_MAXLD 64

typedef struct { const elem_t * dram; uint32_t sp; uint16_t cols; uint16_t rows; uint8_t id; } v2_ld_t;

static inline __attribute__((always_inline)) void nm_stream_v2_impl(const int sparse, const int opts,
    size_t M, size_t N, size_t K, const elem_t * A, size_t lda, const elem_t * B, size_t ldb,
    const uint64_t * meta, acc_t * C, size_t ldc, size_t TI, size_t TJ) {
  const uint32_t acc_bit = (uint32_t)1 << (ADDR_LEN - 1), accum_bit = (uint32_t)1 << (ADDR_LEN - 2),
                 full_bit = (uint32_t)1 << (ADDR_LEN - 3);
  const int split = sparse && (opts & V2_BANKSPLIT), inter = opts & V2_INTERLEAVE, early = sparse && (opts & V2_META_EARLY);
  const size_t MT = (M + DIM - 1) / DIM, NT = N / DIM, KT = K / DIM;
  const size_t S = (KT + NM_STREAM_KSTEP - 1) / NM_STREAM_KSTEP;
  const size_t JB = (NT + TJ - 1) / TJ, nsteps = ((MT + TI - 1) / TI) * JB * S;
  const size_t mw = 2 * nm_meta_cmds(NM_M);
  const size_t a_slot = TI * NM_STREAM_KSTEP * DIM, w_slot = NM_STREAM_KSTEP * TJ * DIM;
  const size_t a_half = TI * (NM_STREAM_KSTEP / 2) * DIM, w_half = (NM_STREAM_KSTEP / 2) * TJ * DIM;
  NM_REQUIRE(M >= 1 && N % DIM == 0 && K % (sparse ? 2 * DIM : DIM) == 0 && K >= DIM);
  NM_REQUIRE(TI >= 1 && TJ >= 1 && TI * TJ * DIM <= ACC_ROWS / 2 && 2 * a_slot <= BANK_ROWS && 2 * w_slot <= BANK_ROWS);
  NM_REQUIRE(!split || (2 * a_half <= BANK_ROWS / 2 && 2 * w_half <= BANK_ROWS / 2));
  // v1 layout: A buffers in banks 0/1, W buffers in banks 2/3 (by buffer parity)
  // split layout: parity 0: A_lo bank 0 rows [0, BANK_ROWS/2), A_hi bank 1, W bank 2 rows [BANK_ROWS/2, ..)
  //               parity 1: A_lo bank 2 rows [0, BANK_ROWS/2), A_hi bank 3, W bank 0 rows [BANK_ROWS/2, ..)
#define V2_A_SP(buf) ((uint32_t)(split ? (((buf) % 2) * 2 * BANK_ROWS + ((buf) / 2) * a_half) \
                                       : (((buf) % 2) * BANK_ROWS + ((buf) / 2) * a_slot)))
#define V2_W_SP(buf) ((uint32_t)(split ? ((2 - ((buf) % 2) * 2) * BANK_ROWS + BANK_ROWS / 2 + ((buf) / 2) * w_half) \
                                       : ((2 + (buf) % 2) * BANK_ROWS + ((buf) / 2) * w_slot)))

  if (sparse) {
    gemmini_nm_reset();
    gemmini_nm_config_ex(1, NO_ACTIVATION, 0, ACC_SCALE_IDENTITY, 1, 1);
  } else {
    gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0);
  }
  if (split) { gemmini_extended4_config_ld(lda * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, BANK_ROWS, 0); }
  else { gemmini_extended3_config_ld(lda * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 0); }
  gemmini_extended3_config_ld(ldb * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 1);
  gemmini_config_st(ldc * sizeof(acc_t));

  v2_ld_t ld[V2_MAXLD];
  size_t nld = 0, ild = 0;
  // the mvins of step g, into ld[]
#define V2_BUILD_LOADS(g) do { \
    const size_t blk_ = (g) / S, s_ = (g) % S, buf_ = (g) % NM_STREAM_NBUF; \
    const size_t i0_ = (blk_ / JB) * TI, j0_ = (blk_ % JB) * TJ; \
    const size_t ti_ = MT - i0_ < TI ? MT - i0_ : TI, tj_ = NT - j0_ < TJ ? NT - j0_ : TJ; \
    const size_t k0_ = s_ * NM_STREAM_KSTEP, kw_ = KT - k0_ < NM_STREAM_KSTEP ? KT - k0_ : NM_STREAM_KSTEP; \
    const size_t wt_ = sparse ? kw_ / 2 : kw_, wrow0_ = sparse ? k0_ / 2 * DIM : k0_ * DIM; \
    nld = 0; ild = 0; \
    for (size_t i = 0; i < ti_; i++) { \
      const size_t r = (i0_ + i) * DIM, rows = M - r < DIM ? M - r : DIM; \
      if (split) { \
        for (size_t c = 0; c < kw_ / 2; c++) \
          ld[nld++] = (v2_ld_t){ A + r * lda + (k0_ + 2 * c) * DIM, V2_A_SP(buf_) + (i * (NM_STREAM_KSTEP / 2) + c) * DIM, 2 * DIM, rows, 0 }; \
      } else { \
        ld[nld++] = (v2_ld_t){ A + r * lda + k0_ * DIM, V2_A_SP(buf_) + i * NM_STREAM_KSTEP * DIM, kw_ * DIM, rows, 0 }; \
      } \
    } \
    for (size_t q = 0; q < wt_; q++) \
      for (size_t jj = 0; jj < tj_; jj += MAX_BLOCK_LEN) { \
        const size_t blocks = tj_ - jj < MAX_BLOCK_LEN ? tj_ - jj : MAX_BLOCK_LEN; \
        ld[nld++] = (v2_ld_t){ B + (wrow0_ + q * DIM) * ldb + (j0_ + jj) * DIM, V2_W_SP(buf_) + (q * TJ + jj) * DIM, blocks * DIM, DIM, 1 }; \
      } \
  } while (0)
#define V2_ISSUE_LD() do { \
    const v2_ld_t * l_ = &ld[ild++]; \
    if (l_->id == 0) { gemmini_extended_mvin(l_->dram, l_->sp, l_->cols, l_->rows); } \
    else { gemmini_extended_mvin2(l_->dram, l_->sp, l_->cols, l_->rows); } \
  } while (0)

  // mvouts still owed by the last finished block
  size_t st_blk = 0, st_next = 0, st_total = 0, st_per = 0;
  // sliding-window index sending (V2_META_EARLY): tiles are numbered in preload order over the whole run
  size_t meta_sent = 0, meta_popped = 0, mc_h = 0, mc_u = 0; // mc_*: (step, local tile) of the next tile to send
#define v2_ntile(hh) ({ const size_t bb_ = (hh) / S, ss_ = (hh) % S, jj0_ = (bb_ % JB) * TJ; \
    const size_t tjj_ = NT - jj0_ < TJ ? NT - jj0_ : TJ, kk0_ = ss_ * NM_STREAM_KSTEP; \
    const size_t kww_ = KT - kk0_ < NM_STREAM_KSTEP ? KT - kk0_ : NM_STREAM_KSTEP; kww_ / 2 * tjj_; })

  for (size_t g = 0; g <= nsteps; g++) {
    // ---- loads of step g: v1 issues them all here; interleaved mode issues the rest during step g-1's computes ----
    if (g < nsteps && (!inter || g == 0)) {
      V2_BUILD_LOADS(g);
      while (ild < nld) V2_ISSUE_LD();
    }
    if (g == 0) continue;

    // ---- preload/computes of step h = g - 1 ----
    const size_t h = g - 1, blk = h / S, s = h % S, buf = h % NM_STREAM_NBUF;
    const size_t i0 = (blk / JB) * TI, j0 = (blk % JB) * TJ;
    const size_t ti = MT - i0 < TI ? MT - i0 : TI, tj = NT - j0 < TJ ? NT - j0 : TJ;
    const size_t k0 = s * NM_STREAM_KSTEP, kw = KT - k0 < NM_STREAM_KSTEP ? KT - k0 : NM_STREAM_KSTEP;
    const uint32_t acc_base = (uint32_t)((blk % 2) * (ACC_ROWS / 2));
    const uint32_t a_sp = V2_A_SP(buf), w_sp = V2_W_SP(buf);
    if (inter && g < nsteps) V2_BUILD_LOADS(g); // step g's mvins go out during step h's pairs
    else if (inter) { nld = 0; ild = 0; }
    const size_t npairs = (sparse ? kw / 2 : kw) * tj * ti;
    size_t pair = 0;
    // issue the loads whose turn has come: load j goes out before pair floor(j * npairs / nld)
#define V2_DRIP() do { if (inter) while (ild < nld && ild * npairs <= pair * nld) V2_ISSUE_LD(); pair++; } while (0)
    if (!sparse) {
      for (size_t q = 0; q < kw; q++) {
        const uint32_t cflags = acc_bit | (k0 + q > 0 ? accum_bit : 0);
        for (size_t j = 0; j < tj; j++) {
          const uint32_t w = w_sp + (q * TJ + j) * DIM;
          size_t rows = M - i0 * DIM < DIM ? M - i0 * DIM : DIM;
          V2_DRIP();
          gemmini_extended_preload(w, cflags | (acc_base + j * DIM), DIM, DIM, DIM, rows);
          gemmini_extended_compute_preloaded(a_sp + q * DIM, GARBAGE_ADDR, DIM, rows, DIM, DIM);
          for (size_t i = 1; i < ti; i++) {
            const size_t r = (i0 + i) * DIM;
            rows = M - r < DIM ? M - r : DIM;
            V2_DRIP();
            gemmini_extended_preload(GARBAGE_ADDR, cflags | (acc_base + (i * TJ + j) * DIM), DIM, DIM, DIM, rows);
            gemmini_extended_compute_accumulated(a_sp + (i * NM_STREAM_KSTEP + q) * DIM, GARBAGE_ADDR, DIM, rows, DIM, DIM);
          }
        }
      }
    } else {
      const size_t ntile = kw / 2 * tj;
      // index tile of local tile u of step h
#define V2_META_OF(hh, u) do { \
        const size_t bb_ = (hh) / S, ss_ = (hh) % S, jj0_ = (bb_ % JB) * TJ, tjj_ = NT - jj0_ < TJ ? NT - jj0_ : TJ; \
        nm_send_meta(meta + ((ss_ * NM_STREAM_KSTEP / 2 + (u) / tjj_) * NT + jj0_ + (u) % tjj_) * mw, NM_M); \
      } while (0)
      for (size_t u0 = 0; u0 < ntile; u0 += NM_META_FIFO_DEPTH) {
        const size_t u1 = u0 + NM_META_FIFO_DEPTH < ntile ? u0 + NM_META_FIFO_DEPTH : ntile;
        if (!early)
          for (size_t u = u0; u < u1; u++) V2_META_OF(h, u);
        for (size_t u = u0; u < u1; u++) {
          const size_t c = u / tj, j = u % tj;
          if (early) {
            // sliding window: before preload n (n = meta_popped) the tiles up to n + DEPTH - 1 may be sent. A tile
            // leaves the FIFO when its preload fires, so sending n + DEPTH before preload n is issued would deadlock.
            while (meta_sent < meta_popped + NM_META_FIFO_DEPTH && mc_h < nsteps) {
              V2_META_OF(mc_h, mc_u);
              meta_sent++;
              if (++mc_u >= v2_ntile(mc_h)) { mc_u = 0; mc_h++; }
            }
          }
          const uint32_t cflags = acc_bit | (k0 / 2 + c > 0 ? accum_bit : 0);
          const uint32_t w = w_sp + (c * TJ + j) * DIM;
          size_t rows = M - i0 * DIM < DIM ? M - i0 * DIM : DIM;
          const uint32_t a_lo0 = split ? a_sp + c * DIM : a_sp + 2 * c * DIM;
          const uint32_t a_hi0 = split ? a_lo0 + BANK_ROWS : a_lo0 + DIM;
          V2_DRIP();
          gemmini_extended_preload(w, cflags | (acc_base + j * DIM), DIM, DIM, DIM, rows);
          gemmini_extended_compute_preloaded(a_lo0, a_hi0, DIM, rows, DIM, rows);
          meta_popped++;
          for (size_t i = 1; i < ti; i++) {
            const size_t r = (i0 + i) * DIM;
            rows = M - r < DIM ? M - r : DIM;
            const uint32_t a_lo = split ? a_sp + (i * (NM_STREAM_KSTEP / 2) + c) * DIM : a_sp + (i * NM_STREAM_KSTEP + 2 * c) * DIM;
            const uint32_t a_hi = split ? a_lo + BANK_ROWS : a_lo + DIM;
            V2_DRIP();
            gemmini_extended_preload(GARBAGE_ADDR, cflags | (acc_base + (i * TJ + j) * DIM), DIM, DIM, DIM, rows);
            gemmini_extended_compute_accumulated(a_lo, a_hi, DIM, rows, DIM, rows);
          }
        }
      }
    }
    if (inter) while (ild < nld) V2_ISSUE_LD();

    // ---- mvouts: as v1 ----
    {
      const size_t n_out = g == nsteps ? st_total - st_next : (st_per < st_total - st_next ? st_per : st_total - st_next);
      const size_t si0 = (st_blk / JB) * TI, sj0 = (st_blk % JB) * TJ;
      const size_t stj = NT - sj0 < TJ ? NT - sj0 : TJ;
      const uint32_t sbase = (uint32_t)((st_blk % 2) * (ACC_ROWS / 2));
      for (size_t e = st_next; e < st_next + n_out; e++) {
        const size_t i = e / stj, j = e % stj, r = (si0 + i) * DIM, rows = M - r < DIM ? M - r : DIM;
        gemmini_extended_mvout(C + r * ldc + (sj0 + j) * DIM, acc_bit | full_bit | (sbase + (i * TJ + j) * DIM), DIM, rows);
      }
      st_next += n_out;
    }
    if (s == S - 1) {
      st_blk = blk; st_next = 0; st_total = ti * tj; st_per = (st_total + S - 1) / S;
      if (g == nsteps)
        for (size_t e = 0; e < st_total; e++) {
          const size_t i = e / tj, j = e % tj, r = (i0 + i) * DIM, rows = M - r < DIM ? M - r : DIM;
          gemmini_extended_mvout(C + r * ldc + (j0 + j) * DIM, acc_bit | full_bit | (acc_base + (i * TJ + j) * DIM), DIM, rows);
        }
    }
  }
  if (split) { gemmini_extended3_config_ld(lda * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 0); } // block stride back to DIM
  if (sparse) { gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0); }
#undef V2_A_SP
#undef V2_W_SP
#undef V2_BUILD_LOADS
#undef V2_ISSUE_LD
#undef V2_DRIP
#undef V2_META_OF
#undef v2_ntile
}

static void tiled_matmul_stream_dense_v2(int opts, size_t M, size_t N, size_t K, const elem_t * A, size_t lda,
    const elem_t * B, size_t ldb, acc_t * C, size_t ldc, size_t TI, size_t TJ) {
  nm_stream_v2_impl(0, opts, M, N, K, A, lda, B, ldb, NULL, C, ldc, TI, TJ);
}

static void tiled_matmul_nm_v2(int opts, size_t M, size_t N, size_t K, const elem_t * A, size_t lda,
    const elem_t * Bc, size_t ldb, const uint64_t * meta, acc_t * C, size_t ldc, size_t TI, size_t TJ) {
  nm_stream_v2_impl(1, opts, M, N, K, A, lda, Bc, ldb, meta, C, ldc, TI, TJ);
}

// ===========================================================================================================
// v3: same schedule as v1 (loads of step g+1 issued in one group before step g's computes; mvouts as v1), but
// the preload/compute stream is issued lean: every rs1/rs2 value is built once per block row (per i) and only
// address offsets are added in the inner loop, so a (preload, compute) pair costs ~8 instructions instead of ~20.
// opts bits: V2_BANKSPLIT (sparse: a_lo / a_hi in different banks, layout as v2), V3_METAWARM (sparse: the index
// tiles of step g+1 are pulled into the L2 by a small mvin into a junk spad region when step g's loads are
// issued, so the CPU's blocking L1 misses on them hit the L2 instead of DRAM).
#define V3_METAWARM 8
#define V3_HALFLOADS 16
#define V3_META_EACH 32 // sparse: each index tile right before its own preload (never more than 1 ahead)
#define V3_ISSUE_LD() do { \
    const v2_ld_t * l_ = &ld[ild++]; \
    if (l_->id == 0) { gemmini_extended_mvin(l_->dram, l_->sp, l_->cols, l_->rows); } \
    else { gemmini_extended_mvin2(l_->dram, l_->sp, l_->cols, l_->rows); } \
  } while (0)
#define V3_JUNK_ROW (BANK_ROWS - 128)
#ifdef V3_TRACE
// per step g: [0] before warm/loads, [1] before computes, [2] after computes, [3] after mvouts; each (cycle, ex, rdma)
static uint64_t v3_tr[160][4][3];
static size_t v3_ntr;
#define V3_T(g, k) do { if ((g) < 160) { v3_tr[g][k][0] = read_cycles(); v3_tr[g][k][1] = counter_read(0); v3_tr[g][k][2] = counter_read(1); } } while (0)
#else
#define V3_T(g, k) do { } while (0)
#endif

static inline __attribute__((always_inline)) void nm_stream_v3_impl(const int sparse, const int opts,
    size_t M, size_t N, size_t K, const elem_t * A, size_t lda, const elem_t * B, size_t ldb,
    const uint64_t * meta, acc_t * C, size_t ldc, size_t TI, size_t TJ) {
  const uint32_t acc_bit = (uint32_t)1 << (ADDR_LEN - 1), accum_bit = (uint32_t)1 << (ADDR_LEN - 2),
                 full_bit = (uint32_t)1 << (ADDR_LEN - 3);
  const int split = sparse && (opts & V2_BANKSPLIT), warm = sparse && (opts & V3_METAWARM), half = opts & V3_HALFLOADS, each = opts & V3_META_EACH;
  v2_ld_t ld[V2_MAXLD];
  size_t nld = 0, ild = 0;
  const size_t MT = (M + DIM - 1) / DIM, NT = N / DIM, KT = K / DIM;
  const size_t S = (KT + NM_STREAM_KSTEP - 1) / NM_STREAM_KSTEP;
  const size_t JB = (NT + TJ - 1) / TJ, nsteps = ((MT + TI - 1) / TI) * JB * S;
  const size_t mw = 2 * nm_meta_cmds(NM_M);
  const size_t a_slot = TI * NM_STREAM_KSTEP * DIM, w_slot = NM_STREAM_KSTEP * TJ * DIM;
  const size_t a_half = TI * (NM_STREAM_KSTEP / 2) * DIM, w_half = (NM_STREAM_KSTEP / 2) * TJ * DIM;
  const uint64_t SZ_FULL = ((uint64_t)DIM << (ADDR_LEN + 16)) | ((uint64_t)DIM << ADDR_LEN);
  NM_REQUIRE(M >= 1 && N % DIM == 0 && K % (sparse ? 2 * DIM : DIM) == 0 && K >= DIM);
  NM_REQUIRE(TI >= 1 && TI <= 8 && TJ >= 1 && TI * TJ * DIM <= ACC_ROWS / 2 && 2 * a_slot <= BANK_ROWS && 2 * w_slot <= BANK_ROWS);
  NM_REQUIRE(!split || (2 * a_half <= BANK_ROWS / 2 && BANK_ROWS / 2 + 2 * w_half <= V3_JUNK_ROW));
  NM_REQUIRE(!warm || split);
#define V3_A_SP(buf) ((uint32_t)(split ? (((buf) % 2) * 2 * BANK_ROWS + ((buf) / 2) * a_half) \
                                       : (((buf) % 2) * BANK_ROWS + ((buf) / 2) * a_slot)))
#define V3_W_SP(buf) ((uint32_t)(split ? ((2 - ((buf) % 2) * 2) * BANK_ROWS + BANK_ROWS / 2 + ((buf) / 2) * w_half) \
                                       : ((2 + (buf) % 2) * BANK_ROWS + ((buf) / 2) * w_slot)))
  if (sparse) {
    gemmini_nm_reset();
    gemmini_nm_config_ex(1, NO_ACTIVATION, 0, ACC_SCALE_IDENTITY, 1, 1);
  } else {
    gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0);
  }
  if (split) { gemmini_extended4_config_ld(lda * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, BANK_ROWS, 0); }
  else { gemmini_extended3_config_ld(lda * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 0); }
  gemmini_extended3_config_ld(ldb * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 1);
  if (warm) { gemmini_extended3_config_ld(MAX_BLOCK_LEN * DIM, MVIN_SCALE_IDENTITY, false, 2); } // index rows: 64 B apart
  gemmini_config_st(ldc * sizeof(acc_t));

  size_t st_blk = 0, st_next = 0, st_total = 0, st_per = 0;
  uint64_t pre2[8], cmp1[8], cmp2[8]; // per row tile i: preload rs2 base, compute rs1 / rs2 base

  for (size_t g = 0; g <= nsteps + 1; g++) {
    V3_T(g, 0);
    // ---- index warm-up for step g + 1 (2 steps ahead of its computes), then the loads of step g ----
    if (warm && g + 1 < nsteps) {
      const size_t gw = g + 1, bw = gw / S, sw = gw % S, jw0 = (bw % JB) * TJ, tjw = NT - jw0 < TJ ? NT - jw0 : TJ;
      const size_t kw0 = sw * NM_STREAM_KSTEP, kww = KT - kw0 < NM_STREAM_KSTEP ? KT - kw0 : NM_STREAM_KSTEP;
      // the bank that step g-1 (the one computing while these run) does not read: 3 for even, 1 for odd steps
      const uint32_t junk = (uint32_t)((g % 2 == 1 ? 3 : 1) * BANK_ROWS + V3_JUNK_ROW);
      const size_t lines = tjw * mw * 8 / 64; // 64 B rows of index data per compressed k row
      for (size_t c = 0; c < kww / 2; c++)
        for (size_t l0 = 0; l0 < lines; l0 += DIM) {
          const size_t nl = lines - l0 < DIM ? lines - l0 : DIM;
          gemmini_extended_mvin3(meta + ((kw0 / 2 + c) * NT + jw0) * mw + l0 * 8, junk, MAX_BLOCK_LEN * DIM, nl);
        }
    }
    if (g < nsteps) {
      const size_t blk = g / S, s = g % S, buf = g % NM_STREAM_NBUF;
      const size_t i0 = (blk / JB) * TI, j0 = (blk % JB) * TJ;
      const size_t ti = MT - i0 < TI ? MT - i0 : TI, tj = NT - j0 < TJ ? NT - j0 : TJ;
      const size_t k0 = s * NM_STREAM_KSTEP, kw = KT - k0 < NM_STREAM_KSTEP ? KT - k0 : NM_STREAM_KSTEP;
      const size_t wt = sparse ? kw / 2 : kw, wrow0 = sparse ? k0 / 2 * DIM : k0 * DIM;
      nld = 0; ild = 0;
      for (size_t i = 0; i < ti; i++) {
        const size_t r = (i0 + i) * DIM, rows = M - r < DIM ? M - r : DIM;
        if (split) {
          for (size_t c = 0; c < kw / 2; c++)
            ld[nld++] = (v2_ld_t){ A + r * lda + (k0 + 2 * c) * DIM, V3_A_SP(buf) + (i * (NM_STREAM_KSTEP / 2) + c) * DIM, 2 * DIM, rows, 0 };
        } else {
          ld[nld++] = (v2_ld_t){ A + r * lda + k0 * DIM, V3_A_SP(buf) + i * NM_STREAM_KSTEP * DIM, kw * DIM, rows, 0 };
        }
      }
      for (size_t q = 0; q < wt; q++)
        for (size_t jj = 0; jj < tj; jj += MAX_BLOCK_LEN) {
          const size_t blocks = tj - jj < MAX_BLOCK_LEN ? tj - jj : MAX_BLOCK_LEN;
          ld[nld++] = (v2_ld_t){ B + (wrow0 + q * DIM) * ldb + (j0 + jj) * DIM, V3_W_SP(buf) + (q * TJ + jj) * DIM, blocks * DIM, DIM, 1 };
        }
      // HALFLOADS: step 0 has nothing to overlap with, so it goes out whole
      const size_t first = (half && g > 0) ? (nld + 1) / 2 : nld;
      while (ild < first) V3_ISSUE_LD();
    }
    V3_T(g, 1);
    if (g == 0 || g > nsteps) continue;

    // ---- preload/computes of step h = g - 1, lean ----
    const size_t h = g - 1, blk = h / S, s = h % S, buf = h % NM_STREAM_NBUF;
    const size_t i0 = (blk / JB) * TI, j0 = (blk % JB) * TJ;
    const size_t ti = MT - i0 < TI ? MT - i0 : TI, tj = NT - j0 < TJ ? NT - j0 : TJ;
    const size_t k0 = s * NM_STREAM_KSTEP, kw = KT - k0 < NM_STREAM_KSTEP ? KT - k0 : NM_STREAM_KSTEP;
    const uint32_t acc_base = (uint32_t)((blk % 2) * (ACC_ROWS / 2));
    const uint32_t a_sp = V3_A_SP(buf), w_sp = V3_W_SP(buf);
    const size_t nq = sparse ? kw / 2 : kw;                 // weight-tile rows in this step
    const size_t a_q = split ? DIM : sparse ? 2 * DIM : DIM; // A address step per weight-tile row
    const size_t a_i = split ? (NM_STREAM_KSTEP / 2) * DIM : NM_STREAM_KSTEP * DIM; // A address step per row tile
    for (size_t i = 0; i < ti; i++) {
      const size_t r = (i0 + i) * DIM, rows = M - r < DIM ? M - r : DIM;
      const uint64_t szr = ((uint64_t)rows << (ADDR_LEN + 16)) | ((uint64_t)DIM << ADDR_LEN);
      const uint32_t alo = a_sp + (uint32_t)(i * a_i);
      pre2[i] = szr | (acc_base + i * TJ * DIM);
      cmp1[i] = szr | alo;
      cmp2[i] = sparse ? (szr | (split ? alo + BANK_ROWS : alo + DIM)) : (SZ_FULL | GARBAGE_ADDR);
    }
    const uint64_t pre1_g = SZ_FULL | GARBAGE_ADDR;
    const uint64_t * mp = sparse ? meta + ((k0 / 2) * NT + j0) * mw : NULL;
    size_t u = 0; // tiles of this step in preload order (q major, j minor), for the index batches
    const size_t ntile = nq * tj;
    for (size_t q = 0; q < nq; q++) {
      if (q == (nq + 1) / 2 || (nq == 1 && q == 0 && 0)) { while (ild < nld) V3_ISSUE_LD(); } // HALFLOADS: rest of step g's mvins
      const uint64_t cfl = (uint64_t)(acc_bit | ((sparse ? k0 / 2 : k0) + q > 0 ? accum_bit : 0));
      const uint64_t aoff = q * a_q;
      for (size_t j = 0; j < tj; j++, u++) {
        if (sparse && (each || u % NM_META_FIFO_DEPTH == 0)) {
          // the next batch of up to 4 index tiles, as v1 (tile u is (q, j): meta tile (k0/2 + q, j0 + j))
          const size_t u1 = each ? u + 1 : (u + NM_META_FIFO_DEPTH < ntile ? u + NM_META_FIFO_DEPTH : ntile);
          // tile v = (bq, bj), stepped from (q, j) without divisions (Rocket's divider is iterative)
          size_t bq = q, bj = j;
          for (size_t v = u; v < u1; v++) {
            const uint64_t * m = mp + (bq * NT + bj) * mw;
            if (++bj == tj) { bj = 0; bq++; }
#pragma GCC unroll 8
            for (int w = 0; w < 2 * nm_meta_cmds(NM_M); w += 2) ROCC_INSTRUCTION_RS1_RS2(XCUSTOM_ACC, m[w], m[w + 1], k_NM_META);
          }
        }
        const uint64_t coff = cfl | (j * DIM);
        ROCC_INSTRUCTION_RS1_RS2(XCUSTOM_ACC, SZ_FULL | (w_sp + (q * TJ + j) * DIM), pre2[0] + coff, k_PRELOAD);
        ROCC_INSTRUCTION_RS1_RS2(XCUSTOM_ACC, cmp1[0] + aoff, cmp2[0] + (sparse ? aoff : 0), k_COMPUTE_PRELOADED);
        for (size_t i = 1; i < ti; i++) {
          ROCC_INSTRUCTION_RS1_RS2(XCUSTOM_ACC, pre1_g, pre2[i] + coff, k_PRELOAD);
          ROCC_INSTRUCTION_RS1_RS2(XCUSTOM_ACC, cmp1[i] + aoff, cmp2[i] + (sparse ? aoff : 0), k_COMPUTE_ACCUMULATE);
        }
      }
    }

    while (ild < nld) V3_ISSUE_LD(); // (nq == 1, or HALFLOADS off: nothing left)
    V3_T(g, 2);
    // ---- mvouts: as v1 ----
    {
      const size_t n_out = g == nsteps ? st_total - st_next : (st_per < st_total - st_next ? st_per : st_total - st_next);
      const size_t si0 = (st_blk / JB) * TI, sj0 = (st_blk % JB) * TJ;
      const size_t stj = NT - sj0 < TJ ? NT - sj0 : TJ;
      const uint32_t sbase = (uint32_t)((st_blk % 2) * (ACC_ROWS / 2));
      size_t i = st_next / stj, j = st_next % stj; // then stepped: no division per mvout (iterative divider)
      for (size_t e = st_next; e < st_next + n_out; e++, j = j + 1 == stj ? (i++, 0) : j + 1) {
        const size_t r = (si0 + i) * DIM, rows = M - r < DIM ? M - r : DIM;
        gemmini_extended_mvout(C + r * ldc + (sj0 + j) * DIM, acc_bit | full_bit | (sbase + (i * TJ + j) * DIM), DIM, rows);
      }
      st_next += n_out;
    }
    if (s == S - 1) {
      st_blk = blk; st_next = 0; st_total = ti * tj; st_per = (st_total + S - 1) / S;
      if (g == nsteps)
        for (size_t i = 0; i < ti; i++) for (size_t j = 0; j < tj; j++) {
          const size_t r = (i0 + i) * DIM, rows = M - r < DIM ? M - r : DIM;
          gemmini_extended_mvout(C + r * ldc + (j0 + j) * DIM, acc_bit | full_bit | (acc_base + (i * TJ + j) * DIM), DIM, rows);
        }
    }
    V3_T(g, 3);
#ifdef V3_TRACE
    v3_ntr = g + 1;
#endif
  }
  if (split) { gemmini_extended3_config_ld(lda * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 0); }
  if (sparse) { gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0); }
#undef V3_A_SP
#undef V3_W_SP
#undef V3_ISSUE_LD
}

static void tiled_matmul_stream_dense_v3(int opts, size_t M, size_t N, size_t K, const elem_t * A, size_t lda,
    const elem_t * B, size_t ldb, acc_t * C, size_t ldc, size_t TI, size_t TJ) {
  nm_stream_v3_impl(0, opts, M, N, K, A, lda, B, ldb, NULL, C, ldc, TI, TJ);
}

static void tiled_matmul_nm_v3(int opts, size_t M, size_t N, size_t K, const elem_t * A, size_t lda,
    const elem_t * Bc, size_t ldb, const uint64_t * meta, acc_t * C, size_t ldc, size_t TI, size_t TJ) {
  nm_stream_v3_impl(1, opts, M, N, K, A, lda, Bc, ldb, meta, C, ldc, TI, TJ);
}

#endif // NM_STREAM_V2_H
