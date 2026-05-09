"""Inspection module: build and compare slide Intermediate Representations (IR).

Typical workflow
----------------
1. Parse a PPTX into a :class:`~.ir.PresentationIR`::

       from typstpresenter.inspection import pptx_to_presentation_ir
       pptx_ir = pptx_to_presentation_ir(Path("talk.pptx"))

2. Parse the compiled PDF into a :class:`~.ir.PresentationIR`::

       from typstpresenter.inspection import pdf_to_presentation_ir
       pdf_ir = pdf_to_presentation_ir(Path("talk.pdf"), skip_title_page=True)

3. Compare them::

       from typstpresenter.inspection import compare_presentations
       result = compare_presentations(pptx_ir, pdf_ir)
       assert result.is_match, result.summary()
"""

from .compare import (
    ElementComparisonResult,
    PresentationComparisonResult,
    SlideComparisonResult,
    compare_presentations,
    compare_slides,
)
from .ir import BoundingBox, ElementIR, PresentationIR, SlideIR
from .pdf_ir import pdf_page_to_ir, pdf_to_presentation_ir
from .pptx_ir import pptx_to_presentation_ir, slide_to_ir

__all__ = [
    # IR data structures
    "BoundingBox",
    "ElementIR",
    "SlideIR",
    "PresentationIR",
    # PPTX → IR
    "slide_to_ir",
    "pptx_to_presentation_ir",
    # PDF → IR
    "pdf_page_to_ir",
    "pdf_to_presentation_ir",
    # Comparison
    "compare_slides",
    "compare_presentations",
    "SlideComparisonResult",
    "PresentationComparisonResult",
    "ElementComparisonResult",
]
