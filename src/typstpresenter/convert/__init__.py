"""
PPTX -> Typst (Touying / CeTZ) conversion.

The package is split by concern:

- :mod:`emitter` -- orchestration: walks the slides, dispatches shapes,
  runs the measure-based calibration loop (autofit shrink, canvas drift).
- :mod:`textbody` -- text frames: styled runs, paragraphs, line metrics.
- :mod:`cetz` -- autoshapes and connectors as CeTZ drawing commands.
- :mod:`media` -- pictures and tables.
- :mod:`markup` -- Typst markup escaping and shared snippets.
- :mod:`faults` -- deliberate corruptions for verifier evaluation.
- :mod:`pptx_inherit` / :mod:`pptx_style` -- resolution of inherited
  placeholder properties and theme colors (shared with the verifier's
  ground-truth extraction).
"""

from typstpresenter.convert.emitter import emit_touying
from typstpresenter.convert.faults import Fault
from typstpresenter.convert.markup import escape_typst

__all__ = ["emit_touying", "Fault", "escape_typst"]
