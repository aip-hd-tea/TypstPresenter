"""
Idiomatic, human-editable slide emission ("flow mode", ``minimal=True``).

Instead of placing every shape at its absolute PPTX coordinates, slides are
rebuilt as normal Typst document flow: the title placeholder becomes a
``==`` heading, bullet paragraphs become native ``-`` list items, the
dominant body font size becomes one ``#set text(...)`` rule, bold/italic
runs become ``*...*`` / ``_..._`` markup, and pictures/tables/diagrams are
emitted in reading order. Simplicity and a coherent, overlap-free layout
take precedence over exact fidelity to the original coordinates.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from typstpresenter.convert.cetz import emit_cetz_shape, is_diagram_shape
from typstpresenter.convert.pptx_inherit import (
    resolve_bullet,
    resolve_font_size_pt,
)
from typstpresenter.convert.textbody import (
    autofit_scales,
    paragraph_run_chunks,
    typst_align,
)
from typstpresenter.verify.geometry import EMU_PER_PT, BBox

# Placeholder types that repeat on every slide (theme chrome, not content).
_CHROME_PH_TYPES = {"SLIDE_NUMBER", "FOOTER", "DATE"}

# Page margins of the emitted deck (shared with the emitter's config-page).
PAGE_MARGIN_X = 30.0
PAGE_MARGIN_TOP = 24.0
PAGE_MARGIN_BOTTOM = 30.0

# Characters that are markup-active *anywhere* in Typst markup mode. Unlike
# the probed emitter we do not escape '-', '+', '=', '/' mid-line: readable
# text beats protection against rare smart-dash substitutions.
_ESCAPE_MIN = str.maketrans({c: f"\\{c}" for c in '\\#$*_`@<>[]'})
# ... but at the start of a line (or content block) they would start a
# list/enum/heading/term item; '1.' would start a numbered enum.
_LINE_START_RE = re.compile(r"^(\s*)(?:([-+=/])|(\d+)\.)")


def escape_flow(text: str) -> str:
    # \x0b (pptx in-paragraph break) becomes a hard break like a:br;
    # '//' would start a line comment and swallow the closing bracket
    text = text.replace("\x0b", "\n")
    return re.sub("//", r"/\\/", text.translate(_ESCAPE_MIN))


def guard_markup_start(line: str) -> str:
    """Escape list/enum/heading/term markers at line or content-block start."""
    m = _LINE_START_RE.match(line)
    if not m:
        return line
    if m.group(2):
        return f"{m.group(1)}\\{line[m.end(1):]}"
    return f"{m.group(1)}{m.group(3)}\\.{line[m.end():]}"


def _round_size(size: float) -> float:
    return round(size * 2) / 2


def _ph_type_name(shape) -> str | None:
    try:
        ph_type = shape.placeholder_format.type
    except (AttributeError, ValueError):
        return None
    return ph_type.name if ph_type is not None else None


@dataclass
class FlowBlock:
    """One flow element of a slide, still carrying its source geometry."""
    bbox: BBox
    kind: str          # text | image | table | diagram
    markup: str


# ------------------------------------------------------------ inline text --

def _inline_chunk(text: str, style: tuple, context_size: float,
                  boundary_ok: bool) -> tuple[str, bool]:
    """Render one styled chunk; also report whether the result ends in a
    hash expression (whose parse would continue over a following '(' etc.)."""
    from typstpresenter.convert.textbody import typst_str

    size, bold, italic, underline, rgb, link = style

    def _linked(markup: str, ends_hash: bool) -> tuple[str, bool]:
        if link:
            return (f"#link({typst_str(link)})"
                    f"[{guard_markup_start(markup)}]", True)
        return markup, ends_hash

    inner = escape_flow(text).replace("\n", " \\ ")
    wrapped_hash = False
    if underline:
        inner = f"#underline[{guard_markup_start(inner)}]"
        wrapped_hash = True
    args = []
    if abs(size - context_size) > 0.26:
        args.append(f"size: {_round_size(size):g}pt")
    if rgb:
        args.append(f'fill: rgb("#{rgb}")')
    if args:
        if bold:
            args.append('weight: "bold"')
        if italic:
            args.append('style: "italic"')
        return _linked(f"#text({', '.join(args)})[{guard_markup_start(inner)}]",
                       True)
    # pure bold/italic can use native markup -- but only at word boundaries,
    # otherwise the delimiters do not trigger
    if bold and italic:
        if boundary_ok:
            return _linked(f"*_{inner}_*", False)
        return _linked(f"#strong[#emph[{guard_markup_start(inner)}]]", True)
    if bold:
        if boundary_ok:
            return _linked(f"*{inner}*", False)
        return _linked(f"#strong[{guard_markup_start(inner)}]", True)
    if italic:
        if boundary_ok:
            return _linked(f"_{inner}_", False)
        return _linked(f"#emph[{guard_markup_start(inner)}]", True)
    return _linked(inner, wrapped_hash)


def _continues_code(text: str) -> bool:
    """True if `text` directly after a hash expression would extend its
    parse: a call chain '(', a content argument '[', or a field access '.'."""
    if not text:
        return False
    if text[0] in "([":
        return True
    return text[0] == "." and len(text) > 1 and (text[1].isalpha() or text[1] == "_")


def _paragraph_inline(chunks: list[tuple[str, tuple]], context_size: float) -> str:
    parts = []
    hash_end = False
    for i, (text, style) in enumerate(chunks):
        prev = chunks[i - 1][0][-1:] if i > 0 else " "
        nxt = chunks[i + 1][0][:1] if i + 1 < len(chunks) else " "
        boundary_ok = (
            not text[:1].isspace()
            and (not prev or not prev.isalnum())
            and (not nxt or not nxt.isalnum())
        )
        rendered, ends_hash = _inline_chunk(text, style, context_size, boundary_ok)
        if hash_end and _continues_code(rendered):
            # ';' ends the previous hash expression, renders as nothing
            parts.append(";")
        parts.append(rendered)
        hash_end = ends_hash
    return "".join(parts)


# ------------------------------------------------------------- text blocks --

def _paragraph_size(paragraph, shape, default_size: float, scale: float) -> float:
    run = paragraph.runs[0] if paragraph.runs else None
    resolved = resolve_font_size_pt(run, paragraph, shape)
    return (resolved if resolved is not None else default_size) * scale


def text_chunks_of_shape(shape, default_size: float) -> list[tuple[str, tuple]]:
    """All (text, style) chunks of a text frame (autofit scale applied)."""
    font_scale, _ = autofit_scales(shape)
    chunks: list[tuple[str, tuple]] = []
    for paragraph in shape.text_frame.paragraphs:
        chunks += paragraph_run_chunks(paragraph, shape, default_size, font_scale)
    return chunks


def dominant_size(chunk_lists: list[list[tuple[str, tuple]]],
                  fallback: float) -> float:
    """The font size covering the most characters, rounded to 0.5pt."""
    weights: Counter[float] = Counter()
    for chunks in chunk_lists:
        for text, style in chunks:
            weights[_round_size(style[0])] += len(text)
    if not weights:
        return fallback
    return weights.most_common(1)[0][0]


def _render_text_block(shape, default_size: float, context_size: float,
                       scale: float = 1.0) -> str:
    """A text frame as flowing markup: native lists, plain paragraphs."""
    font_scale, _ = autofit_scales(shape)
    font_scale *= scale
    lines: list[str] = []
    in_list = False
    for paragraph in shape.text_frame.paragraphs:
        chunks = paragraph_run_chunks(paragraph, shape, default_size, font_scale,
                                      breaks=True)
        if not chunks:
            in_list = False
            continue
        inline = _paragraph_inline(chunks, context_size)
        bullet = resolve_bullet(paragraph, shape)
        level = paragraph.level
        align = typst_align(paragraph, shape)
        if bullet and not align:
            marker = "+" if bullet == "1." else "-"
            if not in_list and lines:
                lines.append("")
            lines.append(f"{'  ' * level}{marker} {guard_markup_start(inline)}")
            in_list = True
        else:
            if lines:
                lines.append("")
            line = guard_markup_start(inline)
            if align:
                line = f"#align({align})[{line}]"
            lines.append(line)
            in_list = False
    return "\n".join(lines)


# ---------------------------------------------------------------- pictures --

_TYPST_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "svg", "webp"}


def _write_image_file(shape, eid: str, media_dir: Path) -> str | None:
    """Write the picture blob (converting if needed); returns the filename."""
    from typstpresenter.verify.pptx_geometry import picture_image

    image = picture_image(shape)
    if image is None:
        return None
    ext = image.ext.lower()
    media_dir.mkdir(parents=True, exist_ok=True)
    if ext in _TYPST_IMAGE_EXTS:
        filename = f"{eid}.{ext}"
        (media_dir / filename).write_bytes(image.blob)
        return filename
    try:
        import io

        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(image.blob)) as im:
            filename = f"{eid}.png"
            im.convert("RGBA").save(media_dir / filename)
        return filename
    except Exception:
        return None  # not renderable; drop rather than draw a broken frame


def _render_picture(shape, eid: str, bbox: BBox, media_dir: Path,
                    page_w: float, scale: float = 1.0) -> str:
    filename = _write_image_file(shape, eid, media_dir)
    if filename is None:
        return ""
    img = f'image("{media_dir.name}/{filename}", width: {bbox.w * scale:.0f}pt)'
    if abs(bbox.center[0] - page_w / 2) < page_w * 0.06:
        return f"#align(center, {img})"
    if bbox.center[0] > page_w * 0.6:
        return f"#align(right, {img})"
    return f"#{img}"


# ------------------------------------------------------------------ tables --

def _render_table(shape, default_size: float, context_size: float,
                  scale: float = 1.0) -> str:
    table = shape.table
    columns = ", ".join(
        f"{c.width * scale / EMU_PER_PT:.0f}pt" for c in table.columns)
    # dense tables get the source row heights (they fit the slide by
    # construction); auto rows grow with typst's line metrics and spill
    # dense tables off the page. Small tables stay editable with auto rows.
    rows = None
    if len(table.rows) > 8:
        rows = ", ".join(
            f"{r.height * scale / EMU_PER_PT:.0f}pt" for r in table.rows)
    cells = []
    for row in table.rows:
        row_cells = []
        for cell in row.cells:
            paras = []
            for paragraph in cell.text_frame.paragraphs:
                chunks = paragraph_run_chunks(paragraph, shape, default_size,
                                              scale, breaks=True)
                if chunks:
                    paras.append(_paragraph_inline(chunks, context_size))
            joined = " \\ ".join(paras)
            row_cells.append(f"[{guard_markup_start(joined)}]")
        cells.append("  " + ", ".join(row_cells) + ",")
    inset = 5.0 * scale if rows is None else min(5.0 * scale, 2.5)
    rows_cfg = f"  rows: ({rows}),\n" if rows else ""
    return (f"#table(\n  columns: ({columns}),\n{rows_cfg}"
            f"  inset: {inset:g}pt, stroke: 0.5pt,\n"
            + "\n".join(cells) + "\n)")


# ---------------------------------------------------------------- diagrams --

def _render_diagram_cluster(cluster: list[tuple], absorbed: list[tuple],
                            page_w: float, default_size: float,
                            context_size: float, media_dir: Path,
                            scale: float = 1.0) -> tuple[BBox, str]:
    """Diagram shapes of a slide, plus text/picture shapes lying in the
    diagram area ("absorbed"), as one flow-embedded CeTZ canvas.

    Absorbed shapes keep their original relative positions: scattered
    labels, hand-drawn tables and small icons are diagram annotations --
    stacking them as flowing paragraphs would garble the picture and blow
    up the slide height.
    """
    boxes = [b for _, b in cluster] + [b for _, _, b, _ in absorbed]
    min_x = min(b.x for b in boxes)
    min_y = min(b.y for b in boxes)
    max_x = max(b.x2 for b in boxes)
    max_y = max(b.y2 for b in boxes)
    bounds = BBox(min_x, min_y, max_x - min_x, max_y - min_y)
    lines = [
        "cetz.canvas(length: 1pt, {",
        "  import cetz.draw: *",
        "  set-style(stroke: 0.75pt)",
        # anchor the canvas so labels sticking out do not shift the drawing
        f"  rect((0, 0), ({bounds.w:.2f}, {-bounds.h:.2f}), stroke: none)",
    ]
    for shape, bbox in cluster:
        rebased = replace(bbox, x=bbox.x - min_x, y=bbox.y - min_y)
        markup, _ = emit_cetz_shape(shape, "", rebased, probes=False,
                                    default_size=default_size)
        lines.append(markup)
    for kind, shape, bbox, eid in absorbed:
        x, y = bbox.x - min_x, bbox.y - min_y
        if kind == "image":
            filename = _write_image_file(shape, eid, media_dir)
            if filename:
                lines.append(
                    f'  content(({x:.1f}, {-y:.1f}), anchor: "north-west", '
                    f'image("{media_dir.name}/{filename}", width: {bbox.w:.0f}pt))')
        else:
            markup = _render_text_block(shape, default_size, context_size)
            if markup:
                # absorbed text must stay inside its source box: match
                # PowerPoint's line pitch instead of typst's airier default
                lines.append(
                    f'  content(({x:.1f}, {-y:.1f}), anchor: "north-west", '
                    f"box(width: {bbox.w:.1f}pt)[\n"
                    "#set par(leading: 0.59em, spacing: 0.59em)\n"
                    f"{markup}\n  ])")
    lines.append("})")
    canvas = "\n".join(lines)
    if scale != 1.0:
        # uniform visual shrink (text included) for overflow calibration
        canvas = f"scale({scale * 100:.0f}%, reflow: true, {canvas})"
    if abs(bounds.center[0] - page_w / 2) < page_w * 0.08:
        return bounds, f"#align(center, block({canvas}))"
    return bounds, f"#{canvas}"


# ------------------------------------------------------------ slide markup --

def _is_chrome(shape, page_h: float, bbox: BBox,
               page_w: float = 1e9) -> bool:
    """Slide chrome (page number, footer, date) that the theme should own."""
    if _ph_type_name(shape) in _CHROME_PH_TYPES:
        return True
    # unnamed text boxes hugging the bottom edge with tiny text are footers
    if (shape.has_text_frame and bbox.y > page_h * 0.92
            and len(shape.text_frame.text) < 60):
        return True
    # small ornaments inside the title band (course badges, QR links)
    # decorate every slide's header, they are not content
    if bbox.y2 <= 60 and bbox.h < 50:
        return True
    # ... as are small pictures pinned to the top-right corner (QR codes,
    # logos) that repeat next to the title
    if (bbox.y < 15 and bbox.x2 > page_w * 0.8 and bbox.w < 130
            and not shape.has_text_frame):
        return True
    return False


def _off_page(bbox: BBox, page_w: float, page_h: float) -> bool:
    """Shapes parked outside the slide are working material, not content."""
    return (bbox.x >= page_w - 1 or bbox.y >= page_h - 1
            or bbox.x2 <= 1 or bbox.y2 <= 1)


def _overlap_frac(bbox: BBox, bounds: BBox) -> float:
    """Fraction of `bbox`'s area lying inside `bounds`."""
    area = bbox.w * bbox.h
    if area <= 0:
        return 0.0
    overlap = (max(0.0, min(bbox.x2, bounds.x2) - max(bbox.x, bounds.x))
               * max(0.0, min(bbox.y2, bounds.y2) - max(bbox.y, bounds.y)))
    return overlap / area


def flow_slide_blocks(slide, slide_index: int, page_w: float, page_h: float,
                      media_dir: Path, default_size: float,
                      context_size: float, scale: float = 1.0) -> list[FlowBlock]:
    """Classify and render the content shapes of one slide (title excluded)."""
    from typstpresenter.verify.pptx_geometry import (
        element_id,
        is_picture,
        iter_flat_shapes,
    )

    diagram_shapes: list[tuple] = []
    candidates: list[tuple] = []  # (kind, shape, bbox, eid)
    for shape, bbox in iter_flat_shapes(slide.shapes):
        if shape == slide.shapes.title:
            continue
        if (_is_chrome(shape, page_h, bbox, page_w)
                or _off_page(bbox, page_w, page_h)):
            continue
        eid = element_id(slide_index, shape.shape_id)
        if is_diagram_shape(shape):
            diagram_shapes.append((shape, bbox))
        elif getattr(shape, "has_table", False):
            candidates.append(("table", shape, bbox, eid))
        elif is_picture(shape):
            candidates.append(("image", shape, bbox, eid))
        elif shape.has_text_frame and shape.text_frame.text.strip():
            candidates.append(("text", shape, bbox, eid))

    # Text/pictures lying in the diagram area -- or labels sitting on an
    # image (annotated screenshots) -- are annotations, not flowing prose:
    # absorb them into one canvas that keeps their relative positions.
    absorbed: list[tuple] = []
    sparse_kernel = False
    texts = [c for c in candidates if c[0] == "text"]
    images = [c for c in candidates if c[0] == "image"]

    def _is_small(bbox: BBox) -> bool:
        return bbox.w * bbox.h < 9000

    # labels genuinely sitting ON an image pull that image into the canvas;
    # large prose merely brushing an image stays in flow (rendered text
    # grows taller than its source box and would collide with the image)
    on_image: set[int] = set()
    labeled: set[int] = set()
    for ti, (_, _, tb, _) in enumerate(texts):
        for ii, (_, _, ib, _) in enumerate(images):
            # labels often sit flush against the image edge; a small
            # growth catches them without swallowing separate captions
            grown = BBox(ib.x - 12, ib.y - 12, ib.w + 24, ib.h + 24)
            if _overlap_frac(tb, grown) > (0.3 if _is_small(tb) else 0.75):
                on_image.add(ti)
                labeled.add(ii)
    # an image lying on a larger image (an inset/detail view) must keep its
    # overlay position: both go into the canvas, the larger one as kernel
    inset_images: set[int] = set()
    for ii, (_, _, ib, _) in enumerate(images):
        for jj, (_, _, jb, _) in enumerate(images):
            if (ii != jj and ib.w * ib.h < jb.w * jb.h
                    and _overlap_frac(ib, jb) > 0.5):
                inset_images.add(ii)
                labeled.add(jj)
    # an image surrounded by several small labels is diagram art (arrows,
    # letters, callouts placed around a screenshot): keep the arrangement
    for ii, (_, _, ib, _) in enumerate(images):
        near = BBox(ib.x - 40, ib.y - 40, ib.w + 80, ib.h + 80)
        satellites = [ti for ti, (_, _, tb, _) in enumerate(texts)
                      if _is_small(tb) and _overlap_frac(tb, near) > 0.5]
        if len(satellites) >= 2:
            labeled.add(ii)

    def _union(boxes: list[BBox]) -> BBox:
        x = min(b.x for b in boxes)
        y = min(b.y for b in boxes)
        return BBox(x, y, max(b.x2 for b in boxes) - x,
                    max(b.y2 for b in boxes) - y)

    kernel_boxes = [b for _, b in diagram_shapes]
    kernel_boxes += [images[ii][2] for ii in labeled]
    if kernel_boxes:
        d_bounds = _union(kernel_boxes)
        # any-size absorption only against the drawn-shape area; bounds
        # that merely inherit an image must not swallow adjacent prose
        s_bounds = _union([b for _, b in diagram_shapes]) if diagram_shapes else None
        expanded = BBox(d_bounds.x - 30, d_bounds.y - 30,
                        d_bounds.w + 60, d_bounds.h + 60)
        # thin textless decorations (brackets, arrows) spanning the slide
        # must not swallow the text columns they decorate
        kernel_area = sum(b.w * b.h for _, b in diagram_shapes)
        kernel_text = any(
            getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip()
            for sh, _ in diagram_shapes)
        sparse_kernel = (
            s_bounds is not None and not kernel_text
            and kernel_area < 0.15 * s_bounds.w * s_bounds.h)
        large_text_threshold = 0.45 if sparse_kernel else 0.15

        absorbed = [images[ii] for ii in sorted(labeled)]
        on_image_entries = {id(texts[ti]) for ti in on_image}
        on_image_entries |= {id(images[ii]) for ii in inset_images}
        remaining = []
        for entry in candidates:
            kind, shape, bbox, eid = entry
            if entry in absorbed:
                continue
            if id(entry) in on_image_entries:
                absorbed.append(entry)
                continue
            small = _is_small(bbox)
            # large text blocks (whole columns) are prose, not annotations:
            # a sparse decoration kernel brushing them must not swallow them
            in_area = (
                (s_bounds is not None
                 and _overlap_frac(bbox, s_bounds)
                 > (0.15 if small else large_text_threshold))
                or (small and _overlap_frac(bbox, d_bounds) > 0.15)
            )
            # small captions hugging the diagram belong to it as well;
            # stacking them in flow detaches them from what they label
            nearby = small and _overlap_frac(bbox, expanded) > 0.5
            if kind != "table" and (in_area or nearby):
                absorbed.append(entry)
            else:
                remaining.append(entry)
        candidates = remaining

    blocks: list[FlowBlock] = []
    for kind, shape, bbox, eid in candidates:
        if kind == "table":
            markup = _render_table(shape, default_size, context_size, scale)
        elif kind == "image":
            markup = _render_picture(shape, eid, bbox, media_dir, page_w, scale)
        else:
            markup = _render_text_block(shape, default_size, context_size, scale)
        if markup:
            blocks.append(FlowBlock(bbox, kind, markup))
    if diagram_shapes or absorbed:
        bounds, markup = _render_diagram_cluster(
            diagram_shapes, absorbed, page_w, default_size, context_size,
            media_dir, scale)
        # a decoration-only canvas (thin brackets/arrows, sparse strips)
        # lying across the text columns it decorates would force those
        # columns to stack; losing the decoration beats halving the slide
        kernel_text = any(
            getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip()
            for sh, _ in diagram_shapes)
        thin = bounds.w < 80 or bounds.h < 40
        droppable = (sparse_kernel or thin) and not kernel_text and not absorbed
        conflicts = droppable and any(
            _decoration_conflict(bounds, b.bbox) for b in blocks)
        if not conflicts:
            blocks.append(FlowBlock(bounds, "diagram", markup))
    # a picture or note box floated in the empty right portion of a wide
    # text box is a side figure: narrow the text's grouping bbox so both
    # form columns instead of the floater being stacked below the text
    for txt_block in blocks:
        if txt_block.kind != "text":
            continue
        tb = txt_block.bbox
        floated = [
            b.bbox.x for b in blocks
            if b is not txt_block
            and _overlap_frac(b.bbox, tb) > 0.7
            and b.bbox.x > tb.x + 0.5 * tb.w
            and ((b.kind == "image" and b.bbox.w >= 100)
                 or (b.kind == "text"
                     and b.bbox.w * b.bbox.h < 0.25 * tb.w * tb.h))
        ]
        if floated:
            new_w = max(min(floated) - 8 - tb.x, tb.w * 0.4)
            txt_block.bbox = replace(tb, w=new_w)

    blocks.sort(key=lambda b: (b.bbox.y, b.bbox.x))
    return _group_columns(blocks, page_w - 2 * PAGE_MARGIN_X)


def _decoration_conflict(canvas: BBox, other: BBox) -> bool:
    """Does a decoration canvas overlap a flow block enough to break its
    column layout?"""
    x_overlap = min(canvas.x2, other.x2) - max(canvas.x, other.x)
    narrower = min(canvas.w, other.w)
    if narrower <= 0 or x_overlap / narrower < 0.3:
        return False
    return _vertical_overlap(canvas, other) > 0.3


def _vertical_overlap(a: BBox, b: BBox) -> float:
    """Overlap of the y ranges as a fraction of the smaller height."""
    overlap = min(a.y2, b.y2) - max(a.y, b.y)
    smaller = min(a.h, b.h)
    return overlap / smaller if smaller > 0 else 0.0


def _column_disjoint(a: FlowBlock, b: FlowBlock) -> bool:
    # PPT columns routinely overlap by a few points (text boxes are drawn
    # generously, diagram labels overhang); tolerate a sliver relative to
    # the narrower block -- more for diagrams, whose bounds include the
    # empty corners of their bounding box
    factor = 0.3 if "diagram" in (a.kind, b.kind) else 0.12
    slack = max(8.0, factor * min(a.bbox.w, b.bbox.w))
    return a.bbox.x2 <= b.bbox.x + slack or b.bbox.x2 <= a.bbox.x + slack


def _column_of(block: FlowBlock, row: list[FlowBlock]) -> int | None:
    """The single row column whose x-range contains `block`, if any."""
    hits = []
    for k, member in enumerate(row):
        overlap = (min(block.bbox.x2, member.bbox.x2)
                   - max(block.bbox.x, member.bbox.x))
        frac = overlap / block.bbox.w if block.bbox.w > 0 else 0.0
        if frac > 0.5:
            hits.append(k)
        elif frac > 0.2:
            return None  # straddles a column boundary
    return hits[0] if len(hits) == 1 else None


def _union_bbox(boxes: list[BBox]) -> BBox:
    x = min(b.x for b in boxes)
    y = min(b.y for b in boxes)
    return BBox(x, y, max(b.x2 for b in boxes) - x, max(b.y2 for b in boxes) - y)


def _fit_to_cell(block: FlowBlock, cell_pt: float) -> str:
    """Fixed-size content (canvas, picture) wider than its grid cell gets a
    uniform visual shrink so it cannot overflow the cell."""
    if block.kind in ("diagram", "image") and block.bbox.w > cell_pt > 0:
        factor = cell_pt / block.bbox.w
        return f"#scale({factor * 100:.0f}%, reflow: true)[{block.markup}]"
    return block.markup


def _row_markup(row: list[FlowBlock], extras: dict[int, list[FlowBlock]],
                content_w: float) -> FlowBlock:
    row = sorted(row, key=lambda b: b.bbox.x)
    all_blocks = list(row) + [b for cell in extras.values() for b in cell]
    bounds = _union_bbox([b.bbox for b in all_blocks])
    if not extras and all(b.kind == "image" for b in row):
        # a bare row of pictures: center it as a whole, with the source
        # gaps as gutters, instead of spreading it over fr-columns
        gaps = [row[k + 1].bbox.x - row[k].bbox.x2 for k in range(len(row) - 1)]
        gutter = max(sum(gaps) / len(gaps), 4.0) if gaps else 16.0
        cells = ", ".join(f"[{b.markup}]" for b in row)
        markup = (f"#align(center, grid(\n  columns: {len(row)}, "
                  f"column-gutter: {gutter:.0f}pt,\n  {cells},\n))")
        return FlowBlock(bounds, "grid", markup)
    widths = [max(b.bbox.w, 1.0) for b in row]
    base = widths[0]
    total = sum(widths)
    usable = content_w - 16.0 * (len(row) - 1)
    columns = ", ".join(f"{w / base:.2g}fr" for w in widths)
    cells = []
    # a row starting well right of the margin keeps its offset as a fixed
    # leading column, so its horizontal placement matches the source
    offset = bounds.x - PAGE_MARGIN_X
    if offset > 40:
        columns = f"{offset:.0f}pt, " + columns
        cells.append("  [],")
        usable -= offset
    for k, member in enumerate(row):
        cell_pt = usable * widths[k] / total
        parts = [_fit_to_cell(member, cell_pt)]
        parts += [_fit_to_cell(b, cell_pt) for b in
                  sorted(extras.get(k, ()), key=lambda b: b.bbox.y)]
        indented = "\n".join(f"    {line}" for line in
                             "\n\n".join(parts).split("\n"))
        cells.append(f"  [\n{indented}\n  ],")
    markup = (f"#grid(\n  columns: ({columns}), column-gutter: 16pt,\n"
              + "\n".join(cells) + "\n)")
    return FlowBlock(bounds, "grid", markup)


def _group_columns(blocks: list[FlowBlock],
                   content_w: float) -> list[FlowBlock]:
    """Merge side-by-side blocks into one #grid block (columns layout).

    Blocks that share most of their vertical range but occupy disjoint
    horizontal ranges were columns in the original slide; stacking them
    would double the slide height and shuffle the reading order. Blocks
    further down that stay within one column's x-range (a picture below
    the text of its column) belong into that column's cell.
    """
    merged: list[FlowBlock] = []
    i = 0
    while i < len(blocks):
        row = [blocks[i]]
        j = i + 1
        while j < len(blocks):
            cand = blocks[j]
            if (all(_vertical_overlap(cand.bbox, m.bbox) > 0.4 for m in row)
                    and all(_column_disjoint(cand, m) for m in row)):
                row.append(cand)
                j += 1
            else:
                break
        extras: dict[int, list[FlowBlock]] = {}
        if len(row) > 1:
            row.sort(key=lambda b: b.bbox.x)
            row_bottom = max(m.bbox.y2 for m in row)
            while j < len(blocks):
                cand = blocks[j]
                col = _column_of(cand, row)
                if col is None or cand.bbox.y >= row_bottom + 40:
                    break
                extras.setdefault(col, []).append(cand)
                j += 1
        if len(row) == 1:
            merged.append(row[0])
        else:
            merged.append(_row_markup(row, extras, content_w))
        i = j if j > i + 1 else i + 1
    return merged


def has_center_title(slide) -> bool:
    """True for title-layout slides (their title is a CENTER_TITLE box)."""
    return any(_ph_type_name(shape) == "CENTER_TITLE"
               for shape in slide.shapes)


def slide_title_size(slide, fallback: float = 40.0) -> float:
    """Resolved (inherited) title size of a slide, autofit applied."""
    title = slide.shapes.title
    if title is None or not getattr(title, "has_text_frame", False):
        return fallback
    font_scale, _ = autofit_scales(title)
    sizes = []
    for paragraph in title.text_frame.paragraphs:
        if not paragraph.text.strip():
            continue
        run = paragraph.runs[0] if paragraph.runs else None
        size = resolve_font_size_pt(run, paragraph, title)
        if size is not None:
            sizes.append(size * font_scale)
    return _round_size(max(sizes)) if sizes else fallback


def slide_title_link(slide) -> str | None:
    """A hyperlink carried by the title (run link or shape click action)."""
    from pptx.oxml.ns import qn

    title = slide.shapes.title
    if title is None or not getattr(title, "has_text_frame", False):
        return None
    for paragraph in title.text_frame.paragraphs:
        for run in paragraph.runs:
            try:
                if run.hyperlink.address:
                    return run.hyperlink.address
            except (AttributeError, KeyError):
                pass
    for el in title.element.iter(qn("a:hlinkClick")):
        rid = el.get(qn("r:id"))
        if rid:
            try:
                return title.part.rels[rid].target_ref
            except KeyError:
                pass
    return None


def deck_title_size(prs) -> float | None:
    """Most common resolved title size of the content slides (title-layout
    slides excluded); sizes the theme's heading preamble."""
    weights: Counter[float] = Counter()
    for slide in prs.slides:
        title = slide.shapes.title
        if title is None or has_center_title(slide):
            continue
        if not getattr(title, "has_text_frame", False):
            continue
        if not title.text_frame.text.strip():
            continue
        weights[slide_title_size(slide)] += 1
    if not weights:
        return None
    return weights.most_common(1)[0][0]


def flow_slide_markup(slide, slide_index: int, page_w: float, page_h: float,
                      media_dir: Path, default_size: float,
                      doc_size: float, scale: float = 1.0,
                      calibration_marker: bool = False,
                      heading_size: float | None = None) -> list[str]:
    """The complete markup of one slide (heading + flowing content)."""
    from typstpresenter.convert.textbody import typst_str

    from typstpresenter.convert.emitter import slide_title_text

    title = slide_title_text(slide)
    if title and has_center_title(slide):
        return _title_slide_markup(slide, slide_index, title, page_w, page_h,
                                   media_dir, default_size, doc_size, scale,
                                   calibration_marker)
    body: list[str] = []
    heading = escape_flow(title) if title else ""
    if title:
        # slides whose resolved title size deviates from the deck-wide
        # heading size get an inline override inside the heading body
        own_size = slide_title_size(slide)
        if heading_size is not None and abs(own_size - heading_size) > 2:
            heading = f"#text(size: {own_size:g}pt)[{heading}]"
        link = slide_title_link(slide)
        if link:
            heading = f"#link({typst_str(link)})[{heading}]"
    body.append(f"== {heading}" if heading else "== ")
    body.append("")
    if calibration_marker:
        # temporary, invisible: lets `typst query` report the page each
        # slide starts on; the final output is emitted without markers.
        # place(hide(..)) keeps it out of flow, and the blank line after the
        # heading keeps touying from splitting the slide -- a bare or
        # heading-adjacent top-level element would create an extra page
        body.append(f"#place(hide(context metadata((s: {slide_index}, "
                    "p: here().position().page))))")
        body.append("")

    # slide-dominant body size: one #set rule instead of per-run sizes
    chunk_lists = [
        text_chunks_of_shape(shape, default_size)
        for shape, bbox in _content_text_shapes(slide, page_h, page_w)
    ]
    slide_size = dominant_size(chunk_lists, doc_size)
    context_size = _round_size(slide_size * scale)
    set_line = None
    if abs(context_size - doc_size) > 0.26:
        set_line = f"#set text(size: {context_size:g}pt)"

    content: list[str] = []
    prev: FlowBlock | None = None
    for block in flow_slide_blocks(slide, slide_index, page_w, page_h,
                                   media_dir, default_size, context_size,
                                   scale):
        # preserve deliberate vertical whitespace of the source layout
        # (sparse slides place content low on purpose); the reference is
        # where flow content normally starts (below the heading, if any)
        if prev is None:
            start = 130.0 if title else 60.0
            if block.bbox.y > start + 25:
                content += [f"#v({(block.bbox.y - start) * scale:.0f}pt)", ""]
        else:
            gap = block.bbox.y - prev.bbox.y2
            if gap > 45:
                content += [f"#v({(gap - 30) * scale:.0f}pt)", ""]
        content.append(block.markup)
        content.append("")
        prev = block
    if set_line:
        # a bare #set at slide level (or a `#[..]` scope containing #align)
        # makes touying split the slide in two; the block() function is the
        # only tested wrapper that keeps one slide. Full width so #align
        # still centers on the page.
        body += ["#block(width: 100%)[", set_line, ""] + content + ["]", ""]
    else:
        body += content
    return body


def _title_slide_markup(slide, slide_index: int, title: str, page_w: float,
                        page_h: float, media_dir: Path, default_size: float,
                        doc_size: float, scale: float,
                        calibration_marker: bool) -> list[str]:
    """A CENTER_TITLE slide as `#title-slide[..]`: big centered title, the
    remaining content (subtitle, authors, date) centered below it."""
    title_size = _round_size(slide_title_size(slide) * scale)
    body = ["#title-slide["]
    if calibration_marker:
        body.append(f"  #place(hide(context metadata((s: {slide_index}, "
                    "p: here().position().page))))")
    body.append(f"  #text(size: {title_size:g}pt)[{escape_flow(title)}]")
    body.append("")

    chunk_lists = [
        text_chunks_of_shape(shape, default_size)
        for shape, bbox in _content_text_shapes(slide, page_h, page_w)
    ]
    slide_size = dominant_size(chunk_lists, doc_size)
    context_size = _round_size(slide_size * scale)
    if abs(context_size - doc_size) > 0.26:
        body.append(f"  #set text(size: {context_size:g}pt)")
        body.append("")
    for block in flow_slide_blocks(slide, slide_index, page_w, page_h,
                                   media_dir, default_size, context_size,
                                   scale):
        body.append(block.markup)
        body.append("")
    body += ["]", ""]
    return body


def _content_text_shapes(slide, page_h: float, page_w: float = 1e9):
    from typstpresenter.verify.pptx_geometry import iter_flat_shapes

    for shape, bbox in iter_flat_shapes(slide.shapes):
        if (shape == slide.shapes.title
                or _is_chrome(shape, page_h, bbox, page_w)
                or _off_page(bbox, page_w, page_h)):
            continue
        if (not is_diagram_shape(shape) and shape.has_text_frame
                and shape.text_frame.text.strip()):
            yield shape, bbox


def document_body_size(prs, default_size: float) -> float:
    """Deck-wide dominant body text size (for the preamble #set text)."""
    page_h = prs.slide_height / EMU_PER_PT
    page_w = prs.slide_width / EMU_PER_PT
    chunk_lists = []
    for slide in prs.slides:
        for shape, _ in _content_text_shapes(slide, page_h, page_w):
            chunk_lists.append(text_chunks_of_shape(shape, default_size))
    return dominant_size(chunk_lists, default_size)
