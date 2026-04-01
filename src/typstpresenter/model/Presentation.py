from dataclasses import dataclass
from typing import Self
from pathlib import Path
from collections.abc import Sequence

from typstpresenter.model.Slide import Slide

import pptx


@dataclass
class Presentation:
    slides: Sequence[Slide]

    # The path to the source file (if sourced from a file)
    source_path: Path | None = None

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """
        Load a presentation from the file at the given path.

        Currently assumes that the path points to a *.pptx file, no other file types can be handled.
        Will fail if other files are presented, possibly in curious ways.
        """
        prs = pptx.Presentation(str(path))
        return cls(
            slides=tuple(
                Slide.from_pptx_slide(pptx_slide) for pptx_slide in prs.slides
            ),
            source_path=path,
        )

    def to_typst_str(self) -> str:
        """
        Convert the presentation to a string in Typst format and return it.
        """
        raise NotImplementedError()  # TODO

    def to_file(self, path: Path) -> None:
        """
        Save a presentation to the given path.

        Will output the file in *.typ (Typst) format, no matter the extension.
        """
        raise NotImplementedError()  # TODO
