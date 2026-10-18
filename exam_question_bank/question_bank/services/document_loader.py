"""Document ingestion: hashing, safe storage and format detection.

Uploaded files are copied to ``data/uploads/<sha256>/original.<ext>`` and never
modified afterwards. The content hash gives us duplicate-document detection and
scope-limited re-processing.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .. import config

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SUPPORTED_EXTS = PDF_EXTS | IMAGE_EXTS


@dataclass
class LoadedDocument:
    filename: str
    sha256: str
    path: Path
    size_bytes: int
    doc_format: str          # 'pdf' | 'image'
    already_existed: bool = False


class DocumentLoadError(RuntimeError):
    pass


def sha256_of_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_format(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    # Fall back to magic bytes so mislabelled files still work.
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
        if head.startswith(b"%PDF"):
            return "pdf"
        if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8"):
            return "image"
    except OSError:
        pass
    raise DocumentLoadError(f"Unsupported file type: {path.name}")


def store_document(source_path: Path, uploads_dir: Optional[Path] = None) -> LoadedDocument:
    """Copy *source_path* into managed storage and return its handle."""
    source_path = Path(source_path)
    if not source_path.is_file():
        raise DocumentLoadError(f"File not found: {source_path}")

    doc_format = detect_format(source_path)
    digest = sha256_of_file(source_path)
    uploads_dir = uploads_dir or config.UPLOADS_DIR
    dest_dir = uploads_dir / digest
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = source_path.suffix.lower() or (".pdf" if doc_format == "pdf" else ".png")
    dest = dest_dir / f"original{ext}"

    already = dest.exists()
    if not already:
        # Copy, never move/overwrite the user's original.
        shutil.copyfile(source_path, dest)

    return LoadedDocument(
        filename=source_path.name,
        sha256=digest,
        path=dest,
        size_bytes=dest.stat().st_size,
        doc_format=doc_format,
        already_existed=already,
    )
