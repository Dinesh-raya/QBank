"""Step 4: Settings & Taxonomy — Topic taxonomy manager and system diagnostics."""
from __future__ import annotations

import streamlit as st

from question_bank import config
from question_bank.taxonomy import TaxonomyError
from question_bank.ui import (ai_status_line, bootstrap, get_repository,
                              get_taxonomy, human_bytes, ocr_status_line,
                              page_header)

bootstrap()
st.set_page_config(page_title="Settings & Taxonomy", page_icon="⚙️", layout="wide")
page_header("⚙️ Step 4: Settings & Topic Taxonomy",
            "Maintain the hierarchical classification taxonomy and review local system paths and OCR engine configuration.")

repo = get_repository()
tax = get_taxonomy()

tab_tax, tab_settings = st.tabs(["🗂️ Topic Taxonomy Manager", "🔧 System & OCR Settings"])

# ---------------------------------------------------------------------------
# TAB 1: TAXONOMY MANAGER
# ---------------------------------------------------------------------------
with tab_tax:
    subjects = tax.subjects()
    entries = tax.entries()
    
    st.subheader("Current Topic Hierarchy")
    for s in subjects:
        topics = tax.topics(s)
        with st.expander(f"📚 **{s}** — {len(topics)} topic(s)", expanded=False):
            if not topics:
                st.caption("No topics defined under this subject yet.")
            for t in topics:
                subs = tax.subtopics(s, t)
                st.markdown(f"- **{t}**" + (f" *({', '.join(subs)})*" if subs else ""))
                
    st.divider()
    sub_c1, sub_c2, sub_c3 = st.columns(3)
    with sub_c1:
        st.markdown("**Add Subject**")
        with st.form("add_subject_form"):
            s_name = st.text_input("New Subject Name")
            if st.form_submit_button("Add Subject") and s_name.strip():
                tax.add_subject(s_name.strip())
                st.success(f"Added Subject: {s_name}")
                st.rerun()
                
    with sub_c2:
        st.markdown("**Add Topic**")
        with st.form("add_topic_form"):
            subj_parent = st.selectbox("Under Subject", subjects) if subjects else None
            t_name = st.text_input("New Topic Name")
            if st.form_submit_button("Add Topic") and subj_parent and t_name.strip():
                tax.add_topic(subj_parent, t_name.strip())
                st.success(f"Added Topic: {t_name}")
                st.rerun()
                
    with sub_c3:
        st.markdown("**Add Subtopic**")
        with st.form("add_subtopic_form"):
            subj_p2 = st.selectbox("Under Subject", subjects, key="subtopic_subj") if subjects else None
            top_p2 = tax.topics(subj_p2) if subj_p2 else []
            chosen_top = st.selectbox("Under Topic", top_p2) if top_p2 else None
            sub_name = st.text_input("New Subtopic Name")
            if st.form_submit_button("Add Subtopic") and subj_p2 and chosen_top and sub_name.strip():
                tax.add_subtopic(subj_p2, chosen_top, sub_name.strip())
                st.success(f"Added Subtopic: {sub_name}")
                st.rerun()

# ---------------------------------------------------------------------------
# TAB 2: SYSTEM SETTINGS & DIAGNOSTICS
# ---------------------------------------------------------------------------
with tab_settings:
    st.subheader("Local Storage & Database State")
    c_d1, c_d2 = st.columns(2)
    c_d1.metric("Database Schema Version", repo.db.schema_version())
    db_sz = config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0
    c_d2.metric("SQLite Database Size", human_bytes(db_sz))
    
    st.dataframe([
        {"Directory": "Project Root", "Path": str(config.PROJECT_ROOT)},
        {"Directory": "SQLite Database", "Path": str(config.DB_PATH)},
        {"Directory": "Uploads Directory", "Path": str(config.UPLOADS_DIR)},
        {"Directory": "Rendered Pages", "Path": str(config.RENDERS_DIR)},
        {"Directory": "Asset Crops (Math/Graphs)", "Path": str(config.ASSETS_DIR)},
        {"Directory": "Encrypted Web App", "Path": str(config.PROJECT_ROOT.parent / "web_app")},
    ], hide_index=True, width="stretch")
    
    st.divider()
    st.subheader("OCR Engine Diagnostics")
    st.write(f"**Tesseract OCR:** {ocr_status_line()}")
    st.caption(f"Render DPI: {config.LAYOUT.render_dpi}. Auto-detected from system or configurable via `QB_TESSERACT_CMD`.")
    
    st.divider()
    st.subheader("Extraction Tuning Parameters")
    st.json({
        "watermark_min_font_size": config.LAYOUT.watermark_min_font_size,
        "header_band_fraction": config.LAYOUT.header_band_fraction,
        "footer_band_fraction": config.LAYOUT.footer_band_fraction,
        "min_text_chars_for_digital": config.LAYOUT.min_text_chars_for_digital,
    })
