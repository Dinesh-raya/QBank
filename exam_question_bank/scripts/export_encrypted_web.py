"""Export the Question Bank into an AES-256-GCM encrypted payload for the Web App.

Usage:
    python scripts/export_encrypted_web.py --password "YourSecretPassphrase"
    python scripts/export_encrypted_web.py --output ../web_app/data.enc
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from question_bank import config
from question_bank.repositories import Repository


def file_to_b64(path_str: str | None) -> str | None:
    if not path_str:
        return None
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    if p.exists() and p.is_file():
        data = p.read_bytes()
        mime = "image/png"
        if p.suffix.lower() in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    return None


def _get_render_dir(doc_id: str) -> Path:
    """Return the directory that holds page_XXX.png renders for a document."""
    return ROOT / "data" / "renders" / doc_id


def build_export_data(repo: Repository, include_pages: bool = True) -> dict[str, Any]:
    docs = repo.list_documents()
    questions_raw = repo.list_questions(limit=5000)

    # ── page renders (keyed by doc_id → page_number → data-URI) ──────────────
    page_renders: dict[str, dict[int, str]] = {}
    if include_pages:
        for d in docs:
            render_dir = _get_render_dir(d["id"])
            if render_dir.exists():
                renders = {}
                for png in sorted(render_dir.glob("page_*.png")):
                    try:
                        page_num = int(png.stem.split("_")[1])
                        b64 = base64.b64encode(png.read_bytes()).decode("ascii")
                        renders[page_num] = f"data:image/png;base64,{b64}"
                    except (ValueError, IndexError):
                        pass
                page_renders[d["id"]] = renders

    # ── contexts ──────────────────────────────────────────────────────────────
    contexts_raw: dict[str, Any] = {}
    for d in docs:
        for c in repo.list_contexts(d["id"]):
            img_b64 = file_to_b64(c.get("asset_path"))
            contexts_raw[c["id"]] = {
                "id": c["id"],
                "document_id": c["document_id"],
                "label": c.get("label"),
                "context_type": c.get("context_type"),
                "text": c.get("text"),
                "page_start": c.get("page_start"),
                "page_end": c.get("page_end"),
                "question_start": c.get("question_start"),
                "question_end": c.get("question_end"),
                "sequence": (c.get("structured") or {}).get("sequence"),
                "image_b64": img_b64,
            }

    # ── questions ─────────────────────────────────────────────────────────────
    questions: list[dict[str, Any]] = []
    topic_counts: dict[str, dict[str, int]] = {}

    for q_summary in questions_raw:
        q = repo.get_question(q_summary["id"])

        prim_cls = next((c for c in q["classifications"] if c.get("is_primary")), None)
        if not prim_cls and q["classifications"]:
            prim_cls = q["classifications"][0]

        subj = prim_cls["subject"] if prim_cls else "Unclassified"
        top  = prim_cls["topic"]   if prim_cls else "General"
        subt = prim_cls.get("subtopic") if prim_cls else None

        topic_counts.setdefault(subj, {})
        topic_counts[subj][top] = topic_counts[subj].get(top, 0) + 1

        q_crop_b64 = file_to_b64(q.get("asset_path"))
        page_num   = q.get("page_number") or 1

        from question_bank.services.typography import format_stem_typography
        stem_formatted = format_stem_typography(q.get("stem_text") or q.get("text") or "")

        q_item = {
            "id":                q["id"],
            "number":            q.get("question_number"),
            "page":              page_num,
            "document_id":       q["document_id"],
            "document_filename": q.get("filename"),
            "section":           q.get("section_name"),
            "subject":           subj,
            "topic":             top,
            "subtopic":          subt,
            "tags":              q.get("tags") or [],
            "stem":              stem_formatted,
            "is_math":           bool(q.get("is_math")),
            "math":              q.get("math"),
            "crop_b64":          q_crop_b64,
            "context_id":        q.get("context_id"),
            "context":           contexts_raw.get(q.get("context_id")),
            "options": [{
                "index": o["option_index"],
                "label": o.get("option_label") or str(o["option_index"]),
                "text":  o.get("text") or "",
            } for o in (q.get("options") or [])],
            "answer": {
                "option_index": q["answer"].get("option_index"),
                "value":        q["answer"].get("answer_value"),
                "status":       q["answer"].get("review_status"),
                "method":       q["answer"].get("extraction_method"),
            } if q.get("answer") else None,
            "review_status": q.get("review_status"),
        }
        questions.append(q_item)

    # ── documents list (include page-count for UI) ────────────────────────────
    documents = []
    for d in docs:
        doc_entry: dict[str, Any] = {
            "id":       d["id"],
            "filename": d["filename"],
            "exam":     d.get("exam"),
            "year":     d.get("year"),
            "pages":    d.get("page_count"),
        }
        # Embed page renders keyed as str for JSON
        if d["id"] in page_renders:
            doc_entry["page_renders"] = {
                str(k): v for k, v in page_renders[d["id"]].items()
            }
        documents.append(doc_entry)

    return {
        "version":        "1.1",
        "created_at":     str(os.environ.get("BUILD_TIMESTAMP") or "2026-10-18"),
        "stats": {
            "total_questions":  len(questions),
            "total_documents":  len(documents),
            "total_contexts":   len(contexts_raw),
        },
        "taxonomy_index": topic_counts,
        "documents":      documents,
        "questions":      questions,
    }


def encrypt_payload(data: dict[str, Any], password: str) -> dict[str, str]:
    raw_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = kdf.derive(password.encode("utf-8"))
    iv = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, raw_bytes, None)

    return {
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export encrypted question bank for Web App")
    parser.add_argument("--password", default=None, help="Master encryption password")
    parser.add_argument("--output", default=None, help="Output file path (default: web_app/data.enc)")
    args = parser.parse_args()

    password = args.password
    if not password:
        password = os.environ.get("QBANK_MASTER_PASSWORD")
    if not password:
        import getpass
        password = getpass.getpass("Enter master password to encrypt Question Bank: ")
        if not password.strip():
            print("Error: Password cannot be empty.", file=sys.stderr)
            return 1

    repo = Repository()
    print("Building Question Bank dataset from SQLite...")
    data = build_export_data(repo)
    print(f"Loaded {len(data['questions'])} questions across {len(data['taxonomy_index'])} subjects.")

    print("Encrypting with AES-256-GCM (PBKDF2 100,000 rounds)...")
    encrypted = encrypt_payload(data, password)

    out_path = Path(args.output) if args.output else (ROOT.parent / "web_app" / "data.enc")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(encrypted), encoding="utf-8")

    size_kb = out_path.stat().st_size / 1024
    print(f"Encrypted vault generated successfully at: {out_path} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
