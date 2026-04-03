from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import Environment, PackageLoader, select_autoescape

from typstpresenter.model.Element import Element
from typstpresenter.model.List import List
from typstpresenter.model.PresentationTitle import PresentationTitle
from typstpresenter.model.Title import Title
from typstpresenter.model.text.Link import Link
from typstpresenter.model.text.Text import Text

if TYPE_CHECKING:
    from typstpresenter.model.Presentation import Presentation


_jinja_env = Environment(
    loader=PackageLoader("typstpresenter"), autoescape=select_autoescape()
)


def express(presentation: Presentation) -> str:
    """
    Express a presentation represented in an abstract format as a Typst string.
    """
    return _jinja_env.get_template("typst/presentation.diatypst.typ").render(
        presentation=presentation
    )


def _express_element(element: Element | str) -> str:
    match element:
        case Link(text, target):
            return f'#link("{target}")[{_express_element(text)}]'
        case Text(value):
            return "".join(_express_element(x) for x in value)
        case List(items):
            # TODO Handle nested lists
            return "\n".join(f"- {_express_element(item)}" for item in items)
        case Title(text) | PresentationTitle(text):
            return _express_element(text)
        case None:
            return ""
        case _:
            return str(element)


# This way, you can say something in Jinja like `{{ slide.title | express }}` and Jinja will apply the _express_element
# function to it, which renders stuff to Typst
_jinja_env.filters["express"] = _express_element
