from dataclasses import dataclass

from typstpresenter.model.Element import Element
from typstpresenter.model.text.Text import Text


@dataclass(frozen=True)
class PresentationTitle(Element):
    """
    Title of an entire presentation.
    """

    text: Text

    def __str__(self) -> str:
        return str(self.text)
