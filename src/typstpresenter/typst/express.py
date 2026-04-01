from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import Environment, PackageLoader, select_autoescape

if TYPE_CHECKING:
    from typstpresenter.model.Presentation import Presentation

_jinja_env = Environment(
    loader=PackageLoader("typstpresenter"), autoescape=select_autoescape()
)


def express(presentation: Presentation) -> str:
    """
    Express a presentation represented in an abstract format as a Typst string.
    """
    return _jinja_env.get_template("typst/presentation.diatypst.typ").render(presentation=presentation)
