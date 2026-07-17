"""
Tests for the idiomatic flow emitter (minimal mode) and Method S.

The contract of minimal mode: human-editable Typst (native lists and
headings, no #place, no probes) that compiles to exactly one page per
slide with no text/image collisions.
"""

import shutil
from pathlib import Path

import pytest

from typstpresenter.convert.emitter import emit_minimal
from typstpresenter.convert.flow import (
    _paragraph_inline,
    escape_flow,
    guard_markup_start,
)
from typstpresenter.verify.method_s import source_metrics, verify_minimal

pytestmark = pytest.mark.skipif(
    shutil.which("typst") is None, reason="typst CLI not on PATH"
)

DATA = Path(__file__).parent / "data"


def test_escape_flow_keeps_text_readable():
    assert escape_flow("Metadaten-Extraktion") == "Metadaten-Extraktion"
    assert escape_flow("C# and $x$") == "C\\# and \\$x\\$"


def test_escape_flow_neutralizes_comments():
    assert "//" not in escape_flow("int x; // counter")
    assert "//" not in escape_flow("http://example.org".replace(":", ""))


def test_guard_markup_start():
    assert guard_markup_start("- item") == "\\- item"
    assert guard_markup_start("/ term") == "\\/ term"
    assert guard_markup_start("= heading") == "\\= heading"
    assert guard_markup_start("1. numbered") == "1\\. numbered"
    assert guard_markup_start("plain") == "plain"
    assert guard_markup_start("  + indented") == "  \\+ indented"


def test_inline_hash_expression_guarded_against_call_chain():
    red = (18.0, False, False, False, "FF0000", None)
    plain = (18.0, False, False, False, None, None)
    markup = _paragraph_inline([("Hosts ", red), ("(Endsysteme)", plain)], 18.0)
    # without the ';' the '(' would be parsed as a call on the #text result
    assert "];(" in markup


def test_inline_hyperlink_becomes_link():
    linked = (18.0, False, False, False, None, "https://example.org/x?a=1")
    markup = _paragraph_inline([("see here", linked)], 18.0)
    assert markup == '#link("https://example.org/x?a=1")[see here]'


@pytest.mark.skipif(not (DATA / "simple.pptx").exists(),
                    reason="simple.pptx not available")
def test_simple_deck_is_idiomatic_and_sane(tmp_path):
    pptx_path = tmp_path / "simple.pptx"
    pptx_path.write_bytes((DATA / "simple.pptx").read_bytes())
    typ_path = tmp_path / "simple.typ"
    emit_minimal(pptx_path, typ_path)
    source = typ_path.read_text(encoding="utf-8")

    assert "== Slide 1 Title" in source
    assert "- This is a bullet point" in source
    metrics = source_metrics(source)
    assert metrics.place_calls == 0
    assert metrics.probe_defs == 0

    report = verify_minimal(typ_path, pptx_path)
    assert report.ok, report.summary()


@pytest.mark.parametrize("deck", ["two_content.pptx", "multi_content.pptx",
                                  "media.pptx", "talk_example_a.pptx"])
def test_data_decks_flow_clean(tmp_path, deck):
    src = DATA / deck
    if not src.exists():
        pytest.skip(f"{deck} not available")
    pptx_path = tmp_path / deck
    pptx_path.write_bytes(src.read_bytes())
    typ_path = pptx_path.with_suffix(".typ")
    emit_minimal(pptx_path, typ_path)
    report = verify_minimal(typ_path, pptx_path)
    assert report.ok, report.summary()
