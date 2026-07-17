"""Text frames as Typst markup: styled runs, paragraphs, line metrics."""

from __future__ import annotations

from typstpresenter.convert.markup import escape_typst
from typstpresenter.convert.pptx_inherit import (
    resolve_alignment,
    resolve_anchor,
    resolve_bullet,
    resolve_font_size_pt,
    resolve_space_before,
)

# Line metrics for the emitted font stack (Calibri): PowerPoint's single
# line pitch is ascent+descent+lineGap ~ 1.22 em; typst renders a line as
# cap-height+descender ~ 0.632 em plus `leading`. Matching the two gives
# the leading that reproduces PowerPoint's vertical rhythm.
PPT_LINE_PITCH_EM = 1.22
TYPST_LINE_HEIGHT_EM = 0.632


def autofit_scales(shape) -> tuple[float, float]:
    """(fontScale, lnSpcReduction) from a:normAutofit, defaults (1, 0)."""
    from pptx.oxml.ns import qn

    bodyPr = shape.text_frame._txBody.find(qn("a:bodyPr"))
    fit = bodyPr.find(qn("a:normAutofit")) if bodyPr is not None else None
    if fit is None:
        return 1.0, 0.0
    font_scale = int(fit.get("fontScale") or 100000) / 100000.0
    lnspc_red = int(fit.get("lnSpcReduction") or 0) / 100000.0
    return font_scale, lnspc_red


def run_size_pt(run, paragraph, shape, default: float, scale: float = 1.0) -> float:
    resolved = resolve_font_size_pt(run, paragraph, shape)
    return (resolved if resolved is not None else default) * scale


def _run_color(run) -> str | None:
    color = run.font.color
    try:
        if color and color.type is not None and color.rgb is not None:
            return str(color.rgb)
    except AttributeError:
        pass
    return None


def run_style(run, paragraph, shape, default_size: float, scale: float = 1.0,
              default_color: str | None = None) -> tuple:
    """Style signature of a run: (size, bold, italic, underline, color)."""
    return (
        round(run_size_pt(run, paragraph, shape, default_size, scale), 2),
        bool(run.font.bold),
        bool(run.font.italic),
        bool(run.font.underline),
        _run_color(run) or default_color,
    )


def styled_text(style: tuple, text: str) -> str:
    size, bold, italic, underline, rgb = style
    args = [f"size: {size:g}pt"]
    if bold:
        args.append('weight: "bold"')
    if italic:
        args.append('style: "italic"')
    if rgb:
        args.append(f'fill: rgb("#{rgb}")')
    inner = escape_typst(text)
    if underline:
        inner = f"#underline[{inner}]"
    return f"#text({', '.join(args)})[{inner}]"


def paragraph_run_chunks(paragraph, shape, default_size: float,
                         scale: float = 1.0,
                         default_color: str | None = None,
                         breaks: bool = False) -> list[tuple[str, tuple]]:
    """(text, style) chunks of a paragraph, merging equal-styled neighbors.

    Merging matters beyond cleanliness: a chain of separate #text() calls
    gives the line breaker a break opportunity at every run boundary, which
    shreds formula-styled text (many tiny runs) into one word per line.

    With ``breaks=True``, explicit line breaks (``a:br``) become ``\\n``
    characters inside the chunk text (used by the flow emitter; the probed
    emitter keeps its historical merging behavior).
    """
    from pptx.oxml.ns import qn

    chunks: list[tuple[str, tuple]] = []

    def _append(text: str, style: tuple) -> None:
        if chunks and chunks[-1][1] == style:
            chunks[-1] = (chunks[-1][0] + text, style)
        else:
            chunks.append((text, style))

    runs = iter(paragraph.runs)
    default_style = None
    for child in paragraph._p:
        tag = child.tag
        if tag == qn("a:r"):
            run = next(runs)
            if run.text:
                style = run_style(run, paragraph, shape, default_size, scale,
                                  default_color)
                default_style = style
                _append(run.text, style)
        elif tag == qn("a:br") and breaks and chunks:
            _append("\n", default_style or chunks[-1][1])
        elif tag == qn("a:fld"):
            # fields (slide number, date) are not exposed as runs; emit
            # their cached text with the paragraph's default styling
            t = child.find(qn("a:t"))
            if t is not None and t.text:
                size = round(run_size_pt(None, paragraph, shape, default_size,
                                         scale), 2)
                _append(t.text, (size, False, False, False, default_color))
    # trailing breaks render as stray backslashes; drop them
    while chunks and not chunks[-1][0].strip("\n") and "\n" in chunks[-1][0]:
        chunks.pop()
    if chunks and chunks[-1][0].endswith("\n"):
        chunks[-1] = (chunks[-1][0].rstrip("\n"), chunks[-1][1])
    return chunks


def paragraph_runs_markup(paragraph, shape, default_size: float,
                          scale: float = 1.0,
                          default_color: str | None = None) -> list[str]:
    """Runs of a paragraph as Typst markup, merging equal-styled neighbors."""
    return [
        styled_text(style, text)
        for text, style in paragraph_run_chunks(
            paragraph, shape, default_size, scale, default_color)
    ]


def typst_align(paragraph, shape) -> str | None:
    from pptx.enum.text import PP_ALIGN

    alignment = resolve_alignment(paragraph, shape)
    return {PP_ALIGN.CENTER: "center", PP_ALIGN.RIGHT: "right"}.get(alignment)


def emit_text_body(shape, default_size: float, extra_text: str,
                   extra_scale: float = 1.0) -> str:
    """Render the paragraphs of a text frame as Typst markup."""
    from pptx.enum.text import MSO_ANCHOR

    font_scale, lnspc_red = autofit_scales(shape)
    font_scale *= extra_scale
    leading_em = max(
        PPT_LINE_PITCH_EM * (1.0 - lnspc_red) - TYPST_LINE_HEIGHT_EM, 0.1
    )
    parts: list[str] = [
        # em-based leading/spacing resolve against the *context* text size;
        # scale it with the autofit factor, otherwise paragraph gaps form a
        # fixed floor and many-paragraph bodies cannot shrink to fit
        f"#set text(size: {default_size * font_scale:.2f}pt)",
        f"#set par(leading: {leading_em:.3f}em, spacing: {leading_em:.3f}em)"
    ]
    first_paragraph = True
    for paragraph in shape.text_frame.paragraphs:
        runs = paragraph_runs_markup(paragraph, shape, default_size, font_scale)
        if not runs:
            continue
        para_size = run_size_pt(
            paragraph.runs[0] if paragraph.runs else None,
            paragraph, shape, default_size, font_scale,
        )
        spc_bef = resolve_space_before(paragraph, shape)
        if spc_bef and not first_paragraph:
            kind, value = spc_bef
            if kind == "pct":
                gap = value * PPT_LINE_PITCH_EM * para_size  # para_size is scaled
            else:
                # PowerPoint's autofit scales point-based paragraph spacing
                # along with the text; without this, many-paragraph bodies
                # keep a fixed spacing floor and shrink cannot converge
                gap = value * font_scale * (1.0 - lnspc_red)
            parts.append(f"#v({gap:.2f}pt)")
        prefix = ""
        indent = paragraph.level * 18.0
        if indent:
            prefix += f"#h({indent:g}pt)"
        bullet = resolve_bullet(paragraph, shape)
        if bullet:
            if len(bullet) == 1 and 0xE000 <= ord(bullet) <= 0xF8FF:
                bullet = "•"
            # size the bullet like its paragraph so it doesn't set the pitch
            prefix += f"#text(size: {para_size:.4g}pt)[{escape_typst(bullet)} ]"
        line = f"#par(hanging-indent: 0pt)[{prefix}{''.join(runs)}]"
        align = typst_align(paragraph, shape)
        if align:
            line = f"#align({align})[{line}]"
        parts.append(line)
        first_paragraph = False
    if extra_text:
        parts.append(f"#par[#text(size: {default_size:g}pt)[{escape_typst(extra_text)}]]")
    content = "\n".join(parts)
    anchor = resolve_anchor(shape)
    if anchor == MSO_ANCHOR.MIDDLE:
        content = f"#align(horizon)[\n{content}\n]"
    elif anchor == MSO_ANCHOR.BOTTOM:
        content = f"#align(bottom)[\n{content}\n]"
    return content
