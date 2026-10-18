"""Dashboard — genuine metrics from the database."""
from __future__ import annotations

import streamlit as st

from question_bank.ui import bootstrap, get_repository, human_bytes, page_header

bootstrap()
st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
page_header("📊 Dashboard", "Live metrics straight from the question-bank database.")

repo = get_repository()
m = repo.dashboard_metrics()

if m["documents"] == 0:
    st.info("No data yet. Import a document from the **Import Documents** page.")
    st.stop()

row1 = st.columns(4)
row1[0].metric("Documents", m["documents"])
row1[1].metric("Pages", m["pages"])
row1[2].metric("Questions", m["questions"])
row1[3].metric("Contexts", m["contexts"])

row2 = st.columns(4)
row2[0].metric("Needs review", m["needs_review"])
row2[1].metric("Confirmed", m["confirmed"])
row2[2].metric("Excluded", m["excluded"])
row2[3].metric("Duplicate candidates", m["duplicate_candidates"])

row3 = st.columns(4)
row3[0].metric("Answer keys", m["answer_keys"])
row3[1].metric("Answers verified", m["answers_verified"])
row3[2].metric("Missing answers", m["missing_answer"])
row3[3].metric("Math questions", m["math_questions"])

st.divider()
left, right = st.columns(2)

with left:
    st.subheader("Classification breakdown by subject")
    if m["by_subject"]:
        st.bar_chart({r["subject"]: r["n"] for r in m["by_subject"]})
        st.dataframe(m["by_subject"], hide_index=True, width="stretch")

with right:
    st.subheader("Review status")
    if m["by_review_status"]:
        st.dataframe(m["by_review_status"], hide_index=True, width="stretch")

st.divider()
st.subheader("Documents")
docs = repo.list_documents()
if docs:
    st.dataframe(
        [{
            "file": d["filename"],
            "exam": d.get("exam") or "",
            "year": d.get("year") or "",
            "pages": d["page_count"],
            "questions": d["question_count"],
            "size": human_bytes(d.get("size_bytes")),
            "sha256": (d["sha256"] or "")[:12],
            "imported": d.get("created_at"),
        } for d in docs],
        hide_index=True, width="stretch",
    )
