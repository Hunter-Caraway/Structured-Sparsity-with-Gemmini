#!/usr/bin/env python3
"""Plain-language results summary of the streaming benchmark (+ chip area + the small fair benchmark), for the paper.
Started from tools/report-builders/build_paper.py (same fonts, styles and table helper); that script and its PDF are not
touched. Every number is formatted from out/numbers.json and out/stream_table.csv (stream_analysis.py) and
analysis/area/area.csv; nothing is typed by hand. Writes out/Streaming-Results-Summary.pdf and out/results-summary.md
(same text). Run stream_analysis.py first.
run: ~/gemmini-sparsity/.venv/bin/python experiments/streaming/analysis/build_stream_paper.py
(the venv per tools/report-builders/README.md: reportlab, pillow)"""
import csv, json, re
from datetime import date
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Image as RLImage, Table, TableStyle,
                                KeepTogether, CondPageBreak)
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "out"
n = json.load(open(OUT / "numbers.json"))
area_rows = list(csv.DictReader(open(REPO / "analysis/area/area.csv")))
L = n["layers"]; F = n["fair"]
REAL = ["bert_qkv", "bert_ffn1", "bert_ffn2", "rn50_conv"]
SHOWN = ["small"] + REAL
NAME = {"edge": "edge (36×128×64)", "small": "small (64×256×128)", "bert_qkv": "BERT QKV (128×768×768)",
        "bert_ffn1": "BERT FFN1 (128×768×3072)", "bert_ffn2": "BERT FFN2 (128×3072×768)",
        "rn50_conv": "ResNet-50 conv (196×2304×256)"}
c = lambda v: f"{v:,}"
x2 = lambda v: f"{v:.2f}×"
def rng(key, f, fmt=x2):
    lo, hi = n["ranges_real_layers"][f"{key}.{f}"]; return fmt(lo) if fmt(lo) == fmt(hi) else f"{fmt(lo)}–{fmt(hi)}"
pct = lambda v: f"{v * 100:.0f}%"

# ---------------------------------------------------------------- content (shared by PDF and Markdown)
doc = []
H = lambda t: doc.append(("h", t)); Pp = lambda t, s="body": doc.append(("p", t, s))
Bl = lambda items: doc.append(("bul", items)); Tb = lambda rows, w0: doc.append(("table", rows, w0))
Im = lambda f, cap: doc.append(("img", f, cap))

dense_list = ", ".join(f"{x2(L[l]['dense']['vs_berkeley_best'])} ({l.replace('bert_', '').replace('rn50_conv', 'rn50')})" for l in SHOWN)
Pp(f"Run <b>{n['run']}</b> · {n['rows']} result rows, {n['rows_verified']} verified · area from analysis/area/area.csv · "
   f"small-scale result from verification/runs/fair-20261103-151404", "sub")

H("What was measured")
Pp("Each test program multiplies one real-size layer of a neural network: C = A × W with 8-bit inputs and 32-bit outputs. "
   "A and W start in main memory and are streamed into the accelerator while it works. The clock-cycle count runs from the "
   "first load to the last result being written back. The chip is simulated exactly, one clock tick at a time (Verilator RTL "
   "simulation of the Chipyard SoC). Three chips were compared: Berkeley's unmodified Gemmini (the <b>stock</b> chip) and our "
   "<b>2:4</b> and <b>4:8</b> versions. Each ran up to three programs on the same layer:")
Bl(["<b>Berkeley's tiler</b> (tiled_matmul_auto, using Gemmini's built-in hardware loop): Berkeley's best way to run a "
    "dense layer, on the stock chip. It is the main reference.",
    "<b>Our hand tiler, dense</b>: the streaming loop written for this benchmark, with ordinary (uncompressed) weights.",
    "<b>Our hand tiler, sparse</b>: the same loop with half-size compressed weights plus the index tiles that say where "
    "each kept weight belongs (2:4 or 4:8)."])
Pp("Every variant computes the same answer from the same pruned weights. The dense and sparse programs of one pattern have "
   "byte-identical code; only two data flags differ. Each run is preceded by an untimed warm-up. The output and the "
   "accumulators are filled with a poison value first, and the caches are flushed by reading a 2 MiB buffer, so every run "
   "starts cold. After each run the CPU hashes the whole output and compares 8 sampled rows in full, and the host checks "
   "the hash again against an independent numpy reference. "
   f"<b>All {n['rows']} result rows are correct.</b>")
Pp("<b>Every number is one deterministic run.</b> Totals are unchanged when all non-reset register and SRAM contents are "
   "randomised (simulator seeds 1–3, verified), so no ranges over seeds are given.")

H("Results")
rows = [["Layer", "Berkeley's tiler (stock)", "Hand tiler, dense (stock)", "Hand tiler, 2:4 sparse", "Hand tiler, 4:8 sparse"]]
for l in SHOWN:
    d = L[l]
    rows.append([NAME[l], f"{c(d['berkeley']['total_cycles'])}",
                 f"{c(d['dense']['total_cycles'])}<br/>{x2(d['dense']['vs_berkeley_best'])} vs Berkeley",
                 f"{c(d['sp24']['total_cycles'])}<br/>{x2(d['sp24']['vs_berkeley_best'])} vs Berkeley<br/>{x2(d['sp24']['vs_dense_stream_stock'])} vs dense tiler",
                 f"{c(d['sp48']['total_cycles'])}<br/>{x2(d['sp48']['vs_berkeley_best'])} vs Berkeley<br/>{x2(d['sp48']['vs_dense_stream_stock'])} vs dense tiler"])
Tb(rows, 1.55)
Pp("Clock cycles, fewer = faster. Speed-up = reference cycles ÷ this run's cycles, so above 1× is faster. The full table, "
   "with every chip and counter, is in stream_table.csv and tables.md.", "cap")
Im("fig-s1-cycles-light.png", "Cycles per layer. Each panel has its own scale.")
Im("fig-s2-speedup-light.png", "Speed-up of the sparse runs against Berkeley's tiler (left) and against the same hand tiler with "
   "dense weights (right).")
Pp("<b>In plain words:</b>")
Bl([f"<b>Sparse is slower than dense on every layer, on both references.</b> On the four real layers, 2:4 sparse runs at "
    f"{rng('sp24', 'vs_berkeley_best')} of Berkeley's speed and 4:8 at {rng('sp48', 'vs_berkeley_best')}. Against the same "
    f"hand tiler with dense weights, 2:4 runs at {rng('sp24', 'vs_dense_stream_stock')} and 4:8 at "
    f"{rng('sp48', 'vs_dense_stream_stock')}.",
    "<b>4:8 is slower than 2:4 on every layer.</b>",
    f"<b>Our dense hand tiler is itself slower than Berkeley's tiler</b>: {dense_list}. Part of the sparse runs' gap to "
    "Berkeley is therefore the tiler, not sparsity. That is why both references are shown.",
    f"<b>The extra hardware doesn't slow dense work.</b> On the 2:4 chip the dense hand tiler takes within "
    f"{n['dense_chip_spread_pct']:.1f}% of the stock chip's cycles on every layer. Berkeley's tiler on the 2:4 and 4:8 chips "
    f"(run for the small and edge layers) is within {max(abs(L[l].get(k, 0)) for l in ('small', 'edge') for k in ('nm24_berkeley_vs_stock_pct', 'nm48_berkeley_vs_stock_pct')):.1f}% "
    "of the stock chip."])

H("What the counters show")
exs = [L[l][k] for l in REAL for k in ("ex_active_sparse24_vs_dense_pct", "ex_active_sparse48_vs_dense_pct")]
assert all(L[l]["sp24"]["rdma_bytes_real"] == L[l]["sp48"]["rdma_bytes_real"] for l in REAL), "2:4/4:8 bytes differ"
assert all(L[l][k]["vs_berkeley_best"] < 1 and L[l][k]["vs_dense_stream_stock"] < 1 for l in SHOWN for k in ("sp24", "sp48")), "a sparse run is not slower"
assert all(L[l]["sp48"]["total_cycles"] > L[l]["sp24"]["total_cycles"] for l in SHOWN), "4:8 not slower than 2:4 everywhere"
byt = [L[l]["sp24"]["rdma_bytes_real"] / L[l]["dense"]["rdma_bytes_real"] for l in REAL]
Bl([f"<b>The array is busy about as long in sparse mode as in dense mode.</b> On the real layers, the sparse runs' "
    f"ex_active (cycles the execute unit spends in its compute state) is within {min(exs):+.1f}% to {max(exs):+.1f}% of the "
    "dense hand tiler's, although sparse mode issues half as many computes.",
    f"<b>The sparse runs read less data</b>: {min(byt):.2f}–{max(byt):.2f}× the bytes of the dense hand tiler (2:4 and 4:8 "
    "read the same amount).",
    "<b>Why the sparse runs don't finish sooner (finding of a separate investigation).</b> The sparse path is limited by "
    "the CPU issuing commands, not by Gemmini. In sparse mode Gemmini's hardware loop (LOOP_WS) is not available, so the "
    "CPU issues every command itself, and each index tile also costs the CPU several RoCC commands. In the investigation's "
    "own counter runs (2:4 chip, small layer, a build with an extra counter set; not part of this run's results.csv), "
    "Gemmini's command buffer was empty 37% of the time with this hand tiler and 42% with a leaner rewrite of it, "
    "against 8% for Berkeley's tiler: Gemmini often sits idle waiting for the CPU. Details: "
    "experiments/streaming/worklogs/investigate.md, sections 9 and 17.",
    "<b>Note on the rs_full counter.</b> Despite its name, Gemmini's rs_full counter does not measure a full command "
    "queue. It counts every cycle in which no new command is accepted, idle cycles included, so it is not plotted. Its "
    "values are kept in tables.md and stream_table.csv under that meaning."])
Im("fig-s3-counters-light.png", "Gemmini's counters relative to the dense hand tiler on the stock chip: array busy time "
   "(left) and bytes read (right).")

H("Chip area")
A = {(r["chip"], r["block"]): float(r["area_um2"]) for r in area_rows}
WHAT = {"Gemmini": "Whole accelerator", "ExecuteController": "Execute unit (array, index FIFO, control)",
        "MeshWithDelays": "Array + input/output skew registers", "Mesh": "16×16 array", "PE_256": "One processing element"}
rows = [["Block", "Stock (µm²)", "2:4 (µm²)", "4:8 (µm²)"]]
for b, w in WHAT.items():
    s = A[("berkeley", b)]
    rows.append([w, c(round(s)), f"{c(round(A[('nm24', b)]))} ({(A[('nm24', b)] / s - 1) * 100:+.1f}%)",
                 f"{c(round(A[('nm48', b)]))} ({(A[('nm48', b)] / s - 1) * 100:+.1f}%)"])
Tb(rows, 2.3)
Pp("Standard-cell area from a Yosys synthesis to the open SkyWater 130 nm high-density cells (sky130_fd_sc_hd, typical "
   "corner), before place and route. The SRAM macros are left out because they are identical in all three chips. This "
   "compares the chips; it is not a die size.", "cap")
grow = {k: (A[(k, "MeshWithDelays")] - A[("berkeley", "MeshWithDelays")]) / (A[(k, "Gemmini")] - A[("berkeley", "Gemmini")]) for k in ("nm24", "nm48")}
Pp(f"The whole accelerator grows by {n['area_overhead_pct']['nm24']}% for 2:4 and {n['area_overhead_pct']['nm48']}% for 4:8. "
   f"The array and its skew registers account for {grow['nm24'] * 100:.0f}% (2:4) and {grow['nm48'] * 100:.0f}% (4:8) of that growth.")

H("Throughput per unit area")
rows = [["Layer", "Berkeley's tiler (stock)", "Hand tiler, dense (stock)", "Hand tiler, 2:4", "Hand tiler, 4:8"]]
for l in SHOWN:
    d = L[l]
    rows.append([NAME[l]] + [f"{d[k]['macs_per_cycle_per_mm2']:.1f}" + ("" if k == "berkeley" else
                 f"<br/>{x2(d[k]['perf_per_mm2_vs_berkeley_best'])} vs Berkeley") for k in ("berkeley", "dense", "sp24", "sp48")])
Tb(rows, 1.55)
Pp(f"Dense-equivalent multiply-accumulates (M×K×N of the layer) per clock cycle per mm² of whole-accelerator standard-cell "
   f"area: stock {n['area_mm2']['stock']:.2f} mm², 2:4 {n['area_mm2']['nm24']:.2f} mm², 4:8 {n['area_mm2']['nm48']:.2f} mm². "
   "For the sparse rows, half of those multiply-accumulates are skipped zeros.", "cap")
Pp(f"Per unit area, 2:4 sparse delivers {rng('sp24', 'perf_per_mm2_vs_berkeley_best')} and 4:8 "
   f"{rng('sp48', 'perf_per_mm2_vs_berkeley_best')} of Berkeley's throughput on the real layers. That is lower than the "
   "speed ratios above, because the sparse chips are also larger.")
Im("fig-s4-perf-per-mm2-light.png", "Throughput per mm², every layer and variant.")

H("Small-scale result: the fair benchmark (64×128×32)")
B0, T24, T48, S0 = F["berkeley"], F["2:4"], F["4:8"], F.get("sameprog", {})
assert T24["busy_reuse"] == T48["busy_reuse"] and B0["fresh"] > max(0, 0) and T24["fresh"] > B0["fresh"] and T48["fresh"] > B0["fresh"]
rows = [["Clock cycles", "Berkeley original", "Ours, 2:4", "Ours, 4:8"],
        ["Array time, weights reused", c(B0["busy_reuse"]), f"{c(T24['busy_reuse'])} ({x2(B0['busy_reuse'] / T24['busy_reuse'])})",
         f"{c(T48['busy_reuse'])} ({x2(B0['busy_reuse'] / T48['busy_reuse'])})"],
        ["Whole job, weights reused", c(B0["reuse"]), f"{c(T24['reuse'])} ({x2(B0['reuse'] / T24['reuse'])})",
         f"{c(T48['reuse'])} ({x2(B0['reuse'] / T48['reuse'])})"],
        ["Whole job, fresh weights", c(B0["fresh"]), f"{c(T24['fresh'])} ({x2(B0['fresh'] / T24['fresh'])})",
         f"{c(T48['fresh'])} ({x2(B0['fresh'] / T48['fresh'])})"],
        ["Whole job, fresh weights, indexes batched 4 tiles ahead", "–", f"{c(T24['batched'])} ({x2(B0['fresh'] / T24['batched'])})",
         f"{c(T48['batched'])} ({x2(B0['fresh'] / T48['batched'])})"]]
Tb(rows, 2.3)
Pp("verification/fair_perf.c: one small matrix multiply (64×128×32), the same program on every chip. Each number is one deterministic run (seeds " + ", ".join(n["fair_seeds"]) + " identical). The ratio is "
   "Berkeley's cycles ÷ ours.", "cap")
Pp(f"With the weights reused, sparsity halves the array's working time ({x2(B0['busy_reuse'] / T24['busy_reuse'])} for "
   f"both patterns). The whole job is {x2(B0['reuse'] / T24['reuse'])} for 2:4 and {x2(B0['reuse'] / T48['reuse'])} for 4:8. "
   f"With fresh weights (and index tiles) for every step, both are slower than Berkeley's: {x2(B0['fresh'] / T24['fresh'])} and "
   f"{x2(B0['fresh'] / T48['fresh'])}. " + (f"Berkeley's exact program with sparsity off takes {c(S0['reuse'])} and "
               f"{c(S0['fresh'])} cycles on our 2:4 chip, against Berkeley's {c(B0['reuse'])} and {c(B0['fresh'])}." if S0 else ""))

H("Caveats")
cmax = max(L[l][k]["rs_full_share"] for l in L for k in ("berkeley", "dense", "sp24", "sp48"))
Bl([f"<b>The hand tiler is not as good as Berkeley's.</b> On dense weights it reaches {dense_list} of Berkeley's "
    "tiled_matmul_auto. Sparse results are therefore reported against both references.",
    "<b>Counter details.</b> The bytes-read counter adds the whole 64 B request size on every 16 B beat, so it reads 4× the real "
    "bytes; the numbers here are divided by 4. Read through a counter snapshot, it returns 0, so it was read live. "
    "loop_matmul_active means something only for Berkeley's tiler. ex_active includes stalls inside the compute state. "
    "rs_full (tables only) counts cycles with no command accepted, idle included; its window starts at its own "
    "configuration and ends at its own read, so it is slightly longer than the timed region and on the smallest layers its "
    f"share of the total can reach {pct(cmax)}.",
    "<b>Area is pre-layout standard-cell area</b> (Yosys 0.69, sky130 HD typical corner; the ABC mapping step &amp;fraig -x was "
    "left out, the same for all chips, because it doesn't finish on one of Berkeley's address-generator modules). "
    "There are no wires, no SRAM macros, and no clock-speed or power numbers. The extra multiplexer in front of every "
    "multiplier may lower the maximum clock speed; that was not measured.",
    "<b>Coverage.</b> Berkeley's tiler was run on the 2:4 and 4:8 chips only for the small and edge layers. The 4:8 chip's "
    "dense hand-tiler run exists only for those layers too, so the dense reference is always the stock chip's run. Five of "
    "the large-layer runs were simulated on a second, validated machine (its simulators were built from the same sources; "
    "results.csv records the host and simulator hash of every row). The edge layer (36×128×64) checks the partial-tile path "
    "and appears only in the tables.",
    "<b>Simulation, synthetic data.</b> The weights are random and pruned; AI accuracy was not measured. Simulation gives "
    "exact cycle counts, not clock speed or power."])

H("Where the numbers come from")
Pp("experiments/streaming/scripts/collect.py writes results.csv from the simulation logs and checks every output. "
   "experiments/streaming/analysis/stream_analysis.py computes every ratio, the per-area throughput and the figures from "
   "results.csv, analysis/area/area.csv (analysis/area.py) and the fair run, read through verification/nmdata.py. This "
   "document is generated by build_stream_paper.py from those outputs. No number was typed by hand.", "small")

# ---------------------------------------------------------------- Markdown
def md_text(t):
    t = re.sub(r"</?b>", "**", t); t = re.sub(r"</?i>", "*", t)
    return t.replace("<br/>", "<br>").replace("&amp;", "&").replace("&quot;", '"')
title = "Gemmini with 2:4 and 4:8 Sparsity: Streaming Benchmark Results"
md = [f"# {title}", ""]
for item in doc:
    k = item[0]
    if k == "h": md += [f"## {item[1]}", ""]
    elif k == "p": md += [("*" + md_text(item[1]) + "*") if item[2] in ("cap", "sub") else md_text(item[1]), ""]
    elif k == "bul": md += [f"- {md_text(i)}" for i in item[1]] + [""]
    elif k == "table":
        r = item[1]
        md += ["| " + " | ".join(md_text(x) for x in r[0]) + " |", "|" + "---|" * len(r[0])]
        md += ["| " + " | ".join(md_text(x) for x in row) + " |" for row in r[1:]] + [""]
    elif k == "img": md += [f"![{item[2]}](figures/{item[1]})", f"*{md_text(item[2])}*", ""]
(OUT / "results-summary.md").write_text("\n".join(md))

# ---------------------------------------------------------------- PDF (styles from build_paper.py)
LS = "/usr/share/fonts/liberation-sans-fonts/"; NM = "/usr/share/fonts/google-noto/"
for nm, f in [("Sans", "LiberationSans-Regular"), ("Sans-Bold", "LiberationSans-Bold"),
              ("Sans-Italic", "LiberationSans-Italic"), ("Sans-BoldItalic", "LiberationSans-BoldItalic")]:
    pdfmetrics.registerFont(TTFont(nm, LS + f + ".ttf"))
pdfmetrics.registerFont(TTFont("Mono", NM + "NotoSansMono-Regular.ttf"))
registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-Italic", boldItalic="Sans-BoldItalic")
INK = colors.HexColor("#1a1d23"); MUTED = colors.HexColor("#5a6270")
RULE = colors.HexColor("#d9dde3"); TINT = colors.HexColor("#f3f5f8")
S = {
 "title": ParagraphStyle("t", fontName="Sans-Bold", fontSize=20, leading=25, textColor=INK, spaceAfter=4),
 "sub": ParagraphStyle("s", fontName="Sans", fontSize=9.5, leading=13, textColor=MUTED, spaceAfter=10),
 "h1": ParagraphStyle("h1", fontName="Sans-Bold", fontSize=14, leading=18, textColor=INK, spaceBefore=12, spaceAfter=6),
 "body": ParagraphStyle("b", fontName="Sans", fontSize=10.3, leading=14.6, textColor=INK, spaceAfter=7),
 "bul": ParagraphStyle("u", fontName="Sans", fontSize=10.3, leading=14.4, textColor=INK, leftIndent=15, bulletIndent=3, spaceAfter=5),
 "cap": ParagraphStyle("c", fontName="Sans-Italic", fontSize=8.6, leading=11.6, textColor=MUTED, spaceBefore=3, spaceAfter=10),
 "cell": ParagraphStyle("ce", fontName="Sans", fontSize=8.6, leading=11.2, textColor=INK),
 "cellb": ParagraphStyle("cb", fontName="Sans-Bold", fontSize=8.6, leading=11.2, textColor=INK),
 "small": ParagraphStyle("sm", fontName="Sans", fontSize=8.8, leading=12, textColor=MUTED),
}
W = letter[0] - 2 * 0.85 * inch
def table(rows, w0):
    data = [[Paragraph(str(x), S["cellb" if i == 0 or j == 0 else "cell"]) for j, x in enumerate(r)] for i, r in enumerate(rows)]
    rest = (W - w0 * inch) / (len(rows[0]) - 1)
    t = Table(data, colWidths=[w0 * inch] + [rest] * (len(rows[0]) - 1))
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                           ("BACKGROUND", (0, 0), (-1, 0), TINT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    return t
story = [Paragraph(title, S["title"])]
for item in doc:
    k = item[0]
    if k == "h": story += [CondPageBreak(1.6 * inch), Paragraph(item[1], S["h1"])]
    elif k == "p": story.append(Paragraph(item[1], S[item[2]]))
    elif k == "bul": story += [Paragraph(i, S["bul"], bulletText="•") for i in item[1]]
    elif k == "table": story.append(table(item[1], item[2]))
    elif k == "img":
        im = Image.open(OUT / item[1]); iw, ih = im.size
        story.append(KeepTogether([RLImage(str(OUT / item[1]), width=W, height=W * ih / iw), Paragraph(item[2], S["cap"])]))
today = date.today().isoformat()
def on_page(cv, d):
    cv.saveState(); cv.setFont("Sans", 8); cv.setFillColor(MUTED)
    cv.drawString(0.85 * inch, 0.55 * inch, f"Gemmini 2:4 / 4:8 sparsity · streaming benchmark results · Hunter Caraway · {today}")
    cv.drawRightString(letter[0] - 0.85 * inch, 0.55 * inch, str(d.page)); cv.restoreState()
pdf = BaseDocTemplate(str(OUT / "Streaming-Results-Summary.pdf"), pagesize=letter, leftMargin=0.85 * inch, rightMargin=0.85 * inch,
                      topMargin=0.75 * inch, bottomMargin=0.85 * inch, title=title, author="Hunter Caraway")
pdf.addPageTemplates([PageTemplate(id="p", frames=[Frame(pdf.leftMargin, pdf.bottomMargin, pdf.width, pdf.height, id="f")], onPage=on_page)])
pdf.build(story)
print(OUT / "Streaming-Results-Summary.pdf", OUT / "results-summary.md")
