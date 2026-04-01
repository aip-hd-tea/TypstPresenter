from dataclasses import dataclass

from typstpresenter.model.Element import Element


@dataclass(frozen=True)
class Title(Element):
    """
    Title of a slide. There can be only one per slide, and it is usually placed at the top in a larger font.
    """

    text: str

    def __str__(self) -> str:
        return self.text
