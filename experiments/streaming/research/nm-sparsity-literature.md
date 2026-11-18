# N:M / structured-sparse accelerators on systolic and tensor arrays: how published work built and evaluated them

Literature review for the Gemmini 2:4 / 4:8 project. Written 2026-11-09.

**Why this review exists.** Our sparse array delivers 2x per compute (micro2: 16.2 cycles per sparse pair vs 16.15
dense), but whole layers run slower than dense. The cause is CPU issue, not the array: sparse mode cannot use
LOOP_WS, and index tiles go in as 4 (2:4) or 8 (4:8) `NM_META` RoCC commands per tile, loaded through the Rocket L1
(see `worklogs/investigate.md` sections 14 and 17; the RS is empty for 37-42% of the sparse run). Before changing the
RTL, we checked how published designs handle (a) metadata delivery and (b) command issue and sequencing, and how
they were evaluated.

**Conventions.**
- "p. N" is the PDF page of the version actually read (arXiv or author copy, linked in each section). Page
  numbers in the published proceedings may differ.
- **[read]** means the text was read in the primary source. **[inference]** is my reasoning from the source; the
  source does not say it. **[secondary]** means the claim was not checked against a primary source.
- Each source was downloaded as a PDF and its text extracted. I read the relevant sections (architecture,
  methodology, results), not every page of every paper.
- Not found: no published (arXiv/IEEE/ACM) Gemmini- or Chipyard-based **N:M** extension. GitHub search for "gemmini
  sparse" and "gemmini sparsity" (gh CLI) returned nothing; a web search surfaced only this project's own repo. The
  closest Gemmini-lineage works are SPOTS (uses Gemmini as a baseline) and Stellar (Berkeley; regenerates Gemmini
  and supports sparse formats). Both are covered below.

---

## 1. STA / STA-DBB: Systolic Tensor Array (Liu, Whatmough, Mattina, Arm ML Research, 2020)

**Citation.** Z.-G. Liu, P. N. Whatmough, M. Mattina, "Systolic Tensor Array: An Efficient Structured-Sparse GEMM
Accelerator for Mobile CNN Inference," *IEEE Computer Architecture Letters*, 2020. arXiv:2005.08098 (4 pages).
<https://arxiv.org/abs/2005.08098>

1. **Metadata delivery [read].** Density-bound block (DBB) format. "A simple bitmask compression is used to encode
   each block of 8 elements (one byte overhead per block), along with the four bytes of non-zero data" (p. 3). The
   2:4 example PE gets "a 50% DBB compressed weight inputs [W0, W1] and associate 2-bit non-zero indices from top"
   (p. 3). The indices travel **with the weights**, down the same systolic path. Cost: 1 bit per dense weight
   position (8-bit mask per 8-element block), or 2 bits per stored non-zero at 4/8.
2. **Control and sequencing.** Not described: this is a 4-page letter about the datapath only.
3. **Datapath [read].** Mux on the **activation** side: "a multiplexer in front of MAC to select the corresponding
   input feature map (activation) based on the index of the non-zero weight" (p. 3). Each SDP4 unit takes a 4-wide
   activation vector [A0..A3] from the left and trades "two 8-bit multipliers for two 8-bit 4:1 multiplexers" (p. 3).
   Note the design goal: STA-DBB uses sparsity to **halve the multipliers at the same throughput**. It is not built
   to double throughput, and "still supports conventional dense GEMM at half throughput" (p. 3).
4. **Evaluation [read].** Verilog from a parameterized RTL generator, synthesized in TSMC 16nm at 1 GHz with Design
   Compiler; power from PrimeTimePX with annotated switching activity (p. 3). The metric is iso-throughput area and
   power efficiency against a TPU-like clock-gated systolic array (SA), plus SMT-SA. Workloads are "typical layers of
   ResNet50 V1" (Fig. 4, p. 4). There is no system, DRAM or host model.
5. **Numbers [read].** Table II (p. 3): STA-DBB area efficiency 3.14x and power efficiency 1.97x (dense STA: 2.08x
   / 1.36x; SMT-SA: 1.21x / 0.80x). Accuracy loss of DBB models: 0.1-1.1% (Table I, p. 3).

## 2. Sparse Systolic Tensor Array / STA-VDBB (Liu, Whatmough, Mattina, 2020)

**Citation.** Z.-G. Liu, P. N. Whatmough, M. Mattina, "Sparse Systolic Tensor Array for Efficient CNN Hardware
Acceleration," arXiv:2009.02381v2, Oct 2020. <https://arxiv.org/abs/2009.02381> (Only the arXiv version was read;
I did not confirm a peer-reviewed venue.)

1. **Metadata delivery [read].** Same DBB bitmask. The mux select "is driven by the positional index metadata (M),
   which is an additional byte per block" (p. 4). In the STA-DBB example, the "2/4 DBB compressed weight input
   [W0, W1] and associated 2-bit non-zero index" come "from the top" (p. 5). The metadata is stored and moved with
   the weights.
2. **Control and sequencing [read].** The SoC contains "Arm Cortex-M33 microcontrollers for DMA and vector compute
   operations" (p. 5). "The input image is loaded into the AB before operation begins, via DMA from the MCUs"
   (p. 7). Weight and activation buffers are double-buffered (p. 7).
3. **Datapath and operand bandwidth [read].** Mux on the activation side (8:1 for 4/8 blocks, p. 4). To feed the
   activations, they add "a novel approach of moving the IM2COL transform into the hardware, which allows us to
   achieve a 3× data bandwidth expansion just before the operands are consumed by the datapath" (abstract, p. 1).
   The hardware IM2COL unit is "reducing SRAM bandwidth by 3× for a typical 3×3 filter" (Fig. 8, p. 8). Variable
   DBB is time-unrolled, so "datapath utilization and operand bandwidth remain constant" (p. 4).
4. **Evaluation [read].** "RTL simulation in Synopsys VCS running our DBB INT8 CNN models" for throughput, and VCD
   traces of "representative layers of ResNet50" into PrimeTimePX for power (p. 8). TSMC 16nm. The baseline is a
   TPU-like 1×1×1 32×64 systolic array (p. 8).
5. **Numbers [read].** 16.8 TOPS/W at 50% model sparsity, up to 55.7 TOPS/W at 87.5% (abstract, p. 1). Whole model:
   "the 4×8×8 VDBB IM2C design achieves a 44.6% power reduction over the baseline. Fixed DBB design 4×8×4 DBB IM2C
   gives a 24.9% power reduction" (p. 9).

## 3. S2TA (Liu, Whatmough, Zhu, Mattina, HPCA 2022)

**Citation.** Z.-G. Liu, P. N. Whatmough, Y. Zhu, M. Mattina, "S2TA: Exploiting Structured Sparsity for
Energy-Efficient Mobile CNN Acceleration," HPCA 2022. arXiv:2107.07983v2. <https://arxiv.org/abs/2107.07983>

1. **Metadata delivery [read].** DBB along the channel dimension. "The non-zero elements are stored by removing the
   zeros. Second, a simple bitmask M is added to encode the presence of a non-zero element at each location in the
   expanded block" (p. 4). The same compression applies to weights and activations (Fig. 5, p. 4). For activations,
   the bitmask is produced **in hardware** by the Dynamic Activation Pruning (DAP) unit, a cascade of maxpool stages
   that outputs the values plus "the positional bit mask M=8'h4D" (Fig. 8, p. 7). Cost: 8 bits per 8-element block.
2. **Control and sequencing [read].** "Control and data movement (DMA) tasks are also performed by the MCUs, e.g.
   loading the input image into AB. We use a cluster of 4 MCUs each with a small 64KB control store SRAM, which is
   sufficient to ensure that the MCUs are never the performance bottleneck" (p. 7). No data is shown to support the
   "never the bottleneck" claim. The 0.5 MB weight buffer and 2 MB activation buffer "are double buffered to overlap
   computation in the TPE array and DMA data transfer" (p. 7). Layers are mapped "using simple matrix tiling,
   similar to the TPU" (p. 6).
3. **Datapath [read].** W-DBB unit DP4M8: "The key to the hardware for W-DBB is the 8:1 MUX in front of each MAC.
   The MUX, controlled by the positional bitmask(M) from the weight DBB block, is used to steer the correct
   activation element into the MAC" (p. 5). This gives a "50% reduction in MACs at the same throughput, and a 37.5%
   reduction in weight operand bandwidth" (p. 5). It uses an output-stationary dataflow (p. 6). Tensor PEs take
   operand **blocks** per cycle, which adds intra-TPE operand reuse (p. 6-7). So the wider activation input is
   amortised over several MACs.
4. **Evaluation [read].** A Python RTL generator emits Verilog plus a testbench. Each design runs "inference on a
   given CNN model" in Synopsys VCS, and VCD traces drive power analysis (p. 7). Full EDA flow in TSMC 16nm (1 GHz)
   and 65nm (500 MHz) (p. 7). Baselines (p. 8): SA-ZVCG (dense SA with zero-value clock gating), S2TA-W (their
   A100-like weight-only 4/8 variant), SA-SMT (re-implemented), and SparTen / Eyeriss-v2 (numbers from those papers).
   "All systolic array designs have 4 TOPS peak (dense) throughput and otherwise identical configurations" (p. 8).
   Workloads: microbenchmarks plus VGG16, MobileNetV1, ResNet50V1 and AlexNet (conv only) (Fig. 11, p. 10).
   DRAM is not modelled (inference: only on-chip SRAM appears in Table 2, p. 7).
5. **Numbers [read].** S2TA-AW vs SA-ZVCG on full DNNs: 2.08x energy reduction, 2.11x speedup (p. 10-11).
   S2TA-W (weight-only 4/8, the closest analogue to our design) has a speedup "capped at 2×" and only "1.2× energy
   reduction compared to SA-ZVCG" (Fig. 9 caption, p. 9). Summary point 3 says S2TA-W "only marginally reduces energy
   (by 1.13×)" (p. 11). Area breakdown: MAC datapath and buffers 58.7%, DAP 2% (Table 2, p. 7). **Where the speedup
   fails:** "fully-connected (FC) and depthwise (DW) layers are memory bound on S2TA, as batching is typically not
   used in inference" (p. 11).

## 4. VEGETA (Jeong et al., HPCA 2023)

**Citation.** G. Jeong, S. Damani, A. R. Bambhaniya, E. Qin, C. J. Hughes, S. Subramoney, H. Kim, T. Krishna,
"VEGETA: Vertically-Integrated Extensions for Sparse/Dense GEMM Tile Acceleration on CPUs," HPCA 2023.
arXiv:2302.08687v2. <https://arxiv.org/abs/2302.08687>

1. **Metadata delivery [read].** Metadata gets its own **architectural registers**: "metadata registers (mreg0-7)
   ... a pair of bits in the metadata represents the position of one non-zero element ... an mreg has 16 rows, each
   with 64 bits of metadata for a total of 128 Bytes" (p. 4). It is loaded from memory by **one instruction per
   tile**: "a corresponding TILE_LOAD_M instruction, which loads 128 B of metadata from memory to an mreg" (p. 5,
   Table II). Tile loads become "16 memory requests and each will be loading ... 64 Bytes (cache line size) through
   load/store queue" (p. 10). Cost: 2 bits per non-zero.
2. **Control and sequencing [read].** Every tile GEMM/SPMM is **one CPU instruction** (TILE_GEMM, TILE_SPMM_U,
   TILE_SPMM_V; Table II, p. 5) issued by an out-of-order core: "2 GHz and fetch/issue/retire width as four" (p. 10),
   while the matrix engines run at 0.5 GHz (p. 11). So the front end has a 4x clock advantage and 4-wide issue
   [inference: this hides per-tile issue cost; their result does not transfer directly to a 1-wide in-order Rocket].
   The renamer, scheduler and ROB are extended to track tile and metadata registers (p. 10). Back-to-back dependent
   tile instructions stall, so they add "output forwarding (OF)" (p. 9), which bought "another 32% runtime" on 2:4
   layers (p. 11). Their motivation also notes that vector code needs "many more instructions" than matrix-engine
   code for the same GEMM (p. 3).
3. **Datapath [read].** Mux on the **input (activation) side**, inside the PE: "An SPE-2-2 receives two (= β) input
   blocks (instead of one input element) from the west and broadcasts them to α SPUs. An input block is fed into each
   M to 1 MUX in an SPU, and using the metadata for the corresponding weight value in the weight buffer, the
   corresponding input element from the block is selected" (p. 6). Per-PE additions: "M to 1 MUXes and a metadata
   buffer added to each weight buffer" (p. 6). The metadata is stationary with the weights. Operand bandwidth comes
   from feeding β input blocks per row and broadcasting them to α units. For mixed-sparsity rows they propose "a
   simple reordering in input/output DMA engines" (p. 10).
4. **Evaluation [read].** LLVM intrinsics, a Pin-based emulator for traces, and an extended MacSim cycle-level CPU
   simulator (p. 10). RTL synthesized with Nangate 15nm for area, power and timing (p. 10). Workloads: ResNet50,
   BERT and GPT-3 layers (Table IV). Baselines: dense CPU matrix engines RASA-SM, RASA-DM and an Intel-TMUL-like
   config, plus an "NVIDIA STC-like config" (2:4 only) on the same framework (p. 10). **Memory is excluded:** "we
   assume that the data is prefetched to the L2 cache" (p. 11).
5. **Numbers [read].** Abstract (p. 1): 1.09x, 2.20x, 3.74x and 3.28x for 4:4, 2:4, 1:4 and unstructured 95%. On 2:4
   layers, the STC-like engine gives only "16% runtime reduction on average compared with the RASA-DM"; VEGETA-S-16-2
   adds another 18%, and output forwarding another 32% (p. 11). Area: the worst VEGETA-S variant has "6% area
   overhead" vs RASA-SM; power overhead is 17%, 8%, 4%, 3% and 1% for α = 1, 2, 4, 8, 16 (p. 11).

## 5. HighLight (Wu, Tsai, Muralidharan, Parashar, Sze, Emer, MICRO 2023)

**Citation.** Y. N. Wu, P.-A. Tsai, S. Muralidharan, A. Parashar, V. Sze, J. Emer, "HighLight: Efficient and
Flexible DNN Acceleration with Hierarchical Structured Sparsity," MICRO 2023. arXiv:2305.12718v2.
<https://arxiv.org/abs/2305.12718>

1. **Metadata delivery [read].** Hierarchical structured sparsity (HSS) with an offset-based coordinate payload
   (CP) per rank: "For Rank0, each nonzero value carries a CP" (p. 7, Fig. 9). Compressed operand B "carries three
   levels of metadata" (p. 9). The metadata is stored **on chip next to the data**: "GLB is partitioned to data and
   metadata storage for sparse designs" (Table 4 caption, p. 10). I did not extract a bits-per-weight figure.
2. **Control and sequencing.** Not modelled. The evaluation is analytical (Sparseloop), so there is no host or
   instruction stream [inference from the methodology].
3. **Datapath [read].** The mux is on the operand paired with the sparse one: "8-to-4 muxing logic can be
   implemented with four 8-to-1 muxes" (p. 6). An 8-to-1 mux is "two 4-to-1 muxes pipelined with a 2-to-1 mux" for
   latency (p. 7). Feeding a variable number of dense blocks: "due to the fixed physical dimensions of the GLB, each
   GLB fetch has to be fixed to a certain number of blocks ... HighLight's Rank1 Skipping SAF employs a Variable
   Fetch Management Unit (VFMU) ... VFMU includes a small buffer that stores the 2×Hmax blocks of operand B. The
   buffer is written with data that are fetched from GLB in an aligned fashion" (p. 8-9). This is their answer to
   unaligned or variable operand fetch (no bank conflict, because GLB reads stay aligned).
4. **Evaluation [read].** "Sparseloop-Accelergy infrastructure ... captures each accelerator's cycle counts and
   component runtime activities" (p. 10). 65nm Accelergy plug-ins; RTL for HighLight-specific parts; "DRAM:
   propriety commercial data for LPDDR4" (p. 10), so DRAM **is** in the energy model. Baselines with "similar storage
   and compute resources": TC-like (dense), STC-like, S2TA-like, DSTC-like (p. 9-10). Workloads: synthetic
   1024×1024 matmuls; ResNet50, DeiT-small and Transformer-Big (p. 10). Metrics: latency, energy, EDP, and
   EDP-vs-accuracy Pareto (p. 10-12).
5. **Numbers [read].** Geomean 6.4x (up to 20.4x) lower EDP vs dense; 2.7x (up to 5.9x) vs sparse accelerators
   (p. 2). The sparse-acceleration features take "only 5.7% of the design's area" (p. 12). Their motivation also
   records where STC-style 2:4 falls short: STC-like is "designed to only allow a maximum of 2× speedup" and "cannot
   exploit activation sparsity" (p. 3).

## 6. TB-STC (Liu, Zeng, et al., HPCA 2025)

**Citation.** J. Liu, S. Zeng, J. Zhao, L. Ding, Z. Wang, J. Li, Z. Zhu, X. Ning, C. Zhang, Y. Wang, G. Dai,
"TB-STC: Transposable Block-wise N:M Structured Sparse Tensor Core," HPCA 2025. Author copy:
<https://chenzhangsjtu.github.io/files/2025-HPCA.pdf> (IEEE version not read).

1. **Metadata delivery [read].** Storage is split into "inter-block storage and intra-block storage" (Fig. 8,
   p. 6). Inter-block storage records the offset of each block's first element; intra-block storage holds each
   block compressed along its own sparsity dimension (p. 6). An **adaptive codec unit** converts the storage format
   to a computation format on the fly: "The codec unit processes the corresponding matrix and sends the matrix'
   values and indices to DVPEs and the MBD unit" (p. 5). "The format conversion ... can be hidden within the entire
   execution pipeline ... only an average of 3.57% of the overall execution cycle" (p. 10).
2. **Control and sequencing.** A tensor core inside a GPU (SIMD issue, p. 7). The paper does not discuss host or
   front-end issue cost.
3. **Datapath [read].** A "matrix B distribution (MBD) unit ... selects and rearranges the matrix B elements
   according to the sparse indices" (p. 5), using "the MUX array and transpose array" (Fig. 10, p. 7). The mux is on
   the dense operand side, before the PEs.
4. **Evaluation [read].** RTL plus Design Compiler for logic area and codec power; Sparseloop for array power;
   "Ramulator and DRAMPower to get the cycle-level evaluation and energy results of DRAM"; CACTI for buffers; a custom
   cycle-level performance simulator (p. 9). Fairness: "keep the same peak performance, on-chip memory capacity, and
   64GB/s off-chip memory bandwidth" for all baselines (p. 9). Baselines: NVIDIA STC (tile-wise N:M), VEGETA and
   HighLight (row-wise N:M), RM-STC (unstructured) (p. 9). They report layer-wise results and "end-to-end" results
   on ResNet-50, BERT and OPT-6.7B at equal accuracy (p. 10).
5. **Numbers [read].** 1.47x bandwidth utilization and 1.57x compute utilization; EDP improved 3.82x on average
   (abstract, p. 1). End-to-end: speedup 1.22x and 1.06x, and EDP 1.62x and 1.92x, vs HighLight and RM-STC
   respectively (p. 10). Area: 12.96 mm² scaled to A100, which is "only 1.57% for the 826 mm2 die area" (p. 11).

## 7. DSTC: Dual-side Sparse Tensor Core (Wang et al., ISCA 2021)

**Citation.** Y. Wang, C. Zhang, Z. Xie, C. Guo, Y. Liu, J. Leng, "Dual-side Sparse Tensor Core," ISCA 2021.
arXiv:2105.09564. <https://arxiv.org/abs/2105.09564>

Unstructured dual-side sparsity, not N:M. It is included because it shows instruction-level sequencing of sparse
tiles on a GPU.

1. **Metadata delivery [read].** A bitmap per operand: "two-tuple encoding of a bitmap and a value array ... The
   bitmap uses 1's for positions of non-zero values" (p. 4). Two-level bitmaps let whole warps be skipped (p. 11).
   Cost: 1 bit per dense element, per operand.
2. **Control and sequencing [read].** Done **in software on the GPU front end**. A SpWMMA call compiles to 8
   OHMMA instructions. Popcounts on the bitmaps set predicate bits, and predicated-off OHMMA instructions are skipped
   ("@p0 HMMA.OHMMA.8161...", p. 8-9). A new binary BOHMMA instruction computes the output bitmap, and "BOHMMA is 16×
   faster than HMMA" (p. 8).
3. **Datapath [read].** An outer-product tensor core (8×8×1 primitive), which needs no input-side mux. The cost
   moves to merging and accumulating partial outputs (p. 4-5).
4. **Evaluation [read].** Accel-Sim (GPGPU-Sim based), cycle-accurate, V100 configuration (p. 2, p. 9). Baselines:
   CUTLASS, cuDNN, cuSPARSE, and Zhu et al.'s Sparse Tensor Core (p. 10). Hardware overhead from CACTI 7 (22nm
   scaled to 12nm) plus RTL estimates (p. 12).
5. **Numbers [read].** Up to 7.49x on SpCONV (p. 2). Overhead 12.846 mm², "1.5% of the whole V100 die area" and
   3.89 W (1.6% of TDP) (p. 12). The vector-wise Sparse Tensor Core baseline "has a fixed speedup of 1.86× over
   CUTLASS" at 75% pruning (p. 11).

## 8. SPOTS (Soltaniyeh, Martin, Nagarakatte; ACM TACO 2022)

**Citation.** M. Soltaniyeh, R. P. Martin, S. Nagarakatte, "SPOTS: An Accelerator for Sparse Convolutional Neural
Networks Leveraging Systolic General Matrix-Matrix Multiplication." Read: Rutgers tech report DCS-TR-756 /
arXiv:2107.13386v2 <https://arxiv.org/abs/2107.13386>. Journal version: ACM TACO, doi:10.1145/3532863 (not read).

Group-wise (block) pruning, not N:M. It is included because it is a systolic design evaluated against Gemmini.

1. **Metadata delivery [read].** Two bitmaps: "M1 encodes whether a column has any non-zeros in the filter matrix
   ... M2 maintains whether a block in a non-zero column is" non-zero (p. 11). The data and metadata (A, M1, M2) "are
   distributed across the various banks of the SRAM so that the input controller" can fetch them in parallel
   (p. 11). The IM2COL unit builds a row bitmap for activations on the fly (p. 12).
2. **Control and sequencing [read].** Zero skipping happens **in the input controller before the array**: "we avoid
   the zeros in the input controller. It relieves the PEs from doing" index matching (p. 6). "We do not need
   additional logic to perform index matching inside a PE" (p. 10). The paper does not discuss host issue.
3. **Datapath [read].** No PE mux. All-zero rows and columns are skipped before entering the array (Fig. 9,
   p. 12). A reconfigurable tall array (128×4) or multiple square arrays sit behind a pipelined hardware IM2COL
   (p. 10, p. 13).
4. **Evaluation [read].** "Cycle-accurate simulation of the RTL model of SPOTS in Verilog using Verilator" with
   FreePDK45 and CACTI for SRAM/DRAM (p. 13). Layers are run one at a time (p. 13). The Gemmini baseline uses 32×32
   PEs, "2× more MAC units than our prototype", with scratchpad sizes matched (p. 15). Batch 1 (p. 15).
5. **Numbers [read].** 1.74x and 2.16x faster than Eyeriss and Gemmini on average (p. 1). Per network vs Gemmini:
   VGG 1.86x, ResNet 2.66x, GoogleNet 1.91x (p. 17).

## 9. Sparse-TPU / STPU (He et al., ICS 2020)

**Citation.** X. He, S. Pal, A. Amarnath, S. Feng, D.-H. Park, A. Rovinski, H. Ye, Y. Chen, R. Dreslinski,
T. Mudge, "Sparse-TPU: Adapting Systolic Arrays for Sparse Matrices," ICS 2020, doi:10.1145/3392717.3392751.
Author copy: <https://rovinski.github.io/pubs/he2020sparse.pdf>

Unstructured SpMV with offline column packing. It is included because it is the plainest precedent for metadata
that travels with the stationary values from memory.

1. **Metadata delivery [read].** "The increased bandwidth is utilized in STPU to load the indices of the matrix
   entries as well as to support float32 and int8 values. Each ... matrix entry loaded into the systolic array is
   held by the PE in its internal registers. PEs ... have double buffers to store the values and indices" (p. 6).
   "The PE receives its assigned matrix {value, index} entry from the left stream" (p. 6). Column index is a 16-bit
   unsigned integer (p. 6). The input scratchpad "stores tuples of (column index, value)" (p. 7).
2. **Control and sequencing [read].** Packing is offline (p. 2). Vector-group streaming is scheduled in hardware
   through double-buffered FIFOs and a crossbar control unit (p. 7). There is no host-issue discussion.
3. **Datapath [read].** Index **matching** in each PE (16-bit comparator; hold, latch and accumulate modes,
   Fig. 7, p. 6), not a mux. The memory side is a multi-bank scratchpad plus a swizzle-switch crossbar into FIFOs
   (p. 7).
4. **Evaluation [read].** "A custom cycle-accurate high-level language simulator" plus Design Compiler synthesis;
   128×128 arrays; synthetic and real SpMV matrices; baseline TPU (p. 7).
5. **Numbers [read].** 16.08x speedup; 4.39x / 19.79x lower energy (int8 / fp32); 12.93% area overhead (abstract,
   p. 1).

## 10. NVIDIA Ampere 2:4 Sparse Tensor Cores (Mishra et al. 2021, A100 whitepaper, PTX ISA, cuSPARSELt, TensorRT blog)

**Citations.**
- A. Mishra, J. Albericio Latorre, J. Pool, D. Stosic, D. Stosic, G. Venkatesh, C. Yu, P. Micikevicius,
  "Accelerating Sparse Deep Neural Networks," arXiv:2104.08378, 2021. <https://arxiv.org/abs/2104.08378>
- NVIDIA, "NVIDIA A100 Tensor Core GPU Architecture" whitepaper, 2020.
  <https://images.nvidia.com/aem-dam/en-zz/Solutions/data-center/nvidia-ampere-architecture-whitepaper.pdf>
- NVIDIA PTX ISA documentation, sections 9.7.16.6 (mma.sp), wgmma.mma_async.sp and 9.7.18.10 (tcgen05.mma.sp).
  <https://docs.nvidia.com/cuda/parallel-thread-execution/index.html> (current version read 2026-11-09)
- cuSPARSELt function reference. <https://docs.nvidia.com/cuda/cusparselt/functions.html>
- J. Pool, A. Sawarkar, J. Rodge, "Accelerating Inference with Sparsity Using the NVIDIA Ampere Architecture and
  NVIDIA TensorRT," NVIDIA Technical Blog, 20 Jul 2021.
  <https://developer.nvidia.com/blog/accelerating-inference-with-sparsity-using-ampere-and-tensorrt/>

1. **Metadata delivery [read].**
   - Format: "Metadata to decode compressed format is stored separately, using 2-bits to encode the position of
     each nonzero value within the group of 4 values ... Metadata information is needed to fetch corresponding
     values from the second matrix" (Mishra p. 4). Overhead: "only 2-bits metadata per value, limiting storage
     overhead to 12.5% and 25% for 16b and 8b values" (p. 4). For 8-bit operands, compression "saves ∼38% in
     memory capacity and bandwidth" (p. 4).
   - Ampere ISA: metadata is a **per-instruction register operand**. In `mma.sp ... d, a, b, c, e, f`, "Operand e
     is a 32-bit integer and operand f is a 32-bit integer constant with values in the range 0..3" (metadata and
     sparsity selector). "In a group of four consecutive threads, one or more threads store the metadata for the
     whole group", chosen by the sparsity selector (PTX 9.7.16.6.1). For int8 m16n8k32, "a thread-pair within a
     group of four consecutive threads contributes the sparsity metadata" (PTX). So threads load the metadata from
     memory with ordinary loads, and each MMA instruction carries it in a register.
   - Hopper `wgmma.mma_async.sp`: A and B come by shared-memory descriptor, but `sp-meta` is still "a 32-bit"
     register operand (PTX).
   - Blackwell `tcgen05.mma.sp`: metadata is an **on-chip memory address**, `[sp-meta-tmem]` in Tensor Memory, and
     "the sparsity selector selects the sub-columns in the Tensor Memory to form the sparsity metadata matrix" (PTX
     9.7.18.10.9.4). [inference: across three generations, metadata moved from a per-instruction register into an
     addressable on-chip buffer that the asynchronous tensor core reads by itself, as operand tiles grew.]
   - Software: weights are pruned and compressed ahead of time. `cusparseLtSpMMACompressedSize` returns one
     "compressedSize" for "the compressed matrix" (cuSPARSELt docs). [inference: values and metadata share one
     allocation; the docs do not describe the layout.] TensorRT 8.0+ does this automatically for 2:4 weights
     (Mishra p. 5).
2. **Control and sequencing [read / inference].** Sparse MMA is a warp-level instruction issued by the SM (PTX).
   The front end is thousands of threads, not one scalar core [inference]. The blog shows the CPU-issue analogue:
   gains grow "with the amount of work that the A100 is doing".
3. **Datapath [read].** "Sparse Tensor Core hardware selects only the elements from B that correspond to the
   nonzero values in A" (Mishra Fig. 2 caption, p. 5). Whitepaper: "only the elements in each row of Matrix A that
   have a non-zero value are matched with the corresponding elements from Matrix B. This transforms the computation
   into a smaller matrix multiply that takes just N/2 cycles" (p. 32). The mux is on the dense (B) operand side, and
   B is "of half the size" relative to the dense A tile in their example (whitepaper p. 32).
4. **Evaluation [read].** Mishra: cuSPARSELt (sparse) vs cuBLAS (dense) INT8 GEMMs on A100 over a sweep of GEMM
   sizes (Fig. 3, p. 6); accuracy over many networks. Blog: end-to-end TensorRT 8.0 on A100 at "various batch
   sizes" (ResNeXt-101_32x8d, FP16).
5. **Numbers and where speedup does NOT materialise [read].**
   - Kernel: "Speedups ... depend on several factors, such as arithmetic intensity and GEMM dimensions" (Mishra
     p. 5). "Larger GEMMs achieve nearly a 2× speedup" (Fig. 3, p. 6). One has to reach large N; for example, "for a
     sequence length of 256, one would need a batch size of 40 to see this plot with N equal to 10K" (p. 6). Library
     constraint: dimensions must be multiples of 32 for int8 (p. 5).
   - End-to-end: "Larger batch sizes generally lead to larger improvements, approaching 20% at the high end"
     (blog, ResNeXt-101 FP16 on A100). At small batch the benefit becomes power ("up to a 36% performance/watt
     gain"). Mishra reports no end-to-end network speedup, only GEMM speedups and accuracy.
   - Peak: INT8 624 dense vs 1248 sparse TOPS (blog Table 1). The whitepaper markets 2x math throughput (p. 32).
   - Third-party comparisons [read in those papers]: S2TA cites the "proprietary Nvidia A100 GPU implements fixed
     2/4 W-DBB, which achieves 1.5× speedup" (S2TA p. 11, citing [8]; secondary for NVIDIA). VEGETA's STC-like 2:4
     engine gives only 16% runtime reduction vs a dense CPU engine (VEGETA p. 11).

## 11. Gemmini-lineage: Gemmini itself and Stellar (Berkeley)

**Gemmini.** H. Genc et al., "Gemmini: Enabling Systematic Deep-Learning Architecture Evaluation via Full-Stack
Integration," DAC 2021; arXiv:1911.09925. Also the `ucb-bar/gemmini` README (master, read 2026-11-09).
- Why LOOP_WS exists [read, README "Matmul and Conv Loop Unrollers"]: "tiling these operations efficiently can be
  difficult for programmers, due to CPU and loop overheads ... To alleviate this difficulty, Gemmini's ISA includes
  high-level CISC-type instructions, which automatically tile and unroll large matmuls and convolutions ...
  implemented as FSMs, which double-buffer matmul/conv tiles ... and which monitor the proportion of
  load/store/execute instructions in the ROB". Also: "There's nothing these CISC instructions do which a programmer
  couldn't do by tiling and looping through the other ISA instructions" (README, "Loop Instructions").
- Host CPU sensitivity [read, arXiv p. 4]: "The less complex the DNN accelerator is, the more the computational
  burden is shifted onto the CPU, giving the host CPU a larger impact on end-to-end performance ... Adding a small
  amount of complexity to the accelerator allows us to reduce the area and complexity of the host CPU to a simple
  in-order core while preserving performance." (Their case is im2col: a BOOM host gave 2.0x without the im2col unit.)

**Stellar.** H. N. Genc, H. Kim, P. Ganesh, Y. S. Shao, "Stellar: An Automated Design Framework for Dense and
Sparse Spatial Accelerators," MICRO 2024. NSF PAR copy: <https://par.nsf.gov/servlets/purl/10618011>
1. **Metadata [read].** Generated accelerators have "spatial arrays, register files, private memory buffers,
   (optional) load-balancers, and a DMA" (p. 6). Programming: "to move a sparse CSR matrix from DRAM into a private
   memory buffer, programmers specify the addresses of the matrix's data and metadata arrays in DRAM" (p. 9), using
   RISC-V commands such as `set_metadata_addr` and `set_metadata_stride` (Listing 7, p. 10). The **DMA moves
   metadata like data**. The paper shows a generated array for "NVIDIA's A100 structured sparsity scheme" using an
   `OptimisticSkip` keyword (Fig. 5, p. 5). I found no evaluation of that 2:4 array.
2. **Sequencing [read].** "All instructions revolve around data transfers from one memory unit to another ...
   Spatial arrays begin execution as soon as their input register files are filled" (p. 9). Compute starts when its
   data arrives; the CPU does not issue it.
3. **Caution for LOOP_WS [read].** On Stellar's regenerated Gemmini: "the handwritten Gemmini could only reach 700
   MHz. The handwritten Gemmini includes complicated, centralized loop-unrollers, whose address generators failed to
   meet timing at higher frequencies" (ASAP7, p. 10). The DMA also mattered: a simple DMA issuing one request per
   cycle caused "latency-sensitive stalls", fixed by allowing "up to 16 independent" requests (p. 11).
4. **Evaluation [read].** Cycle-accurate simulation; "an end-to-end ResNet50 inference for Gemmini" (p. 10);
   ASAP7 synthesis; Stellar-Gemmini reached 90% of handwritten utilization at 500 MHz with 13% more area (p. 10).

---

## Comparison table

| Work | Sparsity | Metadata format, cost | How metadata reaches the PEs | Who sequences tiles | Mux / operand side | Evaluation | Memory in timing? | Headline (page) | Overhead (page) |
|---|---|---|---|---|---|---|---|---|---|
| STA-DBB (CAL'20) | W 4/8 DBB | 8-bit bitmask per 8-block | With weights, "from top" | not described | Activation 4:1 / 8:1 | RTL synth 16nm, iso-throughput | No | 3.14x area eff., 1.97x power eff. (Tbl II, p3) | (mux replaces 2 multipliers) |
| Sparse STA / VDBB (arXiv'20) | W DBB var., A sparse | 1 byte per block | With weights, from top | 4x Cortex-M33 (DMA) | Activation 8:1, HW IM2COL 3x BW | VCS RTL + PTPX 16nm | On-chip SRAM only | 16.8-55.7 TOPS/W (p1); -44.6% power (p9) | - |
| S2TA (HPCA'22) | W 4/8 + A DBB | 8-bit bitmask per 8-block; A mask made by HW (DAP) | In compressed blocks in WB/AB SRAM, DMA double-buffered | 4x Cortex-M33 MCUs, "never the bottleneck" (p7) | Activation 8:1 (W-only) | VCS RTL, full EDA 16/65nm, iso 4 TOPS | No DRAM model [inf.] | 2.11x speed, 2.08x energy vs SA-ZVCG (p10-11); S2TA-W capped 2x | DAP 2% area (Tbl 2, p7) |
| VEGETA (HPCA'23) | N:4 row-wise (1:4, 2:4, 4:4) | 2 bits per nz; 128 B mreg per tile | TILE_LOAD_M: 1 load instr per tile into metadata register | 1 CPU instr per tile, 4-wide OoO @2GHz, engine @0.5GHz | Input-side M:1, β blocks per row, broadcast to α | MacSim + Pin; RTL 15nm | No (data prefetched to L2, p11) | 2.20x on 2:4 (p1); STC-like only -16% (p11) | ≤6% area; 1-17% power (p11) |
| HighLight (MICRO'23) | Hierarchical G:H | CP offsets, multi-rank | GLB partition for metadata (Tbl 4) | n/a (analytical) | Dense-operand 8-to-4 mux; VFMU 2×Hmax buffer | Sparseloop + Accelergy 65nm | Yes (LPDDR4 energy) | 6.4x EDP vs dense (p2) | SAFs 5.7% area (p12) |
| TB-STC (HPCA'25) | Transposable block N:M | inter-block offsets + intra-block | Codec unit converts storage to compute format on the fly | GPU tensor core | MBD mux/transpose array on B | Cycle sim + Sparseloop + DC + Ramulator | Yes (64 GB/s) | e2e 1.22x vs HighLight (p10) | 1.57% of A100 die (p11) |
| DSTC (ISCA'21) | Unstructured, dual-side | Bitmap, 1 bit per element | Registers via warp instrs | GPU warp instrs, predicated skip | Outer product (no mux) | Accel-Sim (V100) | Yes (GPU sim) | up to 7.49x SpCONV (p2) | 1.5% die, 1.6% TDP (p12) |
| SPOTS (TACO'22) | Group-wise | Column + block bitmaps | Banked SRAM next to data | Input controller (HW) | Skip before array | Verilator RTL, 45nm | Per-layer | 2.16x vs Gemmini (p1) | - |
| Sparse-TPU (ICS'20) | Unstructured SpMV | 16-bit col index per entry | {value,index} streamed from HBM into PE regs | HW FIFOs / XCU | Index compare in PE | Custom cycle sim + DC | HBM assumed | 16.08x vs TPU (p1) | 12.93% area (p1) |
| NVIDIA Ampere STC | W 2:4 | 2 bits per nz (25% of int8) | Ampere/Hopper: 32-bit reg operand per MMA; Blackwell: Tensor Memory | GPU warps | Dense-B side select | Silicon: cuSPARSELt vs cuBLAS; TensorRT e2e | Yes (real HW) | ~2x large GEMM (Mishra Fig 3, p6); e2e ≤~20% (blog) | not published |
| Stellar (MICRO'24) | Generic (CSR, A100 2:4 shown) | Format-specific | DMA moves data + metadata arrays (p9) | Data-arrival triggered; RISC-V cmds are transfers | Generated | Cycle-accurate, ASAP7 | Yes (e2e ResNet50 for Gemmini) | 90% of handwritten Gemmini util. (p10) | +13% area vs Gemmini (p10) |

---

## Implications for this project

### (a) Metadata delivery: published designs never write index bits through the control path tile by tile

Every design read here does one of two things:

1. **Stores metadata in memory with, or next to, the compressed weights and moves it on chip through the data
   path.** STA, Sparse STA and S2TA send the bitmask with each weight block from the top of the array and keep it in
   the same SRAM. Sparse-TPU streams {value, index} tuples from HBM into PE registers. HighLight keeps a metadata
   partition of the GLB. SPOTS banks the bitmaps beside the data. Stellar's DMA takes "data and metadata arrays in
   DRAM" as one transfer descriptor.
2. **Loads it with one wide load per tile into a dedicated register or buffer.** VEGETA uses TILE_LOAD_M, 128 B per
   tile, as one instruction. NVIDIA uses a 32-bit register per mma.sp (Ampere, Hopper), and Blackwell reads it from
   Tensor Memory.

Our current scheme (4 or 8 `NM_META` RoCC writes of packed words per tile, each loaded first through the Rocket L1)
has no counterpart. **Fix (1), index metadata loaded by DMA into the meta FIFO, has strong precedent**: Sparse-TPU,
Stellar and the S2TA family all do it. The S2TA/STA variant also suggests a cheaper alternative: keep the index bits
**in the weight tile itself** (e.g. extra bytes per spad row, or a side array mvin'd with the same command) and
deliver them down the column with the weights during preload. That removes a separate FIFO and the ordering problem
between index tiles and preloads. Cost reference: 2 bits per kept weight (NVIDIA, VEGETA) is the norm for 2:4.
DBB-style bitmasks cost 1 bit per dense position.

### (b) CPU and sequencer issue: no published design reaching ~2x has its compute issue-bound by a 1-wide in-order core

- S2TA and Sparse STA use 4 Cortex-M33 MCUs and state that this is "sufficient to ensure that the MCUs are never
  the performance bottleneck" (S2TA p. 7). They give no supporting data.
- VEGETA issues **one** instruction per tile op from a 4-wide OoO core clocked 4x faster than the engine. Even
  then, back-to-back dependent tile ops needed output forwarding (32% runtime on 2:4).
- GPUs issue from many warps. NVIDIA has also moved toward asynchronous, descriptor-driven MMAs (wgmma, tcgen05)
  [inference: this cuts per-op issue work].
- Stellar starts compute when data arrives, so the CPU issues only transfers.
- Gemmini's own README says LOOP_WS exists because of "CPU and loop overheads". The Gemmini paper shows that the
  simpler the accelerator, the more the host CPU sets end-to-end performance.

So **fix (2), extending LOOP_WS to sparse mode, is backed by Gemmini's own design rationale and by the general
pattern**, but not by a specific published N:M paper. I found none that extends a Gemmini loop unroller. Two
cautions:
1. Stellar found that Gemmini's "centralized loop-unrollers, whose address generators failed to meet timing" capped
   it at 700 MHz (ASAP7). Adding a_hi bank placement and index-mvin generation to LoopMatmul adds to that critical
   logic, so check timing.
2. Fix (2) depends on fix (1). The unroller cannot emit CPU-side index loads, so index delivery must be a
   DMA/mvin-style command first. Our own estimate (worklog section 14) is that fix (1) alone gives about 0.83x
   (2:4) / 0.78x (4:8) of Berkeley on `small`. That is still CPU-bound, which matches the literature: issue rate
   must be decoupled from the scalar core to see the array's 2x.

### Other approaches to consider (from the literature)

- **Coarser sparse commands** (VEGETA-style): one command covering a whole K-strip of sparse tiles (preload +
  computes + index), so that issue cost per MAC falls even without a full LOOP_WS port. This is an intermediate step
  if extending LoopMatmul turns out too invasive.
- **In-line metadata** (STA/S2TA): pack the index bits into the weight rows, so that preload carries them and no
  extra command or FIFO is needed (see (a)).
- **Activation operand bandwidth**: our BANKSPLIT (a_lo / a_hi in different banks) matches the published fixes in
  kind. Published designs feed the extra activations through wider per-PE input blocks (STA/S2TA tensor PEs,
  VEGETA β blocks), aligned fetch plus a small shift buffer (HighLight VFMU, 2×Hmax blocks), or bandwidth
  magnification after the SRAM (Sparse STA hardware IM2COL, 3x).
- **Small dedicated sequencer**: the S2TA MCU-cluster model, i.e. a tiny control core or FSM next to Gemmini. This
  is a heavier change than extending LoopMatmul.

### What reviewers will expect in the evaluation

- **Baselines.** Dense on the same hardware at the same peak throughput and memory (every paper: S2TA's SA-ZVCG at
  iso-4-TOPS, VEGETA's RASA-DM, HighLight's TC-like, TB-STC's matched peak/on-chip memory/64 GB/s). Also the best
  available dense software path: NVIDIA compares cuSPARSELt to cuBLAS; DSTC uses CUTLASS and cuDNN. For us, that
  means **stock Gemmini with LOOP_WS** ("Berkeley"), not our own dense_stream issue loop. An NVIDIA-STC-like 2:4
  point is a common extra baseline (VEGETA, HighLight, TB-STC, S2TA-W).
- **Metrics.**
  - Kernel/layer speedup over a size sweep. NVIDIA shows speedup rising with GEMM size toward 2x, so reviewers
    will expect to see where the crossover is.
  - Full-model end-to-end time (S2TA, TB-STC, Stellar-Gemmini ResNet50).
  - Energy or EDP and area overhead in % (2-13% is the published range: TB-STC 1.57% of die, DSTC 1.5%, HighLight
    5.7%, VEGETA ≤6%, Sparse-TPU 12.93%, Stellar +13%), or iso-area perf/mm² (STA, S2TA TOPS/mm²).
  - Accuracy of 2:4 and 4:8 pruned models (every N:M paper reports it).
- **Memory included.** HighLight and TB-STC model DRAM. VEGETA states it excludes memory (data prefetched to L2).
  Our Verilator SoC includes the real memory system, which is a strength; say so explicitly and break time into
  CPU-issue, DMA and EX (the counters from worklog section 17 already do this).
- **Report where speedup does not appear.** S2TA states that FC/DW layers are memory bound. NVIDIA's end-to-end
  gain is about 20% at large batch against ~2x on kernels. Expect to show layers where sparse does not help, and
  why.
- **Process hygiene** (already in progress): the same binary for both configs, warm caches, several seeds. None of
  the papers read here report seed variance; doing so will help with reviewers.
