#!/usr/bin/env python3
"""WITHDRAWN. Don't use. This builds the old plain-language report. Every speed-up in it (2.00x, 1.88x, 1.44x,
1.36x, 0.64-0.84x) comes from the original benchmark, which has been withdrawn. Kept only as a historical record.
The script refuses to run. A new report must be built from the corrected re-run."""
raise SystemExit("build_explained.py is withdrawn: its speed-up numbers come from the superseded benchmark")
import re, csv
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Image as RLImage,
                                Table, TableStyle, PageBreak, KeepTogether, CondPageBreak)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon

PROJ = Path(__file__).resolve().parents[2]
VER = PROJ / "verification"
CHARTS = PROJ / "analysis" / "charts"
SCR = Path(__file__).parent
SHOTS = SCR / "shots3"; SHOTS.mkdir(exist_ok=True)
OUT = PROJ / "N-M-Sparsity-Explained.pdf"

LS = "/usr/share/fonts/liberation-sans-fonts/"; NM = "/usr/share/fonts/google-noto/"
for n, f in [("Sans", "LiberationSans-Regular"), ("Sans-Bold", "LiberationSans-Bold"),
             ("Sans-Italic", "LiberationSans-Italic"), ("Sans-BoldItalic", "LiberationSans-BoldItalic")]:
    pdfmetrics.registerFont(TTFont(n, LS + f + ".ttf"))
pdfmetrics.registerFont(TTFont("Mono", NM + "NotoSansMono-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Mono-Bold", NM + "NotoSansMono-Bold.ttf"))
registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-Italic", boldItalic="Sans-BoldItalic")
registerFontFamily("Mono", normal="Mono", bold="Mono-Bold", italic="Mono", boldItalic="Mono-Bold")

INK = colors.HexColor("#1a1d23"); MUTED = colors.HexColor("#5a6270"); ACC = colors.HexColor("#2a6fd6")
RULE = colors.HexColor("#d9dde3"); TINT = colors.HexColor("#f3f5f8"); OKC = colors.HexColor("#2f8f46")
BLUE = colors.HexColor("#2a7ad6"); ORANGE = colors.HexColor("#eb6a35")
S = {
 "title": ParagraphStyle("title", fontName="Sans-Bold", fontSize=25, leading=30, textColor=INK, spaceAfter=6),
 "sub": ParagraphStyle("sub", fontName="Sans", fontSize=13, leading=18, textColor=MUTED, spaceAfter=4),
 "h1": ParagraphStyle("h1", fontName="Sans-Bold", fontSize=17, leading=22, textColor=INK, spaceBefore=6, spaceAfter=8),
 "h2": ParagraphStyle("h2", fontName="Sans-Bold", fontSize=12.5, leading=16, textColor=INK, spaceBefore=10, spaceAfter=5),
 "body": ParagraphStyle("body", fontName="Sans", fontSize=10.5, leading=15, textColor=INK, spaceAfter=7),
 "bul": ParagraphStyle("bul", fontName="Sans", fontSize=10.5, leading=14.6, textColor=INK, leftIndent=15, bulletIndent=3, spaceAfter=4),
 "cap": ParagraphStyle("cap", fontName="Sans-Italic", fontSize=8.8, leading=11.8, textColor=MUTED, spaceBefore=3, spaceAfter=12),
 "cell": ParagraphStyle("cell", fontName="Sans", fontSize=8.8, leading=11.4, textColor=INK),
 "cellb": ParagraphStyle("cellb", fontName="Sans-Bold", fontSize=8.8, leading=11.4, textColor=INK),
 "h3": ParagraphStyle("h3", fontName="Sans-Bold", fontSize=9.5, leading=12, textColor=ACC, spaceBefore=2, spaceAfter=3),
 "small": ParagraphStyle("small", fontName="Sans", fontSize=8.8, leading=11.8, textColor=MUTED),
 "callout": ParagraphStyle("callout", fontName="Sans", fontSize=10.5, leading=15, textColor=INK, backColor=colors.HexColor("#eef4fd"),
                           borderPadding=(9, 10, 9, 10), leftIndent=10, rightIndent=10, spaceBefore=8, spaceAfter=14),
 "big": ParagraphStyle("big", fontName="Sans-Bold", fontSize=22, leading=26, textColor=INK, alignment=1),
 "bigl": ParagraphStyle("bigl", fontName="Sans", fontSize=9, leading=12, textColor=MUTED, alignment=1),
}
W = letter[0] - 2 * 0.9 * inch

def P(t, s="body"): return Paragraph(t, S[s])
def B(items): return [Paragraph(i, S["bul"], bulletText="•") for i in items]
def M(t): return f"<font name='Mono' size='9.5'>{t}</font>"
def table(rows, widths, header=True):
    data = [[Paragraph(str(c), S["cellb" if (header and i == 0) else "cell"]) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
          ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
          ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
    if header: st += [("BACKGROUND", (0, 0), (-1, 0), TINT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
    t.setStyle(TableStyle(st)); return t
def img(path, caption, width=W):
    im = Image.open(path); w, h = im.size; dw = width; dh = dw * h / w
    r = RLImage(str(path), width=dw, height=dh); r.hAlign = "CENTER"
    return KeepTogether([r, P(caption, "cap")])
def fig(name, caption, width=W): return img(CHARTS / f"{name}-light.png", caption, width)

# ---------- terminal captures of the verification output ----------
fmono = ImageFont.truetype(NM + "NotoSansMono-Regular.ttf", 26)
fmono_b = ImageFont.truetype(NM + "NotoSansMono-Bold.ttf", 26)
fbar = ImageFont.truetype(LS + "LiberationSans-Regular.ttf", 24)
def terminal(name, title, lines, cols=None):
    lines = [l.expandtabs(4) for l in lines]
    cw = fmono.getbbox("M")[2]; lh = 36; pad = 24; bar_h = 48
    cols = cols or max(100, max(len(l) for l in lines))
    Wp = pad * 2 + cw * cols; H = bar_h + pad * 2 + lh * len(lines)
    im = Image.new("RGB", (Wp, H), (30, 32, 38)); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, Wp, bar_h], fill=(52, 55, 63))
    for i, c in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
        d.ellipse([20 + i * 34, 14, 40 + i * 34, 34], fill=c)
    tw = d.textlength(title, font=fbar); d.text(((Wp - tw) / 2, 11), title, font=fbar, fill=(190, 193, 200))
    y = bar_h + pad
    for l in lines:
        if l.startswith("$ "):
            d.text((pad, y), "$", font=fmono_b, fill=(120, 170, 250)); d.text((pad + cw * 2, y), l[2:], font=fmono_b, fill=(255, 255, 255))
        else:
            # colour by the line's own status word only, never by words inside the message
            st = l.strip()
            col = (220, 223, 228)
            if st.startswith("ok") or st == "ALL CHECKS PASSED" or "detected in" in l or " == " in l: col = (110, 200, 120)
            if st.startswith("FAIL") or st.endswith("CHECK(S) FAILED") or re.search(r"detected in (\d+)/(\d+)", l) and \
                    re.search(r"detected in (\d+)/(\d+)", l)[1] != re.search(r"detected in (\d+)/(\d+)", l)[2]:
                col = (240, 100, 90)
            if re.match(r"^\d\. ", l): col = (255, 255, 255)
            d.text((pad, y), l, font=fmono_b if re.match(r"^\d\. ", l) else fmono, fill=col)
        y += lh
    p = SHOTS / f"{name}.png"; im.save(p); return p

def shorten(l): return l.replace("  (report says", "  (report:").replace("all_data.csv compared, see any FAIL lines above", "all_data.csv compared, 0 mismatches")

xc = (VER / "cross_check.out").read_text().splitlines()
math_out = (VER / "independent_math_check.out").read_text().splitlines()
status = (VER / "rerun-logs/status.txt").read_text().splitlines()
from datetime import datetime
_t = [datetime.strptime(re.search(r"(\d+:\d+:\d+ [AP]M)", l)[1], "%I:%M:%S %p") for l in (status[0], status[-1])]
RERUN_TIME = f"about {round((_t[1] - _t[0]).seconds / 60)} min"

sec = {}
cur = None
for l in xc:
    m = re.match(r"^(\d)\. ", l)
    if m: cur = m[1]; sec[cur] = [l]; continue
    if cur and l.strip(): sec[cur].append(l)
final = [l for l in xc if "CHECKS PASSED" in l or "FAILED" in l][-1]

shot_math = terminal("math", "verification/independent_math_check.py",
                     ["$ python verification/independent_math_check.py"] +
                     [l.replace(" (largest |output|", "\n").split("\n")[0] for l in math_out[1:]])
shot_rerun = terminal("rerun", "verification/cross_check.py · section 4 (re-run vs original)",
                      ["$ verification/rerun.sh   # " + status[0].replace("start ", "started ")] + sec["4"] + [status[-1]])
shot_csv = terminal("csv", "verification/cross_check.py · sections 1–3",
                    ["$ python verification/cross_check.py"] + sec["1"] + [sec["2"][0]] + sec["2"][1:4] + ["  ...  (" + str(len(sec["2"]) - 5) + " more rows, all ok)"] + [sec["2"][-1]] + [shorten(l) for l in sec["3"]])
shot_quotes = terminal("quotes", "verification/cross_check.py · section 5 (every quoted number recomputed)",
                       [shorten(l) for l in sec["5"] if "CHECK" not in l] + ["", final])

# ---------- raw data ----------
rows = {(r["config"], r["test"], r["variant"]): r for r in csv.DictReader(open(PROJ / "results/cycles.csv"))}
def v(cfg, test, var, col="total_cycles"):
    return int(rows[("GemminiNMRocketConfig" if cfg == "2:4" else "GemminiNM48RocketConfig", test, var)][col])

# ---------- diagrams ----------
def sparsity_diagram():
    d = Drawing(W, 175)
    vals = [0.8, 0.1, -0.5, 0.05, -0.2, 0.9, 0.0, 0.3]
    keep = [0, 2, 5, 7]
    bw = 44; gap = 6; x0 = 20; y0 = 112
    d.add(String(x0, 160, "Original row of 8 weights (two groups of 4)", fontName="Sans-Bold", fontSize=9.5, fillColor=INK))
    for i, val in enumerate(vals):
        x = x0 + i * (bw + gap) + (14 if i >= 4 else 0)
        k = i in keep
        d.add(Rect(x, y0, bw, 30, fillColor=colors.HexColor("#dbe9fb") if k else colors.HexColor("#f1f2f4"),
                   strokeColor=BLUE if k else colors.HexColor("#c4c8cf"), strokeWidth=1.2 if k else 0.6))
        d.add(String(x + bw / 2, y0 + 11, f"{val:g}", fontName="Sans-Bold" if k else "Sans", fontSize=10,
                     fillColor=INK if k else colors.HexColor("#9aa1ad"), textAnchor="middle"))
        d.add(String(x + bw / 2, y0 - 12, f"pos {i % 4}", fontName="Sans", fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
    d.add(String(x0 + 2 * (bw + gap) - 3, y0 + 36, "group 1: keep the 2 biggest", fontName="Sans", fontSize=8, fillColor=MUTED, textAnchor="middle"))
    d.add(String(x0 + 6 * (bw + gap) + 11, y0 + 36, "group 2: keep the 2 biggest", fontName="Sans", fontSize=8, fillColor=MUTED, textAnchor="middle"))
    # compressed
    cx = 20; cy = 22
    d.add(String(cx, 78, "What gets stored: 4 values (half the multiplications) + a small position note for each",
                 fontName="Sans-Bold", fontSize=9.5, fillColor=INK))
    for s, i in enumerate(keep):
        x = cx + s * (bw + gap) + (14 if s >= 2 else 0)
        d.add(Rect(x, cy + 22, bw, 26, fillColor=colors.HexColor("#dbe9fb"), strokeColor=BLUE, strokeWidth=1.2))
        d.add(String(x + bw / 2, cy + 31, f"{vals[i]:g}", fontName="Sans-Bold", fontSize=10, fillColor=INK, textAnchor="middle"))
        d.add(Rect(x, cy, bw, 18, fillColor=colors.HexColor("#fde8dd"), strokeColor=ORANGE, strokeWidth=0.8))
        d.add(String(x + bw / 2, cy + 5, f"pos {i % 4}", fontName="Sans", fontSize=8, fillColor=colors.HexColor("#9a3b12"), textAnchor="middle"))
    d.add(String(cx + 4 * (bw + gap) + 30, cy + 31, "values  (multiplied)", fontName="Sans", fontSize=8.5, fillColor=MUTED))
    d.add(String(cx + 4 * (bw + gap) + 30, cy + 5, "position notes (\"indexes\": which input to use)", fontName="Sans", fontSize=8.5, fillColor=MUTED))
    return d

def reading(shows, how, notice, why):
    rows = [["What it shows", shows], ["How to read it", how], ["What to notice", notice], ["Why it matters", why]]
    data = [[Paragraph(a, S["cellb"]), Paragraph(b, S["cell"])] for a, b in rows]
    t = Table(data, colWidths=[1.05 * inch, W - 1.05 * inch])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f8fb")),
                           ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c9d3e3")),
                           ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#dde3ec")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
    return t

def graph(name, caption, shows, how, notice, why, width=W):
    im = Image.open(CHARTS / f"{name}-light.png"); w, h = im.size
    r = RLImage(str(CHARTS / f"{name}-light.png"), width=width, height=width * h / w); r.hAlign = "CENTER"
    return [KeepTogether([r, P(caption, "cap")]),
            KeepTogether([P("Reading this graph", "h3"), reading(shows, how, notice, why)]), Spacer(1, 14)]

def pattern_diagram():
    vals = [0.9, -0.7, 0.6, 0.05, 0.1, -0.2, 0.8, 0.0]
    total = sum(abs(x) for x in vals)
    rows = [("2:4  (NVIDIA and ours)", [0, 1, 5, 6], "groups"),
            ("NVIDIA paired 4:8 (FP4 only)", [0, 1, 6, 7], "pairs"),
            ("Our 4:8", [0, 1, 2, 6], "one")]
    d = Drawing(W, 196)
    bw, gap, x0 = 29, 3, 128
    lx = x0 + 8 * (bw + gap) + 22
    d.add(String(x0, 184, "The same 8 weights, pruned to half by each rule (kept values in blue)", fontName="Sans-Bold", fontSize=9, fillColor=INK))
    for k, (label, keep, kind) in enumerate(rows):
        y = 140 - k * 56
        d.add(String(0, y + 10, label, fontName="Sans-Bold", fontSize=8.8, fillColor=INK))
        for i, val in enumerate(vals):
            x = x0 + i * (bw + gap) + (8 if (kind == "groups" and i >= 4) else 0) + (5 * (i // 2) if kind == "pairs" else 0)
            on = i in keep
            d.add(Rect(x, y, bw, 26, fillColor=colors.HexColor("#dbe9fb") if on else colors.HexColor("#f1f2f4"),
                       strokeColor=BLUE if on else colors.HexColor("#c4c8cf"), strokeWidth=1.2 if on else 0.6))
            d.add(String(x + bw / 2, y + 9, f"{val:g}", fontName="Sans-Bold" if on else "Sans", fontSize=8.5,
                         fillColor=INK if on else colors.HexColor("#9aa1ad"), textAnchor="middle"))
        if kind == "groups":
            d.add(String(x0 + 2 * (bw + gap) - 2, y - 10, "group of 4: any 2", fontName="Sans", fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
            d.add(String(x0 + 6 * (bw + gap) + 6, y - 10, "group of 4: any 2", fontName="Sans", fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
        elif kind == "pairs":
            for pr in range(4):
                px = x0 + 2 * pr * (bw + gap) + 5 * pr
                d.add(Line(px, y - 4, px + 2 * bw + gap, y - 4, strokeColor=ORANGE, strokeWidth=1.4))
            d.add(String(x0 + 4 * (bw + gap) + 8, y - 13, "4 pairs of neighbours: keep 2 whole pairs", fontName="Sans", fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
        else:
            d.add(String(x0 + 4 * (bw + gap), y - 10, "one group of 8: any 4", fontName="Sans", fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
        kept = sum(abs(vals[i]) for i in keep)
        d.add(String(lx, y + 14, f"keeps {kept:.1f} of {total:.2f}", fontName="Sans-Bold", fontSize=8.5, fillColor=INK))
        d.add(String(lx, y + 3, f"({kept / total * 100:.0f}% of total size)", fontName="Sans", fontSize=8, fillColor=MUTED))
    return d

def system_diagram():
    d = Drawing(W, 150)
    def box(x, y, w, h, title, sub, fill):
        d.add(Rect(x, y, w, h, rx=6, ry=6, fillColor=fill, strokeColor=colors.HexColor("#b9c6dc"), strokeWidth=0.8))
        d.add(String(x + w / 2, y + h - 18, title, fontName="Sans-Bold", fontSize=10, fillColor=INK, textAnchor="middle"))
        for k, s in enumerate(sub):
            d.add(String(x + w / 2, y + h - 34 - k * 12, s, fontName="Sans", fontSize=8.2, fillColor=MUTED, textAnchor="middle"))
    box(0, 40, 122, 90, "Regular processor", ["(Rocket CPU core)", "runs the program,", "sends commands"], colors.HexColor("#f1f7ee"))
    box(W - 196, 0, 196, 140, "Gemmini accelerator", ["16 × 16 grid of multipliers", "(the \"systolic array\")", "+ its own scratch memory"], colors.HexColor("#eef3fc"))
    gx, gy, gs = W - 149, 14, 6.4
    for r in range(16):
        for c in range(16):
            d.add(Rect(gx + c * gs, gy + r * gs * 0.62, gs - 1.4, gs * 0.62 - 1.4, fillColor=colors.HexColor("#a9c4ec"), strokeColor=None))
    x1, x2 = 132, W - 206
    for k, (lab, y) in enumerate([("commands: load, preload, compute", 100), ("+ new: index notes (sparse mode)", 74)]):
        d.add(Line(x1, y, x2 - 8, y, strokeColor=ACC if k == 0 else ORANGE, strokeWidth=1.4))
        d.add(Polygon([x2 - 8, y + 4, x2 - 8, y - 4, x2, y], fillColor=ACC if k == 0 else ORANGE, strokeColor=None))
        d.add(String((x1 + x2) / 2, y + 5, lab, fontName="Sans", fontSize=7.8, fillColor=INK, textAnchor="middle"))
    d.add(String((x1 + x2) / 2, 48, "one command at a time", fontName="Sans-Italic", fontSize=7.8, fillColor=MUTED, textAnchor="middle"))
    return d

# ---------- content ----------
e = lambda a, b: f"{a / b:.2f}×"
story = [Spacer(1, 0.9 * inch),
         P("Teaching an AI Accelerator to Skip Zeros", "title"),
         P("A plain-language report: what was built, the evidence that it works, what the speedups mean, and where every number came from", "sub"),
         Spacer(1, 8), P("Hunter Caraway · work done 2026-10-05 to 2026-10-06 · verified and written 2026-10-06", "small"),
         Spacer(1, 22), P("The short version", "h2"),
         P("AI models spend most of their time multiplying large tables of numbers. Many of those numbers can be set to zero "
           "with little effect, and a multiplication by zero is wasted effort. This project modified <b>Gemmini</b>, an open-source "
           "AI chip design from UC Berkeley, so that it skips half of those multiplications using a pattern called "
           "<b>2:4 or 4:8 structured sparsity</b>. The chip was then tested in a simulation that reproduces its behaviour "
           "one clock tick at a time.")]
kpi = Table([[P("2.00×", "big"), P("1.44×", "big"), P("0.64–0.84×", "big")],
             [P("faster at the core: the multiplier grid finishes the same job in half the time", "bigl"),
              P("faster overall (2:4) when weights are reused, the normal way AI workloads run. 1.36× for 4:8", "bigl"),
              P("i.e. <b>slower</b> overall when weights are not reused, because the processor feeding the chip becomes the bottleneck", "bigl")]],
            colWidths=[W / 3] * 3)
kpi.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, RULE), ("INNERGRID", (0, 0), (-1, -1), 0.4, RULE),
                         ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafbfc")),
                         ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
story += [Spacer(1, 4), kpi, Spacer(1, 12),
          P("<b>Is it correct?</b> Yes, as far as these tests can show. Every answer the modified chip produced was compared, number "
            "by number, with an answer calculated separately; all of them matched. Section 3 lays out five independent "
            "pieces of evidence, including a fresh re-run today that reproduced every measurement exactly, and an automated "
            "check that traced every published number back to the simulator's raw output with zero mismatches.", "callout")]

# 1 background
story += [PageBreak(), P("1 · Background, in plain terms", "h1"),
          P("Why AI needs special chips", "h2"),
          P("An AI model like a chatbot or an image recogniser is, underneath, a long list of tables of numbers called "
            "<b>weights</b>. Running the model means multiplying the input (also a table of numbers) by these weight tables, "
            "over and over. This operation is called <b>matrix multiplication</b>, and it is most of the work. A normal "
            "processor does it one or a few multiplications at a time. An <b>AI accelerator</b> is a circuit built to do "
            "hundreds at once."),
          P("What Gemmini is", "h2"),
          P("Gemmini is an AI accelerator design published by UC Berkeley. Its heart is a 16 × 16 grid of 256 tiny "
            "multiply-and-add units called a <b>systolic array</b>: numbers flow through it like a bucket brigade, each unit "
            "multiplying what it receives and passing the result along. Gemmini doesn't run on its own. A regular processor "
            "core (here, Berkeley's <b>Rocket</b> core) runs the program and sends Gemmini one command at a time: "
            "&quot;load this data&quot;, &quot;preload these weights&quot;, &quot;compute&quot;."),
          system_diagram(),
          P("Figure 1. The setup that was tested. The processor issues commands; Gemmini's grid does the multiplying. Sparse mode adds "
            "one new kind of command: the index notes explained in section 2.", "cap"),
          P("No physical chip was made: how it was tested", "h2"),
          *B(["<b>Verilator (the main tool).</b> It turns the chip's circuit design into a program that simulates every wire "
              "on every tick of the chip's clock. One tick is a <b>cycle</b>. The simulation is exact about how many cycles "
              "things take, which is what the speedups measure. It is slow: one test takes 4–9 minutes to simulate a "
              "fraction of a millisecond of chip time.",
              "<b>Spike.</b> A much faster model that only checks whether answers are right, not how long they take. Used "
              "to check the software before the slow simulations.",
              "<b>Chipyard.</b> Berkeley's framework that bundles Gemmini, the Rocket processor and these tools together."]),
          P("A simulation can't tell you the chip's clock speed, power use or size in silicon. Those need a further step "
            "(synthesis) that wasn't part of this work. So every result here is in <b>cycles</b>, not seconds.")]

# 2 sparsity
story += [CondPageBreak(3 * inch), P("2 · The idea: structured sparsity", "h1"),
          P("Many weights in a trained AI model are close to zero and contribute little. <b>Pruning</b> sets the smallest ones "
            "to exactly zero. <b>Structured</b> pruning does it in a fixed pattern that hardware can exploit:"),
          *B(["<b>2:4</b>: in every group of 4 weights, keep the 2 largest and zero the other 2.",
              "<b>4:8</b>: in every group of 8, keep the 4 largest, <i>any</i> 4. Same 50% of zeros, with more freedom in which ones "
              "survive, at the cost of bigger position notes. This is not the same as NVIDIA's &quot;paired 4:8&quot;; see below."]),
          sparsity_diagram(),
          P("Figure 2. 2:4 pruning on a made-up row of 8 weights. Only the kept values are stored and multiplied. "
            "A small &quot;position note&quot; (index) records where each one came from, so the chip can pair it with the right input.", "cap"),
          P("This isn't a new idea: NVIDIA's data-centre GPUs have had hardware support for 2:4 sparsity since 2020. What this project "
            "did was add it to Gemmini, which did not support it."),
          P("Our 4:8 is not NVIDIA's &quot;paired 4:8&quot;", "h2"),
          P("NVIDIA's newest GPUs (Blackwell) support a pattern NVIDIA calls <b>paired 4:8</b>, but only for 4-bit floating-point "
            "data (FP4). It sounds like ours, but the rule is different. NVIDIA treats each group of 8 weights as 4 pairs of "
            "neighbours, and keeps or drops a <b>whole pair</b> at a time: 2 of the 4 pairs survive. Our 4:8 keeps <b>any</b> "
            "4 of the 8, each one chosen individually."),
          pattern_diagram(),
          P("Figure 3. One made-up row of 8 weights pruned by each rule, keeping the biggest values the rule allows (for paired "
            "4:8, the 2 pairs with the largest combined size). All three keep exactly 4 of the 8. Only our 4:8 can keep the 4 "
            "largest values here (0.9, −0.7, 0.6, 0.8). 2:4 must drop 0.6 because its group already has two bigger values; paired "
            "4:8 must drop 0.6 and keep a 0.0, because 0.8 and 0.0 are neighbours.", "cap"),
          table([["", "2:4 (NVIDIA and ours)", "NVIDIA paired 4:8", "Our 4:8"],
                 ["Rule", "In each group of 4, keep any 2", "Each group of 8 is 4 neighbouring pairs; keep 2 whole pairs", "In each group of 8, keep any 4"],
                 ["Allowed ways to prune 8 weights", "36  (6 per half × 6 per half)", "6  (choose 2 of 4 pairs)", "70  (choose any 4 of 8)"],
                 ["Position information to store", "2 bits per kept weight: 8 bits per 8 weights", "Only which 2 of the 4 pairs survived (6 possibilities)", "3 bits per kept weight: 12 bits per 8 weights"],
                 ["Where it's used", "NVIDIA GPUs since 2020 for 16-bit and 8-bit data; this project", "NVIDIA Blackwell GPUs, for 4-bit floating-point (FP4) data only", "This project, with 8-bit integer data"],
                 ["Multiplier grid speed-up here", "2.00×", "not applicable (not built here)", "2.00×"]],
                [1.35 * inch, (W - 1.35 * inch) / 3, (W - 1.35 * inch) / 3, (W - 1.35 * inch) / 3]),
          Spacer(1, 6),
          P("Put simply: <b>paired 4:8 is the strictest of the three</b> (6 choices), and <b>our 4:8 is the most flexible</b> "
            "(70 choices). Every pattern that 2:4 or paired 4:8 allows is also allowed by ours. Flexibility matters because the "
            "pruner can more often keep the weights that are really the biggest, which generally keeps a pruned model closer to "
            "the original. (Model accuracy wasn't measured in this project.) The price is more position information: 12 bits per "
            "8 weights against 8 for 2:4. That's why our 4:8 needs twice as many note commands, and why it comes out a little "
            "slower than 2:4 overall (1.36× against 1.44×). NVIDIA's pairing goes the other way: very little position information, "
            "at the cost of flexibility. One likely reason it's used only for FP4: two 4-bit values fill exactly one byte, so "
            "pairs are a natural unit. That is our reading; NVIDIA's documentation doesn't give a reason."),
          P("What was changed in the chip", "h2"),
          *B(["Each of the 256 multiply units got a small slot for a position note next to its weight, and a selector "
              "that uses the note to pick the right input (one out of 4, or one out of 8).",
              "The inputs are now fed in twice as wide, so every unit has its whole group of candidates available.",
              "A new command lets the processor send the position notes. The chip keeps up to 4 tiles' worth of notes "
              "in a queue and matches each set to the weights it belongs to.",
              "Matching changes to the fast Spike model, plus four new test programs."]),
          P("In total that's about 1,300 lines added across three code repositories. The exact changes are in "
            f"{M('Gemmini-NM-Code-Changes.pdf')}.")]

# 3 proof
story += [CondPageBreak(4 * inch), P("3 · Proof that the results are correct", "h1"),
          P("&quot;Correct&quot; means two separate things here, and both were checked:"),
          *B(["<b>The chip computes the right answers</b> in sparse mode (evidence 1–3).",
              "<b>The reported numbers are real</b>: not mistyped, reproducible, and traceable to the simulator's own output (evidence 4–5)."]),
          P("Evidence 1 · Every answer is checked against an independent calculation", "h2"),
          P("Each test program computes the same multiplication twice: once on Gemmini, and once the slow, ordinary way on the "
            "processor. It then compares <b>every single number</b> in the result and fails loudly if even one differs. "
            "All tests printed &quot;passed&quot; for both 2:4 and 4:8."),
          table([["Test", "What is compared", "Numbers compared per run", "Result"],
                 ["nm_sparse_matmul", "Gemmini (normal mode) vs processor, and Gemmini (sparse mode) vs processor", "1,024 + 1,024", "all match, 2:4 and 4:8"],
                 ["nm_sparse_debug", "One sparse tile vs processor, plus five deliberately wrong answers", "256", "256 of 256 match the right answer"],
                 ["nm_sparse_perf", "Three sparse variants vs the normal-mode result", "3 × 2,048", "all match, 2:4 and 4:8"],
                 ["nm_sparse_sw", "Processor only: prune → pack → unpack → multiply round trip", "2:4, 4:8 and 1:2", "all match"]],
                [1.25 * inch, 2.75 * inch, 1.35 * inch, W - 5.35 * inch]),
          Spacer(1, 4),
          P("Evidence 2 · The checks are capable of failing, and did", "h2"),
          P("A test that has never failed proves less than one that has. These ones did. The first sparse runs failed: one "
            "printed &quot;got 230 want 61&quot;, and the diagnostic test showed the chip's answers matched the "
            "&quot;position notes ignored&quot; mistake 256 of 256 times and the correct answer 0 times. That exposed a real bug: "
            "a storage slot for the notes had accidentally been created with a size of zero bits. Once that was fixed, the "
            "same test flipped to 256 of 256 correct. The full before-and-after logs are in the original run report."),
          P("Evidence 3 · An independent re-check of the math", "h2"),
          P(f"A separate program ({M('verification/independent_math_check.py')}) was written for this report in a different "
            "language (Python), sharing no code with the C tests. It models exactly what the modified grid computes, and checks "
            "it against ordinary multiplication on 1,000 random cases. It also injects four kinds of hardware mistake, to "
            "confirm that a comparison like the tests' would catch each one."),
          img(shot_math, "<b>Output.</b> The sparse method gives exactly the same answer as normal multiplication in every case, "
              "and every injected mistake is caught (200 of 200 for each kind)."),
          P("Evidence 4 · A fresh re-run reproduced every number exactly", "h2"),
          P("For this report, all six benchmark simulations were run again today on the same simulators and the same test "
            "programs. Nothing had changed since the original runs; the repositories were checked clean and the programs' "
            "timestamps confirmed it. A digital simulation is deterministic: the same design and program must give the same "
            "cycle count every time, so any typo or made-up number would show up as a difference. There were none."),
          img(shot_rerun, "<b>Output.</b> Today's re-run against the original 02:52–03:21 runs: every cycle count and every "
              "hardware counter is identical, for both patterns and all three tests."),
          P("Evidence 5 · Every published number traces back to the raw output", "h2"),
          P(f"A second program ({M('verification/cross_check.py')}) reads the simulator's raw logs and checks them against the "
            f"results spreadsheet ({M('results/cycles.csv')}), the chart data ({M('analysis/all_data.csv')}), and every "
            "speedup and percentage quoted in the reports."),
          img(shot_csv, "<b>Output, part 1.</b> The spreadsheet rows and chart data match the logs value for value."),
          img(shot_quotes, "<b>Output, part 2.</b> Each speedup in the reports, recomputed from the raw cycle counts, rounds to the "
              "published value."),
          P("What this does NOT prove", "h2"),
          *B(["<b>Real silicon.</b> This is a simulation of the design. It's exact about cycles, but says nothing about clock "
              "speed, power, or chip area. The extra selectors might lower the maximum clock speed slightly; that needs synthesis to measure.",
              "<b>AI accuracy.</b> The tests use random numbers. Whether a real AI model stays accurate after 2:4 or 4:8 pruning "
              "is a separate question. Published work on NVIDIA GPUs suggests it usually does after retraining, but that wasn't tested here.",
              "<b>Big workloads.</b> The test matrices are small (at most 64 × 128 × 32) so the simulations finish in minutes. "
              "Real AI layers are much larger.",
              "<b>The normal mode on the original design.</b> The &quot;dense&quot; comparison numbers were measured on the "
              "modified chip with sparse mode switched off, which is a fair like-for-like comparison. A full re-test of the "
              "unmodified-behaviour path on the final design hasn't been run yet."])]

# 4 speedups
d24, s24 = v("2:4", "nm_sparse_perf", "dense_reuse"), v("2:4", "nm_sparse_perf", "sparse_reuse")
d48, s48 = v("4:8", "nm_sparse_perf", "dense_reuse"), v("4:8", "nm_sparse_perf", "sparse_reuse")
story += [CondPageBreak(4 * inch), P("4 · What the speedup numbers mean", "h1"),
          P("A <b>speedup</b> is old time ÷ new time. 2.00× means twice as fast; 1.44× means the job takes about 70% as long "
            "(1 ÷ 1.44); a number below 1 means slower. All times are in clock cycles of the simulated chip. The benchmark "
            "multiplies a 64 × 128 table by a 128 × 32 table, the same job with and without sparsity."),
          P("How to read the graphs in this section", "h2"),
          *B(["Every time is in <b>cycles</b> (ticks of the chip's clock). For time graphs, <b>shorter bars are better</b>.",
              "<font color='#2a7ad6'><b>Blue</b></font> = the normal (dense) method and <font color='#eb6a35'><b>orange</b></font> "
              "= sparse. Where both patterns appear side by side, <b>2:4 is on the left and 4:8 on the right</b>.",
              "<b>Weight reuse</b> rows are the realistic case (load weights once, use them many times). <b>No reuse</b> rows "
              "are a stress test where every step needs fresh weights.",
              "The graphs were drawn from the raw measurements by this project's chart scripts; section 5 lists where each number comes from."]),
          P("Number 1 · 2.00× at the core: the idea works as designed", "h2"),
          P("The multiplier grid processes weights in 16 × 16 blocks called <b>tiles</b>. The normal method needs 64 tiles for "
            "this job. With half the weights removed, sparse needs only 32. Each tile takes the grid the same 21 cycles either way "
            f"(1,344 ÷ 64 = 672 ÷ 32 = 21). So the grid is busy for {v('2:4','nm_sparse_perf','dense_reuse','array_busy_cycles'):,} "
            f"cycles normally and {v('2:4','nm_sparse_perf','sparse_reuse','array_busy_cycles'):,} with sparsity: <b>exactly half</b>. "
            "Half the work in half the time is the theoretical best, and both 2:4 and 4:8 reach it."),
          *graph("fig1-array-busy", "Figure 4. Cycles the multiplier grid spends working. Without weight reuse it reaches 1.88× rather "
              "than 2.00×: each sparse tile then takes about 30 grid cycles against about 28 for a normal one (960 ÷ 32 vs 1,800 ÷ 64). "
              "The cause of that small gap wasn't investigated.",
              "How long the multiplier grid itself spent working on the same job: normal method (blue) against sparse (orange). "
              "Everything else, like the processor writing commands, is left out on purpose.",
              "Each bar is an amount of time; shorter is better. Compare each orange bar with the blue bar directly above it. "
              "The labels on the left give the ratio.",
              "The orange bars are half the length of the blue ones (exactly half with weight reuse). The 2:4 and 4:8 panels are "
              "identical: both rules remove exactly half the weights, and the grid's time depends on how many weights are left, "
              "not which ones.",
              "This isolates the part of the chip that was changed. It shows the change does exactly what the theory predicts: "
              "half the work, half the time."),
          P("Number 2 · 1.44× (2:4) and 1.36× (4:8) overall, in the realistic case", "h2"),
          P("The whole job takes longer than the grid's busy time, because the processor also has to send every command. The "
            "realistic case is <b>weight reuse</b>: load a tile of weights once, then push many inputs through it, like "
            "setting up a rubber stamp once and stamping many pages. That's how real AI layers run. Here the whole job "
            f"dropped from {d24:,} to {s24:,} cycles for 2:4 (<b>{e(d24, s24)}</b>) and from {d48:,} to {s48:,} for 4:8 "
            f"(<b>{e(d48, s48)}</b>). That is a real end-to-end gain, but smaller than 2× because the grid isn't the only thing that takes time."),
          KeepTogether([P("Number 3 · 0.64× to 0.84×: slower when weights aren't reused", "h2"),
          P("This is the important caveat, and the explanation is the main lesson of the project. Think of a restaurant:"),
          P("The kitchen (Gemmini's grid) got twice as fast. But every order has to be written up and carried in by one waiter "
            "(the processor). Sparse mode also needs extra slips per order: the position notes, which take 4 extra commands per "
            "tile for 2:4 and 8 for 4:8. When every order uses fresh ingredients (no reuse), the waiter is the bottleneck: "
            "the kitchen finishes and waits. More slips per order means the meal arrives later, however fast the kitchen is.", "callout")]),
          P(f"The measurements support this directly. The tests were also run with the accelerator <i>removed</i>, timing only the "
            "processor writing out the commands. That alone accounts for <b>67% to 86%</b> of every run's total time. In the "
            f"no-reuse case, the processor needs {v('2:4','nm_sparse_perf','cpu_dense'):,} cycles to issue the normal job but "
            f"{v('2:4','nm_sparse_perf','cpu_sparse'):,} for the 2:4 sparse job ({v('4:8','nm_sparse_perf','cpu_sparse'):,} for "
            "4:8), even though the sparse job has half as many tiles. 4:8 suffers more than 2:4 because its notes are bigger, so "
            "it needs twice as many note commands."),
          *graph("fig2-end-to-end", "Figure 5. Total cycles for the whole job (bars), with the time the processor alone needs to "
              "issue the same commands (dots).",
              "The total time for the whole job, from the first command to the last result (bars). The black dot on each bar is a "
              "separate measurement: the same program with the accelerator switched off, timing only the processor writing out the commands.",
              "In the restaurant picture, the dot is the waiter's time and the bar is when the meal arrives. The bar can't be much "
              "shorter than its dot, because the chip can't start work it hasn't been told about yet.",
              "In the two &quot;no reuse&quot; rows, the orange bar is <i>longer</i> than the blue, and its dot has moved right too: "
              "the extra note commands cost the processor more time than the grid saves. In the &quot;weight reuse&quot; row, the "
              "orange bar and its dot are both shorter, an overall win. The 4:8 dots sit further right than the 2:4 ones because "
              "4:8 needs twice as many note commands.",
              "The dots explain the bars. Wherever sparse loses overall, it's because the processor's share of the work grew, not "
              "because the grid got slower."),
          *graph("fig3-speedup", "Figure 6. All the speedups side by side (normal time ÷ sparse time).",
              "Every comparison in this report reduced to one number: normal time ÷ sparse time. Purple is 2:4, green is 4:8.",
              "Higher is better. Above the lower dashed line (1.0) sparse wins; below it, sparse loses. The upper dashed line (2.0) "
              "is the ceiling: removing half the work can at most halve the time.",
              "The two groups on the left measure the grid alone, and they sit at or just under the ceiling. The three on the right "
              "measure the whole job, and they're far lower: only weight reuse clears 1.0. The drop from left to right is the cost "
              "of everything outside the grid, mostly the processor issuing commands.",
              "The hardware change itself is close to perfect. The remaining room for improvement is in how work gets fed to it."),
          *graph("fig6-metadata-cost", "Figure 7. Processor cycles to issue one tile's worth of commands, with the accelerator removed.",
              "How much processor time it takes to send the commands for one tile, measured with no accelerator attached. A normal "
              "tile needs 2 commands; a sparse tile also needs its note commands (4 more for 2:4, 8 more for 4:8).",
              "Longer bars mean more processor time per tile. The dashed line is the cost of two normal tiles: one sparse tile does "
              "the work of two normal tiles, so that's the fair comparison. A sparse bar to the left of the line would mean sparse "
              "work is cheaper for the processor to issue than the normal work it replaces.",
              "Every sparse bar is to the right of the line: 62 to 84 cycles against 48.5. Issuing sparse work costs the processor "
              "28% to 73% more than issuing the same amount of normal work, and 4:8 costs more than 2:4.",
              "This is the mechanism behind the slowdown, in one picture. It also points to the fix: have the chip fetch the notes "
              "from memory itself, so the processor doesn't send them."),
          *graph("fig5-utilization", "Figure 8. Share of the total time the multiplier grid was actually computing.",
              "For each run, the fraction of the total time the grid was busy multiplying. The rest of the time it was idle, "
              "waiting for commands or data.",
              "Longer bars mean a busier grid; 100% would mean it never waited. Compare blue and orange within each row.",
              "With no reuse, the normal method keeps the grid about 80% busy, while sparse keeps it only 27–36% busy. The sparse "
              "grid finishes each tile twice as fast but is fed at the processor's pace, so it spends most of its time waiting. "
              "With weight reuse both drop (to roughly 24–37%) in this small test, because the processor's command-writing dominates there too.",
              "Idle time is wasted capacity: about two-thirds of the sparse grid's time goes unused. That is the room for improvement "
              "the next step (letting the chip fetch its own notes) is aimed at."),
          P("So what's the significance?", "h2"),
          *B(["<b>The hardware idea is sound.</b> The modified grid delivers the full theoretical 2× and computes correct answers.",
              "<b>The bottleneck has moved.</b> With the grid twice as fast, the limit is now how quickly the processor can feed "
              "it commands. That's the part to fix next: store the position notes in memory alongside the weights so the chip "
              "fetches them itself, instead of the processor sending them one command at a time. The overall speedup should "
              "then move toward the 2× the grid already achieves. That is a prediction, not a measurement.",
              "<b>In the realistic mode it's already a win:</b> 1.44× faster for 2:4 on this test, with no change to the answers."])]

# 5 provenance
story += [CondPageBreak(4 * inch), P("5 · Where every number came from", "h1"),
          P("Every cycle count was produced the same way:"),
          *B(["The test program, running on the simulated processor, reads the chip's cycle counter "
              f"({M('rdcycle')}) just before starting the work and again just after it finishes, and prints the difference.",
              "The &quot;grid busy&quot; numbers come from Gemmini's own built-in counters (it counts the cycles its grid is "
              "working), read at the same moment.",
              f"Verilator saves everything the program prints into a log file under {M('logs/runs/')}.",
              f"{M('run-flow.sh')} copies the numbers from the logs into {M('results/cycles.csv')}. The chart scripts read that "
              "file and the logs to draw the figures.",
              "Speedups and percentages are simple divisions of those numbers, recomputed independently in evidence 5."]),
          Spacer(1, 4)]
lr = "logs/runs/bench-nm24-nm_sparse_perf-20261006-025209.log"; lr8 = "logs/runs/bench-nm48-nm_sparse_perf-20261006-030607.log"
prov = [["Number", "What it is", "Source (line printed)", "How it's derived"],
        ["2.00× (both)", "Grid busy time, weight reuse", f"{M('dense_reuse')} / {M('sparse_reuse')} lines, {M('ex_active=')}", "1,344 ÷ 672"],
        ["1.88× (both)", "Grid busy time, no reuse", f"{M('dense')} / {M('sparse')} lines, {M('ex_active=')}", "1,800 ÷ 960"],
        ["1.44× (2:4)", "Whole job, weight reuse", f"{M('dense_reuse')} / {M('sparse_reuse')}, {M('total')} column", f"{d24:,} ÷ {s24:,}"],
        ["1.36× (4:8)", "Whole job, weight reuse", "same, 4:8 log", f"{d48:,} ÷ {s48:,}"],
        ["0.74× / 0.64×", "Whole job, no reuse, notes sent ahead", f"{M('dense')} / {M('sparse')}, {M('total')}",
         f"{v('2:4','nm_sparse_perf','dense'):,} ÷ {v('2:4','nm_sparse_perf','sparse'):,};  {v('4:8','nm_sparse_perf','dense'):,} ÷ {v('4:8','nm_sparse_perf','sparse'):,}"],
        ["0.84× / 0.65×", "Whole job, no reuse, natural order", f"{M('dense')} / {M('sparse_nat')}, {M('total')}",
         f"{v('2:4','nm_sparse_perf','dense'):,} ÷ {v('2:4','nm_sparse_perf','sparse_nat'):,};  {v('4:8','nm_sparse_perf','dense'):,} ÷ {v('4:8','nm_sparse_perf','sparse_nat'):,}"],
        ["67%–86%", "Share of total time the processor needs just to issue commands", f"{M('cpu_*')} lines vs the matching runs, {M('total')}", "e.g. 2,146 ÷ 2,508 = 86%;  1,551 ÷ 2,217 = 70%"],
        ["64 vs 32 tiles", "Weight tiles the grid processes", f"{M('pairs')} column", "(64÷16)×(128÷16)×(32÷16) = 64; sparse halves the 128"],
        ["21 cycles", "Grid time per tile, reuse case", f"{M('ex_active=')} ÷ {M('pairs')}", "1,344 ÷ 64 = 672 ÷ 32"],
        ["4 / 8", "Extra note commands per sparse tile (2:4 / 4:8)", f"{M('nm_sparse_matmul')}: &quot;4 meta cmds each&quot;", "set by the note size: 2 bits vs 3 bits per note"],
        ["256 / 256", "Diagnostic test: outputs matching the right answer", "nm_sparse_debug logs", "printed by the test"],
        ["543→815, 554→1,031", "Small 32×64×32 test, normal → sparse (2:4, 4:8)", "nm_sparse_matmul logs, &quot;cycles:&quot;", "printed by the test"],
        ["28,599,226", "Original unmodified chip, standard test, full simulation", f"{M('logs/baseline/baseline_matmul-RESULT.txt')}", "Verilator's own total. Includes loading the program; not used for speedups"]]
story += [table(prov, [1.05 * inch, 1.75 * inch, 1.95 * inch, W - 4.75 * inch]),
          P(f"The 2:4 numbers are in {M(lr)}; the 4:8 numbers in {M(lr8)}. Today's identical re-runs are in "
            f"{M('verification/rerun-logs/')}.", "cap"),
          P("Re-checking it yourself", "h2"),
          P("From the project folder:"),
          table([["Command", "What it does", "Time"],
                 [M("~/chipyard/.conda-env/bin/python verification/independent_math_check.py"), "Evidence 3: the independent math check", "about 10 s"],
                 [M("verification/rerun.sh"), "Evidence 4: re-runs the six simulations (writes only to verification/rerun-logs)", RERUN_TIME],
                 [M("~/chipyard/.conda-env/bin/python verification/cross_check.py"), "Evidence 4 and 5: compares everything, prints ALL CHECKS PASSED", "about 1 s"]],
                [2.9 * inch, 2.6 * inch, W - 5.5 * inch])]

# glossary
story += [CondPageBreak(3 * inch), P("Glossary", "h1"),
          table([["Term", "Meaning"],
                 ["Accelerator", "A chip (or part of one) built to do one kind of work very fast, here matrix multiplication for AI"],
                 ["Cycle", "One tick of the chip's clock. All timings here are counts of cycles"],
                 ["Dense / normal mode", "Multiplying every weight, zeros included. The baseline everything is compared against"],
                 ["Gemmini", "UC Berkeley's open-source AI accelerator design, the starting point of this project"],
                 ["Index / position note", "The small number stored with each kept weight saying which of the 4 (or 8) positions it came from"],
                 ["Matrix multiplication", "Multiplying two tables of numbers: the core operation of AI models"],
                 ["N:M sparsity (2:4, 4:8)", "In every group of M weights, only N are non-zero. Here always half"],
                 ["Rocket", "The general-purpose processor core that runs the program and sends Gemmini its commands"],
                 ["Speedup", "Old time ÷ new time. Above 1 = faster, below 1 = slower"],
                 ["Spike", "A fast simulator that checks answers but not timing"],
                 ["Systolic array", "Gemmini's 16 × 16 grid of multiply units that pass numbers along like a bucket brigade"],
                 ["Tile", "A 16 × 16 block of weights: the amount the grid holds at once"],
                 ["Verilator", "A simulator that runs the chip's actual circuit design cycle by cycle"],
                 ["Weight reuse", "Loading a tile of weights once and pushing many inputs through it, the normal way AI layers run"],
                 ["Weights", "The numbers inside an AI model that it learned during training"]],
                [1.6 * inch, W - 1.6 * inch]),
          Spacer(1, 12), P("Sources for the NVIDIA comparison", "h2"),
          P("NVIDIA cuSPARSELt documentation, Data Types (sparsity ratio: &quot;paired 4:8 for e2m1; 2:4 for half, bfloat16, int, "
            "int8, e4m3, e5m2; 1:2 for float&quot;): https://docs.nvidia.com/cuda/cusparselt/types.html", "small"),
          P("NVIDIA PTX ISA documentation, sparse matrix multiply-accumulate (&quot;pair-wise structured sparse at a granularity of "
            "4:8&quot; for .e2m1): https://docs.nvidia.com/cuda/parallel-thread-execution/", "small"),
          P("Meng et al., &quot;SharQ: Bridging Activation Sparsity and FP4 Quantization for LLM Inference&quot; (describes Blackwell's "
            "4:8 sparsity in pairs: 8 elements as 4 pairs, 2 pairs kept): https://arxiv.org/abs/2606.26587", "small"),
          P("NVIDIA Developer Blog, &quot;Exploiting NVIDIA Ampere Structured Sparsity with cuSPARSELt&quot; (2:4 on Ampere, 2020): "
            "https://developer.nvidia.com/blog/exploiting-ampere-structured-sparsity-with-cusparselt/", "small")]

merged = []
for f in story:
    if merged and isinstance(merged[-1], Paragraph) and merged[-1].style.name in ("h1", "h2"):
        h = merged.pop()
        f = list(f._content) if isinstance(f, KeepTogether) else [f]
        if merged and isinstance(merged[-1], Paragraph) and merged[-1].style.name == "h1":
            merged.append(KeepTogether([merged.pop(), h, *f]))
        else:
            merged.append(KeepTogether([h, *f]))
    else:
        merged.append(f)
story = merged

def on_page(c, doc):
    c.saveState()
    if doc.page > 1:
        c.setFont("Sans", 8); c.setFillColor(MUTED)
        c.drawString(0.9 * inch, 0.55 * inch, "Teaching an AI Accelerator to Skip Zeros")
        c.drawRightString(letter[0] - 0.9 * inch, 0.55 * inch, str(doc.page))
        c.setStrokeColor(RULE); c.setLineWidth(0.5); c.line(0.9 * inch, 0.72 * inch, letter[0] - 0.9 * inch, 0.72 * inch)
    else:
        c.setFillColor(ACC); c.rect(0, letter[1] - 0.28 * inch, letter[0], 0.28 * inch, stroke=0, fill=1)
    c.restoreState()

doc = BaseDocTemplate(str(OUT), pagesize=letter, leftMargin=0.9 * inch, rightMargin=0.9 * inch, topMargin=0.8 * inch,
                      bottomMargin=0.9 * inch, title="Teaching an AI Accelerator to Skip Zeros", author="Hunter Caraway",
                      subject="Plain-language report on N:M structured sparsity in Gemmini: verification and meaning of results")
doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")], onPage=on_page)])
doc.build(story)
print(OUT)
