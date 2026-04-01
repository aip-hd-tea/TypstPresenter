from dataclasses import dataclass

from typstpresenter.model.Element import Element
from typstpresenter.model.text.Text import Text


@dataclass(frozen=True)
class Title(Element):
    """
    Title of a slide. There can be only one per slide, and it is usually placed at the top in a larger font.
    """

    text: Text

    def __str__(self) -> str:
        return str(self.text)
