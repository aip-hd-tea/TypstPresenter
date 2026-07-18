"""Build the human review drop for one complexity level.

Output layout (tests/results_tmp/diagram_svg/L{n}/):
    L{n}.pptx            copy of the source deck
    slide{N}.svg         our translation
    slide{N}.render.png  our SVG rendered through typst (the real pipeline)
    slide{N}.ref.png     PowerPoint COM export of the source slide
    index.html           side-by-side contact sheet

Run: uv run python -m typstpresenter.diagram2svg.review <pptx> <out_dir>
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pptx as _pptx

from typstpresenter.diagram2svg.convert import pptx_to_svgs

_PS_EXPORT = r"""
$ErrorActionPreference = "Stop"
$pp = New-Object -ComObject PowerPoint.Application
$pres = $pp.Presentations.Open("{pptx}", $true, $true, $false)
$i = 1
foreach ($slide in $pres.Slides) {{
    $slide.Export("{outdir}\slide$i.ref.png", "PNG", {w}, {h})
    $i++
}}
$pres.Close()
$pp.Quit()
"""


def export_reference_pngs(pptx_path: Path, out_dir: Path, width_px: int = 1920) -> bool:
    """Export each slide as PNG via PowerPoint COM. Returns False if COM fails."""
    prs = _pptx.Presentation(str(pptx_path))
    height_px = round(width_px * prs.slide_height / prs.slide_width)
    script = _PS_EXPORT.format(
        pptx=str(pptx_path.resolve()), outdir=str(out_dir.resolve()),
        w=width_px, h=height_px,
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True, capture_output=True, timeout=180,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def render_svg_via_typst(svg_path: Path, w_pt: float, h_pt: float, out_png: Path) -> bool:
    """Embed the SVG in a minimal typst page and compile to PNG (ppi 144)."""
    with tempfile.TemporaryDirectory() as td:
        main = Path(td) / "main.typ"
        shutil.copy(svg_path, Path(td) / svg_path.name)
        main.write_text(
            f"#set page(width: {w_pt}pt, height: {h_pt}pt, margin: 0pt)\n"
            f'#image("{svg_path.name}", width: 100%)\n',
            encoding="utf-8",
        )
        try:
            subprocess.run(
                ["typst", "compile", "--format", "png", "--ppi", "144",
                 str(main), str(out_png.resolve())],
                check=True, capture_output=True, timeout=60,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False


def build_review_drop(pptx_path: Path | str, out_dir: Path | str) -> Path:
    pptx_path = Path(pptx_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(pptx_path, out_dir / pptx_path.name)

    results = pptx_to_svgs(pptx_path, out_dir)

    prs = _pptx.Presentation(str(pptx_path))
    w_pt = prs.slide_width / 12700.0
    h_pt = prs.slide_height / 12700.0

    have_ref = export_reference_pngs(pptx_path, out_dir)
    for i, (svg_path, _res) in enumerate(results):
        render_svg_via_typst(svg_path, w_pt, h_pt, out_dir / f"slide{i + 1}.render.png")

    rows = []
    for i, (svg_path, res) in enumerate(results):
        n = i + 1
        ref = f'<img src="slide{n}.ref.png">' if have_ref else "<em>no PowerPoint COM</em>"
        note = ""
        if res.fallbacks:
            note += f"<br><small>bbox-fallback: {', '.join(res.fallbacks)}</small>"
        if res.skipped:
            note += f"<br><small>skipped: {', '.join(res.skipped)}</small>"
        rows.append(
            f"<tr><th>slide {n}{note}</th>"
            f"<td>{ref}</td>"
            f'<td><img src="slide{n}.render.png"></td>'
            f'<td><a href="slide{n}.svg">svg</a></td></tr>'
        )
    (out_dir / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'>"
        f"<title>diagram2svg review: {pptx_path.name}</title>"
        "<style>img{width:480px;border:1px solid #ccc} th{text-align:left;"
        "vertical-align:top;padding:4px} td{vertical-align:top}</style>"
        f"<h1>{pptx_path.name}</h1>"
        "<table><tr><th></th><th>PowerPoint reference</th>"
        "<th>our SVG via typst</th><th></th></tr>"
        + "".join(rows) + "</table>\n",
        encoding="utf-8",
    )
    return out_dir / "index.html"


if __name__ == "__main__":
    print(build_review_drop(sys.argv[1], sys.argv[2]))
