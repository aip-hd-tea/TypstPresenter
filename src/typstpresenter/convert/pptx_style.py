"""
Resolve effective fill, outline and font colors of PPTX autoshapes.

Autoshapes rarely carry explicit colors: a freshly inserted PowerPoint
shape references the theme through its ``p:style`` element (fillRef ->
accent1, lnRef -> darker accent1, fontRef -> lt1/white). This module
resolves explicit fills first and falls back to the theme color scheme.
Color transforms (shade/tint/lumMod) are currently ignored -- close
enough for layout verification purposes.
"""

from __future__ import annotations

from lxml import etree
from pptx.enum.dml import MSO_FILL, MSO_THEME_COLOR
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn

_A_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}

# clrMap defaults: style references use tx/bg names, the scheme dk/lt names
_SCHEME_ALIASES = {"tx1": "dk1", "bg1": "lt1", "tx2": "dk2", "bg2": "lt2"}

_THEME_ENUM_TO_SCHEME = {
    MSO_THEME_COLOR.ACCENT_1: "accent1",
    MSO_THEME_COLOR.ACCENT_2: "accent2",
    MSO_THEME_COLOR.ACCENT_3: "accent3",
    MSO_THEME_COLOR.ACCENT_4: "accent4",
    MSO_THEME_COLOR.ACCENT_5: "accent5",
    MSO_THEME_COLOR.ACCENT_6: "accent6",
    MSO_THEME_COLOR.DARK_1: "dk1",
    MSO_THEME_COLOR.DARK_2: "dk2",
    MSO_THEME_COLOR.LIGHT_1: "lt1",
    MSO_THEME_COLOR.LIGHT_2: "lt2",
    MSO_THEME_COLOR.HYPERLINK: "hlink",
    MSO_THEME_COLOR.FOLLOWED_HYPERLINK: "folHlink",
    # clrMap-mapped names (aliases resolved by _scheme_lookup)
    MSO_THEME_COLOR.TEXT_1: "tx1",
    MSO_THEME_COLOR.TEXT_2: "tx2",
    MSO_THEME_COLOR.BACKGROUND_1: "bg1",
    MSO_THEME_COLOR.BACKGROUND_2: "bg2",
}


def theme_color_scheme(shape) -> dict[str, str]:
    """Scheme color name -> RRGGBB hex, from the master's theme part."""
    master = shape.part.slide.slide_layout.slide_master
    theme_part = master.part.part_related_by(RT.THEME)
    root = etree.fromstring(theme_part.blob)
    scheme = root.find(".//a:clrScheme", _A_NS)
    colors: dict[str, str] = {}
    if scheme is None:
        return colors
    for child in scheme:
        name = etree.QName(child).localname
        srgb = child.find("a:srgbClr", _A_NS)
        sysclr = child.find("a:sysClr", _A_NS)
        if srgb is not None and srgb.get("val"):
            colors[name] = srgb.get("val")
        elif sysclr is not None and sysclr.get("lastClr"):
            colors[name] = sysclr.get("lastClr")
    return colors


def _scheme_lookup(scheme_name: str | None, colors: dict[str, str]) -> str | None:
    if not scheme_name:
        return None
    return colors.get(_SCHEME_ALIASES.get(scheme_name, scheme_name))


def _style_ref_color(shape, ref_tag: str) -> str | None:
    """Color referenced by p:style/<ref_tag> (fillRef, lnRef, fontRef)."""
    style = shape.element.find(qn("p:style"))
    if style is None:
        return None
    ref = style.find(qn(f"a:{ref_tag}"))
    if ref is None:
        return None
    srgb = ref.find(qn("a:srgbClr"))
    if srgb is not None and srgb.get("val"):
        return srgb.get("val")
    scheme = ref.find(qn("a:schemeClr"))
    if scheme is not None:
        return _scheme_lookup(scheme.get("val"), theme_color_scheme(shape))
    return None


def _explicit_color(color_format) -> str | None:
    """RRGGBB from a python-pptx ColorFormat, resolving theme colors."""
    try:
        if color_format.type is None:
            return None
        if color_format.type == 1:  # MSO_COLOR_TYPE.RGB
            return str(color_format.rgb)
    except AttributeError:
        return None
    return None


def _explicit_or_theme_color(color_format, shape) -> str | None:
    rgb = _explicit_color(color_format)
    if rgb:
        return rgb
    try:
        theme = color_format.theme_color
    except (AttributeError, ValueError):
        return None
    scheme_name = _THEME_ENUM_TO_SCHEME.get(theme)
    return _scheme_lookup(scheme_name, theme_color_scheme(shape)) if scheme_name else None


def shape_fill_rgb(shape) -> str | None:
    """Effective fill color, or None for an unfilled shape."""
    fill = shape.fill
    if fill.type == MSO_FILL.SOLID:
        return _explicit_or_theme_color(fill.fore_color, shape)
    if fill.type == MSO_FILL.BACKGROUND:  # explicitly no fill
        return None
    if fill.type is None:  # inherited -> style fillRef
        return _style_ref_color(shape, "fillRef")
    return None


def shape_line_rgb(shape) -> str | None:
    """Effective outline color, or None for no outline."""
    line = shape.line
    if line.fill.type == MSO_FILL.SOLID:
        return _explicit_or_theme_color(line.color, shape)
    if line.fill.type == MSO_FILL.BACKGROUND:
        return None
    if line.fill.type is None:
        return _style_ref_color(shape, "lnRef")
    return None


def shape_line_width_pt(shape, default: float = 0.75) -> float:
    # width 0 EMU means "hairline" in PowerPoint, not invisible
    width = shape.line.width
    return width.pt if width is not None and width.pt > 0 else default


def shape_font_rgb(shape) -> str | None:
    """Default text color inside the shape (style fontRef, often white)."""
    return _style_ref_color(shape, "fontRef")
