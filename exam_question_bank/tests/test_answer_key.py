"""Regression tests for answer-key detection and matching."""
from __future__ import annotations


def test_all_key_entries_detected(processed):
    assert len(processed.analysis.answer_key) == 80


def test_every_key_entry_matches_a_question(processed):
    statuses = {e.match_status for e in processed.analysis.answer_key}
    assert statuses == {"matched"}, statuses


def test_no_missing_duplicate_or_invalid_entries(processed):
    issues = processed.repo.answer_key_issues(processed.doc_id)
    assert issues["missing"] == []
    assert issues["out_of_range"] == []
    assert issues["invalid_option"] == []
    assert issues["duplicate"] == []
    assert issues["total_keys"] == 80
    assert issues["total_questions"] == 80


def test_option_indices_are_in_range(processed):
    for e in processed.analysis.answer_key:
        assert e.option_index is not None
        assert 1 <= e.option_index <= 5
        assert str(e.option_index) == e.answer_value


def test_keys_are_persisted_and_joined_to_questions(processed):
    rows = processed.repo.list_answer_keys(processed.doc_id)
    assert len(rows) == 80
    assert all(r["match_question_id"] is not None for r in rows)


def test_no_answer_is_invented(processed):
    # every persisted answer came from the parsed key (extraction_method recorded)
    rows = processed.repo.list_answer_keys(processed.doc_id)
    assert all(r["extraction_method"] for r in rows)
