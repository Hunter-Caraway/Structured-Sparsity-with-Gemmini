#!/usr/bin/env python3
"""Short results summary for the paper: Berkeley original vs our 2:4 and 4:8 (fair, identical loops), plain language."""
import json, re
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Image as RLImage,
                                Table, TableStyle, KeepTogether, CondPageBreak)
from PIL import Image

PROJ = Path(__file__).resolve().parents[2]
VER = PROJ / "verification"
OUT = PROJ / "N-M-Sparsity-Paper-Summary.pdf"
d = json.load(open(VER / "paper_data.json"))
fid = {}
for l in (VER / "pattern_fidelity.out").read_text().splitlines():
    m = re.match(r"^(bell curve|heavy tail)\s+(paired 4:8|2:4|4:8|no pattern)\s+([\d.]+)%\s+([\d.]+)%", l)
    if m: fid[(m[1], m[2])] = (float(m[3]), float(m[4]))

LS = "/usr/share/fonts/liberation-sans-fonts/"; NM = "/usr/share/fonts/google-noto/"
for n, f in [("Sans", "LiberationSans-Regular"), ("Sans-Bold", "LiberationSans-Bold"),
             ("Sans-Italic", "LiberationSans-Italic"), ("Sans-BoldItalic", "LiberationSans-BoldItalic")]:
    pdfmetrics.registerFont(TTFont(n, LS + f + ".ttf"))
pdfmetrics.registerFont(TTFont("Mono", NM + "NotoSansMono-Regular.ttf"))
registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-Italic", boldItalic="Sans-BoldItalic")
INK = colors.HexColor("#1a1d23"); MUTED = colors.HexColor("#5a6270")
RULE = colors.HexColor("#d9dde3"); TINT = colors.HexColor("#f3f5f8")
S = {
 "title": ParagraphStyle("t", fontName="Sans-Bold", fontSize=22, leading=27, textColor=INK, spaceAfter=4),
 "sub": ParagraphStyle("s", fontName="Sans", fontSize=11.5, leading=16, textColor=MUTED, spaceAfter=12),
 "h1": ParagraphStyle("h1", fontName="Sans-Bold", fontSize=14.5, leading=19, textColor=INK, spaceBefore=12, spaceAfter=6),
 "body": ParagraphStyle("b", fontName="Sans", fontSize=10.5, leading=15, textColor=INK, spaceAfter=7),
 "bul": ParagraphStyle("u", fontName="Sans", fontSize=10.5, leading=14.8, textColor=INK, leftIndent=15, bulletIndent=3, spaceAfter=5),
 "cap": ParagraphStyle("c", fontName="Sans-Italic", fontSize=8.8, leading=11.8, textColor=MUTED, spaceBefore=3, spaceAfter=10),
 "cell": ParagraphStyle("ce", fontName="Sans", fontSize=9.2, leading=12, textColor=INK),
 "cellb": ParagraphStyle("cb", fontName="Sans-Bold", fontSize=9.2, leading=12, textColor=INK),
 "box": ParagraphStyle("r", fontName="Sans", fontSize=10.5, leading=15, textColor=INK, backColor=colors.HexColor("#eef4fd"),
                       borderPadding=(9, 10, 9, 10), leftIndent=10, rightIndent=10, spaceBefore=6, spaceAfter=14),
 "small": ParagraphStyle("sm", fontName="Sans", fontSize=8.8, leading=12, textColor=MUTED),
}
W = letter[0] - 2 * 0.95 * inch
def P(t, s="body"): return Paragraph(t, S[s])
def M(t): return f"<font name='Mono' size='9'>{t}</font>"
def B(items): return [Paragraph(i, S["bul"], bulletText="•") for i in items]
def table(rows, widths):
    data = [[Paragraph(str(c), S["cellb" if i == 0 or j == 0 else "cell"]) for j, c in enumerate(r)] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                           ("BACKGROUND", (0, 0), (-1, 0), TINT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    return t

B0, T24, T48, CPU = d["berkeley"], d["ours_2:4"], d["ours_4:8"], d["cpu"]
OFF = d["ours_off_2:4"]
def r(a, b): return a / b
def word(x): return "faster" if x > 1.02 else "slower" if x < 0.98 else "about the same"
def x(a, b):
    v = r(a, b); return f"<b>{v:.2f}×</b> ({word(v)})"
def c(v): return f"{v:,}"
g24, g48 = r(B0["busy"], T24["busy"]), r(B0["busy"], T48["busy"])
e24, e48 = r(B0["reuse"], T24["reuse"]), r(B0["reuse"], T48["reuse"])
f24, f48 = r(B0["fresh"], T24["fresh"]), r(B0["fresh"], T48["fresh"])
def pct(v): return f"{abs(v - 1) * 100:.0f}%"

story = [P("Gemmini with 2:4 and 4:8 Sparsity: Results Summary", "title"),
         P("How our modified chip compares with UC Berkeley's original, what the numbers mean, and which pattern makes sense", "sub"),
         P("What was compared", "h1"),
         P("Three versions of the chip did the <b>same job</b>: multiplying a 64 × 128 table of numbers by a 128 × 32 table, "
           "the core operation of an AI model, using the same input numbers. Each was run in a simulation that reproduces "
           "the chip's circuit exactly, one tick of its clock at a time. Time is counted in <b>clock cycles</b>, and fewer "
           "cycles means faster. All three ran <b>the same, efficiently written test program</b>, so the only differences are "
           "the chip and the sparsity pattern. Every result was checked against an answer the processor computed "
           "separately, and all of them were correct."),
         *B(["<b>Berkeley original</b>: UC Berkeley's Gemmini design, unmodified. It multiplies every number, zeros included.",
             "<b>Ours, 2:4</b>: our modified Gemmini, with the weights pruned so that every group of 4 keeps only 2. "
             "The chip skips the rest.",
             "<b>Ours, 4:8</b>: the same idea with groups of 8, keeping any 4 of each 8."]),
         P("Results", "h1")]
rows = [["Clock cycles (fewer = faster)", "Berkeley original", "Ours, 2:4", "Ours, 4:8"],
        ["Blocks of weights to process", c(B0["tiles"]), f"{c(T24['tiles'])} (half)", f"{c(T48['tiles'])} (half)"],
        ["Multiplier grid working time<br/><font size='8' color='#5a6270'>just the part that does the multiplying</font>",
         c(B0["busy"]), f"{c(T24['busy'])}<br/>{x(B0['busy'], T24['busy'])}", f"{c(T48['busy'])}<br/>{x(B0['busy'], T48['busy'])}"],
        ["<b>Whole job, weights reused</b><br/><font size='8' color='#5a6270'>the realistic case: load weights once, use them many times</font>",
         c(B0["reuse"]), f"{c(T24['reuse'])}<br/>{x(B0['reuse'], T24['reuse'])}", f"{c(T48['reuse'])}<br/>{x(B0['reuse'], T48['reuse'])}"],
        ["Whole job, fresh weights every step<br/><font size='8' color='#5a6270'>a stress test with no reuse</font>",
         c(B0["fresh"]), f"{c(T24['fresh'])}<br/>{x(B0['fresh'], T24['fresh'])}", f"{c(T48['fresh'])}<br/>{x(B0['fresh'], T48['fresh'])}"],
        ["Processor time just to send the instructions<br/><font size='8' color='#5a6270'>same jobs, chip disconnected (reused / fresh)</font>",
         f"{c(CPU['berkeley_reuse'])} / {c(CPU['berkeley_fresh'])}", f"{c(CPU['2:4_reuse'])} / {c(CPU['2:4_fresh'])}",
         f"{c(CPU['4:8_reuse'])} / {c(CPU['4:8_fresh'])}"]]
story += [table(rows, [2.3 * inch, (W - 2.3 * inch) / 3, (W - 2.3 * inch) / 3, (W - 2.3 * inch) / 3]),
          P("Speed-ups are Berkeley's cycles divided by ours. Results within 2% are counted as &quot;about the same&quot;.", "cap")]
im = Image.open(VER / "paper_chart.png"); iw, ih = im.size
chart = RLImage(str(VER / "paper_chart.png"), width=W, height=W * ih / iw); chart.hAlign = "CENTER"
story += [KeepTogether([chart, P("The first three rows of the table as bars. Shorter bars are faster.", "cap")])]
SAME = d.get("ours_off_sameprog")
own24 = r(OFF["reuse"], T24["reuse"])          # 2:4 against our own chip's normal mode, same program
HW_SAME = bool(SAME) and abs(r(B0["reuse"], SAME["reuse"]) - 1) <= 0.02 and abs(r(B0["fresh"], SAME["fresh"]) - 1) <= 0.02
if SAME and HW_SAME:
    note = (f"<b>Does the sparse hardware slow down normal use?</b> No. Running Berkeley's exact program with sparsity switched "
            f"off, our chip took {c(SAME['reuse'])} and {c(SAME['fresh'])} cycles, against Berkeley's {c(B0['reuse'])} and "
            f"{c(B0['fresh'])}. Inside the full test program, the same normal-mode steps took {c(OFF['reuse'])} and {c(OFF['fresh'])} "
            "cycles on our chip. That few-percent gap comes from where the program's code sits in memory, not from the hardware. "
            "So differences of a few percent in these results are within the noise.")
elif SAME:
    sd = r(B0["reuse"], SAME["reuse"])
    note = (f"<b>Does the sparse hardware slow down normal use?</b> Slightly. Running Berkeley's exact program with sparsity "
            f"switched off, our chip took {c(SAME['reuse'])} cycles for the realistic job against Berkeley's {c(B0['reuse'])} "
            f"({sd:.2f}×). The added sparse circuitry costs some normal-mode speed.")
else:
    note = (f"Our chip with sparsity switched off took {c(OFF['reuse'])} cycles for the realistic job, against Berkeley's {c(B0['reuse'])}.")
story += [P(note, "small")]

story += [CondPageBreak(3 * inch), P("What the data means", "h1"),
          *B([f"<b>The hardware change works.</b> With half the weights removed, the multiplier grid finishes its work in "
              f"about half the time: {g24:.2f}× faster than Berkeley's original, the same for 2:4 and 4:8, because both "
              "remove exactly half the weights.",
              f"<b>But the whole job doesn't get faster.</b> In the realistic case, 2:4 runs at {e24:.2f}× Berkeley's speed "
              f"(and {own24:.2f}× our own chip's normal mode within the same program): essentially break-even. 4:8 is clearly "
              f"slower ({e48:.2f}×). With fresh weights every step, both are much slower ({f24:.2f}× and {f48:.2f}×).",
              "<b>Why: the chip can only work as fast as it receives instructions.</b> The main processor sends Gemmini every "
              "instruction one at a time, and sparse mode adds extra ones: &quot;position notes&quot; telling the chip which input "
              "goes with each kept weight (4 extra per block for 2:4, 8 for 4:8). The last row of the table shows the cost. "
              f"Even with the chip disconnected, the processor needs {c(CPU['2:4_fresh'])} cycles to send the 2:4 job's "
              f"instructions and {c(CPU['4:8_fresh'])} for 4:8, against {c(CPU['berkeley_fresh'])} for Berkeley's, even though "
              "the sparse jobs have half as many blocks. Think of a kitchen that got twice as fast but still gets its orders "
              "from one waiter, who now has to carry extra slips. The meal doesn't arrive much sooner.",
              "<b>Why 4:8 trails 2:4:</b> its position notes are bigger (3 bits per weight instead of 2), so it needs twice as "
              "many extra instructions, which adds more to the processor's workload.",
              "<b>Bottom line:</b> sparsity does halve the multiplying work. In this design, though, the saving is used up by "
              "sending position notes, so there's no meaningful overall speed-up yet. The fix is clear: let the chip read the "
              "notes from memory itself, alongside the weights, instead of having the processor send them. That would remove "
              "most of the extra processor work and let the overall result move toward the grid's 2×. This is a prediction, "
              "not something measured here."])]

f = lambda dist, rule: fid[(dist, rule)][0]
story += [CondPageBreak(3.2 * inch), P("Which pattern makes the most sense: 2:4, 4:8, or paired 4:8?", "h1"),
          P("All three keep exactly half the weights. The difference is <b>which</b> half they're allowed to keep:"),
          *B(["<b>2:4</b>: every group of 4 keeps any 2. The industry standard, supported by NVIDIA GPUs since 2020.",
              "<b>4:8 (ours)</b>: every group of 8 keeps <i>any</i> 4. The most freedom.",
              "<b>Paired 4:8 (NVIDIA)</b>: each group of 8 is split into 4 neighbouring pairs, and 2 whole pairs are kept. "
              "The least freedom. NVIDIA uses it only for 4-bit numbers, where two values fill exactly one byte."]),
          P("More freedom lets the pruning keep the weights that matter most. To compare the rules, the same large sets of "
            "random weights were pruned with each one, and we measured how much of the original weights survived (a "
            "standard stand-in for how much accuracy pruning costs).")]
rows2 = [["", "Paired 4:8 (NVIDIA)", "2:4", "4:8 (ours)"],
         ["Ways to choose which half to keep (per 8 weights)", "6", "36", "70"],
         ["Share of the original weights kept<br/><font size='8' color='#5a6270'>higher = closer to the unpruned model</font>",
          f"{f('bell curve','paired 4:8'):.0f}–{f('heavy tail','paired 4:8'):.0f}% (lowest)",
          f"{f('bell curve','2:4'):.0f}–{f('heavy tail','2:4'):.0f}%",
          f"<b>{f('bell curve','4:8'):.0f}–{f('heavy tail','4:8'):.0f}% (highest)</b>"],
         ["Position information per 8 weights", "least: which 2 of 4 pairs", "8 bits", "12 bits (most)"],
         ["Grid speed on Gemmini vs Berkeley", "not built", f"{g24:.2f}× (measured)", f"{g48:.2f}× (measured)"],
         ["Whole-job speed vs Berkeley, realistic case", "not built", f"<b>{e24:.2f}×</b> (measured; about even)", f"{e48:.2f}× (measured; slower)"],
         ["Best suited to", "4-bit numbers (NVIDIA Blackwell GPUs)", "8- and 16-bit numbers; widest tool support", "8-bit numbers where accuracy matters most"]]
story += [table(rows2, [2.0 * inch, (W - 2.0 * inch) / 3, (W - 2.0 * inch) / 3, (W - 2.0 * inch) / 3]),
          P("&quot;Share kept&quot; is the share of the weights' total size (sum of squares) left after pruning, for bell-curve and "
            "heavy-tailed random weights. The best possible 50% with no pattern at all keeps "
            f"{f('bell curve','no pattern'):.0f}–{f('heavy tail','no pattern'):.0f}%. It's a stand-in, not a test of a trained AI model.", "cap"),
          P("<b>Interpretation.</b> In today's design the bottleneck is sending position notes, so the pattern needing the "
            f"fewest notes does best: <b>2:4</b> comes out about even with Berkeley's original ({e24:.2f}×, or {own24:.2f}× against "
            f"our own chip's normal mode), while 4:8 is clearly slower ({e48:.2f}×). <b>Paired 4:8</b> needs even less position information, so in "
            "this design it would probably suffer least from the bottleneck. But that's a prediction (it wasn't built), and "
            "it keeps the least of the original weights. Its whole advantage, packing pairs of 4-bit numbers into a byte, "
            "doesn't apply to Gemmini's 8-bit numbers.", "box"),
          KeepTogether(P("<b>Recommendation.</b> As the chip stands, sparsity isn't worth turning on for speed. If one pattern is used, "
            "it should be <b>2:4</b>: roughly break-even, the least overhead of the two we built, and the industry standard "
            "with the best tool support. Once the chip reads its own position notes from memory, <b>4:8</b> becomes the best "
            "choice: the grid runs just as fast, it keeps the most of the original weights, and its one weakness (more position "
            "information) is exactly the cost that change removes. <b>Paired 4:8 isn't recommended</b> for Gemmini.", "box"))]

story += [CondPageBreak(2 * inch), P("Limits of these results", "h1"),
          *B(["<b>Simulation, not a physical chip.</b> Cycle counts are exact, but clock speed, power and chip area weren't measured.",
              "<b>One small job.</b> The test is sized so each simulation finishes in minutes. Real AI layers are much larger, "
              "and the balance between processor and chip could shift.",
              "<b>The test program matters.</b> How efficiently the processor's instruction loop is written changes the "
              "whole-job numbers a lot. That's why all three chips here ran the same program. An earlier version of the "
              "benchmark used a less efficient loop that slowed normal mode more than sparse mode, and showed sparse 1.36–1.44× "
              "faster. Those figures are superseded by this summary and shouldn't be cited.",
              "<b>AI accuracy wasn't measured.</b> &quot;Share kept&quot; is a stand-in. The real test is a trained model, usually "
              "retrained after pruning.",
              "<b>Paired 4:8 wasn't built.</b> Its entries describe the rule, not a measurement on Gemmini."]),
          P("Where the numbers come from", "h1"),
          P("The test program reads the chip's cycle counter just before and just after the work and prints the difference. "
            "The grid's working time comes from Gemmini's own built-in counter. All three chips ran "
            f"{M('verification/fair_perf.c')}: Berkeley's unmodified design ran it with the sparse steps left out "
            f"({M('verification/berkeley-logs/')}), and ours ran it in full ({M('verification/fair-logs/')}). "
            f"{M('verification/paper_data.py')} reads every number straight from those logs, with nothing copied by hand. "
            f"The pattern comparison comes from {M('verification/pattern_fidelity.py')}.", "small")]

def on_page(cv, doc):
    cv.saveState(); cv.setFont("Sans", 8); cv.setFillColor(MUTED)
    cv.drawString(0.95 * inch, 0.55 * inch, "Gemmini 2:4 / 4:8 sparsity · results summary · Hunter Caraway · 2026-10-06")
    cv.drawRightString(letter[0] - 0.95 * inch, 0.55 * inch, str(doc.page)); cv.restoreState()

doc = BaseDocTemplate(str(OUT), pagesize=letter, leftMargin=0.95 * inch, rightMargin=0.95 * inch, topMargin=0.8 * inch,
                      bottomMargin=0.85 * inch, title="Gemmini with 2:4 and 4:8 Sparsity: Results Summary", author="Hunter Caraway")
doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")], onPage=on_page)])
doc.build(story)
print(OUT)
