"""Resolve a shape's SVG presentation attributes from PPTX styling.

Thin wrapper over typstpresenter.convert.pptx_style (theme + explicit
colors); adds the DrawingML path fill variants (darken/lighten) used by
some presets (e.g. can, bevel).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pptx.enum.dml import MSO_FILL
from pptx.oxml.ns import qn

from typstpresenter.convert.pptx_style import (
    shape_fill_rgb,
    shape_line_rgb,
    shape_line_width_pt,
)


@dataclass
class GradientFill:
    """Linear gradient: stops as (position 0..1, "#RRGGBB")."""

    stops: list[tuple[float, str]] = field(default_factory=list)
    angle_deg: float = 0.0  # clockwise from +x (y-down), PowerPoint convention


@dataclass
class ShapeStyle:
    fill: str | GradientFill | None  # "#RRGGBB", gradient, or None (no fill)
    stroke: str | None
    stroke_width_pt: float
    dash: tuple[float, ...] | None = None  # stroke-width multiples

    @property
    def solid_fill(self) -> str | None:
        """Representative solid color (first gradient stop for gradients)."""
        if isinstance(self.fill, GradientFill):
            return self.fill.stops[0][1] if self.fill.stops else None
        return self.fill


def _hex(rgb: str | None) -> str | None:
    return f"#{rgb}" if rgb else None


# a:prstDash val -> dash pattern in stroke-width multiples
_DASH_PATTERNS = {
    "dash": (4, 3),
    "lgDash": (8, 3),
    "dot": (1, 3),
    "sysDash": (3, 1),
    "sysDot": (1, 1),
    "dashDot": (4, 3, 1, 3),
    "lgDashDot": (8, 3, 1, 3),
    "lgDashDotDot": (8, 3, 1, 3, 1, 3),
    "sysDashDot": (3, 1, 1, 1),
    "sysDashDotDot": (3, 1, 1, 1, 1, 1),
}


def _gradient_of(shape) -> GradientFill | None:
    try:
        if shape.fill.type != MSO_FILL.GRADIENT:
            return None
    except (AttributeError, TypeError):
        return None
    grad = GradientFill()
    try:
        for stop in shape.fill.gradient_stops:
            grad.stops.append((stop.position, f"#{stop.color.rgb}"))
    except (AttributeError, ValueError, TypeError):
        return None
    try:
        grad.angle_deg = shape.fill.gradient_angle
    except (AttributeError, ValueError, TypeError):
        grad.angle_deg = 90.0  # PowerPoint default: top-to-bottom
    grad.stops.sort(key=lambda s: s[0])
    return grad if grad.stops else None


def _dash_of(shape) -> tuple[float, ...] | None:
    sp_pr = shape.element.find(qn("p:spPr"))
    ln = sp_pr.find(qn("a:ln")) if sp_pr is not None else None
    dash = ln.find(qn("a:prstDash")) if ln is not None else None
    if dash is None:
        return None
    return _DASH_PATTERNS.get(dash.get("val"))


def resolve_style(shape) -> ShapeStyle:
    fill: str | GradientFill | None = _gradient_of(shape)
    if fill is None:
        try:
            fill = _hex(shape_fill_rgb(shape))
        except (AttributeError, TypeError):
            fill = None  # connectors have no fill
    return ShapeStyle(
        fill=fill,
        stroke=_hex(shape_line_rgb(shape)),
        stroke_width_pt=shape_line_width_pt(shape),
        dash=_dash_of(shape),
    )


def _blend(rgb: str, factor: float, toward: int) -> str:
    """Blend #RRGGBB toward black (toward=0) or white (toward=255)."""
    r, g, b = (int(rgb[i : i + 2], 16) for i in (1, 3, 5))
    mix = lambda c: round(c + (toward - c) * factor)  # noqa: E731
    return f"#{mix(r):02X}{mix(g):02X}{mix(b):02X}"


def path_fill_color(variant: str, base: str | None) -> str | None:
    """Fill color for one DrawingML path given its fill variant.

    `base` must already be a solid color (gradients are referenced by
    url(#id) in the writer and skip this function's variants).
    """
    if variant == "none" or base is None:
        return None
    if variant == "norm":
        return base
    if variant == "darken":
        return _blend(base, 0.5, 0)
    if variant == "darkenLess":
        return _blend(base, 0.25, 0)
    if variant == "lighten":
        return _blend(base, 0.5, 255)
    if variant == "lightenLess":
        return _blend(base, 0.25, 255)
    return base
