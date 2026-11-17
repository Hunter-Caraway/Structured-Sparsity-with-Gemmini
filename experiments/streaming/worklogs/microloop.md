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
