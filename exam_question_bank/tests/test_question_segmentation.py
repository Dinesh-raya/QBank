"""Regression tests for question / option segmentation."""
from __future__ import annotations


def test_all_questions_detected(processed):
    qs = processed.analysis.questions
    assert len(qs) == 80


def test_question_numbers_are_sequential_without_gaps_or_duplicates(processed):
    nums = sorted(q.number for q in processed.analysis.questions if q.number is not None)
    assert nums == list(range(1, 81))
    assert processed.analysis.metadata.get("missing_numbers") == []
    assert processed.analysis.metadata.get("duplicate_numbers") == []


def test_every_question_has_five_options(processed):
    for q in processed.analysis.questions:
        assert len(q.options) == 5, f"Q{q.number} has {len(q.options)} options"
        assert sorted(o.index for o in q.options) == [1, 2, 3, 4, 5]


def test_option_text_is_not_empty(processed):
    for q in processed.analysis.questions:
        for o in q.options:
            assert (o.text or "").strip(), f"Q{q.number} option {o.index} is empty"


def test_two_sections_detected(processed):
    sections = processed.analysis.sections
    assert len(sections) == 2
    names = [s.name.upper() for s in sections]
    assert any("REASONING" in n for n in names)
    assert any("NUMERICAL" in n for n in names)
    ranges = sorted((s.start_question, s.end_question) for s in sections)
    assert ranges == [(1, 40), (41, 80)]


def test_questions_are_in_reading_order(processed):
    orders = [q.order_index for q in processed.analysis.questions]
    assert orders == sorted(orders)
