# banksplit-rebuild worklog (server rebuild of nm24, nm48, nm816 from bank-split-fix sources + RTL reruns)

Agent: banksplit-rebuild agent. Started 2026-11-23. User approved the rebuild (memory 2026-11-17, re-confirmed 2026-11-18). Quota 10 sims.
Never touch GemminiRocketConfig, its generated-src, or the stock rot180 rerun (`~/sinv/runs/20261123-143334-rot180-stock-srv`).

## Steps
1. Sources. Laptop HEADs = the approved hashes: gemmini 7b19c038, libgemmini 4886238, rocc-tests 2ad1fd3 (bank-split-fix, nothing newer).
   Created `current-working-branch` at those commits in all three repos, pushed to `fork`.
2. Server sync (server has no git on plain PATH; env needed). Server was on `sparse-nm` (gemmini 639a5068, libgemmini a14aaa1, rocc-tests 61086b4)
   plus uncommitted diffs. Backup of old working trees: `~/sinv/banksplit-sync/old-working-tree/{gem,lib,rt}.uncommitted.diff` + `rt.untracked/`.
   Sent `git bundle` files (scratch, sha256 gem c0977827, lib fef56f75, rt 6a9558f1; copied with ssh cat) to `~/sinv/banksplit-sync/`,
   `git fetch --no-recurse-submodules <bundle> current-working-branch:current-working-branch`, checkout. Server HEADs: gemmini 7b19c038, libgemmini 4886238,
   rocc-tests 2ad1fd3, `git status` clean, submodule gitlinks match. Source list (run-flow.sh `src_sha_list`) laptop vs server: 234 files each, 0 differences.
   Driver note: run-flow.sh `pattern` does not sync and runs the full ~122-job plan; so builds are done by hand with `tools/pattern_srv_build.sh` (the same script the driver would call).
3. Pre-build sim sha256 (backed up by the build script): nm24 1042fc926288a463, nm48 f4a3642cf572de92, stock 84c2264ab08524b8 (untouched).
   No `.src.sha256` build lists existed. nm816 has no sim yet.
4. nm24 build started 14:35 EST: `~/sinv/builds/20261123-banksplit-nm24` (make -j8, STATUS file, backup/ inside).
5. nm24 build done 14:42 (6.5 min, make -j8): `~/sinv/builds/20261123-banksplit-nm24/` STATUS BUILD_DONE, sim sha256 ff844142354b3326b50d0bc6998547c3b30c7fb06494651880f10252a8c4b39a,
   backup/ (old sim + generated-src + SHA256SUMS), `src.before-build.sha256`, sim `.src.sha256` written. build.log "error" hits are only rocket-chip Error.scala printf warnings.
   Note: elaboration rewrites rocc-tests `include/gemmini_params.h` on the server; restore it (`git checkout -- include/gemmini_params.h`) after the last build.
6. nm48 build started 14:42 (`~/sinv/builds/20261123-banksplit-nm48`).
7. Coordinator note (rot180-diag.md, 9a8410f): +max-cycles / TIMEOUT_CYCLES count 1 GHz sim clock, chip is 500 MHz: 1 core cycle = 2 sim cycles. Every cap here
   is set to >= 2 x expected core cycles + margin. The 62.7M / 162M estimates in pattern-flow.md step 2 came from `(timeout) after N` / wall_s (sim cycles) and
   from the 600M-budget pass of nm_sparse_loop_24 (sim units), but the stock rate part used `sbench end cycle` (core) so the basis is mixed: treat all as possibly
   core and double. nm_sparse_loop_*: cap 1200M sim cycles. Reported rdcycle results are unaffected.
8. nm48 build done 14:46: `~/sinv/builds/20261123-banksplit-nm48/` BUILD_DONE, sim sha256 d2d555454f4a9ced3b9db4d2eff1ef6ca83723d19c9bcd32786de809695ea504, backup/ made.
9. nm816 first build started 14:48 (`~/sinv/builds/20261123-banksplit-nm816`). Laptop Spike stages done for nm48 (flow folder `investigate/runs/20261123-143835-nm48-flow`, 119 programs); nm816 running.
10. nm816 first build done 14:51 (4 min): `~/sinv/builds/20261123-banksplit-nm816/`, sim sha256 747d6cb122ec911e5cad74f1f0eba0b890442899b843baa6883ccdaff215c061.
    All three builds BUILD_DONE. Laptop Spike stages passed for nm48 (`investigate/runs/20261123-143835-nm48-flow`) and nm816 (`20261123-144244-nm816-flow`), 119 programs each.
11. run-flow.sh prog_timeout (repo-local) raised: nm_sparse_loop_N 300M -> 600M; conv_with_input_dilation* 300M -> 1000M (sim cycles, see step 7;
    rot180-diag.md: rot180 ~390M, neg_padding ~165M sim cycles). The `_816` regex miss was already fixed (`^nm_sparse_loop_[0-9]+-baremetal$`).
12. Dense Verilog check started 15:0x: `~/sinv/dense_elab2.sh` (make verilog GemminiRocketConfig into separate gen dir generated-src-banksplit-dense, no Verilator,
    stock sim + generated-src sha256 before/after in `~/sinv/banksplit-dense/`). Compare vs stock generated-src and vs generated-src-fixb-dense (accepted baseline, dense-verilog-diff.md).
13. Dense Verilog check (done 14:53; `investigate/runs/20261123-banksplit-rebuild/dense/`, scripts dense_elab2.sh, dcmp.sh, d.sh): dense GemminiRocketConfig
    elaborated from bank-split-fix into `generated-src-banksplit-dense` (652 files, same count as stock and as the accepted `generated-src-fixb-dense`, sparse-loop-fix).
    Stock sim sha and stock generated-src checksums unchanged (dense/stock-*.before vs .after, STATUS DENSE_ELAB_EXIT=0).
    - vs accepted sparse-loop-fix dense (generated-src-fixb-dense): 9 files differ raw; after stripping `@[file:line]` and `.scala:line` only LoopMatmulLdA.sv differs
      (new-vs-fixbdense.differ): rename max_blocks -> max_blocks_dense, _sp_addr_T_4 -> _sp_addr_dense_T_4 (diff-details.txt, "LdA new vs fixb"), same expressions.
    - vs stock generated-src: 17 raw, 7 after stripping (new-vs-stock.differ): ExecuteController 440, MeshWithDelays 4690, Gemmini 11, LoadController 2, ReservationStation 6,
      LoopMatmul 6 (is_loop_config_cmd -> _ws rename), LoopMatmulLdA 18 (rename). Same files as the accepted 2026-11-13 set (dense-verilog-diff.md; ExecuteController 442 / MeshWithDelays 4694 then),
      plus the LdA rename. RESULT: no new logic delta from bank-split-fix on the dense build (names, line numbers only). Caveat: my normaliser is coarser than the 2026-11-13 one
      (RS/LoadController/Gemmini counts not re-inspected line by line; they equal the earlier set because new-vs-fixbdense shows only LdA changed).
    - Note: this `make verilog` ran in sims/ while the other agent's stock rot180 `make run-binary-fast` was alive, different gen dir, under flock ~/sinv/sims-make.lock; stock sim untouched (checked).
14. Driver bugs: (i) the final `srv "... nohup setsid ... &"` ssh hangs unless the local ssh gets `< /dev/null`; killed it, flow.state not written -> wrote it by hand for nm24.
    Fixed in run-flow.sh (`< /dev/null` on the launch and build ssh). (ii) schedule ordered longest first so five multi-day Berkeley conv tests would hold all slots while the sparse tests wait:
    added `--last` to tools/pattern_flow.py schedule and run-flow.sh passes `^conv_with_(input|kernel)_dilation` (those start after the rest). (iii) run.info text for timeouts updated.
    (iv) flow does not sync sources (known), and a failing `die` after the ssh kill leaves no flow.state.
15. Launched with QUOTA split 4/3/3 (+1 stock rot180 of the other agent = 11 <= 12; mine 10):
    nm24 `~/sinv/runs/20261123-145434-nm24-srv` (flow `investigate/runs/20261117-145939-nm24-flow`), 14:54; nm48 `20261123-150442-nm48-srv` (flow `20261123-143835-nm48-flow`); nm816 next (flow `20261123-144244-nm816-flow`).
    Each plan = 122 jobs (118 on the chip, stock jobs reused or scheduled): all Berkeley dense, nm_sparse_*, NEG (protocol 4/7/9/10/14, loop incl. 90/91/92), bench layers x full/fixa/loop, fair_perf seeds 1-3.
    This covers the listed targeted reruns (nm_sparse_loop with 600M sim cap, NEG 90/91/92, bench loop layers) so they are not run twice.
16. All three launched: nm24 14:54:52 (`~/sinv/runs/20261123-145434-nm24-srv`, quota 4), nm48 15:05:04 (`20261123-150442-nm48-srv`, quota 3), nm816 15:12:18 (`20261123-151155-nm816-srv`, quota 3).
    11 simulators on the box = my 10 + the other agent's stock rot180. The launch ssh hung every time even with `< /dev/null`; killed the local ssh, wrote flow.state by hand for each flow
    (the remote driver was RUNNING each time). run-flow.sh now uses `(nohup setsid ... &)` in a subshell (the form that worked for the builds); untested in the flow itself.
    First jobs per run: nm_sparse_loop_<N> (600M sim cap), conv_with_rot180, tiled_matmul_option, ...; Berkeley dilation/neg_padding/kernel-dilation jobs scheduled last.
## RESUME HERE
- Done: sync (3 repos at 7b19c038/4886238/2ad1fd3 on server, clean, laptop-vs-server list identical), 3 builds (nm24 ff844142.., nm48 d2d55545.., nm816 747d6cb1..), dense Verilog check, 3 launches.
- Running (server `~/sinv/runs/`): 20261123-145434-nm24-srv, 20261123-150442-nm48-srv, 20261123-151155-nm816-srv (STATUS files; ALL_DONE when finished). Do not touch GemminiRocketConfig or 20261123-143334-rot180-stock-srv.
- Next: wait for STATUS ALL_DONE on all three (nm_sparse_loop ~38 h predicted; Berkeley dilation tests several days); then `./run-flow.sh pattern-finish <pat> <flow folder>` (flows listed in each flow.state) copies back, checksums,
  verify_all --mode run; commit the copied run folders. Check intermediate logs for asserts/FAILED meanwhile. Restore server `include/gemmini_params.h` is not needed (no elaboration changed it? check `git status` in server rocc-tests).
