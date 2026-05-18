from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jinja2 import Environment, PackageLoader, select_autoescape, pass_context

from typstpresenter.model.Element import Element
from typstpresenter.typst.expressors.Expressor import Expressor
from typstpresenter.typst.expressors.GridExpressor import GridExpressor
from typstpresenter.typst.expressors.ImageExpressor import ImageExpressor
from typstpresenter.typst.expressors.LinkExpressor import LinkExpressor
from typstpresenter.typst.expressors.ListExpressor import ListExpressor
from typstpresenter.typst.expressors.NoneExpressor import NoneExpressor
from typstpresenter.typst.expressors.StringExpressor import StringExpressor
from typstpresenter.typst.expressors.SubscriptExpressor import SubscriptExpressor
from typstpresenter.typst.expressors.SuperscriptExpressor import SuperscriptExpressor
from typstpresenter.typst.expressors.TableExpressor import TableExpressor
from typstpresenter.typst.expressors.TextExpressor import TextExpressor
from typstpresenter.typst.expressors.TitleExpressor import TitleExpressor

if TYPE_CHECKING:
    from typstpresenter.model.Presentation import Presentation


_jinja_env = Environment(
    loader=PackageLoader("typstpresenter"), autoescape=select_autoescape()
)

# If need be, one could encapsulate this, but currently, there is no need.
_expressors: list[Expressor] = [
    LinkExpressor(),
    TableExpressor(),
    TextExpressor(),
    SubscriptExpressor(),
    SuperscriptExpressor(),
    ListExpressor(),
    GridExpressor(),
    ImageExpressor(),
    TitleExpressor(),
    StringExpressor(),
    NoneExpressor(),
]


def express(presentation: Presentation, media_dir: str = "media") -> str:
    """
    Express a presentation represented in an abstract format as a Typst string.
    """
    return _jinja_env.get_template("typst/presentation.diatypst.typ").render(
        presentation=presentation, media_dir=media_dir
    )


@pass_context
def _express_element(context: Any, element: Element | str | None) -> str:
    def dispatcher(e: Element | str | None) -> str:
        return _express_element(context, e)

    for expressor in _expressors:
        if expressor.can_express(element):
            return expressor(element, dispatcher, context)

    return str(element)


# This way, you can say something in Jinja like `{{ slide.title | express }}` and Jinja will apply the _express_element
# function to it, which renders stuff to Typst
_jinja_env.filters["express"] = _express_element
