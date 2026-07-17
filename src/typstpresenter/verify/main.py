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
    method: Annotated[str, typer.Option(
        help="a (PDF), b (introspection), both, or s (minimal/flow output)")] = "both",
) -> None:
    """
    Check a generated Typst presentation against its PPTX ground truth.

    Exits with code 1 if any issues are found.
    """
    if method == "s":
        from typstpresenter.verify.method_s import verify_minimal

        report = verify_minimal(typ_path, pptx_path)
        typer.echo(f"--- Method S (minimal layout sanity)\n{report.summary()}")
        if not report.ok:
            raise typer.Exit(code=1)
        return

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
def showcase(
    data_dir: Annotated[Path, typer.Option("--data-dir",
        help="Directory with test presentations")] = Path("tests/data"),
    out_dir: Annotated[Path, typer.Option("--out-dir", "-o",
        help="Where to put .typ and .pdf files")] = Path("tests/results_tmp/showcase"),
) -> None:
    """
    Emit .typ and compiled PDF for every test presentation (tests/data plus
    the IBN_presentations directories and the generated corpus cases), so a
    human can judge conversion quality. Regenerate after every major change.
    """
    from typstpresenter.convert.emitter import emit_touying
    from typstpresenter.verify.compare import compare_by_id
    from typstpresenter.verify.corpus import generate_corpus
    from typstpresenter.verify.method_b import run_method_b
    from typstpresenter.verify.method_s import verify_minimal
    from typstpresenter.verify.typst_tools import TypstError, compile_pdf

    out_dir.mkdir(parents=True, exist_ok=True)

    sources = sorted(data_dir.glob("*.pptx"))
    for sub in ("IBN_presentations", "IBN_presentations2"):
        sources += sorted((data_dir / sub).glob("*.pptx"))

    # generated corpus cases (clean ones) are part of the showcase too;
    # generate_corpus has emitted their .typ already
    corpus_cases = generate_corpus(out_dir / "corpus")
    jobs = [(c.pptx_path, c.typ_path, False) for c in corpus_cases
            if not c.expected_issues_b]

    for src in sources:
        pptx_path = out_dir / src.name
        pptx_path.write_bytes(src.read_bytes())
        jobs.append((pptx_path, pptx_path.with_suffix(".typ"), True))

    failed = 0
    for pptx_path, typ_path, emit in jobs:
        try:
            if emit:
                emit_touying(pptx_path, typ_path)
            compile_pdf(typ_path)
            truth = extract_pptx_geometry(pptx_path)
            slide0 = truth.slides[0]
            result = run_method_b(typ_path, slide0.width, slide0.height)
            report = compare_by_id(truth, result.geometry, overflows=result.overflows)

            s_info = ""
            if emit:
                # the human-facing showcase copy is the minimal (flow) output
                emit_touying(pptx_path, typ_path, minimal=True)
                compile_pdf(typ_path)
                s_report = verify_minimal(pptx_path=pptx_path, typ_path=typ_path)
                s_info = (f"  S: {len(s_report.issues)} issues, "
                          f"{len(s_report.warnings)} warnings")

            typer.echo(f"{typ_path.stem:<50} pdf ok  B: {len(report.issues)} issues, "
                       f"{len(report.warnings)} warnings{s_info}")
        except TypstError as error:
            failed += 1
            typer.echo(f"{typ_path.stem:<50} FAILED: {str(error)[:160]}")
    typer.echo(f"\n{len(jobs)} decks -> {out_dir} ({failed} failed)")


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
