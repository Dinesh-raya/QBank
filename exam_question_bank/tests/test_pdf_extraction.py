"""Regression tests for digital PDF extraction on the reference paper."""
from __future__ import annotations


def test_page_count(processed):
    assert processed.analysis.page_count == 8
    assert len(processed.analysis.page_layouts) == 8


def test_every_page_has_text_and_a_page_number_reference(processed):
    for layout in processed.analysis.page_layouts:
        assert layout.raw_text.strip(), f"page {layout.page_number} has no text"
        assert layout.page_number >= 1


def test_watermark_and_page_numbers_are_separated_not_deleted(processed):
    # Watermark / page-number lines are moved to noise_lines (kept), never dropped.
    for layout in processed.analysis.page_layouts:
        assert all(line.kind != "watermark" for line in layout.lines)
        kinds = {line.kind for line in layout.noise_lines}
        assert "page_number" in kinds
        assert "watermark" in kinds


def test_symbol_font_glyphs_are_decoded(processed):
    # The inequality questions use Symbol-font comparators (<=, >=) which the
    # decoder must restore rather than drop.
    blob = " ".join(q.stem for q in processed.analysis.questions)
    assert ("\u2264" in blob) or ("\u2265" in blob)


def test_alphanumeric_sequence_preserved(processed):
    ctx = next(c for c in processed.analysis.contexts if c.q_start == 24)
    seq = (ctx.structured or {}).get("sequence", "")
    assert seq
    for token in ("7", "S", "8", "<", ">", "@", "!", "%"):
        assert token in seq, f"missing {token!r} in sequence"


def test_questions_reference_source_pages(processed):
    for q in processed.analysis.questions:
        assert 1 <= q.page_number <= 8
        assert q.page_end is None or q.page_end >= q.page_number


def test_no_extraction_warnings_on_reference_paper(processed):
    # The reference paper is a clean digital PDF; any warning is a real finding.
    assert processed.res.warnings == [], processed.res.warnings
