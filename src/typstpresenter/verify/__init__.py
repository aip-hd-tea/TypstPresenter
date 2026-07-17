"""
Verification tools for PPTX -> Typst translation accuracy.

Two independent implementations extract element geometry from the Typst side
and compare it against the PPTX ground truth:

- Method A (:mod:`method_a`): compile Typst to PDF, extract text/image/drawing
  bounding boxes with PyMuPDF.
- Method B (:mod:`method_b`): instrument the Typst source with introspection
  probes (metadata + here().position() + measure) and read them back via
  ``typst query`` -- no PDF export needed.

Both produce a :class:`~typstpresenter.verify.geometry.DocGeometry` that is
compared by :mod:`~typstpresenter.verify.compare`.

Human-editable flow-mode output (``emit_touying(minimal=True)``) carries no
probes and deliberately deviates from the source coordinates; it is checked
by Method S (:mod:`method_s`): compiles, one page per slide, no ink outside
the page, no text/image collisions beyond what the source itself contains,
plus source-simplicity metrics.
"""
