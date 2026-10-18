"""SQLite connection handling, schema definition and lightweight migrations.

The schema is normalised (no "big JSON blob" question bank) with explicit
foreign keys, indexes, and a ``schema_version`` table for forward migrations.
Only parameterised SQL is used; the access layer lives in ``repositories``.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from . import config

SCHEMA_VERSION = 1

_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    sha256          TEXT NOT NULL UNIQUE,
    path            TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    page_count      INTEGER NOT NULL DEFAULT 0,
    format          TEXT NOT NULL DEFAULT 'pdf',
    exam            TEXT,
    year            INTEGER,
    source_notes    TEXT,
    status          TEXT NOT NULL DEFAULT 'imported',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number     INTEGER NOT NULL,
    width           REAL,
    height          REAL,
    rotation        INTEGER DEFAULT 0,
    text_char_count INTEGER DEFAULT 0,
    image_count     INTEGER DEFAULT 0,
    drawing_count   INTEGER DEFAULT 0,
    has_text        INTEGER DEFAULT 0,
    is_scanned      INTEGER DEFAULT 0,
    page_type       TEXT DEFAULT 'digital',
    quality_flags   TEXT,
    raw_text        TEXT,
    cleaned_text    TEXT,
    render_path     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (document_id, page_number)
);

CREATE TABLE IF NOT EXISTS sections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    page_number     INTEGER,
    order_index     INTEGER NOT NULL DEFAULT 0,
    start_question  INTEGER,
    end_question    INTEGER,
    raw_bbox        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contexts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    context_type    TEXT NOT NULL DEFAULT 'other',
    label           TEXT,
    text            TEXT,
    raw_text        TEXT,
    page_start      INTEGER,
    page_end        INTEGER,
    question_start  INTEGER,
    question_end    INTEGER,
    bbox            TEXT,
    asset_path      TEXT,
    structured_json TEXT,
    verified        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id      INTEGER REFERENCES sections(id) ON DELETE SET NULL,
    context_id      INTEGER REFERENCES contexts(id) ON DELETE SET NULL,
    question_number INTEGER,
    question_number_raw TEXT,
    page_number     INTEGER,
    page_end        INTEGER,
    order_index     INTEGER NOT NULL DEFAULT 0,
    text            TEXT,
    stem_text       TEXT,
    raw_text        TEXT,
    bbox            TEXT,
    asset_path      TEXT,
    math_json       TEXT,
    is_mcq          INTEGER NOT NULL DEFAULT 1,
    is_math         INTEGER NOT NULL DEFAULT 0,
    extraction_method TEXT,
    quality_flags   TEXT,
    needs_review    INTEGER NOT NULL DEFAULT 1,
    review_status   TEXT NOT NULL DEFAULT 'draft',
    correct_answer  TEXT,
    answer_verified INTEGER NOT NULL DEFAULT 0,
    explanation     TEXT,
    classification_method TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS options (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id     INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    option_index    INTEGER NOT NULL,
    option_label    TEXT,
    text            TEXT,
    raw_text        TEXT,
    bbox            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (question_id, option_index)
);

CREATE TABLE IF NOT EXISTS taxonomy (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subject         TEXT NOT NULL,
    topic           TEXT,
    subtopic        TEXT,
    level           TEXT NOT NULL,
    parent_id       INTEGER REFERENCES taxonomy(id) ON DELETE CASCADE,
    path            TEXT NOT NULL UNIQUE,
    is_active       INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS question_classifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id     INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    subject         TEXT,
    topic           TEXT,
    subtopic        TEXT,
    method          TEXT,
    confidence      REAL,
    confidence_kind TEXT,
    is_primary      INTEGER NOT NULL DEFAULT 1,
    review_status   TEXT NOT NULL DEFAULT 'suggested',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS question_tags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id     INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    tag             TEXT NOT NULL,
    kind            TEXT DEFAULT 'secondary',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (question_id, tag)
);

CREATE TABLE IF NOT EXISTS answer_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    question_number INTEGER NOT NULL,
    option_index    INTEGER,
    answer_value    TEXT,
    page_number     INTEGER,
    extraction_method TEXT,
    match_status    TEXT NOT NULL DEFAULT 'unmatched',
    match_question_id INTEGER REFERENCES questions(id) ON DELETE SET NULL,
    review_status   TEXT NOT NULL DEFAULT 'unreviewed',
    raw_text        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (document_id, question_number)
);

CREATE TABLE IF NOT EXISTS review_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT NOT NULL,
    entity_id       INTEGER,
    action          TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number     INTEGER,
    stage           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    message         TEXT,
    started_at      TEXT,
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS duplicate_candidates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id     INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    other_question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    score           REAL,
    method          TEXT,
    decision        TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (question_id, other_question_id)
);

CREATE INDEX IF NOT EXISTS idx_pages_doc          ON pages(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_questions_doc      ON questions(document_id, question_number);
CREATE INDEX IF NOT EXISTS idx_questions_number   ON questions(question_number);
CREATE INDEX IF NOT EXISTS idx_questions_context  ON questions(context_id);
CREATE INDEX IF NOT EXISTS idx_questions_review   ON questions(review_status);
CREATE INDEX IF NOT EXISTS idx_options_question   ON options(question_id);
CREATE INDEX IF NOT EXISTS idx_sections_doc       ON sections(document_id);
CREATE INDEX IF NOT EXISTS idx_contexts_doc       ON contexts(document_id);
CREATE INDEX IF NOT EXISTS idx_taxonomy_level     ON taxonomy(level);
CREATE INDEX IF NOT EXISTS idx_class_question     ON question_classifications(question_id);
CREATE INDEX IF NOT EXISTS idx_answerkey_doc      ON answer_keys(document_id);
"""


class Database:
    """Thin wrapper around a SQLite file with per-thread connections."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else config.DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialised = False

    # -- connection management ------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # -- schema ---------------------------------------------------------------
    def initialise(self) -> None:
        with self._init_lock:
            if self._initialised:
                return
            conn = self.connect()
            conn.executescript(_DDL)
            cur = conn.execute("SELECT version FROM schema_version")
            row = cur.fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
            conn.commit()
            self._initialised = True

    def schema_version(self) -> int:
        conn = self.connect()
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return int(row[0]) if row else 0

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = self.connect()
        return conn.execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.connect().execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self.connect().execute(sql, params).fetchone()


_default_db: Optional[Database] = None


def get_db(path: Optional[Path] = None) -> Database:
    """Return the process-wide default database (initialised on first use)."""
    global _default_db
    if _default_db is None or (path is not None and Path(path) != _default_db.path):
        db = Database(path)
        db.initialise()
        _default_db = db
    return _default_db
