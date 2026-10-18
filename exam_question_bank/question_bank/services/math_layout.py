"""Best-effort reconstruction of 2-D mathematical layouts.

The reference paper renders formulas with stacked fractions, radicals drawn as
vector paths, big parentheses and superscripts. Reading order from the text
layer is therefore wrong, so we rebuild an expression from coordinates:

* collect tokens into visual rows;
* fold superscripts (much smaller font, raised) onto the preceding token as ``^``;
* detect stacked fractions (aligned numerator/denominator, optionally under a
  drawn fraction bar) and render them ``(num)/(den)``;
* detect radicals (filled vector paths) as ``sqrt`` and big parentheses from the
  Symbol glyph pieces;
* merge every element back in left-to-right order.

IMPORTANT: this is explicitly a *heuristic*. Whenever structure (fraction,
radical, big parenthesis, superscript) is present the result is flagged
``uncertain`` so the UI shows the original crop for verification. We never
present the reconstruction as the verified source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .. import config
from ..models import Line, Span
from .pdf_extractor import DrawingInfo

_OPEN_PAREN = "("
_CLOSE_PAREN = ")"
_OPERATORS = set("+\u2212\u00d7\u00f7=<>")
_BIG_PAREN_PIECES = {"(", ")"}


@dataclass
class Element:
    text: str
    x0: float
    x1: float
    y0: float
    kind: str = "token"          # token|fraction|radical|paren
    fraction: bool = False
    radical: bool = False


@dataclass
class MathBlock:
    visual_lines: list[str] = field(default_factory=list)
    linear: str = ""
    has_fractions: bool = False
    has_radicals: bool = False
    has_superscripts: bool = False
    has_big_parens: bool = False
    uncertain: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def is_math(self) -> bool:
        return bool(self.visual_lines)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _is_big_paren_piece(font: str, text: str) -> bool:
    return "symbol" in font.lower() and text.strip() in _BIG_PAREN_PIECES


def _radicals(drawings: list[DrawingInfo], bbox: Optional[tuple]) -> list[DrawingInfo]:
    """Return filled vector paths that look like radical (sqrt) signs.

    Radical signs are filled paths ~10-22 pt tall and 10-120 pt wide. Fraction
    bars are *stroked* lines and are therefore excluded automatically.
    """
    out = []
    for d in drawings:
        if d.kind != "fill":
            continue
        w = d.bbox[2] - d.bbox[0]
        h = d.bbox[3] - d.bbox[1]
        if not (8 <= h <= 24 and 8 <= w <= 130):
            continue
        if bbox is not None and not (bbox[1] - 4 <= d.bbox[1] <= bbox[3] + 4):
            continue
        out.append(d)
    return out


def _unique_radicals(radicals: list[DrawingInfo]) -> list[DrawingInfo]:
    """Deduplicate radicals that share (nearly) the same position."""
    seen: list[DrawingInfo] = []
    for r in radicals:
        if any(abs(r.bbox[0] - s.bbox[0]) < 3 and abs(r.bbox[1] - s.bbox[1]) < 3 for s in seen):
            continue
        seen.append(r)
    return seen


def _blank(text: str) -> bool:
    return text.strip() == ""


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------
def reconstruct(lines: list[Line], drawings: list[DrawingInfo],
                base_font: float, bbox: Optional[tuple] = None) -> MathBlock:
    block = MathBlock()
    spans: list[Span] = [s for l in lines for s in l.spans]
    # Keep only spans inside the vertical band of interest (if given).
    if bbox is not None:
        spans = [s for s in spans if bbox[1] - 2 <= s.y0 <= bbox[3] + 2]
    spans = [s for s in spans if not _blank(s.text)]
    if not spans:
        return block

    sup_threshold = base_font * 0.74

    # 1) rows
    spans.sort(key=lambda s: (s.y0, s.x0))
    rows: list[list[Span]] = []
    for s in spans:
        placed = False
        for row in rows:
            ref = row[0]
            if abs(s.y0 - ref.y0) <= config.LAYOUT.line_y_tolerance + 1:
                row.append(s)
                placed = True
                break
        if not placed:
            rows.append([s])
    for row in rows:
        row.sort(key=lambda s: s.x0)
    rows.sort(key=lambda r: (r[0].y0, r[0].x0))

    block.visual_lines = [_row_text(r) for r in rows]

    # 2) pull out superscripts and paren pieces per row, build per-row elements
    row_elements: list[list[Element]] = []
    for row in rows:
        row_elements.append(_row_elements(row, sup_threshold, block))

    # 3) main row = the row containing '=' else the widest row
    main_idx = _main_row_index(row_elements)

    # 4) fraction detection among non-main rows
    fractions: list[Element] = []
    consumed: set[int] = set()
    _detect_fractions(row_elements, main_idx, fractions, consumed, block)

    # 5) radicals
    for d in _unique_radicals(_radicals(drawings, bbox)):
        block.has_radicals = True
        el = Element("\u221a", d.bbox[0], d.bbox[0] + 1, d.bbox[1], kind="radical", radical=True)
        # extent of the radical = a horizontal stroke starting near the glyph top
        bar_x1 = _radical_overbar_x1(drawings, d)
        if bar_x1 is not None:
            el.x1 = bar_x1
        fractions.append(el)

    # 6) elements = main-row elements + fractions + radicals; consumed rows dropped
    elements: list[Element] = list(row_elements[main_idx]) if 0 <= main_idx < len(row_elements) else []
    for idx, row in enumerate(row_elements):
        if idx == main_idx or idx in consumed:
            continue
        elements.extend(row)
    elements.extend(fractions)
    elements = [e for e in elements if e.text.strip() != ""]

    # 7) order by x and render
    elements.sort(key=lambda e: (e.x0, e.y0))
    block.linear = _render(elements)
    block.uncertain = block.has_fractions or block.has_radicals or block.has_big_parens or block.has_superscripts
    if block.uncertain:
        block.notes.append("2-D layout reconstructed heuristically; verify against the source crop.")
    return block


def _row_text(row: list[Span]) -> str:
    parts: list[str] = []
    for i, s in enumerate(row):
        t = s.text
        if i > 0 and not parts[-1].endswith(" ") and not t.startswith(" "):
            if s.x0 - row[i - 1].x1 > 1.0:
                parts.append(" ")
        parts.append(t)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _row_elements(row: list[Span], sup_threshold: float, block: MathBlock) -> list[Element]:
    elements: list[Element] = []
    base_size = max((s.size for s in row), default=sup_threshold / 0.74)
    for s in row:
        text = s.text
        if _is_big_paren_piece(s.font, text):
            block.has_big_parens = True
            elements.append(Element(text.strip(), s.x0, s.x1, s.y0, kind="paren"))
            continue
        is_sup = s.size <= sup_threshold and s.size < base_size - 0.5
        if is_sup:
            block.has_superscripts = True
            if elements and elements[-1].kind == "token":
                elements[-1].text += "^" + _wrap_sup(text.strip())
            else:
                elements.append(Element("^" + _wrap_sup(text.strip()), s.x0, s.x1, s.y0))
            continue
        if elements and s.x0 - elements[-1].x1 < 1.0 and elements[-1].kind == "token":
            elements[-1].text += text
            elements[-1].x1 = s.x1
        else:
            elements.append(Element(text, s.x0, s.x1, s.y0, kind="token"))
    # collapse multi-piece big parens (open/close) at the same x
    collapsed: list[Element] = []
    for e in elements:
        if e.kind == "paren" and collapsed and collapsed[-1].kind == "paren" and abs(collapsed[-1].x0 - e.x0) <= 4:
            continue
        collapsed.append(e)
    return [e for e in collapsed if e.text.strip() != ""]


def _wrap_sup(text: str) -> str:
    t = text.strip()
    if len(t) <= 1:
        return t
    return f"({t})"


def _main_row_index(row_elements: list[list[Element]]) -> int:
    best = -1
    best_score = -1.0
    for i, row in enumerate(row_elements):
        row_text = " ".join(e.text for e in row)
        span = (max((e.x1 for e in row), default=0.0) - min((e.x0 for e in row), default=0.0))
        score = span + (500 if "=" in row_text else 0)
        if score > best_score:
            best_score = score
            best = i
    return best


def _detect_fractions(row_elements, main_idx, out_elements, consumed, block) -> None:
    # token-level alignment first (multiple fractions on shared rows)
    for ai, arow in enumerate(row_elements):
        if ai == main_idx:
            continue
        for bi, brow in enumerate(row_elements):
            if bi == main_idx or bi <= ai:
                continue
            for a in arow:
                if a.kind != "token":
                    continue
                for b in brow:
                    if b.kind != "token":
                        continue
                    dy = b.y0 - a.y0
                    if not (6 <= dy <= 26):
                        continue
                    cx_a = (a.x0 + a.x1) / 2
                    cx_b = (b.x0 + b.x1) / 2
                    if abs(cx_a - cx_b) <= 6 and pure_fraction_text(a.text) and pure_fraction_text(b.text):
                        out_elements.append(Element(
                            f"{a.text}/{b.text}", min(a.x0, b.x0), max(a.x1, b.x1), a.y0,
                            kind="fraction", fraction=True))
                        block.has_fractions = True
                        consumed.add(ai)
                        consumed.add(bi)
                        break
    # row-level fallback for a single stacked numerator/denominator (e.g. (267-42)/15)
    unclaimed_above = [i for i in range(main_idx) if i not in consumed]
    unclaimed_below = [i for i in range(main_idx + 1, len(row_elements)) if i not in consumed]
    for ai in unclaimed_above:
        for bi in unclaimed_below:
            arow, brow = row_elements[ai], row_elements[bi]
            if not arow or not brow:
                continue
            a0 = min(e.x0 for e in arow); a1 = max(e.x1 for e in arow)
            b0 = min(e.x0 for e in brow); b1 = max(e.x1 for e in brow)
            overlap = min(a1, b1) - max(a0, b0)
            if overlap <= 0:
                continue
            a_c = (a0 + a1) / 2
            b_c = (b0 + b1) / 2
            if abs(a_c - b_c) > 18:
                continue
            num = " ".join(e.text for e in arow if e.kind == "token")
            den = " ".join(e.text for e in brow if e.kind == "token")
            if not num or not den:
                continue
            out_elements.append(Element(
                f"({num})/({den})" if _needs_parens(num) else f"{num}/{den}",
                min(a0, b0), max(a1, b1), min(e.y0 for e in arow),
                kind="fraction", fraction=True))
            block.has_fractions = True
            consumed.add(ai)
            consumed.add(bi)


def pure_fraction_text(t: str) -> bool:
    t = t.strip()
    return bool(re.fullmatch(r"[0-9]+(\.[0-9]+)?", t))


def _needs_parens(text: str) -> bool:
    return len(text.split()) > 1


def _radical_overbar_x1(drawings: list[DrawingInfo], radical: DrawingInfo) -> Optional[float]:
    """If a horizontal stroke sits at the radical's top, return its end x."""
    top = radical.bbox[1]
    best: Optional[float] = None
    for d in drawings:
        if d.kind != "line":
            continue
        w = d.bbox[2] - d.bbox[0]
        h = abs(d.bbox[3] - d.bbox[1])
        if h > 1.5 or w < 8:
            continue
        if abs(d.bbox[1] - top) <= 2.0 and d.bbox[0] >= radical.bbox[0] - 2:
            if best is None or d.bbox[2] > best:
                best = d.bbox[2]
    return best


def _render(elements: list[Element]) -> str:
    if not elements:
        return ""
    parts: list[str] = []
    for e in elements:
        parts.append(e.text)
    text = " ".join(p.strip() for p in parts if p.strip() != "")
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\u221a\s+", "\u221a", text)
    text = re.sub(r"\s+\^", "^", text)
    text = re.sub(r"([+\u2212\u00d7\u00f7=<>])\s+", r"\1 ", text)
    text = re.sub(r"\s+([+\u2212\u00d7\u00f7=<>])", r" \1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
