"""Compare PPTX-derived and PDF-derived slide IRs.

The comparison is text-centred: we check that every text fragment found in
the source (PPTX) slide also appears in the target (PDF) slide.  Position
matching is secondary and controlled by a tolerance parameter.

All public functions return plain dataclasses whose ``is_match`` property
can be used directly in test assertions.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from .ir import BoundingBox, ElementIR, PresentationIR, SlideIR


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lower-case, collapse whitespace."""
    return " ".join(text.lower().split())


def _text_similarity(a: str, b: str) -> float:
    """Return a similarity ratio in [0, 1] between two strings."""
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _fragment_present(fragment: str, target_fragments: list[str], threshold: float) -> bool:
    """Return True if *fragment* can be found (above *threshold*) in any target string."""
    n = _norm(fragment)
    if not n:
        return True
    for t in target_fragments:
        nt = _norm(t)
        # Exact substring match first (fast path)
        if n in nt or nt in n:
            return True
        # Fuzzy similarity fallback
        if _text_similarity(n, nt) >= threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# Per-element comparison
# ---------------------------------------------------------------------------

@dataclass
class ElementComparisonResult:
    source: ElementIR
    target: ElementIR | None
    kind_match: bool
    text_match: bool
    text_similarity: float          # 0.0–1.0; 1.0 when both have no text
    position_match: bool            # True when bounds overlap or no bounds available

    @property
    def is_match(self) -> bool:
        return self.text_match and self.position_match


# ---------------------------------------------------------------------------
# Per-slide comparison
# ---------------------------------------------------------------------------

@dataclass
class SlideComparisonResult:
    source_index: int
    target_index: int
    title_match: bool
    title_similarity: float         # 0.0–1.0
    text_coverage: float            # fraction of source fragments found in target
    missing_fragments: list[str]    # source text not found in target
    element_count: tuple[int, int]  # (source, target)
    element_results: list[ElementComparisonResult] = field(default_factory=list)

    @property
    def is_match(self) -> bool:
        return self.title_match and self.text_coverage >= 0.9

    def summary(self) -> str:
        lines = [
            f"Slide {self.source_index} vs {self.target_index}",
            f"  title_match:    {self.title_match} (similarity {self.title_similarity:.2f})",
            f"  text_coverage:  {self.text_coverage:.2f}",
            f"  elements:       source={self.element_count[0]}  target={self.element_count[1]}",
        ]
        if self.missing_fragments:
            lines.append("  missing text:")
            for f in self.missing_fragments:
                lines.append(f"    - {f!r}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-presentation comparison
# ---------------------------------------------------------------------------

@dataclass
class PresentationComparisonResult:
    source_title: str | None
    target_title: str | None
    title_match: bool
    slide_count: tuple[int, int]    # (source, target)
    slide_results: list[SlideComparisonResult] = field(default_factory=list)

    @property
    def slide_count_match(self) -> bool:
        return self.slide_count[0] == self.slide_count[1]

    @property
    def is_match(self) -> bool:
        return (
            self.title_match
            and self.slide_count_match
            and all(r.is_match for r in self.slide_results)
        )

    def summary(self) -> str:
        lines = [
            "Presentation comparison",
            f"  title_match:  {self.title_match}",
            f"  slides:       source={self.slide_count[0]}  target={self.slide_count[1]}",
        ]
        for r in self.slide_results:
            lines.append(r.summary())
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core comparison logic
# ---------------------------------------------------------------------------

def _match_element(
    source: ElementIR,
    target_elements: list[ElementIR],
    position_tolerance: float,
    text_threshold: float,
) -> ElementComparisonResult:
    """Find the best-matching target element for *source*."""
    best: ElementIR | None = None
    best_score = -1.0

    src_fragments = source.all_text_fragments()
    src_text = " ".join(src_fragments)

    for tgt in target_elements:
        tgt_fragments = tgt.all_text_fragments()
        tgt_text = " ".join(tgt_fragments)

        # Combined similarity: text + optional position proximity
        txt_sim = _text_similarity(src_text, tgt_text) if (src_text or tgt_text) else 1.0
        pos_score = 0.0
        if source.bounds and tgt.bounds:
            dist = source.bounds.center_distance(tgt.bounds)
            pos_score = max(0.0, 1.0 - dist * 4)  # 0 at dist ≥ 0.25

        score = 0.7 * txt_sim + 0.3 * pos_score
        if score > best_score:
            best_score = score
            best = tgt

    if best is None:
        return ElementComparisonResult(
            source=source,
            target=None,
            kind_match=False,
            text_match=False,
            text_similarity=0.0,
            position_match=False,
        )

    tgt_fragments = best.all_text_fragments()
    tgt_text = " ".join(tgt_fragments)
    txt_sim = _text_similarity(src_text, tgt_text) if (src_text or tgt_text) else 1.0

    pos_match = True
    if source.bounds and best.bounds:
        pos_match = source.bounds.overlaps(best.bounds, tolerance=position_tolerance)

    return ElementComparisonResult(
        source=source,
        target=best,
        kind_match=source.kind == best.kind,
        text_match=txt_sim >= text_threshold or not src_text,
        text_similarity=txt_sim,
        position_match=pos_match,
    )


def compare_slides(
    source: SlideIR,
    target: SlideIR,
    *,
    position_tolerance: float = 0.10,
    text_threshold: float = 0.80,
) -> SlideComparisonResult:
    """Compare a source (PPTX) slide IR against a target (PDF) slide IR.

    Parameters
    ----------
    source:
        The reference slide (typically from the PPTX).
    target:
        The rendered slide (typically from the PDF).
    position_tolerance:
        Maximum relative distance (0–1) for two element positions to be
        considered matching.
    text_threshold:
        Minimum similarity ratio (0–1) for two text strings to count as a
        match.
    """
    # --- Title comparison ---
    src_title = _norm(source.title or "")
    tgt_title = _norm(target.title or "")
    title_sim = _text_similarity(src_title, tgt_title) if (src_title or tgt_title) else 1.0
    title_match = bool(src_title and tgt_title and title_sim >= text_threshold) or (not src_title and not tgt_title)

    # --- Text coverage ---
    src_fragments = source.all_text_fragments()
    tgt_fragments = target.all_text_fragments()

    missing: list[str] = []
    for frag in src_fragments:
        if not _fragment_present(frag, tgt_fragments, text_threshold):
            missing.append(frag)

    coverage = 1.0 - len(missing) / len(src_fragments) if src_fragments else 1.0

    # --- Per-element matching ---
    element_results = [
        _match_element(e, target.elements, position_tolerance, text_threshold)
        for e in source.elements
    ]

    return SlideComparisonResult(
        source_index=source.index,
        target_index=target.index,
        title_match=title_match,
        title_similarity=title_sim,
        text_coverage=coverage,
        missing_fragments=missing,
        element_count=(len(source.elements), len(target.elements)),
        element_results=element_results,
    )


def compare_presentations(
    source: PresentationIR,
    target: PresentationIR,
    *,
    target_slide_offset: int = 0,
    position_tolerance: float = 0.10,
    text_threshold: float = 0.80,
) -> PresentationComparisonResult:
    """Compare a PPTX-derived :class:`PresentationIR` to a PDF-derived one.

    Parameters
    ----------
    source:
        The reference presentation IR (from the PPTX).
    target:
        The rendered presentation IR (from the PDF).
    target_slide_offset:
        Index into ``target.slides`` that corresponds to ``source.slides[0]``.
        Use ``1`` when the PDF has a generated title page as page 0 (diatypst
        default) and you are using ``skip_title_page=False``.
    position_tolerance / text_threshold:
        Forwarded to :func:`compare_slides`.
    """
    src_title = _norm(source.title or "")
    tgt_title = _norm(target.title or "")
    title_sim = _text_similarity(src_title, tgt_title) if (src_title or tgt_title) else 1.0
    title_match = bool(src_title and tgt_title and title_sim >= text_threshold) or (not src_title and not tgt_title)

    slide_results: list[SlideComparisonResult] = []
    target_slides = target.slides[target_slide_offset:]

    for i, src_slide in enumerate(source.slides):
        if i < len(target_slides):
            tgt_slide = target_slides[i]
        else:
            # No corresponding target slide: create an empty placeholder
            tgt_slide = SlideIR(index=-1, title=None, elements=[])

        slide_results.append(
            compare_slides(
                src_slide,
                tgt_slide,
                position_tolerance=position_tolerance,
                text_threshold=text_threshold,
            )
        )

    return PresentationComparisonResult(
        source_title=source.title,
        target_title=target.title,
        title_match=title_match,
        slide_count=(len(source.slides), len(target_slides)),
        slide_results=slide_results,
    )
