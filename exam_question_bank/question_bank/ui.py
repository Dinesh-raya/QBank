"""Shared Streamlit helpers.

Kept separate from the pages so the page files stay thin and the same cached
repository/config is reused across reruns. Nothing here is imported by the core
processing modules, so the pipeline stays testable without Streamlit.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the project root importable regardless of how Streamlit launches a page.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st  # noqa: E402

from question_bank import config  # noqa: E402
from question_bank.repositories import Repository  # noqa: E402
from question_bank.services import ocr_engine  # noqa: E402
from question_bank.services.classifier import Classifier  # noqa: E402
from question_bank.services import local_model_adapter  # noqa: E402
from question_bank.taxonomy import Taxonomy  # noqa: E402


def bootstrap() -> None:
    """Ensure the project root is importable from a page script."""
    root = str(_PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


@st.cache_resource(show_spinner=False)
def get_repository() -> Repository:
    repo = Repository()
    Taxonomy(repo.db).ensure_seeded()
    return repo


@st.cache_resource(show_spinner=False)
def get_taxonomy() -> Taxonomy:
    tax = Taxonomy(get_repository().db)
    tax.ensure_seeded()
    return tax


def inject_theme() -> None:
    """Inject modern typography and high-visibility styling into the Streamlit app."""
    css = """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        letter-spacing: -0.01em;
    }

    code, pre, .mono {
        font-family: 'JetBrains Mono', monospace !important;
    }

    /* Primary Hero Header */
    .qb-header-container {
        padding: 0.85rem 0 1.25rem 0;
        margin-bottom: 1.5rem;
        border-bottom: 1px solid rgba(148, 163, 184, 0.15);
    }
    .qb-header-title {
        font-size: 1.85rem;
        font-weight: 700;
        letter-spacing: -0.025em;
        margin: 0;
        color: #f8fafc;
    }
    .qb-header-subtitle {
        font-size: 0.95rem;
        color: #94a3b8;
        margin-top: 0.35rem;
        line-height: 1.45;
    }

    /* Question card */
    .qb-question-card {
        background: linear-gradient(145deg, rgba(30, 41, 59, 0.75), rgba(15, 23, 42, 0.9));
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 12px;
        padding: 1.25rem 1.4rem;
        margin-bottom: 1.25rem;
        box-shadow: 0 4px 16px -2px rgba(0, 0, 0, 0.3);
    }
    .qb-question-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
        margin-bottom: 0.85rem;
    }
    .qb-question-text {
        font-size: 1.05rem;
        line-height: 1.65;
        color: #f8fafc;
        margin-bottom: 1.15rem;
        white-space: pre-wrap;
    }

    /* Options */
    .qb-option-item {
        display: flex;
        align-items: flex-start;
        padding: 0.65rem 0.85rem;
        margin-bottom: 0.5rem;
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(148, 163, 184, 0.12);
        transition: all 0.15s ease-in-out;
    }
    .qb-option-item:hover {
        background: rgba(255, 255, 255, 0.06);
        border-color: rgba(148, 163, 184, 0.25);
    }
    .qb-option-item.correct {
        background: rgba(16, 185, 129, 0.14);
        border-color: rgba(16, 185, 129, 0.45);
        box-shadow: 0 0 12px rgba(16, 185, 129, 0.15);
    }
    .qb-option-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 26px;
        height: 26px;
        border-radius: 6px;
        background: rgba(148, 163, 184, 0.15);
        color: #cbd5e1;
        font-weight: 600;
        font-size: 0.85rem;
        margin-right: 0.75rem;
        flex-shrink: 0;
    }
    .qb-option-item.correct .qb-option-badge {
        background: #10b981;
        color: #ffffff;
    }
    .qb-option-content {
        flex-grow: 1;
        font-size: 0.98rem;
        line-height: 1.5;
        color: #e2e8f0;
    }
    .qb-correct-tag {
        margin-left: 0.5rem;
        font-size: 0.75rem;
        font-weight: 700;
        color: #34d399;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* Chips */
    .qb-chip {
        display: inline-flex;
        align-items: center;
        padding: 0.22rem 0.65rem;
        border-radius: 6px;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.01em;
    }
    .qb-chip-subject { background: rgba(99, 102, 241, 0.18); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.35); }
    .qb-chip-topic { background: rgba(14, 165, 233, 0.18); color: #7dd3fc; border: 1px solid rgba(14, 165, 233, 0.35); }
    .qb-chip-subtopic { background: rgba(14, 165, 233, 0.12); color: #bae6fd; border: 1px solid rgba(14, 165, 233, 0.25); }
    .qb-chip-confirmed { background: rgba(16, 185, 129, 0.18); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.35); }
    .qb-chip-needs_review { background: rgba(245, 158, 11, 0.18); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.35); }
    .qb-chip-draft { background: rgba(148, 163, 184, 0.18); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.35); }
    .qb-chip-excluded { background: rgba(239, 68, 68, 0.18); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.35); }
    .qb-chip-tag { background: rgba(168, 85, 247, 0.18); color: #d8b4fe; border: 1px solid rgba(168, 85, 247, 0.35); }
    .qb-chip-page { background: rgba(100, 116, 139, 0.18); color: #e2e8f0; border: 1px solid rgba(100, 116, 139, 0.35); }

    /* Shared Context Banner */
    .qb-context-box {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.6), rgba(15, 23, 42, 0.8));
        border-left: 4px solid #6366f1;
        border-radius: 0 10px 10px 0;
        padding: 0.9rem 1.15rem;
        margin-bottom: 1.15rem;
        font-size: 0.94rem;
        line-height: 1.55;
        color: #e2e8f0;
    }
    .qb-context-title {
        font-size: 0.85rem;
        font-weight: 700;
        color: #818cf8;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 0.4rem;
    }

    /* Math Box */
    .qb-math-box {
        background: rgba(15, 23, 42, 0.95);
        border: 1px solid rgba(99, 102, 241, 0.3);
        border-radius: 8px;
        padding: 0.75rem 1rem;
        margin: 0.75rem 0;
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.05rem;
        color: #38bdf8;
    }

    /* Study & Practice Mode Styles */
    .qb-nav-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem;
        margin: 0.75rem 0 1.25rem 0;
        max-height: 140px;
        overflow-y: auto;
        padding: 0.5rem;
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid rgba(148, 163, 184, 0.12);
        border-radius: 8px;
    }
    .qb-nav-pill {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        border-radius: 6px;
        font-size: 0.82rem;
        font-weight: 600;
        cursor: pointer;
        background: rgba(30, 41, 59, 0.8);
        color: #cbd5e1;
        border: 1px solid rgba(148, 163, 184, 0.15);
        transition: all 0.15s ease;
    }
    .qb-nav-pill.active {
        background: #4f46e5;
        color: #ffffff;
        border-color: #6366f1;
        box-shadow: 0 0 10px rgba(99, 102, 241, 0.5);
    }
    .qb-nav-pill.answered {
        border-color: #10b981;
        color: #6ee7b7;
    }

    /* Interactive Practice Card */
    .qb-practice-card {
        background: linear-gradient(145deg, #182234, #0f172a);
        border: 1px solid rgba(99, 102, 241, 0.25);
        border-radius: 14px;
        padding: 1.5rem 1.75rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 8px 24px -4px rgba(0, 0, 0, 0.4);
    }
    .qb-practice-stem {
        font-size: 1.15rem;
        line-height: 1.7;
        font-weight: 500;
        color: #f8fafc;
        margin: 1rem 0 1.25rem 0;
        letter-spacing: -0.01em;
    }
    .qb-feedback-correct {
        background: rgba(16, 185, 129, 0.15);
        border: 1px solid rgba(16, 185, 129, 0.4);
        border-radius: 8px;
        padding: 0.85rem 1.1rem;
        color: #34d399;
        font-weight: 600;
        font-size: 0.95rem;
        margin-top: 1rem;
    }
    .qb-feedback-wrong {
        background: rgba(239, 68, 68, 0.15);
        border: 1px solid rgba(239, 68, 68, 0.4);
        border-radius: 8px;
        padding: 0.85rem 1.1rem;
        color: #f87171;
        font-weight: 600;
        font-size: 0.95rem;
        margin-top: 1rem;
    }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def linear_to_latex(linear: str) -> str:
    """Convert heuristic linear math expression into KaTeX math formula."""
    if not linear:
        return ""
    import re
    s = linear.strip()
    s = re.sub(r'√\s*(\d+|\?)', r'\\sqrt{\1}', s)
    s = s.replace('÷', r' \div ')
    s = s.replace('−', ' - ')
    s = s.replace('×', r' \times ')
    s = re.sub(r'(\d+|\?)\s*x\s*(\d+|\?)', r'\1 \\times \2', s)
    s = re.sub(r'\(([^)]+)\)/\(([^)]+)\)', r'\\frac{\1}{\2}', s)
    s = re.sub(r'(\d+)/(\d+)', r'\\frac{\1}{\2}', s)
    return s


def page_header(title: str, subtitle: str = "") -> None:
    inject_theme()
    html = f"""
    <div class="qb-header-container">
        <h1 class="qb-header-title">{title}</h1>
        {f'<div class="qb-header-subtitle">{subtitle}</div>' if subtitle else ''}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_chip(label: str, kind: str = "tag") -> str:
    return f'<span class="qb-chip qb-chip-{kind}">{label}</span>'


def render_question_display(q: dict) -> None:
    """Render a fully formatted question with chips, stem, options, and context."""
    chips = []
    if q.get("question_number") is not None:
        chips.append(render_chip(f"Q{q['question_number']}", "page"))
    if q.get("page_number"):
        chips.append(render_chip(f"Page {q['page_number']}", "page"))
    if q.get("subject"):
        chips.append(render_chip(q["subject"], "subject"))
    if q.get("topic"):
        chips.append(render_chip(q["topic"], "topic"))
    if q.get("review_status"):
        chips.append(render_chip(q["review_status"].replace("_", " "), q["review_status"]))
    for tag in q.get("tags") or []:
        chips.append(render_chip(f"#{tag}", "tag"))

    # Shared Context
    ctx = q.get("context")
    if ctx and ctx.get("text"):
        st.markdown(f"""
        <div class="qb-context-box">
            <div class="qb-context-title">📌 {ctx.get('label') or 'Shared Direction'} [{ctx.get('context_type', '')}]</div>
            <div>{ctx.get('text')}</div>
        </div>
        """, unsafe_allow_html=True)

    # Question stem & meta
    st.markdown(f"""
    <div class="qb-question-card">
        <div class="qb-question-meta">{''.join(chips)}</div>
        <div class="qb-question-text">{q.get('text') or ''}</div>
    </div>
    """, unsafe_allow_html=True)

    # Math formula linear reconstruction if available
    if q.get("math") and q["math"].get("linear"):
        st.markdown(f"""
        <div style="font-size:0.85rem; color:#94a3b8; font-weight:600; margin-bottom:0.25rem;">
            📐 Heuristic Formula Representation (verify with crop on left):
        </div>
        <div class="qb-math-box">{q['math']['linear']}</div>
        """, unsafe_allow_html=True)

    # Options
    correct_opt = str(q["answer"]["option_index"]) if (q.get("answer") and q["answer"].get("option_index") is not None) else None
    st.markdown('<div style="font-weight:600; margin: 0.75rem 0 0.5rem 0; color:#cbd5e1;">Options</div>', unsafe_allow_html=True)
    for opt in q.get("options") or []:
        is_correct = correct_opt is not None and str(opt.get("option_index")) == correct_opt
        opt_class = "qb-option-item correct" if is_correct else "qb-option-item"
        lbl = opt.get("option_label") or str(opt.get("option_index"))
        correct_marker = '<span class="qb-correct-tag">✓ Correct Answer</span>' if is_correct else ''
        st.markdown(f"""
        <div class="{opt_class}">
            <div class="qb-option-badge">{lbl}</div>
            <div class="qb-option-content">{opt.get('text') or ''} {correct_marker}</div>
        </div>
        """, unsafe_allow_html=True)


def human_bytes(n: int | float | None) -> str:
    if not n:
        return "0 B"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def show_image(path: str | None, caption: str = "", width: int | None = None) -> None:
    if not path:
        st.info("No image available.")
        return
    p = Path(path)
    if not p.exists():
        st.warning(f"Image file missing: {p}")
        return
    st.image(str(p), caption=caption or p.name, width=width or "stretch")


def ai_status_line() -> str:
    status = local_model_adapter.check_status()
    if status.available:
        return f"Local AI reachable at {status.endpoint}"
    return f"Local AI unavailable — {status.detail}"


def ocr_status_line() -> str:
    if ocr_engine.ocr_available():
        return f"Tesseract available: {ocr_engine.tesseract_path()}"
    return ("Tesseract not detected. Digital PDFs work fully; scanned files will "
            "be flagged. Set QB_TESSERACT_CMD to enable OCR.")


def env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default) == "1"
