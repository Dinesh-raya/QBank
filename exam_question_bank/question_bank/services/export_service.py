"""Export services: structured JSON and spreadsheet-friendly CSV."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import config
from ..database import Database, get_db


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def build_export(document_id: Optional[str] = None, db: Optional[Database] = None) -> dict:
    """Assemble a nested, structured export for one document or the whole bank."""
    db = db or get_db()
    where = "WHERE q.document_id = ?" if document_id else ""
    params = (document_id,) if document_id else ()

    documents = _rows_to_dicts(db.query(
        "SELECT id, filename, sha256, page_count, format, exam, year, created_at "
        "FROM documents" + (" WHERE id=?" if document_id else ""),
        (document_id,) if document_id else (),))

    questions = db.query(
        f"""SELECT q.*, s.name AS section_name, c.label AS context_label,
                   c.context_type AS context_type
            FROM questions q
            LEFT JOIN sections s ON q.section_id = s.id
            LEFT JOIN contexts c ON q.context_id = c.id
            {where}
            ORDER BY q.document_id, q.order_index""", params)

    out_questions = []
    for q in questions:
        options = _rows_to_dicts(db.query(
            "SELECT option_index, option_label, text FROM options WHERE question_id=? ORDER BY option_index",
            (q["id"],)))
        classes = _rows_to_dicts(db.query(
            "SELECT subject, topic, subtopic, method, is_primary, review_status "
            "FROM question_classifications WHERE question_id=? ORDER BY is_primary DESC, id",
            (q["id"],)))
        tags = [r["tag"] for r in db.query(
            "SELECT tag FROM question_tags WHERE question_id=? ORDER BY tag", (q["id"],))]
        answer = None
        arow = db.query_one(
            "SELECT answer_value, option_index, match_status, review_status, extraction_method, page_number "
            "FROM answer_keys WHERE match_question_id=? AND document_id=?", (q["id"], q["document_id"]))
        if arow:
            answer = dict(arow)
        contexts = None
        if q["context_id"]:
            crow = db.query_one("SELECT * FROM contexts WHERE id=?", (q["context_id"],))
            if crow:
                contexts = {
                    "id": crow["id"], "type": crow["context_type"], "label": crow["label"],
                    "text": crow["text"], "page_start": crow["page_start"], "page_end": crow["page_end"],
                }
        out_questions.append({
            "id": q["id"],
            "document_id": q["document_id"],
            "section": q["section_name"],
            "question_number": q["question_number"],
            "page_number": q["page_number"],
            "page_end": q["page_end"],
            "text": q["text"],
            "stem_text": q["stem_text"],
            "raw_text": q["raw_text"],
            "is_mcq": bool(q["is_mcq"]),
            "is_math": bool(q["is_math"]),
            "math": json.loads(q["math_json"]) if q["math_json"] else None,
            "options": options,
            "classification": {
                "primary": classes[0] if classes else None,
                "all": classes,
            },
            "tags": tags,
            "correct_answer": answer,
            "answer_verified": bool(q["answer_verified"]),
            "extraction_method": q["extraction_method"],
            "quality_flags": (q["quality_flags"] or "").split(",") if q["quality_flags"] else [],
            "review_status": q["review_status"],
            "source": {
                "document_id": q["document_id"],
                "page": q["page_number"],
                "bbox": q["bbox"],
                "asset_path": q["asset_path"],
            },
            "shared_context": contexts,
            "created_at": q["created_at"],
            "updated_at": q["updated_at"],
        })

    contexts = _rows_to_dicts(db.query(
        "SELECT * FROM contexts" + (" WHERE document_id=?" if document_id else ""), params))
    answer_keys = _rows_to_dicts(db.query(
        "SELECT * FROM answer_keys" + (" WHERE document_id=?" if document_id else ""), params))
    sections = _rows_to_dicts(db.query(
        "SELECT * FROM sections" + (" WHERE document_id=?" if document_id else ""), params))

    return {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "schema": "exam-question-bank/1",
        "scope": document_id or "ALL",
        "documents": documents,
        "sections": sections,
        "contexts": contexts,
        "questions": out_questions,
        "answer_keys": answer_keys,
    }


def write_json(document_id: Optional[str] = None, out_path: Optional[Path] = None,
               db: Optional[Database] = None) -> Path:
    data = build_export(document_id, db)
    out_path = Path(out_path) if out_path else _default_path(document_id, "json")
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def write_csv(document_id: Optional[str] = None, out_path: Optional[Path] = None,
              db: Optional[Database] = None) -> Path:
    data = build_export(document_id, db)
    out_path = Path(out_path) if out_path else _default_path(document_id, "csv")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "question_id", "document_id", "question_number", "section", "page_number",
        "question_text", "options", "subject", "topic", "subtopic", "tags",
        "correct_answer", "answer_verified", "review_status", "needs_review",
        "is_math", "quality_flags",
    ])
    for q in data["questions"]:
        prim = q["classification"]["primary"] or {}
        opts = " | ".join(f'{o["option_index"]}) {o.get("text") or ""}' for o in q["options"])
        writer.writerow([
            q["id"], q["document_id"], q["question_number"], q["section"], q["page_number"],
            (q["text"] or "").replace("\n", " "), opts,
            prim.get("subject"), prim.get("topic"), prim.get("subtopic"),
            ",".join(q["tags"]),
            (q["correct_answer"] or {}).get("answer_value"),
            q["answer_verified"], q["review_status"],
            q["review_status"] == config.REVIEW_STATUS_NEEDS_REVIEW,
            q["is_math"], ",".join(q["quality_flags"]),
        ])
    # newline="" disables newline translation so the writer's own \r\n is not
    # doubled into \r\r\n on Windows.
    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(buf.getvalue())
    return out_path


def _default_path(document_id: Optional[str], ext: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scope = (document_id[:8] if document_id else "all")
    config.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return config.EXPORTS_DIR / f"question_bank_{scope}_{stamp}.{ext}"
