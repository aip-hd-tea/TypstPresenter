"""PPTX diagram → SVG translation (isolated package, see docs/diagram-to-svg-plan.md).

Import policy: this package may import read-only helpers from
typstpresenter.verify.pptx_geometry and typstpresenter.convert.pptx_style,
but nothing outside it may depend on it except the flow-emitter dispatch
and asset writing.
"""

from typstpresenter.diagram2svg.convert import shapes_to_svg, slide_to_svg

__all__ = ["shapes_to_svg", "slide_to_svg"]
