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

from pptx.enum.shapes import MSO_SHAPE_TYPE

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
    size, bold, italic, underline, rgb = style
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
        return f"#text({', '.join(args)})[{guard_markup_start(inner)}]", True
    # pure bold/italic can use native markup -- but only at word boundaries,
    # otherwise the delimiters do not trigger
    if bold and italic:
        if boundary_ok:
            return f"*_{inner}_*", False
        return f"#strong[#emph[{guard_markup_start(inner)}]]", True
    if bold:
        if boundary_ok:
            return f"*{inner}*", False
        return f"#strong[{guard_markup_start(inner)}]", True
    if italic:
        if boundary_ok:
            return f"_{inner}_", False
        return f"#emph[{guard_markup_start(inner)}]", True
    return inner, wrapped_hash


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
    image = shape.image
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
                lines.append(
                    f'  content(({x:.1f}, {-y:.1f}), anchor: "north-west", '
                    f"box(width: {bbox.w:.1f}pt)[\n{markup}\n  ])")
    lines.append("})")
    canvas = "\n".join(lines)
    if scale != 1.0:
        # uniform visual shrink (text included) for overflow calibration
        canvas = f"scale({scale * 100:.0f}%, reflow: true, {canvas})"
    if abs(bounds.center[0] - page_w / 2) < page_w * 0.08:
        return bounds, f"#align(center, block({canvas}))"
    return bounds, f"#{canvas}"


# ------------------------------------------------------------ slide markup --

def _is_chrome(shape, page_h: float, bbox: BBox) -> bool:
    """Slide chrome (page number, footer, date) that the theme should own."""
    if _ph_type_name(shape) in _CHROME_PH_TYPES:
        return True
    # unnamed text boxes hugging the bottom edge with tiny text are footers
    if (shape.has_text_frame and bbox.y > page_h * 0.92
            and len(shape.text_frame.text) < 60):
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
    from typstpresenter.verify.pptx_geometry import element_id, iter_flat_shapes

    diagram_shapes: list[tuple] = []
    candidates: list[tuple] = []  # (kind, shape, bbox, eid)
    for shape, bbox in iter_flat_shapes(slide.shapes):
        if shape == slide.shapes.title:
            continue
        if _is_chrome(shape, page_h, bbox) or _off_page(bbox, page_w, page_h):
            continue
        eid = element_id(slide_index, shape.shape_id)
        if is_diagram_shape(shape):
            diagram_shapes.append((shape, bbox))
        elif getattr(shape, "has_table", False):
            candidates.append(("table", shape, bbox, eid))
        elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            candidates.append(("image", shape, bbox, eid))
        elif shape.has_text_frame and shape.text_frame.text.strip():
            candidates.append(("text", shape, bbox, eid))

    # Text/pictures lying in the diagram area -- or labels sitting on an
    # image (annotated screenshots) -- are annotations, not flowing prose:
    # absorb them into one canvas that keeps their relative positions.
    absorbed: list[tuple] = []
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
            if _overlap_frac(tb, ib) > (0.3 if _is_small(tb) else 0.75):
                on_image.add(ti)
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

        absorbed = [images[ii] for ii in sorted(labeled)]
        on_image_entries = {id(texts[ti]) for ti in on_image}
        remaining = []
        for entry in candidates:
            kind, shape, bbox, eid = entry
            if entry in absorbed:
                continue
            if id(entry) in on_image_entries:
                absorbed.append(entry)
                continue
            small = _is_small(bbox)
            in_area = (
                (s_bounds is not None
                 and _overlap_frac(bbox, s_bounds) > 0.15)
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
        blocks.append(FlowBlock(bounds, "diagram", markup))
    blocks.sort(key=lambda b: (b.bbox.y, b.bbox.x))
    return _group_columns(blocks)


def _vertical_overlap(a: BBox, b: BBox) -> float:
    """Overlap of the y ranges as a fraction of the smaller height."""
    overlap = min(a.y2, b.y2) - max(a.y, b.y)
    smaller = min(a.h, b.h)
    return overlap / smaller if smaller > 0 else 0.0


def _horizontally_disjoint(a: BBox, b: BBox) -> bool:
    return a.x2 <= b.x + 4 or b.x2 <= a.x + 4


def _group_columns(blocks: list[FlowBlock]) -> list[FlowBlock]:
    """Merge side-by-side blocks into one #grid block (columns layout).

    Blocks that share most of their vertical range but occupy disjoint
    horizontal ranges were columns in the original slide; stacking them
    would double the slide height and shuffle the reading order.
    """
    merged: list[FlowBlock] = []
    i = 0
    while i < len(blocks):
        row = [blocks[i]]
        j = i + 1
        while j < len(blocks):
            cand = blocks[j]
            if (all(_vertical_overlap(cand.bbox, m.bbox) > 0.4 for m in row)
                    and all(_horizontally_disjoint(cand.bbox, m.bbox)
                            for m in row)):
                row.append(cand)
                j += 1
            else:
                break
        if len(row) == 1:
            merged.append(row[0])
        else:
            row.sort(key=lambda b: b.bbox.x)
            widths = [max(b.bbox.w, 1.0) for b in row]
            base = widths[0]
            columns = ", ".join(f"{w / base:.2g}fr" for w in widths)
            cells = []
            for b in row:
                indented = "\n".join(f"    {line}" for line in
                                     b.markup.split("\n"))
                cells.append(f"  [\n{indented}\n  ],")
            x = min(b.bbox.x for b in row)
            y = min(b.bbox.y for b in row)
            x2 = max(b.bbox.x2 for b in row)
            y2 = max(b.bbox.y2 for b in row)
            markup = (f"#grid(\n  columns: ({columns}), column-gutter: 16pt,\n"
                      + "\n".join(cells) + "\n)")
            merged.append(FlowBlock(BBox(x, y, x2 - x, y2 - y), "grid", markup))
        i = j if j > i + 1 else i + 1
    return merged


def flow_slide_markup(slide, slide_index: int, page_w: float, page_h: float,
                      media_dir: Path, default_size: float,
                      doc_size: float, scale: float = 1.0,
                      calibration_marker: bool = False) -> list[str]:
    """The complete markup of one slide (heading + flowing content)."""
    from typstpresenter.convert.emitter import slide_title_text

    body: list[str] = []
    title = slide_title_text(slide)
    body.append(f"== {escape_flow(title)}" if title else "== ")
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
    for block in flow_slide_blocks(slide, slide_index, page_w, page_h,
                                   media_dir, default_size, context_size,
                                   scale):
        content.append(block.markup)
        content.append("")
    if set_line:
        # a bare #set at slide level (or a `#[..]` scope containing #align)
        # makes touying split the slide in two; the block() function is the
        # only tested wrapper that keeps one slide. Full width so #align
        # still centers on the page.
        body += ["#block(width: 100%)[", set_line, ""] + content + ["]", ""]
    else:
        body += content
    return body


def _content_text_shapes(slide, page_h: float, page_w: float = 1e9):
    from typstpresenter.verify.pptx_geometry import iter_flat_shapes

    for shape, bbox in iter_flat_shapes(slide.shapes):
        if (shape == slide.shapes.title or _is_chrome(shape, page_h, bbox)
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
