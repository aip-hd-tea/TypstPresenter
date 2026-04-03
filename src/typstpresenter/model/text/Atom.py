from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from typstpresenter.model.text.Superscript import Superscript
    from typstpresenter.model.text.Subscript import Subscript
    from typstpresenter.model.text.Link import Link

type Atom = str | Link | Subscript | Superscript
