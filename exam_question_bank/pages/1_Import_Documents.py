"""Step 1: Import Documents — Upload exam papers and run the extraction pipeline."""
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
page_header("📥 Step 1: Import & Digitize Documents",
            "Upload competitive exam papers (digital PDFs or scanned documents). The extraction pipeline "
            "coordinates text layout, crops stimulus graphics, decodes math symbols, and extracts answer keys.")

repo = get_repository()

with st.form("import_form"):
    files = st.file_uploader(
        "Choose one or more exam paper files",
        type=sorted(e.lstrip(".") for e in SUPPORTED_EXTS),
        accept_multiple_files=True,
        help="Upload digital PDFs, scanned PDFs, or exam page images (PNG/JPG)."
    )
    c1, c2 = st.columns(2)
    exam = c1.text_input("Exam Name (e.g. IBPS RRB Clerk, SBI PO)", value=config.DEFAULT_EXAM)
    year = c2.text_input("Exam Year (optional)", value="")
    
    with st.expander("🛠️ Advanced Extraction Settings", expanded=False):
        use_ai = st.checkbox(
            "Use optional local AI classifier for ambiguous questions",
            value=False,
            help="Uses a local Ollama or OpenAI-compatible endpoint if configured in Settings."
        )

    submitted = st.form_submit_button("⚡ Process & Extract Questions", type="primary")

if submitted:
    if not files:
        st.warning("Please choose at least one file to process.")
    else:
        year_val = int(year) if str(year).strip().isdigit() else None
        pipeline = Pipeline(repository=repo, use_ai=use_ai)
        results = []
        progress = st.progress(0.0, text="Starting pipeline…")
        
        for i, uploaded in enumerate(files):
            progress.progress(i / len(files), text=f"Digitizing {uploaded.name}…")
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
            except Exception as exc:
                results.append((uploaded.name, None, str(exc)))
        
        progress.empty()
        st.session_state["import_results"] = results
        st.success(f"🎉 Successfully processed {len(files)} file(s)!")

results = st.session_state.get("import_results")
if results:
    st.subheader("Extraction Summary")
    for name, res, err in results:
        if err:
            st.error(f"**{name}** — Processing failed: {err}")
            continue
        with st.expander(f"✅ {name} — {res.stats.get('questions', 0)} questions extracted across {res.stats.get('pages', 0)} pages", expanded=True):
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Questions", res.stats.get("questions", 0))
            s2.metric("Options", res.stats.get("options", 0))
            s3.metric("Stimulus / Puzzles", res.stats.get("contexts", 0))
            s4.metric("Answer Keys", res.stats.get("answer_keys", 0))
            if res.warnings:
                st.warning("Warnings: " + "; ".join(res.warnings))
            st.caption(f"Document ID: `{res.document_id}`")
            
    st.info("👉 Next Step: Proceed to **Step 2: Review & Verify** to inspect extracted questions and confirm answer keys.")

st.divider()
st.subheader("Imported Documents Inventory")
docs = repo.list_documents()
if not docs:
    st.info("No documents imported yet. Upload your first exam paper above!")
else:
    st.dataframe(
        [{
            "Document": d["filename"], "Exam": d.get("exam") or "", "Year": d.get("year") or "",
            "Pages": d["page_count"], "Questions": d["question_count"],
            "File Size": human_bytes(d.get("size_bytes")), "SHA-256": (d["sha256"] or "")[:12],
        } for d in docs],
        hide_index=True, width="stretch",
    )
    labels = {f'{d["filename"]} ({d["sha256"][:8]})': d["id"] for d in docs}
    choice = st.selectbox("Select document to manage", list(labels))
    doc_id = labels[choice]
    c1, c2 = st.columns(2)
    if c1.button("🔄 Reprocess this document"):
        doc = repo.get_document(doc_id)
        src = Path(doc["path"])
        if not src.exists():
            st.error(f"Original file not found at {src}")
        else:
            with st.spinner("Reprocessing pipeline…"):
                Pipeline(repository=repo).process(src, exam=doc.get("exam"), year=doc.get("year"))
            st.success("Reprocessed successfully. Refresh page to see updated numbers.")
    if c2.button("🗑️ Delete document from bank", type="secondary"):
        repo.delete_document(doc_id)
        st.warning("Document deleted from the database.")
        st.rerun()
