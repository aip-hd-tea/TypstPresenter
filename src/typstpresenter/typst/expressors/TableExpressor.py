from __future__ import annotations

from typing import Any, Callable

from typstpresenter.model.Element import Element
from typstpresenter.model.Table import Table


class TableExpressor:
    def can_express(self, element: Element | str | None) -> bool:
        return isinstance(element, Table)

    def __call__(self, element: Table, express: Callable[[Element | str | None], str], context: Any) -> str:
        cells = tuple(f"[{express(cell)}]" for row in element.rows for cell in row)

        return f"""#table(
    columns: {element.num_columns},
    {", ".join(cells)}
)"""
