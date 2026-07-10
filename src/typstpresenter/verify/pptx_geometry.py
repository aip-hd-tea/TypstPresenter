"""
Extract element geometry (ground truth) from a PPTX file via python-pptx.
"""

from __future__ import annotations

from pathlib import Path

import pptx
from pptx.enum.shapes import MSO_SHAPE_TYPE

from typstpresenter.verify.geometry import (
    EMU_PER_PT,
    BBox,
    DocGeometry,
    ElementGeometry,
    ElementKind,
    SlideGeometry,
)


def element_id(slide_index: int, shape_id: int) -> str:
    """Stable element id shared between PPTX ground truth and Typst probes."""
    return f"s{slide_index}-e{shape_id}"


def _kind_of(shape) -> ElementKind:
    st = shape.shape_type
    if st == MSO_SHAPE_TYPE.PICTURE:
        return ElementKind.IMAGE
    if st == MSO_SHAPE_TYPE.GROUP:
        return ElementKind.GROUP
    if st in (MSO_SHAPE_TYPE.AUTO_SHAPE,):
        return ElementKind.SHAPE
    if st in (MSO_SHAPE_TYPE.LINE,) or shape.shape_type is None and shape.element.tag.endswith("cxnSp"):
        return ElementKind.CONNECTOR
    if shape.has_text_frame:
        return ElementKind.TEXT
    return ElementKind.OTHER


def _shape_text(shape) -> str:
    if not shape.has_text_frame:
        return ""
    return "\n".join(p.text for p in shape.text_frame.paragraphs).strip()


def _bbox_of(shape) -> BBox | None:
    if shape.left is None or shape.top is None:
        return None
    return BBox(
        x=shape.left / EMU_PER_PT,
        y=shape.top / EMU_PER_PT,
        w=(shape.width or 0) / EMU_PER_PT,
        h=(shape.height or 0) / EMU_PER_PT,
    )


def extract_pptx_geometry(path: Path | str) -> DocGeometry:
    """
    Read a *.pptx file and return the geometry of all placed shapes.

    Shapes without a position (e.g. unplaced placeholders) are skipped.
    Group shapes are recorded as a single element (no recursion into
    children, whose coordinates live in a scaled group space).
    """
    prs = pptx.Presentation(str(path))
    slide_w = prs.slide_width / EMU_PER_PT
    slide_h = prs.slide_height / EMU_PER_PT

    doc = DocGeometry(source=str(path))
    for slide_index, slide in enumerate(prs.slides):
        sg = SlideGeometry(index=slide_index, width=slide_w, height=slide_h)
        for shape in slide.shapes:
            bbox = _bbox_of(shape)
            if bbox is None:
                continue
            kind = _kind_of(shape)
            text = _shape_text(shape)
            # Empty text boxes carry no visual content to verify.
            if kind == ElementKind.TEXT and not text:
                continue
            sg.elements.append(
                ElementGeometry(
                    kind=kind,
                    bbox=bbox,
                    id=element_id(slide_index, shape.shape_id),
                    text=text,
                    meta={"shape_name": shape.name},
                )
            )
        doc.slides.append(sg)
    return doc
