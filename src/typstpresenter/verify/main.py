import logging
from pathlib import Path
from typing import Annotated

import typer

from typstpresenter.verify.compare import compare_by_id, compare_spatial
from typstpresenter.verify.method_a import run_method_a
from typstpresenter.verify.method_b import run_method_b
from typstpresenter.verify.pptx_geometry import extract_pptx_geometry

app = typer.Typer()
logger = logging.getLogger(__name__)


@app.command()
def verify(
    pptx_path: Annotated[Path, typer.Argument(help="Ground-truth *.pptx file")],
    typ_path: Annotated[Path, typer.Argument(help="Generated *.typ file to check")],
    method: Annotated[str, typer.Option(help="a (PDF), b (introspection) or both")] = "both",
) -> None:
    """
    Check a generated Typst presentation against its PPTX ground truth.

    Exits with code 1 if any issues are found.
    """
    truth = extract_pptx_geometry(pptx_path)
    slide0 = truth.slides[0]
    failed = False

    if method in ("b", "both"):
        result = run_method_b(typ_path, slide0.width, slide0.height)
        report = compare_by_id(truth, result.geometry, overflows=result.overflows)
        report.timings["query"] = result.query_seconds
        typer.echo(f"--- Method B (introspection)\n{report.summary()}")
        failed |= not report.ok

    if method in ("a", "both"):
        result = run_method_a(typ_path)
        report = compare_spatial(truth, result.geometry)
        report.timings["compile"] = result.compile_seconds
        report.timings["extract"] = result.extract_seconds
        typer.echo(f"--- Method A (PDF)\n{report.summary()}")
        failed |= not report.ok

    if failed:
        raise typer.Exit(code=1)


@app.command()
def benchmark(
    out_dir: Annotated[Path, typer.Option("--out-dir", "-o",
        help="Directory for the generated corpus")] = Path("verify_corpus"),
    repeats: Annotated[int, typer.Option(help="Timing repetitions per case")] = 3,
    report_path: Annotated[Path | None, typer.Option("--report",
        help="Write the markdown report to this file")] = None,
) -> None:
    """
    Generate the evaluation corpus and benchmark Method A vs Method B.
    """
    from typstpresenter.verify.benchmark import run_benchmark, to_markdown

    results = run_benchmark(out_dir, repeats=repeats)
    markdown = to_markdown(results)
    typer.echo(markdown)
    if report_path:
        report_path.write_text(markdown, encoding="utf-8")
        typer.echo(f"\nreport written to {report_path}")
