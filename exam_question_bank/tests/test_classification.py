"""Classification rules: unit tests (no PDF required)."""
from __future__ import annotations

import pytest

from question_bank.services.classifier import Classifier
from question_bank.taxonomy import Taxonomy


@pytest.fixture()
def clf(fresh_db):
    tax = Taxonomy(fresh_db)
    tax.ensure_seeded()
    return Classifier(tax), tax


def test_syllogism(clf):
    classifier, _ = clf
    r = classifier.classify(
        "Statements: Only a few Lakes are Rivers Some Rivers are Puddles "
        "Conclusion I: Some Ponds can be Rivers Conclusion II: All Rivers are Ponds",
        "", "logical_statements")
    assert r.topic == "Syllogism"


def test_inequality_chain_beats_syllogism(clf):
    classifier, _ = clf
    r = classifier.classify(
        "Statement: H < K \u2264 P = R \u2265 Y > M < T "
        "Conclusion I: M \u2264 P Conclusion II: R > H", "", "instruction")
    assert r.topic == "Inequality"


def test_percentage_rule_matches_percent_sign(clf):
    classifier, _ = clf
    r = classifier.classify(
        "If 12.5% of number of students studying in School B took part, "
        "what is the number of students studying in School B ?", "", None)
    assert r.topic == "Percentage"


def test_inequality_does_not_match_character_sequence(clf):
    classifier, _ = clf
    # a lone "F < G ... E > L" inside an arrangement is not an inequality question
    r = classifier.classify(
        "How many such numbers are there in the given arrangement each of which is "
        "immediately preceded by a letter and immediately followed by a symbol?",
        "arrangement of symbol, letter and digits J 7 I * S 8 F < G E > L M ! T",
        "alphanumeric_sequence")
    assert r.topic != "Inequality"


def test_chart_prior_for_keywordless_question(clf):
    classifier, _ = clf
    r = classifier.classify(
        "Total how many students from Schools A, B and E together took part in the event ?",
        "Refer to the graph and answer the given questions. Data regarding students.",
        "data_interpretation_graph")
    assert r.subject == "Quantitative Aptitude"
    assert r.topic == "Data Interpretation"
    assert r.method == "heuristic_context"


def test_chart_task_topic_with_data_interpretation_tag(clf):
    classifier, _ = clf
    r = classifier.classify(
        "What is the respective ratio between total number of students from Schools C "
        "and D together and number of students from School A ?", "", "data_interpretation_graph")
    assert r.topic == "Ratio and Proportion"
    assert "data_interpretation" in r.tags


def test_table_stimulus_does_not_force_reasoning_topic(clf):
    classifier, _ = clf
    r = classifier.classify(
        "What is the difference between total number of books sold by Shops A and C "
        "together in January and number of books sold by Shop B in February ?",
        "Study the table and answer the given questions: number of books sold by 3 shops in 3 months.",
        "data_interpretation_table")
    assert r.subject == "Quantitative Aptitude"
    assert r.topic == "Data Interpretation"


def test_shared_context_can_supply_specific_rule_for_non_chart(clf):
    classifier, _ = clf
    r = classifier.classify(
        "3     5     9     17     33     66     129",
        "Direction (46-50): a number series is given in which one number is wrong. Find out the wrong number.",
        "instruction")
    assert r.topic == "Wrong Number Series"
    assert r.method == "heuristic_context"


def test_returned_topic_is_valid_in_taxonomy(clf):
    classifier, tax = clf
    for text in ("What is the average of 2, 4, 6 ?", "A train overtakes a car.",
                 "Find the area of the circle of radius 7 cm."):
        r = classifier.classify(text)
        assert r.topic in tax.topics(r.subject, active_only=False)


def test_unclassified_when_nothing_matches(clf):
    classifier, _ = clf
    r = classifier.classify("zzzz qqqq wwww", "")
    assert r.subject == "Unclassified"
    assert r.method == "none"
