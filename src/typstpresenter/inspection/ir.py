from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class BoundingBox:
    """Element position as fractions of slide dimensions (0.0–1.0)."""

    left: float
    top: float
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        return {
            "left": round(self.left, 4),
            "top": round(self.top, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
        }

    def overlaps(self, other: BoundingBox, tolerance: float = 0.05) -> bool:
        """Return True if the two boxes overlap within the given tolerance."""
        h_overlap = self.left < other.left + other.width + tolerance and other.left < self.left + self.width + tolerance
        v_overlap = self.top < other.top + other.height + tolerance and other.top < self.top + self.height + tolerance
        return h_overlap and v_overlap

    def center_distance(self, other: BoundingBox) -> float:
        """Euclidean distance between the centres of the two boxes (in relative units)."""
        cx1 = self.left + self.width / 2
        cy1 = self.top + self.height / 2
        cx2 = other.left + other.width / 2
        cy2 = other.top + other.height / 2
        return ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5


@dataclass
class ElementIR:
    """Intermediate representation of a single slide element."""

    kind: str  # "title" | "presentation_title" | "text" | "list" | "image"
    bounds: BoundingBox | None
    text: str | None = None          # flat text for title/text elements
    items: list[str] | None = None   # flat list of strings for list elements
    image_name: str | None = None    # filename hint for image elements

    def all_text_fragments(self) -> list[str]:
        """Return all non-empty text strings contained in this element."""
        result: list[str] = []
        if self.text:
            result.append(self.text.strip())
        if self.items:
            result.extend(item.strip() for item in self.items if item.strip())
        return result

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind}
        if self.bounds is not None:
            d["bounds"] = self.bounds.to_dict()
        if self.text is not None:
            d["text"] = self.text
        if self.items is not None:
            d["items"] = self.items
        if self.image_name is not None:
            d["image_name"] = self.image_name
        return d


@dataclass
class SlideIR:
    """Intermediate representation of a single slide or PDF page."""

    index: int
    title: str | None
    elements: list[ElementIR] = field(default_factory=list)

    def all_text_fragments(self) -> list[str]:
        """Return all non-empty text strings from all elements (title included)."""
        fragments: list[str] = []
        if self.title:
            fragments.append(self.title.strip())
        for element in self.elements:
            fragments.extend(element.all_text_fragments())
        return fragments

    def non_title_elements(self) -> list[ElementIR]:
        return [e for e in self.elements if e.kind not in ("title", "presentation_title")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "elements": [e.to_dict() for e in self.elements],
        }

    def to_yaml(self) -> str:
        return yaml.dump(
            self.to_dict(),
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


@dataclass
class PresentationIR:
    """Intermediate representation of a whole presentation or PDF document."""

    title: str | None
    slides: list[SlideIR] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "slides": [s.to_dict() for s in self.slides],
        }

    def to_yaml(self) -> str:
        return yaml.dump(
            self.to_dict(),
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
