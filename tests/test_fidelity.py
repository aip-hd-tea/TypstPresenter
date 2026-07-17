"""
Tests for Method F (structural fidelity between PPTX source and PDF).

talk_example_a.pptx is the reference deck: it contains a title-layout
slide, placeholder pictures, column layouts with pictures, hyperlinks and
image pairs -- each a fidelity aspect Method F guards.
"""

import shutil
from pathlib import Path

import pytest

from typstpresenter.convert.emitter import emit_minimal
from typstpresenter.verify.method_f import verify_fidelity

pytestmark = pytest.mark.skipif(
    shutil.which("typst") is None, reason="typst CLI not on PATH"
)

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def talk(tmp_path_factory):
    """Emitted + compiled talk_example_a (shared by the module's tests)."""
    from typstpresenter.verify.typst_tools import compile_pdf

    src = DATA / "talk_example_a.pptx"
    if not src.exists():
        pytest.skip("talk_example_a.pptx not available")
    tmp_path = tmp_path_factory.mktemp("talk")
    pptx_path = tmp_path / src.name
    pptx_path.write_bytes(src.read_bytes())
    typ_path = pptx_path.with_suffix(".typ")
    emit_minimal(pptx_path, typ_path)
    compile_pdf(typ_path)
    return pptx_path, typ_path


def test_talk_example_a_is_faithful(talk):
    pptx_path, typ_path = talk
    report = verify_fidelity(pptx_path, typ_path.with_suffix(".pdf"))
    assert report.ok, report.summary()


def test_talk_example_a_uses_expected_constructs(talk):
    _, typ_path = talk
    source = typ_path.read_text(encoding="utf-8")
    # title-layout slide is a real centered title slide, at the source size
    assert "#title-slide[" in source
    assert "#text(size: 60pt)[This is a Title of a Talk]" in source
    # slide headings carry the resolved source title size, not the theme em
    assert 'text(44pt, weight: "bold"' in source
    # hyperlinks survive
    assert '#link("https://phdcomics.com/' in source
    # placeholder pictures are emitted like any picture (slides 2 and 3)
    assert source.count("#image(") + source.count(", image(") >= 8


def test_fidelity_flags_missing_image_and_shrunk_title(talk, tmp_path):
    from typstpresenter.verify.typst_tools import compile_pdf

    pptx_path, typ_path = talk
    doctored = tmp_path / "doctored.typ"
    source = typ_path.read_text(encoding="utf-8")
    # drop slide 2's picture and shrink every heading to 20pt
    source = source.replace(
        '#align(center, image("talk_example_a_media/s1-e5.png", width: 335pt))', "")
    source = source.replace('text(44pt, weight: "bold"',
                            'text(20pt, weight: "bold"')
    media = typ_path.parent / "talk_example_a_media"
    shutil.copytree(media, tmp_path / media.name)
    doctored.write_text(source, encoding="utf-8")
    compile_pdf(doctored)

    report = verify_fidelity(pptx_path, doctored.with_suffix(".pdf"))
    assert any("source images rendered" in i for i in report.issues)
    assert any("title rendered at" in i for i in report.issues)
