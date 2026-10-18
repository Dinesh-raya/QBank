"""Regression tests for formula / math preservation (questions 68-80).

The reference renders these as 2-D expressions (stacked fractions, radicals,
big parentheses), so the raw text-layer reading order is deliberately jumbled.
The tests therefore assert what is *guaranteed* — faithful raw capture, a
flagged heuristic reconstruction and an authoritative source crop — and never
assert a clean formula we did not verify.
"""
from __future__ import annotations

from pathlib import Path

MATH_EXPECTED = set(range(68, 81))


def _math_questions(processed):
    return [q for q in processed.analysis.questions if q.is_math]


def test_math_questions_are_68_to_80(processed):
    nums = sorted(q.number for q in _math_questions(processed))
    assert set(nums) == MATH_EXPECTED
    assert len(nums) == 13


def test_math_questions_are_flagged_and_carry_a_record(processed):
    for q in _math_questions(processed):
        assert "math_reconstructed" in q.quality_flags
        assert q.math is not None
        assert (q.math.get("linear") or "").strip(), f"Q{q.number} has no reconstruction"
        assert q.math.get("verified") is False


def test_raw_text_is_preserved_verbatim(processed):
    for q in _math_questions(processed):
        assert q.raw_text, f"Q{q.number} raw text lost"
        assert f"{q.number}." in q.raw_text


def test_every_math_question_has_a_source_crop(processed):
    for q in _math_questions(processed):
        assert q.asset_path, f"Q{q.number} has no crop"
        assert Path(q.asset_path).exists(), f"Q{q.number} crop missing on disk"


def test_uncertainty_is_flagged_when_structure_is_present(processed):
    # At least the fraction-bearing equations must be marked uncertain so the UI
    # shows the crop for verification.
    uncertain = [q for q in _math_questions(processed) if "math_layout_uncertain" in q.quality_flags]
    assert uncertain, "no math question was flagged uncertain despite 2-D structure"
    assert any(q.math and q.math.get("has_fractions") for q in _math_questions(processed))


def test_reconstruction_retains_operators(processed):
    q68 = next(q for q in _math_questions(processed) if q.number == 68)
    linear = q68.math["linear"]
    assert "=" in linear
    assert any(op in linear for op in ("+", "\u2212", "/", "\u00f7"))
