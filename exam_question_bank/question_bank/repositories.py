"""Database access layer.

All SQL lives here so services stay storage-agnostic and the Streamlit pages
never build SQL by hand. Every write uses parameterised statements inside a
transaction; reads return plain dicts (``sqlite3.Row`` is not picklable across
Streamlit reruns and leaks connection state into the UI).

Design notes
------------
* A document's ``id`` is its SHA-256, which gives stable identity, natural
  duplicate-document detection and a scope key for re-processing.
* ``questions.raw_text`` is immutable; ``questions.text`` is the editable,
  corrected copy. Editing never touches ``raw_text``.
* Re-importing the same document replaces its derived rows inside one
  transaction, so an interrupted run never leaves half a document behind.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Optional

from . import config
from .database import Database, get_db
from .models import (DocumentAnalysis, PageLayout, ParsedAnswerKeyEntry,
                     ParsedContext, ParsedOption, ParsedQuestion, ParsedSection)


def _bbox_str(bbox: Optional[Iterable[float]]) -> Optional[str]:
    if not bbox:
        return None
    return ",".join(f"{v:.2f}" for v in bbox)


def _flags_str(flags: Iterable[str]) -> str:
    return ",".join(f for f in flags if f)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Repository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()
        self.db.initialise()

    # ==================================================================
    # persistence of a full analysis
    # ==================================================================
    def save_analysis(self, analysis: DocumentAnalysis, *, exam: Optional[str] = None,
                      year: Optional[int] = None, source_notes: Optional[str] = None,
                      inspections: Optional[list] = None,
                      render_paths: Optional[dict[int, str]] = None,
                      classify: bool = True,
                      classifier=None) -> str:
        """Persist an analysed document and everything derived from it.

        Returns the document id. Idempotent: derived rows for the document are
        replaced atomically, so a retry does not create duplicates (the master
        prompt's "prevent duplicate inserts during reruns").
        """
        doc_id = analysis.sha256
        with self.db.transaction() as conn:
            # Replace derived rows (cascade handles children via FK).
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.execute(
                "INSERT INTO documents(id, filename, sha256, path, size_bytes, page_count,"
                " format, exam, year, source_notes, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, analysis.filename, analysis.sha256, analysis.path,
                 analysis.metadata.get("size_bytes", 0), analysis.page_count, "pdf",
                 exam, year, source_notes, "imported"),
            )

            insp_by_page = {i.page_number: i for i in (inspections or [])}
            for layout in analysis.page_layouts:
                insp = insp_by_page.get(layout.page_number)
                conn.execute(
                    "INSERT INTO pages(document_id, page_number, width, height, rotation,"
                    " text_char_count, image_count, drawing_count, has_text, is_scanned,"
                    " page_type, quality_flags, raw_text, cleaned_text, render_path)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        doc_id, layout.page_number, layout.width, layout.height, layout.rotation,
                        getattr(insp, "char_count", len(layout.raw_text)),
                        getattr(insp, "image_count", len(layout.drawings)),
                        len(layout.drawings),
                        1 if getattr(insp, "has_text", bool(layout.raw_text)) else 0,
                        1 if layout.page_type != "digital" else 0,
                        layout.page_type,
                        ",".join(layout.warnings) if layout.warnings else None,
                        layout.raw_text,
                        layout.raw_text,
                        (render_paths or {}).get(layout.page_number),
                    ),
                )

            section_map = self._insert_sections(conn, doc_id, analysis.sections)
            context_map = self._insert_contexts(conn, doc_id, analysis.contexts)
            context_type_by_index = {c.index: c.context_type for c in analysis.contexts}

            question_id_by_number: dict[int, int] = {}
            for q in analysis.questions:
                qid = self._insert_question(conn, doc_id, q, section_map, context_map,
                                            context_type_by_index, classify, classifier)
                if q.number is not None:
                    question_id_by_number[q.number] = qid

            self._insert_answer_keys(conn, doc_id, analysis.answer_key, question_id_by_number)

        # Duplicate detection runs outside the write transaction.
        try:
            from .services.duplicate_detector import DuplicateDetector
            DuplicateDetector(self.db).detect_for_document(doc_id)
        except Exception:
            pass
        return doc_id

    def _insert_sections(self, conn, doc_id: str, sections: list[ParsedSection]) -> dict[int, int]:
        out: dict[int, int] = {}
        for s in sections:
            cur = conn.execute(
                "INSERT INTO sections(document_id, name, page_number, order_index,"
                " start_question, end_question) VALUES (?,?,?,?,?,?)",
                (doc_id, s.name, s.page_number, s.order_index, s.start_question, s.end_question),
            )
            out[s.index] = int(cur.lastrowid)
        return out

    def _insert_contexts(self, conn, doc_id: str, contexts: list[ParsedContext]) -> dict[int, int]:
        out: dict[int, int] = {}
        for c in contexts:
            cur = conn.execute(
                "INSERT INTO contexts(document_id, context_type, label, text, raw_text,"
                " page_start, page_end, question_start, question_end, bbox, asset_path,"
                " structured_json, verified) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, c.context_type, c.label, c.text, c.raw_text, c.page_start, c.page_end,
                 c.q_start, c.q_end, _bbox_str(c.bbox), c.asset_path,
                 json.dumps(c.structured, ensure_ascii=False) if c.structured else None,
                 1 if c.verified else 0),
            )
            out[c.index] = int(cur.lastrowid)
        return out

    def _insert_question(self, conn, doc_id: str, q: ParsedQuestion,
                         section_map, context_map, context_type_by_index,
                         classify: bool, classifier) -> int:
        section_id = section_map.get(q.section_index) if q.section_index is not None else None
        context_id = context_map.get(q.context_index) if q.context_index is not None else None
        classification = None
        if classify:
            classifier = classifier or _default_classifier()
            context_text = ""
            if q.context_index is not None:
                context_text = getattr(q, "_context_text", "") or ""
            context_type = context_type_by_index.get(q.context_index) if q.context_index is not None else None
            classification = classifier.classify(q.stem, context_text, context_type)
        method = "pymupdf-math-reconstruct" if q.is_math else config.EXTRACTION_METHOD_DIGITAL
        cur = conn.execute(
            "INSERT INTO questions(document_id, section_id, context_id, question_number,"
            " question_number_raw, page_number, page_end, order_index, text, stem_text,"
            " raw_text, bbox, asset_path, math_json, is_mcq, is_math, extraction_method,"
            " quality_flags, needs_review, review_status, classification_method) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, section_id, context_id, q.number, q.number_raw, q.page_number, q.page_end,
             q.order_index, q.stem, q.stem, q.raw_text, _bbox_str(q.bbox), q.asset_path,
             json.dumps(q.math, ensure_ascii=False) if q.math else None,
             1 if q.is_mcq else 0, 1 if q.is_math else 0, method, _flags_str(q.quality_flags),
             1 if q.needs_review else 0, config.REVIEW_STATUS_DRAFT,
             classification.method if classification else None),
        )
        qid = int(cur.lastrowid)
        for o in q.options:
            conn.execute(
                "INSERT INTO options(question_id, option_index, option_label, text, raw_text, bbox)"
                " VALUES (?,?,?,?,?,?)",
                (qid, o.index, o.label, o.text, o.raw_text, _bbox_str(o.bbox)),
            )
        if classification is not None:
            self._insert_classification(conn, qid, classification)
        return qid

    def _insert_classification(self, conn, question_id: int, classification) -> None:
        conn.execute(
            "INSERT INTO question_classifications(question_id, subject, topic, subtopic,"
            " method, confidence, confidence_kind, is_primary, review_status)"
            " VALUES (?,?,?,?,?,?,?,1,?)",
            (question_id, classification.subject, classification.topic, classification.subtopic,
             classification.method, classification.confidence, classification.confidence_kind,
             "suggested" if classification.subject != "Unclassified" else "needs_review"),
        )
        for tag in classification.tags:
            conn.execute(
                "INSERT OR IGNORE INTO question_tags(question_id, tag, kind) VALUES (?,?, 'secondary')",
                (question_id, tag),
            )

    def _insert_answer_keys(self, conn, doc_id: str, entries: list[ParsedAnswerKeyEntry],
                            question_id_by_number: dict[int, int]) -> None:
        conn.execute("DELETE FROM answer_keys WHERE document_id = ?", (doc_id,))
        for e in entries:
            qid = question_id_by_number.get(e.question_number)
            match_status = e.match_status
            if match_status == "unmatched":
                match_status = "matched" if qid is not None else "unmatched"
            conn.execute(
                "INSERT OR REPLACE INTO answer_keys(document_id, question_number, option_index,"
                " answer_value, page_number, extraction_method, match_status, match_question_id,"
                " raw_text) VALUES (?,?,?,?,?,?,?,?,?)",
                (doc_id, e.question_number, e.option_index, e.answer_value, e.page_number,
                 e.extraction_method, match_status, qid, e.raw_text),
            )
            if qid is not None:
                conn.execute(
                    "UPDATE questions SET correct_answer = ? WHERE id = ?",
                    (e.answer_value, qid),
                )

    # ==================================================================
    # reads
    # ==================================================================
    def list_documents(self) -> list[dict]:
        rows = self.db.query(
            "SELECT d.*, (SELECT COUNT(*) FROM questions q WHERE q.document_id=d.id) AS question_count"
            " FROM documents d ORDER BY d.created_at DESC, d.filename")
        return [dict(r) for r in rows]

    def get_document(self, document_id: str) -> Optional[dict]:
        row = self.db.query_one("SELECT * FROM documents WHERE id=?", (document_id,))
        return dict(row) if row else None

    def document_id_by_sha(self, sha256: str) -> Optional[str]:
        row = self.db.query_one("SELECT id FROM documents WHERE sha256=?", (sha256,))
        return row["id"] if row else None

    def list_pages(self, document_id: str) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM pages WHERE document_id=? ORDER BY page_number", (document_id,))
        return [dict(r) for r in rows]

    def get_page(self, document_id: str, page_number: int) -> Optional[dict]:
        row = self.db.query_one(
            "SELECT * FROM pages WHERE document_id=? AND page_number=?", (document_id, page_number))
        return dict(row) if row else None

    def list_sections(self, document_id: str) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM sections WHERE document_id=? ORDER BY order_index", (document_id,))]

    def list_contexts(self, document_id: str) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM contexts WHERE document_id=? ORDER BY page_start, id", (document_id,))
        out = []
        for r in rows:
            d = dict(r)
            d["structured"] = json.loads(d["structured_json"]) if d.get("structured_json") else {}
            out.append(d)
        return out

    def get_context(self, context_id: int) -> Optional[dict]:
        row = self.db.query_one("SELECT * FROM contexts WHERE id=?", (context_id,))
        if not row:
            return None
        d = dict(row)
        d["structured"] = json.loads(d["structured_json"]) if d.get("structured_json") else {}
        return d

    # -- question queries ------------------------------------------------
    def list_questions(self, *, document_id: Optional[str] = None,
                       search: Optional[str] = None, subject: Optional[str] = None,
                       topic: Optional[str] = None, subtopic: Optional[str] = None,
                       exam: Optional[str] = None, year: Optional[int] = None,
                       section_id: Optional[int] = None,
                       review_status: Optional[str] = None,
                       missing_answer: Optional[bool] = None,
                       duplicate_only: bool = False,
                       limit: int = 500, offset: int = 0) -> list[dict]:
        where, params = self._question_filters(
            document_id, search, subject, topic, subtopic, exam, year, section_id,
            review_status, missing_answer, duplicate_only)
        sql = (
            "SELECT q.*, s.name AS section_name, c.label AS context_label,"
            " c.context_type AS context_type,"
            " (SELECT subject FROM question_classifications kc WHERE kc.question_id=q.id"
            "  ORDER BY is_primary DESC, id LIMIT 1) AS subject,"
            " (SELECT topic FROM question_classifications kc WHERE kc.question_id=q.id"
            "  ORDER BY is_primary DESC, id LIMIT 1) AS topic,"
            " (SELECT subtopic FROM question_classifications kc WHERE kc.question_id=q.id"
            "  ORDER BY is_primary DESC, id LIMIT 1) AS subtopic,"
            " (SELECT answer_value FROM answer_keys ak WHERE ak.match_question_id=q.id) AS answer_value,"
            " (SELECT COUNT(*) FROM options o WHERE o.question_id=q.id) AS option_count"
            " FROM questions q"
            " LEFT JOIN sections s ON q.section_id=s.id"
            " LEFT JOIN contexts c ON q.context_id=c.id"
            f" {where} ORDER BY COALESCE(q.question_number, 100000), q.document_id, q.order_index"
            " LIMIT ? OFFSET ?")
        rows = self.db.query(sql, tuple(params) + (limit, offset))
        return [dict(r) for r in rows]

    def count_questions(self, **kwargs) -> int:
        kwargs.pop("limit", None); kwargs.pop("offset", None)
        where, params = self._question_filters(**kwargs)
        row = self.db.query_one(f"SELECT COUNT(*) AS n FROM questions q {where}", tuple(params))
        return int(row["n"]) if row else 0

    def _question_filters(self, document_id=None, search=None, subject=None, topic=None,
                          subtopic=None, exam=None, year=None, section_id=None,
                          review_status=None, missing_answer=None, duplicate_only=False):
        clauses: list[str] = []
        params: list[Any] = []
        if document_id:
            clauses.append("q.document_id = ?"); params.append(document_id)
        if section_id:
            clauses.append("q.section_id = ?"); params.append(section_id)
        if review_status:
            clauses.append("q.review_status = ?"); params.append(review_status)
        if exam:
            clauses.append("q.document_id IN (SELECT id FROM documents WHERE exam = ?)"); params.append(exam)
        if year:
            clauses.append("q.document_id IN (SELECT id FROM documents WHERE year = ?)"); params.append(year)
        if subject:
            clauses.append("EXISTS (SELECT 1 FROM question_classifications k WHERE k.question_id=q.id AND k.subject=?)")
            params.append(subject)
        if topic:
            clauses.append("EXISTS (SELECT 1 FROM question_classifications k WHERE k.question_id=q.id AND k.topic=?)")
            params.append(topic)
        if subtopic:
            clauses.append("EXISTS (SELECT 1 FROM question_classifications k WHERE k.question_id=q.id AND k.subtopic=?)")
            params.append(subtopic)
        if search:
            like = f"%{search}%"
            clauses.append("(q.text LIKE ? OR q.stem_text LIKE ? OR q.raw_text LIKE ?"
                           " OR EXISTS (SELECT 1 FROM options o WHERE o.question_id=q.id AND o.text LIKE ?))")
            params.extend([like, like, like, like])
        if missing_answer is True:
            clauses.append("NOT EXISTS (SELECT 1 FROM answer_keys a WHERE a.match_question_id=q.id AND a.answer_value IS NOT NULL)")
        if missing_answer is False:
            clauses.append("EXISTS (SELECT 1 FROM answer_keys a WHERE a.match_question_id=q.id AND a.answer_value IS NOT NULL)")
        if duplicate_only:
            clauses.append("EXISTS (SELECT 1 FROM duplicate_candidates d WHERE d.question_id=q.id OR d.other_question_id=q.id)")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def get_question(self, question_id: int) -> Optional[dict]:
        row = self.db.query_one(
            "SELECT q.*, s.name AS section_name, d.filename, d.exam, d.year, d.sha256"
            " FROM questions q"
            " LEFT JOIN sections s ON q.section_id=s.id"
            " LEFT JOIN documents d ON q.document_id=d.id"
            " WHERE q.id=?", (question_id,))
        if not row:
            return None
        d = dict(row)
        d["math"] = json.loads(d["math_json"]) if d.get("math_json") else None
        d["options"] = [dict(r) for r in self.db.query(
            "SELECT * FROM options WHERE question_id=? ORDER BY option_index", (question_id,))]
        d["classifications"] = [dict(r) for r in self.db.query(
            "SELECT * FROM question_classifications WHERE question_id=? ORDER BY is_primary DESC, id",
            (question_id,))]
        d["tags"] = [r["tag"] for r in self.db.query(
            "SELECT tag FROM question_tags WHERE question_id=? ORDER BY tag", (question_id,))]
        d["context"] = self.get_context(d["context_id"]) if d["context_id"] else None
        d["answer"] = None
        arow = self.db.query_one(
            "SELECT * FROM answer_keys WHERE match_question_id=? AND document_id=?",
            (question_id, d["document_id"]))
        if arow:
            d["answer"] = dict(arow)
        return d

    # ==================================================================
    # edits (human review) — always logged
    # ==================================================================
    def log_review(self, entity_type: str, entity_id: Optional[int], action: str,
                   old_value: Optional[str] = None, new_value: Optional[str] = None,
                   note: Optional[str] = None) -> None:
        self.db.execute(
            "INSERT INTO review_history(entity_type, entity_id, action, old_value, new_value, note)"
            " VALUES (?,?,?,?,?,?)",
            (entity_type, entity_id, action, _clip(old_value), _clip(new_value), note))
        self.db.connect().commit()

    def update_question(self, question_id: int, *, text: Optional[str] = None,
                        question_number: Optional[int] = None,
                        review_status: Optional[str] = None,
                        needs_review: Optional[bool] = None,
                        correct_answer: Optional[str] = None,
                        answer_verified: Optional[bool] = None,
                        explanation: Optional[str] = None,
                        context_id: Optional[int] = None,
                        section_id: Optional[int] = None,
                        is_excluded: Optional[bool] = None) -> None:
        current = self.db.query_one("SELECT * FROM questions WHERE id=?", (question_id,))
        if not current:
            return
        fields: list[str] = []
        params: list[Any] = []
        for col, val in (
            ("text", text), ("question_number", question_number),
            ("review_status", config.REVIEW_STATUS_EXCLUDED if is_excluded else review_status),
            ("correct_answer", correct_answer), ("explanation", explanation),
            ("context_id", context_id), ("section_id", section_id),
        ):
            if val is not None:
                fields.append(f"{col}=?"); params.append(val)
        if needs_review is not None:
            fields.append("needs_review=?"); params.append(1 if needs_review else 0)
        if answer_verified is not None:
            fields.append("answer_verified=?"); params.append(1 if answer_verified else 0)
        if is_excluded:
            fields.append("needs_review=0")
        if not fields:
            return
        fields.append("updated_at=?")
        params.append(_now())
        params.append(question_id)
        self.db.execute(f"UPDATE questions SET {', '.join(fields)} WHERE id=?", tuple(params))
        self.db.connect().commit()
        if text is not None:
            self.log_review("question", question_id, "edit_text", current["text"], text)
        if review_status is not None or is_excluded:
            self.log_review("question", question_id, "review_status",
                            current["review_status"],
                            config.REVIEW_STATUS_EXCLUDED if is_excluded else review_status)
        if correct_answer is not None:
            self.log_review("question", question_id, "correct_answer",
                            current["correct_answer"], correct_answer)

    def update_option(self, option_id: int, text: str) -> None:
        row = self.db.query_one("SELECT * FROM options WHERE id=?", (option_id,))
        if not row:
            return
        self.db.execute("UPDATE options SET text=? WHERE id=?", (text, option_id))
        self.db.connect().commit()
        self.log_review("option", option_id, "edit_text", row["text"], text)

    def add_option(self, question_id: int, text: str, label: Optional[str] = None) -> int:
        row = self.db.query_one(
            "SELECT COALESCE(MAX(option_index),0) AS m FROM options WHERE question_id=?", (question_id,))
        idx = int(row["m"]) + 1
        cur = self.db.execute(
            "INSERT INTO options(question_id, option_index, option_label, text, raw_text)"
            " VALUES (?,?,?,?,?)", (question_id, idx, label or f"{idx})", text, text))
        self.db.connect().commit()
        self.log_review("question", question_id, "add_option", None, text)
        return int(cur.lastrowid)

    def delete_option(self, option_id: int) -> None:
        row = self.db.query_one("SELECT * FROM options WHERE id=?", (option_id,))
        if not row:
            return
        self.db.execute("DELETE FROM options WHERE id=?", (option_id,))
        self.db.connect().commit()
        self.log_review("option", option_id, "delete_option", row["text"], None)

    def set_classification(self, question_id: int, subject: str, topic: str,
                           subtopic: Optional[str] = None, *, method: str = "manual",
                           review_status: str = "confirmed", confidence_kind: str = "manual") -> None:
        with self.db.transaction() as conn:
            old = conn.execute(
                "SELECT subject, topic, subtopic FROM question_classifications"
                " WHERE question_id=? AND is_primary=1", (question_id,)).fetchone()
            conn.execute(
                "UPDATE question_classifications SET is_primary=0 WHERE question_id=?", (question_id,))
            conn.execute(
                "INSERT INTO question_classifications(question_id, subject, topic, subtopic, method,"
                " confidence_kind, is_primary, review_status) VALUES (?,?,?,?,?,?,1,?)",
                (question_id, subject, topic, subtopic, method, confidence_kind, review_status))
            conn.execute("UPDATE questions SET updated_at=? WHERE id=?", (_now(), question_id))
            conn.execute(
                "INSERT INTO review_history(entity_type, entity_id, action, old_value, new_value)"
                " VALUES ('question', ?, 'set_classification', ?, ?)",
                (question_id,
                 f"{old['subject']}/{old['topic']}/{old['subtopic']}" if old else None,
                 f"{subject}/{topic}/{subtopic}"))

    def add_tag(self, question_id: int, tag: str, kind: str = "secondary") -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO question_tags(question_id, tag, kind) VALUES (?,?,?)",
            (question_id, tag, kind))
        self.db.connect().commit()

    def remove_tag(self, question_id: int, tag: str) -> None:
        self.db.execute("DELETE FROM question_tags WHERE question_id=? AND tag=?", (question_id, tag))
        self.db.connect().commit()

    def set_answer(self, document_id: str, question_number: int, question_id: Optional[int],
                   value: Optional[str], option_index: Optional[int],
                   *, review_status: str = "confirmed", answered_by: str = "manual") -> None:
        self.db.execute(
            "INSERT INTO answer_keys(document_id, question_number, option_index, answer_value,"
            " extraction_method, match_status, match_question_id, review_status)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(document_id, question_number) DO UPDATE SET"
            " answer_value=excluded.answer_value, option_index=excluded.option_index,"
            " extraction_method=excluded.extraction_method, match_status=excluded.match_status,"
            " match_question_id=excluded.match_question_id, review_status=excluded.review_status",
            (document_id, question_number, option_index, value, answered_by,
             "matched" if question_id else "unmatched", question_id, review_status))
        self.db.connect().commit()
        if question_id is not None:
            self.update_question(question_id, correct_answer=value, answer_verified=True)

    # -- create / split / merge -----------------------------------------
    def create_manual_question(self, document_id: str, *, text: str, question_number: Optional[int],
                               page_number: Optional[int] = None,
                               options: Optional[list[str]] = None,
                               section_id: Optional[int] = None,
                               context_id: Optional[int] = None) -> int:
        row = self.db.query_one(
            "SELECT COALESCE(MAX(order_index),0) AS m FROM questions WHERE document_id=?", (document_id,))
        order = int(row["m"]) + 1
        cur = self.db.execute(
            "INSERT INTO questions(document_id, section_id, context_id, question_number,"
            " question_number_raw, page_number, order_index, text, stem_text, raw_text, is_mcq,"
            " extraction_method, needs_review, review_status, classification_method)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
            (document_id, section_id, context_id, question_number, str(question_number or ""),
             page_number, order, text, text, text, 1 if options else 0,
             config.EXTRACTION_METHOD_MANUAL, config.REVIEW_STATUS_NEEDS_REVIEW, "manual"))
        qid = int(cur.lastrowid)
        for i, opt in enumerate(options or [], start=1):
            self.db.execute(
                "INSERT INTO options(question_id, option_index, option_label, text, raw_text)"
                " VALUES (?,?,?,?,?)", (qid, i, f"{i})", opt, opt))
        self.db.connect().commit()
        self.log_review("question", qid, "create_manual", None, text)
        return qid

    def exclude_question(self, question_id: int) -> None:
        self.update_question(question_id, is_excluded=True)

    def merge_questions(self, source_id: int, target_id: int) -> int:
        """Merge *source* into *target*: append stem text and re-number options.

        Nothing is lost silently: the action is written to ``review_history``.
        Returns the target question id.
        """
        source = self.get_question(source_id)
        target = self.get_question(target_id)
        if not source or not target:
            return target_id
        merged_text = " ".join(t for t in (target["text"], source["text"]) if t).strip()
        with self.db.transaction() as conn:
            conn.execute("UPDATE questions SET text=?, stem_text=?, updated_at=? WHERE id=?",
                         (merged_text, merged_text, _now(), target_id))
            row = conn.execute("SELECT COALESCE(MAX(option_index),0) AS m FROM options WHERE question_id=?",
                               (target_id,)).fetchone()
            nxt = int(row["m"]) + 1
            for o in source["options"]:
                conn.execute(
                    "INSERT INTO options(question_id, option_index, option_label, text, raw_text)"
                    " VALUES (?,?,?,?,?)",
                    (target_id, nxt, f"{nxt})", o["text"], o["raw_text"]))
                nxt += 1
            conn.execute("INSERT INTO review_history(entity_type, entity_id, action, old_value, new_value)"
                         " VALUES ('question', ?, 'merge', ?, ?)",
                         (target_id, f"merged q{source_id}", merged_text[:200]))
            conn.execute("DELETE FROM questions WHERE id=?", (source_id,))
        return target_id

    def split_question(self, question_id: int, first_text: str, second_text: str,
                       second_number: Optional[int] = None) -> int:
        """Split a combined record into two.

        The original record keeps *first_text*; a new record (created directly
        after it, flagged for review) holds *second_text* and no options.
        Returns the new question id.
        """
        original = self.db.query_one("SELECT * FROM questions WHERE id=?", (question_id,))
        if not original:
            return question_id
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE questions SET text=?, stem_text=?, updated_at=? WHERE id=?",
                (first_text, first_text, _now(), question_id))
            cur = conn.execute(
                "INSERT INTO questions(document_id, section_id, context_id, question_number,"
                " question_number_raw, page_number, page_end, order_index, text, stem_text,"
                " raw_text, is_mcq, extraction_method, needs_review, review_status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                (original["document_id"], original["section_id"], original["context_id"],
                 second_number, str(second_number) if second_number is not None else "",
                 original["page_number"], original["page_end"],
                 int(original["order_index"]) + 1, second_text, second_text, second_text,
                 1, config.EXTRACTION_METHOD_MANUAL, config.REVIEW_STATUS_NEEDS_REVIEW))
            new_id = int(cur.lastrowid)
            conn.execute("INSERT INTO review_history(entity_type, entity_id, action, old_value, new_value)"
                         " VALUES ('question', ?, 'split', ?, ?)",
                         (question_id, original["text"], f"{first_text} || {second_text}"))
        return new_id

    def link_context(self, question_id: int, context_id: Optional[int]) -> None:
        """Link (or unlink, with ``None``) a question's shared context."""
        row = self.db.query_one("SELECT context_id FROM questions WHERE id=?", (question_id,))
        if row is None:
            return
        self.db.execute("UPDATE questions SET context_id=?, updated_at=? WHERE id=?",
                        (context_id, _now(), question_id))
        self.db.connect().commit()
        self.log_review("question", question_id, "link_context",
                        str(row["context_id"]) if row["context_id"] is not None else None,
                        str(context_id) if context_id is not None else None)

    def delete_question(self, question_id: int) -> None:
        self.log_review("question", question_id, "delete", None, None)
        self.db.execute("DELETE FROM questions WHERE id=?", (question_id,))
        self.db.connect().commit()

    def delete_document(self, document_id: str) -> None:
        self.db.execute("DELETE FROM documents WHERE id=?", (document_id,))
        self.db.connect().commit()

    # ==================================================================
    # answer-key reads / edits
    # ==================================================================
    def list_answer_keys(self, document_id: str) -> list[dict]:
        rows = self.db.query(
            "SELECT ak.*, q.question_number AS q_number, q.text AS q_text"
            " FROM answer_keys ak LEFT JOIN questions q ON ak.match_question_id=q.id"
            " WHERE ak.document_id=? ORDER BY ak.question_number", (document_id,))
        return [dict(r) for r in rows]

    def answer_key_issues(self, document_id: str) -> dict:
        """Missing / duplicate / out-of-range / invalid-option report (no fixing)."""
        keys = self.list_answer_keys(document_id)
        by_num = {k["question_number"]: k for k in keys}
        q_rows = self.db.query(
            "SELECT q.id, q.question_number, (SELECT COUNT(*) FROM options o WHERE o.question_id=q.id) AS opt_count"
            " FROM questions q WHERE q.document_id=? AND q.question_number IS NOT NULL", (document_id,))
        questions = {r["question_number"]: r for r in q_rows}
        missing = sorted(set(questions) - set(by_num))
        out_of_range = sorted(n for n in by_num if n not in questions)
        invalid_option = []
        for n, k in by_num.items():
            q = questions.get(n)
            if q and k["option_index"] is not None and q["opt_count"] and k["option_index"] > q["opt_count"]:
                invalid_option.append(n)
        duplicates = [n for n, c in _counts(by_num).items() if c > 1]
        return {
            "missing": missing,
            "out_of_range": out_of_range,
            "invalid_option": sorted(invalid_option),
            "duplicate": sorted(duplicates),
            "total_keys": len(keys),
            "total_questions": len(questions),
        }

    # ==================================================================
    # dashboard metrics / filters
    # ==================================================================
    def dashboard_metrics(self) -> dict:
        def one(sql: str, params: tuple = ()) -> int:
            row = self.db.query_one(sql, params)
            return int(row["n"]) if row and row["n"] is not None else 0

        metrics = {
            "documents": one("SELECT COUNT(*) AS n FROM documents"),
            "pages": one("SELECT COUNT(*) AS n FROM pages"),
            "questions": one("SELECT COUNT(*) AS n FROM questions WHERE review_status != 'excluded'"),
            "needs_review": one("SELECT COUNT(*) AS n FROM questions WHERE needs_review=1 AND review_status != 'excluded'"),
            "confirmed": one("SELECT COUNT(*) AS n FROM questions WHERE review_status='confirmed'"),
            "excluded": one("SELECT COUNT(*) AS n FROM questions WHERE review_status='excluded'"),
            "contexts": one("SELECT COUNT(*) AS n FROM contexts"),
            "answer_keys": one("SELECT COUNT(*) AS n FROM answer_keys WHERE answer_value IS NOT NULL"),
            "answers_verified": one("SELECT COUNT(*) AS n FROM answer_keys WHERE review_status='confirmed'"),
            "missing_answer": one(
                "SELECT COUNT(*) AS n FROM questions q WHERE q.review_status != 'excluded'"
                " AND NOT EXISTS (SELECT 1 FROM answer_keys a WHERE a.match_question_id=q.id AND a.answer_value IS NOT NULL)"),
            "duplicate_candidates": one("SELECT COUNT(*) AS n FROM duplicate_candidates WHERE decision='pending'"),
            "math_questions": one("SELECT COUNT(*) AS n FROM questions WHERE is_math=1"),
        }
        metrics["by_subject"] = [
            dict(r) for r in self.db.query(
                "SELECT COALESCE(k.subject,'Unclassified') AS subject, COUNT(*) AS n"
                " FROM questions q"
                " LEFT JOIN question_classifications k ON k.question_id=q.id AND k.is_primary=1"
                " WHERE q.review_status != 'excluded' GROUP BY subject ORDER BY n DESC")
        ]
        metrics["by_review_status"] = [
            dict(r) for r in self.db.query(
                "SELECT review_status, COUNT(*) AS n FROM questions GROUP BY review_status ORDER BY n DESC")
        ]
        return metrics

    def filter_options(self) -> dict:
        return {
            "documents": self.list_documents(),
            "subjects": [r["subject"] for r in self.db.query(
                "SELECT DISTINCT subject FROM taxonomy WHERE level='subject' ORDER BY subject")],
            "exams": [r["exam"] for r in self.db.query(
                "SELECT DISTINCT exam FROM documents WHERE exam IS NOT NULL AND exam<>'' ORDER BY exam")],
            "years": [r["year"] for r in self.db.query(
                "SELECT DISTINCT year FROM documents WHERE year IS NOT NULL ORDER BY year DESC")],
        }

    def topics_for_subject(self, subject: str) -> list[str]:
        return [r["topic"] for r in self.db.query(
            "SELECT DISTINCT topic FROM taxonomy WHERE subject=? AND level='topic' ORDER BY topic",
            (subject,))]

    def subtopics_for(self, subject: str, topic: str) -> list[str]:
        return [r["subtopic"] for r in self.db.query(
            "SELECT subtopic FROM taxonomy WHERE subject=? AND topic=? AND level='subtopic' ORDER BY subtopic",
            (subject, topic))]

    def review_history(self, entity_type: Optional[str] = None, entity_id: Optional[int] = None,
                       limit: int = 200) -> list[dict]:
        clauses, params = [], []
        if entity_type:
            clauses.append("entity_type=?"); params.append(entity_type)
        if entity_id is not None:
            clauses.append("entity_id=?"); params.append(entity_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return [dict(r) for r in self.db.query(
            f"SELECT * FROM review_history {where} ORDER BY id DESC LIMIT ?", tuple(params) + (limit,))]


def _counts(items) -> dict:
    out: dict = {}
    for k in items:
        out[k] = out.get(k, 0) + 1
    return out


def _clip(value: Optional[str], limit: int = 2000) -> Optional[str]:
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit] + "…"


_default_classifier_cache = None


def _default_classifier():
    global _default_classifier_cache
    if _default_classifier_cache is None:
        from .services.classifier import Classifier
        from .taxonomy import Taxonomy
        tax = Taxonomy()
        tax.ensure_seeded()
        _default_classifier_cache = Classifier(tax)
    return _default_classifier_cache
