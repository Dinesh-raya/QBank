"""Exam Paper Digitizer & Question Bank — Streamlit entry point.

Run with:  streamlit run app.py

The heavy lifting lives in the ``question_bank`` package so every processing
stage is testable without Streamlit. This app is a thin, local-only UI over the
SQLite question bank: import papers, review the extraction, correct it, classify
it, validate answer keys, search, export and back up.
"""
from __future__ import annotations

import streamlit as st

from question_bank import config
from question_bank.ui import (ai_status_line, bootstrap, get_repository,
                              human_bytes, ocr_status_line, page_header)

bootstrap()

st.set_page_config(page_title="Exam Question Bank", page_icon="📚", layout="wide")

page_header("📚 Exam Paper Digitizer & Question Bank",
            "Local-only extraction, review, classification and storage for exam papers.")

repo = get_repository()
metrics = repo.dashboard_metrics()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Documents", metrics["documents"])
c2.metric("Questions", metrics["questions"])
c3.metric("Needs review", metrics["needs_review"])
c4.metric("Missing answers", metrics["missing_answer"])

st.divider()

left, right = st.columns([3, 2])
with left:
    st.subheader("Get started")
    st.markdown(
        "Use the sidebar to navigate:\n\n"
        "1. **Import Documents** — upload one or more PDFs/image papers and process them.\n"
        "2. **Review Extraction** — compare the source page with the extracted text, "
        "edit questions/options, split/merge, link context.\n"
        "3. **Question Bank** — search and filter every stored question.\n"
        "4. **Answer-Key Review** — validate and correct answer mappings.\n"
        "5. **Taxonomy Manager** — maintain subjects, topics and subtopics.\n"
        "6. **Export & Backup** — JSON/CSV export and full ZIP backup/restore."
    )
    if metrics["documents"] == 0:
        st.info("No documents yet. Start on the **Import Documents** page.")

with right:
    st.subheader("Environment")
    st.write(f"**Database:** `{config.DB_PATH}`")
    st.write(f"**Database size:** {human_bytes(config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0)}")
    st.write(f"**OCR:** {ocr_status_line()}")
    st.write(f"**Classifier:** {ai_status_line()}")

st.divider()
st.caption(
    "Private by default: everything stays on this machine. No document content is "
    "sent anywhere unless the optional local model is explicitly enabled."
)
