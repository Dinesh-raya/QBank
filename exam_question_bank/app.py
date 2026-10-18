"""Exam Paper Digitizer Studio — Control Center & Pipeline Overview.

Run with:  streamlit run app.py

A focused ingestion and digitizing studio for exam papers:
1. Ingest PDF papers (coordinate-driven extraction + OCR fallback).
2. Review & verify extracted questions, options, passages & answer keys.
3. 1-Click publish the encrypted vault directly to GitHub Pages.
"""
from __future__ import annotations

import streamlit as st

from question_bank import config
from question_bank.ui import (ai_status_line, bootstrap, get_repository,
                              human_bytes, ocr_status_line, page_header)

bootstrap()

st.set_page_config(page_title="QBank Studio", page_icon="⚡", layout="wide")

page_header("⚡ QBank Ingestion Studio",
            "High-precision exam paper extraction, review, and 1-click publishing to your live encrypted web app.")

repo = get_repository()
metrics = repo.dashboard_metrics()

# Live Portal Banner
st.markdown(
    """
    <div style="background: linear-gradient(135deg, rgba(99, 102, 241, 0.15), rgba(168, 85, 247, 0.15));
                border: 1px solid rgba(139, 92, 246, 0.35); border-radius: 12px; padding: 18px 24px; margin-bottom: 24px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
            <div>
                <h4 style="margin: 0 0 6px 0; color: #a5b4fc; font-weight: 700; font-size: 1.15rem;">
                    🌐 Live Web App Status: Active & Secured
                </h4>
                <p style="margin: 0; color: #cbd5e1; font-size: 0.92rem;">
                    Students and readers view, practice, and search questions securely on GitHub Pages with zero cloud dependencies.
                </p>
            </div>
            <div>
                <a href="https://dinesh-raya.github.io/QBank/" target="_blank"
                   style="display: inline-block; background: #6366f1; color: #ffffff; text-decoration: none;
                          padding: 10px 20px; border-radius: 8px; font-weight: 600; font-size: 0.9rem;
                          box-shadow: 0 4px 14px rgba(99, 102, 241, 0.4);">
                    Open Live App ↗
                </a>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Key Metrics
c1, c2, c3, c4 = st.columns(4)
c1.metric("Documents Ingested", metrics["documents"])
c2.metric("Total Questions", metrics["questions"])
c3.metric("Review Flags", metrics["needs_review"])
c4.metric("Unmatched Keys", metrics["missing_answer"])

st.divider()

# Studio Workflow Cards
st.subheader("🛠️ The 3-Step Ingestion Workflow")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(
        """
        <div style="border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; padding: 20px; min-height: 220px; background: rgba(30, 41, 59, 0.4);">
            <div style="font-size: 1.8rem; margin-bottom: 10px;">📄</div>
            <h4 style="margin: 0 0 8px 0; color: #f8fafc;">Step 1: Ingest & Digitize</h4>
            <p style="color: #94a3b8; font-size: 0.9rem; margin-bottom: 16px;">
                Upload exam PDFs or scans. The pipeline auto-detects columns, strips watermarks, decodes symbol math fonts, and crops puzzles.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Go to Import ➔", key="btn_import", use_container_width=True):
        st.switch_page("pages/1_Import_Documents.py")

with col2:
    st.markdown(
        """
        <div style="border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; padding: 20px; min-height: 220px; background: rgba(30, 41, 59, 0.4);">
            <div style="font-size: 1.8rem; margin-bottom: 10px;">🔍</div>
            <h4 style="margin: 0 0 8px 0; color: #f8fafc;">Step 2: Review & Verify</h4>
            <p style="color: #94a3b8; font-size: 0.9rem; margin-bottom: 16px;">
                Inspect extracted text alongside the original PDF page. Edit any text, verify answer keys, and check topic classifications.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Go to Review ➔", key="btn_review", use_container_width=True):
        st.switch_page("pages/2_Review_and_Verify.py")

with col3:
    st.markdown(
        """
        <div style="border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; padding: 20px; min-height: 220px; background: rgba(30, 41, 59, 0.4);">
            <div style="font-size: 1.8rem; margin-bottom: 10px;">🚀</div>
            <h4 style="margin: 0 0 8px 0; color: #f8fafc;">Step 3: Publish & Sync</h4>
            <p style="color: #94a3b8; font-size: 0.9rem; margin-bottom: 16px;">
                One-click encryption (AES-256-GCM) and automatic sync to GitHub Pages so updates are immediately live for readers.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Go to Publish ➔", key="btn_publish", use_container_width=True):
        st.switch_page("pages/3_Publish_to_Web_App.py")

st.divider()

# System & Environment Info
with st.expander("⚙️ System Diagnostics & Offline Environment", expanded=False):
    s1, s2 = st.columns(2)
    with s1:
        st.write(f"**Database Location:** `{config.DB_PATH}`")
        db_sz = config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0
        st.write(f"**Database Size:** {human_bytes(db_sz)}")
    with s2:
        st.write(f"**OCR Engine:** {ocr_status_line()}")
        st.write(f"**Classifier Status:** {ai_status_line()}")
