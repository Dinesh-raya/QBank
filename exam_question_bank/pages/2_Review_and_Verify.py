"""Step 2: Review & Verify — Inspect questions, options, stimulus regions and answer keys."""
from __future__ import annotations

import streamlit as st

from question_bank import config
from question_bank.ui import (bootstrap, get_repository, get_taxonomy,
                              page_header, show_image)

bootstrap()
st.set_page_config(page_title="Review & Verify", page_icon="🔍", layout="wide")
page_header("🔍 Step 2: Review & Verify Extraction",
            "Verify extracted questions against the original document pages, adjust topic classifications, "
            "and confirm answer key mappings before publishing.")

repo = get_repository()
tax = get_taxonomy()

docs = repo.list_documents()
if not docs:
    st.info("No documents imported yet. Please upload a document on the **Import Documents** page first.")
    st.stop()

doc_labels = {f'{d["filename"]} ({d["sha256"][:8]})': d["id"] for d in docs}
doc_id = doc_labels[st.selectbox("Select Document", list(doc_labels))]

pages = repo.list_pages(doc_id)
questions = repo.list_questions(document_id=doc_id, limit=2000)

tab_editor, tab_page, tab_answers, tab_create = st.tabs([
    "✏️ Question Editor",
    "🖼️ Full Page Inspector",
    "✅ Answer Key Reconciliation",
    "➕ Create / Split / Merge",
])

# ---------------------------------------------------------------------------
# TAB 1: QUESTION EDITOR
# ---------------------------------------------------------------------------
with tab_editor:
    if not questions:
        st.info("No questions found for this document.")
    else:
        col_f1, col_f2 = st.columns([1, 2])
        filter_p = col_f1.selectbox("Filter by Page", ["All Pages"] + [p["page_number"] for p in pages], key="rev_page_filter")
        filtered_qs = questions if filter_p == "All Pages" else [q for q in questions if q.get("page_number") == filter_p]
        
        q_options = [f'Q{q["question_number"]} (id: {q["id"]}, p.{q.get("page_number")}) — {q.get("primary_topic") or "Unclassified"}' for q in filtered_qs]
        
        if not q_options:
            st.info(f"No questions on Page {filter_p}.")
        else:
            q_choice = col_f2.selectbox("Select Question to Inspect", q_options)
            chosen_q_id = filtered_qs[q_options.index(q_choice)]["id"]
            q = repo.get_question(chosen_q_id)
            
            left, right = st.columns([3, 2])
            with left:
                with st.form(f"edit_q_{q['id']}"):
                    st.caption(f"Question ID: `{q['id']}` · Document Page: {q.get('page_number')}")
                    
                    stem = st.text_area("Question Stem Text", q["stem_text"], height=140)
                    
                    # Editable Options
                    opts = q.get("options") or []
                    new_opts = []
                    st.markdown("**Answer Options:**")
                    for opt in opts:
                        val = st.text_input(f"Option {opt['option_index']}", opt["text"], key=f"opt_{opt['id']}")
                        new_opts.append({"id": opt["id"], "option_index": opt["option_index"], "text": val})
                    
                    # Classification
                    c_subj, c_top = st.columns(2)
                    subjects = tax.subjects()
                    cur_subj = q.get("subject") or (subjects[0] if subjects else "")
                    s_idx = subjects.index(cur_subj) if cur_subj in subjects else 0
                    chosen_subj = c_subj.selectbox("Subject", subjects, index=s_idx)
                    
                    avail_topics = tax.topics(chosen_subj) if chosen_subj else []
                    cur_top = q.get("primary_topic") or (avail_topics[0] if avail_topics else "")
                    t_idx = avail_topics.index(cur_top) if cur_top in avail_topics else 0
                    chosen_top = c_top.selectbox("Topic", avail_topics, index=t_idx)
                    
                    c_save, c_flag = st.columns(2)
                    save_clicked = c_save.form_submit_button("💾 Save Changes", type="primary")
                    flag_clicked = c_flag.form_submit_button("🚩 Toggle Needs Review")
                    
                    if save_clicked:
                        repo.update_question(q["id"], stem_text=stem, subject=chosen_subj,
                                             primary_topic=chosen_top, review_status="human_verified")
                        for o in new_opts:
                            repo.update_option(o["id"], text=o["text"])
                        st.success("Changes saved successfully!")
                        st.rerun()
                    if flag_clicked:
                        new_st = "human_verified" if q["review_status"] == "needs_review" else "needs_review"
                        repo.update_question(q["id"], review_status=new_st)
                        st.rerun()

            with right:
                st.subheader("Source Document Verification")
                page_info = repo.get_page(doc_id, q.get("page_number", 1))
                if page_info and page_info.get("render_path"):
                    show_image(page_info["render_path"], caption=f"Page {q.get('page_number')}")
                
                # Check for shared stimulus / puzzle
                if q.get("context_id"):
                    ctx = repo.get_context(q["context_id"])
                    if ctx:
                        st.markdown(f"**Linked Stimulus ({ctx.get('label') or 'Shared Context'}):**")
                        if ctx.get("asset_path"):
                            show_image(ctx["asset_path"], caption="Extracted Stimulus Crop")
                        if ctx.get("text"):
                            st.caption(ctx["text"][:300] + "…")

# ---------------------------------------------------------------------------
# TAB 2: FULL PAGE INSPECTOR
# ---------------------------------------------------------------------------
with tab_page:
    c_p1, c_p2 = st.columns([3, 2])
    sel_page_no = c_p1.selectbox("Select Page to View", [p["page_number"] for p in pages], key="full_page_sel")
    page_data = repo.get_page(doc_id, sel_page_no)
    
    with c_p1:
        if page_data and page_data.get("render_path"):
            show_image(page_data["render_path"], caption=f"Original Document Page {sel_page_no}")
    
    with c_p2:
        st.write(f"**Layout Type:** {page_data.get('page_type', 'standard')}")
        st.write(f"**Character Count:** {page_data.get('text_char_count', 0)}")
        if page_data.get("quality_flags"):
            st.warning("Quality Flags: " + page_data["quality_flags"])
            
        p_qs = [q for q in questions if q.get("page_number") == sel_page_no]
        st.markdown(f"**Questions on this page ({len(p_qs)}):**")
        for pq in p_qs:
            st.markdown(f"- **Q{pq.get('question_number')}:** {(pq.get('stem_text') or '')[:70]}…")
        
        with st.expander("Show Raw Extracted OCR/Coordinate Text"):
            st.text_area("Page Text", page_data.get("raw_text") or "", height=220, disabled=True)

# ---------------------------------------------------------------------------
# TAB 3: ANSWER KEY RECONCILIATION
# ---------------------------------------------------------------------------
with tab_answers:
    issues = repo.answer_key_issues(doc_id)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Answer Keys Found", issues["total_keys"])
    m2.metric("Questions Count", issues["total_questions"])
    m3.metric("Missing Keys", len(issues["missing"]))
    m4.metric("Key Issues", len(issues["out_of_range"]) + len(issues["invalid_option"]))
    
    if issues["missing"]:
        st.warning(f"⚠️ Missing answers for Question(s): {', '.join(map(str, issues['missing']))}")
    else:
        st.success("✅ All questions have a matched answer key!")
        
    keys = repo.list_answer_keys(doc_id)
    st.dataframe([{
        "Question #": k["question_number"], "Option Key": k["option_index"],
        "Value": k["answer_value"], "Status": k["match_status"],
        "Method": k["extraction_method"], "Page": k["page_number"]
    } for k in keys], hide_index=True, width="stretch", height=320)
    
    st.subheader("Manual Answer Override")
    with st.form("manual_ans_form"):
        col_q, col_opt = st.columns(2)
        ans_qlabels = {f'Q{q["question_number"]}': q["id"] for q in questions if q.get("question_number") is not None}
        if ans_qlabels:
            selected_ql = col_q.selectbox("Question", list(ans_qlabels))
            selected_qid = ans_qlabels[selected_ql]
            opt_input = col_opt.number_input("Correct Option (e.g. 1, 2, 3, 4, 5)", min_value=1, max_value=5, value=1, step=1)
            if st.form_submit_button("Set / Confirm Answer Key"):
                q_num = int(selected_ql.replace("Q", ""))
                repo.set_answer(doc_id, q_num, selected_qid, str(int(opt_input)), int(opt_input),
                                review_status="confirmed", answered_by="manual")
                st.success(f"Confirmed Answer Option {int(opt_input)} for {selected_ql}!")
                st.rerun()

# ---------------------------------------------------------------------------
# TAB 4: CREATE / SPLIT / MERGE
# ---------------------------------------------------------------------------
with tab_create:
    st.subheader("Split or Merge Questions")
    st.caption("Use these operations if multi-part questions were combined or separated during raw parsing.")
    
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        st.markdown("**Merge Questions**")
        with st.form("merge_form"):
            q_nums = [q.get("question_number") for q in questions if q.get("question_number") is not None]
            target_q = st.selectbox("Target Question (Kept)", q_nums, key="merge_target") if q_nums else None
            source_q = st.selectbox("Source Question (Appended into Target)", q_nums, key="merge_src") if q_nums else None
            if st.form_submit_button("Merge Source into Target") and target_q and source_q:
                if target_q == source_q:
                    st.error("Cannot merge a question with itself.")
                else:
                    t_id = next(q["id"] for q in questions if q.get("question_number") == target_q)
                    s_id = next(q["id"] for q in questions if q.get("question_number") == source_q)
                    repo.merge_questions(t_id, s_id)
                    st.success(f"Merged Q{source_q} into Q{target_q}.")
                    st.rerun()
