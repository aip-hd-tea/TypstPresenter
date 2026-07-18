"""Assemble SVG documents from evaluated shape geometry.

All coordinates are pt (1 SVG user unit = 1 pt); the viewBox spans the
requested slide/cluster region so the document embeds 1:1 in Typst via
``#image(..., width: <region w>pt)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import math

from typstpresenter.diagram2svg.presets import EvaluatedPath, Segment
from typstpresenter.diagram2svg.style import GradientFill, ShapeStyle, path_fill_color

_EMU_PER_PT = 12700.0


def _fmt(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def path_data(segments: list[Segment], sx: float, sy: float) -> str:
    """Segments in EMU path space → SVG `d` in pt, shape-local coords."""
    kx = sx / _EMU_PER_PT
    ky = sy / _EMU_PER_PT
    parts: list[str] = []
    for seg in segments:
        op = seg[0]
        if op in ("M", "L"):
            parts.append(f"{op}{_fmt(seg[1] * kx)} {_fmt(seg[2] * ky)}")
        elif op == "C":
            x1, y1, x2, y2, x, y = seg[1:]
            parts.append(
                f"C{_fmt(x1 * kx)} {_fmt(y1 * ky)} {_fmt(x2 * kx)} {_fmt(y2 * ky)} "
                f"{_fmt(x * kx)} {_fmt(y * ky)}"
            )
        elif op == "Q":
            x1, y1, x, y = seg[1:]
            parts.append(f"Q{_fmt(x1 * kx)} {_fmt(y1 * ky)} {_fmt(x * kx)} {_fmt(y * ky)}")
        elif op == "A":
            rx, ry, sweep, x, y = seg[1:]
            parts.append(
                f"A{_fmt(rx * kx)} {_fmt(ry * ky)} 0 0 {sweep} {_fmt(x * kx)} {_fmt(y * ky)}"
            )
        elif op == "Z":
            parts.append("Z")
    return " ".join(parts)


# marker geometry templates in a 6x6 box, stroke-width units.
# "end" variants point +x (path direction); "start" variants are mirrored.
_MARKER_PATHS = {
    ("triangle", "end"): ('<path d="M0 0 L6 3 L0 6 Z" fill="{c}"/>', 5.5),
    ("triangle", "start"): ('<path d="M6 0 L0 3 L6 6 Z" fill="{c}"/>', 0.5),
    ("stealth", "end"): ('<path d="M0 0 L6 3 L0 6 L1.5 3 Z" fill="{c}"/>', 5.5),
    ("stealth", "start"): ('<path d="M6 0 L0 3 L6 6 L4.5 3 Z" fill="{c}"/>', 0.5),
    ("arrow", "end"): (
        '<path d="M0.5 0.5 L5.5 3 L0.5 5.5" fill="none" stroke="{c}" stroke-width="1"/>', 5.5),
    ("arrow", "start"): (
        '<path d="M5.5 0.5 L0.5 3 L5.5 5.5" fill="none" stroke="{c}" stroke-width="1"/>', 0.5),
    ("oval", "end"): ('<ellipse cx="3" cy="3" rx="2.2" ry="2.2" fill="{c}"/>', 3.0),
    ("oval", "start"): ('<ellipse cx="3" cy="3" rx="2.2" ry="2.2" fill="{c}"/>', 3.0),
    ("diamond", "end"): ('<path d="M3 0 L6 3 L3 6 L0 3 Z" fill="{c}"/>', 3.0),
    ("diamond", "start"): ('<path d="M3 0 L6 3 L3 6 L0 3 Z" fill="{c}"/>', 3.0),
}

_MARKER_SCALE = {"sm": 0.75, "med": 1.0, "lg": 1.5}


@dataclass
class ArrowEnd:
    kind: str  # triangle | stealth | arrow | oval | diamond
    w: str = "med"
    length: str = "med"


@dataclass
class SvgShape:
    """One translated shape: positioned geometry + style."""

    id: str
    x_pt: float
    y_pt: float
    w_pt: float
    h_pt: float
    paths: list[EvaluatedPath]
    style: ShapeStyle
    rot_deg: float = 0.0
    flip_h: bool = False
    flip_v: bool = False
    head: ArrowEnd | None = None  # marker at path start
    tail: ArrowEnd | None = None  # marker at path end
    text_elements: list[str] = field(default_factory=list)

    def transform(self) -> str:
        t = [f"translate({_fmt(self.x_pt)} {_fmt(self.y_pt)})"]
        if self.rot_deg or self.flip_h or self.flip_v:
            cx, cy = self.w_pt / 2, self.h_pt / 2
            t.append(f"translate({_fmt(cx)} {_fmt(cy)})")
            if self.rot_deg:
                t.append(f"rotate({_fmt(self.rot_deg)})")
            if self.flip_h or self.flip_v:
                t.append(f"scale({-1 if self.flip_h else 1} {-1 if self.flip_v else 1})")
            t.append(f"translate({_fmt(-cx)} {_fmt(-cy)})")
        return " ".join(t)


@dataclass
class SvgDocument:
    """Region in absolute slide pt coordinates; shapes in z-order.

    Entries may also be raw SVG fragment strings (pre-rendered elements
    such as embedded raster images), painted at their list position.
    """

    x: float
    y: float
    w: float
    h: float
    shapes: list[SvgShape | str] = field(default_factory=list)

    def _marker_id(self, end: ArrowEnd, direction: str, color: str,
                   defs: dict[str, str]) -> str:
        key = (end.kind, direction)
        if key not in _MARKER_PATHS:
            key = ("triangle", direction)
        body_tpl, ref_x = _MARKER_PATHS[key]
        sw = _MARKER_SCALE.get(end.length, 1.0)
        sh = _MARKER_SCALE.get(end.w, 1.0)
        mid = f"m-{key[0]}-{direction}-{color.lstrip('#')}-{end.w}-{end.length}"
        if mid not in defs:
            defs[mid] = (
                f'<marker id="{mid}" viewBox="0 0 6 6" refX="{ref_x}" refY="3" '
                f'markerWidth="{_fmt(6 * sw)}" markerHeight="{_fmt(6 * sh)}" '
                f'orient="auto">{body_tpl.format(c=color)}</marker>'
            )
        return mid

    def _gradient_id(self, grad: GradientFill, owner_id: str, defs: dict[str, str]) -> str:
        gid = f"grad-{owner_id}"
        if gid not in defs:
            # PowerPoint angle: clockwise from +x in y-down space
            a = math.radians(grad.angle_deg)
            dx, dy = math.cos(a) / 2.0, math.sin(a) / 2.0
            stops = "".join(
                f'<stop offset="{_fmt(pos * 100)}%" stop-color="{color}"/>'
                for pos, color in grad.stops
            )
            defs[gid] = (
                f'<linearGradient id="{gid}" '
                f'x1="{_fmt(0.5 - dx)}" y1="{_fmt(0.5 - dy)}" '
                f'x2="{_fmt(0.5 + dx)}" y2="{_fmt(0.5 + dy)}">{stops}</linearGradient>'
            )
        return gid

    def to_string(self) -> str:
        defs: dict[str, str] = {}
        body: list[str] = []
        for shape in self.shapes:
            if isinstance(shape, str):
                body.append(f"  {shape}")
                continue
            body.append(f'  <g id="{shape.id}" transform="{shape.transform()}">')
            for ep in shape.paths:
                if isinstance(shape.style.fill, GradientFill) and ep.fill != "none":
                    gid = self._gradient_id(shape.style.fill, shape.id, defs)
                    fill = f"url(#{gid})"
                else:
                    fill = path_fill_color(ep.fill, shape.style.solid_fill)
                stroke = shape.style.stroke if ep.stroke else None
                attrs = [
                    f'd="{path_data(ep.segments, ep.sx, ep.sy)}"',
                    f'fill="{fill or "none"}"',
                    f'stroke="{stroke or "none"}"',
                ]
                if stroke:
                    attrs.append(f'stroke-width="{_fmt(shape.style.stroke_width_pt)}"')
                    if shape.style.dash:
                        arr = " ".join(
                            _fmt(m * shape.style.stroke_width_pt) for m in shape.style.dash
                        )
                        attrs.append(f'stroke-dasharray="{arr}"')
                    if shape.head:
                        mid = self._marker_id(shape.head, "start", stroke, defs)
                        attrs.append(f'marker-start="url(#{mid})"')
                    if shape.tail:
                        mid = self._marker_id(shape.tail, "end", stroke, defs)
                        attrs.append(f'marker-end="url(#{mid})"')
                body.append(f'    <path {" ".join(attrs)}/>')
            for el in shape.text_elements:
                body.append(f"    {el}")
            body.append("  </g>")

        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{_fmt(self.w)}pt" height="{_fmt(self.h)}pt" '
            f'viewBox="{_fmt(self.x)} {_fmt(self.y)} {_fmt(self.w)} {_fmt(self.h)}">'
        ]
        if defs:
            lines.append("  <defs>" + "".join(defs.values()) + "</defs>")
        lines.extend(body)
        lines.append("</svg>")
        return "\n".join(lines) + "\n"
