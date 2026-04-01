import typer
import logging
from pathlib import Path
from typing import Annotated

from typstpresenter.model.Presentation import Presentation


app = typer.Typer()
logger = logging.getLogger(__name__)


@app.command()
def convert(
    pptx_path: Annotated[
        Path,
        typer.Argument(help="Path to a *.pptx file"),
    ],
    typst_path: Annotated[
        Path | None,
        typer.Argument(
            help="Path to the output *.typ file. If omitted, will print to standard output."
        ),
    ] = None,
) -> None:
    """
    Convert a given (single) presentation from PPTX to Typst.
    """
    presentation = Presentation.from_file(pptx_path)

    if typst_path:
        presentation.to_file(typst_path)
    else:
        print(presentation.to_typst_str())
