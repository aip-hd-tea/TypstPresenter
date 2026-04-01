from pptx.enum.shapes import PP_PLACEHOLDER_TYPE
from pptx.shapes import Subshape
from pptx.shapes.base import BaseShape
from pptx.shapes.placeholder import SlidePlaceholder
from pptx.text.text import _Paragraph, TextFrame, _Run

from typstpresenter.model.Element import Element
from typstpresenter.model.text.Link import Link
from typstpresenter.model.text.Text import Text, Atom
from typstpresenter.model.Title import Title
from typstpresenter.powerpoint.Ignore import Ignore


def _interpret_placeholder(shape: SlidePlaceholder) -> Element | Ignore | None:
    """
    Interpret a shape of type SlidePlaceholder.

    These are somewhat nicer to interpret, because some of them have a type assigned which is actually semantic.

    See: https://python-pptx.readthedocs.io/en/latest/user/understanding-shapes.html
    """

    match shape.placeholder_format.type:
        case PP_PLACEHOLDER_TYPE.TITLE:
            return Title(text=_interpret_text_frame(shape.text_frame))
        case PP_PLACEHOLDER_TYPE.SLIDE_NUMBER:
            return Ignore()
        case _:
            return None


def _interpret_text_frame(text_frame: TextFrame) -> Text:
    if len(text_frame.paragraphs) == 1:
        return _interpret_paragraph(text_frame.paragraphs[0])
    else:
        raise NotImplementedError()  # TODO Implement as needed


def _interpret_paragraph(paragraph: _Paragraph) -> Text:
    return Text(tuple(_interpret_run(run) for run in paragraph.runs))


def _interpret_run(run: _Run) -> Atom:
    if run.hyperlink.address is not None:
        return Link(text=Text(run.text), target=run.hyperlink.address)

    return run.text


def interpret(shape: BaseShape | Subshape) -> Element | None:
    """
    Interpret a shape (or a subshape, which is an element introduced as child of a shape) coming from a PowerPoint.

    Interpreting a shape means converting it to an Element, i.e., an instance from our abstraction layer which
    we control. If a shape cannot be interpreted, this returns None.
    """
    match shape:
        case SlidePlaceholder():
            return _interpret_placeholder(shape)
        case _:
            # TODO Implement as needed
            return None
