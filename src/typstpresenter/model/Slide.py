import logging
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Self

import pptx.slide
from pptx.shapes.base import BaseShape

from typstpresenter.model.Element import Element
from typstpresenter.model.Title import Title
from typstpresenter.powerpoint.flatten import flatten
from typstpresenter.powerpoint.interpret import interpret


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Slide:
    elements: Sequence[Element]
    shapes: Sequence[BaseShape]

    @cached_property
    def title(self) -> Title | None:
        return self.get_singular_element_or_none(Title)

    @cached_property
    def content(self) -> Element | None:
        """
        Return the main content of the slide. We currently better hope that this is one (or no) element,
        which makes up the entire slide.
        """
        # Currently, everything which is not the title is content
        content_elements = tuple(e for e in self.elements if not isinstance(e, Title))

        if not content_elements:
            return None

        # TODO We should of course be able to handle multiple content elements. Technically, maybe a
        #  class Element(ElementGroup) could solve the problem. Semantically, this might be a bit harder, because
        #  how would you render them? As columns next to each other? Just one after the other? 70/30 split?
        if len(content_elements) > 1:
            logger.warning(
                "Slide hat more than 1 content element, which we currently can't handle."
            )

        return content_elements[0]

    def get_singular_element_or_none[T: Element](self, t: type[T]) -> T | None:
        elements = tuple(e for e in self.elements if isinstance(e, t))

        if not elements:
            return None

        if len(elements) > 1:
            raise ValueError(
                f"Slide had {len(elements)} elements of type {t}, but should have either 0 or 1."
            )

        return elements[0]

    @classmethod
    def from_pptx_slide(cls, pptx_slide: pptx.slide.Slide) -> Self:
        # pptx_slide.slide_layout.name contains the layout name, which is often rather useless, as it can be
        # "Titel und Inhalt" irrespective of whether the slide contains structured bullet-points or completely
        # free floating thought bubbles.

        elements_and_shapes = tuple(
            interpret(shape) or shape for shape in flatten(pptx_slide.shapes)
        )

        return cls(
            elements=tuple(x for x in elements_and_shapes if isinstance(x, Element)),
            shapes=tuple(x for x in elements_and_shapes if isinstance(x, BaseShape)),
        )
