"""
Shared geometry model for verification.

All coordinates are in typographic points (pt) within the slide/page
coordinate system, origin at the top-left corner. PPTX EMU values are
converted with 1 pt = 12700 EMU; PDF and Typst already use pt natively,
so the mapping between the three worlds is the identity once the emitted
page size equals the PPTX slide size.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

EMU_PER_PT = 12700.0


class ElementKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    SHAPE = "shape"       # autoshape (rect, ellipse, ...)
    CONNECTOR = "connector"
    GROUP = "group"
    DRAWING = "drawing"   # vector path extracted from a PDF
    OTHER = "other"


@dataclass(frozen=True)
class BBox:
    """Axis-aligned bounding box in pt, origin top-left."""
    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    @property
    def area(self) -> float:
        return max(self.w, 0.0) * max(self.h, 0.0)

    def union(self, other: BBox) -> BBox:
        x1 = min(self.x, other.x)
        y1 = min(self.y, other.y)
        x2 = max(self.x2, other.x2)
        y2 = max(self.y2, other.y2)
        return BBox(x1, y1, x2 - x1, y2 - y1)

    def intersection_area(self, other: BBox) -> float:
        w = min(self.x2, other.x2) - max(self.x, other.x)
        h = min(self.y2, other.y2) - max(self.y, other.y)
        return max(w, 0.0) * max(h, 0.0)

    def iou(self, other: BBox) -> float:
        inter = self.intersection_area(other)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def center_distance(self, other: BBox) -> float:
        cx1, cy1 = self.center
        cx2, cy2 = other.center
        return ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5


@dataclass
class ElementGeometry:
    """One visual element on a slide (text box, image, shape, ...)."""
    kind: ElementKind
    bbox: BBox
    # Stable identifier; PPTX side uses "s{slide}-e{shape_id}", introspection
    # probes carry the same id, PDF extraction leaves it None (matched later).
    id: str | None = None
    # Plain text content (for text elements), used for matching in Method A.
    text: str = ""
    # Extra per-method data, e.g. measured content size or overflow flags.
    meta: dict = field(default_factory=dict)


@dataclass
class SlideGeometry:
    index: int  # 0-based slide/page index
    width: float
    height: float
    elements: list[ElementGeometry] = field(default_factory=list)


@dataclass
class DocGeometry:
    """Geometry of a whole presentation (from PPTX, PDF or introspection)."""
    slides: list[SlideGeometry] = field(default_factory=list)
    source: str = ""

    def slide(self, index: int) -> SlideGeometry | None:
        for s in self.slides:
            if s.index == index:
                return s
        return None

    def all_elements(self) -> list[tuple[int, ElementGeometry]]:
        return [(s.index, e) for s in self.slides for e in s.elements]
