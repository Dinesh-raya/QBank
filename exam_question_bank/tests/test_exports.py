"""Export tests: JSON/CSV structure and content."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from question_bank.services import export_service


def test_json_export_structure(processed, data_dirs):
    data = export_service.build_export(processed.doc_id, processed.db)
    assert data["schema"] == "exam-question-bank/1"
    assert data["scope"] == processed.doc_id
    assert len(data["documents"]) == 1
    assert len(data["questions"]) == 80
    assert len(data["answer_keys"]) == 80
    assert len(data["contexts"]) == 12
    q = data["questions"][0]
    assert set(["options", "classification", "shared_context", "source"]).issubset(q)
    assert len(q["options"]) == 5


def test_write_json_file(processed, data_dirs, tmp_path):
    out = export_service.write_json(processed.doc_id, out_path=tmp_path / "export.json",
                                    db=processed.db)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["questions"]) == 80


def test_write_csv_file(processed, data_dirs, tmp_path):
    out = export_service.write_csv(processed.doc_id, out_path=tmp_path / "export.csv",
                                   db=processed.db)
    assert out.exists()
    with open(out, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][:6] == ["question_id", "document_id", "question_number", "section",
                           "page_number", "question_text"]
    assert len(rows) == 81  # header + 80 questions
    assert all(len(r) == len(rows[0]) for r in rows)
