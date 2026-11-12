# Streaming benchmark tables (stream_analysis.py, from experiments/streaming/runs/20261109-144252/results.csv)

52 result rows, all verified. One number per row (the small layer's seeds 1-3 are identical). Area = whole-Gemmini standard-cell area (analysis/area/area.csv, SRAM macros excluded).

| Layer | Variant (chip) | Cycles | vs Berkeley best | vs dense_stream (stock) | MACs/cycle | MACs/cycle/mm² | perf/mm² vs Berkeley | ex_active | bytes read | no-alloc cycles (rs_full) ÷ total |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| edge | berkeley (nm24) | 4,306 | 1.000× | 1.131× | 68.5 | 8.35 | 0.950× | 1,767 | 12,800 | 99% |
| edge | dense_stream (nm24) | 4,908 | 0.877× | 0.992× | 60.1 | 7.33 | 0.833× | 1,551 | 12,800 | 99% |
| edge | sparse_stream (nm24) | 8,310 | 0.518× | 0.586× | 35.5 | 4.33 | 0.492× | 1,425 | 8,704 | 101% |
| edge | berkeley (nm48) | 4,373 | 0.984× | 1.114× | 67.4 | 7.89 | 0.898× | 1,791 | 12,800 | 99% |
| edge | dense_stream (nm48) | 4,834 | 0.890× | 1.007× | 61.0 | 7.14 | 0.812× | 1,547 | 12,800 | 99% |
| edge | sparse_stream (nm48) | 9,448 | 0.456× | 0.515× | 31.2 | 3.65 | 0.415× | 1,419 | 8,704 | 100% |
| edge | berkeley (stock) | 4,304 | 1.000× | 1.131× | 68.5 | 8.79 | 1.000× | 1,756 | 12,800 | 99% |
| edge | dense_stream (stock) | 4,870 | 0.884× | 1.000× | 60.6 | 7.77 | 0.884× | 1,547 | 12,800 | 99% |
| small | berkeley (nm24) | 14,842 | 1.000× | 1.246× | 141.3 | 17.23 | 0.950× | 9,275 | 49,152 | 94% |
| small | dense_stream (nm24) | 18,634 | 0.796× | 0.992× | 112.5 | 13.72 | 0.757× | 8,631 | 49,152 | 95% |
| small | sparse_stream (nm24) | 29,777 | 0.498× | 0.621× | 70.4 | 8.59 | 0.474× | 8,836 | 32,768 | 99% |
| small | berkeley (nm48) | 14,860 | 0.999× | 1.244× | 141.1 | 16.51 | 0.911× | 9,291 | 49,152 | 94% |
| small | dense_stream (nm48) | 18,588 | 0.798× | 0.995× | 112.8 | 13.20 | 0.728× | 8,613 | 49,152 | 95% |
| small | sparse_stream (nm48) | 34,518 | 0.430× | 0.536× | 60.8 | 7.11 | 0.392× | 8,836 | 32,768 | 99% |
| small | berkeley (stock) | 14,840 | 1.000× | 1.246× | 141.3 | 18.13 | 1.000× | 9,291 | 49,152 | 94% |
| small | dense_stream (stock) | 18,487 | 0.803× | 1.000× | 113.4 | 14.55 | 0.803× | 8,631 | 49,152 | 95% |
| bert_qkv | dense_stream (nm24) | 459,492 | 0.689× | 1.002× | 164.3 | 20.03 | 0.655× | 300,408 | 1,769,472 | 92% |
| bert_qkv | sparse_stream (nm24) | 651,640 | 0.486× | 0.706× | 115.9 | 14.13 | 0.462× | 301,818 | 1,474,560 | 97% |
| bert_qkv | sparse_stream (nm48) | 743,192 | 0.426× | 0.619× | 101.6 | 11.89 | 0.389× | 301,362 | 1,474,560 | 97% |
| bert_qkv | berkeley (stock) | 316,791 | 1.000× | 1.453× | 238.3 | 30.58 | 1.000× | 291,727 | 1,062,912 | 88% |
| bert_qkv | dense_stream (stock) | 460,206 | 0.688× | 1.000× | 164.1 | 21.05 | 0.688× | 300,414 | 1,769,472 | 92% |
| bert_ffn1 | dense_stream (nm24) | 1,827,348 | 0.787× | 1.000× | 165.3 | 20.15 | 0.748× | 1,201,866 | 7,077,888 | 91% |
| bert_ffn1 | sparse_stream (nm24) | 2,598,704 | 0.553× | 0.704× | 116.2 | 14.17 | 0.526× | 1,206,876 | 5,898,240 | 97% |
| bert_ffn1 | sparse_stream (nm48) | 3,000,588 | 0.479× | 0.609× | 100.6 | 11.78 | 0.437× | 1,205,094 | 5,898,240 | 97% |
| bert_ffn1 | berkeley (stock) | 1,438,120 | 1.000× | 1.271× | 210.0 | 26.94 | 1.000× | 1,182,510 | 3,766,272 | 89% |
| bert_ffn1 | dense_stream (stock) | 1,828,210 | 0.787× | 1.000× | 165.2 | 21.19 | 0.787× | 1,201,896 | 7,077,888 | 91% |
| bert_ffn2 | dense_stream (nm24) | 1,763,972 | 0.999× | 1.000× | 171.2 | 20.87 | 0.949× | 1,199,040 | 7,077,888 | 91% |
| bert_ffn2 | sparse_stream (nm24) | 2,556,093 | 0.689× | 0.690× | 118.1 | 14.40 | 0.655× | 1,219,205 | 5,898,240 | 97% |
| bert_ffn2 | sparse_stream (nm48) | 2,915,792 | 0.604× | 0.605× | 103.6 | 12.12 | 0.551× | 1,213,652 | 5,898,240 | 97% |
| bert_ffn2 | berkeley (stock) | 1,761,377 | 1.000× | 1.001× | 171.5 | 22.00 | 1.000× | 1,418,461 | 7,375,872 | 91% |
| bert_ffn2 | dense_stream (stock) | 1,763,352 | 0.999× | 1.000× | 171.3 | 21.97 | 0.999× | 1,198,899 | 7,077,888 | 91% |
| rn50_conv | dense_stream (nm24) | 740,332 | 0.894× | 1.002× | 156.2 | 19.04 | 0.849× | 485,494 | 2,985,984 | 92% |
| rn50_conv | sparse_stream (nm24) | 1,158,534 | 0.571× | 0.640× | 99.8 | 12.17 | 0.543× | 473,679 | 2,396,160 | 97% |
| rn50_conv | sparse_stream (nm48) | 1,346,269 | 0.491× | 0.551× | 85.9 | 10.05 | 0.448× | 473,527 | 2,396,160 | 98% |
| rn50_conv | berkeley (stock) | 661,605 | 1.000× | 1.121× | 174.7 | 22.42 | 1.000× | 562,519 | 2,815,296 | 90% |
| rn50_conv | dense_stream (stock) | 741,495 | 0.892× | 1.000× | 155.9 | 20.00 | 0.892× | 485,380 | 2,985,984 | 92% |

Definitions: see the header of stream_analysis.py. bytes read = rdma_bytes counter / 4.
no-alloc cycles (rs_full) = Gemmini's rs_full counter, which is !io.alloc.ready (ReservationStation.scala:611): cycles with no command allocated into the reservation station, idle cycles included. It is not a measure of a full queue. Its counting window is slightly longer than the timed region (~130-175 cycles, measured in the investigation), so it can exceed 100% on the smallest layers. See worklogs/investigate.md sections 9 and 17.
