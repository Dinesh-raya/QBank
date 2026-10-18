"""Shared pytest fixtures.

Tests are written so they *skip* (never error) when the optional reference PDF
or an optional dependency is absent. The reference paper (``Model Test 13.pdf``)
is a copyrighted local fixture and is intentionally git-ignored; place it at
``tests/fixtures/Model Test 13.pdf`` to enable the regression tests.

All data written by the tests goes to a temporary directory, never the project
``data/`` folder.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FIXTURE_PDF = Path(__file__).resolve().parent / "fixtures" / "Model Test 13.pdf"


def _import_core():
    try:
        import pymupdf  # noqa: F401
        from question_bank.database import Database
        from question_bank.pipeline import Pipeline
        from question_bank.repositories import Repository
    except Exception as exc:  # pragma: no cover - depends on environment
        pytest.skip(f"core dependencies unavailable: {exc}")


@pytest.fixture(scope="session")
def data_dirs(tmp_path_factory):
    """Redirect all local data directories to a temp folder for the session."""
    from question_bank import config

    root = tmp_path_factory.mktemp("qb_data")
    config.DATA_DIR = root
    config.UPLOADS_DIR = root / "uploads"
    config.RENDERS_DIR = root / "renders"
    config.ASSETS_DIR = root / "assets"
    config.EXPORTS_DIR = root / "exports"
    config.BACKUPS_DIR = root / "backups"
    config.DB_PATH = root / "question_bank.db"
    for d in (config.UPLOADS_DIR, config.RENDERS_DIR, config.ASSETS_DIR,
              config.EXPORTS_DIR, config.BACKUPS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(scope="session")
def processed(data_dirs):
    """Run the full pipeline once against the reference PDF (session scope)."""
    _import_core()
    if not FIXTURE_PDF.exists():
        pytest.skip(f"reference fixture not present at {FIXTURE_PDF}")

    from question_bank.database import Database
    from question_bank.pipeline import Pipeline
    from question_bank.repositories import Repository

    db = Database(data_dirs / "question_bank.db")
    db.initialise()
    repo = Repository(db)
    res = Pipeline(repository=repo).process(FIXTURE_PDF, exam="IBPS RRB Clerk")
    return SimpleNamespace(db=db, repo=repo, res=res, analysis=res.analysis,
                           doc_id=res.document_id)


@pytest.fixture()
def fresh_db(data_dirs):
    """A brand-new empty database (function scope) for unit-style DB tests."""
    _import_core()
    import importlib
    import question_bank.database as database_module

    path = data_dirs / f"unit_{id(object())}.db"
    db = database_module.Database(path)
    db.initialise()
    return db
