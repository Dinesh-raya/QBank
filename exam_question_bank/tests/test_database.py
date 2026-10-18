"""Database / repository round-trip tests (synthetic data, no PDF)."""
from __future__ import annotations

from question_bank.models import (DocumentAnalysis, Line, PageLayout,
                                  ParsedAnswerKeyEntry, ParsedContext,
                                  ParsedOption, ParsedQuestion, ParsedSection,
                                  Span)
from question_bank.repositories import Repository
from question_bank.taxonomy import Taxonomy


def _synthetic_analysis(sha: str = "a" * 64) -> DocumentAnalysis:
    line = Line(page_number=1, bbox=(50, 100, 400, 115),
                spans=[Span(text="1. What is 1 + 1?", font="Body", size=11,
                            bbox=(50, 100, 400, 115), raw_text="1. What is 1 + 1?")])
    layout = PageLayout(page_number=1, width=595, height=842, rotation=0,
                        body_font_size=11, lines=[line], raw_text="1. What is 1 + 1?")
    section = ParsedSection(index=0, name="TEST SECTION", page_number=1,
                            order_index=0, start_question=1, end_question=1)
    context = ParsedContext(index=0, context_type="instruction", label="Direction (1-1)",
                            text="Answer all questions.", raw_text="Answer all questions.",
                            page_start=1, page_end=1, q_start=1, q_end=1)
    question = ParsedQuestion(
        number=1, number_raw="1.", page_number=1, order_index=1,
        stem="What is 1 + 1?", raw_text="1. What is 1 + 1?", context_index=0, section_index=0,
        options=[ParsedOption(index=i, label=f"{i})", text=f"opt{i}") for i in range(1, 6)])
    key = ParsedAnswerKeyEntry(question_number=1, option_index=2, answer_value="2",
                               page_number=1, extraction_method="test", raw_text="1.2")
    return DocumentAnalysis(filename="synthetic.pdf", sha256=sha, path="/tmp/synthetic.pdf",
                            page_count=1, page_layouts=[layout], sections=[section],
                            contexts=[context], questions=[question], answer_key=[key])


def test_save_and_read_back(fresh_db):
    repo = Repository(fresh_db)
    doc_id = repo.save_analysis(_synthetic_analysis(), exam="Test Exam", classify=False)
    assert repo.get_document(doc_id)["filename"] == "synthetic.pdf"

    questions = repo.list_questions(document_id=doc_id)
    assert len(questions) == 1
    assert questions[0]["question_number"] == 1

    full = repo.get_question(questions[0]["id"])
    assert len(full["options"]) == 5
    assert full["answer"]["answer_value"] == "2"


def test_resave_is_idempotent(fresh_db):
    repo = Repository(fresh_db)
    analysis = _synthetic_analysis(sha="b" * 64)
    repo.save_analysis(analysis, classify=False)
    repo.save_analysis(analysis, classify=False)
    assert repo.count_questions(document_id="b" * 64) == 1
    assert len(repo.list_documents()) == 1


def test_editing_question_logs_history(fresh_db):
    repo = Repository(fresh_db)
    doc_id = repo.save_analysis(_synthetic_analysis(sha="c" * 64), classify=False)
    qid = repo.list_questions(document_id=doc_id)[0]["id"]
    repo.update_question(qid, text="What is 2 + 2?")
    history = repo.review_history(entity_type="question", entity_id=qid)
    assert any(h["action"] == "edit_text" for h in history)
    assert repo.get_question(qid)["text"] == "What is 2 + 2?"


def test_option_edits(fresh_db):
    repo = Repository(fresh_db)
    doc_id = repo.save_analysis(_synthetic_analysis(sha="d" * 64), classify=False)
    q = repo.get_question(repo.list_questions(document_id=doc_id)[0]["id"])
    oid = q["options"][0]["id"]
    repo.update_option(oid, "changed")
    new_id = repo.add_option(q["id"], "opt6")
    repo.delete_option(new_id)
    updated = repo.get_question(q["id"])
    assert updated["options"][0]["text"] == "changed"
    assert len(updated["options"]) == 5


def test_manual_answer_and_answer_key_issues(fresh_db):
    repo = Repository(fresh_db)
    doc_id = repo.save_analysis(_synthetic_analysis(sha="e" * 64), classify=False)
    qid = repo.list_questions(document_id=doc_id)[0]["id"]
    repo.set_answer(doc_id, 1, qid, "3", 3)
    issues = repo.answer_key_issues(doc_id)
    assert issues["missing"] == []
    assert repo.get_question(qid)["correct_answer"] == "3"


def test_classification_edit_persists(fresh_db):
    repo = Repository(fresh_db)
    doc_id = repo.save_analysis(_synthetic_analysis(sha="f" * 64), classify=False)
    qid = repo.list_questions(document_id=doc_id)[0]["id"]
    repo.set_classification(qid, "Quantitative Aptitude", "Average")
    q = repo.get_question(qid)
    primary = [c for c in q["classifications"] if c["is_primary"]]
    assert primary[-1]["topic"] == "Average"


def test_taxonomy_seeded_and_valid(fresh_db):
    tax = Taxonomy(fresh_db)
    tax.ensure_seeded()
    assert "Quantitative Aptitude" in tax.subjects()
    assert "Data Interpretation" in tax.topics("Quantitative Aptitude")


def test_link_and_unlink_context(fresh_db):
    repo = Repository(fresh_db)
    doc_id = repo.save_analysis(_synthetic_analysis(sha="1" * 64), classify=False)
    qid = repo.list_questions(document_id=doc_id)[0]["id"]
    repo.link_context(qid, None)
    assert repo.get_question(qid)["context_id"] is None
