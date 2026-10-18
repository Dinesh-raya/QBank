"""Configuration, paths and tunable constants for the Exam Question Bank.

Everything the rest of the application needs to locate files, choose defaults,
and tune extraction behaviour lives here so it can be changed in one place and
overridden with environment variables where sensible.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Package / project layout
# ---------------------------------------------------------------------------
PACKAGE_DIR = Path(__file__).resolve().parent          # .../exam_question_bank/question_bank
PROJECT_ROOT = PACKAGE_DIR.parent                       # .../exam_question_bank

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
RENDERS_DIR = DATA_DIR / "renders"
ASSETS_DIR = DATA_DIR / "assets"
EXPORTS_DIR = DATA_DIR / "exports"
BACKUPS_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / "question_bank.db"

DEFAULT_TAXONOMY_PATH = CONFIG_DIR / "default_taxonomy.json"

for _d in (DATA_DIR, UPLOADS_DIR, RENDERS_DIR, ASSETS_DIR, EXPORTS_DIR, BACKUPS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Layout / extraction tuning
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LayoutConfig:
    """Heuristics for turning raw PDF coordinates into structured content.

    All coordinates are in PDF points with the origin at the top-left of the
    page (PyMuPDF convention).
    """

    # A span whose font size is at least this large is treated as decorative
    # watermark / branding, not body content. (Reference watermark is 90 / 212 pt.)
    watermark_min_font_size: float = 30.0

    # Vertical tolerance when grouping spans into the same visual text line.
    line_y_tolerance: float = 3.0

    # Fraction of the page height reserved at the top and bottom for running
    # headers/footers when there is no stronger evidence.
    header_band_fraction: float = 0.09
    # The reference paper draws its page number at ~91% of page height and the
    # answer key up to ~87%, so the footer band starts below the key.
    footer_band_fraction: float = 0.10

    # A page whose extractable text has fewer than this many characters is
    # treated as needing OCR.
    min_text_chars_for_digital: int = 120

    # Fraction of page area covered by images above which a page is considered
    # scan-like even if it has a little text.
    scanned_image_area_fraction: float = 0.55

    # Render DPI for page previews and asset crops.
    render_dpi: int = 150

    # Extra padding (points) added around cropped assets.
    crop_padding: float = 4.0


LAYOUT = LayoutConfig()


# ---------------------------------------------------------------------------
# Symbol-font decoding
# ---------------------------------------------------------------------------
# PDF fonts such as "SymbolMT" encode their glyphs with a subset that maps to
# the Adobe Symbol encoding + 0xF000 (private use area). Decoding these restores
# math/inequality symbols that would otherwise be dropped from the text layer.
SYMBOL_PUA_BASE = 0xF000
SYMBOL_MAP: dict[int, str] = {
    0x22: "\u2200",   # forall
    0x24: "\u2203",   # exists
    0x27: "\u220b",   # suchthat
    0x2A: "\u2217",   # asterisk math
    0x2B: "+",
    0x2D: "\u2212",   # minus sign
    0x3D: "=",
    0xA3: "\u2264",   # <=
    0xB1: "\u00b1",   # +/-
    0xB3: "\u2265",   # >=
    0xB4: "\u00d7",   # multiplication sign
    0xB9: "\u2260",   # not equal
    0xB8: "\u00f7",   # division sign
    0xD6: "\u221a",   # radical
    0xE6: "(",        # large left parenthesis (top piece)
    0xE7: "(",        # large left parenthesis (middle piece)
    0xE8: "(",        # large left parenthesis (bottom piece)
    0xF6: ")",        # large right parenthesis (top piece)
    0xF7: ")",        # large right parenthesis (middle piece)
    0xF8: ")",        # large right parenthesis (bottom piece)
}
# Fonts whose private-use glyphs should be decoded via SYMBOL_MAP.
SYMBOL_FONT_MARKERS = ("symbol", "mt extra", "mathematicalpi")


def decode_symbol_text(text: str, font_name: str) -> str:
    """Return *text* with Symbol-font PUA code points mapped to real symbols."""
    if not text:
        return text
    is_symbol = any(m in font_name.lower() for m in SYMBOL_FONT_MARKERS)
    if not is_symbol:
        return text
    out = []
    for ch in text:
        code = ord(ch)
        if SYMBOL_PUA_BASE <= code <= SYMBOL_PUA_BASE + 0xFF:
            out.append(SYMBOL_MAP.get(code - SYMBOL_PUA_BASE, f"\ufffd"))
        else:
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# Optional local AI classifier (Ollama / OpenAI-compatible)
# ---------------------------------------------------------------------------
@dataclass
class AIConfig:
    enabled: bool = field(default_factory=lambda: os.environ.get("QB_AI_ENABLED", "0") == "1")
    provider: str = field(default_factory=lambda: os.environ.get("QB_AI_PROVIDER", "ollama"))
    base_url: str = field(default_factory=lambda: os.environ.get("QB_AI_BASE_URL", "http://localhost:11434"))
    model: str = field(default_factory=lambda: os.environ.get("QB_AI_MODEL", "qwen2.5:3b-instruct"))
    timeout: float = field(default_factory=lambda: _env_float("QB_AI_TIMEOUT", 60.0))
    # Never send content anywhere unless the user explicitly opts in.
    allow_remote: bool = field(default_factory=lambda: os.environ.get("QB_AI_ALLOW_REMOTE", "0") == "1")


AI = AIConfig()


# ---------------------------------------------------------------------------
# Content/structure patterns
# ---------------------------------------------------------------------------
# Question marker: a number followed by '.' or ')' at the start of a
# left-margin line (e.g. "5." / "61.").
QUESTION_NUMBER_RE = r"^\s*(\d{1,3})\s*[\.\)]\s*"

# Option markers embedded in a line, e.g. "1) ...", "3)". Used to split option
# text even when several options share a physical line or span.
OPTION_MARKER_RE = r"(?:(?<=^)|(?<=\s)|(?<=[a-z\)\]]))([1-9])\)\s*"

# "Direction (5-9): ..." / "Directions (52-57) ..."
DIRECTION_RE = r"^\s*Directions?\s*\(\s*(\d{1,3})\s*[\-\u2013\u2014]\s*(\d{1,3})\s*\)\s*:?"

# Answer key pair e.g. "12.3" (question 12 -> option 3)
ANSWER_KEY_PAIR_RE = r"(\d{1,3})\s*[\.\)\-\u2013]\s*([1-9])\b"
# Answer key letter pair e.g. "12.A"
ANSWER_KEY_LETTER_RE = r"(\d{1,3})\s*[\.\)\-\u2013]\s*([A-Ea-e])\b"

# Section headings that should be recognised as first-class sections.
KNOWN_SECTION_NAMES = [
    "REASONING",
    "REASONING ABILITY",
    "NUMERICAL ABILITY",
    "QUANTITATIVE APTITUDE",
    "QUANTITATIVE APTITUDE & DATA INTERPRETATION",
    "ENGLISH LANGUAGE",
    "ENGLISH",
    "GENERAL AWARENESS",
    "GENERAL KNOWLEDGE",
    "BANKING AWARENESS",
    "COMPUTER AWARENESS",
    "COMPUTER KNOWLEDGE",
    "HINDI LANGUAGE",
    "PROFESSIONAL KNOWLEDGE",
]

# A section heading is an all-caps short line rendered at a larger font than
# body text. Relative sizing is used so it adapts to other papers.
SECTION_FONT_SIZE_MARGIN = 1.0  # pts larger than the page's body font size

DEFAULT_BODY_FONT_SIZE = 11.0


# ---------------------------------------------------------------------------
# Review / persistence defaults
# ---------------------------------------------------------------------------
DEFAULT_EXAM = "IBPS RRB Clerk"
REVIEW_STATUS_DRAFT = "draft"
REVIEW_STATUS_NEEDS_REVIEW = "needs_review"
REVIEW_STATUS_CONFIRMED = "confirmed"
REVIEW_STATUS_EXCLUDED = "excluded"

EXTRACTION_METHOD_DIGITAL = "pymupdf-text"
EXTRACTION_METHOD_OCR = "tesseract-ocr"
EXTRACTION_METHOD_MANUAL = "manual"
