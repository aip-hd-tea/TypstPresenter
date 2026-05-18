from collections.abc import Sequence
from dataclasses import dataclass

from typstpresenter.model.Element import Element

type Row = Sequence[Element]


@dataclass(frozen=True)
class Table(Element):
    rows: Sequence[Row]

    @property
    def num_columns(self) -> int:
        return len(self.rows[0])
