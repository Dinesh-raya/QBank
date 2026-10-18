"""Export & Backup — JSON/CSV exports and full ZIP backup/restore."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from question_bank.services import backup_service, export_service
from question_bank.ui import bootstrap, get_repository, human_bytes, page_header

bootstrap()
st.set_page_config(page_title="Export & Backup", page_icon="💾", layout="wide")
page_header("💾 Export & Backup",
            "JSON/CSV are for sharing and spreadsheets. A backup is a full ZIP of the "
            "database and all local assets — CSV alone is not a backup.")

repo = get_repository()
docs = repo.list_documents()

st.subheader("Export")
scope = st.radio("Scope", ["Whole bank", "One document"], horizontal=True)
doc_id = None
if scope == "One document":
    if not docs:
        st.info("No documents to export.")
    else:
        labels = {f'{d["filename"]} ({d["sha256"][:8]})': d["id"] for d in docs}
        doc_id = labels[st.selectbox("Document", list(labels))]

c1, c2 = st.columns(2)
if c1.button("Create JSON export", type="primary"):
    path = export_service.write_json(doc_id)
    st.session_state["export_json"] = str(path)
if c2.button("Create CSV export", type="primary"):
    path = export_service.write_csv(doc_id)
    st.session_state["export_csv"] = str(path)

for key, mime in (("export_json", "application/json"), ("export_csv", "text/csv")):
    p = st.session_state.get(key)
    if p and Path(p).exists():
        st.download_button(f"⬇️ Download {Path(p).name}", Path(p).read_bytes(), file_name=Path(p).name, mime=mime)
        st.caption(f"Saved to `{p}`")

st.divider()
st.subheader("🔐 Encrypted Web App Vault (GitHub Pages)")
st.caption("Package and encrypt the entire Question Bank with AES-256-GCM for the standalone Web App / GitHub Pages.")

with st.form("web_vault_export_form"):
    vault_pass = st.text_input("Master Passphrase for Web Vault", type="password", placeholder="Enter your secret passphrase...")
    c_btn, _ = st.columns([1, 2])
    do_export_vault = c_btn.form_submit_button("Export & Encrypt for Web App", type="primary")

if do_export_vault:
    if not vault_pass.strip():
        st.error("Please enter a master passphrase to encrypt your question bank.")
    else:
        try:
            from scripts.export_encrypted_web import (build_export_data,
                                                      encrypt_payload)
            import json
            import subprocess
            data = build_export_data(repo)
            encrypted = encrypt_payload(data, vault_pass.strip())
            repo_root = Path(__file__).resolve().parent.parent.parent
            out_file = repo_root / "web_app" / "data.enc"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps(encrypted), encoding="utf-8")
            st.success(f"✅ Encrypted vault generated at: `{out_file}` ({out_file.stat().st_size / 1024:.1f} KB).")

            with st.spinner("Pushing updated vault to live GitHub Pages..."):
                try:
                    subprocess.run(["git", "add", "web_app/data.enc"], cwd=repo_root, check=True, capture_output=True)
                    subprocess.run(["git", "commit", "-m", "update: deploy updated encrypted vault"], cwd=repo_root, capture_output=True)
                    subprocess.run(["git", "push", "origin", "main"], cwd=repo_root, check=True, capture_output=True)
                    # Sync to gh-pages branch
                    subprocess.run(["git", "subtree", "split", "--prefix", "web_app", "-b", "gh-pages-sync"], cwd=repo_root, check=True, capture_output=True)
                    subprocess.run(["git", "branch", "-D", "gh-pages"], cwd=repo_root, capture_output=True)
                    subprocess.run(["git", "branch", "-m", "gh-pages-sync", "gh-pages"], cwd=repo_root, check=True, capture_output=True)
                    subprocess.run(["git", "push", "-f", "origin", "gh-pages:gh-pages"], cwd=repo_root, check=True, capture_output=True)
                    st.success("🚀 Successfully deployed to live site! Access at: https://dinesh-raya.github.io/QBank/")
                except Exception as git_err:
                    st.warning(f"Vault saved locally. To push online, run git push or check: {git_err}")
        except Exception as exc:
            st.error(f"Encryption failed: {exc}")
st.subheader("Backup")
if st.button("Create backup now"):
    info = backup_service.create_backup()
    st.success(f"Backup created: {info.path} ({human_bytes(info.size_bytes)}, "
               f"{info.file_count} asset files)")

backups = backup_service.list_backups()
if backups:
    st.dataframe([{
        "file": b.path.name, "created": b.created_at,
        "size": human_bytes(b.size_bytes), "db size": human_bytes(b.database_bytes),
    } for b in backups], hide_index=True, width="stretch")
    labels = {b.path.name: b.path for b in backups}
    chosen = labels[st.selectbox("Backup", list(labels))]
    st.download_button("⬇️ Download backup", Path(chosen).read_bytes(),
                       file_name=Path(chosen).name, mime="application/zip")
else:
    st.info("No backups yet.")

st.divider()
st.subheader("Restore")
st.warning("Restoring replaces the current database (and, optionally, asset files). "
           "The existing database is moved aside as `*.replaced` before being overwritten.")
up = st.file_uploader("Upload a backup ZIP to restore", type="zip")
restore_assets = st.checkbox("Also restore asset files (page renders, crops)", value=True)
if up is not None and st.button("Restore this backup", type="secondary"):
    tmp = Path("data") / "_restore_upload.zip"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(up.getbuffer())
    try:
        manifest = backup_service.restore_backup(tmp, restore_assets=restore_assets)
        st.success("Restored. Manifest: " + str(manifest.get("created_at", "unknown")))
        st.json(manifest.get("counts", {}))
    except Exception as exc:
        st.error(f"Restore failed: {exc}")
    finally:
        tmp.unlink(missing_ok=True)
