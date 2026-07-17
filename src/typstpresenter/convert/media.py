"""Pictures and tables as Typst markup."""

from __future__ import annotations

from pathlib import Path

from typstpresenter.convert.textbody import paragraph_runs_markup
from typstpresenter.verify.geometry import EMU_PER_PT

# formats the typst `image` function can load directly
_TYPST_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "svg", "webp"}


def emit_picture(shape, eid: str, media_dir: Path) -> str:
    """Write the picture blob and return typst markup for it.

    Formats typst cannot load (wmf, emf, tiff, bmp) are converted to PNG
    via Pillow when possible; otherwise a placeholder frame keeps the
    geometry intact.
    """
    from typstpresenter.verify.pptx_geometry import picture_image

    image = picture_image(shape)
    if image is None:
        return ('#rect(width: 100%, height: 100%, stroke: 0.5pt + gray)'
                '// picture without image data')
    ext = image.ext.lower()
    if ext in _TYPST_IMAGE_EXTS:
        filename = f"{eid}.{ext}"
        (media_dir / filename).write_bytes(image.blob)
        return f'#image("{media_dir.name}/{filename}", width: 100%, height: 100%)'
    try:
        import io

        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(image.blob)) as im:
            filename = f"{eid}.png"
            im.convert("RGBA").save(media_dir / filename)
        return f'#image("{media_dir.name}/{filename}", width: 100%, height: 100%)'
    except Exception:
        return ('#rect(width: 100%, height: 100%, stroke: 0.5pt + gray)'
                f'// unsupported image format: {ext}')


def emit_table(shape, default_size: float) -> str:
    """A PPTX table as a Typst table with the exact column/row extents."""
    table = shape.table
    columns = ", ".join(f"{c.width / EMU_PER_PT:.2f}pt" for c in table.columns)
    rows = ", ".join(f"{r.height / EMU_PER_PT:.2f}pt" for r in table.rows)
    cells = []
    for row in table.rows:
        for cell in row.cells:
            runs = []
            for paragraph in cell.text_frame.paragraphs:
                runs += paragraph_runs_markup(paragraph, shape, default_size)
            cells.append(f"  [{''.join(runs)}],")
    header = (f"#table(\n  columns: ({columns}),\n  rows: ({rows}),\n"
              "  inset: 3pt, stroke: 0.5pt,\n")
    return header + "\n".join(cells) + "\n)"
