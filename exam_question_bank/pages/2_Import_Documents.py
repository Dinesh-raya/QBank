"""Import Documents — upload PDFs/images and run the extraction pipeline."""
from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from question_bank import config
from question_bank.pipeline import Pipeline
from question_bank.services.document_loader import SUPPORTED_EXTS
from question_bank.ui import bootstrap, get_repository, human_bytes, page_header

bootstrap()
st.set_page_config(page_title="Import Documents", page_icon="📥", layout="wide")
page_header("📥 Import Documents", "Upload exam papers (digital PDFs or scanned images).")

repo = get_repository()

with st.form("import_form"):
    files = st.file_uploader(
        "Choose one or more files",
        type=sorted(e.lstrip(".") for e in SUPPORTED_EXTS),
        accept_multiple_files=True,
    )
    c1, c2 = st.columns(2)
    exam = c1.text_input("Exam name (optional)", value=config.DEFAULT_EXAM)
    year = c2.text_input("Year (optional)", value="")
    use_ai = st.checkbox(
        "Use the optional local AI classifier for questions rules can't place",
        value=False,
        help="Requires a running Ollama/OpenAI-compatible server (see Settings).",
    )
    submitted = st.form_submit_button("Process files", type="primary")

if submitted:
    if not files:
        st.warning("Choose at least one file.")
    else:
        year_val = int(year) if str(year).strip().isdigit() else None
        pipeline = Pipeline(repository=repo, use_ai=use_ai)
        results = []
        progress = st.progress(0.0, text="Starting…")
        for i, uploaded in enumerate(files):
            progress.progress(i / len(files), text=f"Processing {uploaded.name}…")
            try:
                suffix = Path(uploaded.name).suffix or ".pdf"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(uploaded.getbuffer())
                    tmp_path = Path(tmp.name)
                try:
                    res = pipeline.process(tmp_path, exam=exam or None, year=year_val)
                finally:
                    tmp_path.unlink(missing_ok=True)
                results.append((uploaded.name, res, None))
            except Exception as exc:  # keep other files going
                results.append((uploaded.name, None, str(exc)))
        progress.empty()
        st.session_state["import_results"] = results
        st.success(f"Processed {len(files)} file(s).")

results = st.session_state.get("import_results")
if results:
    st.subheader("Last processing run")
    for name, res, err in results:
        if err:
            st.error(f"**{name}** — failed: {err}")
            continue
        with st.expander(f"✅ {name} — {res.stats.get('questions', 0)} questions, "
                         f"{res.stats.get('pages', 0)} pages", expanded=False):
            st.json(res.stats)
            if res.warnings:
                st.warning("Warnings: " + "; ".join(res.warnings))
            else:
                st.success("No warnings.")
            st.caption(f"Document id: `{res.document_id}`")

st.divider()
st.subheader("Imported documents")
docs = repo.list_documents()
if not docs:
    st.info("No documents imported yet.")
else:
    st.dataframe(
        [{
            "file": d["filename"], "exam": d.get("exam") or "", "year": d.get("year") or "",
            "pages": d["page_count"], "questions": d["question_count"],
            "size": human_bytes(d.get("size_bytes")), "sha256": (d["sha256"] or "")[:16],
        } for d in docs],
        hide_index=True, width="stretch",
    )
    labels = {f'{d["filename"]} ({d["sha256"][:8]})': d["id"] for d in docs}
    choice = st.selectbox("Select a document to manage", list(labels))
    doc_id = labels[choice]
    c1, c2 = st.columns(2)
    if c1.button("Reprocess this document"):
        doc = repo.get_document(doc_id)
        src = Path(doc["path"])
        if not src.exists():
            st.error(f"Original file not found at {src}")
        else:
            with st.spinner("Reprocessing…"):
                Pipeline(repository=repo).process(src, exam=doc.get("exam"), year=doc.get("year"))
            st.success("Reprocessed. Reload the page to see updated numbers.")
    if c2.button("Delete document", type="secondary"):
        repo.delete_document(doc_id)
        st.warning("Deleted from the bank (the uploaded original file is kept on disk).")
