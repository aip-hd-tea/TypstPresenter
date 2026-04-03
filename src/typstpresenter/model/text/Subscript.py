from dataclasses import dataclass

from typstpresenter.model.Element import Element
from typstpresenter.model.text.Text import Text


@dataclass(frozen=True)
class Subscript(Element):
    text: Text

    def __str__(self) -> str:
        return f"_{str(self.text)}"
