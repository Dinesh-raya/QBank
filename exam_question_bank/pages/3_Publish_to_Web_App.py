"""Step 3: Publish to Web App & Backups — 1-click sync to GitHub Pages and full backups."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import streamlit as st

from question_bank.services import backup_service, export_service
from question_bank.ui import bootstrap, get_repository, human_bytes, page_header

bootstrap()
st.set_page_config(page_title="Publish to Web App", page_icon="🚀", layout="wide")
page_header("🚀 Step 3: Publish to Web App & Backups",
            "Encrypt the entire question bank with AES-256-GCM and deploy directly to your free GitHub Pages portal.")

repo = get_repository()
docs = repo.list_documents()
metrics = repo.dashboard_metrics()

# Live Web App Status Box
st.markdown(
    """
    <div style="background: linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(168, 85, 247, 0.12));
                border: 1px solid rgba(139, 92, 246, 0.4); border-radius: 12px; padding: 20px 24px; margin-bottom: 24px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px;">
            <div>
                <span style="background: #10b981; color: #ffffff; padding: 3px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;">Live</span>
                <h3 style="margin: 6px 0 4px 0; color: #f8fafc; font-size: 1.25rem;">
                    GitHub Pages Portal: <a href="https://dinesh-raya.github.io/QBank/" target="_blank" style="color: #a5b4fc; text-decoration: underline;">https://dinesh-raya.github.io/QBank/</a>
                </h3>
                <p style="margin: 0; color: #94a3b8; font-size: 0.92rem;">
                    All students and readers access questions through this encrypted URL. Zero cloud servers required.
                </p>
            </div>
            <div>
                <a href="https://dinesh-raya.github.io/QBank/" target="_blank"
                   style="display: inline-block; background: #6366f1; color: #ffffff; text-decoration: none;
                          padding: 10px 22px; border-radius: 8px; font-weight: 600; font-size: 0.92rem;
                          box-shadow: 0 4px 14px rgba(99, 102, 241, 0.4);">
                    Visit Live Portal ↗
                </a>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Publishing Readiness Metrics
c1, c2, c3 = st.columns(3)
c1.metric("Questions Ready to Publish", metrics["questions"])
c2.metric("Documents Ingested", metrics["documents"])
c3.metric("Review Flags", metrics["needs_review"], help="Questions flagged for review will still be included.")

st.divider()

# ---------------------------------------------------------------------------
# PUBLISH TO GITHUB PAGES
# ---------------------------------------------------------------------------
st.subheader("🔐 Encrypt & Publish to Live Web App")
st.caption("Packages questions, multi-column options, cropped math formulas, and stimulus puzzles into a secure client-side vault.")

repo_root = Path(__file__).resolve().parent.parent.parent
key_file = repo_root / ".vault_key"

# Read saved passphrase if available
saved_pass = ""
if key_file.exists():
    try:
        saved_pass = key_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass

with st.form("web_publish_form"):
    vault_pass = st.text_input(
        "Master Passphrase",
        type="password",
        value=saved_pass,
        placeholder="Enter your secret master passphrase…",
        help="This passphrase is required by readers to unlock the web app on GitHub Pages."
    )
    remember_pass = st.checkbox("Remember passphrase on this local machine (saved to .vault_key)", value=bool(saved_pass))
    
    c_pub, _ = st.columns([1, 2])
    do_publish = c_pub.form_submit_button("🚀 1-Click Publish to Live GitHub Pages", type="primary")

if do_publish:
    if not vault_pass.strip():
        st.error("Please enter a master passphrase to encrypt your question bank.")
    else:
        # Save or clear local key
        if remember_pass:
            key_file.write_text(vault_pass.strip(), encoding="utf-8")
        elif key_file.exists():
            key_file.unlink(missing_ok=True)
            
        with st.status("Publishing Question Bank to GitHub Pages…", expanded=True) as status:
            try:
                st.write("1. Extracting questions, stimulus crops & page renders from database…")
                from scripts.export_encrypted_web import (build_export_data,
                                                          encrypt_payload)
                data = build_export_data(repo)
                
                st.write(f"2. Encrypting {len(data['questions'])} questions with AES-256-GCM (100,000 PBKDF2 rounds)…")
                encrypted = encrypt_payload(data, vault_pass.strip())
                
                out_file = repo_root / "web_app" / "data.enc"
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_text(json.dumps(encrypted), encoding="utf-8")
                st.write(f"3. Generated encrypted vault ({out_file.stat().st_size / 1024:.1f} KB).")
                
                st.write("4. Syncing update to GitHub Pages (`gh-pages` branch)…")
                subprocess.run(["git", "add", "web_app/data.enc"], cwd=repo_root, check=True, capture_output=True)
                subprocess.run(["git", "commit", "-m", "update: deploy latest encrypted question bank"], cwd=repo_root, capture_output=True)
                subprocess.run(["git", "push", "origin", "main"], cwd=repo_root, check=True, capture_output=True)
                
                # Push subtree to gh-pages branch
                subprocess.run(["git", "subtree", "split", "--prefix", "web_app", "-b", "gh-pages-deploy"], cwd=repo_root, check=True, capture_output=True)
                subprocess.run(["git", "branch", "-D", "gh-pages"], cwd=repo_root, capture_output=True)
                subprocess.run(["git", "branch", "-m", "gh-pages-deploy", "gh-pages"], cwd=repo_root, check=True, capture_output=True)
                subprocess.run(["git", "push", "-f", "origin", "gh-pages:gh-pages"], cwd=repo_root, check=True, capture_output=True)
                
                status.update(label="🎉 Successfully published live to GitHub Pages!", state="complete")
                st.balloons()
                st.success("Your live website is updated! Open: https://dinesh-raya.github.io/QBank/")
            except Exception as exc:
                status.update(label="Publish failed", state="error")
                st.error(f"Error publishing: {exc}")

st.divider()

# ---------------------------------------------------------------------------
# OFFLINE EXPORTS & DATABASE BACKUPS
# ---------------------------------------------------------------------------
st.subheader("💾 Offline Exports & Full Database Backups")

tab_exp, tab_bk = st.tabs(["📊 JSON / CSV Exports", "📦 Full System Backup & Restore"])

with tab_exp:
    st.caption("Export question bank data for spreadsheets, data analysis, or printing.")
    scope = st.radio("Export Scope", ["Entire Bank", "Single Document"], horizontal=True)
    doc_id = None
    if scope == "Single Document":
        if docs:
            d_labels = {f'{d["filename"]} ({d["sha256"][:8]})': d["id"] for d in docs}
            doc_id = d_labels[st.selectbox("Choose Document", list(d_labels))]
            
    col_j, col_c = st.columns(2)
    if col_j.button("📄 Create JSON Export"):
        p = export_service.write_json(doc_id)
        st.download_button("⬇️ Download JSON File", Path(p).read_bytes(), file_name=Path(p).name, mime="application/json")
    if col_c.button("📊 Create CSV Export"):
        p = export_service.write_csv(doc_id)
        st.download_button("⬇️ Download CSV File", Path(p).read_bytes(), file_name=Path(p).name, mime="text/csv")

with tab_bk:
    st.caption("Create a complete ZIP archive containing the SQLite database and all rendered page images and crops.")
    if st.button("📦 Create Full Backup ZIP"):
        info = backup_service.create_backup()
        st.success(f"Backup created: {info.path.name} ({human_bytes(info.size_bytes)})")
        st.download_button("⬇️ Download Backup ZIP", info.path.read_bytes(), file_name=info.path.name, mime="application/zip")
        
    backups = backup_service.list_backups()
    if backups:
        st.markdown("**Existing Backups:**")
        st.dataframe([{
            "Filename": b.path.name, "Date": b.created_at,
            "Total Size": human_bytes(b.size_bytes), "DB Size": human_bytes(b.database_bytes)
        } for b in backups], hide_index=True, width="stretch")
