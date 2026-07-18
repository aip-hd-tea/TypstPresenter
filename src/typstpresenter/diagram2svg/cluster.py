"""Render a flow-emitter diagram cluster as one SVG file + #image markup.

Drop-in alternative to flow._render_diagram_cluster (the CeTZ path):
same inputs, same (bounds, markup) contract, same alignment and
overflow-fit behavior.  Returns None when the cluster contains content
the SVG backend cannot represent yet (tables, unembeddable images) —
the caller then falls back to CeTZ.
"""

from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path

from typstpresenter.diagram2svg.convert import _has_geometry, build_svg_shape
from typstpresenter.diagram2svg.presets import evaluate_preset
from typstpresenter.diagram2svg.style import ShapeStyle
from typstpresenter.diagram2svg.svg_writer import SvgDocument, SvgShape, _fmt
from typstpresenter.diagram2svg.text import layout_shape_text
from typstpresenter.verify.geometry import BBox

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}


def _image_fragment(shape, bbox: BBox, eid: str, media_dir: Path) -> str | None:
    """Absorbed picture as an embedded <image> (data URI; typst's SVG
    pipeline does not load external references)."""
    from typstpresenter.convert.flow import _write_image_file

    filename = _write_image_file(shape, eid, media_dir)
    if not filename:
        return None
    path = media_dir / filename
    mime = _MIME.get(path.suffix.lower())
    if mime is None:
        return None
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return (
        f'<image x="{_fmt(bbox.x)}" y="{_fmt(bbox.y)}" '
        f'width="{_fmt(bbox.w)}" height="{_fmt(bbox.h)}" '
        f'preserveAspectRatio="none" href="data:{mime};base64,{b64}"/>'
    )


def _text_box_shape(shape, bbox: BBox, eid: str, default_size: float) -> SvgShape:
    """Absorbed text box (has rect geometry in practice; synthesize one
    with no ink if the XML carries none)."""
    if _has_geometry(shape):
        svg_shape, _ = build_svg_shape(shape, bbox, eid, default_size=default_size)
        return svg_shape
    from typstpresenter.diagram2svg.convert import _xfrm_of

    rot, flip_h, flip_v = _xfrm_of(shape)
    return SvgShape(
        id=eid,
        x_pt=bbox.x,
        y_pt=bbox.y,
        w_pt=bbox.w,
        h_pt=bbox.h,
        paths=[replace(p, fill="none", stroke=False)
               for p in evaluate_preset("rect", bbox.w * 12700.0, bbox.h * 12700.0)],
        style=ShapeStyle(fill=None, stroke=None, stroke_width_pt=0.75),
        rot_deg=rot,
        flip_h=flip_h,
        flip_v=flip_v,
        text_elements=layout_shape_text(shape, bbox.w, bbox.h,
                                        default_size=default_size),
    )


def render_cluster_svg(
    cluster: list[tuple],
    absorbed: list[tuple],
    page_w: float,
    default_size: float,
    context_size: float,
    media_dir: Path,
    scale: float = 1.0,
    slide_index: int = 0,
    cluster_index: int = 0,
    canvas_markers: bool = False,
    page_margin_x: float = 30.0,
) -> tuple[BBox, str] | None:
    from typstpresenter.convert.cetz import effective_bbox
    from typstpresenter.verify.pptx_geometry import element_id

    # tables inside the diagram area are not SVG-representable yet
    if any(kind == "table" for kind, *_ in absorbed):
        return None

    # hyperlinks cannot survive inside an embedded SVG (typst attaches
    # link annotations only to document-layer text) -> CeTZ fallback
    def _has_link(shape) -> bool:
        if not getattr(shape, "has_text_frame", False):
            return False
        try:
            return any(
                run.hyperlink.address
                for para in shape.text_frame.paragraphs
                for run in para.runs
            )
        except (AttributeError, KeyError, ValueError):
            return False

    if any(_has_link(sh) for sh, _ in cluster) or any(
            _has_link(sh) for _, sh, _, _ in absorbed):
        return None

    boxes = ([effective_bbox(shape, b) for shape, b in cluster]
             + [effective_bbox(sh, b) if k == "text" else b
                for k, sh, b, _ in absorbed])
    min_x = min(b.x for b in boxes)
    min_y = min(b.y for b in boxes)
    max_x = max(b.x2 for b in boxes)
    max_y = max(b.y2 for b in boxes)
    bounds = BBox(min_x, min_y, max_x - min_x, max_y - min_y)

    doc = SvgDocument(x=min_x, y=min_y, w=bounds.w, h=bounds.h)

    # source document order = paint order (same as the CeTZ path)
    entries = [("shape", shape, bbox, element_id(slide_index, shape.shape_id))
               for shape, bbox in cluster]
    entries += list(absorbed)
    root = entries[0][1]._element.getroottree().getroot()
    z_order = {el: i for i, el in enumerate(root.iter())}
    entries.sort(key=lambda e: z_order.get(e[1]._element, 0))

    shape_ids: list[str] = []
    for kind, shape, bbox, eid in entries:
        shape_ids.append(eid)
        if kind == "shape":
            if not _has_geometry(shape):
                continue
            svg_shape, _ = build_svg_shape(shape, bbox, eid,
                                           default_size=default_size)
            doc.shapes.append(svg_shape)
        elif kind == "image":
            frag = _image_fragment(shape, bbox, eid, media_dir)
            if frag is None:
                return None  # unembeddable image -> CeTZ fallback
            doc.shapes.append(frag)
        else:  # text
            doc.shapes.append(_text_box_shape(shape, bbox, eid, default_size))

    filename = f"s{slide_index + 1}-d{cluster_index}.svg"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / filename).write_text(doc.to_string(), encoding="utf-8")

    available_w = page_w - 2 * page_margin_x
    fit_scale = min(available_w / bounds.w, 1.0) if bounds.w > 0 else 1.0
    total_scale = scale * fit_scale
    render_w = bounds.w * total_scale
    render_h = bounds.h * total_scale
    image = f'image("{media_dir.name}/{filename}", width: {render_w:.2f}pt)'

    if canvas_markers:
        shapes_str = ", ".join(f'"{sid}"' for sid in shape_ids)
        marker = (
            f'#context metadata((kind: "canvas", id: "s{slide_index}-c{cluster_index}", '
            f"page: here().position().page, x: here().position().x.pt(), "
            f"y: here().position().y.pt(), "
            f"w: {render_w:.2f}, h: {render_h:.2f}, "
            f"shapes: ({shapes_str},)))<tp-canvas>"
        )
        body = f"box[{marker}#{image}]"
    else:
        body = image

    fitted_bounds = replace(bounds, w=render_w / scale if scale else bounds.w,
                            h=render_h / scale if scale else bounds.h)
    align_cx = bounds.center[0]
    if abs(align_cx - page_w / 2) < page_w * 0.08:
        return fitted_bounds, f"#align(center, block({body}))"
    if align_cx > page_w * 0.6:
        return fitted_bounds, f"#align(right, block({body}))"
    return fitted_bounds, f"#{body}"
