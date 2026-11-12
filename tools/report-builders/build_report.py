#!/usr/bin/env python3
"""Builds the N:M sparsity run report PDF from the project's logs, results and charts."""
import os, re, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Image as RLImage,
                                Table, TableStyle, PageBreak, KeepTogether, CondPageBreak, Preformatted)

PROJ = Path(__file__).resolve().parents[2]
LOGS = PROJ / "logs"
CHARTS = PROJ / "analysis" / "charts"
SCR = Path(__file__).parent
CAP = SCR / "cap"
SHOTS = SCR / "shots"; SHOTS.mkdir(exist_ok=True)
OUT = PROJ / "N-M-Sparsity-Run-Report.pdf"
GEM = Path(os.environ.get("CHIPYARD_DIR", Path.home() / "chipyard")) / "generators" / "gemmini"

ANSI = re.compile(r"\x1b\[[0-9;]*m")
def rd(p): return ANSI.sub("", Path(p).read_text(errors="replace"))

# ---------- fonts ----------
LS = "/usr/share/fonts/liberation-sans-fonts/"
NM = "/usr/share/fonts/google-noto/"
pdfmetrics.registerFont(TTFont("Sans", LS + "LiberationSans-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Bold", LS + "LiberationSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Italic", LS + "LiberationSans-Italic.ttf"))
pdfmetrics.registerFont(TTFont("Sans-BoldItalic", LS + "LiberationSans-BoldItalic.ttf"))
pdfmetrics.registerFont(TTFont("Mono", NM + "NotoSansMono-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Mono-Bold", NM + "NotoSansMono-Bold.ttf"))
from reportlab.pdfbase.pdfmetrics import registerFontFamily
registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-Italic", boldItalic="Sans-BoldItalic")
registerFontFamily("Mono", normal="Mono", bold="Mono-Bold", italic="Mono", boldItalic="Mono-Bold")

# ---------- terminal screenshots ----------
TERM_BG = (30, 32, 38); TERM_FG = (220, 223, 228); BAR = (52, 55, 63)
HI = {"pass": (110, 200, 120), "PASS": (110, 200, 120), "passed": (110, 200, 120), "ok": (110, 200, 120),
      "FAIL": (240, 100, 90), "FAILED": (240, 100, 90), "error": (240, 100, 90), "Error": (240, 100, 90),
      "Fatal": (240, 100, 90), "ERROR": (240, 100, 90), "FAILURE": (240, 100, 90)}
fmono = ImageFont.truetype(NM + "NotoSansMono-Regular.ttf", 26)
fmono_b = ImageFont.truetype(NM + "NotoSansMono-Bold.ttf", 26)
fbar = ImageFont.truetype(LS + "LiberationSans-Regular.ttf", 24)

def terminal(name, title, lines, cols=None):
    """Render text lines as a terminal window PNG. Lines starting with '$ ' are drawn as prompts."""
    cw = fmono.getbbox("M")[2]; lh = 36; pad = 24; bar_h = 48
    lines = [l.expandtabs(4) for l in lines]
    cols = cols or max(100, max(len(l) for l in lines))
    W = pad * 2 + cw * cols; H = bar_h + pad * 2 + lh * len(lines)
    im = Image.new("RGB", (W, H), TERM_BG); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, bar_h], fill=BAR)
    for i, c in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
        d.ellipse([20 + i * 34, 14, 40 + i * 34, 34], fill=c)
    tw = d.textlength(title, font=fbar); d.text(((W - tw) / 2, 11), title, font=fbar, fill=(190, 193, 200))
    y = bar_h + pad
    for l in lines:
        if l.startswith("$ "):
            d.text((pad, y), "$", font=fmono_b, fill=(120, 170, 250))
            d.text((pad + cw * 2, y), l[2:], font=fmono_b, fill=(255, 255, 255))
        else:
            col = TERM_FG
            for k, v in HI.items():
                if re.search(r"(^|[^a-zA-Z_])" + re.escape(k) + r"($|[^a-zA-Z_])", l):
                    col = v; break
            if l.startswith("#"): col = (140, 145, 155)
            d.text((pad, y), l, font=fmono, fill=col)
        y += lh
    p = SHOTS / f"{name}.png"; im.save(p); return p

def short(path):
    cy, home = f"{GEM.parents[1]}/", f"{Path.home()}/"
    return str(path).replace(f"{cy}sims/verilator/generated-src/", "…/generated-src/") \
                    .replace(f"{GEM}/software/gemmini-rocc-tests/build/bareMetalC/", "…/bareMetalC/") \
                    .replace(cy, "~/chipyard/").replace(home, "~/")

shots = {}
# 1 setup failure
t = rd(LOGS / "setup/setup-attempt1-failed.log").splitlines()
shots["setup_fail"] = terminal("setup_fail", "logs/setup/setup-attempt1-failed.log (last lines)",
    ["$ ./build-setup.sh riscv-tools", "  …  (conda-lock install usage dump, 150+ lines)  …"] + t[-6:])
# 2 firemarshal
t = rd(LOGS / "setup/firemarshal-step9-guestmount-failure.log").splitlines()
fm = [re.sub(r"^\S+ \S+ \[\w+\s*\] ", "", l) for l in t[-4:]]
fm = [short(l)[:110] for l in fm]
shots["firemarshal"] = terminal("firemarshal", "logs/setup/firemarshal-step9-guestmount-failure.log (last lines)",
    ["# step 9: FireMarshal buildroot image (not needed for bare-metal Gemmini)", *fm,
     "FileNotFoundError: [Errno 2] No such file or directory: 'guestmount'"])
# 3/4 live check + spike
shots["check"] = terminal("check", "live run · 2026-10-06 10:15 · ./run-flow.sh check",
    [l for l in (CAP / "check.txt").read_text().splitlines() if l.strip()])
sp = [short(l) for l in (CAP / "spike.txt").read_text().splitlines() if l.strip()]
shots["spike"] = terminal("spike", "live run · 2026-10-06 10:15 · ./run-flow.sh spike", sp)
# 5 baseline timeout + pass
t = rd(LOGS / "baseline/baseline_matmul-try1-timeout-10Mcycles.log").splitlines()
bt = [short(l)[:112] for l in t[-11:-4]]
shots["base_timeout"] = terminal("base_timeout", "logs/baseline/baseline_matmul-try1-timeout-10Mcycles.log",
    ["$ make CONFIG=GemminiRocketConfig run-binary BINARY=…/matmul-baremetal", "  …  (2 of 8 dataflow/transpose combinations finish)  …", *bt,
     "# 10,000,001 cycles = Chipyard's default TIMEOUT_CYCLES; wall time 24m35s"])
t = rd(LOGS / "baseline/baseline_matmul-RESULT.txt").splitlines()
shots["base_pass"] = terminal("base_pass", "logs/baseline/baseline_matmul-RESULT.txt",
    ["$ make CONFIG=GemminiRocketConfig run-binary BINARY=…/matmul-baremetal TIMEOUT_CYCLES=150000000"] +
    [short(l)[:112] for l in t])
# 6 scala compile errors
t = [l for l in rd(LOGS / "sparse/verilator-build-nm24-try1.log").splitlines() if l.startswith("[error]")]
shots["scala_err"] = terminal("scala_err", "logs/sparse/verilator-build-nm24-try1.log",
    ["$ make -j4 CONFIG=GemminiNMRocketConfig"] + [short(l).replace("~/chipyard/generators/gemmini/src/main/scala/gemmini/", "")[:112] for l in t[:10]])

def sim_out(path, keep):
    """Program output lines only: drop make/sim command lines (they contain paths or start with a tab)."""
    out = []
    for l in rd(path).splitlines():
        if l.startswith(("\t", "(set", "if [", "make", "mkdir")) or re.search(r"(/home/|\.\./|generators/)", l) and "FAILED" not in l: continue
        if any(re.match(k, l) for k in keep): out.append(short(l)[:112])
    return out
# 7 first rtl run (wrong + slow)
shots["run1"] = terminal("run1", "logs/sparse/nm24-rtl-run1.log (first sparse RTL run, 2:4)",
    ["$ make CONFIG=GemminiNMRocketConfig run-binary-fast BINARY=…/nm_sparse_matmul-baremetal"] +
    sim_out(LOGS / "sparse/nm24-rtl-run1.log", [r"nm_sparse_matmul", r"sparse mismatch", r"(dense|sparse)\s+cycles:", r"\*\*\* FAILED", r"real"]))
# 8 debug run2 vs run3
shots["dbg_fail"] = terminal("dbg_fail", "logs/sparse/nm24-rtl-run2-nm_sparse_debug.log (before the fix)",
    ["$ make CONFIG=GemminiNMRocketConfig run-binary-fast BINARY=…/nm_sparse_debug-baremetal"] +
    sim_out(LOGS / "sparse/nm24-rtl-run2-nm_sparse_debug.log", [r"nm_sparse_debug", r"  [a-z]", r"row 0", r"\*\*\* FAILED"]))
shots["dbg_pass"] = terminal("dbg_pass", "logs/sparse/nm24-rtl-run3-nm_sparse_debug.log (after the width fix)",
    ["$ make CONFIG=GemminiNMRocketConfig run-binary-fast BINARY=…/nm_sparse_debug-baremetal"] +
    sim_out(LOGS / "sparse/nm24-rtl-run3-nm_sparse_debug.log", [r"nm_sparse_debug", r"  [a-z]", r"row 0"]))
# 9 git log
gl = ["$ git log --oneline   # generators/gemmini (sparse-nm)"]
gl += subprocess.run(["git", "-C", str(GEM), "log", "--format=%h %ad  %s", "--date=format:%H:%M", "-3"], capture_output=True, text=True).stdout.splitlines()
gl += ["$ git log --oneline   # software/libgemmini (sparse-nm)"]
gl += subprocess.run(["git", "-C", str(GEM / "software/libgemmini"), "log", "--format=%h  %ad  %s", "--date=format:%H:%M", "-4"], capture_output=True, text=True).stdout.splitlines()
gl += ["$ git log --oneline   # software/gemmini-rocc-tests (sparse-nm)"]
gl += subprocess.run(["git", "-C", str(GEM / "software/gemmini-rocc-tests"), "log", "--format=%h  %ad  %s", "--date=format:%H:%M", "-4"], capture_output=True, text=True).stdout.splitlines()
shots["gitlog"] = terminal("gitlog", "commit history, 2026-10-06 (times are local, EDT)", gl)
ds = ["$ git diff --stat 8c3f9923 HEAD   # generators/gemmini"]
ds += subprocess.run(["git", "-C", str(GEM), "diff", "--stat=100", "8c3f9923", "HEAD"], capture_output=True, text=True).stdout.splitlines()
shots["diffstat"] = terminal("diffstat", "RTL diff against the upstream Gemmini commit", ds)
# 10 perf output (trimmed after ex_active)
perf = []
for l in rd(LOGS / "runs/bench-nm24-nm_sparse_perf-20261006-025209.log").splitlines():
    if l.startswith("nm_sparse_perf") or l.startswith("cpu only"):
        perf.append(l)
    elif re.match(r"^[a-z_]+ +total", l):
        m = re.match(r"^(\S+)\s+total\s+(\d+)\s+cpu_issue_done\s+(\d+)\s+pairs\s+(\d+)\s+cyc/pair\s+(\d+) \| ex_active=(\d+)", l)
        perf.append(f"{m[1]:<17} total {m[2]:>5}  cpu_issue_done {m[3]:>5}  pairs {m[4]:>3}  cyc/pair {m[5]:>3} | ex_active={m[6]}")
shots["perf24"] = terminal("perf24", "logs/runs/bench-nm24-nm_sparse_perf-20261006-025209.log (counter columns trimmed)",
    ["$ ./run-flow.sh bench nm24"] + perf)
# 11 4:8 debug + matmul
d48 = sim_out(LOGS / "runs/bench-nm48-nm_sparse_debug-20261006-030607.log", [r"nm_sparse_debug", r"  [a-z]", r"row 0"])
m48 = sim_out(LOGS / "runs/bench-nm48-nm_sparse_matmul-20261006-030607.log", [r"nm_sparse_matmul", r"(dense|sparse)\s+cycles:"])
shots["nm48"] = terminal("nm48", "logs/runs/bench-nm48-*-20261006-030607.log", ["$ ./run-flow.sh bench nm48"] + d48 + m48)

# ---------- styles ----------
INK = colors.HexColor("#1a1d23"); MUTED = colors.HexColor("#5a6270"); ACC = colors.HexColor("#2a6fd6")
RULE = colors.HexColor("#d9dde3"); TINT = colors.HexColor("#f3f5f8"); OK = colors.HexColor("#2f8f46"); BAD = colors.HexColor("#c7402f")
S = {
 "title": ParagraphStyle("title", fontName="Sans-Bold", fontSize=26, leading=31, textColor=INK, spaceAfter=6),
 "sub": ParagraphStyle("sub", fontName="Sans", fontSize=13, leading=18, textColor=MUTED, spaceAfter=4),
 "h1": ParagraphStyle("h1", fontName="Sans-Bold", fontSize=17, leading=22, textColor=INK, spaceBefore=6, spaceAfter=8),
 "h2": ParagraphStyle("h2", fontName="Sans-Bold", fontSize=12.5, leading=16, textColor=INK, spaceBefore=10, spaceAfter=5),
 "body": ParagraphStyle("body", fontName="Sans", fontSize=10, leading=14.2, textColor=INK, spaceAfter=6),
 "bul": ParagraphStyle("bul", fontName="Sans", fontSize=10, leading=14, textColor=INK, leftIndent=14, bulletIndent=3, spaceAfter=3),
 "cap": ParagraphStyle("cap", fontName="Sans-Italic", fontSize=8.6, leading=11.5, textColor=MUTED, spaceBefore=3, spaceAfter=12),
 "cell": ParagraphStyle("cell", fontName="Sans", fontSize=8.6, leading=11, textColor=INK),
 "cellb": ParagraphStyle("cellb", fontName="Sans-Bold", fontSize=8.6, leading=11, textColor=INK),
 "code": ParagraphStyle("code", fontName="Mono", fontSize=8.2, leading=11, textColor=INK, backColor=TINT,
                        borderPadding=(6, 7, 6, 7), leftIndent=7, rightIndent=7, spaceBefore=4, spaceAfter=10),
 "small": ParagraphStyle("small", fontName="Sans", fontSize=8.6, leading=11.5, textColor=MUTED),
}
W = letter[0] - 2 * 0.85 * inch

def P(t, s="body"): return Paragraph(t, S[s])
def B(items): return [Paragraph(i, S["bul"], bulletText="•") for i in items]
def code(t): return Preformatted(t, S["code"])
def img(path, caption, width=W, maxh=7.4 * inch):
    im = Image.open(path); w, h = im.size; dw = width; dh = dw * h / w
    if dh > maxh: dh = maxh; dw = dh * w / h
    r = RLImage(str(path), width=dw, height=dh); r.hAlign = "CENTER"
    return KeepTogether([r, P(caption, "cap")])
def shot(key, caption, width=W): return img(shots[key], "<b>Screenshot.</b> " + caption, width)
def fig(name, caption, width=W, maxh=7.4 * inch): return img(CHARTS / f"{name}-light.png", caption, width, maxh)
def table(rows, widths, header=True, align_right=()):
    data = [[Paragraph(str(c), S["cellb" if (header and i == 0) else "cell"]) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
          ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
          ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
    if header: st += [("BACKGROUND", (0, 0), (-1, 0), TINT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
    t.setStyle(TableStyle(st)); return t

# ---------- content ----------
story = []
story += [Spacer(1, 1.3 * inch),
          P("Structured N:M Sparsity on Gemmini", "title"),
          P("Run report: environment setup, baseline, RTL implementation, verification and benchmarks", "sub"),
          Spacer(1, 10),
          P("Hunter Caraway · work done 2026-10-05 to 2026-10-06 · report generated 2026-10-06", "small"),
          Spacer(1, 26)]
summary = [
 ["", ""],
 ["Goal", "Add N:M structured weight sparsity (2:4 and 4:8) to Gemmini's weight-stationary systolic array and measure it against dense."],
 ["Platform", "Chipyard <font name='Mono'>bfa5699f</font> · Gemmini <font name='Mono'>8c3f9923</font> (16×16 array, int8 in, int32 acc) · Rocket core · Verilator RTL sim + Spike"],
 ["Correctness", "<font color='#2f8f46'><b>2:4 and 4:8 pass on Spike and on Verilator RTL</b></font>. Hardware output matches the CPU reference 256/256 on the debug tile."],
 ["Array speedup", "Sparse array finishes the same 64×128×32 matmul in <b>half the busy cycles</b> (1344 → 672 with weight reuse; 1800 → 960 without)."],
 ["End-to-end", "<b>1.44× faster (2:4) and 1.36× faster (4:8)</b> with weight reuse. Without reuse sparse is slower (0.64–0.84×) because the CPU issuing metadata commands is the bottleneck."],
 ["Status", "Code on local <font name='Mono'>sparse-nm</font> branches in three repos (11 commits). Nothing pushed."],
]
t = table(summary, [1.15 * inch, W - 1.15 * inch], header=False)
t.setStyle(TableStyle([("BACKGROUND", (0, 1), (0, -1), TINT), ("FONTNAME", (0, 1), (0, -1), "Sans-Bold"),
                       ("LINEABOVE", (0, 1), (-1, 1), 0.8, INK)]))
story += [P("At a glance", "h2"), t, Spacer(1, 18)]
story += [P("How this report was made", "h2"),
          P("Every number here comes from the project's own files: <font name='Mono'>results/cycles.csv</font>, "
            "<font name='Mono'>analysis/all_data.csv</font> and the run logs under <font name='Mono'>logs/</font>. "
            "The charts are the PNGs that <font name='Mono'>analysis/make_charts.py</font> and "
            "<font name='Mono'>chart_all_data.py</font> produced. "
            "The terminal screenshots are drawn from the saved log files named in each title bar. "
            "Make and simulator echo lines are left out and long paths are shortened with “…”; "
            "the perf table is re-spaced with its stall-counter columns trimmed. Every line shown is otherwise as logged. "
            "The two marked “live run” were captured fresh on 2026-10-06 at 10:15 by running "
            "<font name='Mono'>./run-flow.sh check</font> and <font name='Mono'>./run-flow.sh spike</font>.")]

story += [PageBreak(), P("Contents", "h1")]
toc = [["Step", "What happened", "Outcome"],
       ["1", "Install Chipyard (Fedora 44): fix the build-setup.sh glibc bug, skip FireMarshal", "Toolchain + Verilator + Spike working"],
       ["2", "Build Gemmini's Spike extension and tests, smoke-test on Spike", "mvin_mvout and matmul pass"],
       ["3", "Dense baseline on Verilator (stock GemminiRocketConfig)", "PASSED, 28,599,226 cycles"],
       ["4", "Design and implement N:M sparsity (software, Spike model, RTL)", "11 commits on sparse-nm"],
       ["5", "Debug the RTL until it matches the reference", "Index width bug found and fixed"],
       ["6", "Benchmark 2:4 and 4:8 on RTL", "2× array speedup; 1.44× / 1.36× end-to-end"],
       ["7", "Reproduce everything with run-flow.sh", "One script, eight steps"],
       ["A", "Appendix: full counter data, log index, next steps", ""]]
story += [table(toc, [0.45 * inch, 3.9 * inch, W - 4.35 * inch])]
story += [Spacer(1, 16), P("Machine and tool versions", "h2"),
          table([["Item", "Value"],
                 ["Host", "Fedora 44, x86_64, 16 cores, 14 GB RAM, glibc 2.43, KDE Plasma 6.7"],
                 ["Chipyard", "<font name='Mono'>~/chipyard</font> @ <font name='Mono'>bfa5699f</font> (Merge PR #2385, 2026-10-05)"],
                 ["Gemmini", "<font name='Mono'>8c3f9923</font> (Merge PR #392, 2025-09-01), branch <font name='Mono'>sparse-nm</font>"],
                 ["Gemmini's CHIPYARD.hash", "<font name='Mono'>e0207441</font> (2025-02-12), an ancestor of HEAD, 635 commits behind"],
                 ["Conda env", "<font name='Mono'>~/chipyard/.conda-env</font>; conda-lock 4.0.2"],
                 ["Simulators", "Verilator (Chipyard conda env) and Spike + <font name='Mono'>libgemmini.so</font>"],
                 ["Array", "dim = 16 (16×16 PEs), int8 inputs, int32 accumulators"]],
                [1.7 * inch, W - 1.7 * inch])]

# Step 1
story += [PageBreak(), P("Step 1 · Install Chipyard", "h1"),
          P("Chipyard has to live at a path with no spaces or colons: <font name='Mono'>:</font> is the PATH separator and "
            "Make can't handle spaces. So it lives at <font name='Mono'>~/chipyard</font>, and this project folder only "
            "holds scripts, logs and results. On Fedora, conda has to be deactivated before sourcing the environment:"),
          code("conda deactivate\ncd ~/chipyard\nsource env.sh        # re-activates ~/chipyard/.conda-env and sets RISCV"),
          P("1a. First attempt failed at step 1", "h2"),
          shot("setup_fail", "<font name='Mono'>build-setup.sh</font> exits at step 1. The real error is hidden behind a "
               "<font name='Mono'>conda-lock install</font> usage dump."),
          P("<b>Root cause:</b> a bug in <font name='Mono'>build-setup.sh</font> that only shows up when the host glibc is "
            "<i>newer</i> than the pinned one."),
          *B(["The script compares the host glibc (2.43) with the pin in <font name='Mono'>chipyard-base.yaml</font> "
              "(<font name='Mono'>sysroot_linux-64=2.34</font>). They differ, so it rewrites the pin to 2.43 and re-solves the lockfile.",
              "The re-solve deletes the committed lockfile first. conda-forge has no <font name='Mono'>sysroot_linux-64=2.43</font> "
              "(the newest is 2.39), so the solve fails and the lockfile is gone.",
              "On the next run the pin already matches the host, so regeneration is skipped and conda-lock is pointed at a file "
              "that no longer exists, which produces the usage dump."]),
          P("<b>Fix</b> (no Chipyard source changes): restore the two files, then run step 1 by hand without the glibc rewrite "
            "and continue the script from step 2.", "body"),
          code("git checkout -- conda-reqs/chipyard-base.yaml \\\n"
               "    conda-reqs/conda-lock-reqs/conda-requirements-riscv-tools-linux-64.conda-lock.yml\n"
               "conda install -n base -c conda-forge conda-lock          # 4.0.2\n"
               "conda-lock install --conda \"$CONDA_EXE\" -p ~/chipyard/.conda-env \\\n"
               "    conda-reqs/conda-lock-reqs/conda-requirements-riscv-tools-linux-64.conda-lock.yml\n"
               "./build-setup.sh riscv-tools -s 1                        # everything except step 1"),
          P("1b. Step 9 (FireMarshal) skipped", "h2"),
          shot("firemarshal", "FireMarshal's Linux image build needs <font name='Mono'>guestmount</font> (libguestfs). "
               "Bare-metal Gemmini work doesn't use FireMarshal, so step 9 was skipped and steps 10–11 ran with "
               "<font name='Mono'>-s 1 … -s 9</font>. To enable it later: <font name='Mono'>sudo dnf install libguestfs</font>."),
          P("Setup steps 2–8, 10 and 11 all succeeded."),
          ]

# Step 2
story += [CondPageBreak(3.5 * inch), P("Step 2 · Spike extension, test build and smoke tests", "h1"),
          P("Gemmini's functional model for Spike (<font name='Mono'>libgemmini</font>) and the bare-metal test suite "
            "(<font name='Mono'>gemmini-rocc-tests</font>) were built, then smoke-tested on Spike. All 56 "
            "<font name='Mono'>bareMetalC</font> tests built without errors."),
          code("./run-flow.sh check       # env sanity\n./run-flow.sh spike-lib   # make -C software/libgemmini install\n"
               "./run-flow.sh tests       # gemmini-rocc-tests/build.sh + the _48 sparse variants\n./run-flow.sh spike       # spike --extension=gemmini <test>"),
          shot("check", "Environment check. The conda env, RISCV toolchain, Spike, Verilator, firtool and "
               "<font name='Mono'>libgemmini.so</font> are all found, and Gemmini is on the <font name='Mono'>sparse-nm</font> branch."),
          shot("spike", "The Spike suite run fresh for this report. The two stock smoke tests (<font name='Mono'>mvin_mvout</font>, "
               "<font name='Mono'>matmul</font>) and the two sparse tests added in Step 4 all pass."),
          P("One snag here: four <font name='Mono'>mvin_mvout*</font> binaries came out <b>0 bytes</b> after a "
            "<font name='Mono'>make</font> was killed mid-write, and their fresh timestamps made later builds skip them. "
            "They were deleted and rebuilt, and <font name='Mono'>run-flow.sh tests</font> now deletes 0-byte binaries before building.")]

# Step 3
story += [CondPageBreak(3.5 * inch), P("Step 3 · Dense baseline on Verilator", "h1"),
          P("The stock <font name='Mono'>GemminiRocketConfig</font> was built into a Verilator simulator with "
            "<font name='Mono'>-j4</font>. With 14 GB of RAM, 16 parallel Verilator compiles risk the OOM killer. "
            "Then <font name='Mono'>matmul-baremetal</font> ran on it. That test checks all 8 combinations of OS/WS dataflow × A/B transpose."),
          P("3a. First run hit Chipyard's default cycle limit", "h2"),
          shot("base_timeout", "Chipyard's default <font name='Mono'>TIMEOUT_CYCLES</font> is 10M, but this test needs about 28.6M, "
               "mostly the CPU computing reference results. Only 2 of the 8 combinations finished."),
          P("3b. Re-run with a 150M cycle limit", "h2"),
          shot("base_pass", "The baseline passes: all 8 combinations, 28,599,226 simulation cycles, 104 min 33 s of wall time "
               "with full instruction tracing. The trace alone is 1.2 GB."),
          P("To keep this baseline truly stock, the in-progress RTL edits were <font name='Mono'>git stash</font>ed while the "
            "simulator was elaborated. Chipyard re-elaborates whenever Gemmini's Scala changes. The edits were popped back once "
            "the sim was running. The generated RTL was checked for any <font name='Mono'>nm_meta</font> logic (none), and the "
            "restored edits matched a saved patch byte for byte."),
          P("<b>Caveat:</b> 28.6M is the simulator's total. It includes loading the program over the serial link and the CPU "
            "reference math, so only a small fraction is Gemmini work. Sparse-vs-dense comparisons in Step 6 use "
            "<font name='Mono'>nm_sparse_perf</font>, which times only the Gemmini work with <font name='Mono'>rdcycle</font>.")]

# Step 4
story += [CondPageBreak(3.5 * inch), P("Step 4 · Design and implementation", "h1"),
          P("4a. What gets pruned", "h2"),
          *B(["The stationary <b>weights</b> in weight-stationary mode are pruned along K, independently for each output column. "
              "This matches NVIDIA's 2:4 semantics for a layer <font name='Mono'>y = x·W</font>.",
              "A K×J weight matrix becomes (K·N/M)×J kept values plus a same-shape index array. Each index is the row "
              "inside its M-group, log2(M) bits. One squashed 16×16 weight tile covers 32 original rows.",
              "The design is generic N:M with M = 2N. 2:4 and 4:8 are built as separate configs: "
              "<font name='Mono'>GemminiNMRocketConfig</font> and <font name='Mono'>GemminiNM48RocketConfig</font>."]),
          P("4b. Hardware changes", "h2"),
          table([["Block", "Change"],
                 ["PE", "Holds a log2(M)-bit index next to its weight, double-buffered like the weight registers, plus an M:1 mux that picks one activation from its group."],
                 ["Mesh / MeshWithDelays", "Activation row is 2·DIM wide. The low half enters on the A port, the high half on the bias (B) port, so sparse mode takes its bias preloaded into the accumulator. Indexes travel down the columns with the weights during preload."],
                 ["Controller / ExecuteController", "New <font name='Mono'>NM_META_CMD</font> (funct 26). Index rows skip the reservation station and go into a 4-tile FIFO. Each real sparse preload pops one tile, and stalls if its tile hasn't arrived."],
                 ["ISA / configs", "<font name='Mono'>config_ex</font> rs1[10] turns sparse mode on. <font name='Mono'>nm_sparsity = Some((n, m))</font> in <font name='Mono'>GemminiArrayConfig</font>; <font name='Mono'>None</font> leaves the dense hardware unchanged."]],
                [1.6 * inch, W - 1.6 * inch]),
          Spacer(1, 8),
          shot("diffstat", "The whole RTL change against upstream Gemmini: 279 lines added and 22 removed across 12 files. "
               "Chipyard's own repo is untouched; the new configs live in Gemmini's <font name='Mono'>chipyard/GemminiConfigs.scala</font>."),
          P("4c. Software and tests", "h2"),
          table([["Test (bareMetalC)", "What it checks"],
                 ["nm_sparse_sw", "CPU only: prune → compress → decompress → matmul round trip for 2:4, 4:8 and 1:2"],
                 ["nm_sparse_debug", "One sparse tile. Scores the hardware output against the correct answer and against five specific wrong answers, so a failure tells you which bug it is."],
                 ["nm_sparse_matmul", "32×64×32 dense vs sparse on Gemmini, both checked against the CPU reference"],
                 ["nm_sparse_perf", "64×128×32 timing: dense, dense+bias, sparse (2 orderings), with and without weight reuse, plus CPU-only variants that issue no Gemmini instructions"]],
                [1.45 * inch, W - 1.45 * inch]),
          Spacer(1, 6),
          P("The 4:8 versions are built as <font name='Mono'>*_48-baremetal</font> with <font name='Mono'>-DNM_N=4 -DNM_M=8</font>. "
            "The Spike model (<font name='Mono'>libgemmini</font>) got the same sparse mode so the tests could be checked on Spike first."),
          shot("gitlog", "All 11 commits on the three <font name='Mono'>sparse-nm</font> branches, in order. "
               "<font name='Mono'>a14aaa1</font> fixes a pre-existing upstream bug and can be upstreamed on its own.")]

# Step 5
story += [CondPageBreak(3.5 * inch), P("Step 5 · Debugging the RTL", "h1"),
          P("5a. Scala compile errors", "h2"),
          shot("scala_err", "First sparse build. <font name='Mono'>flatten(r)</font> was parsed as passing an implicit argument, "
               "and <font name='Mono'>Vec</font> invariance broke the now-generic A port. Fixed by indexing a flattened local "
               "and wrapping the shifted outputs in <font name='Mono'>VecInit</font>."),
          P("5b. First RTL run: wrong answers and inflated timing", "h2"),
          shot("run1", "The first sparse run on RTL failed the reference check and reported 22,674 cycles. Two separate "
               "problems: the index packing was inside the timed loop (it's weight prep, so it was moved out), and the "
               "hardware wasn't using the indexes at all."),
          P("5c. Finding the index bug", "h2"),
          shot("dbg_fail", "<font name='Mono'>nm_sparse_debug</font> before the fix. The output matches the “index ignored "
               "(all 0)” guess 256/256, so the hardware was behaving as if every index were 0."),
          P("<b>Root cause:</b> Scala initialization order. <font name='Mono'>ComputeCntlSignals</font> was built before "
            "<font name='Mono'>nm_row_bits</font> was defined, so the index field had width 0 "
            "(<font name='Mono'>UInt&lt;0&gt;</font>), and firtool constant-folded it away. It showed up in the "
            "<font name='Mono'>.fir</font>. Moving the width definitions above the bundle fixed it."),
          shot("dbg_pass", "The same test after the fix: 256/256 against the correct sparse result and near zero against every wrong guess."),
          P("5d. Other problems along the way", "h2"),
          table([["Problem", "Fix"],
                 ["Hardware counters reported more cycles than had elapsed", "Some counters tick on stale control signals while idle. The test now snapshots them at the fence."],
                 ["Metadata through the reservation station could reorder against preloads", "Commit 47f5f15f: index rows bypass the reservation station into a dedicated 4-tile FIFO."],
                 ["Spike segfault / heap corruption after adding state fields", "<b>Existing Gemmini bug:</b> <font name='Mono'>gemmini_state_t::reset()</font> never initialized <font name='Mono'>norm_stat_id</font> or the counter arrays. Fixed in a14aaa1. All 54 runnable tests are clean under AddressSanitizer."]],
                [2.3 * inch, W - 2.3 * inch]),
          Spacer(1, 10),
          fig("fig7-history", "<b>Figure 7.</b> How the 2:4 sparse timing changed across design iterations. Left: moving index "
              "packing out of the timed loop took the first run from 22,674 to 815 cycles. Right: moving metadata into the FIFO "
              "fixed ordering but barely changed cycles. The “no metadata” bar is a lower bound: what the loop costs with the metadata commands removed (its results are wrong).")]

# Step 6
story += [CondPageBreak(3.5 * inch), P("Step 6 · Benchmarks on RTL", "h1"),
          P("Each sparse config ran the three RTL tests with <font name='Mono'>run-binary-fast</font> and "
            "<font name='Mono'>LOADMEM=1</font>. Neither changes the measured cycles; they skip instruction logging and the slow serial load. "
            "Results were appended to <font name='Mono'>results/cycles.csv</font>."),
          code("./run-flow.sh sim nm24 && ./run-flow.sh bench nm24     # 2:4, run 20261006-025209\n"
               "./run-flow.sh sim nm48 && ./run-flow.sh bench nm48     # 4:8, run 20261006-030607"),
          shot("perf24", "<font name='Mono'>nm_sparse_perf</font> on the 2:4 RTL. A “pair” is one preload + compute, so one weight "
               "tile. Sparse needs 32 tiles where dense needs 64. <font name='Mono'>ex_active</font> is the cycles the execute controller "
               "spent streaming rows through the array. The scratchpad/stall counter columns are trimmed here; they're in Figure 8."),
          shot("nm48", "4:8 correctness on RTL: the debug tile matches 256/256, and the 32×64×32 matmul passes against the CPU reference."),
          CondPageBreak(3 * inch),
          P("6a. Results table (64×128×32, int8 in, int32 accumulate)", "h2")]
res = [["Variant", "2:4 total", "2:4 array busy", "4:8 total", "4:8 array busy"],
       ["dense, no weight reuse", "2,217", "1,800", "2,248", "1,800"],
       ["sparse, no weight reuse", "2,977", "<b>960</b>", "3,513", "<b>960</b>"],
       ["sparse, natural order", "2,633", "960", "3,470", "960"],
       ["dense, weight reuse", "3,623", "1,344", "3,761", "1,344"],
       ["sparse, weight reuse", "<b>2,508</b>", "<b>672</b>", "<b>2,771</b>", "<b>672</b>"],
       ["CPU-only issue, dense", "1,551", "–", "1,568", "–"],
       ["CPU-only issue, sparse", "1,995", "–", "2,685", "–"],
       ["nm_sparse_matmul 32×64×32, dense", "543", "", "554", ""],
       ["nm_sparse_matmul 32×64×32, sparse", "815", "", "1,031", ""]]
rt = table(res, [2.35 * inch] + [(W - 2.35 * inch) / 4] * 4)
rt.setStyle(TableStyle([("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
for r in rt._cellvalues:
    for c in r[1:]: c.style = ParagraphStyle("r", parent=c.style, alignment=2)
story += [rt, P("Source: <font name='Mono'>results/cycles.csv</font>. Weights are pruned to the pattern for both dense and sparse runs, "
                "so both compute the same answer. Every run passed its correctness check.", "cap")]
story += [P("6b. What the data shows", "h2"),
          *B(["<b>The sparse array does the same matmul in half the busy cycles:</b> 1344 → 672 with weight reuse, the theoretical "
              "2×; 1.88× without reuse. Identical for 2:4 and 4:8.",
              "<b>End to end with weight reuse</b>, the way Gemmini's real kernels run: <b>1.44× faster for 2:4, 1.36× for 4:8.</b>",
              "<b>Without reuse, sparse is slower end to end.</b> These bare-metal loops are limited by Rocket issuing RoCC commands. "
              "Building the command stream alone, with no accelerator, takes 67–86% of the runtime. Each sparse tile adds "
              "4 (2:4) or 8 (4:8) metadata commands, each costing 2 loads plus a RoCC instruction."]),
          fig("fig1-array-busy", "<b>Figure 1.</b> Array-busy cycles. The sparse array halves the time spent computing for both patterns."),
          fig("fig3-speedup", "<b>Figure 3.</b> Sparse speedup over dense. Array-level speedup reaches the 2× limit. End-to-end speedup "
              "only beats break-even with weight reuse."),
          fig("fig2-end-to-end", "<b>Figure 2.</b> End-to-end cycles (bars) against the CPU-only issue time for the same loop (dots). "
              "CPU-only time is 67–86% of each total, so the CPU, not the array, sets most of the runtime."),
          fig("fig6-metadata-cost", "<b>Figure 6.</b> CPU cost to issue one tile's commands. A sparse tile does the work of two dense tiles "
              "but costs more than two dense tiles to issue. That overhead is why sparse only wins with weight reuse today."),
          fig("fig4-per-tile", "<b>Figure 4.</b> Where each tile's cycles go. Array-busy per tile stays at 21–30 cycles, close to the "
              "16-row floor, while the CPU-only issue cost pushes the totals out."),
          fig("fig5-utilization", "<b>Figure 5.</b> Share of the run the array spends computing. Dense keeps the array about 80% busy "
              "without reuse; sparse spends most of its run waiting on the CPU.")]

# Step 7
story += [CondPageBreak(3.5 * inch), P("Step 7 · Reproducing the flow", "h1"),
          P("<font name='Mono'>run-flow.sh</font> in the project folder wraps every step above. It sources the environment the "
            "Fedora way, picks <font name='Mono'>-j</font> from free RAM (about 2.5 GB per Verilator compile) and retries at "
            "<font name='Mono'>-j2</font> on an OOM kill. It restores the committed <font name='Mono'>gemmini_params.h</font> "
            "before building tests and deletes 0-byte binaries."),
          table([["Command", "What it does"],
                 ["./run-flow.sh env", "Print the commands to set up a fresh terminal by hand"],
                 ["./run-flow.sh check", "Check the conda env, RISCV, spike, verilator, firtool, libgemmini.so"],
                 ["./run-flow.sh spike-lib", "Build and install the Gemmini Spike extension"],
                 ["./run-flow.sh tests", "Build gemmini-rocc-tests plus the _48 sparse variants"],
                 ["./run-flow.sh spike", "Smoke tests + sparse tests on Spike"],
                 ["./run-flow.sh sim &lt;cfg&gt;", "Build a Verilator sim: dense, nm24 or nm48"],
                 ["./run-flow.sh baseline", "Dense matmul-baremetal on the dense sim"],
                 ["./run-flow.sh bench &lt;cfg&gt;", "nm_sparse_debug / matmul / perf on nm24 or nm48; appends to results/cycles.csv"],
                 ["./run-flow.sh all", "Everything above, in order"]],
                [1.9 * inch, W - 1.9 * inch]),
          Spacer(1, 8),
          table([["Variable", "Effect"],
                 ["CHIPYARD_DIR", "Where Chipyard lives (default ~/chipyard)"],
                 ["JOBS", "make -j for Verilator builds (default: picked from free RAM)"],
                 ["LOADMEM=1", "Load the binary straight into sim DRAM instead of over TSI. Only changes load time (bench defaults to 1)"],
                 ["NO_REBUILD=1", "Reuse the existing sim even if Scala changed since"],
                 ["TIMEOUT_CYCLES", "Sim cycle limit (default 150M; Chipyard's 10M is too short for matmul-baremetal)"]],
                [1.9 * inch, W - 1.9 * inch]),
          Spacer(1, 8),
          P("Then regenerate the charts with the Chipyard conda Python, which has matplotlib and pandas:"),
          code("~/chipyard/.conda-env/bin/python analysis/make_charts.py       # fig1–fig7\n"
               "~/chipyard/.conda-env/bin/python analysis/chart_all_data.py    # fig8–fig11 + analysis/all_data.csv"),
          P("The Spike model's N:M pattern is fixed at compile time (default 2:4). For 4:8 on Spike, rebuild "
            "<font name='Mono'>libgemmini</font> with <font name='Mono'>-DNM_N=4 -DNM_M=8</font>.")]

# Appendix
story += [CondPageBreak(3.5 * inch), P("Appendix A · Full counter data", "h1"),
          fig("fig8-all-counters", "<b>Figure 8.</b> Every hardware counter from <font name='Mono'>nm_sparse_perf</font>, both patterns, "
              "snapshotted at the fence. <font name='Mono'>cpu_*</font> rows issue no Gemmini instructions.", maxh=8.3 * inch),
          fig("fig9-scratchpad-waits", "<b>Figure 9.</b> Scratchpad wait counters: cycles with no A, B or D row ready to stream. "
              "Lower is better."),
          fig("fig10-pattern-totals", "<b>Figure 10.</b> Total cycles for every benchmark run, 2:4 against 4:8. Dense runs are within "
              "0–4%; sparse runs cost 9–35% more for 4:8 because each tile carries twice the metadata commands."),
          fig("fig11-debug-checks", "<b>Figure 11.</b> <font name='Mono'>nm_sparse_debug</font> scoring on the final RTL. Only the "
              "correct sparse result matches the hardware output.", width=0.72 * W)]
story += [CondPageBreak(3.5 * inch), P("Appendix B · Log index", "h1"),
          table([["Log (under logs/)", "Contents"],
                 ["setup/setup-attempt1-failed.log", "Original failing build-setup.sh run (step 1)"],
                 ["setup/step1-conda-env-manual.log", "Manual conda-lock install"],
                 ["setup/setup-steps2-9.log, setup-steps10-11.log", "Rest of the setup (CIRCT, cleanup)"],
                 ["setup/firemarshal-step9-guestmount-failure.log", "FireMarshal guestmount failure"],
                 ["setup/gemmini-rocc-tests-build.log", "First test-suite build"],
                 ["baseline/spike-smoke.log", "Spike smoke tests"],
                 ["baseline/verilator-build-j4.log", "Stock GemminiRocketConfig sim build"],
                 ["baseline/baseline_matmul-try1-timeout-10Mcycles.log", "Baseline hitting the 10M cycle limit"],
                 ["baseline/baseline_matmul*.log, -RESULT.txt", "The passing baseline"],
                 ["sparse/verilator-build-nm24-try1..4, nm48.log", "Every N:M sim build (try1/2 compile errors, try3 width fix, try4 FIFO)"],
                 ["sparse/nm24-rtl-*.log, nm48-rtl-*.log", "Every RTL test run during development, in order"],
                 ["sparse/rtl-wip-backup.patch", "Safety copy of the RTL edits before the stash for the stock build"],
                 ["runs/rocc-tests-*, spike-*, bench-*", "Final run-flow.sh runs that produced results/cycles.csv"]],
                [2.9 * inch, W - 2.9 * inch]),
          Spacer(1, 14), P("Appendix C · Next steps", "h1"),
          *B(["<b>Move metadata off the CPU.</b> Put the indexes in memory, <font name='Mono'>mvin</font> them with the weights and have the "
              "preload (or a sparse-aware <font name='Mono'>LOOP_WS</font> unroller) fetch them. That removes the per-tile RoCC cost, "
              "which is why sparse only wins with weight reuse today.",
              "Support sparse mode in <font name='Mono'>LoopMatmul</font> so <font name='Mono'>tiled_matmul_auto</font> can use it.",
              "Pack index metadata in DRAM. The tests store each index as int8, but only log2(M) bits are needed.",
              "Area and timing: each PE adds a log2(M)-bit register pair and an M:1 mux. Run synthesis before scaling DIM."])]

# keep every heading on the same page as the block after it
merged = []
for f in story:
    if merged and isinstance(merged[-1], Paragraph) and merged[-1].style.name in ("h1", "h2"):
        h = merged.pop()
        # nesting KeepTogether breaks its height check, so splice the inner content in
        f = list(f._content) if isinstance(f, KeepTogether) else [f]
        if merged and isinstance(merged[-1], Paragraph) and merged[-1].style.name == "h1":
            merged.append(KeepTogether([merged.pop(), h, *f]))
        else:
            merged.append(KeepTogether([h, *f]))
    else:
        merged.append(f)
story = merged

# ---------- page template ----------
def on_page(c, doc):
    c.saveState()
    if doc.page > 1:
        c.setFont("Sans", 8); c.setFillColor(MUTED)
        c.drawString(0.85 * inch, 0.55 * inch, "Structured N:M Sparsity on Gemmini · Run report")
        c.drawRightString(letter[0] - 0.85 * inch, 0.55 * inch, str(doc.page))
        c.setStrokeColor(RULE); c.setLineWidth(0.5)
        c.line(0.85 * inch, 0.72 * inch, letter[0] - 0.85 * inch, 0.72 * inch)
    else:
        c.setFillColor(ACC); c.rect(0, letter[1] - 0.28 * inch, letter[0], 0.28 * inch, stroke=0, fill=1)
    c.restoreState()

doc = BaseDocTemplate(str(OUT), pagesize=letter, leftMargin=0.85 * inch, rightMargin=0.85 * inch,
                      topMargin=0.8 * inch, bottomMargin=0.9 * inch,
                      title="Structured N:M Sparsity on Gemmini: Run Report", author="Hunter Caraway",
                      subject="Chipyard/Gemmini N:M sparsity setup, implementation and benchmarks")
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=on_page)])
doc.build(story)
print(OUT)
