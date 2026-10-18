"""Question Bank — interactive practice, card feed, and searchable database."""
from __future__ import annotations

import streamlit as st

from question_bank.ui import (bootstrap, get_repository, get_taxonomy,
                              linear_to_latex, page_header, render_chip,
                              render_question_display, show_image)

bootstrap()
st.set_page_config(page_title="Question Bank", page_icon="📚", layout="wide")
page_header("📚 Question Bank", "Interactive exam practice, card feed, and multi-filter question search.")

repo = get_repository()
tax = get_taxonomy()
opts = repo.filter_options()

# ---------------------------------------------------------------------------
# Filter bar
# ---------------------------------------------------------------------------
with st.expander("🔍 Filter & Search Questions", expanded=False):
    c1, c2, c3 = st.columns(3)
    search = c1.text_input("Search keywords", "", placeholder="e.g. river, ratio, discount...")
    subject = c2.selectbox("Subject", ["All Subjects"] + tax.subjects())
    subj_val = None if subject == "All Subjects" else subject
    topic = c3.selectbox("Topic", ["All Topics"] + (tax.topics(subj_val) if subj_val else []))
    top_val = None if topic == "All Topics" else topic

    c4, c5, c6 = st.columns(3)
    doc_labels = {"All Documents": None}
    doc_labels.update({f'{d["filename"]} ({d["sha256"][:8]})': d["id"] for d in opts["documents"]})
    doc_choice = c4.selectbox("Source Document", list(doc_labels))
    doc_id = doc_labels[doc_choice]
    exam = c5.selectbox("Exam", ["All Exams"] + [e for e in opts["exams"] if e])
    review_status = c6.selectbox("Review Status", ["All", "draft", "needs_review", "confirmed", "excluded"])

kwargs = dict(
    document_id=doc_id,
    search=search or None,
    subject=subj_val,
    topic=top_val,
    exam=None if exam == "All Exams" else exam,
    review_status=None if review_status == "All" else review_status,
)

total = repo.count_questions(**kwargs)
rows = repo.list_questions(limit=1000, **kwargs)

if not rows:
    st.info("No questions match the current filters. Try resetting the filters above.")
    st.stop()

# ---------------------------------------------------------------------------
# View Mode Selection
# ---------------------------------------------------------------------------
st.markdown(
    f"<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;'>"
    f"<span style='font-weight:600; font-size:1rem; color:#94a3b8;'>Showing {len(rows)} of {total} question(s)</span>"
    f"</div>",
    unsafe_allow_html=True,
)

tab_practice, tab_cards, tab_table = st.tabs([
    "🎯 Interactive Practice Mode",
    "📑 Card Feed Mode",
    "📊 Table Explorer",
])

# ===========================================================================
# TAB 1: INTERACTIVE PRACTICE MODE
# ===========================================================================
with tab_practice:
    # State management for current index
    if "practice_idx" not in st.session_state:
        st.session_state["practice_idx"] = 0
    
    # Boundary check if filter changed
    if st.session_state["practice_idx"] >= len(rows):
        st.session_state["practice_idx"] = 0

    curr_idx = st.session_state["practice_idx"]
    q_summary = rows[curr_idx]
    q = repo.get_question(q_summary["id"])

    # Navigation Controls
    col_nav1, col_nav2, col_nav3 = st.columns([1, 3, 1])
    with col_nav1:
        if st.button("⬅ Previous", disabled=(curr_idx == 0), key="btn_prev", use_container_width=True):
            st.session_state["practice_idx"] = max(0, curr_idx - 1)
            st.rerun()
    with col_nav2:
        new_qnum = st.slider(
            "Jump to Question",
            min_value=1,
            max_value=len(rows),
            value=curr_idx + 1,
            format="Question %d",
            label_visibility="collapsed",
        )
        if new_qnum - 1 != curr_idx:
            st.session_state["practice_idx"] = new_qnum - 1
            st.rerun()
    with col_nav3:
        if st.button("Next ➡", disabled=(curr_idx >= len(rows) - 1), key="btn_next", use_container_width=True):
            st.session_state["practice_idx"] = min(len(rows) - 1, curr_idx + 1)
            st.rerun()

    st.divider()

    # Main Practice View
    left_stimulus, right_question = st.columns([1, 1], gap="large")

    # Left Column: Stimulus, Puzzles, Line Graphs, Tables, Page Snippet
    with left_stimulus:
        st.markdown("#### 📖 Reference Stimulus & Source")
        
        ctx = q.get("context")
        if ctx and ctx.get("text"):
            st.markdown(f"""
            <div class="qb-context-box" style="margin-bottom:1rem;">
                <div class="qb-context-title">📌 {ctx.get('label') or 'Shared Direction'} · Questions {ctx.get('question_start') or '?'}-{ctx.get('question_end') or '?'}</div>
                <div style="font-size:0.95rem; line-height:1.6; color:#f1f5f9; white-space:pre-wrap;">{ctx.get('text')}</div>
            </div>
            """, unsafe_allow_html=True)
            
            # If region asset crop exists (e.g. Line graph for Q52-57, Table for Q61-66)
            if ctx.get("asset_path"):
                show_image(ctx["asset_path"], caption=f"Shared Stimulus Asset ({ctx.get('context_type')})")

        # Alphanumeric sequence highlight if present
        if ctx and (ctx.get("structured") or {}).get("sequence"):
            seq = ctx["structured"]["sequence"]
            st.markdown(f"""
            <div style="background:#0f172a; border:1px solid #4f46e5; border-radius:8px; padding:0.75rem 1rem; font-family:'JetBrains Mono',monospace; color:#38bdf8; font-size:1.1rem; letter-spacing:0.15em; word-break:break-all; margin-bottom:1rem;">
                {seq}
            </div>
            """, unsafe_allow_html=True)

        # Original Exam Snippet / Page Render Toggle
        with st.expander("🖼️ View Original Exam Page Snippet", expanded=not bool(ctx and ctx.get("text"))):
            if q.get("asset_path"):
                show_image(q["asset_path"], caption="Formula / Question Snippet Crop")
            if q.get("page_number"):
                page = repo.get_page(q["document_id"], q["page_number"])
                if page and page.get("render_path"):
                    show_image(page["render_path"], caption=f"Full Exam Page {q['page_number']}")

    # Right Column: Question Card, KaTeX Math, Options, Practice Actions
    with right_question:
        # Question Header Chips
        chips = []
        if q.get("question_number") is not None:
            chips.append(render_chip(f"Question #{q['question_number']}", "page"))
        if q.get("subject"):
            chips.append(render_chip(q["subject"], "subject"))
        if q.get("topic"):
            chips.append(render_chip(q["topic"], "topic"))
        if q.get("page_number"):
            chips.append(render_chip(f"Page {q['page_number']}", "draft"))
        
        st.markdown(f"<div style='margin-bottom:0.75rem;'>{''.join(chips)}</div>", unsafe_allow_html=True)

        # Question Stem in High-Visibility Card
        st.markdown(f"""
        <div class="qb-practice-card">
            <div class="qb-practice-stem">{q.get('text') or ''}</div>
        </div>
        """, unsafe_allow_html=True)

        # If Math formula reconstruction available, render with LaTeX
        if q.get("math") and q["math"].get("linear"):
            latex_code = linear_to_latex(q["math"]["linear"])
            st.markdown("<div style='font-size:0.88rem; font-weight:600; color:#818cf8; margin-bottom:0.25rem;'>📐 Formatted Mathematical Expression:</div>", unsafe_allow_html=True)
            try:
                st.latex(latex_code)
            except Exception:
                st.code(q["math"]["linear"])

        # Options Interactive Selection
        st.markdown("<div style='font-weight:600; color:#e2e8f0; margin:1rem 0 0.5rem 0;'>Choose your answer:</div>", unsafe_allow_html=True)
        options = q.get("options") or []
        opt_map = {f"{o['option_label'] or o['option_index']})  {o['text']}": o['option_index'] for o in options}
        
        choice_key = f"choice_q_{q['id']}"
        selected_label = st.radio(
            "Options",
            list(opt_map.keys()),
            key=choice_key,
            label_visibility="collapsed",
        )

        col_act1, col_act2 = st.columns([1, 1])
        check_clicked = col_act1.button("Check Answer", key=f"btn_check_{q['id']}", type="primary", use_container_width=True)
        reveal_answer = col_act2.checkbox("👁️ Reveal Answer Key", key=f"chk_rev_{q['id']}")

        # Answer Feedback
        ans_obj = q.get("answer")
        correct_idx = ans_obj.get("option_index") if ans_obj else None
        user_opt = opt_map.get(selected_label) if selected_label else None

        if check_clicked:
            if correct_idx is None:
                st.info("ℹ️ No official answer key is mapped to this question yet.")
            elif str(user_opt) == str(correct_idx):
                st.markdown(f"""
                <div class="qb-feedback-correct">
                    🎉 Excellent! Option {correct_idx} is the correct answer.
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="qb-feedback-wrong">
                    ❌ Incorrect. You selected Option {user_opt}, but the official answer is Option {correct_idx}.
                </div>
                """, unsafe_allow_html=True)

        if reveal_answer and ans_obj:
            st.markdown(f"""
            <div style="background:rgba(30, 41, 59, 0.7); border:1px solid rgba(16, 185, 129, 0.3); border-radius:8px; padding:0.85rem 1rem; margin-top:0.75rem;">
                <div style="font-weight:700; color:#34d399; font-size:0.95rem;">Official Key: Option {ans_obj.get('option_index')} ({ans_obj.get('answer_value')})</div>
                <div style="font-size:0.85rem; color:#94a3b8; margin-top:0.25rem;">
                    Status: <code>{ans_obj.get('review_status', 'unverified')}</code> · Extraction Method: <code>{ans_obj.get('extraction_method', 'answer_key_pairs')}</code>
                </div>
            </div>
            """, unsafe_allow_html=True)

# ===========================================================================
# TAB 2: CARD FEED MODE
# ===========================================================================
with tab_cards:
    st.markdown("### 📑 Browse Questions Feed")
    page_size = 10
    total_pages = max(1, (len(rows) + page_size - 1) // page_size)
    
    col_p1, col_p2 = st.columns([1, 3])
    feed_page = col_p1.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)
    col_p2.caption(f"Showing page {feed_page} of {total_pages} ({len(rows)} matching questions)")

    start_idx = (feed_page - 1) * page_size
    page_items = rows[start_idx : start_idx + page_size]

    for item in page_items:
        q_full = repo.get_question(item["id"])
        render_question_display(q_full)
        st.divider()

# ===========================================================================
# TAB 3: TABLE EXPLORER
# ===========================================================================
with tab_table:
    st.markdown("### 📊 Question Bank Spreadsheet View")
    table_data = [{
        "#": r["question_number"],
        "Subject": r["subject"],
        "Topic": r["topic"],
        "Page": r["page_number"],
        "Options": r["option_count"],
        "Answer": r["answer_value"] or "—",
        "Review Status": r["review_status"],
        "Question Stem": (r["stem_text"] or "")[:120],
    } for r in rows]
    st.dataframe(table_data, hide_index=True, width="stretch", height=500)
