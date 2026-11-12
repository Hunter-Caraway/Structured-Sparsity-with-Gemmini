// tiled_matmul_nm_v2.h: improved streaming tiler for the n:m sparse Gemmini (investigate agent, 2026-11-09).
// Include AFTER include/gemmini_nm.h (uses its protocol macros, NM_STREAM_KSTEP / NM_STREAM_NBUF and nm_stream_tiles()).
// Same interface and schedule as tiled_matmul_nm() / tiled_matmul_stream_dense() in gemmini_nm.h (v1), with:
//  1. sparse: a_lo and a_hi in DIFFERENT scratchpad banks. v1 puts them in the same bank; the EX then reads A and B
//     on alternate cycles (ExecuteController.scala:395-412), 32 instead of 16 cycles per sparse compute, which
//     cancels the halving of the compute count. Each A tile pair (2c, 2c+1) is moved in by one 2-tile mvin with
//     block_mvin_stride = BANK_ROWS. Layout: even steps A_lo bank 0, A_hi bank 1, W bank 2 (rows >= BANK_ROWS/2);
//     odd steps A_lo bank 2, A_hi bank 3, W bank 0. The next step's mvins never write a bank the array is reading
//     heavily (spad banks are single-ported, DMA writes win: Scratchpad.scala:119-120).
//  2. both: lean issue. rs1/rs2 of every preload/compute are built once per row tile and only offsets are added in
//     the inner loop (11 instead of 16 instructions per pair); the Rocket core issues ~1 instruction/cycle and
//     the array needs a pair every 16 cycles, so instruction count per command matters.
//  3. sparse, by default (NMV2_METAWARM): the index tiles of step g+1 are pulled into the L2 with a small mvin
//     to a junk spad row when step g's mvins are issued, so the CPU's (blocking) L1 misses on them hit the L2.
// Measured on Verilator (experiments/streaming/worklogs/investigate.md): small 2:4 29,869 -> 21,801 cycles,
// small 4:8 34,518 -> 23,866, dense small 18,538 -> 17,143.
// opts: NMV2_DEFAULT picks the measured best (sparse: BANKSPLIT + METAWARM); other bits as documented
// in nm_stream_v2.h (HALFLOADS and META_EACH lost on small/edge and are not on by default).
// changed: Fix A (2026-11-11). NMV2_SPADIDX (tiled_matmul_nm_v2_spad(), needs a Fix A chip): the index tiles, in the
// scratchpad format (nm_pack_meta_spad), are mvin'd with each step's loads (first, mvin3, 16 byte rows) into the bank
// that step's computes do not read (bank 3 for even steps, 1 for odd, from row BANK_ROWS/4), and each batch of up to
// 4 is one gemmini_nm_load_spad() issued early: right after the compute_preloaded of the previous batch's last tile
// (for a step's first batch: of the previous step's last tile), so the index loader can fetch the rows while the
// remaining GARBAGE-preload pairs run. Needs BANKSPLIT; replaces METAWARM (the CPU no longer touches index data).

#ifndef TILED_MATMUL_NM_V2_H
#define TILED_MATMUL_NM_V2_H

#define NMV2_BANKSPLIT 1
#define NMV2_METAWARM 8
#define NMV2_HALFLOADS 16
#define NMV2_META_EACH 32
#define NMV2_SPADIDX 64 // changed: Fix A
#define NMV2_IDX_ROW (BANK_ROWS / 4) // changed: Fix A, first index row in banks 1 / 3 (A_hi uses rows < 2*a_half <= 512)
#define NMV2_DEFAULT (-1)
#define NMV2_MAXLD 64
#define NMV2_JUNK_ROW (BANK_ROWS - 128)
typedef struct { const elem_t * dram; uint32_t sp; uint16_t cols; uint16_t rows; uint8_t id; } nmv2_ld_t;
#define NMV2_ISSUE_LD() do { \
    const nmv2_ld_t * l_ = &ld[ild++]; \
    if (l_->id == 0) { gemmini_extended_mvin(l_->dram, l_->sp, l_->cols, l_->rows); } \
    else { gemmini_extended_mvin2(l_->dram, l_->sp, l_->cols, l_->rows); } \
  } while (0)

static inline __attribute__((always_inline)) void nm_stream_v2k_impl(const int sparse, const int opts,
    size_t M, size_t N, size_t K, const elem_t * A, size_t lda, const elem_t * B, size_t ldb,
    const uint64_t * meta, const uint8_t * meta_sp, acc_t * C, size_t ldc, size_t TI, size_t TJ) {
  const uint32_t acc_bit = (uint32_t)1 << (ADDR_LEN - 1), accum_bit = (uint32_t)1 << (ADDR_LEN - 2),
                 full_bit = (uint32_t)1 << (ADDR_LEN - 3);
  const int split = sparse && (opts & NMV2_BANKSPLIT), warm = sparse && (opts & NMV2_METAWARM), half = opts & NMV2_HALFLOADS, each = opts & NMV2_META_EACH;
  const int spadidx = sparse && (opts & NMV2_SPADIDX); // changed: Fix A
  nmv2_ld_t ld[NMV2_MAXLD];
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
  NM_REQUIRE(!split || (2 * a_half <= BANK_ROWS / 2 && BANK_ROWS / 2 + 2 * w_half <= NMV2_JUNK_ROW));
  NM_REQUIRE(!warm || split);
  const size_t i_slot = (NM_STREAM_KSTEP / 2) * TJ * NM_SPAD_ROWS_PER_TILE; // changed: Fix A, index rows per buffer
  NM_REQUIRE(!spadidx || (split && !warm && !each && 2 * a_half <= NMV2_IDX_ROW && NMV2_IDX_ROW + 2 * i_slot <= NMV2_JUNK_ROW));
#define NMV2_I_SP(buf) ((uint32_t)(((buf) % 2 == 0 ? 3 : 1) * BANK_ROWS + NMV2_IDX_ROW + ((buf) / 2) * i_slot))
#define NMV2_A_SP(buf) ((uint32_t)(split ? (((buf) % 2) * 2 * BANK_ROWS + ((buf) / 2) * a_half) \
                                       : (((buf) % 2) * BANK_ROWS + ((buf) / 2) * a_slot)))
#define NMV2_W_SP(buf) ((uint32_t)(split ? ((2 - ((buf) % 2) * 2) * BANK_ROWS + BANK_ROWS / 2 + ((buf) / 2) * w_half) \
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
  if (spadidx) { gemmini_extended3_config_ld(DIM * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 2); } // Fix A: 16 B rows
  gemmini_config_st(ldc * sizeof(acc_t));

  size_t st_blk = 0, st_next = 0, st_total = 0, st_per = 0;
  uint64_t pre2[8], cmp1[8], cmp2[8]; // per row tile i: preload rs2 base, compute rs1 / rs2 base
  uint32_t nx_isp = 0; size_t nx_ntile = 0; // Fix A: index rows and tile count of the step whose loads went out last

  for (size_t g = 0; g <= nsteps + 1; g++) {
    // ---- index warm-up for step g + 1 (2 steps ahead of its computes), then the loads of step g ----
    if (warm && g + 1 < nsteps) {
      const size_t gw = g + 1, bw = gw / S, sw = gw % S, jw0 = (bw % JB) * TJ, tjw = NT - jw0 < TJ ? NT - jw0 : TJ;
      const size_t kw0 = sw * NM_STREAM_KSTEP, kww = KT - kw0 < NM_STREAM_KSTEP ? KT - kw0 : NM_STREAM_KSTEP;
      // the bank that step g-1 (the one computing while these run) does not read: 3 for even, 1 for odd steps
      const uint32_t junk = (uint32_t)((g % 2 == 1 ? 3 : 1) * BANK_ROWS + NMV2_JUNK_ROW);
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
      if (spadidx) { // Fix A: index tile (c, j) of step g at NMV2_I_SP(buf) + (c * tj + j) * R, one run of tj tiles per c
        for (size_t c = 0; c < kw / 2; c++)
          nm_mvin_meta_spad(meta_sp + ((k0 / 2 + c) * NT + j0) * NM_META_SPAD_BYTES,
                            NMV2_I_SP(buf) + (uint32_t)(c * tj * NM_SPAD_ROWS_PER_TILE), tj, 2);
        nx_isp = NMV2_I_SP(buf); nx_ntile = (kw / 2) * tj;
      }
      nld = 0; ild = 0;
      for (size_t i = 0; i < ti; i++) {
        const size_t r = (i0 + i) * DIM, rows = M - r < DIM ? M - r : DIM;
        if (split) {
          for (size_t c = 0; c < kw / 2; c++)
            ld[nld++] = (nmv2_ld_t){ A + r * lda + (k0 + 2 * c) * DIM, NMV2_A_SP(buf) + (i * (NM_STREAM_KSTEP / 2) + c) * DIM, 2 * DIM, rows, 0 };
        } else {
          ld[nld++] = (nmv2_ld_t){ A + r * lda + k0 * DIM, NMV2_A_SP(buf) + i * NM_STREAM_KSTEP * DIM, kw * DIM, rows, 0 };
        }
      }
      for (size_t q = 0; q < wt; q++)
        for (size_t jj = 0; jj < tj; jj += MAX_BLOCK_LEN) {
          const size_t blocks = tj - jj < MAX_BLOCK_LEN ? tj - jj : MAX_BLOCK_LEN;
          ld[nld++] = (nmv2_ld_t){ B + (wrow0 + q * DIM) * ldb + (j0 + jj) * DIM, NMV2_W_SP(buf) + (q * TJ + jj) * DIM, blocks * DIM, DIM, 1 };
        }
      // HALFLOADS: step 0 has nothing to overlap with, so it goes out whole
      const size_t first = (half && g > 0) ? (nld + 1) / 2 : nld;
      while (ild < first) NMV2_ISSUE_LD();
    }
    if (g == 0 || g > nsteps) continue;

    // ---- preload/computes of step h = g - 1, lean ----
    const size_t h = g - 1, blk = h / S, s = h % S, buf = h % NM_STREAM_NBUF;
    const size_t i0 = (blk / JB) * TI, j0 = (blk % JB) * TJ;
    const size_t ti = MT - i0 < TI ? MT - i0 : TI, tj = NT - j0 < TJ ? NT - j0 : TJ;
    const size_t k0 = s * NM_STREAM_KSTEP, kw = KT - k0 < NM_STREAM_KSTEP ? KT - k0 : NM_STREAM_KSTEP;
    const uint32_t acc_base = (uint32_t)((blk % 2) * (ACC_ROWS / 2));
    const uint32_t a_sp = NMV2_A_SP(buf), w_sp = NMV2_W_SP(buf);
    const uint32_t isp = spadidx ? NMV2_I_SP(buf) : 0; // Fix A
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
      if (q == (nq + 1) / 2 || (nq == 1 && q == 0 && 0)) { while (ild < nld) NMV2_ISSUE_LD(); } // HALFLOADS: rest of step g's mvins
      const uint64_t cfl = (uint64_t)(acc_bit | ((sparse ? k0 / 2 : k0) + q > 0 ? accum_bit : 0));
      const uint64_t aoff = q * a_q;
      for (size_t j = 0; j < tj; j++, u++) {
        if (spadidx && h == 0 && u == 0) gemmini_nm_load_spad(isp, ntile < NM_META_FIFO_DEPTH ? ntile : NM_META_FIFO_DEPTH);
        if (sparse && !spadidx && (each || u % NM_META_FIFO_DEPTH == 0)) {
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
        if (spadidx && ((u + 1) % NM_META_FIFO_DEPTH == 0 || u + 1 == ntile)) {
          // Fix A: this batch is all popped and its last compute issued: load the next batch (of this or the next step)
          if (u + 1 < ntile) gemmini_nm_load_spad(isp + (uint32_t)((u + 1) * NM_SPAD_ROWS_PER_TILE),
                                                  ntile - u - 1 < NM_META_FIFO_DEPTH ? ntile - u - 1 : NM_META_FIFO_DEPTH);
          else if (g < nsteps) gemmini_nm_load_spad(nx_isp, nx_ntile < NM_META_FIFO_DEPTH ? nx_ntile : NM_META_FIFO_DEPTH);
        }
        for (size_t i = 1; i < ti; i++) {
          ROCC_INSTRUCTION_RS1_RS2(XCUSTOM_ACC, pre1_g, pre2[i] + coff, k_PRELOAD);
          ROCC_INSTRUCTION_RS1_RS2(XCUSTOM_ACC, cmp1[i] + aoff, cmp2[i] + (sparse ? aoff : 0), k_COMPUTE_ACCUMULATE);
        }
      }
    }

    while (ild < nld) NMV2_ISSUE_LD(); // (nq == 1, or HALFLOADS off: nothing left)
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
  }
  if (split) { gemmini_extended3_config_ld(lda * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 0); }
  if (sparse) { gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0); }
#undef NMV2_A_SP
#undef NMV2_W_SP
#undef NMV2_I_SP
#undef NMV2_ISSUE_LD
}


// opts = NMV2_DEFAULT (or a bit mask). TI/TJ as for v1 (nm_stream_tiles()).
// always_inline: as a separate (constprop) function GCC spills registers in the issue loops (+14% instructions in
// the sparse call on Spike, ~7-9% slower on Verilator); inlined into the caller it matches nm_stream_v2.h's v3.
static inline __attribute__((always_inline)) void tiled_matmul_stream_dense_v2(int opts, size_t M, size_t N, size_t K, const elem_t * A, size_t lda,
    const elem_t * B, size_t ldb, acc_t * C, size_t ldc, size_t TI, size_t TJ) {
  nm_stream_v2k_impl(0, opts == NMV2_DEFAULT ? 0 : opts, M, N, K, A, lda, B, ldb, NULL, NULL, C, ldc, TI, TJ);
}

static inline __attribute__((always_inline)) void tiled_matmul_nm_v2(int opts, size_t M, size_t N, size_t K, const elem_t * A, size_t lda,
    const elem_t * Bc, size_t ldb, const uint64_t * meta, acc_t * C, size_t ldc, size_t TI, size_t TJ) {
  const int o = opts == NMV2_DEFAULT ? (NMV2_BANKSPLIT | NMV2_METAWARM) : opts;
  nm_stream_v2k_impl(1, o & ~NMV2_SPADIDX, M, N, K, A, lda, Bc, ldb, meta, NULL, C, ldc, TI, TJ);
}

// changed: Fix A. meta_sp: index tiles in the scratchpad format, tile (t, jt) at meta_sp + (t * (N/DIM) + jt) *
// NM_META_SPAD_BYTES (16-byte aligned). opts = NMV2_DEFAULT: BANKSPLIT + SPADIDX; otherwise SPADIDX is added.
static inline __attribute__((always_inline)) void tiled_matmul_nm_v2_spad(int opts, size_t M, size_t N, size_t K, const elem_t * A, size_t lda,
    const elem_t * Bc, size_t ldb, const uint8_t * meta_sp, acc_t * C, size_t ldc, size_t TI, size_t TJ) {
  const int o = opts == NMV2_DEFAULT ? (NMV2_BANKSPLIT | NMV2_SPADIDX) : (opts | NMV2_SPADIDX);
  nm_stream_v2k_impl(1, o, M, N, K, A, lda, Bc, ldb, NULL, meta_sp, C, ldc, TI, TJ);
}

#endif // TILED_MATMUL_NM_V2_H
