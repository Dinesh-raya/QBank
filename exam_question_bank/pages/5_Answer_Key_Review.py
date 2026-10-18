"""Answer-Key Review — validate extracted answers and fix mappings."""
from __future__ import annotations

import streamlit as st

from question_bank.ui import bootstrap, get_repository, page_header

bootstrap()
st.set_page_config(page_title="Answer-Key Review", page_icon="✅", layout="wide")
page_header("✅ Answer-Key Review",
            "Validate extracted answers, spot unmatched entries and correct mappings. "
            "A missing answer stays missing until you supply it.")

repo = get_repository()
docs = repo.list_documents()
if not docs:
    st.info("Import a document first.")
    st.stop()

doc_labels = {f'{d["filename"]} ({d["sha256"][:8]})': d["id"] for d in docs}
doc_id = doc_labels[st.selectbox("Document", list(doc_labels))]

issues = repo.answer_key_issues(doc_id)
c = st.columns(5)
c[0].metric("Keys", issues["total_keys"])
c[1].metric("Questions", issues["total_questions"])
c[2].metric("Missing", len(issues["missing"]))
c[3].metric("Out of range", len(issues["out_of_range"]))
c[4].metric("Invalid option", len(issues["invalid_option"]))

if issues["missing"]:
    st.warning("Answers missing for question(s): " + ", ".join(map(str, issues["missing"])))
if issues["out_of_range"]:
    st.warning("Key entries with no matching question: " + ", ".join(map(str, issues["out_of_range"])))
if issues["duplicate"]:
    st.warning("Duplicate key entries: " + ", ".join(map(str, issues["duplicate"])))
if not any(issues[k] for k in ("missing", "out_of_range", "invalid_option", "duplicate")):
    st.success("No structural problems detected in the answer key.")

st.divider()
keys = repo.list_answer_keys(doc_id)
st.dataframe([{
    "#": k["question_number"], "option": k["option_index"], "value": k["answer_value"],
    "matched": k["match_status"], "review": k["review_status"],
    "method": k["extraction_method"], "page": k["page_number"],
    "raw": k["raw_text"],
} for k in keys], hide_index=True, width="stretch", height=360)

st.divider()
st.subheader("Manually set / correct an answer")
questions = repo.list_questions(document_id=doc_id, limit=2000)
qlabels = {f'Q{q["question_number"]}': q["id"] for q in questions if q["question_number"] is not None}
if not qlabels:
    st.info("No numbered questions available.")
else:
    with st.form("set_answer"):
        c1, c2 = st.columns(2)
        qlabel = c1.selectbox("Question", list(qlabels))
        qid = qlabels[qlabel]
        q = repo.get_question(qid)
        n_opts = max(len(q["options"]), 5)
        opt = c2.number_input("Correct option number", min_value=1, max_value=int(n_opts), value=1, step=1)
        if st.form_submit_button("Save answer"):
            repo.set_answer(doc_id, int(qlabel[1:]), qid, str(int(opt)), int(opt),
                            review_status="confirmed", answered_by="manual")
            st.success(f"Saved answer {int(opt)} for {qlabel} and marked the question verified.")
            st.rerun()
