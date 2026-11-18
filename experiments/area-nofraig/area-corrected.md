# Chip area (corrected): Berkeley's Gemmini vs. the 2:4 and 4:8 chips

Standard-cell area, Yosys 0.69 synthesis to sky130 HD (`sky130_fd_sc_hd__tt_025C_1v80.lib`, OpenROAD-flow-scripts copy, sha256 ec0e1067…d0d9), before place and route, SRAM macros left out (byte-identical in all chips). abc run without `&fraig -x` (see run_area_nofraig.py). Areas are yosys's own hierarchical `area` / `sequential_area`, cross-checked against leaf cells × liberty areas (area_corrected.py). analysis/area.py's hier() double-counts these; its output here is kept as area.areapy-DOUBLECOUNTED.{csv,md} (wrong areas; flops OK).

| Block | Berkeley (µm²) | 2:4 (µm²) | 2:4 vs Berkeley | 4:8 (µm²) | 4:8 vs Berkeley |
|---|---:|---:|---:|---:|---:|
| Gemmini (whole accelerator (no sram macros)) | 7,794,492 | 8,201,671 | +5.2% | 8,546,004 | +9.6% |
| ExecuteController (execute unit (array, index fifo, control)) | 2,795,913 | 3,206,114 | +14.7% | 3,549,807 | +27.0% |
| MeshWithDelays (array + input/output skew registers) | 2,674,665 | 2,977,755 | +11.3% | 3,259,037 | +21.8% |
| Mesh (16x16 array of tiles) | 2,443,103 | 2,707,036 | +10.8% | 2,975,774 | +21.8% |
| PE_256 (one multiply-accumulate pe) | 7,866 | 8,357 | +6.2% | 8,736 | +11.1% |

| Block | Chip | Flops | Flops vs Berkeley | Seq area (µm²) | Seq share of area | Seq share of added area |
|---|---|---:|---:|---:|---:|---:|
| Gemmini | berkeley | 98,932 | +0.0% | 2,800,626 | 35.9% | – |
| Gemmini | nm24 | 111,160 | +12.4% | 3,088,452 | 37.7% | 71% |
| Gemmini | nm48 | 122,097 | +23.4% | 3,328,863 | 39.0% | 70% |
| ExecuteController | berkeley | 36,457 | +0.0% | 997,036 | 35.7% | – |
| ExecuteController | nm24 | 48,685 | +33.5% | 1,284,862 | 40.1% | 70% |
| ExecuteController | nm48 | 59,622 | +63.5% | 1,525,273 | 43.0% | 70% |
| MeshWithDelays | berkeley | 34,414 | +0.0% | 936,708 | 35.0% | – |
| MeshWithDelays | nm24 | 43,903 | +27.6% | 1,142,376 | 38.4% | 68% |
| MeshWithDelays | nm48 | 53,479 | +55.4% | 1,341,927 | 41.2% | 69% |
| Mesh | berkeley | 26,118 | +0.0% | 744,514 | 30.5% | – |
| Mesh | nm24 | 33,798 | +29.4% | 913,636 | 33.8% | 64% |
| Mesh | nm48 | 42,758 | +63.7% | 1,100,696 | 37.0% | 67% |
| PE_256 | berkeley | 41 | +0.0% | 1,231 | 15.7% | – |
| PE_256 | nm24 | 45 | +9.8% | 1,351 | 16.2% | 24% |
| PE_256 | nm48 | 47 | +14.6% | 1,411 | 16.2% | 21% |
