"""Regression tests for shared instructions, puzzles, graphs and tables."""
from __future__ import annotations


def test_context_count(processed):
    assert len(processed.analysis.contexts) == 12


def test_every_link_index_is_valid(processed):
    n = len(processed.analysis.contexts)
    for q in processed.analysis.questions:
        if q.context_index is not None:
            assert 0 <= q.context_index < n


def test_symbol_arrangement_linked_to_24_28(processed):
    ctx = next(c for c in processed.analysis.contexts if c.q_start == 24)
    assert ctx.q_end == 28
    assert ctx.context_type == "alphanumeric_sequence"
    linked = {q.number for q in processed.analysis.questions if q.context_index == ctx.index}
    assert linked == {24, 25, 26, 27, 28}


def test_graph_linked_to_all_six_questions(processed):
    ctx = next(c for c in processed.analysis.contexts if c.q_start == 52)
    assert ctx.q_end == 57
    assert ctx.context_type == "data_interpretation_graph"
    assert (ctx.structured or {}).get("region_kind") == "graph"
    assert ctx.asset_path, "graph region crop was not produced"
    linked = {q.number for q in processed.analysis.questions if q.context_index == ctx.index}
    assert linked == {52, 53, 54, 55, 56, 57}


def test_table_linked_to_all_six_questions(processed):
    ctx = next(c for c in processed.analysis.contexts if c.q_start == 61)
    assert ctx.q_end == 66
    assert ctx.context_type == "data_interpretation_table"
    assert (ctx.structured or {}).get("region_kind") == "table"
    assert ctx.asset_path
    linked = {q.number for q in processed.analysis.questions if q.context_index == ctx.index}
    assert linked == {61, 62, 63, 64, 65, 66}


def test_table_grid_is_structured(processed):
    ctx = next(c for c in processed.analysis.contexts if c.q_start == 61)
    structured = (ctx.structured or {}).get("structured", {})
    rows = structured.get("rows", [])
    # three shops, three months of numeric data
    flat = " ".join(" ".join(r) for r in rows)
    for value in ("80", "120", "91", "96", "104", "72"):
        assert value in flat, f"table value {value} missing"


def test_shared_contexts_are_stored_once_but_referenced_by_many(processed):
    # 12 contexts, but many questions reference them -> not duplicated per question.
    distinct_ids = {q.context_index for q in processed.analysis.questions if q.context_index is not None}
    assert len(distinct_ids) <= len(processed.analysis.contexts)
    # at least the six-question groups share a single context record
    assert len(distinct_ids) == len({c.index for c in processed.analysis.contexts if any(
        q.context_index == c.index for q in processed.analysis.questions)})
