"""Editable Subject → Topic → Subtopic taxonomy.

The taxonomy is stored in the database (``taxonomy`` table) and seeded from
``config/default_taxonomy.json``. Subtopics are optional; topics are created
directly under their subject so the shipped taxonomy is immediately usable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from . import config
from .database import Database, get_db


@dataclass(frozen=True)
class TaxonomyEntry:
    id: Optional[int]
    subject: str
    topic: Optional[str]
    subtopic: Optional[str]
    level: str
    path: str
    is_active: bool = True


class TaxonomyError(ValueError):
    """Raised for invalid taxonomy operations (e.g. bad parent-child links)."""


def _slug(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _make_path(subject: str, topic: Optional[str] = None, subtopic: Optional[str] = None) -> str:
    parts = [_slug(subject)]
    if topic:
        parts.append(_slug(topic))
    if subtopic:
        parts.append(_slug(subtopic))
    return " > ".join(parts)


class Taxonomy:
    """Database-backed taxonomy with validation and safe CRUD operations."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    # -- seeding --------------------------------------------------------------
    def seed_from_file(self, path: Optional[Path] = None, *, replace: bool = False) -> int:
        path = Path(path) if path else config.DEFAULT_TAXONOMY_PATH
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return self.seed_from_dict(data, replace=replace)

    def seed_from_dict(self, data: dict, *, replace: bool = False) -> int:
        added = 0
        with self.db.transaction() as conn:
            if replace:
                conn.execute("DELETE FROM taxonomy")
            for subject in data.get("subjects", []):
                sname = _slug(subject["name"])
                added += self._ensure_row(conn, sname, None, None)
                for topic in subject.get("topics", []):
                    added += self._ensure_row(conn, sname, _slug(topic), None)
        return added

    def _ensure_row(self, conn, subject: str, topic: Optional[str], subtopic: Optional[str]) -> int:
        path = _make_path(subject, topic, subtopic)
        row = conn.execute("SELECT id FROM taxonomy WHERE path = ?", (path,)).fetchone()
        if row:
            return 0
        level = "subtopic" if subtopic else ("topic" if topic else "subject")
        conn.execute(
            "INSERT INTO taxonomy(subject, topic, subtopic, level, path, is_active) "
            "VALUES (?,?,?,?,?,1)",
            (subject, topic, subtopic, level, path),
        )
        return 1

    def ensure_seeded(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM taxonomy")
        if row and row["n"] > 0:
            return 0
        return self.seed_from_file()

    # -- reads ----------------------------------------------------------------
    def subjects(self, active_only: bool = True) -> list[str]:
        sql = "SELECT DISTINCT subject FROM taxonomy WHERE level='subject'"
        if active_only:
            sql += " AND is_active=1"
        sql += " ORDER BY sort_order, subject"
        return [r["subject"] for r in self.db.query(sql)]

    def topics(self, subject: str, active_only: bool = True) -> list[str]:
        sql = "SELECT topic FROM taxonomy WHERE level='topic' AND subject=?"
        if active_only:
            sql += " AND is_active=1"
        sql += " ORDER BY sort_order, topic"
        return [r["topic"] for r in self.db.query(sql, (subject,))]

    def subtopics(self, subject: str, topic: str, active_only: bool = True) -> list[str]:
        sql = "SELECT subtopic FROM taxonomy WHERE level='subtopic' AND subject=? AND topic=?"
        if active_only:
            sql += " AND is_active=1"
        sql += " ORDER BY sort_order, subtopic"
        return [r["subtopic"] for r in self.db.query(sql, (subject, topic))]

    def all_paths(self, active_only: bool = True) -> list[str]:
        sql = "SELECT path FROM taxonomy"
        if active_only:
            sql += " WHERE is_active=1"
        sql += " ORDER BY path"
        return [r["path"] for r in self.db.query(sql)]

    def entries(self) -> list[TaxonomyEntry]:
        rows = self.db.query("SELECT * FROM taxonomy ORDER BY subject, topic, subtopic")
        return [
            TaxonomyEntry(r["id"], r["subject"], r["topic"], r["subtopic"], r["level"], r["path"], bool(r["is_active"]))
            for r in rows
        ]

    def subjects_with_topics(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for s in self.subjects():
            out[s] = self.topics(s)
        return out

    def is_valid_path(self, subject: str, topic: Optional[str], subtopic: Optional[str] = None) -> bool:
        return any(e.path == _make_path(subject, topic, subtopic) for e in self.entries() if e.is_active)

    # -- writes ---------------------------------------------------------------
    def add_subject(self, subject: str) -> int:
        subject = _slug(subject)
        if not subject:
            raise TaxonomyError("Subject name must not be empty")
        with self.db.transaction() as conn:
            return self._ensure_row(conn, subject, None, None)

    def add_topic(self, subject: str, topic: str) -> int:
        subject, topic = _slug(subject), _slug(topic)
        if not subject or not topic:
            raise TaxonomyError("Subject and topic names must not be empty")
        if subject not in self.subjects(active_only=False):
            raise TaxonomyError(f"Unknown subject: {subject!r}")
        with self.db.transaction() as conn:
            return self._ensure_row(conn, subject, topic, None)

    def add_subtopic(self, subject: str, topic: str, subtopic: str) -> int:
        subject, topic, subtopic = _slug(subject), _slug(topic), _slug(subtopic)
        if not (subject and topic and subtopic):
            raise TaxonomyError("Subject, topic and subtopic names must not be empty")
        if topic not in self.topics(subject, active_only=False):
            raise TaxonomyError(f"Unknown topic {topic!r} under subject {subject!r}")
        with self.db.transaction() as conn:
            return self._ensure_row(conn, subject, topic, subtopic)

    def rename(self, path: str, new_name: str) -> None:
        """Rename a subject/topic/subtopic and cascade to child paths."""
        new_name = _slug(new_name)
        if not new_name:
            raise TaxonomyError("New name must not be empty")
        row = self.db.query_one("SELECT * FROM taxonomy WHERE path=?", (path,))
        if not row:
            raise TaxonomyError(f"Unknown taxonomy path: {path!r}")
        old_parts = path.split(" > ")
        new_parts = list(old_parts)
        new_parts[-1] = new_name
        new_path = " > ".join(new_parts)
        with self.db.transaction() as conn:
            # Update the row itself.
            conn.execute(
                "UPDATE taxonomy SET subject=?, topic=?, subtopic=?, path=? WHERE id=?",
                (
                    new_parts[0],
                    new_parts[1] if len(new_parts) > 1 else None,
                    new_parts[2] if len(new_parts) > 2 else None,
                    new_path,
                    row["id"],
                ),
            )
            # Cascade to descendants (path prefix).
            descendants = conn.execute(
                "SELECT id, path FROM taxonomy WHERE path LIKE ? AND id != ?",
                (path + " > %", row["id"]),
            ).fetchall()
            for d in descendants:
                d_new = new_path + d["path"][len(path):]
                conn.execute("UPDATE taxonomy SET path=? WHERE id=?", (d_new, d["id"]))

    def set_active(self, path: str, active: bool) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE taxonomy SET is_active=? WHERE path=?", (1 if active else 0, path))

    def delete(self, path: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM taxonomy WHERE path=? OR path LIKE ?", (path, path + " > %"))
