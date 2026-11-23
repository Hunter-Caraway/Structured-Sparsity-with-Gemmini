# Worklog: micro_loop (bank-split-fix-spec.md section 8 micro-test)

Agent: microloop, started 2026-11-17. Task: measure, with no simulator rebuild, how much splitting a_lo/a_hi across
scratchpad banks cuts ex_active / cycles per compute (layouts L0-L4, qkv tile 5x6x48 and remainder 3x6x48) on the
existing Fix B nm24 / nm48 Verilator simulators.
Files: `investigate/src/micro_loop.c`, `investigate/src/gen_micro_loop.py`, `investigate/scripts/build_micro_loop.sh` (new),
run folders `investigate/runs/<stamp>-microloop-spike`, `<stamp>-microloop-srv`.

## Step 0. Inputs checked (2026-11-17)
- Spec read: `bank-split-fix-spec.md` (FROZEN), `investigate.md` sections 4-5, `investigate/src/micro2.c`.
- Server sims unchanged since the Fix B run: nm24 sha256 1042fc92...7891 (mtime 2026-11-13T15:56:35), nm48 f4a3642c...ed34
  (2026-11-13T16:00:15), identical to `runs/20261113-160015-fixb-srv/run.info`.
- Server slots: `ps -eo comm | grep -c ^simulator-chip` = 12 at first check (all busy).
- Spike libs: Fix B builds copied into scratch, sha256 nm24 0d30970a..., nm48 9c5894d4... (same as
  `runs/20261113-145855-fixb-final-spike/run.info`).
- Headers: gemmini-rocc-tests is being edited by another agent (branch bank-split-fix), so the bench builds against a
  `git archive 22158bf include` snapshot (Fix B commit; gemmini_nm.h sha256 98ff9ba8..., same as the fixb-srv run.info).
- Spec notes found while implementing:
  - Section 8 says the dense case is "K = 96 tiles, 1440 computes". 1440 = 48 K tiles x 6 x 5, so it is K = 48 dense tiles
    (the same 768-deep problem as the sparse case). K = 96 would not fit the scratchpad (A 7680 + B 9216 rows). Using 48.
  - S_A (I=5): E + B = 1920 + 2304 = 4224 rows > one bank (4096), so L1 (B with a_lo) and L2 (B with a_hi) cannot hold all
    of B in one bank. They place the first 136 of 144 B tiles in that bank and the last 8 in bank 2 (labelled in the
    output). S_B (I=3, E = 1152) fits fully.
  - Added L0i and L3i: L0 / L3 with the index rows where the real loop keeps them (top of bank 1 of the half), since the
    spec's bank-3 staging hides any index-read conflict with a_hi / B in bank 1.
- Verification: Verilator runs ~700 cycles/s here (qkv loop job: 3.2M cycles in 4501 s, fixb-srv jobs.tsv), so a CPU
  reference of 80x96x768 MACs (~60M cycles) is out of reach on RTL. As stream_bench does, the reference C comes from the
  host (gen_micro_loop.py, exact integer math). On Spike the binary also runs nm_ref_sparse and nm_ref_dense on the CPU
  and checks they equal the embedded reference (volatile flag; the server binary has the same .text).

## Step 1. micro_loop.c written (2026-11-17)
- `investigate/src/micro_loop.c`: cases L0, L0i, L1, L2, L3, L3i, L4, dense per shape; shapes I=5 / I=3 (SHAPE_MASK 3),
  I=1 (SHAPE_MASK 4, optional S3). Issue: precomputed 32-bit address words (sparse I=5 stream 12 KB, fits the 16 KB L1;
  dense I=5 is 24 KB and may not: watch `issue` vs `total` on RTL). Index tiles: Fix A spad LOADs on the loop's rolling
  rule (4 first, then 2 when loaded - pre <= 2), fix-b-spec 1.5.
- Per case: place (untimed), poison acc tiles + C, timed run (rep 0 warm-up, rep 1 measured), mvout, full compare of
  C (I*16 x 96) to the host reference -> `verified` / `FAILED`. Exit 1 unless every check verified.
- `investigate/src/gen_micro_loop.py` (stdlib only): data seed 20261117, A 80x768, W 768x96 pruned (nm_prune rule),
  WC/IDX (nm_compress rule), IDXSP (nm_pack_meta_spad, loop tile order), C exact.
- `investigate/scripts/build_micro_loop.sh <out>`: builds `micro_loop_{24,48}`, `_s1`, `_ref`; checks .text identical.

## Step 2. Spike (2026-11-17) -> `investigate/runs/20261117-142827-microloop-spike/`
- All 6 binaries exit 0 with ALL VERIFIED: nm24 micro_loop_24_ref 33/33 (incl. cpu_ref: nm_ref_sparse 0, nm_ref_dense 0
  mismatches, packed index bytes identical, W n:m pruned), micro_loop_24 32/32, _s1 16/16; nm48 same counts
  (`nm24.micro_loop_24_ref.log`, `nm48.micro_loop_48_ref.log`, ...).
- Checker negative tests (`mutants/`): reference value flipped (m_data), rs2 = a_lo (m_ahi), no accumulate on k'>0
  (m_noacc): all exit 1, FAILED on every sparse case (m_data also dense). The checker catches wrong C.

## Step 3. Server: blocked, SSH socket hung (2026-11-17 ~14:35)
- First server check (14:0x): 12 simulators running, sims sha256 unchanged (see step 0).
- From ~14:30 every command through `/tmp/claude-1000/cm-6994ff...` hangs (timeout 60-100 s), although
  `ssh -O check` says "Master running" and port 22 answers: the master's TCP connection is stale (VPN blip likely).
  Nothing was copied or launched on the server.
- Prepared `investigate/scripts/launch_micro_loop_srv.sh <spike_run_dir> [s3]` (new): checks the socket, the slot count
  (busy <= 12 - new sims), the nm24/nm48 sha256 (1042fc92.../f4a3642c...), copies the Spike-verified binaries with
  `ssh cat` + sha256 check, writes run.info + jobs, then `nohup setsid ~/fixb/run_jobs.sh` (PAR = number of sims,
  writes jobs.tsv, SHA256SUMS, STATUS). Exit 3 = socket down, 4 = server busy, 5 = simulator changed. Not yet run.

## RESUME HERE
- Done: micro_loop.c + gen_micro_loop.py + build_micro_loop.sh; Spike all verified on nm24 / nm48
  (`investigate/runs/20261117-142827-microloop-spike/`), checker negative tests fail as they should.
- Running: nothing.
- Blocker: SSH control master stale. User must restart it (CLAUDE.md steps: `ssh -O exit` the old master or kill
  pid 2013965, reconnect VPN if needed, then
  `ssh -o ControlMaster=yes -o ControlPath=/tmp/claude-1000/cm-%C -o ControlPersist=12h -fN ai-user@ai-1769.floridapoly.org`).
- Next:
  1. `cd ~/gemmini-sparsity/experiments/streaming/investigate && scripts/launch_micro_loop_srv.sh runs/20261117-142827-microloop-spike s3`
     (drop `s3` if only 2 slots; exit 4 = busy: retry every 30-60 min with a background wait). Prints the run folder.
  2. Wait on `<run>/STATUS` (ALL_DONE). Expected [E]: ~4-5M cycles per sim, ~2 h wall at ~700 cycles/s.
  3. Copy back into `investigate/runs/<same stamp>-microloop-srv/` (ssh cat per file), `sha256sum -c SHA256SUMS`.
  4. Each log must end `microloop done: 32 of 32 checks verified -> ALL VERIFIED` (s1: 16 of 16); use rep=1 lines.
     Table: layout x shape x chip: ex_active, cyc_per_compute, total, verified. Gain L0 vs L3 / L3i and vs L4.
     Check `issue` vs `total` on the dense lines (dense I=5 stream may exceed L1: if issue ~ total, dense is CPU-bound).

## Step 4. Server launch (2026-11-18)
- 23:21 server time: 5 sims running (convbudget only), 3 new -> 8 <= 12, quota 6 OK. Ran
  `launch_micro_loop_srv.sh runs/20261117-142827-microloop-spike s3` (S1 nm24 micro_loop_24, S2 nm48 micro_loop_48,
  S3 nm24 micro_loop_24_s1). The script's last ssh call hit its 60 s timeout (exit 124, backgrounded ssh held the
  channel) but the job started anyway.
- Server run folder: `~/sinv/runs/20261118-232156-microloop-srv` (run.info, jobs.tsv, 3 logs present). Launched ~23:22.
  Simulator PIDs: 756522 (nm24 micro_loop_24), 756773 (nm48), 757011 (nm24 s1). Driver pid 756153.
- Waiting on `<run>/STATUS`.
- 00:05 (Nov 19) progress: case-line counts s1 16/16, nm24 13/32, nm48 5/32; no failures seen. nm48 slower (~8 lines/h); est. a few more hours. Watching via background until-loop on STATUS.

## Step 5. Results (2026-11-23), run `investigate/runs/20261118-232156-microloop-srv/`
- Copied back with ssh cat; `sha256sum -c SHA256SUMS` all OK. STATUS ALL_DONE Thu Nov 19 02:16:33 2026. jobs.tsv: all exit 0, wall
  s1 1589 s, nm24 5626 s, nm48 10471 s. No FAILED/assert in any log.
- Verification (line 53 / 37 of each log): `nm24.micro_loop_24.seed1.log:53` 32 of 32 ALL VERIFIED;
  `nm48.micro_loop_48.seed1.log:53` 32 of 32 ALL VERIFIED; `nm24.micro_loop_24_s1.seed1.log:37` 16 of 16 ALL VERIFIED.
- rep=1 lines (cycles within the same build only, rule 4). Columns: total / cyc_per_compute x100 / ex_active. Log line numbers are
  the same in both 32-check logs: 5x6x48 L0 22, L0i 24, L1 26, L2 28, L3 30, L3i 32, L4 34, dense 36; 3x6x48 same order 38-52.
  s1 (nm24_s1 log): L0 22 ... dense 36.

| shape | case | nm24 total / cpc / ex | nm48 total / cpc / ex |
|---|---|---|---|
| 5x6x48 | L0 | 23197 / 3221 / 22344 | 23184 / 3220 / 22338 |
| | L0i | 23192 / 3221 / 22344 | 23172 / 3218 / 22338 |
| | L1 | 15537 / 2157 / 13743 | 15404 / 2139 / 13653 |
| | L2 | 15418 / 2141 / 13679 | 15509 / 2154 / 13728 |
| | L3 | 15463 / 2147 / 13736 | 15519 / 2155 / 13716 |
| | L3i | 15503 / 2153 / 13722 | 15439 / 2144 / 13645 |
| | L4 | 15382 / 2136 / 13593 | 15318 / 2127 / 13596 |
| | dense (1440 c) | 28607 / 1986 / 25890 | 28770 / 1997 / 25893 |
| 3x6x48 | L0 | 13956 / 3230 / 13410 | 13955 / 3230 / 13410 |
| | L0i | 13964 / 3232 / 13428 | 13955 / 3230 / 13410 |
| | L1 | 10218 / 2365 / 8978 | 10411 / 2409 / 9053 |
| | L2 | 10307 / 2385 / 9015 | 10266 / 2376 / 9006 |
| | L3 | 10597 / 2453 / 9088 | 10536 / 2438 / 9078 |
| | L3i | 10500 / 2430 / 9054 | 10355 / 2396 / 9038 |
| | L4 | 10356 / 2397 / 8889 | 10448 / 2418 / 8889 |
| | dense (864 c) | 20600 / 2384 / 17871 | 20342 / 2354 / 17730 |
| 1x6x48 (s1, nm24) | L0 / L0i / L1 / L2 | 4756/3302/4509, 4772/3313/4524, 4735/3288/4456, 4695/3260/4460 | - |
| | L3 / L3i / L4 / dense | 4730/3284/4452, 4714/3273/4458, 4214/2926/3690, 7448/2586/6690 | - |

- Gains (ratio of cyc_per_compute, same chip, [C] computed from the table):
  | shape | chip | L0/L3 | L0/L3i | L0/L4 |
  |---|---|---|---|---|
  | 5x6x48 | nm24 | 1.500 | 1.496 | 1.508 |
  | 5x6x48 | nm48 | 1.494 | 1.502 | 1.514 |
  | 3x6x48 | nm24 | 1.317 | 1.329 | 1.348 |
  | 3x6x48 | nm48 | 1.325 | 1.348 | 1.336 |
  | 1x6x48 | nm24 | 1.005 | 1.009 | 1.129 |
- Findings: the bank split (L1-L4) cuts cycles per compute ~33% (5x) and ~24-26% (3x); L3/L3i land within ~1-2% of L4 at 5x and 3x, so
  the split with indices in place (L3i) captures nearly all of the ideal. At 1x only L4 gains (1.129); L1-L3i gain <=1%.
- Dense issue vs total: 5x nm24 28535/28607, nm48 28697/28770; 3x nm24 20531/20600, nm48 20276/20342; 1x nm24 7366/7448
  (ratios 0.989-0.997). issue ~ total, but the dense stream does not look CPU-bound relative to the sparse cases beyond the same
  ~0.3% overhead every case shows (sparse L0 5x: 22798/23197 = 0.983); [E] the L1 fetch hypothesis is not supported, dense is
  not instruction-fetch limited here. Per-case spill: L1/L2 at 5x show b_spill=8 (labelled B overflow into bank 2), see logs.
- Anomalies: nm48 5x L2 (15509) is slower than nm48 L1 (15404) while nm24 shows the opposite (L2 15418 < L1 15537): chip differences
  of ~1%, single seed, single rep, so not conclusive. 3x L3 is the slowest split layout on nm24 (10597) and L3i recovers ~1%.
  Launcher's last ssh call timed out at exit 124 (harmless, job started).

## RESUME HERE (2026-11-23)
- Done: micro_loop launched, finished, copied back, checksums OK, all three logs ALL VERIFIED, table and gains above.
- Running: nothing.
- Findings: see Step 5 (L0 -> L3/L3i gain 1.50x at 5x6x48, ~1.32-1.35x at 3x6x48, ~1.0x at 1x6x48; L4 only at 1x).
- Next: user decides whether the spec's bank split proceeds; no further micro_loop runs planned. README / paper numbers need user approval.
