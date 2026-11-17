// micro_loop.c: bank-split-fix-spec.md section 8. Replays the sparse LOOP_WS execute stream (fix-b-spec 1.5) with
// per-tile instructions, with the activations hand-placed in different scratchpad layouts, to measure how much putting
// a_lo and a_hi in different banks cuts the array time. Derived from micro2.c tight(): every command's rs1/rs2 is
// precomputed (32-bit address words, so the sparse streams stay L1-hot), 2 loads + 1 rocc each. It measures the execute side only (no LdA/LdB mvins in the window).
//
// problem: C (I*16 x 96) = A (I*16 x 768) * W (768 x 96, n:m pruned), i.e. a loop call of I x J=6 x K=48 tiles
// (kb = 24 compressed tiles, I*144 computes). Data and the reference C come from the host (gen_micro_loop.py -> data.h).
// order (as LoopMatmulExecute): for k' for j for i: preload (real B at i == 0, GARBAGE else; C at acc tile (i, j),
// accumulate when k' != 0), compute_preloaded at i == 0 else compute_accumulated, rs1 = a_lo, rs2 = a_hi.
// index tiles: Fix A scratchpad LOADs (funct 26 rd 2) on the loop's rule (fix-b-spec 1.5): 4 tiles before tile 0,
// then after the last compute of tile u, if loaded - (u+1) <= 2, a LOAD of 2.
// layouts (rows; S = BANK_ROWS; E = even K tiles = a_lo, O = odd K tiles = a_hi; Ea = I*24*16, Bsz = 24*6*16):
//   L0   today's loop: A tile (i,c) at (i*48+c)*16 (a_hi = a_lo + 16, same bank), B below the index region of the half
//   L0i  L0 with the index rows where the loop keeps them ([2S - idx, 2S), bank 1); L0 uses a bank-3 staging area
//   L1   E bank 0, O bank 1, B in bank 0 after E (tiles that do not fit go to bank 2; counted in the output)
//   L2   E bank 0, O bank 1, B in bank 1 after O (overflow to bank 2 as L1)
//   L3   design 1: E at 0, B at Ea (straddles banks 0/1), O at max(S, Ea + Bsz); index rows bank-3 staging
//   L3i  L3 with the index rows at [2S - idx, 2S) as design 1 keeps them
//   L4   E bank 0, O bank 1, B bank 2 (upper bound: no B conflicts)
//   dense  dense mode, W pruned (48 K tiles, I*288 computes), A bank 0, W from bank 1 on: the 16-cycle ceiling
// per case: place operands (untimed), poison the accumulator tiles and C, run the timed stream (rep 0 warm-up,
// rep 1 measured), mvout C, compare all of it to the reference. a line prints "verified" or "FAILED".
// timed window: counters reset .. last command issued .. gemmini_fence() (micro2's convention).
// build: -DNM_N/-DNM_M (== data.h), -DMICRO_LOOP_DATA=\"<.../data.h>\". volatile flags (the .text is the same):
//   -DCPU_REF       also check the host reference with nm_ref_sparse / nm_ref_dense and nm_pack_meta_spad on the
//                   CPU (minutes on Spike, far too slow for RTL)
//   -DSHAPE_MASK=b  1: I=5 (qkv tile), 2: I=3 (qkv remainder), 4: I=1 (preload-heavy); default 3
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include "include/gemmini_testutils.h"
#include "include/gemmini_counter.h"
#include "include/gemmini_nm.h"
#include MICRO_LOOP_DATA

#if D_NM_N != NM_N || D_NM_M != NM_M
#error "data header pattern differs from -DNM_N/-DNM_M"
#endif

#ifdef CPU_REF
static volatile int cpu_ref = 0x101;
#else
static volatile int cpu_ref = 0x100;
#endif
#ifndef SHAPE_MASK
#define SHAPE_MASK 3
#endif
static volatile int shape_mask = 0x100 | (SHAPE_MASK);

#define J_T 6
#define K_T 48
#define KB (K_T / 2)
#define I_MAX 5
#define R_IDX NM_SPAD_ROWS_PER_TILE
#define NTILE (KB * J_T)
#define S_ROWS BANK_ROWS
_Static_assert(D_M == I_MAX * DIM && D_K == K_T * DIM && D_N == J_T * DIM, "data.h dimensions");
_Static_assert(D_IDXSP_BYTES == NTILE * NM_META_SPAD_BYTES, "data.h index tiles");

enum { L0, L0I, L1, L2, L3, L3I, L4, LDENSE, NLAYOUT };
static const char * layout_names[NLAYOUT] = { "L0", "L0i", "L1", "L2", "L3", "L3i", "L4", "dense" };

#define NCTR 6
static const int ctr_ids[NCTR] = { EXE_ACTIVE_CYCLE, EXE_PRELOAD_HAZ_CYCLE, EXE_OVERLAP_HAZ_CYCLE,
  SCRATCHPAD_A_WAIT_CYCLE, SCRATCHPAD_B_WAIT_CYCLE, RESERVATION_STATION_ACTIVE_CYCLES };
static const char * ctr_names[NCTR] = { "ex_active", "pre_haz", "overlap_haz", "spA_wait", "spB_wait", "rs_busy" };

// the most commands: dense I_MAX * 288 computes x (preload, compute), 4 words each
#define OPS_MAX (I_MAX * K_T * J_T * 4 + 2 * NTILE)
static uint32_t ops[OPS_MAX] __attribute__((aligned(64)));  // addresses; the rows/cols field is OR'd in at issue
static uint8_t ldf[K_T * J_T];
static acc_t c_out[D_M][D_N] __attribute__((aligned(64)));
static acc_t acc_poison[DIM][DIM] __attribute__((aligned(64)));
#define POISON ((acc_t)0x5A5A5A5A)

// where one case keeps its operands (scratchpad rows)
typedef struct {
  uint32_t a_lo[I_MAX][KB], a_hi[I_MAX][KB];  // sparse: rs1 / rs2 of compute (i, k')
  uint32_t a_dense[I_MAX][K_T];               // dense: A tile (i, k)
  uint32_t b[K_T * J_T];                      // weight tile u = k' * J + j (dense: k * J + j)
  uint32_t idx_base;
  int b_spill;                                // B tiles placed in bank 2 because the chosen bank was full
} layout_t;
static layout_t lay;

static void make_layout(int ly, int I) {
  const uint32_t S = S_ROWS, Ea = (uint32_t)(I * KB * DIM), Bsz = (uint32_t)(NTILE * DIM), idx = (uint32_t)(NTILE * R_IDX);
  const uint32_t idx_top = 2 * S - idx;
  lay.b_spill = 0;
  lay.idx_base = (ly == L0I || ly == L3I) ? idx_top : 3 * S;
  if (ly == LDENSE) {
    for (int i = 0; i < I; i++) for (int k = 0; k < K_T; k++) lay.a_dense[i][k] = (uint32_t)((i * K_T + k) * DIM);
    for (int u = 0; u < K_T * J_T; u++) lay.b[u] = S + (uint32_t)(u * DIM);
    return;
  }
  uint32_t e = 0, o = S, b0 = 0, cap = NTILE;
  switch (ly) {
    case L0: case L0I: b0 = idx_top - Bsz; break;
    case L1: b0 = Ea; cap = (S - Ea) / DIM; break;
    case L2: b0 = S + Ea; cap = (S - Ea) / DIM; break;
    case L3: case L3I: b0 = Ea; o = Ea + Bsz > S ? Ea + Bsz : S; break;
    case L4: b0 = 2 * S; break;
  }
  for (int i = 0; i < I; i++)
    for (int k = 0; k < KB; k++) {
      if (ly == L0 || ly == L0I) {
        lay.a_lo[i][k] = (uint32_t)((i * K_T + 2 * k) * DIM);
        lay.a_hi[i][k] = lay.a_lo[i][k] + DIM;
      } else {
        lay.a_lo[i][k] = e + (uint32_t)((i * KB + k) * DIM);
        lay.a_hi[i][k] = o + (uint32_t)((i * KB + k) * DIM);
      }
    }
  for (int u = 0; u < NTILE; u++) {
    if ((uint32_t)u < cap) lay.b[u] = b0 + (uint32_t)(u * DIM);
    else { lay.b[u] = 2 * S + (uint32_t)((u - (int)cap) * DIM); lay.b_spill++; }
  }
}

// layout sanity (any overlap would give wrong C anyway, but say why): regions inside 4 banks, a_lo / a_hi banks
static int layout_ok(int ly, int I) {
  const uint32_t lim = BANK_NUM * BANK_ROWS;
  if (ly == LDENSE) return lay.b[K_T * J_T - 1] + DIM <= lim;
  for (int i = 0; i < I; i++)
    for (int k = 0; k < KB; k++) {
      const int same = lay.a_lo[i][k] / S_ROWS == lay.a_hi[i][k] / S_ROWS;
      if (same != (ly == L0 || ly == L0I)) return 0;
      if (lay.a_hi[i][k] + DIM > lay.idx_base && lay.a_hi[i][k] < lay.idx_base + NTILE * R_IDX) return 0;
    }
  return lay.idx_base + NTILE * R_IDX <= lim;
}

// untimed: A, B (compressed or dense) and index tiles into the scratchpad
static void place(int ly, int I) {
  const int dense = ly == LDENSE;
  gemmini_extended3_config_ld(D_K * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 0);
  gemmini_extended3_config_ld(D_N * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 1);
  gemmini_extended3_config_ld(DIM * sizeof(elem_t), MVIN_SCALE_IDENTITY, false, 2);
  for (int i = 0; i < I; i++)
    for (int c = 0; c < K_T; c++) {
      const elem_t * src = d_A + (size_t)i * DIM * D_K + (size_t)c * DIM;
      const uint32_t dst = dense ? lay.a_dense[i][c] : (c % 2 ? lay.a_hi[i][c / 2] : lay.a_lo[i][c / 2]);
      gemmini_extended_mvin(src, dst, DIM, DIM);
    }
  const int nb = dense ? K_T * J_T : NTILE;
  for (int u = 0; u < nb; u++) {
    const int k = u / J_T, j = u % J_T;
    const elem_t * src = (dense ? d_W : d_WC) + (size_t)k * DIM * D_N + (size_t)j * DIM;
    gemmini_extended_mvin2(src, lay.b[u], DIM, DIM);
  }
  if (!dense) nm_mvin_meta_spad(d_IDXSP, lay.idx_base, NTILE, 2);
  gemmini_fence();
}

// untimed: poison the accumulator tiles the case writes, and C in dram
static void poison(int I) {
  const uint32_t acc = (uint32_t)1 << (ADDR_LEN - 1);
  gemmini_extended3_config_ld(DIM * sizeof(acc_t), MVIN_SCALE_IDENTITY, false, 2);
  for (int t = 0; t < I * J_T; t++) gemmini_extended_mvin3(&acc_poison[0][0], acc | (uint32_t)(t * DIM), DIM, DIM);
  for (int y = 0; y < D_M; y++) for (int x = 0; x < D_N; x++) c_out[y][x] = POISON;
  gemmini_fence();
}

// all of C (I*16 x 96) against the host reference
static int check(int I) {
  const uint32_t acc = (uint32_t)1 << (ADDR_LEN - 1), full = (uint32_t)1 << (ADDR_LEN - 3);
  gemmini_config_st(D_N * sizeof(acc_t));
  for (int i = 0; i < I; i++)
    for (int j = 0; j < J_T; j++)
      gemmini_extended_mvout(&c_out[i * DIM][j * DIM], acc | full | (uint32_t)((i * J_T + j) * DIM), DIM, DIM);
  gemmini_fence();
  int bad = 0;
  for (int y = 0; y < I * DIM; y++)
    for (int x = 0; x < D_N; x++)
      if (c_out[y][x] != d_C[y * D_N + x]) {
        if (!bad) printf("  mismatch at (%d,%d): got %d want %d\n", y, x, (int)c_out[y][x], (int)d_C[y * D_N + x]);
        bad++;
      }
  return bad;
}

// the command stream of one case into ops[] / ldf[]
static size_t build_ops(int ly, int I) {
  const uint32_t acc = (uint32_t)1 << (ADDR_LEN - 1), accum = (uint32_t)1 << (ADDR_LEN - 2);
  size_t n = 0;
  if (ly == LDENSE) {
    for (int k = 0; k < K_T; k++)
      for (int j = 0; j < J_T; j++) {
        ldf[k * J_T + j] = 0;
        for (int i = 0; i < I; i++) {
          const uint32_t c = acc | (k ? accum : 0) | (uint32_t)((i * J_T + j) * DIM);
          ops[n++] = i == 0 ? lay.b[k * J_T + j] : GARBAGE_ADDR; ops[n++] = c;
          ops[n++] = lay.a_dense[i][k]; ops[n++] = GARBAGE_ADDR;
        }
      }
    return n;
  }
  int loaded = 0;
  for (int u = 0; u < NTILE; u++) {
    const int k = u / J_T, j = u % J_T;
    int ln = 0;
    if (u == 0) ln = NTILE < 4 ? NTILE : 4;
    else if (loaded < NTILE && loaded - u <= 2) ln = NTILE - loaded < 2 ? NTILE - loaded : 2;  // after tile u-1: pre = u
    ldf[u] = (uint8_t)(ln != 0);
    if (ln) { ops[n++] = lay.idx_base + (uint32_t)(loaded * R_IDX); ops[n++] = (uint32_t)ln; loaded += ln; }
    for (int i = 0; i < I; i++) {
      const uint32_t c = acc | (k ? accum : 0) | (uint32_t)((i * J_T + j) * DIM);
      ops[n++] = i == 0 ? lay.b[u] : GARBAGE_ADDR; ops[n++] = c;
      ops[n++] = lay.a_lo[i][k]; ops[n++] = lay.a_lo[i][k];
    }
  }
  NM_REQUIRE(loaded == NTILE);
  return n;
}

#define RI(f, p) ROCC_INSTRUCTION_RS1_RS2(XCUSTOM_ACC, sz | (p)[0], sz | (p)[1], f)

// one timed run of the prepared stream; returns 1 if C verified
static int run(int ly, int I, int rep) {
  const int dense = ly == LDENSE, ntile = dense ? K_T * J_T : NTILE, computes = I * ntile;
  poison(I);
  if (!dense) { gemmini_nm_reset(); gemmini_nm_config_ex(1, NO_ACTIVATION, 0, ACC_SCALE_IDENTITY, 1, 1); }
  else { gemmini_fence(); gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0); }
  gemmini_fence();
  counter_reset();
  for (int i = 0; i < NCTR; i++) counter_configure(i, ctr_ids[i]);
  const uint64_t t0 = read_cycles();
  const uint64_t sz = ((uint64_t)DIM << (ADDR_LEN + 16)) | ((uint64_t)DIM << ADDR_LEN);
  const uint32_t * p = ops;
  for (int t = 0; t < ntile; t++) {
    if (ldf[t]) { gemmini_nm_load_spad(p[0], p[1]); p += 2; }
    RI(k_PRELOAD, p); RI(k_COMPUTE_PRELOADED, p + 2); p += 4;
    for (int i = 1; i < I; i++) { RI(k_PRELOAD, p); RI(k_COMPUTE_ACCUMULATE, p + 2); p += 4; }
  }
  const uint64_t t1 = read_cycles();
  gemmini_fence();
  const uint64_t t2 = read_cycles();
  uint32_t v[NCTR];
  for (int i = 0; i < NCTR; i++) v[i] = counter_read(i);
  if (!dense) { gemmini_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0); }
  const int bad = check(I);
  printf("microloop case=%s shape=%dx%dx%d rep=%d computes=%d total=%llu issue=%llu cyc_per_compute_x100=%llu",
         layout_names[ly], I, J_T, K_T, rep, computes, (unsigned long long)(t2 - t0), (unsigned long long)(t1 - t0),
         (unsigned long long)((t2 - t0) * 100 / computes));
  for (int i = 0; i < NCTR; i++) printf(" %s=%u", ctr_names[i], v[i]);
  printf(" ex_per_compute_x100=%llu b_spill=%d %s\n", (unsigned long long)v[0] * 100 / computes, dense ? 0 : lay.b_spill,
         bad ? "FAILED" : "verified");
  if (bad) printf("microloop case=%s shape=%dx%dx%d rep=%d mismatches=%d of %d\n", layout_names[ly], I, J_T, K_T, rep,
                  bad, I * DIM * D_N);
  return !bad;
}

// Spike only (cpu_ref): the host reference against the CPU's nm_ref_sparse / nm_ref_dense and the index packing
static int cpu_check(void) {
  static acc_t cs[D_M][D_N], cd[D_M][D_N];
  static uint8_t tile[NM_META_SPAD_BYTES] __attribute__((aligned(8)));
  int bad_s = 0, bad_d = 0, bad_p = 0;
  nm_ref_sparse(D_M, D_K, D_N, d_A, D_K, d_WC, d_IDX, D_N, &cs[0][0], D_N, NM_N, NM_M);
  nm_ref_dense(D_M, D_K, D_N, d_A, D_K, d_W, D_N, &cd[0][0], D_N);
  for (int y = 0; y < D_M; y++)
    for (int x = 0; x < D_N; x++) { bad_s += cs[y][x] != d_C[y * D_N + x]; bad_d += cd[y][x] != d_C[y * D_N + x]; }
  for (int u = 0; u < NTILE; u++) {
    const int k = u / J_T, j = u % J_T;
    nm_pack_meta_spad(d_IDX + (size_t)k * DIM * D_N + (size_t)j * DIM, D_N, DIM, DIM, NM_M, tile);
    for (size_t b = 0; b < NM_META_SPAD_BYTES; b++) bad_p += tile[b] != d_IDXSP[(size_t)u * NM_META_SPAD_BYTES + b];
  }
  const int pruned = nm_check(D_K, D_N, d_W, D_N, NM_N, NM_M);
  printf("microloop cpu_ref: nm_ref_sparse mismatches %d, nm_ref_dense mismatches %d, packed index bytes differing %d, "
         "W n:m pruned %d -> %s\n", bad_s, bad_d, bad_p, pruned, !bad_s && !bad_d && !bad_p && pruned ? "verified" : "FAILED");
  return !bad_s && !bad_d && !bad_p && pruned;
}

int main(void) {
  static const int shapes[3] = { 5, 3, 1 };
  int cases = 0, ok = 0;
  gemmini_flush(0);
  for (int y = 0; y < DIM; y++) for (int x = 0; x < DIM; x++) acc_poison[y][x] = POISON;
  printf("microloop: DIM=%d BANK_ROWS=%d NM=%d:%d R=%d data_seed=%d C.sha256=%s cpu_ref=%d shape_mask=%d\n", DIM, BANK_ROWS,
         NM_N, NM_M, (int)R_IDX, D_SEED, D_SHA_C, cpu_ref & 1, shape_mask & 0xff);
  if (cpu_ref & 1) { cases++; ok += cpu_check(); }
  for (int s = 0; s < 3; s++) {
    if (!(shape_mask >> s & 1)) continue;
    const int I = shapes[s];
    for (int ly = 0; ly < NLAYOUT; ly++) {
      make_layout(ly, I);
      if (!layout_ok(ly, I)) { printf("microloop case=%s shape=%dx%dx%d layout check FAILED\n", layout_names[ly], I, J_T, K_T); cases++; continue; }
      place(ly, I);
      build_ops(ly, I);
      for (int rep = 0; rep < 2; rep++) { cases++; ok += run(ly, I, rep); }
    }
  }
  printf("microloop done: %d of %d checks verified -> %s\n", ok, cases, ok == cases ? "ALL VERIFIED" : "FAILED");
  exit(ok == cases ? 0 : 1);
}
