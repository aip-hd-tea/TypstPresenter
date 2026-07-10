"""
Baseline PPTX -> Touying emitter.

This is deliberately the simplest possible faithful translation: every
shape is placed at its absolute PPTX coordinates on a Touying slide whose
page size equals the PPTX slide size (margin 0), so PPTX pt coordinates
map 1:1 to Typst pt coordinates. It serves two purposes:

1. It produces paired (PPTX, Typst) documents to exercise and evaluate
   the verification tools (Methods A and B).
2. It is the seed of the real converter: later development replaces
   absolute placement with idiomatic Touying/CeTZ/Fletcher constructs,
   while the verification tools guard the visual fidelity.

Fault injection deliberately corrupts the emitted geometry (shift, resize,
extra text, dropped elements) to measure whether the verification methods
detect the corresponding problems.

Autoshapes and connectors are emitted as one CeTZ canvas per slide with
node probes, so diagram translation to CeTZ is covered as well.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pptx
from pptx.enum.shapes import MSO_SHAPE_TYPE

from typstpresenter.verify.geometry import EMU_PER_PT, BBox
from typstpresenter.verify.method_b import PROBE_PRELUDE
from typstpresenter.verify.pptx_geometry import element_id
from typstpresenter.verify.pptx_inherit import (
    resolve_alignment,
    resolve_anchor,
    resolve_bullet,
    resolve_font_size_pt,
)

TOUYING_VERSION = "0.6.1"
CETZ_VERSION = "0.5.2"

_ESCAPE = str.maketrans({c: f"\\{c}" for c in '\\#$*_`@<>"~[]'})


def escape_typst(text: str) -> str:
    return text.translate(_ESCAPE)


@dataclass(frozen=True)
class Fault:
    """A deliberate corruption of one emitted element (for evaluation)."""
    element_id: str
    dx: float = 0.0        # shift in pt
    dy: float = 0.0
    scale_w: float = 1.0   # box resize factors
    scale_h: float = 1.0
    extra_text: str = ""   # appended to the content (provokes overflow)
    drop: bool = False     # omit the element entirely

    def expected_issues(self) -> set[str]:
        """Issue kinds a verifier with access to box geometry (Method B)
        should report for this fault."""
        expected = set()
        if self.drop:
            return {"missing"}
        if self.dx or self.dy:
            expected.add("moved")
        if self.scale_w != 1.0 or self.scale_h != 1.0:
            expected.add("resized")
        if self.extra_text or self.scale_h < 1.0:
            expected.add("overflow")
        return expected

    def expected_issues_ink(self) -> set[str]:
        """Issue kinds detectable from rendered ink alone (Method A).

        Boxes without fill or stroke leave no trace in the PDF, so pure
        box resizing (and the overflow it causes within the original
        bounds) is invisible to ink-based verification.
        """
        expected = set()
        if self.drop:
            return {"missing"}
        if self.dx or self.dy:
            expected.add("moved")
        if self.extra_text:
            expected.add("overflow")
        return expected


def _run_size_pt(run, paragraph, shape, default: float) -> float:
    resolved = resolve_font_size_pt(run, paragraph, shape)
    return resolved if resolved is not None else default


def _run_color(run) -> str | None:
    color = run.font.color
    try:
        if color and color.type is not None and color.rgb is not None:
            return str(color.rgb)
    except AttributeError:
        pass
    return None


def _run_markup(run, paragraph, shape, default_size: float) -> str:
    """One PPTX run as a Typst #text(...) call with its effective styling."""
    args = [f"size: {_run_size_pt(run, paragraph, shape, default_size):g}pt"]
    if run.font.bold:
        args.append('weight: "bold"')
    if run.font.italic:
        args.append('style: "italic"')
    rgb = _run_color(run)
    if rgb:
        args.append(f'fill: rgb("#{rgb}")')
    inner = escape_typst(run.text)
    if run.font.underline:
        inner = f"#underline[{inner}]"
    return f"#text({', '.join(args)})[{inner}]"


def _typst_align(paragraph, shape) -> str | None:
    from pptx.enum.text import PP_ALIGN

    alignment = resolve_alignment(paragraph, shape)
    return {PP_ALIGN.CENTER: "center", PP_ALIGN.RIGHT: "right"}.get(alignment)


def _shape_bbox(shape) -> BBox | None:
    if shape.left is None or shape.top is None:
        return None
    return BBox(
        shape.left / EMU_PER_PT,
        shape.top / EMU_PER_PT,
        (shape.width or 0) / EMU_PER_PT,
        (shape.height or 0) / EMU_PER_PT,
    )


def _emit_text_body(shape, default_size: float, extra_text: str) -> str:
    """Render the paragraphs of a text frame as Typst markup."""
    from pptx.enum.text import MSO_ANCHOR

    parts: list[str] = []
    for paragraph in shape.text_frame.paragraphs:
        runs = [_run_markup(run, paragraph, shape, default_size)
                for run in paragraph.runs if run.text]
        if not runs:
            continue
        prefix = ""
        indent = paragraph.level * 18.0
        if indent:
            prefix += f"#h({indent:g}pt)"
        bullet = resolve_bullet(paragraph, shape)
        if bullet:
            prefix += escape_typst(bullet) + " "
        line = f"#par(hanging-indent: 0pt)[{prefix}{''.join(runs)}]"
        align = _typst_align(paragraph, shape)
        if align:
            line = f"#align({align})[{line}]"
        parts.append(line)
    if extra_text:
        parts.append(f"#par[#text(size: {default_size:g}pt)[{escape_typst(extra_text)}]]")
    content = "\n".join(parts)
    anchor = resolve_anchor(shape)
    if anchor == MSO_ANCHOR.MIDDLE:
        content = f"#align(horizon)[\n{content}\n]"
    elif anchor == MSO_ANCHOR.BOTTOM:
        content = f"#align(bottom)[\n{content}\n]"
    return content


def _is_diagram_shape(shape) -> bool:
    return shape.shape_type in (MSO_SHAPE_TYPE.AUTO_SHAPE, MSO_SHAPE_TYPE.LINE) or (
        shape.element.tag.endswith("}cxnSp")
    )


def _emit_cetz_shape(shape, eid: str, bbox: BBox, probes: bool) -> str:
    """One PPTX autoshape/connector as CeTZ drawing commands (y axis flipped)."""
    from pptx.enum.shapes import MSO_SHAPE

    lines = []
    x1, y1, x2, y2 = bbox.x, -bbox.y, bbox.x2, -bbox.y2
    is_connector = shape.shape_type not in (MSO_SHAPE_TYPE.AUTO_SHAPE,)
    if is_connector:
        lines.append(f"    line(({x1:.2f}, {y1:.2f}), ({x2:.2f}, {y2:.2f}), mark: (end: \">\"))")
        if probes:
            cx, cy = bbox.center
            lines.append(f'    content(({cx:.2f}, {-cy:.2f}), [#tp-node-probe("{eid}")])')
    else:
        auto = None
        try:
            auto = shape.auto_shape_type
        except (ValueError, AttributeError):
            pass
        if auto == MSO_SHAPE.OVAL:
            cx, cy = bbox.center
            lines.append(
                f"    circle(({cx:.2f}, {-cy:.2f}), radius: ({bbox.w / 2:.2f}, {bbox.h / 2:.2f}))"
            )
        else:
            radius = 4.0 if auto == MSO_SHAPE.ROUNDED_RECTANGLE else 0.0
            lines.append(
                f"    rect(({x1:.2f}, {y1:.2f}), ({x2:.2f}, {y2:.2f}), radius: {radius:g})"
            )
        text = shape.text_frame.text.strip() if shape.has_text_frame else ""
        cx, cy = bbox.center
        marker = f"#tp-node-probe(\"{eid}\")" if probes else ""
        if text or marker:
            lines.append(
                f"    content(({cx:.2f}, {-cy:.2f}), [{marker}{escape_typst(text)}])"
            )
    return "\n".join(lines)


def emit_touying(
    pptx_path: Path | str,
    out_path: Path | str,
    probes: bool = True,
    faults: tuple[Fault, ...] = (),
    default_font_size: float = 18.0,
) -> Path:
    """
    Emit a Touying presentation with absolute positioning from a PPTX file.

    Every text/image element becomes a ``tp-probe(...)`` call (designed
    geometry included), autoshapes/connectors become one CeTZ canvas per
    slide with ``tp-node-probe`` markers. With ``probes=False`` the same
    layout is emitted without instrumentation.
    """
    pptx_path = Path(pptx_path)
    out_path = Path(out_path)
    prs = pptx.Presentation(str(pptx_path))
    page_w = prs.slide_width / EMU_PER_PT
    page_h = prs.slide_height / EMU_PER_PT
    faults_by_id = {f.element_id: f for f in faults}

    header = [
        "// Auto-generated by typstpresenter baseline emitter -- edit freely.",
        f'#import "@preview/touying:{TOUYING_VERSION}": *',
        "#import themes.simple: *",
        f'#import "@preview/cetz:{CETZ_VERSION}"',
        "",
        "#show: simple-theme.with(",
        f"  config-page(width: {page_w:g}pt, height: {page_h:g}pt, margin: 0pt),",
        "  config-common(handout: true),",
        "  footer: none,",
        ")",
        '#set text(font: ("Calibri", "Arial", "Liberation Sans"))',
        "",
    ]
    if probes:
        header.append(PROBE_PRELUDE)

    media_dir = out_path.parent / f"{out_path.stem}_media"
    body: list[str] = []

    for slide_index, slide in enumerate(prs.slides):
        body.append("#slide[")
        cetz_lines: list[str] = []
        for shape in slide.shapes:
            bbox = _shape_bbox(shape)
            if bbox is None:
                continue
            eid = element_id(slide_index, shape.shape_id)
            fault = faults_by_id.get(eid)
            if fault:
                if fault.drop:
                    continue
                bbox = replace(
                    bbox,
                    x=bbox.x + fault.dx, y=bbox.y + fault.dy,
                    w=bbox.w * fault.scale_w, h=bbox.h * fault.scale_h,
                )

            if _is_diagram_shape(shape):
                cetz_lines.append(_emit_cetz_shape(shape, eid, bbox, probes))
                continue

            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                media_dir.mkdir(parents=True, exist_ok=True)
                image = shape.image
                filename = f"{eid}.{image.ext}"
                (media_dir / filename).write_bytes(image.blob)
                content = f'#image("{media_dir.name}/{filename}", width: 100%, height: 100%)'
            elif shape.has_text_frame and shape.text_frame.text.strip():
                content = _emit_text_body(
                    shape, default_size=default_font_size,
                    extra_text=fault.extra_text if fault else "",
                )
            else:
                continue

            geometry = f"{bbox.x:.2f}pt, {bbox.y:.2f}pt, {bbox.w:.2f}pt, {bbox.h:.2f}pt"
            if probes:
                body.append(f'  #tp-probe("{eid}", {geometry})[\n{content}\n  ]')
            else:
                body.append(
                    f"  #place(top + left, dx: {bbox.x:.2f}pt, dy: {bbox.y:.2f}pt, "
                    f"block(width: {bbox.w:.2f}pt, height: {bbox.h:.2f}pt)[\n{content}\n  ])"
                )

        if cetz_lines:
            body.append("  #place(top + left, cetz.canvas(length: 1pt, {")
            body.append("    import cetz.draw: *")
            body.append("    set-style(stroke: 0.75pt)")
            # invisible full-page rect anchors the canvas at the page origin,
            # otherwise CeTZ shrink-wraps it and all coordinates shift
            body.append(f"    rect((0, 0), ({page_w:.2f}, {-page_h:.2f}), stroke: none)")
            body.append("\n".join(cetz_lines))
            body.append("  }))")
        body.append("]")
        body.append("")

    out_path.write_text("\n".join(header + body), encoding="utf-8", newline="\n")
    return out_path
