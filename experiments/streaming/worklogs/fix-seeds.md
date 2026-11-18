# fix-seeds worklog

## 2026-11-09 17:15: Step 1 (root cause). Result: seeds DO randomise state, but timing does not depend on it. Stopped after step 1.

The premise "`--x-initial fast` means `+verilator+seed` randomises nothing" is wrong. Evidence (laptop, read-only):
- `~/chipyard/sims/common-sim-flags.mk` (SIM_PREPROC_DEFINES) passes `+define+RANDOMIZE_MEM_INIT +define+RANDOMIZE_REG_INIT
  +define+RANDOMIZE_GARBAGE_ASSIGN +define+RANDOMIZE_INVALID_ASSIGN` to Verilator. `common.mk:228-243` runs firtool
  without `--disable-all-randomization`, so the generated RTL keeps its init blocks.
- gen-collateral (GemminiRocketConfig): 359 modules have `ifdef RANDOMIZE_REG_INIT` init blocks and 57 memories have
  `ifdef RANDOMIZE_MEM_INIT`, all with `` `define RANDOM $random ``. The verilated model calls `VL_RANDOM_I` 6740 times,
  plus `VL_RANDOM_Q` 61 times and `VL_RANDOM_W` 45 times.
- Verilator 5.046 `verilated.cpp:425-435`: `$random` uses a thread RNG seeded from `randSeedDefault64()`, which is
  `(seed<<32)^seed` when `+verilator+seed+N` is given (parsed at :3091). `emulator.cc:255-257` calls
  `Verilated::commandArgs` before it builds the model, so the seed applies to the init blocks. TestDriver.v:40-41 reseeds
  `$random` from `$urandom`, which is still a function of the seed.
- `--x-initial fast`/`--x-assign fast` (sims/verilator/Makefile:105-106) only affect state that has no init block. That
  is about 38 regs in harness blackboxes (SimDRAM, SimTSI, SimUART, SimJTAG, TestDriver, EICG_wrapper latch, plusarg_reader)
  and the `'bx` read data of disabled SRAM read ports (59 mem wrappers). `emulator.cc:255` sets `randReset(2)`, which
  would only matter with `--x-initial unique`.
- DRAMSim2/C++ harness: no rand() use found in DRAMSim2, testchipip csrc or emulator.cc beyond srand. The `-s` seed is not
  passed. Runs were already identical across separate processes (srand is time^pid by default), so any C++ RNG is irrelevant.
- Empirical (laptop simulator binary run directly, nothing rebuilt, output in scratchpad `seedprobe/`):
  `simulator-chipyard.harness-GemminiRocketConfig` (sha256 062e7da1...), fair_perf_dense_only, `+verbose +max-cycles=2000`,
  seeds 1/2/3. "testing $random" = 1ffffff / 2ffffff / 3ffffff. Un-reset CSR reads differ: cycle 32 csrr 0x303 gives
  0x2020 / 0x2222 / 0x2022, and cycle 44 (0x304, mie) gives 619dc057995a3b29 vs 752e3a46615f66e7. The cycle/pc sequence
  of all 35 retired instructions is identical across the seeds.
- Conclusion: the seed changes the initial value of every non-reset Chisel register and every SRAM. All
  timing-relevant control state (cache/TLB valid bits, BHT via reset FSM, queues, Gemmini controllers) is reset or
  written before it is read. So the cycle counts are seed-invariant, and 12/12 identical Nov-3 runs plus 12/12 on the
  server agree. An `--x-initial unique --x-assign unique` build would add randomness only to the harness blackbox regs
  and to disabled-port SRAM read data. It is not expected to change any total, so it was not built (task rule: stop after step 1).
- Server not touched.
