"""Backup and restore: one ZIP containing the SQLite DB plus all local assets.

CSV export is *not* a backup (it cannot restore the bank). A real backup must
round-trip the database together with the uploaded originals, page renders and
cropped assets, so a restore returns the exact prior state.

The SQLite file is snapshotted with the online-backup API rather than copied,
so a live WAL database is captured consistently.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import config
from ..database import Database, get_db

_MANIFEST = "backup_manifest.json"


@dataclass
class BackupInfo:
    path: Path
    created_at: str
    size_bytes: int
    database_bytes: int
    file_count: int


def _snapshot_sqlite(db_path: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def create_backup(dest_path: Optional[Path] = None, *, db: Optional[Database] = None) -> BackupInfo:
    """Create a ZIP backup and return its metadata."""
    db = db or get_db()
    db.initialise()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_path = Path(dest_path) if dest_path else (config.BACKUPS_DIR / f"question_bank_backup_{stamp}.zip")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="qbank_backup_") as tmp:
        tmp_dir = Path(tmp)
        snap = tmp_dir / "question_bank.db"
        _snapshot_sqlite(db.path, snap)

        # Count files under data/ (excluding the DB itself and backups).
        file_count = 0
        members: list[Path] = []
        for root in (config.UPLOADS_DIR, config.RENDERS_DIR, config.ASSETS_DIR):
            if root.exists():
                for p in root.rglob("*"):
                    if p.is_file():
                        members.append(p)
                        file_count += 1

        manifest = {
            "schema": "exam-question-bank-backup/1",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "database_schema_version": db.schema_version(),
            "database_name": "question_bank.db",
            "counts": _table_counts(db),
            "asset_files": file_count,
            "note": "ZIP contains the database snapshot and all local asset files.",
        }
        (tmp_dir / _MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snap, "question_bank.db")
            zf.write(tmp_dir / _MANIFEST, _MANIFEST)
            for p in members:
                zf.write(p, p.relative_to(config.DATA_DIR).as_posix())

        info = BackupInfo(
            path=dest_path,
            created_at=manifest["created_at"],
            size_bytes=dest_path.stat().st_size,
            database_bytes=snap.stat().st_size,
            file_count=file_count,
        )
    return info


def _table_counts(db: Database) -> dict:
    counts: dict[str, int] = {}
    for table in ("documents", "pages", "questions", "options", "contexts",
                  "sections", "answer_keys", "taxonomy", "question_classifications"):
        try:
            row = db.query_one(f"SELECT COUNT(*) AS n FROM {table}")
            counts[table] = int(row["n"]) if row else 0
        except sqlite3.Error:
            counts[table] = -1
    return counts


def restore_backup(zip_path: Path, *, target_db: Optional[Path] = None,
                   restore_assets: bool = True) -> dict:
    """Restore a backup ZIP created by ``create_backup``.

    Returns the manifest. Existing target files are *moved aside* (``*.replaced``)
    before being overwritten so a failed restore never destroys the current bank.
    """
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise FileNotFoundError(f"Backup not found: {zip_path}")

    target_db = Path(target_db) if target_db else config.DB_PATH
    manifest: dict = {}
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if "question_bank.db" not in names:
            raise ValueError("Not a valid question bank backup: database snapshot missing")
        if _MANIFEST in names:
            manifest = json.loads(zf.read(_MANIFEST).decode("utf-8"))

        _replace_file(target_db, lambda tmp: _extract_member(zf, "question_bank.db", tmp))

        if restore_assets:
            for name in names:
                if name in ("question_bank.db", _MANIFEST) or name.endswith("/"):
                    continue
                out = config.DATA_DIR / name
                _replace_file(out, lambda tmp, _n=name: _extract_member(zf, _n, tmp))
    return manifest


def _extract_member(zf: zipfile.ZipFile, name: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(name) as src, open(dest, "wb") as fh:
        shutil.copyfileobj(src, fh)


def _replace_file(dest: Path, writer) -> None:
    """Write *dest* atomically-ish via a temp file, preserving the old one."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".restoring")
    if tmp.exists():
        tmp.unlink()
    writer(tmp)
    if dest.exists():
        backup = dest.with_suffix(dest.suffix + ".replaced")
        if backup.exists():
            backup.unlink()
        dest.replace(backup)
    tmp.replace(dest)


def list_backups(directory: Optional[Path] = None) -> list[BackupInfo]:
    directory = Path(directory) if directory else config.BACKUPS_DIR
    out: list[BackupInfo] = []
    if not directory.exists():
        return out
    for z in sorted(directory.glob("*.zip"), reverse=True):
        created = ""
        db_bytes = 0
        try:
            with zipfile.ZipFile(z) as zf:
                if _MANIFEST in zf.namelist():
                    m = json.loads(zf.read(_MANIFEST).decode("utf-8"))
                    created = m.get("created_at", "")
                    db_bytes = zf.getinfo("question_bank.db").file_size if "question_bank.db" in zf.namelist() else 0
        except (zipfile.BadZipFile, OSError):
            pass
        out.append(BackupInfo(z, created, z.stat().st_size, db_bytes, 0))
    return out
