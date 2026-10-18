"""Non-destructive duplicate detection.

Produces candidate pairs with a similarity score. Nothing is ever merged or
deleted automatically; the user reviews candidates and marks them identical,
related or distinct. Repeated questions from different papers keep separate
source references.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from ..database import Database, get_db

_WS = re.compile(r"\s+")
_NUM = re.compile(r"\b\d+\b")


def normalize_question_text(text: str, drop_numbers: bool = False) -> str:
    t = (text or "").lower()
    t = _WS.sub(" ", t).strip()
    if drop_numbers:
        t = _NUM.sub("#", t)
    return t


@dataclass
class DuplicateCandidate:
    question_id: int
    other_question_id: int
    score: float
    method: str


class DuplicateDetector:
    def __init__(self, db: Database | None = None, threshold: float = 0.86):
        self.db = db or get_db()
        self.threshold = threshold

    def detect_for_document(self, document_id: str) -> list[DuplicateCandidate]:
        rows = self.db.query(
            "SELECT id, text FROM questions WHERE document_id=? AND text IS NOT NULL AND text<>''",
            (document_id,),
        )
        mine = [(r["id"], normalize_question_text(r["text"])) for r in rows]
        others = self.db.query(
            "SELECT id, text FROM questions WHERE document_id<>? AND text IS NOT NULL AND text<>''",
            (document_id,),
        )
        theirs = [(r["id"], normalize_question_text(r["text"])) for r in others]

        candidates: list[DuplicateCandidate] = []
        for qid, qtext in mine:
            if not qtext:
                continue
            for oid, otext in theirs:
                score = SequenceMatcher(None, qtext, otext).quick_ratio()
                if score < self.threshold:
                    continue
                ratio = SequenceMatcher(None, qtext, otext).ratio()
                if ratio >= self.threshold:
                    candidates.append(DuplicateCandidate(qid, oid, round(ratio, 4), "text_similarity"))

        self._persist(candidates)
        return candidates

    def _persist(self, candidates: list[DuplicateCandidate]) -> None:
        with self.db.transaction() as conn:
            for c in candidates:
                a, b = sorted((c.question_id, c.other_question_id))
                conn.execute(
                    "INSERT OR IGNORE INTO duplicate_candidates"
                    "(question_id, other_question_id, score, method) VALUES (?,?,?,?)",
                    (a, b, c.score, c.method),
                )
