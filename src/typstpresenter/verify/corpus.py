"""
Generate the evaluation corpus: paired (PPTX, Typst) documents.

Covers:
(i)  simple presentations with common layouts (title+content, two columns,
     2x2 grid),
(ii) diagram slides translated to CeTZ (via the emitter) and Fletcher
     (dedicated generator),
plus fault-injected variants with known ground truth, used to measure the
detection quality of verification Methods A and B.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pptx
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.util import Pt

from typstpresenter.verify.emitter import Fault, emit_touying, escape_typst
from typstpresenter.verify.geometry import EMU_PER_PT, DocGeometry
from typstpresenter.verify.pptx_geometry import extract_pptx_geometry

FLETCHER_VERSION = "0.5.8"


@dataclass
class CorpusCase:
    name: str
    pptx_path: Path
    typ_path: Path
    truth: DocGeometry
    # element id -> issue kinds Method B (box geometry) must report;
    # empty for clean cases
    expected_issues_b: dict[str, set[str]] = field(default_factory=dict)
    # element id -> issue kinds detectable from rendered ink (Method A)
    expected_issues_a: dict[str, set[str]] = field(default_factory=dict)
    # injected text exists that is legitimately reported as 'extra' by A
    allows_extra_text: bool = False
    kind: str = "layout"  # layout | diagram-cetz | diagram-fletcher


# ------------------------------------------------------------ PPTX builders --

def _add_textbox(slide, x_in, y_in, w_in, h_in, text: str, size_pt: float,
                 bold: bool = False):
    from pptx.util import Inches
    box = slide.shapes.add_textbox(Inches(x_in), Inches(y_in), Inches(w_in), Inches(h_in))
    tf = box.text_frame
    tf.word_wrap = True
    lines = text.split("\n")
    tf.text = lines[0]
    for line in lines[1:]:
        tf.add_paragraph().text = line
    for paragraph in tf.paragraphs:
        for run in paragraph.runs:
            run.font.size = Pt(size_pt)
            run.font.bold = bold
        if not paragraph.runs:
            paragraph.font.size = Pt(size_pt)
    return box


LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Aenean commodo "
    "ligula eget dolor. Aenean massa. Cum sociis natoque penatibus et magnis "
    "dis parturient montes, nascetur ridiculus mus."
)


def build_title_content(path: Path) -> None:
    prs = pptx.Presentation()  # default 10 x 7.5 in
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _add_textbox(slide, 0.5, 0.4, 9.0, 1.0, "Title and Content", 36, bold=True)
    _add_textbox(slide, 0.5, 1.8, 9.0, 5.0,
                 f"First point about the topic\nSecond point with more words\n{LOREM}", 18)
    prs.save(str(path))


def build_two_columns(path: Path) -> None:
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_textbox(slide, 0.5, 0.4, 9.0, 1.0, "Two Columns", 36, bold=True)
    _add_textbox(slide, 0.5, 1.8, 4.25, 4.8, f"Left column.\n{LOREM}", 16)
    _add_textbox(slide, 5.25, 1.8, 4.25, 4.8, f"Right column.\n{LOREM}", 16)
    prs.save(str(path))


def build_grid(path: Path) -> None:
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_textbox(slide, 0.5, 0.3, 9.0, 0.9, "2x2 Grid", 32, bold=True)
    cells = [(0.5, 1.5), (5.25, 1.5), (0.5, 4.4), (5.25, 4.4)]
    for i, (x, y) in enumerate(cells):
        _add_textbox(slide, x, y, 4.25, 2.6,
                     f"Cell {i + 1}. Short paragraph of body text for cell {i + 1}.", 16)
    # second slide: same grid, longer texts
    slide2 = prs.slides.add_slide(prs.slide_layouts[6])
    _add_textbox(slide2, 0.5, 0.3, 9.0, 0.9, "2x2 Grid, fuller", 32, bold=True)
    for i, (x, y) in enumerate(cells):
        _add_textbox(slide2, x, y, 4.25, 2.6, f"Cell {i + 1}. {LOREM[:140]}", 16)
    prs.save(str(path))


def build_flowchart(path: Path) -> None:
    """Horizontal flowchart: three rounded boxes joined by two connectors."""
    from pptx.util import Inches
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_textbox(slide, 0.5, 0.4, 9.0, 0.9, "Simple Flowchart", 32, bold=True)
    labels = ["Start", "Process", "End"]
    boxes = []
    for i, label in enumerate(labels):
        shape = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(0.8 + i * 3.2), Inches(3.0), Inches(1.8), Inches(1.0),
        )
        shape.text_frame.text = label
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(14)
        boxes.append(shape)
    for a, b in zip(boxes, boxes[1:]):
        conn = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            a.left + a.width, a.top + a.height // 2,
            b.left, b.top + b.height // 2,
        )
        conn.line.width = Pt(1.5)
    prs.save(str(path))


def build_mixed_shapes(path: Path) -> None:
    """Rectangle, oval and a line: basic shape vocabulary for CeTZ."""
    from pptx.util import Inches
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_textbox(slide, 0.5, 0.4, 9.0, 0.9, "Mixed Shapes", 32, bold=True)
    rect = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(1.0), Inches(2.0), Inches(2.5), Inches(1.5))
    rect.text_frame.text = "Box"
    oval = slide.shapes.add_shape(
        MSO_SHAPE.OVAL, Inches(6.0), Inches(4.0), Inches(2.0), Inches(2.0))
    oval.text_frame.text = "Circle"
    for shape in (rect, oval):
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(14)
    slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT,
        rect.left + rect.width, rect.top + rect.height // 2,
        oval.left, oval.top + oval.height // 2,
    )
    prs.save(str(path))


def build_rich_text(path: Path) -> None:
    """Level 1: run styling, alignments, vertical anchoring and bullets."""
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.dml.color import RGBColor
    from pptx.oxml.ns import qn
    from pptx.util import Inches

    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    title = _add_textbox(slide, 0.5, 0.3, 9.0, 0.9, "Rich Text Features", 32, bold=True)
    title.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

    # mixed run styling within one paragraph
    box = slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(4.25), Inches(2.2))
    box.text_frame.word_wrap = True
    p = box.text_frame.paragraphs[0]
    for text, bold, italic, underline, color in [
        ("Plain, ", False, False, False, None),
        ("bold, ", True, False, False, None),
        ("italic, ", False, True, False, None),
        ("underlined, ", False, False, True, None),
        ("and colored words", False, False, False, RGBColor(0xC0, 0x00, 0x00)),
    ]:
        run = p.add_run()
        run.text = text
        run.font.size = Pt(16)
        run.font.bold = bold
        run.font.italic = italic
        run.font.underline = underline
        if color is not None:
            run.font.color.rgb = color
    p2 = box.text_frame.add_paragraph()
    run = p2.add_run()
    run.text = "A second paragraph in the same box."
    run.font.size = Pt(16)

    # bulleted list with two levels
    bullets = slide.shapes.add_textbox(Inches(5.25), Inches(1.5), Inches(4.25), Inches(2.2))
    bullets.text_frame.word_wrap = True
    items = [("First bullet item", 0), ("Second bullet item", 0),
             ("Nested sub-item", 1), ("Third bullet item", 0)]
    for i, (text, level) in enumerate(items):
        p = bullets.text_frame.paragraphs[0] if i == 0 else bullets.text_frame.add_paragraph()
        run = p.add_run()
        run.text = text
        run.font.size = Pt(16)
        p.level = level
        pPr = p._p.get_or_add_pPr()
        bu = pPr.makeelement(qn("a:buChar"), {"char": "•"})
        pPr.append(bu)

    # right-aligned and center-aligned paragraphs
    aligned = _add_textbox(slide, 0.5, 4.2, 4.25, 2.0,
                           "Centered line\nRight-aligned line\nLeft-aligned line", 16)
    aligned.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    aligned.text_frame.paragraphs[1].alignment = PP_ALIGN.RIGHT

    # vertically centered content
    middle = _add_textbox(slide, 5.25, 4.2, 4.25, 2.0,
                          "Vertically centered text", 16)
    middle.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    prs.save(str(path))


def build_placeholder_deck(path: Path) -> None:
    """Level 2: real slide layouts; all styling inherited from the master.

    No run sets an explicit font size, alignment or anchor -- the emitter
    must resolve them through layout/master/txStyles.
    """
    prs = pptx.Presentation()

    slide = prs.slides.add_slide(prs.slide_layouts[0])  # title slide
    slide.shapes.title.text = "Inherited Styles Deck"
    slide.placeholders[1].text = "Subtitle set without any explicit formatting"

    slide2 = prs.slides.add_slide(prs.slide_layouts[1])  # title and content
    slide2.shapes.title.text = "Bullets from the Master"
    body = slide2.placeholders[1].text_frame
    body.text = "Top level point with a reasonable amount of words"
    p = body.add_paragraph()
    p.text = "Second top level point"
    p = body.add_paragraph()
    p.text = "An indented sub-point below it"
    p.level = 1
    p = body.add_paragraph()
    p.text = "Another sub-point on level two"
    p.level = 2
    prs.save(str(path))


# ------------------------------------------------------- Fletcher generator --

def emit_fletcher_flowchart(pptx_path: Path, out_path: Path) -> Path:
    """
    Emit the flowchart PPTX as a Fletcher diagram.

    Unlike the CeTZ emitter (absolute coordinates), Fletcher lays nodes out
    on an elastic grid. We force node boxes to the PPTX shape sizes and set
    the column spacing to the PPTX gap, so positions should land close to
    the truth -- how close is exactly what the verification measures.
    """
    from typstpresenter.verify.method_b import PROBE_PRELUDE
    from typstpresenter.verify.geometry import ElementKind

    truth = extract_pptx_geometry(pptx_path)
    prs = pptx.Presentation(str(pptx_path))
    page_w = prs.slide_width / EMU_PER_PT
    page_h = prs.slide_height / EMU_PER_PT

    slide = truth.slides[0]
    shapes = [e for e in slide.elements if e.kind == ElementKind.SHAPE]
    texts = [e for e in slide.elements if e.kind == ElementKind.TEXT]
    shapes.sort(key=lambda e: e.bbox.x)
    gap = shapes[1].bbox.x - shapes[0].bbox.x2 if len(shapes) > 1 else 20.0

    lines = [
        "// Auto-generated Fletcher pairing for the flowchart corpus case.",
        '#import "@preview/touying:0.6.1": *',
        "#import themes.simple: *",
        f'#import "@preview/fletcher:{FLETCHER_VERSION}" as fletcher: diagram, node, edge',
        "",
        "#show: simple-theme.with(",
        f"  config-page(width: {page_w:g}pt, height: {page_h:g}pt, margin: 0pt),",
        "  config-common(handout: true),",
        "  footer: none,",
        ")",
        '#set text(font: ("Calibri", "Arial", "Liberation Sans"))',
        "",
        PROBE_PRELUDE,
        "#slide[",
    ]
    for el in texts:
        b = el.bbox
        lines.append(
            f'  #tp-probe("{el.id}", {b.x:.2f}pt, {b.y:.2f}pt, {b.w:.2f}pt, {b.h:.2f}pt)'
            f"[#text(size: 32pt, weight: \"bold\")[{escape_typst(el.text)}]]"
        )
    connectors = [e for e in slide.elements if e.kind == ElementKind.CONNECTOR]
    connectors.sort(key=lambda e: e.bbox.x)
    first = shapes[0].bbox
    lines.append(f"  #place(top + left, dx: {first.x:.2f}pt, dy: {first.y:.2f}pt, diagram(")
    lines.append("    node-inset: 0pt,")
    lines.append(f"    spacing: ({gap:.2f}pt, {gap:.2f}pt),")
    lines.append("    node-stroke: 0.75pt,")
    for i, el in enumerate(shapes):
        b = el.bbox
        label = (
            f"#box(width: {b.w:.2f}pt, height: {b.h:.2f}pt, "
            f'align(center + horizon)[#tp-node-probe("{el.id}")#text(size: 14pt)[{escape_typst(el.text)}]])'
        )
        lines.append(f"    node(({i}, 0), [{label}], corner-radius: 4pt),")
        if i < len(shapes) - 1:
            # probe the connector via the edge label (placed at edge midpoint)
            conn_id = connectors[i].id if i < len(connectors) else None
            probe = f'[#tp-node-probe("{conn_id}")]' if conn_id else "none"
            lines.append(f'    edge("-|>", label: {probe}, label-sep: 0pt),')
    lines.append("  ))")
    lines.append("]")
    out_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return out_path


# ------------------------------------------------------------ corpus driver --

# Static registry: name -> (pptx builder, case kind). Cases added by the
# autoresearch loop go here; tests parametrize over these names.
BUILDERS = {
    "layout_title_content": (build_title_content, "layout"),
    "layout_two_columns": (build_two_columns, "layout"),
    "layout_grid": (build_grid, "layout"),
    "diagram_flowchart": (build_flowchart, "diagram-cetz"),
    "diagram_mixed_shapes": (build_mixed_shapes, "diagram-cetz"),
    # autoresearch level 1: rich text
    "layout_rich_text": (build_rich_text, "layout"),
    # autoresearch level 2: placeholder layouts with inherited styles
    "layout_placeholders": (build_placeholder_deck, "layout"),
}

FAULT_VARIANTS = ("moved", "overflow", "resized", "missing", "extra_text")


def clean_case_names() -> list[str]:
    return [*BUILDERS, "diagram_flowchart_fletcher"]


def fault_case_names() -> list[str]:
    return [f"layout_two_columns_faulty_{v}" for v in FAULT_VARIANTS]


def _find_id(truth: DocGeometry, text_prefix: str) -> str:
    for _, el in truth.all_elements():
        if el.text.startswith(text_prefix):
            assert el.id is not None
            return el.id
    raise KeyError(f"no element starting with '{text_prefix}'")


def generate_corpus(out_dir: Path | str) -> list[CorpusCase]:
    """Build all PPTX files, paired Typst files and fault variants."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases: list[CorpusCase] = []

    for name, (builder, kind) in BUILDERS.items():
        pptx_path = out_dir / f"{name}.pptx"
        builder(pptx_path)
        truth = extract_pptx_geometry(pptx_path)
        typ_path = out_dir / f"{name}.typ"
        emit_touying(pptx_path, typ_path)
        cases.append(CorpusCase(name=name, pptx_path=pptx_path, typ_path=typ_path,
                                truth=truth, kind=kind))

    # Fletcher pairing of the flowchart
    flow_pptx = out_dir / "diagram_flowchart.pptx"
    fletcher_typ = out_dir / "diagram_flowchart_fletcher.typ"
    emit_fletcher_flowchart(flow_pptx, fletcher_typ)
    cases.append(CorpusCase(
        name="diagram_flowchart_fletcher", pptx_path=flow_pptx,
        typ_path=fletcher_typ, truth=extract_pptx_geometry(flow_pptx),
        kind="diagram-fletcher",
    ))

    # Fault-injected variants of the two-column layout
    two_col_pptx = out_dir / "layout_two_columns.pptx"
    truth = extract_pptx_geometry(two_col_pptx)
    title_id = _find_id(truth, "Two Columns")
    left_id = _find_id(truth, "Left column.")
    right_id = _find_id(truth, "Right column.")

    fault_sets: dict[str, tuple[Fault, ...]] = {
        "faulty_moved": (Fault(title_id, dx=25.0, dy=15.0),),
        "faulty_overflow": (Fault(left_id, scale_h=0.35),),
        "faulty_resized": (Fault(right_id, scale_w=0.55),),
        "faulty_missing": (Fault(left_id, drop=True),),
        "faulty_extra_text": (Fault(
            right_id,
            extra_text="This extra sentence was injected to trigger a text "
                       "overflow beyond the designated placeholder box, with "
                       "some padding words to make absolutely sure. " + LOREM,
        ),),
    }
    for variant, faults in fault_sets.items():
        typ_path = out_dir / f"layout_two_columns_{variant}.typ"
        emit_touying(two_col_pptx, typ_path, faults=faults)
        cases.append(CorpusCase(
            name=f"layout_two_columns_{variant}", pptx_path=two_col_pptx,
            typ_path=typ_path, truth=truth,
            expected_issues_b={f.element_id: f.expected_issues() for f in faults},
            expected_issues_a={f.element_id: f.expected_issues_ink() for f in faults},
            allows_extra_text=any(f.extra_text for f in faults),
            kind="layout",
        ))
    return cases
