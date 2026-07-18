"""
Tests for Method D (diagram/connector translation fidelity in flow mode).

Progression, per the diagram-benchmark task: simple single-canvas
synthetic diagrams first (exact shape/color/connector-topology checks),
then the real IBN decks (Method D abstains where a page is too visually
complex to attribute confidently -- tables, dense multi-diagram slides --
so those runs mainly assert it doesn't *mis*-report on the slides it does
check).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from typstpresenter.convert.emitter import emit_minimal
from typstpresenter.verify.corpus import BUILDERS
from typstpresenter.verify.method_d import verify_diagrams
from typstpresenter.verify.typst_tools import compile_pdf

pytestmark = pytest.mark.skipif(
    shutil.which("typst") is None, reason="typst CLI not on PATH"
)

DATA = Path(__file__).parent / "data"

# every synthetic diagram case in the corpus registry, checked in flow mode
DIAGRAM_CASES = [name for name, (_, kind) in BUILDERS.items()
                 if kind == "diagram-cetz"]


@pytest.mark.parametrize("name", DIAGRAM_CASES)
def test_synthetic_diagram_is_faithful(tmp_path, name):
    builder, _ = BUILDERS[name]
    pptx_path = tmp_path / f"{name}.pptx"
    builder(pptx_path)
    typ_path = tmp_path / f"{name}.typ"
    emit_minimal(pptx_path, typ_path)
    compile_pdf(typ_path)

    report = verify_diagrams(pptx_path, typ_path.with_suffix(".pdf"))
    assert report.checked_slides >= 1, "Method D abstained on a simple synthetic deck"
    assert report.ok, report.summary()


def test_freeform_renders_as_polygon_not_bbox(tmp_path):
    """Regression guard: freeform shapes were briefly (this session)
    misclassified as connectors and drawn as a bogus diagonal line across
    their own bounding box -- not even the documented bbox fallback."""
    from typstpresenter.verify.corpus import build_freeform_shapes

    pptx_path = tmp_path / "freeform.pptx"
    build_freeform_shapes(pptx_path)
    typ_path = tmp_path / "freeform.typ"
    emit_minimal(pptx_path, typ_path)
    source = typ_path.read_text(encoding="utf-8")
    # a real polygon has several vertices; a bbox or a bogus diagonal line
    # would have at most 2 point pairs on the line(...) call
    assert source.count("line((") >= 2
    for call_line in (l for l in source.splitlines() if "line((" in l):
        assert call_line.count("(") >= 8, (
            "freeform shape drawn with too few vertices -- looks like a "
            f"bbox/line fallback, not the actual polygon: {call_line}")


def test_rotation_is_applied(tmp_path):
    """Regression guard: shape rotation used to be silently ignored."""
    from typstpresenter.verify.corpus import build_rotated_shapes

    pptx_path = tmp_path / "rotated.pptx"
    build_rotated_shapes(pptx_path)
    typ_path = tmp_path / "rotated.typ"
    emit_minimal(pptx_path, typ_path)
    source = typ_path.read_text(encoding="utf-8")
    assert "rotate(" in source


@pytest.mark.parametrize("deck", ["talk_example_a.pptx", "two_content.pptx"])
def test_data_decks_diagram_check_does_not_misreport(tmp_path, deck):
    """Decks without (talk_example_a has none) or with only simple diagram
    content must not produce false positives; Method D may abstain."""
    src = DATA / deck
    if not src.exists():
        pytest.skip(f"{deck} not available")
    pptx_path = tmp_path / deck
    pptx_path.write_bytes(src.read_bytes())
    typ_path = pptx_path.with_suffix(".typ")
    emit_minimal(pptx_path, typ_path)
    compile_pdf(typ_path)
    report = verify_diagrams(pptx_path, typ_path.with_suffix(".pdf"))
    assert report.ok, report.summary()
