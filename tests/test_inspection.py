"""Tests for the inspection module.

Most tests use ``tests/data/talk_example_a.pptx`` as the source PPTX.
PDF-based tests are either self-contained (using mock SlideIR objects) or
skipped when a compiled PDF is not present.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from typstpresenter.inspection import (
    BoundingBox,
    ElementIR,
    PresentationIR,
    SlideIR,
    compare_presentations,
    compare_slides,
    pdf_to_presentation_ir,
    pptx_to_presentation_ir,
    slide_to_ir,
)
from typstpresenter.model.Presentation import Presentation

TALK_PPTX = Path(__file__).parent / "data" / "talk_example_a.pptx"
TALK_PDF = Path(__file__).parent / "data" / "talk_example_a.pdf"


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(scope="module")
def talk_pptx_ir() -> PresentationIR:
    assert TALK_PPTX.exists(), "Missing test fixture: tests/data/talk_example_a.pptx"
    return pptx_to_presentation_ir(TALK_PPTX)


@pytest.fixture(scope="module")
def talk_prs() -> Presentation:
    assert TALK_PPTX.exists(), "Missing test fixture: tests/data/talk_example_a.pptx"
    return Presentation.from_file(TALK_PPTX)


# ===========================================================================
# BoundingBox unit tests
# ===========================================================================

class TestBoundingBox:
    def test_centre_of_slide(self):
        box = BoundingBox(left=0.25, top=0.25, width=0.5, height=0.5)
        cx = box.left + box.width / 2
        cy = box.top + box.height / 2
        assert cx == pytest.approx(0.5)
        assert cy == pytest.approx(0.5)

    def test_overlaps_same_box(self):
        box = BoundingBox(left=0.1, top=0.1, width=0.4, height=0.4)
        assert box.overlaps(box)

    def test_overlaps_adjacent(self):
        a = BoundingBox(left=0.0, top=0.0, width=0.5, height=0.5)
        b = BoundingBox(left=0.5, top=0.0, width=0.5, height=0.5)
        # Exactly adjacent – overlaps within default tolerance=0.05
        assert a.overlaps(b, tolerance=0.05)

    def test_no_overlap_far_apart(self):
        a = BoundingBox(left=0.0, top=0.0, width=0.2, height=0.2)
        b = BoundingBox(left=0.8, top=0.8, width=0.2, height=0.2)
        assert not a.overlaps(b, tolerance=0.0)

    def test_center_distance_identical(self):
        box = BoundingBox(left=0.1, top=0.1, width=0.4, height=0.4)
        assert box.center_distance(box) == pytest.approx(0.0)

    def test_center_distance_known(self):
        a = BoundingBox(left=0.0, top=0.0, width=0.0, height=0.0)  # centre at (0,0)
        b = BoundingBox(left=0.3, top=0.4, width=0.0, height=0.0)  # centre at (0.3, 0.4)
        assert a.center_distance(b) == pytest.approx(0.5)

    def test_to_dict_rounds_to_4_decimal_places(self):
        box = BoundingBox(left=1 / 3, top=1 / 7, width=1 / 6, height=1 / 9)
        d = box.to_dict()
        for key in ("left", "top", "width", "height"):
            assert len(str(d[key]).rstrip("0").split(".")[-1]) <= 4


# ===========================================================================
# ElementIR unit tests
# ===========================================================================

class TestElementIR:
    def test_all_text_fragments_text_element(self):
        elem = ElementIR(kind="text", bounds=None, text="Hello world")
        assert elem.all_text_fragments() == ["Hello world"]

    def test_all_text_fragments_list_element(self):
        elem = ElementIR(kind="list", bounds=None, items=["item a", "item b", "  nested"])
        frags = elem.all_text_fragments()
        assert "item a" in frags
        assert "item b" in frags

    def test_all_text_fragments_image_element(self):
        elem = ElementIR(kind="image", bounds=None, image_name="foo.png")
        assert elem.all_text_fragments() == []

    def test_to_dict_includes_only_set_fields(self):
        elem = ElementIR(kind="title", bounds=None, text="My Title")
        d = elem.to_dict()
        assert d["kind"] == "title"
        assert d["text"] == "My Title"
        assert "items" not in d
        assert "image_name" not in d
        assert "bounds" not in d

    def test_to_dict_with_bounds(self):
        box = BoundingBox(0.1, 0.05, 0.8, 0.12)
        elem = ElementIR(kind="title", bounds=box, text="Hello")
        d = elem.to_dict()
        assert "bounds" in d
        assert d["bounds"]["left"] == pytest.approx(0.1)


# ===========================================================================
# SlideIR and PresentationIR YAML serialization
# ===========================================================================

class TestYamlSerialization:
    def test_slide_ir_to_yaml_is_valid_yaml(self, talk_pptx_ir: PresentationIR):
        slide = talk_pptx_ir.slides[0]
        yml = slide.to_yaml()
        parsed = yaml.safe_load(yml)
        assert isinstance(parsed, dict)
        assert "index" in parsed
        assert "elements" in parsed

    def test_slide_ir_yaml_contains_title(self, talk_pptx_ir: PresentationIR):
        slide = talk_pptx_ir.slides[0]
        yml = slide.to_yaml()
        if slide.title:
            assert slide.title in yml

    def test_presentation_ir_to_yaml_is_valid_yaml(self, talk_pptx_ir: PresentationIR):
        yml = talk_pptx_ir.to_yaml()
        parsed = yaml.safe_load(yml)
        assert isinstance(parsed, dict)
        assert "title" in parsed
        assert "slides" in parsed
        assert isinstance(parsed["slides"], list)

    def test_presentation_ir_yaml_round_trip(self, talk_pptx_ir: PresentationIR):
        yml = talk_pptx_ir.to_yaml()
        parsed = yaml.safe_load(yml)
        assert parsed["title"] == talk_pptx_ir.title
        assert len(parsed["slides"]) == len(talk_pptx_ir.slides)


# ===========================================================================
# PPTX → IR (pptx_to_presentation_ir / slide_to_ir)
# ===========================================================================

class TestPptxToIr:
    def test_presentation_title_extracted(self, talk_pptx_ir: PresentationIR):
        assert talk_pptx_ir.title is not None
        assert "Title" in talk_pptx_ir.title or len(talk_pptx_ir.title) > 3

    def test_correct_slide_count(self, talk_pptx_ir: PresentationIR):
        # talk_example_a has 8 content slides (first slide is title slide)
        assert len(talk_pptx_ir.slides) == 8

    def test_each_slide_has_index(self, talk_pptx_ir: PresentationIR):
        for i, slide in enumerate(talk_pptx_ir.slides):
            assert slide.index == i

    def test_first_slide_has_title(self, talk_pptx_ir: PresentationIR):
        # Slide 0 is "Title: Just a Figure"
        assert talk_pptx_ir.slides[0].title is not None
        assert "Figure" in talk_pptx_ir.slides[0].title

    def test_slide_with_list_has_list_element(self, talk_pptx_ir: PresentationIR):
        # Slide 1: "Title: Text left, Figure right" - contains a List
        slide = talk_pptx_ir.slides[1]
        kinds = [e.kind for e in slide.elements]
        assert "list" in kinds

    def test_slide_with_list_items_not_empty(self, talk_pptx_ir: PresentationIR):
        slide = talk_pptx_ir.slides[1]
        list_elements = [e for e in slide.elements if e.kind == "list"]
        assert list_elements
        assert any(len(e.items or []) > 0 for e in list_elements)

    def test_slide_with_image_has_image_element(self, talk_pptx_ir: PresentationIR):
        # Slide 2: "Title: Small figure on the bottom right" contains an Image
        slide = talk_pptx_ir.slides[2]
        kinds = [e.kind for e in slide.elements]
        assert "image" in kinds

    def test_bounds_are_relative(self, talk_pptx_ir: PresentationIR):
        for slide in talk_pptx_ir.slides:
            for elem in slide.elements:
                if elem.bounds:
                    assert 0.0 <= elem.bounds.left <= 1.0, f"left out of range: {elem.bounds.left}"
                    assert 0.0 <= elem.bounds.top <= 1.0, f"top out of range: {elem.bounds.top}"
                    assert 0.0 <= elem.bounds.width <= 1.0, f"width out of range: {elem.bounds.width}"
                    assert 0.0 <= elem.bounds.height <= 1.0, f"height out of range: {elem.bounds.height}"

    def test_title_element_is_near_top(self, talk_pptx_ir: PresentationIR):
        for slide in talk_pptx_ir.slides:
            title_elements = [e for e in slide.elements if e.kind == "title"]
            for te in title_elements:
                if te.bounds:
                    assert te.bounds.top < 0.30, (
                        f"Title element not near top of slide: top={te.bounds.top}"
                    )

    def test_slide_to_ir_uses_custom_dimensions(self, talk_prs: Presentation):
        slide = talk_prs.slides[0]
        # Use half-size dimensions → coords should double (clamped to meaningful range)
        ir_standard = slide_to_ir(slide, 0, slide_width=9144000, slide_height=6858000)
        ir_half = slide_to_ir(slide, 0, slide_width=4572000, slide_height=3429000)
        for es, eh in zip(ir_standard.elements, ir_half.elements):
            if es.bounds and eh.bounds:
                assert eh.bounds.left == pytest.approx(es.bounds.left * 2, abs=1e-3)

    def test_all_text_fragments_non_empty(self, talk_pptx_ir: PresentationIR):
        for slide in talk_pptx_ir.slides:
            frags = slide.all_text_fragments()
            assert frags, f"Slide {slide.index} has no text fragments"

    def test_presentation_ir_to_dict_structure(self, talk_pptx_ir: PresentationIR):
        d = talk_pptx_ir.to_dict()
        assert set(d.keys()) >= {"title", "slides"}
        for s in d["slides"]:
            assert "index" in s
            assert "title" in s
            assert "elements" in s


# ===========================================================================
# Comparison: compare_slides
# ===========================================================================

class TestCompareSlides:
    def _make_slide(self, index: int, title: str, texts: list[str]) -> SlideIR:
        elements = [ElementIR(kind="title", bounds=BoundingBox(0.05, 0.05, 0.9, 0.1), text=title)]
        for i, t in enumerate(texts):
            bounds = BoundingBox(0.05, 0.2 + i * 0.15, 0.9, 0.12)
            elements.append(ElementIR(kind="text", bounds=bounds, text=t))
        return SlideIR(index=index, title=title, elements=elements)

    def test_identical_slides_match(self):
        slide = self._make_slide(0, "My Title", ["Text A", "Text B"])
        result = compare_slides(slide, slide)
        assert result.is_match
        assert result.title_match
        assert result.text_coverage == pytest.approx(1.0)
        assert result.missing_fragments == []

    def test_same_text_different_case(self):
        source = self._make_slide(0, "My Title", ["Hello World"])
        target = self._make_slide(0, "my title", ["hello world"])
        result = compare_slides(source, target)
        assert result.title_match
        assert result.text_coverage == pytest.approx(1.0)

    def test_completely_different_slides_no_match(self):
        source = self._make_slide(0, "Source Title", ["unique alpha text content"])
        target = self._make_slide(1, "Target Title", ["zeta omega theta kappa"])
        result = compare_slides(source, target)
        assert not result.is_match

    def test_partial_text_coverage(self):
        source = self._make_slide(0, "Title", ["Text present", "Text missing xyz"])
        # Target contains first but not second fragment
        target = SlideIR(
            index=0,
            title="Title",
            elements=[
                ElementIR(kind="title", bounds=None, text="Title"),
                ElementIR(kind="text", bounds=None, text="Text present"),
            ],
        )
        result = compare_slides(source, target)
        assert result.text_coverage < 1.0
        assert any("Text missing xyz" in f for f in result.missing_fragments)

    def test_title_similarity_in_result(self):
        source = self._make_slide(0, "Introduction to Machine Learning", [])
        target = self._make_slide(0, "introduction to machine learning", [])
        result = compare_slides(source, target)
        assert result.title_similarity > 0.95

    def test_empty_slide_matches_empty(self):
        s1 = SlideIR(index=0, title=None, elements=[])
        s2 = SlideIR(index=0, title=None, elements=[])
        result = compare_slides(s1, s2)
        assert result.is_match

    def test_position_match_for_overlapping_boxes(self):
        box_a = BoundingBox(0.1, 0.1, 0.4, 0.4)
        box_b = BoundingBox(0.12, 0.12, 0.38, 0.38)
        assert box_a.overlaps(box_b)

    def test_element_count_captured(self):
        source = self._make_slide(0, "T", ["A", "B", "C"])
        target = self._make_slide(0, "T", ["A"])
        result = compare_slides(source, target)
        assert result.element_count == (4, 2)  # 1 title + 3 texts vs 1 title + 1 text

    def test_list_items_compared_as_text(self):
        source = SlideIR(
            index=0,
            title="T",
            elements=[
                ElementIR(kind="list", bounds=None, items=["bullet one", "bullet two"]),
            ],
        )
        target = SlideIR(
            index=0,
            title="T",
            elements=[
                ElementIR(kind="text", bounds=None, text="bullet one bullet two"),
            ],
        )
        result = compare_slides(source, target)
        # bullet fragments should be found in target text
        assert result.text_coverage == pytest.approx(1.0)


# ===========================================================================
# Comparison: compare_presentations
# ===========================================================================

class TestComparePresentations:
    def _make_pres(self, title: str, slide_titles: list[str]) -> PresentationIR:
        slides = [
            SlideIR(
                index=i,
                title=t,
                elements=[ElementIR(kind="title", bounds=None, text=t)],
            )
            for i, t in enumerate(slide_titles)
        ]
        return PresentationIR(title=title, slides=slides)

    def test_identical_presentations_match(self):
        pres = self._make_pres("Main Title", ["Slide 1", "Slide 2"])
        result = compare_presentations(pres, pres)
        assert result.is_match
        assert result.title_match
        assert result.slide_count_match

    def test_different_slide_count_no_match(self):
        source = self._make_pres("T", ["A", "B", "C"])
        target = self._make_pres("T", ["A"])
        result = compare_presentations(source, target)
        assert not result.slide_count_match
        assert not result.is_match

    def test_different_title_no_match(self):
        source = self._make_pres("Presentation Alpha", ["S1"])
        target = self._make_pres("Completely Different", ["S1"])
        result = compare_presentations(source, target)
        assert not result.title_match

    def test_slide_count_tuple(self):
        source = self._make_pres("T", ["A", "B"])
        target = self._make_pres("T", ["A", "B", "C"])
        result = compare_presentations(source, target)
        assert result.slide_count == (2, 3)

    def test_slide_results_count_matches_source_slides(self):
        source = self._make_pres("T", ["A", "B", "C"])
        target = self._make_pres("T", ["A", "B", "C"])
        result = compare_presentations(source, target)
        assert len(result.slide_results) == 3

    def test_summary_is_string(self):
        pres = self._make_pres("Main Title", ["Slide 1"])
        result = compare_presentations(pres, pres)
        s = result.summary()
        assert isinstance(s, str)
        assert "title_match" in s

    def test_target_slide_offset(self):
        """target_slide_offset lets us skip a diatypst-generated title page."""
        source = self._make_pres("T", ["Content 1", "Content 2"])
        # target has an extra "title page" prepended
        title_page = SlideIR(index=0, title="T", elements=[ElementIR(kind="title", bounds=None, text="T")])
        target = PresentationIR(
            title="T",
            slides=[title_page] + source.slides,
        )
        result = compare_presentations(source, target, target_slide_offset=1)
        assert result.slide_count_match
        assert result.is_match


# ===========================================================================
# Integration: PPTX IR compared against itself (via a re-serialised clone)
# ===========================================================================

class TestSelfComparison:
    def test_pptx_ir_matches_itself(self, talk_pptx_ir: PresentationIR):
        result = compare_presentations(talk_pptx_ir, talk_pptx_ir)
        assert result.is_match, result.summary()

    def test_each_slide_matches_itself(self, talk_pptx_ir: PresentationIR):
        for slide in talk_pptx_ir.slides:
            result = compare_slides(slide, slide)
            assert result.is_match, f"Slide {slide.index} does not match itself:\n{result.summary()}"

    def test_first_slide_text_fragment_present(self, talk_pptx_ir: PresentationIR):
        slide0 = talk_pptx_ir.slides[0]
        frags = slide0.all_text_fragments()
        assert frags
        # Clone with the same fragments as "target" – all should be present
        result = compare_slides(slide0, slide0)
        assert result.missing_fragments == []


# ===========================================================================
# PDF-based tests (skipped unless the compiled PDF exists)
# ===========================================================================

@pytest.mark.skipif(not TALK_PDF.exists(), reason="Compiled PDF not present")
class TestPdfIr:
    def test_pdf_to_presentation_ir_loads(self):
        ir = pdf_to_presentation_ir(TALK_PDF)
        assert isinstance(ir, PresentationIR)
        assert len(ir.slides) > 0

    def test_pdf_slides_have_elements(self):
        ir = pdf_to_presentation_ir(TALK_PDF)
        for slide in ir.slides:
            assert isinstance(slide, SlideIR)

    def test_pdf_vs_pptx_comparison(self):
        pptx_ir = pptx_to_presentation_ir(TALK_PPTX)
        pdf_ir = pdf_to_presentation_ir(TALK_PDF, skip_title_page=True)
        result = compare_presentations(pptx_ir, pdf_ir)
        # Expect reasonable text coverage even if perfect match is unlikely
        for sr in result.slide_results:
            assert sr.text_coverage >= 0.5, (
                f"Very low text coverage for slide {sr.source_index}: {sr.text_coverage:.2f}\n"
                f"Missing: {sr.missing_fragments}"
            )
