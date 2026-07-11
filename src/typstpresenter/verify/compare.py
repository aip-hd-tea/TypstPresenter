"""
Compare Typst-side geometry against the PPTX ground truth.

Two matching strategies:

- id-based (Method B): probes carry the same element ids as the ground
  truth, matching is exact and trivial.
- content-based (Method A): PDF elements are anonymous; text blocks are
  assigned to ground-truth text boxes by text similarity, images and
  drawings by spatial overlap.

Detected issue kinds:

- ``missing``  -- ground-truth element has no counterpart on the Typst side
- ``extra``    -- Typst side shows an element with no ground-truth origin
- ``moved``    -- element center deviates beyond tolerance
- ``resized``  -- element box size deviates beyond tolerance
- ``overflow`` -- content does not fit its designated box
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from typstpresenter.verify.geometry import (
    BBox,
    DocGeometry,
    ElementGeometry,
    ElementKind,
)


@dataclass(frozen=True)
class Tolerances:
    # maximum allowed deviation of the element center, in pt
    pos_pt: float = 3.0
    # maximum allowed relative deviation of width/height
    size_frac: float = 0.05
    # content may exceed its box by this much (pt) before counting as overflow
    overflow_pt: float = 1.0
    # minimum text similarity for Method A text matching (0..1)
    text_similarity: float = 0.5
    # Method A: max distance between box top-left and text ink top-left, in
    # pt (text inset/rendering differences stay below this, gross moves not)
    anchor_pt: float = 15.0
    # slack for diagram node probes (labels sit inside shapes, layout noise
    # of Fletcher/CeTZ label placement is tolerated up to this)
    node_pos_pt: float = 10.0


@dataclass
class Issue:
    kind: str            # missing | extra | moved | resized | overflow
    slide: int           # 0-based slide index
    element_id: str | None
    detail: str
    magnitude_pt: float = 0.0

    def __str__(self) -> str:
        ident = self.element_id or "?"
        return f"[slide {self.slide + 1}] {self.kind:<8} {ident}: {self.detail}"


@dataclass
class MatchedPair:
    truth: ElementGeometry
    found_bbox: BBox
    slide: int
    center_offset_pt: float = 0.0
    iou: float = 0.0


@dataclass
class VerificationReport:
    source_truth: str
    source_typst: str
    issues: list[Issue] = field(default_factory=list)
    # findings that exist in the source presentation as well (e.g. text that
    # already overflows its box in PowerPoint): reported, but not errors
    warnings: list[Issue] = field(default_factory=list)
    matches: list[MatchedPair] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues

    def issues_of(self, kind: str) -> list[Issue]:
        return [i for i in self.issues if i.kind == kind]

    def summary(self) -> str:
        lines = [
            f"truth: {self.source_truth}",
            f"typst: {self.source_typst}",
            f"matched elements: {len(self.matches)}, issues: {len(self.issues)}, "
            f"warnings: {len(self.warnings)}",
        ]
        lines += [f"  {issue}" for issue in self.issues]
        lines += [f"  (warning) {issue}" for issue in self.warnings]
        if self.timings:
            timing = ", ".join(f"{k}={v:.3f}s" for k, v in self.timings.items())
            lines.append(f"timings: {timing}")
        return "\n".join(lines)


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).lower()


# bullet glyphs / numbering the Typst side prepends to list paragraphs but
# which are not part of the PPTX paragraph text
_LIST_PREFIX = re.compile(r"^[\s•◦▪‣·–—*-]+|^\d{1,2}[.)]\s+")


def _text_similarity(found: str, truth: str) -> float:
    found = _normalize_text(_LIST_PREFIX.sub("", found))
    truth = _normalize_text(truth)
    if not found or not truth:
        return 0.0
    # containment counts fully: PDF lines are fragments of one text box
    if found in truth or truth in found:
        return 1.0
    return difflib.SequenceMatcher(None, found, truth).ratio()


def _check_geometry(pair: MatchedPair, tol: Tolerances, issues: list[Issue],
                    check_size: bool = True) -> None:
    truth_bbox = pair.truth.bbox
    found = pair.found_bbox
    offset = truth_bbox.center_distance(found)
    pair.center_offset_pt = offset
    pair.iou = truth_bbox.iou(found)
    if offset > tol.pos_pt:
        issues.append(Issue(
            kind="moved", slide=pair.slide, element_id=pair.truth.id,
            detail=f"center off by {offset:.1f}pt "
                   f"(truth {truth_bbox.center}, found {found.center})",
            magnitude_pt=offset,
        ))
    if check_size and truth_bbox.w > 0 and truth_bbox.h > 0:
        dw = abs(found.w / truth_bbox.w - 1)
        dh = abs(found.h / truth_bbox.h - 1)
        if max(dw, dh) > tol.size_frac:
            issues.append(Issue(
                kind="resized", slide=pair.slide, element_id=pair.truth.id,
                detail=f"size {found.w:.0f}x{found.h:.0f}pt vs "
                       f"truth {truth_bbox.w:.0f}x{truth_bbox.h:.0f}pt",
                magnitude_pt=max(dw * truth_bbox.w, dh * truth_bbox.h),
            ))


# ---------------------------------------------------------------- Method B --

def compare_by_id(
    truth: DocGeometry,
    found: DocGeometry,
    overflows: dict[str, float] | None = None,
    tol: Tolerances = Tolerances(),
) -> VerificationReport:
    """Compare using shared element ids (Method B)."""
    report = VerificationReport(source_truth=truth.source, source_typst=found.source)

    found_by_id = {e.id: (s, e) for s, e in found.all_elements() if e.id}
    truth_ids = set()

    for slide_index, truth_el in truth.all_elements():
        truth_ids.add(truth_el.id)
        hit = found_by_id.get(truth_el.id)
        if hit is None:
            report.issues.append(Issue(
                kind="missing", slide=slide_index, element_id=truth_el.id,
                detail=f"no probe found ({truth_el.kind}, '{truth_el.text[:40]}')",
            ))
            continue
        found_slide, found_el = hit
        pair = MatchedPair(truth=truth_el, found_bbox=found_el.bbox, slide=slide_index)
        report.matches.append(pair)
        if found_slide != slide_index:
            report.issues.append(Issue(
                kind="moved", slide=slide_index, element_id=truth_el.id,
                detail=f"expected on slide {slide_index + 1}, found on {found_slide + 1}",
            ))
            continue
        is_node = found_el.meta.get("node_probe", False)
        if is_node:
            # node probes mark the label's top-left; verify position only,
            # against the truth box (the label lies inside the shape)
            if not _bbox_contains(truth_el.bbox, found_el.bbox, tol.node_pos_pt):
                report.issues.append(Issue(
                    kind="moved", slide=slide_index, element_id=truth_el.id,
                    detail=f"node label at ({found_el.bbox.x:.0f}, {found_el.bbox.y:.0f})pt "
                           f"outside truth box ({truth_el.bbox.x:.0f}, {truth_el.bbox.y:.0f}, "
                           f"{truth_el.bbox.w:.0f}x{truth_el.bbox.h:.0f})pt",
                ))
            continue
        _check_geometry(pair, tol, report.issues)
        overflow_pt = (overflows or {}).get(truth_el.id, 0.0)
        if overflow_pt > tol.overflow_pt:
            issue = Issue(
                kind="overflow", slide=slide_index, element_id=truth_el.id,
                detail=f"content exceeds box by {overflow_pt:.1f}pt vertically",
                magnitude_pt=overflow_pt,
            )
            # If the measured content would not even fit the *source* box,
            # the overflow already exists in PowerPoint (which only shrinks
            # text when autofit is on) -- report it as a warning, not as a
            # translation error.
            content_h = found_el.meta.get("content_h", 0.0)
            source_overflows = content_h > truth_el.bbox.h + tol.overflow_pt
            # "shrink" boxes are fitted by PowerPoint (and by our autofit
            # calibration), so overflow there is always a translation error;
            # "none"/"resize" boxes overflow in PowerPoint just the same
            if source_overflows and truth_el.meta.get("autofit", "none") != "shrink":
                report.warnings.append(issue)
            else:
                report.issues.append(issue)

    for slide_index, found_el in found.all_elements():
        if found_el.id not in truth_ids:
            report.issues.append(Issue(
                kind="extra", slide=slide_index, element_id=found_el.id,
                detail="probe without ground-truth element",
            ))
    return report


# ---------------------------------------------------------------- Method A --

def _bbox_contains(outer: BBox, inner: BBox, slack: float) -> bool:
    return (
        inner.x >= outer.x - slack
        and inner.y >= outer.y - slack
        and inner.x2 <= outer.x2 + slack
        and inner.y2 <= outer.y2 + slack
    )


def compare_spatial(
    truth: DocGeometry,
    found: DocGeometry,
    tol: Tolerances = Tolerances(),
) -> VerificationReport:
    """
    Compare anonymous PDF geometry (Method A) against the ground truth.

    Text: every PDF text block is assigned to the best-matching truth text
    box (text similarity, ties broken by distance); the union of assigned
    blocks is the found geometry of that box. The union must lie inside
    the truth box (else: moved/overflow), and blocks that match no truth
    element are reported as extra.

    Images: greedy best-IoU matching with full geometry check.

    Shapes/connectors: matched against vector drawings by IoU; drawings
    are also produced by text box decorations, so unmatched drawings are
    NOT reported as extra.
    """
    report = VerificationReport(source_truth=truth.source, source_typst=found.source)

    for truth_slide in truth.slides:
        found_slide = found.slide(truth_slide.index)
        if found_slide is None:
            for el in truth_slide.elements:
                report.issues.append(Issue(
                    kind="missing", slide=truth_slide.index, element_id=el.id,
                    detail="page missing in PDF",
                ))
            continue

        _match_text(truth_slide, found_slide, tol, report)
        _match_by_overlap(truth_slide, found_slide, ElementKind.IMAGE,
                          (ElementKind.IMAGE,), tol, report, check_size=True)
        used: set[int] = set()
        _match_by_overlap(truth_slide, found_slide, ElementKind.SHAPE,
                          (ElementKind.DRAWING,), tol, report, check_size=True,
                          used=used)
        _match_connectors(truth_slide, found_slide, tol, report, used)

    extra_pages = {s.index for s in found.slides} - {s.index for s in truth.slides}
    for index in sorted(extra_pages):
        report.issues.append(Issue(
            kind="extra", slide=index, element_id=None,
            detail="PDF page without corresponding slide",
        ))
    return report


def _match_text(truth_slide, found_slide, tol: Tolerances, report: VerificationReport) -> None:
    # Shape labels (e.g. flowchart node texts) are also rendered as PDF text,
    # so any truth element with text is a valid target.
    truth_texts = [e for e in truth_slide.elements if e.text]
    pdf_lines = [e for e in found_slide.elements if e.kind == ElementKind.TEXT]

    assigned: dict[int, list[ElementGeometry]] = {i: [] for i in range(len(truth_texts))}
    for line in pdf_lines:
        # rank by similarity; ties (e.g. a short table cell whose text also
        # occurs in a long body paragraph) are broken by geometric
        # containment first, then proximity
        best_index, best_key = None, None
        for i, truth_el in enumerate(truth_texts):
            score = _text_similarity(line.text, truth_el.text)
            if score <= 0.0:
                continue
            lx, ly = line.bbox.center
            inside = (truth_el.bbox.x <= lx <= truth_el.bbox.x2
                      and truth_el.bbox.y <= ly <= truth_el.bbox.y2)
            key = (round(score, 3), inside, -truth_el.bbox.center_distance(line.bbox))
            if best_key is None or key > best_key:
                best_index, best_key = i, key
        if best_index is not None and best_key[0] >= tol.text_similarity:
            assigned[best_index].append(line)
        else:
            report.issues.append(Issue(
                kind="extra", slide=found_slide.index, element_id=None,
                detail=f"text not in ground truth: '{line.text[:50]}'",
            ))

    for i, truth_el in enumerate(truth_texts):
        lines = assigned[i]
        if not lines:
            report.issues.append(Issue(
                kind="missing", slide=truth_slide.index, element_id=truth_el.id,
                detail=f"text not found: '{truth_el.text[:40]}'",
            ))
            continue
        union = lines[0].bbox
        for pdf_line in lines[1:]:
            union = union.union(pdf_line.bbox)
        pair = MatchedPair(truth=truth_el, found_bbox=union, slide=truth_slide.index)
        pair.center_offset_pt = truth_el.bbox.center_distance(union)
        pair.iou = truth_el.bbox.iou(union)
        report.matches.append(pair)
        if truth_el.kind != ElementKind.TEXT:
            # shape label: geometry is checked via the shape itself
            continue
        # PDF line boxes span ascender..descender and thus overshoot the
        # layout box by a font-dependent margin; allow for it.
        font_size = max(pdf_line.meta.get("font_size", 12.0) for pdf_line in lines)
        slack = tol.pos_pt + 0.3 * font_size
        # The ink of the text must lie inside the designated box.
        # Ink outside the box means misplacement or overflowing content.
        if not _bbox_contains(truth_el.bbox, union, slack):
            below = union.y2 - truth_el.bbox.y2
            kind = "overflow" if below > slack and union.y >= truth_el.bbox.y - slack else "moved"
            issue = Issue(
                kind=kind, slide=truth_slide.index, element_id=truth_el.id,
                detail=f"text ink ({union.x:.0f}, {union.y:.0f}, {union.w:.0f}x{union.h:.0f})pt "
                       f"escapes box ({truth_el.bbox.x:.0f}, {truth_el.bbox.y:.0f}, "
                       f"{truth_el.bbox.w:.0f}x{truth_el.bbox.h:.0f})pt",
                magnitude_pt=max(below, 0.0),
            )
            # without shrink-autofit, PowerPoint would overflow this box just
            # the same; ink alone cannot distinguish source from translation
            # overflow, so treat it as a warning
            if kind == "overflow" and truth_el.meta.get("autofit", "none") != "shrink":
                report.warnings.append(issue)
            else:
                report.issues.append(issue)
            continue
        # Inside a (possibly much larger) box, gross shifts of top-left
        # aligned text are still detectable via the ink anchor. Centered or
        # bottom-anchored text legitimately starts away from the corner.
        if not truth_el.meta.get("align_left_top", True):
            continue
        dx = abs(union.x - truth_el.bbox.x)
        dy = abs(union.y - truth_el.bbox.y)
        if max(dx, dy) > tol.anchor_pt:
            report.issues.append(Issue(
                kind="moved", slide=truth_slide.index, element_id=truth_el.id,
                detail=f"text ink starts at ({union.x:.0f}, {union.y:.0f})pt, "
                       f"box at ({truth_el.bbox.x:.0f}, {truth_el.bbox.y:.0f})pt",
                magnitude_pt=max(dx, dy),
            ))


def _match_by_overlap(truth_slide, found_slide, truth_kind: ElementKind,
                      found_kinds: tuple[ElementKind, ...], tol: Tolerances,
                      report: VerificationReport, check_size: bool,
                      used: set[int] | None = None) -> None:
    truth_els = [e for e in truth_slide.elements if e.kind == truth_kind]
    candidates = [e for e in found_slide.elements if e.kind in found_kinds]
    if not truth_els:
        if truth_kind == ElementKind.IMAGE:
            for c in candidates:
                report.issues.append(Issue(
                    kind="extra", slide=found_slide.index, element_id=None,
                    detail=f"unexpected {c.kind} at ({c.bbox.x:.0f}, {c.bbox.y:.0f})pt",
                ))
        return

    used = set() if used is None else used
    for truth_el in truth_els:
        if truth_el.meta.get("invisible"):
            continue  # no fill, no outline -> nothing to find in the PDF
        if truth_el.meta.get("unrenderable"):
            continue  # image format typst cannot render (placeholder emitted)
        best_index, best_iou = None, 0.0
        for j, cand in enumerate(candidates):
            if j in used:
                continue
            iou = truth_el.bbox.iou(cand.bbox)
            if iou > best_iou:
                best_index, best_iou = j, iou
        if best_index is None or best_iou <= 0.0:
            report.issues.append(Issue(
                kind="missing", slide=truth_slide.index, element_id=truth_el.id,
                detail=f"{truth_kind} not found near "
                       f"({truth_el.bbox.x:.0f}, {truth_el.bbox.y:.0f})pt",
            ))
            continue
        used.add(best_index)
        pair = MatchedPair(truth=truth_el, found_bbox=candidates[best_index].bbox,
                           slide=truth_slide.index)
        report.matches.append(pair)
        _check_geometry(pair, tol, report.issues, check_size=check_size)


def _match_connectors(truth_slide, found_slide, tol: Tolerances,
                      report: VerificationReport, used: set[int]) -> None:
    """
    Connectors need special handling: their bboxes can have zero area
    (horizontal/vertical lines), and PDF rendering splits them into line
    body plus arrowhead. All unused drawings inside the (slightly grown)
    truth bbox are collected; their union must cover most of the
    connector's extent.

    ``used`` indexes into the DRAWING elements in slide order and is
    shared with the shape matching to avoid double assignment.
    """
    truth_els = [e for e in truth_slide.elements if e.kind == ElementKind.CONNECTOR]
    drawings = [e for e in found_slide.elements if e.kind == ElementKind.DRAWING]
    slack = tol.pos_pt + 6.0  # stroke width and arrowhead spread

    for truth_el in truth_els:
        grown = BBox(
            truth_el.bbox.x - slack, truth_el.bbox.y - slack,
            truth_el.bbox.w + 2 * slack, truth_el.bbox.h + 2 * slack,
        )
        members = [
            j for j, d in enumerate(drawings)
            if j not in used and _bbox_contains(grown, d.bbox, 0.0)
        ]
        if not members:
            report.issues.append(Issue(
                kind="missing", slide=truth_slide.index, element_id=truth_el.id,
                detail=f"connector not found near "
                       f"({truth_el.bbox.x:.0f}, {truth_el.bbox.y:.0f})pt",
            ))
            continue
        used.update(members)
        union = drawings[members[0]].bbox
        for j in members[1:]:
            union = union.union(drawings[j].bbox)
        pair = MatchedPair(truth=truth_el, found_bbox=union, slide=truth_slide.index)
        pair.center_offset_pt = truth_el.bbox.center_distance(union)
        pair.iou = truth_el.bbox.iou(union)
        report.matches.append(pair)
        extent_truth = max(truth_el.bbox.w, truth_el.bbox.h)
        extent_found = max(union.w, union.h)
        if extent_truth > 0 and extent_found / extent_truth < 0.75:
            report.issues.append(Issue(
                kind="resized", slide=truth_slide.index, element_id=truth_el.id,
                detail=f"connector covers only {extent_found:.0f}pt of "
                       f"{extent_truth:.0f}pt",
            ))
