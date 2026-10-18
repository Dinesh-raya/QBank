"""Review Extraction — compare source page with extracted content and fix it."""
from __future__ import annotations

import streamlit as st

from question_bank import config
from question_bank.ui import bootstrap, get_repository, get_taxonomy, page_header, show_image

bootstrap()
st.set_page_config(page_title="Review Extraction", page_icon="🔍", layout="wide")
page_header("🔍 Review Extraction",
            "Compare the original page with what was extracted, then correct it. "
            "Every edit is recorded in the review history.")

repo = get_repository()
tax = get_taxonomy()

docs = repo.list_documents()
if not docs:
    st.info("Import a document first.")
    st.stop()

doc_labels = {f'{d["filename"]} ({d["sha256"][:8]})': d["id"] for d in docs}
doc_id = doc_labels[st.selectbox("Document", list(doc_labels))]

pages = repo.list_pages(doc_id)
questions = repo.list_questions(document_id=doc_id, limit=2000)

page_tab, editor_tab, manage_tab = st.tabs(["🖼️ Page view", "✏️ Question editor", "➕ Create / manage"])

# ---------------------------------------------------------------------------
with page_tab:
    c1, c2 = st.columns([3, 2])
    page_no = c1.selectbox("Page", [p["page_number"] for p in pages])
    page = repo.get_page(doc_id, page_no)
    with c1:
        if page:
            show_image(page.get("render_path"), caption=f"Page {page_no}")
    with c2:
        st.write(f"**Type:** {page.get('page_type')}  |  **Chars:** {page.get('text_char_count')}  |  "
                 f"**Images:** {page.get('image_count')}")
        if page.get("quality_flags"):
            st.warning("Flags: " + page["quality_flags"])
        st.text_area("Raw extracted text (immutable)", page.get("raw_text") or "",
                     height=240, disabled=True)
        
        # Show questions detected on this page
        page_qs = [q for q in questions if q.get("page_number") == page_no]
        with st.expander(f"📋 Questions on Page {page_no} ({len(page_qs)} detected)", expanded=True):
            for pq in page_qs:
                st.markdown(f"**Q{pq.get('question_number')}:** {(pq.get('stem_text') or '')[:70]}...")

# ---------------------------------------------------------------------------
with editor_tab:
    if not questions:
        st.info("No questions extracted for this document.")
    else:
        col_f1, col_f2 = st.columns([1, 2])
        filter_p = col_f1.selectbox("Page Filter", ["All Pages"] + [p["page_number"] for p in pages], key="ed_page_sel")
        filtered_qs = questions if filter_p == "All Pages" else [q for q in questions if q.get("page_number") == filter_p]
        
        if not filtered_qs:
            st.info(f"No questions on page {filter_p}.")
            st.stop()

        qlabels = {f'Q{q["question_number"] if q["question_number"] is not None else "?"} '
                   f'(p{q["page_number"]}) — {(q["stem_text"] or "")[:55]}': q["id"] for q in filtered_qs}
        qid = qlabels[col_f2.selectbox("Select Question to Edit", list(qlabels))]
        q = repo.get_question(qid)
        contexts = repo.list_contexts(doc_id)

        left, right = st.columns([2, 3])
        with left:
            show_image(repo.get_page(doc_id, q["page_number"]).get("render_path") if q["page_number"] else None,
                       caption=f"Source page {q['page_number']}")
            if q.get("asset_path"):
                show_image(q["asset_path"], caption="Question / formula crop")
            if q.get("math"):
                st.caption("Math reconstruction (heuristic — verify against the crop):")
                st.code(q["math"].get("linear") or "", language=None)
                st.json({k: v for k, v in q["math"].items() if k != "linear"})
            st.text_area("Raw text (immutable)", q.get("raw_text") or "", height=120, disabled=True)

        with right:
            with st.form(f"edit_{qid}"):
                st.markdown(f"#### Q{q['question_number']} — page {q['page_number']}")
                num = st.number_input("Question number", value=int(q["question_number"] or 0), step=1)
                text = st.text_area("Question text (corrected)", value=q["text"] or "", height=120)
                st.write("**Options**")
                opt_values = []
                for o in q["options"]:
                    opt_values.append((o["id"], st.text_input(
                        f"Option {o['option_label'] or o['option_index']}",
                        value=o["text"] or "", key=f"opt_{qid}_{o['id']}")))
                status = st.selectbox(
                    "Review status", ["draft", "needs_review", "confirmed", "excluded"],
                    index=["draft", "needs_review", "confirmed", "excluded"].index(
                        q["review_status"] if q["review_status"] in
                        ("draft", "needs_review", "confirmed", "excluded") else "draft"))
                ctx_labels = {"— none —": None}
                ctx_labels.update({f'{c["label"]} [{c["context_type"]}]': c["id"] for c in contexts})
                current_ctx = next((k for k, v in ctx_labels.items() if v == q["context_id"]), "— none —")
                ctx_pick = st.selectbox("Shared context", list(ctx_labels), index=list(ctx_labels).index(current_ctx))
                saved = st.form_submit_button("💾 Save changes", type="primary")

            if saved:
                repo.update_question(qid, text=text, question_number=int(num),
                                     review_status=None if status == "excluded" else status,
                                     is_excluded=(status == "excluded"))
                for oid, val in opt_values:
                    repo.update_option(oid, val)
                repo.link_context(qid, ctx_labels[ctx_pick])
                st.success("Saved.")
                st.rerun()

            # Classification (dynamically reactive: changing Subject immediately updates Topic list)
            st.markdown("##### 🏷️ Topic Classification")
            prim = (q["classifications"][0] if q["classifications"] else None)
            subjects = tax.subjects()
            cur_subject = prim["subject"] if prim and prim["subject"] in subjects else subjects[0]

            s = st.selectbox("Subject", subjects, index=subjects.index(cur_subject), key=f"sel_s_{qid}")
            topics = tax.topics(s) or ["Unclassified"]
            cur_topic = prim["topic"] if prim and prim["topic"] in topics else topics[0]
            t_idx = topics.index(cur_topic) if cur_topic in topics else 0
            t = st.selectbox("Topic", topics, index=t_idx, key=f"sel_t_{qid}")

            subtopics = ["—"] + tax.subtopics(s, t)
            cur_sub = prim["subtopic"] if prim and prim["subtopic"] in subtopics else "—"
            sub_idx = subtopics.index(cur_sub) if cur_sub in subtopics else 0
            sub = st.selectbox("Subtopic", subtopics, index=sub_idx, key=f"sel_sub_{qid}")

            if st.button("💾 Update Classification", key=f"btn_save_cls_{qid}", type="secondary"):
                repo.set_classification(qid, s, t, None if sub == "—" else sub)
                st.success(f"Classification updated to {s} › {t}")
                st.rerun()

            if prim:
                st.caption(f"Current: **{prim['subject']} › {prim['topic']}** "
                           f"(method: `{prim['method']}`, status: `{prim['review_status']}`)")
            if q["tags"]:
                st.caption("Tags: " + ", ".join(q["tags"]))

        st.divider()
        st.markdown("##### History")
        history = repo.review_history(entity_type="question", entity_id=qid, limit=50)
        if history:
            st.dataframe([{k: h[k] for k in ("action", "old_value", "new_value", "created_at")}
                          for h in history], hide_index=True, width="stretch")
        else:
            st.caption("No edits recorded yet.")

        danger = st.columns(3)
        if danger[0].button("🚫 Exclude question"):
            repo.exclude_question(qid)
            st.warning("Excluded (kept in the DB for traceability).")
            st.rerun()
        if danger[1].button("🗑️ Delete question"):
            repo.delete_question(qid)
            st.warning("Deleted.")
            st.rerun()
        prev = [x for x in questions if x["order_index"] < q["order_index"]]
        if prev and danger[2].button("🔗 Merge into previous"):
            repo.merge_questions(qid, prev[-1]["id"])
            st.success("Merged into previous question.")
            st.rerun()

# ---------------------------------------------------------------------------
with manage_tab:
    st.subheader("Create a question manually")
    with st.form("create_manual"):
        c1, c2 = st.columns(2)
        m_num = c1.number_input("Question number", value=0, step=1)
        m_page = c2.number_input("Page number", value=1, step=1)
        m_text = st.text_area("Question text", height=100)
        m_opts = st.text_area("Options (one per line)", height=100)
        if st.form_submit_button("Create"):
            opts = [ln.strip() for ln in (m_opts or "").splitlines() if ln.strip()]
            repo.create_manual_question(
                doc_id, text=m_text, question_number=int(m_num) or None,
                page_number=int(m_page), options=opts)
            st.success("Question created.")
            st.rerun()

    st.divider()
    st.subheader("Split a combined record")
    if questions:
        slabels = {f'Q{q["question_number"]} — {(q["text"] or "")[:50]}': q["id"] for q in questions}
        sqid = slabels[st.selectbox("Record to split", list(slabels), key="split_sel")]
        sq = repo.get_question(sqid)
        with st.form("split_form"):
            a = st.text_area("First question text (kept)", value=sq["text"] or "", height=100)
            b = st.text_area("Second question text (new record)", height=100)
            if st.form_submit_button("Split"):
                if b.strip():
                    repo.split_question(sqid, a, b, second_number=None)
                    st.success("Split into two records (the new one is flagged for review).")
                    st.rerun()
                else:
                    st.error("Provide text for the second question.")
