#!/usr/bin/env python3
"""Builds a PDF documenting every code change on the sparse-nm branches against upstream Gemmini."""
import os, re, subprocess
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily, stringWidth
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, KeepTogether, CondPageBreak, Preformatted)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon

PROJ = Path(__file__).resolve().parents[2]
OUT = PROJ / "Gemmini-NM-Code-Changes.pdf"
GEM = Path(os.environ.get("CHIPYARD_DIR", Path.home() / "chipyard")) / "generators" / "gemmini"
LIB = GEM / "software/libgemmini"
TST = GEM / "software/gemmini-rocc-tests"
BASE = {"gem": "8c3f9923", "lib": "ea8f7ed", "tst": "7c540b3"}

def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout

# ---------- fonts / styles ----------
LS = "/usr/share/fonts/liberation-sans-fonts/"; NM = "/usr/share/fonts/google-noto/"
for n, f in [("Sans", "LiberationSans-Regular"), ("Sans-Bold", "LiberationSans-Bold"),
             ("Sans-Italic", "LiberationSans-Italic"), ("Sans-BoldItalic", "LiberationSans-BoldItalic")]:
    pdfmetrics.registerFont(TTFont(n, LS + f + ".ttf"))
pdfmetrics.registerFont(TTFont("Mono", NM + "NotoSansMono-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Mono-Bold", NM + "NotoSansMono-Bold.ttf"))
registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-Italic", boldItalic="Sans-BoldItalic")
registerFontFamily("Mono", normal="Mono", bold="Mono-Bold", italic="Mono", boldItalic="Mono-Bold")

INK = colors.HexColor("#1a1d23"); MUTED = colors.HexColor("#5a6270"); ACC = colors.HexColor("#2a6fd6")
RULE = colors.HexColor("#d9dde3"); TINT = colors.HexColor("#f3f5f8")
ADD_BG = colors.HexColor("#e6f4ea"); ADD_FG = colors.HexColor("#1e6b34")
DEL_BG = colors.HexColor("#fbe9e7"); DEL_FG = colors.HexColor("#a3321f")
HUNK_BG = colors.HexColor("#e8effa"); HUNK_FG = colors.HexColor("#2a5db0")
S = {
 "title": ParagraphStyle("title", fontName="Sans-Bold", fontSize=26, leading=31, textColor=INK, spaceAfter=6),
 "sub": ParagraphStyle("sub", fontName="Sans", fontSize=13, leading=18, textColor=MUTED, spaceAfter=4),
 "h1": ParagraphStyle("h1", fontName="Sans-Bold", fontSize=17, leading=22, textColor=INK, spaceBefore=6, spaceAfter=8),
 "h2": ParagraphStyle("h2", fontName="Sans-Bold", fontSize=12.5, leading=16, textColor=INK, spaceBefore=12, spaceAfter=4),
 "file": ParagraphStyle("file", fontName="Mono-Bold", fontSize=10.5, leading=14, textColor=INK, spaceBefore=14, spaceAfter=3),
 "body": ParagraphStyle("body", fontName="Sans", fontSize=10, leading=14.2, textColor=INK, spaceAfter=6),
 "bul": ParagraphStyle("bul", fontName="Sans", fontSize=10, leading=14, textColor=INK, leftIndent=14, bulletIndent=3, spaceAfter=3),
 "cap": ParagraphStyle("cap", fontName="Sans-Italic", fontSize=8.6, leading=11.5, textColor=MUTED, spaceBefore=3, spaceAfter=12),
 "cell": ParagraphStyle("cell", fontName="Sans", fontSize=8.6, leading=11, textColor=INK),
 "cellb": ParagraphStyle("cellb", fontName="Sans-Bold", fontSize=8.6, leading=11, textColor=INK),
 "code": ParagraphStyle("code", fontName="Mono", fontSize=8, leading=10.6, textColor=INK, backColor=TINT,
                        borderPadding=(6, 7, 6, 7), leftIndent=7, rightIndent=7, spaceBefore=4, spaceAfter=10),
 "small": ParagraphStyle("small", fontName="Sans", fontSize=8.6, leading=11.5, textColor=MUTED),
}
W = letter[0] - 2 * 0.8 * inch

def P(t, s="body"): return Paragraph(t, S[s])
def B(items): return [Paragraph(i, S["bul"], bulletText="•") for i in items]
def M(t): return f"<font name='Mono'>{t}</font>"
def code(t): return Preformatted(t, S["code"])
def table(rows, widths, header=True):
    data = [[Paragraph(str(c), S["cellb" if (header and i == 0) else "cell"]) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
          ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
          ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
    if header: st += [("BACKGROUND", (0, 0), (-1, 0), TINT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
    t.setStyle(TableStyle(st)); return t

# ---------- diff rendering ----------
CODE_FS = 7.2
NUMW = 0.36 * inch
TXTW = W - 2 * NUMW
CHARW = stringWidth("M", "Mono", CODE_FS)
MAXC = int((TXTW - 8) / CHARW)

def wrap(s):
    s = s.expandtabs(4)
    if len(s) <= MAXC: return [s]
    out = [s[:MAXC]]; s = s[MAXC:]
    while s:
        out.append("  ↪ " + s[:MAXC - 4]); s = s[MAXC - 4:]
    return out

def code_table(rows):
    """rows: list of (old_no, new_no, kind, text); kind in ' +-@'"""
    data, st = [], [("FONTNAME", (0, 0), (-1, -1), "Mono"), ("FONTSIZE", (0, 0), (-1, -1), CODE_FS),
                    ("LEADING", (0, 0), (-1, -1), CODE_FS * 1.3),
                    ("TOPPADDING", (0, 0), (-1, -1), 0.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TEXTCOLOR", (0, 0), (1, -1), colors.HexColor("#9aa1ad")), ("ALIGN", (0, 0), (1, -1), "RIGHT"),
                    ("TEXTCOLOR", (2, 0), (2, -1), INK),
                    ("BOX", (0, 0), (-1, -1), 0.5, RULE), ("LINEAFTER", (1, 0), (1, -1), 0.5, RULE)]
    for o, n, kind, text in rows:
        for k, seg in enumerate(wrap(text)):
            i = len(data)
            data.append([str(o) if (o and k == 0) else "", str(n) if (n and k == 0) else "",
                         (kind if k == 0 else " ") + seg if kind != "@" else seg])
            if kind == "+": st += [("BACKGROUND", (0, i), (-1, i), ADD_BG), ("TEXTCOLOR", (2, i), (2, i), ADD_FG)]
            elif kind == "-": st += [("BACKGROUND", (0, i), (-1, i), DEL_BG), ("TEXTCOLOR", (2, i), (2, i), DEL_FG)]
            elif kind == "@": st += [("BACKGROUND", (0, i), (-1, i), HUNK_BG), ("TEXTCOLOR", (2, i), (2, i), HUNK_FG)]
    t = Table(data, colWidths=[NUMW, NUMW, TXTW], repeatRows=0, splitByRow=1)
    t.setStyle(TableStyle(st)); t.hAlign = "LEFT"
    return t

def parse_diff(text):
    """-> {path: [(old, new, kind, line)]}"""
    files, cur, o, n = {}, None, 0, 0
    for l in text.splitlines():
        if l.startswith("diff --git"):
            cur = l.split(" b/", 1)[1]; files[cur] = []; continue
        if cur is None or l.startswith(("index ", "--- ", "+++ ", "new file", "deleted file")): continue
        m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", l)
        if m:
            o, n = int(m[1]), int(m[2]); files[cur].append(("", "", "@", l)); continue
        if l.startswith("+"): files[cur].append(("", n, "+", l[1:])); n += 1
        elif l.startswith("-"): files[cur].append((o, "", "-", l[1:])); o += 1
        elif l.startswith("\\"): continue
        else: files[cur].append((o, n, " ", l[1:])); o += 1; n += 1
    return files

def listing(path):
    return [("", i + 1, " ", l) for i, l in enumerate(Path(path).read_text().splitlines())]

def numstat(repo, base, opts=(), paths=()):
    out = {}
    for l in git(repo, "diff", "--numstat", *opts, base, "HEAD", "--", *paths).splitlines():
        a, d, p = l.split("\t"); out[p] = (int(a), int(d))
    return out

gem_diff = parse_diff(git(GEM, "diff", BASE["gem"], "HEAD", "--", "src", "chipyard"))
lib_diff_w = parse_diff(git(LIB, "diff", "-w", BASE["lib"], "HEAD"))
tst_diff = parse_diff(git(TST, "diff", BASE["tst"], "HEAD", "--", "bareMetalC/Makefile"))
gem_ns = numstat(GEM, BASE["gem"], paths=("src", "chipyard"))
lib_ns = numstat(LIB, BASE["lib"]); lib_ns_w = numstat(LIB, BASE["lib"], opts=("-w",))
tst_ns = numstat(TST, BASE["tst"])

def commits(repo, base):
    out = []
    for blk in git(repo, "log", "--reverse", "--format=%h%x1f%ad%x1f%s%x1f%b%x1e", "--date=format:%Y-%m-%d %H:%M", f"{base}..HEAD").split("\x1e"):
        blk = blk.strip()
        if not blk: continue
        h, d, s, b = blk.split("\x1f")
        b = " ".join(l for l in b.splitlines() if not l.startswith("Co-Authored-By")).strip()
        out.append((h, d, s, b))
    return out

# ---------- diagram ----------
def datapath():
    d = Drawing(W, 330)
    bw, bh = W * 0.62, 38; x0 = (W - bw) / 2
    boxes = [
        ("Software · gemmini_nm.h", "config_ex rs1[10]=1 · nm_send_meta → RoCC funct 26 · preload · compute(a_lo, a_hi)"),
        ("Controller.scala", "funct 26 (NM_META_CMD) bypasses the reservation station → ex_controller.nm_meta_in"),
        ("ExecuteController.scala", "assemble DIM×DIM index tile → 4-deep FIFO · real sparse preload pops one tile, stalls if empty"),
        ("MeshWithDelays.scala", "2·DIM activation row = A port (low) + B/bias port (high) → each row gets its group of M"),
        ("Mesh.scala · Tile.scala", "index travels down each column alongside the preloaded weight (same timing as d)"),
        ("PE.scala", "index regs m1/m2 beside weight regs c1/c2 · M:1 mux picks the activation for this weight"),
    ]
    gap = (330 - len(boxes) * bh) / len(boxes)
    for i, (t, sub) in enumerate(boxes):
        y = 330 - (i + 1) * bh - i * gap
        fill = colors.HexColor("#eef3fc") if i else colors.HexColor("#f1f7ee")
        d.add(Rect(x0 - 70, y, bw + 140, bh, rx=5, ry=5, fillColor=fill, strokeColor=colors.HexColor("#b9c6dc"), strokeWidth=0.8))
        d.add(String(x0 - 60, y + bh - 14, t, fontName="Sans-Bold", fontSize=9.5, fillColor=INK))
        d.add(String(x0 - 60, y + 8, sub, fontName="Sans", fontSize=8, fillColor=MUTED))
        if i < len(boxes) - 1:
            cx = W / 2; y1 = y; y2 = y - gap
            d.add(Line(cx, y1, cx, y2 + 4, strokeColor=ACC, strokeWidth=1.2))
            d.add(Polygon([cx - 4, y2 + 5, cx + 4, y2 + 5, cx, y2], fillColor=ACC, strokeColor=ACC))
    return d

# ---------- content ----------
story = []
g_add = sum(a for a, _ in gem_ns.values()); g_del = sum(d for _, d in gem_ns.values())
l_add = sum(a for a, _ in lib_ns.values()); l_del = sum(d for _, d in lib_ns.values())
lw_add = sum(a for a, _ in lib_ns_w.values()); lw_del = sum(d for _, d in lib_ns_w.values())
t_add = sum(a for a, _ in tst_ns.values())

story += [Spacer(1, 1.1 * inch), P("Gemmini N:M Sparsity: Code Changes", "title"),
          P("Every change made to the upstream UC Berkeley Gemmini code on the sparse-nm branches", "sub"),
          Spacer(1, 8),
          P("Hunter Caraway · changes made 2026-10-06 · document generated 2026-10-06", "small"), Spacer(1, 24),
          P("Summary", "h2"),
          table([["Repository (ucb-bar upstream)", "Upstream base → sparse-nm", "Files", "Lines"],
                 ["gemmini (Chisel RTL + configs)", f"{M(BASE['gem'])} → {M(git(GEM, 'rev-parse', '--short', 'HEAD').strip())}",
                  f"{len(gem_ns)} modified", f"+{g_add} / −{g_del}"],
                 ["libgemmini (Spike functional model)", f"{M(BASE['lib'])} → {M(git(LIB, 'rev-parse', '--short', 'HEAD').strip())}",
                  f"{len(lib_ns)} modified", f"+{l_add} / −{l_del}<br/>(+{lw_add} / −{lw_del} ignoring whitespace)"],
                 ["gemmini-rocc-tests (bare-metal C)", f"{M(BASE['tst'])} → {M(git(TST, 'rev-parse', '--short', 'HEAD').strip())}",
                  "1 modified, 5 new", f"+{t_add} / −0"]],
                [2.15 * inch, 1.75 * inch, 1.05 * inch, W - 4.95 * inch]),
          Spacer(1, 10),
          P("The gemmini repo also bumps its two software submodules to the sparse-nm commits above. "
            "Chipyard itself is untouched; the two new SoC configs live inside Gemmini's own "
            f"{M('chipyard/GemminiConfigs.scala')}. Nothing has been pushed; all three branches are local."),
          P("How to read this document", "h2"),
          *B([f"Every edit in the source is marked with a {M('// changed:')} comment, so the changes can also be found with "
              f"{M('grep -rn &quot;changed:&quot;')}.",
              "Diffs are shown against the upstream base commit, with 3 lines of context. "
              "<font color='#1e6b34'>Green</font> lines are added, <font color='#a3321f'>red</font> lines removed, "
              "<font color='#2a5db0'>blue</font> lines start a hunk. The two number columns are old and new line numbers.",
              "Lines too long for the page wrap onto a continuation line marked ↪.",
              f"The libgemmini diff is shown with whitespace changes ignored ({M('git diff -w')}). The full diff's "
              f"{l_del} removed lines are the dense compute loop re-indented inside a new {M('else')} branch, with no logic change.",
              "All 11 commits carry a Co-Authored-By: Claude trailer: the changes were written in a Claude Code session "
              "under Hunter Caraway's git identity."])]

story += [PageBreak(), P("1 · Overview", "h1"),
          P("The change adds an optional N:M structured-sparsity mode (M = 2N; built and tested for 2:4 and 4:8) to Gemmini's "
            "weight-stationary systolic array. Weights are pruned along K, independently for each output column: every group of "
            "M rows keeps N values. A K×J weight matrix is stored as (K·N/M)×J kept values plus a same-shaped array of "
            "log2(M)-bit indexes, each naming the row inside its group the value came from. A squashed 16×16 weight tile therefore "
            "covers 32 original rows, so the array does the same matmul with half the weight tiles."),
          P(f"With {M('nm_sparsity = None')} (the default) every new port and register is left out at elaboration "
            "and the generated dense hardware is meant to be unchanged. (The dense baseline in the run report was built from "
            "stock sources, so it does not re-verify this branch with sparsity off.)"),
          P("How an index and its activations reach a PE", "h2"),
          datapath(),
          P("Figure 1. The path the new metadata and activations take, top to bottom. Each box is one changed file.", "cap"),
          P("Commit history", "h2")]
hist = [["Commit", "Repo", "Summary"]]
for repo, key, name in [(TST, "tst", "rocc-tests"), (LIB, "lib", "libgemmini"), (GEM, "gem", "gemmini")]:
    for h, d, s, b in commits(repo, BASE[key]):
        hist.append([f"{M(h)}<br/><font size='7' color='#5a6270'>{d[11:]}</font>", name,
                     f"<b>{escape(s)}</b><br/>{escape(b)}" if b else f"<b>{escape(s)}</b>"])
hist[1:] = sorted(hist[1:], key=lambda r: re.search(r"(\d\d:\d\d)", r[0])[1])
story += [table(hist, [0.75 * inch, 0.8 * inch, W - 1.55 * inch]),
          P("All commits are dated 2026-10-06 (times are EDT). Messages are as written in git, minus the trailer.", "cap")]

# ISA
story += [PageBreak(), P("2 · Interface changes (ISA)", "h1"),
          table([["Item", "Encoding", "Meaning"],
                 ["config_ex", f"{M('rs1[10]')} (was spacer)", "1 = sparse mode on. Weight-stationary only, no A/B transpose."],
                 ["NM_META_CMD", f"RoCC {M('funct = 26')}", "Carries index rows in rs1 and rs2. Fills one DIM×DIM index tile; a finished tile goes into the 4-deep FIFO."],
                 ["preload (sparse mode)", "unchanged encoding", "A real preload pops one index tile and stalls until one is there. A garbage-address preload (weight reuse) pops nothing."],
                 ["compute (sparse mode)", f"{M('rs1 = a_lo')}, {M('rs2 = a_hi')}", "The B/D operand slot carries columns DIM…2·DIM−1 of the activation row, so sparse mode has no bias input. Preload the bias into the accumulator instead."]],
                [1.35 * inch, 1.4 * inch, W - 2.75 * inch]),
          Spacer(1, 6), P("Index packing in NM_META_CMD", "h2"),
          P("Each index is log2(M) bits. A row is DIM indexes packed with column 0 in the lowest bits. Each 64-bit register "
            "holds as many whole rows as fit, rs1 first, then rs2. For the 16×16 array:"),
          table([["Pattern", "Index bits", "Row width", "Rows per register", "Rows per command", "Commands per tile"],
                 ["2:4", "2", "32 bits", "2", "4", "4"],
                 ["4:8", "3", "48 bits", "1", "2", "8"]],
                [W / 6] * 6),
          Spacer(1, 6),
          P(f"The generated header {M('gemmini_params.h')} gains {M('HAS_NM_SPARSITY')}, {M('NM_N')} and {M('NM_M')} "
            "when sparsity is configured, so software can check what the hardware supports."),
          P("Elaboration-time checks", "h2"),
          P(f"{M('GemminiArrayConfig')} now refuses configurations the sparse datapath can't support:"),
          *B(["M = 2N and N &gt; 0 (the activation row is exactly two operand widths)",
              "array rows divide evenly into groups of N",
              "dataflow is not output-stationary only",
              f"{M('hardcode_d_to_garbage_addr')} is off (the high half of the activations uses the D slot)",
              "input and weight types have the same width (the B port carries activations)",
              "M is a power of two, and one index row fits in 64 bits"])]

# Part 3: RTL
gem_notes = {
 "chipyard/GemminiConfigs.scala": "Adds the two SoC configs used for simulation: <b>GemminiNMRocketConfig</b> (2:4) and "
     "<b>GemminiNM48RocketConfig</b> (4:8). They match the stock GemminiRocketConfig (one big Rocket core, 128-bit system bus) "
     "except for the Gemmini parameters.",
 "src/main/scala/gemmini/Configs.scala": f"Adds {M('nmSparseConfig')} / {M('nm48SparseConfig')}, the default config with "
     f"{M('nm_sparsity')} set, and the {M('NMSparseGemminiConfig')} mixin that instantiates Gemmini with one of them.",
 "src/main/scala/gemmini/GemminiConfigs.scala": f"Adds the {M('nm_sparsity: Option[(Int, Int)]')} parameter (default "
     f"{M('None')}), the elaboration checks listed in section 2, the derived {M('nm_n')}/{M('nm_m')}/{M('nm_idx_bits')} values, "
     "and the three header defines.",
 "src/main/scala/gemmini/GemminiISA.scala": f"Defines {M('NM_META_CMD = 26')} and takes one bit of the config_ex spacer for "
     f"{M('nm_sparse')} (rs1[10]).",
 "src/main/scala/gemmini/Controller.scala": f"Decodes {M('NM_META_CMD')} and sends it straight to the execute controller's "
     f"{M('nm_meta_in')} port instead of allocating a reservation-station entry. Order is still preserved because preloads pop "
     "the index FIFO in program order.",
 "src/main/scala/gemmini/ExecuteController.scala": "The core of the control side. "
     "Adds the new input port; assembles incoming rows into a DIM×DIM index tile and queues finished tiles 4 deep; "
     f"latches {M('nm_sparse_mode')} from config_ex; blocks a real sparse preload (alone or overlapped with a compute) until its "
     f"tile is queued, and pops the tile when the preload finishes; and sends the matching index row with each D row into the "
     f"mesh. Note the comment at the top: {M('nm_row_bits')} must be defined <i>before</i> {M('ComputeCntlSignals')} is built. "
     "Scala initializes vals in order, and defining it later produced a 0-bit field that firtool silently removed. That was the "
     "&quot;hardware ignores the indexes&quot; bug found during RTL debugging.",
 "src/main/scala/gemmini/MeshWithDelays.scala": f"Adds the {M('nm_sparse')} request bit and the {M('d_meta')} input. In sparse "
     "mode it builds each array row's group of M activations from the 2·DIM-wide row (A port = low half, B port = high half), "
     "zeroes the B input to the mesh (partial sums start at 0), and feeds the indexes in with D. In dense mode on sparse "
     "hardware each row gets its own activation in slot 0 with index 0.",
 "src/main/scala/gemmini/Mesh.scala": f"The A input becomes a {M('Vec(M, inputType)')} per row when sparsity is on, and a new "
     f"{M('in_meta')} input is pipelined down each column with exactly the timing of {M('in_d')}.",
 "src/main/scala/gemmini/Tile.scala": "Same widening of A inside a tile, and chains the index through the PEs of each column, "
     "the same path the weights take.",
 "src/main/scala/gemmini/PE.scala": f"Each PE gets index registers {M('m1')}/{M('m2')}, double-buffered exactly like weight "
     f"registers {M('c1')}/{M('c2')}, so a new tile's indexes can preload while the current tile computes. In WS mode the "
     "index belonging to the weight in use selects one of the M activations; OS mode takes slot 0. The PE forwards the whole "
     "activation group to its right-hand neighbour, not just the one it picked.",
}
order = ["src/main/scala/gemmini/GemminiISA.scala", "src/main/scala/gemmini/GemminiConfigs.scala",
         "src/main/scala/gemmini/Configs.scala", "chipyard/GemminiConfigs.scala",
         "src/main/scala/gemmini/Controller.scala", "src/main/scala/gemmini/ExecuteController.scala",
         "src/main/scala/gemmini/MeshWithDelays.scala", "src/main/scala/gemmini/Mesh.scala",
         "src/main/scala/gemmini/Tile.scala", "src/main/scala/gemmini/PE.scala"]
assert set(order) == set(gem_diff), set(gem_diff) ^ set(order)
story += [PageBreak(), P("3 · Gemmini RTL (Chisel)", "h1"),
          P(f"Repository {M('generators/gemmini')}, diff {M(BASE['gem'] + '..sparse-nm')}. Files go in data-path order: "
            "ISA and configuration first, then the controllers, then the array from the outside in.")]
for f in order:
    a, d = gem_ns[f]
    story += [CondPageBreak(1.6 * inch),
              KeepTogether([P(f"{f}  <font name='Sans' size='9' color='#5a6270'>+{a} / −{d}</font>", "file"),
                            P(gem_notes[f])]),
              code_table(gem_diff[f]), Spacer(1, 4)]

# Part 4: libgemmini
lib_notes = {
 "gemmini.h": f"Adds the {M('NM_N')}/{M('NM_M')} defaults (2:4), the sparse-mode state (the mode flag, the tile being "
     f"assembled, a {M('std::deque')} index-tile FIFO, and the indexes the PEs and the last preload hold), the "
     f"{M('nm_meta_load')} handler and {M('nm_meta_funct = 26')}.",
 "gemmini.cc": "Mirrors the RTL so tests can be checked on Spike before RTL simulation: "
     f"{M('config')} reads rs1[10] and asserts WS with no transposes; {M('preload')} pops an index tile on a real sparse preload "
     f"and aborts if none is queued (where the RTL would hang); {M('compute')} gains a sparse WS path where each PE row's "
     f"index selects from the 2·DIM activation row; {M('nm_meta_load')} unpacks index rows exactly like the hardware. "
     f"<br/><br/><b>Upstream bug fix (a14aaa1):</b> {M('gemmini_state_t::reset()')} never initialized {M('norm_stat_id')} or the "
     "counter arrays, so out-of-bounds writes depended on leftover heap contents. It became visible as a segfault once the "
     "state struct grew. It is a standalone commit and could be sent upstream on its own. After the fix, all 54 runnable "
     "bare-metal tests are clean under AddressSanitizer.",
}
story += [PageBreak(), P("4 · Spike functional model (libgemmini)", "h1"),
          P(f"Repository {M('software/libgemmini')}, diff {M(BASE['lib'] + '..sparse-nm')}, whitespace ignored. "
            f"The N:M pattern is fixed at compile time; build with {M('-DNM_N=4 -DNM_M=8')} for 4:8.")]
for f in ["gemmini.h", "gemmini.cc"]:
    a, d = lib_ns[f]
    story += [CondPageBreak(1.6 * inch),
              KeepTogether([P(f"{f}  <font name='Sans' size='9' color='#5a6270'>+{a} / −{d} (+{lib_ns_w[f][0]} / −{lib_ns_w[f][1]} ignoring whitespace)</font>", "file"),
                            P(lib_notes[f])]),
              code_table(lib_diff_w[f]), Spacer(1, 4)]

# Part 5: tests
story += [PageBreak(), P("5 · Software and tests (gemmini-rocc-tests)", "h1"),
          P(f"Repository {M('software/gemmini-rocc-tests')}, diff {M(BASE['tst'] + '..sparse-nm')}. One existing file changed "
            "(the Makefile); everything else is new."),
          table([["File", "Lines", "Purpose"],
                 [M("include/gemmini_nm.h"), str(tst_ns["include/gemmini_nm.h"][0]), "CPU helpers (prune, check, compress, decompress, dense and sparse reference matmuls) and the Gemmini wrappers (sparse config_ex, index packing and sending)"],
                 [M("bareMetalC/nm_sparse_sw.c"), str(tst_ns["bareMetalC/nm_sparse_sw.c"][0]), "CPU only: prune → compress → decompress → matmul round trip for 2:4, 4:8 and 1:2"],
                 [M("bareMetalC/nm_sparse_matmul.c"), str(tst_ns["bareMetalC/nm_sparse_matmul.c"][0]), "32×64×32 dense vs sparse on Gemmini, both checked against the CPU reference; prints cycles"],
                 [M("bareMetalC/nm_sparse_debug.c"), str(tst_ns["bareMetalC/nm_sparse_debug.c"][0]), "One sparse tile scored against the right answer and five specific wrong ones, so a failure names the bug"],
                 [M("bareMetalC/nm_sparse_perf.c"), str(tst_ns["bareMetalC/nm_sparse_perf.c"][0]), "64×128×32 timing with hardware counters: dense, dense+bias, two sparse orderings, weight reuse, and CPU-only variants"],
                 [M("bareMetalC/Makefile"), "+4", "Adds the four tests to the build"]],
                [2.0 * inch, 0.5 * inch, W - 2.5 * inch]),
          Spacer(1, 4),
          P(f"The 4:8 binaries ({M('*_48-baremetal')}) are built by the project's {M('run-flow.sh tests')} with "
            f"{M('-DNM_N=4 -DNM_M=8')}; no Makefile change is needed for them."),
          P("bareMetalC/Makefile  <font name='Sans' size='9' color='#5a6270'>+4 / −0</font>", "file"),
          code_table(tst_diff["bareMetalC/Makefile"]),
          CondPageBreak(2 * inch),
          P("include/gemmini_nm.h  <font name='Sans' size='9' color='#5a6270'>new file, " + str(tst_ns["include/gemmini_nm.h"][0]) + " lines</font>", "file"),
          P(f"The software interface to the new mode. The top half is portable C used by the CPU reference and the tests. "
            f"The bottom half wraps the new instructions: {M('gemmini_nm_config_ex')} sets the sparse bit, and "
            f"{M('nm_pack_meta')} packs a tile of indexes once at weight-prep time so the timed loop only runs "
            f"{M('nm_send_meta')}. The comment block at the start of the Gemmini half documents the programming model."),
          code_table(listing(TST / "include/gemmini_nm.h"))]

story += [PageBreak(), P("Appendix · New test sources", "h1"),
          P("Full listings of the four new bare-metal tests, as committed.")]
for f, note in [("bareMetalC/nm_sparse_sw.c", "CPU-only check of the helper library."),
                ("bareMetalC/nm_sparse_matmul.c", "End-to-end correctness on Gemmini, dense and sparse, with cycle counts. "
                 "The sparse loop sends tile q+1's indexes between preload(q) and compute(q) so the hardware can still overlap them."),
                ("bareMetalC/nm_sparse_debug.c", "Single-tile diagnostic. It was the test that identified the index-width bug."),
                ("bareMetalC/nm_sparse_perf.c", "The benchmark behind every number in the run report. "
                 "The CPU-only variants replace each Gemmini instruction with an empty asm that still uses its operands, "
                 "which measures how long the core takes just to build the command stream.")]:
    story += [CondPageBreak(1.6 * inch),
              KeepTogether([P(f"{f}  <font name='Sans' size='9' color='#5a6270'>new file, {tst_ns[f][0]} lines</font>", "file"),
                            P(note)]),
              code_table(listing(TST / f)), Spacer(1, 4)]

story += [CondPageBreak(3 * inch), P("Review notes", "h1"),
          P("Things a reviewer would raise, found while preparing this document:"),
          *B([f"<b>Cosmetic:</b> in {M('libgemmini/gemmini.cc')}, the {M('dprintf(&quot;GEMMINI: compute - PEs after matmul&quot;)')} "
              "line lost its indentation when the dense loop was wrapped in the new branch. No behaviour change.",
              f"<b>Not wired into the hardware loops:</b> {M('LOOP_WS')} / {M('tiled_matmul_auto')} don't know about sparse mode. "
              "It is only reachable through the explicit preload/compute sequence the tests use.",
              "<b>No bias in sparse mode:</b> the B/D slot carries the high half of the activations. Bias has to be preloaded into "
              "the accumulator.",
              f"<b>Index storage:</b> the tests keep each index as an {M('uint8_t')} in memory. Only log2(M) bits are used, and the "
              "packed form exists only transiently before it is sent.",
              f"<b>{M('dense_bias')} in nm_sparse_perf</b> is timed but its results are deliberately not checked; its bias is "
              "an arbitrary tile."])]

# ---------- build ----------
merged = []
for f in story:
    if merged and isinstance(merged[-1], Paragraph) and merged[-1].style.name in ("h1", "h2"):
        h = merged.pop()
        f = list(f._content) if isinstance(f, KeepTogether) else [f]
        if isinstance(f[0], Table) and len(f[0]._cellvalues) > 30:
            merged += [CondPageBreak(1.5 * inch), h, *f]
        elif merged and isinstance(merged[-1], Paragraph) and merged[-1].style.name == "h1":
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
        c.drawString(0.8 * inch, 0.55 * inch, "Gemmini N:M Sparsity · Code changes")
        c.drawRightString(letter[0] - 0.8 * inch, 0.55 * inch, str(doc.page))
        c.setStrokeColor(RULE); c.setLineWidth(0.5)
        c.line(0.8 * inch, 0.72 * inch, letter[0] - 0.8 * inch, 0.72 * inch)
    else:
        c.setFillColor(ACC); c.rect(0, letter[1] - 0.28 * inch, letter[0], 0.28 * inch, stroke=0, fill=1)
    c.restoreState()

doc = BaseDocTemplate(str(OUT), pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                      topMargin=0.75 * inch, bottomMargin=0.9 * inch,
                      title="Gemmini N:M Sparsity: Code Changes", author="Hunter Caraway",
                      subject="Changes to UC Berkeley Gemmini, libgemmini and gemmini-rocc-tests on the sparse-nm branches")
doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")], onPage=on_page)])
doc.build(story)
print(OUT)
