"""
Method A: classic PDF-based verification.

The generated Typst document is compiled to PDF; PyMuPDF then extracts
text blocks, images and vector drawings with their bounding boxes. PDF
coordinates are already in pt with a top-left origin, so they map 1:1
onto the PPTX slide space as long as the emitted page size matches the
slide size.

PDF elements carry no identifiers, so matching against the PPTX ground
truth happens later by text similarity and spatial proximity (see
:mod:`compare`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from typstpresenter.verify.geometry import (
    BBox,
    DocGeometry,
    ElementGeometry,
    ElementKind,
    SlideGeometry,
)
from typstpresenter.verify.typst_tools import compile_pdf


@dataclass
class MethodAResult:
    geometry: DocGeometry
    compile_seconds: float
    extract_seconds: float


def _cluster_rects(rects: list[BBox], gap: float) -> list[BBox]:
    """
    Merge rectangles whose expanded bounds touch into clusters.

    Used to combine the many small vector paths of a diagram into one
    bounding box per connected drawing region.
    """
    clusters: list[BBox] = []
    for rect in rects:
        expanded = BBox(rect.x - gap, rect.y - gap, rect.w + 2 * gap, rect.h + 2 * gap)
        merged = rect
        remaining: list[BBox] = []
        for c in clusters:
            if expanded.intersection_area(BBox(c.x - gap, c.y - gap, c.w + 2 * gap, c.h + 2 * gap)) > 0:
                merged = merged.union(c)
            else:
                remaining.append(c)
        remaining.append(merged)
        clusters = remaining
    return clusters


def extract_pdf_geometry(
    pdf_path: Path | str,
    cluster_drawings: bool = False,
    drawing_gap: float = 6.0,
) -> DocGeometry:
    """
    Extract text blocks, images and vector drawings from every PDF page.

    Text granularity is PyMuPDF "blocks" (visually contiguous paragraphs),
    which corresponds well to PPTX text boxes. With ``cluster_drawings``
    the individual vector paths are merged into per-diagram regions;
    otherwise each path becomes one DRAWING element (needed to verify
    individual diagram shapes).
    """
    doc = fitz.open(str(pdf_path))
    result = DocGeometry(source=str(pdf_path))
    for page_index, page in enumerate(doc):
        sg = SlideGeometry(index=page_index, width=page.rect.width, height=page.rect.height)

        for block in page.get_text("dict")["blocks"]:
            if block["type"] == 1:  # image
                bbox = BBox(
                    block["bbox"][0],
                    block["bbox"][1],
                    block["bbox"][2] - block["bbox"][0],
                    block["bbox"][3] - block["bbox"][1],
                )
                sg.elements.append(ElementGeometry(kind=ElementKind.IMAGE, bbox=bbox))
                continue
            # Text at LINE granularity: PyMuPDF merges side-by-side boxes
            # sharing a baseline into one block, lines keep them apart.
            for line in block["lines"]:
                text = "".join(span["text"] for span in line["spans"]).strip()
                if not text:
                    continue
                bbox = BBox(
                    line["bbox"][0],
                    line["bbox"][1],
                    line["bbox"][2] - line["bbox"][0],
                    line["bbox"][3] - line["bbox"][1],
                )
                font_size = max(span["size"] for span in line["spans"])
                sg.elements.append(ElementGeometry(
                    kind=ElementKind.TEXT, bbox=bbox, text=text,
                    meta={"font_size": font_size},
                ))

        path_rects = []
        for drawing in page.get_drawings():
            r = drawing["rect"]
            if r.width <= 0 and r.height <= 0:
                continue
            path_rects.append(BBox(r.x0, r.y0, r.width, r.height))
        if cluster_drawings:
            path_rects = _cluster_rects(path_rects, gap=drawing_gap)
        for rect in path_rects:
            sg.elements.append(ElementGeometry(kind=ElementKind.DRAWING, bbox=rect))

        result.slides.append(sg)
    doc.close()
    return result


def run_method_a(typ_path: Path | str, cluster_drawings: bool = False) -> MethodAResult:
    """Compile the Typst file and extract PDF geometry, with timings."""
    import time

    compiled = compile_pdf(Path(typ_path))
    start = time.perf_counter()
    geometry = extract_pdf_geometry(compiled.value, cluster_drawings=cluster_drawings)
    return MethodAResult(
        geometry=geometry,
        compile_seconds=compiled.seconds,
        extract_seconds=time.perf_counter() - start,
    )
