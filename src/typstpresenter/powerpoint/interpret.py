import logging

from pptx.shapes import Subshape
from pptx.shapes.base import BaseShape

from typstpresenter.model.Element import Element
from typstpresenter.powerpoint.Ignore import Ignore
from typstpresenter.powerpoint.interpreters.TableInterpreter import TableInterpreter
from typstpresenter.powerpoint.interpreters.Interpreter import Interpreter
from typstpresenter.powerpoint.interpreters.PictureInterpreter import PictureInterpreter
from typstpresenter.powerpoint.interpreters.SlidePlaceholderInterpreter import SlidePlaceholderInterpreter
from typstpresenter.powerpoint.interpreters.TextBoxInterpreter import TextBoxInterpreter

logger = logging.getLogger(__name__)

_interpreters: list[Interpreter] = [
    TableInterpreter(),
    SlidePlaceholderInterpreter(),
    TextBoxInterpreter(),
    PictureInterpreter(),
]


def interpret(shape: BaseShape | Subshape, context: dict | None = None) -> Element | None:
    """
    Interpret a shape (or a subshape, which is an element introduced as child of a shape) coming from a PowerPoint.

    Interpreting a shape means converting it to an Element, i.e., an instance from our abstraction layer which
    represents the contents of a PowerPoint independently of its presentation format. Multiple interpreters exist
    for different kinds of shapes.

    Returns the element (if recognized) or None if it should be completely ignored (such as slide numbers or pure design lines)
    """

    for interpreter in _interpreters:
        if interpreter.can_interpret(shape):
            interpreted = interpreter(shape, context=context)

            # We could be more explicit in the return types maybe?
            # E.g. what should you do with a SlideTitle? It feels strange returning it here alongside regular texts.
            if isinstance(interpreted, Ignore):
                return None

            if isinstance(interpreted, Element):
                return interpreted

    logger.warning(
        f"Ignoring Shape {shape.shape_type if hasattr(shape, 'shape_type') else 'Unknown'}. Did not find a matching handler."
    )
    return None
