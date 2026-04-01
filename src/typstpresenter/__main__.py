import logging

import typer

from .stats.main import app as stats_app
from .convert.main import app as convert_app


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] @%(name)s:%(lineno)d %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("typstpresenter")
logger.setLevel(logging.INFO)


app = typer.Typer(pretty_exceptions_show_locals=False)
app.add_typer(convert_app)
app.add_typer(stats_app)

if __name__ == "__main__":
    app()
