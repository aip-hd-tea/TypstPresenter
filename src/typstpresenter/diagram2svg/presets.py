"""ECMA-376 preset geometry: loader + guide-formula interpreter.

The shipped ``data/presetShapeDefinitions.xml`` defines all 187 preset
shapes as guide-formula programs over the shape's adjust values.  One
generic interpreter evaluates any preset into path commands; hand-coding
individual presets is never needed.

Units inside a geometry: EMU-like path space where ``w``/``h`` are the
shape extents in EMU; angles are 1/60000 of a degree.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_DATA = Path(__file__).parent / "data" / "presetShapeDefinitions.xml"

# 360° in DrawingML angle units.
_FULL_CIRCLE = 21_600_000

_CD_RE = re.compile(r"^(\d*)cd(\d+)$")  # cd2, 3cd4, ...
_DIV_RE = re.compile(r"^(w|h|ss|ls)d(\d+)$")  # wd2, hd4, ssd16, ...


@dataclass
class PathDef:
    """One <path> element: local size, fill/stroke behavior, commands."""

    w: int | None
    h: int | None
    fill: str  # norm | none | darken | darkenLess | lighten | lightenLess
    stroke: bool
    commands: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)


@dataclass
class PresetGeometry:
    name: str
    av_defaults: dict[str, str] = field(default_factory=dict)  # name -> fmla
    guides: list[tuple[str, str]] = field(default_factory=list)  # (name, fmla)
    paths: list[PathDef] = field(default_factory=list)
    text_rect: dict[str, str] | None = None  # l/t/r/b formula tokens


def _strip(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_path(el: ET.Element) -> PathDef:
    pd = PathDef(
        w=int(el.get("w")) if el.get("w") else None,
        h=int(el.get("h")) if el.get("h") else None,
        fill=el.get("fill", "norm"),
        stroke=el.get("stroke", "true") not in ("false", "0"),
    )
    for cmd in el:
        op = _strip(cmd.tag)
        if op in ("moveTo", "lnTo"):
            pt = cmd[0]
            pd.commands.append((op, (pt.get("x"), pt.get("y"))))
        elif op == "arcTo":
            pd.commands.append(
                (op, (cmd.get("wR"), cmd.get("hR"), cmd.get("stAng"), cmd.get("swAng")))
            )
        elif op in ("cubicBezTo", "quadBezTo"):
            args: list[str] = []
            for pt in cmd:
                args.extend((pt.get("x"), pt.get("y")))
            pd.commands.append((op, tuple(args)))
        elif op == "close":
            pd.commands.append((op, ()))
    return pd


@lru_cache(maxsize=1)
def load_presets(path: Path | None = None) -> dict[str, PresetGeometry]:
    root = ET.parse(path or _DATA).getroot()
    presets: dict[str, PresetGeometry] = {}
    for shape_el in root:
        geom = PresetGeometry(name=_strip(shape_el.tag))
        for section in shape_el:
            tag = _strip(section.tag)
            if tag == "avLst":
                for gd in section:
                    geom.av_defaults[gd.get("name")] = gd.get("fmla")
            elif tag == "gdLst":
                for gd in section:
                    geom.guides.append((gd.get("name"), gd.get("fmla")))
            elif tag == "pathLst":
                for p in section:
                    geom.paths.append(_parse_path(p))
            elif tag == "rect":
                geom.text_rect = {k: section.get(k) for k in ("l", "t", "r", "b")}
        presets[geom.name] = geom
    return presets


# ------------------------------------------------------------ evaluation --


def _deg(v: float) -> float:
    """DrawingML angle units → radians."""
    return math.radians(v / 60000.0)


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


class GuideContext:
    """Variable environment for one shape instance (w, h in EMU)."""

    def __init__(self, w: float, h: float):
        ss = min(w, h)
        ls = max(w, h)
        self.vars: dict[str, float] = {
            "w": w, "h": h, "ss": ss, "ls": ls,
            "l": 0.0, "t": 0.0, "r": w, "b": h,
            "hc": w / 2.0, "vc": h / 2.0,
        }

    def resolve(self, token: str) -> float:
        try:
            return float(token)
        except ValueError:
            pass
        v = self.vars.get(token)
        if v is not None:
            return v
        m = _CD_RE.match(token)
        if m:  # cd2 = 1/2 circle, 3cd4 = 3/4 circle ...
            num = int(m.group(1) or 1)
            return num * _FULL_CIRCLE / int(m.group(2))
        m = _DIV_RE.match(token)
        if m:  # wd2 = w/2, ssd16 = ss/16 ...
            return self.vars[m.group(1)] / int(m.group(2))
        raise KeyError(f"unknown guide token {token!r}")

    def evaluate(self, fmla: str) -> float:
        parts = fmla.split()
        op, args = parts[0], [*map(self.resolve, parts[1:])]
        if op == "val":
            return args[0]
        if op == "*/":
            return _safe_div(args[0] * args[1], args[2])
        if op == "+-":
            return args[0] + args[1] - args[2]
        if op == "+/":
            return _safe_div(args[0] + args[1], args[2])
        if op == "?:":
            return args[1] if args[0] > 0 else args[2]
        if op == "abs":
            return abs(args[0])
        if op == "at2":
            return math.degrees(math.atan2(args[1], args[0])) * 60000.0
        if op == "cat2":
            return args[0] * math.cos(math.atan2(args[2], args[1]))
        if op == "sat2":
            return args[0] * math.sin(math.atan2(args[2], args[1]))
        if op == "cos":
            return args[0] * math.cos(_deg(args[1]))
        if op == "sin":
            return args[0] * math.sin(_deg(args[1]))
        if op == "tan":
            return args[0] * math.tan(_deg(args[1]))
        if op == "max":
            return max(args)
        if op == "min":
            return min(args)
        if op == "mod":
            return math.sqrt(sum(a * a for a in args))
        if op == "pin":
            return min(max(args[1], args[0]), args[2])
        if op == "sqrt":
            return math.sqrt(max(args[0], 0.0))
        raise ValueError(f"unknown formula op {op!r} in {fmla!r}")

    def define(self, name: str, fmla: str) -> None:
        self.vars[name] = self.evaluate(fmla)


# Segment types produced by evaluate_paths (coordinates in EMU path space):
#   ("M", x, y) / ("L", x, y) / ("C", x1,y1,x2,y2,x,y) / ("Q", x1,y1,x,y)
#   ("A", rx, ry, sweep_pos, x, y)   -- axis-aligned elliptical arc chunk ≤120°
#   ("Z",)
Segment = tuple


@dataclass
class EvaluatedPath:
    fill: str
    stroke: bool
    segments: list[Segment]
    # scale factors mapping this path's local units to shape EMU
    sx: float = 1.0
    sy: float = 1.0


def _arc_segments(cur: tuple[float, float], wR: float, hR: float,
                  st_ang: float, sw_ang: float) -> tuple[list[Segment], tuple[float, float]]:
    """DrawingML arcTo → SVG arc chunks (parametric-angle interpretation)."""
    st = _deg(st_ang)
    sw = _deg(sw_ang)
    cx = cur[0] - wR * math.cos(st)
    cy = cur[1] - hR * math.sin(st)
    n = max(1, math.ceil(abs(sw) / (2 * math.pi / 3)))  # chunks ≤ 120°
    segs: list[Segment] = []
    end = cur
    for i in range(1, n + 1):
        ang = st + sw * i / n
        end = (cx + wR * math.cos(ang), cy + hR * math.sin(ang))
        segs.append(("A", wR, hR, 1 if sw > 0 else 0, end[0], end[1]))
    return segs, end


def _evaluate_paths(
    ctx: GuideContext, path_defs: list[PathDef], w_emu: float, h_emu: float
) -> list[EvaluatedPath]:
    out: list[EvaluatedPath] = []
    for pd in path_defs:
        sx = w_emu / pd.w if pd.w else 1.0
        sy = h_emu / pd.h if pd.h else 1.0
        ep = EvaluatedPath(fill=pd.fill, stroke=pd.stroke, segments=[], sx=sx, sy=sy)
        cur = (0.0, 0.0)
        for op, args in pd.commands:
            vals = [ctx.resolve(a) for a in args]
            if op == "moveTo":
                cur = (vals[0], vals[1])
                ep.segments.append(("M", *cur))
            elif op == "lnTo":
                cur = (vals[0], vals[1])
                ep.segments.append(("L", *cur))
            elif op == "cubicBezTo":
                cur = (vals[4], vals[5])
                ep.segments.append(("C", *vals))
            elif op == "quadBezTo":
                cur = (vals[2], vals[3])
                ep.segments.append(("Q", *vals))
            elif op == "arcTo":
                segs, cur = _arc_segments(cur, vals[0], vals[1], vals[2], vals[3])
                ep.segments.extend(segs)
            elif op == "close":
                ep.segments.append(("Z",))
        out.append(ep)
    return out


def evaluate_preset(
    name: str,
    w_emu: float,
    h_emu: float,
    av_overrides: dict[str, str] | None = None,
) -> list[EvaluatedPath]:
    """Evaluate preset `name` for a shape of w×h EMU; returns paths in EMU."""
    geom = load_presets()[name]
    ctx = GuideContext(w_emu, h_emu)
    for av_name, fmla in geom.av_defaults.items():
        ctx.define(av_name, fmla)
    for av_name, fmla in (av_overrides or {}).items():
        ctx.define(av_name, fmla)
    for g_name, fmla in geom.guides:
        ctx.define(g_name, fmla)
    return _evaluate_paths(ctx, geom.paths, w_emu, h_emu)


def has_preset(name: str) -> bool:
    return name in load_presets()


def evaluate_custgeom(custgeom_el, w_emu: float, h_emu: float) -> list[EvaluatedPath]:
    """Evaluate an a:custGeom element (same dialect as preset geometry).

    Freeform coordinates are usually literal EMU within the path's local
    w/h space; gdLst guides (rare) are supported through the same context.
    Works with both lxml and ElementTree elements.
    """
    ctx = GuideContext(w_emu, h_emu)
    paths: list[PathDef] = []
    for section in custgeom_el:
        tag = _strip(section.tag)
        if tag in ("avLst", "gdLst"):
            for gd in section:
                ctx.define(gd.get("name"), gd.get("fmla"))
        elif tag == "pathLst":
            for p in section:
                paths.append(_parse_path(p))
    return _evaluate_paths(ctx, paths, w_emu, h_emu)


def evaluate_text_rect(
    name: str,
    w_emu: float,
    h_emu: float,
    av_overrides: dict[str, str] | None = None,
) -> tuple[float, float, float, float] | None:
    """The preset's text rectangle (l, t, r, b) in EMU, or None."""
    geom = load_presets().get(name)
    if geom is None or geom.text_rect is None:
        return None
    ctx = GuideContext(w_emu, h_emu)
    for av_name, fmla in geom.av_defaults.items():
        ctx.define(av_name, fmla)
    for av_name, fmla in (av_overrides or {}).items():
        ctx.define(av_name, fmla)
    for g_name, fmla in geom.guides:
        ctx.define(g_name, fmla)
    try:
        return tuple(ctx.resolve(geom.text_rect[k]) for k in ("l", "t", "r", "b"))
    except KeyError:
        return None
