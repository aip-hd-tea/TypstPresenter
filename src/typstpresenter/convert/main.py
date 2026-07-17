import logging
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer()
logger = logging.getLogger(__name__)


@app.command()
def convert(
    pptx_path: Annotated[Path, typer.Argument(help="Input *.pptx file")],
    out_path: Annotated[Path | None, typer.Option("--out", "-o",
        help="Output *.typ path (default: next to the input)")] = None,
    minimal: Annotated[bool, typer.Option(
        help="Human-editable output without verification probes")] = True,
    pdf: Annotated[bool, typer.Option(help="Also compile the result to PDF")] = False,
) -> None:
    """
    Convert a PowerPoint presentation to a Touying/Typst presentation.
    """
    from typstpresenter.convert.emitter import emit_touying
    from typstpresenter.verify.typst_tools import compile_pdf

    typ_path = out_path or pptx_path.with_suffix(".typ")
    typ_path.parent.mkdir(parents=True, exist_ok=True)
    emit_touying(pptx_path, typ_path, minimal=minimal)
    typer.echo(f"wrote {typ_path}")
    if pdf:
        compile_pdf(typ_path)
        typer.echo(f"wrote {typ_path.with_suffix('.pdf')}")
