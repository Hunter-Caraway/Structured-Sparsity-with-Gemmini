# Area run: Yosys OOC logic area of `Gemmini` (stock, nm24, nm48)

Agent: area-run, started 2026-11-17. Plan: `worklogs/area-flow.md`. Scripts: `experiments/streaming/area/`.
Approvals (user, 2026-11-17): yosys in its own server conda env; Nangate45 + sky130hd Liberty download; 1 core and
8 GB RAM on the server beside the sims; no yosys on the laptop.

## Step 1: server checks (read-only, 2026-11-17 14:44 EST)
- Server: 16 cores, 31 GiB, MemAvailable 29 GB (`free -g`), load 12.06, 12 `simulator-chip*` processes
  (`pgrep -fc '^[^ ]*simulator-chip'`), busy cores 0,1,3,4,6,7,8,9,10,12,14,15 (`ps -eo psr`). Free: 2,5,11,13.
- No yosys/sta/openroad/sv2v in the chipyard env (`which`, `ls .conda-env/bin`).
- `.mems.conf` md5 `8608a99f8a8fef13bc7e351d264049c0` for all three configs on the server (same as laptop).
- Verilog server vs laptop (sha256 of every gen-collateral file, laptop scratchpad diff):
  - stock `GemminiRocketConfig`: 651 files, all identical.
  - nm24 / nm48: DIFFER. Server has 661 files, laptop 653. Server N:M Verilog was regenerated 2026-11-13 15:53/15:57
    (sparse-loop-fix rebuild, `worklogs/fixb-server.md:49`, simulators used by `runs/20261113-160015-fixb-srv`);
    laptop N:M Verilog is from 2026-11-03 (pre spad-index-fix/sparse-loop-fix; e.g. no `LoopMatmulLdIdx.sv`).
    The server copy is the one measured here (it matches the current server simulators). Laptop copy is stale.
- `mem_1_ext` (8192 x 64): instantiated by `mem_1.sv` <- `ScratchpadBank_4.sv` <- `TLRAM_ScratchpadBank.sv`, source
  `rocket-chip/.../util/DescribedSRAM.scala` (a rocket-chip TL scratchpad, not Gemmini). Not in Gemmini's closure
  (confirmed by `verilog_closure.py` per run, file `closure.txt`). Gemmini SRAMs: `mem_ext` (spad, via `mem.sv`,
  `Scratchpad.scala:163`) and `mem_0_ext` (acc, via `mem_0.sv`, `SyncMem.scala:45`).

## Step 2: installs (2026-11-17)
- `conda create -y -n yosys -c conda-forge yosys=0.71 python=3.12` in `~/miniforge3` (log `~/area/logs/conda-create.log`).
  `yosys -V`: `Yosys 0.71+ (git sha1 10084e2a1-dirty, ...) [github.com/conda-forge/yosys-feedstock at main]`.
  No slang plugin in the package. sv2v not installed (not needed unless plain parse fails).
- Liberty files in `~/area/pdk/` (`~/area/pdk/SHA256SUMS`):
  | File | URL | sha256 |
  |---|---|---|
  | nangate45/NangateOpenCellLibrary_typical.lib | ORFS `43be7b73.../flow/platforms/nangate45/lib/` | 8d540a4d4cf6d09d27c87ad067857a9c0c2eeb023ab7a56e058cd3113db4e9b1 |
  | nangate45/LICENSE (Apache-2.0, ORFS platform) | ORFS `.../flow/platforms/nangate45/LICENSE` | 0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594 |
  | nangate45/README.md (PDKv1.3_v2010_12.Apache.CCL, from si2.org) | ORFS `.../flow/platforms/nangate45/README.md` | 0e3c8a8cbe5429552764c6531dc454d64f6aa7c1f7128175b5f06070a3de578d |
  | sky130hd/sky130_fd_sc_hd__tt_025C_1v80.lib | ORFS `.../flow/platforms/sky130hd/lib/` | ec0e1067a35c8bf20b11e58d1e8ac53326067e4dac84a125cc1b917a3518d0d9 |
  | sky130hd/LICENSE (Apache-2.0) | `raw.githubusercontent.com/google/skywater-pdk/main/LICENSE` (HEAD 7198cf64) | cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30 |
  ORFS = `https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD-flow-scripts/43be7b732a04f336db52f5822ca476a154229192`.
  License note: the Nangate .lib header carries a Nangate copyright/"License Agreement" notice; ORFS ships it under
  Apache-2.0 as "PDKv1.3_v2010_12.Apache.CCL". Liberty files stay on the server; not copied into this repo.
- sv2v: plain `read_verilog -sv` fails on firtool packed-array patterns: `LoopMatmulStC.sv:77: ERROR:Assignment pattern
  is only supported for whole unpacked array assignments.` (85 stock files use `'{`; log
  `~/area/runs/20261117-145000-GemminiRocketConfig-nangate45-area/yosys.log`, STATUS `FAIL yosys rc=1`; kept as a failed record).
  Installed `conda install -n yosys -c litex-hub zachjs-sv2v=0.0.11_33_gdf01650` (binary `zachjs-sv2v`,
  `sv2v 0.0.11-33-gdf01650`, log `~/area/logs/conda-sv2v.log`). sv2v output of `LoopMatmulStC.sv` parses in yosys.
  conda-forge has no sv2v or yosys-slang package (`conda search`).

## Step 3: flow scripts (`experiments/streaming/area/`)
- `synth_area.sh <Config> <nangate45|sky130hd>` (laptop): uploads the flow to `~/area/flow/` (sha-checked), preflight
  (one area run at a time, MemAvailable >= 12 GB, gen-collateral exists), records sim count, launches
  `nohup setsid nice -n 10 taskset -c ${AREA_CORE:-13} area_remote.sh`. Prints the run folder.
- `area_remote.sh` (server): `ulimit -v 8 GiB`; `verilog_closure.py` (file closure of `Gemmini`, fails if `mem_1_ext`
  is inside); sha256 of every source file (`verilog.sha256`) and inputs; sv2v of the closure into
  `~/area/work/<run>/top_sv2v.v` (outside the run folder; its sha in run.info); aborts if the sim count changed;
  runs yosys `synth_area.ys.in`; `parse_area.py` -> `area.txt`; SHA256SUMS; STATUS DONE / FAIL.
- `synth_area.ys.in`: `read_verilog -lib <cfg>.top.mems.v` (all SRAM `*_ext` = blackboxes with exact ports),
  `hierarchy -check -top Gemmini`, `synth -top Gemmini` (hierarchy kept), assert no `$_DLATCH*`, `dfflibmap`,
  `abc -liberty <lib>` (FIXED setting for all runs: default abc script, no `-D` delay target), `opt_clean`,
  `stat -liberty -top Gemmini` (txt + json).
- `parse_area.py`: recomputes area from cell counts x Liberty cell area and fails if it disagrees with yosys's total;
  flops = Liberty cells with an `ff`/`latch` group; blackbox SRAM count x mems.conf depth x width = SRAM bits;
  per-module (incl. submodules) area x instance count. `--compare base run...` builds the results table from area.txt.
- `fetch_area.sh <run name>`: ssh cat of every SHA256SUMS file into `area/runs/<name>/`, `sha256sum -c`.
- Launcher bug fixed: first sv2v launch held ssh open (whole `a && b && nohup ... &` list backgrounded); now only the
  nohup line is backgrounded.

## Step 4: runs
| Run | Status |
|---|---|
| 20261117-145000-GemminiRocketConfig-nangate45-area | FAIL (SV parse, before sv2v) |
| 20261117-145118-GemminiRocketConfig-nangate45-area | FAIL yosys rc=1 (server STATUS; yosys.log:308 `ERROR: Module \plusarg_reader' referenced in module \ReservationStation ... is not part of the design`, plusarg_reader Verilog missing from the file list) |
| 20261117-145438-GemminiRocketConfig-nangate45-area | DONE (server STATUS; yosys_wall_s=24046, run.info) |

## Fetch 2026-11-18
- `fetch_area.sh 20261117-145438-GemminiRocketConfig-nangate45-area` -> `experiments/streaming/area/runs/20261117-145438-GemminiRocketConfig-nangate45-area/` (16 files), sha256sum -c OK.
- `parse_area.py --compare <run> <run>` rc 0 (laptop; the run's own area.txt was written server-side by parse_area.py, whose self-check requires area == yosys total: area.txt logic_area_um2 1547317.212 = yosys_area_um2 1547317.212).
- area.txt: top Gemmini logic 1547317.212 um^2 (sequential 447176.058), flops 98889, cells 996536, SRAM blackbox bits 2621440 (mem_ext 4x 4096x128 = 2097152; mem_0_ext 2x 512x512 = 524288), SRAM area not included in logic area. Biggest modules (area.txt, nested, not additive): ExecuteController 552401.4 (36457 ff), MeshWithDelays 527970.4, Mesh 478912.3, Scratchpad 471715.1 (39150 ff), PE_256/Tile x256 386581.0, LoopConv 332434.0, AccumulatorScale 177389.3, MacUnit x256 142456.8.
- 145118 failure: yosys.log:308 plusarg_reader not part of design (ReservationStation); 145438 fixed that.

## RESUME HERE
Done: area run 145438 fetched, verified, parsed (above). Next: coordinator decides area runs for nm24/nm48 and compare with `parse_area.py --compare`.
