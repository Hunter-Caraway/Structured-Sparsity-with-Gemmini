# Report builders

The scripts that generated the PDF reports removed on 2026-10-06, kept so the reports can be remade.

| Script | Made | Notes |
|---|---|---|
| `build_paper.py` | `N-M-Sparsity-Paper-Summary.pdf` | The 4-page plain-language summary. Reads `verification/paper_data.json` and `pattern_fidelity.out`. **Start here.** |
| `build_changes.py` | `Gemmini-NM-Code-Changes.pdf` | Every code change, with diffs, read live from the `sparse-nm` branches in `~/chipyard` |
| `build_report.py` | `N-M-Sparsity-Run-Report.pdf` | Detailed run report. **Its speed-up figures are superseded**; reuse only the setup/debugging parts |
| `build_explained.py` | `N-M-Sparsity-Explained.pdf` | **Withdrawn**: its numbers are hard-coded from the superseded benchmark. The script refuses to run |

## Before running them

- They need `reportlab` and `Pillow`, which aren't in the Chipyard conda env. Make a small virtual env:
  `python3 -m venv .venv && .venv/bin/pip install reportlab pillow`
- They were written as one-off scripts. They find the repo from their own location and Chipyard from
  `CHIPYARD_DIR` (default `~/chipyard`), write the PDF to the repo root, and save temporary images next to
  themselves. `build_report.py` and `build_explained.py` also expect terminal captures (`cap/check.txt`,
  `cap/spike.txt`) that no longer exist. Treat those two as templates.
- `build_paper.py` writes its numbers from data, not from text, so after new experiments it mostly needs the data
  sources pointed at the new results.
- Fonts: Liberation Sans and Noto Sans Mono (installed on Fedora by default).
