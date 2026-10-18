"""Taxonomy Manager — maintain subjects, topics and subtopics."""
from __future__ import annotations

import streamlit as st

from question_bank.taxonomy import Taxonomy, TaxonomyError
from question_bank.ui import bootstrap, get_repository, get_taxonomy, page_header

bootstrap()
st.set_page_config(page_title="Taxonomy Manager", page_icon="🗂️", layout="wide")
page_header("🗂️ Taxonomy Manager",
            "Add, rename, deactivate or delete subjects, topics and subtopics. "
            "Invalid parent-child links are rejected.")

get_repository()
tax = get_taxonomy()

subjects = tax.subjects()
entries = tax.entries()

st.subheader("Current taxonomy")
for s in subjects:
    topics = tax.topics(s)
    with st.expander(f"**{s}** — {len(topics)} topic(s)", expanded=False):
        if not topics:
            st.caption("No topics yet.")
        for t in topics:
            subs = tax.subtopics(s, t)
            st.markdown(f"- **{t}**" + (f" — {', '.join(subs)}" if subs else ""))
    inactive = [e for e in entries if e.subject == s and not e.is_active]
    if inactive:
        st.caption(f"Inactive entries: {', '.join(e.path for e in inactive)}")

st.divider()
tab_add, tab_manage = st.tabs(["➕ Add", "🛠️ Manage"])

with tab_add:
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Add subject**")
        with st.form("add_subject"):
            name = st.text_input("Subject name")
            if st.form_submit_button("Add subject") and name.strip():
                tax.add_subject(name)
                st.success(f"Added subject: {name}")
                st.rerun()
    with c2:
        st.markdown("**Add topic**")
        with st.form("add_topic"):
            subj = st.selectbox("Under subject", subjects) if subjects else None
            topic = st.text_input("Topic name")
            if st.form_submit_button("Add topic") and subj and topic.strip():
                tax.add_topic(subj, topic)
                st.success(f"Added topic: {topic}")
                st.rerun()
    with c3:
        st.markdown("**Add subtopic**")
        with st.form("add_subtopic"):
            subj2 = st.selectbox("Subject", subjects, key="sub_subj") if subjects else None
            topics2 = tax.topics(subj2) if subj2 else []
            topic2 = st.selectbox("Topic", topics2, key="sub_topic") if topics2 else None
            subtopic = st.text_input("Subtopic name")
            if st.form_submit_button("Add subtopic") and subj2 and topic2 and subtopic.strip():
                tax.add_subtopic(subj2, topic2, subtopic)
                st.success(f"Added subtopic: {subtopic}")
                st.rerun()

with tab_manage:
    paths = [e.path for e in entries]
    if not paths:
        st.info("Taxonomy is empty.")
    else:
        path = st.selectbox("Entry path", paths)
        entry = next(e for e in entries if e.path == path)
        col1, col2, col3 = st.columns(3)
        with col1:
            with st.form("rename"):
                new_name = st.text_input("New name for this level", value=path.split(" > ")[-1])
                if st.form_submit_button("Rename") and new_name.strip():
                    try:
                        tax.rename(path, new_name)
                        st.success("Renamed (children update automatically).")
                        st.rerun()
                    except TaxonomyError as exc:
                        st.error(str(exc))
        with col2:
            st.markdown("**Active state**")
            st.write("Currently: " + ("active" if entry.is_active else "inactive"))
            toggle = st.button("Deactivate" if entry.is_active else "Activate")
            if toggle:
                tax.set_active(path, not entry.is_active)
                st.rerun()
        with col3:
            st.markdown("**Delete**")
            st.caption("Deletes this entry and its descendants.")
            if st.button("🗑️ Delete", type="secondary"):
                tax.delete(path)
                st.warning("Deleted.")
                st.rerun()
