"""Convert PDF pages (produced by typst) to the inspection IR via pdfplumber."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pdfplumber

from .ir import BoundingBox, ElementIR, PresentationIR, SlideIR


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rel_box(x0: float, top: float, x1: float, bottom: float, pw: float, ph: float) -> BoundingBox:
    return BoundingBox(
        left=x0 / pw,
        top=top / ph,
        width=(x1 - x0) / pw,
        height=(bottom - top) / ph,
    )


def _cluster_words(words: list[dict[str, Any]], page_height: float, y_tol: float = 0.02) -> list[list[dict[str, Any]]]:
    """Group words into text blocks by their vertical position.

    Words whose ``top`` values differ by less than ``y_tol`` (relative to
    page height) are considered to share the same text line.
    """
    if not words:
        return []

    # Sort top-to-bottom, then left-to-right within a line
    sorted_words = sorted(words, key=lambda w: (round(w["top"] / page_height / y_tol), w["x0"]))

    blocks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = [sorted_words[0]]

    for word in sorted_words[1:]:
        if abs(word["top"] - current[-1]["top"]) / page_height < y_tol:
            current.append(word)
        else:
            blocks.append(current)
            current = [word]
    blocks.append(current)
    return blocks


def _merge_nearby_blocks(
    blocks: list[list[dict[str, Any]]],
    page_height: float,
    gap_tol: float = 0.04,
) -> list[list[dict[str, Any]]]:
    """Merge consecutive lines that are visually close into single text blocks.

    This groups multi-line paragraphs / bullet-lists into one element so
    that the IR element count is closer to that of the source PPTX.
    """
    if not blocks:
        return []

    merged: list[list[dict[str, Any]]] = [blocks[0]]
    for block in blocks[1:]:
        prev_bottom = max(w["bottom"] for w in merged[-1])
        curr_top = min(w["top"] for w in block)
        gap = (curr_top - prev_bottom) / page_height
        if gap < gap_tol:
            merged[-1] = merged[-1] + block
        else:
            merged.append(block)
    return merged


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pdf_page_to_ir(page: Any, page_index: int) -> SlideIR:
    """Convert a single ``pdfplumber`` page to a :class:`SlideIR`.

    The first text block whose bounding box starts in the upper quarter of
    the page is labelled ``"title"``; all others become ``"text"`` blocks.
    Images found on the page are added as ``"image"`` elements.
    """
    pw: float = page.width
    ph: float = page.height

    words: list[dict[str, Any]] = page.extract_words(
        keep_blank_chars=False,
        x_tolerance=3,
        y_tolerance=3,
    )

    elements: list[ElementIR] = []
    title_text: str | None = None

    if words:
        line_blocks = _cluster_words(words, ph)
        merged_blocks = _merge_nearby_blocks(line_blocks, ph)

        for i, block in enumerate(merged_blocks):
            text = " ".join(w["text"] for w in block)
            x0 = min(w["x0"] for w in block)
            x1 = max(w["x1"] for w in block)
            top = min(w["top"] for w in block)
            bottom = max(w["bottom"] for w in block)
            bounds = _rel_box(x0, top, x1, bottom, pw, ph)

            # Heuristic: the very first block sitting in the top 25 % is the slide title
            if i == 0 and bounds.top < 0.25:
                title_text = text
                elements.append(ElementIR(kind="title", bounds=bounds, text=text))
            else:
                elements.append(ElementIR(kind="text", bounds=bounds, text=text))

    for j, img in enumerate(page.images):
        bounds = _rel_box(img["x0"], img["top"], img["x1"], img["bottom"], pw, ph)
        elements.append(ElementIR(
            kind="image",
            bounds=bounds,
            image_name=f"page_{page_index}_img_{j}",
        ))

    return SlideIR(index=page_index, title=title_text, elements=elements)


def pdf_to_presentation_ir(path: Path, skip_title_page: bool = False) -> PresentationIR:
    """Load a PDF and return a :class:`PresentationIR`.

    Parameters
    ----------
    path:
        Path to the PDF file.
    skip_title_page:
        When ``True`` the first PDF page is treated as a generated title
        page (as produced by ``diatypst``) and excluded from
        ``PresentationIR.slides``; its title is used for
        ``PresentationIR.title``.  When ``False`` (default) all pages
        become slides.
    """
    with pdfplumber.open(str(path)) as pdf:
        slide_irs = [pdf_page_to_ir(page, i) for i, page in enumerate(pdf.pages)]

    if not slide_irs:
        return PresentationIR(title=None, slides=[])

    if skip_title_page:
        title = slide_irs[0].title
        content_slides = [
            SlideIR(index=s.index - 1, title=s.title, elements=s.elements)
            for s in slide_irs[1:]
        ]
        return PresentationIR(title=title, slides=content_slides)

    title = slide_irs[0].title
    return PresentationIR(title=title, slides=slide_irs)
