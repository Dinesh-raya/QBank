"""Question and shared-context segmentation — the highest-priority stage.

Strategy (deliberately not regex-only):

1. Flatten every page's structural lines into one reading-order stream.
2. Section headings and ``Direction (a-b):`` blocks are structural anchors.
   A direction block opens a *shared context* with a question range; everything
   between the direction and the first question is the stimulus/passage text.
3. Question anchors are ``N.`` / ``N)`` markers at the left margin. Lines are
   assigned to the question whose marker precedes them.
4. Math preamble lines (formula rows that sit *above* the question number, as
   the reference does for Q68) and superscript fragments that precede the next
   marker are re-assigned to the correct question rather than being lost.
5. Options are extracted by ``option_extractor`` which understands every option
   layout in the reference paper.
6. Every question is linked to the shared context whose ``(a-b)`` range contains
   its number. Questions remain independently searchable/classifiable.

Nothing is fabricated: missing numbers are left missing and flagged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .. import config
from ..models import (Line, PageLayout, ParsedContext, ParsedOption,
                      ParsedQuestion, ParsedSection, Region)
from . import math_layout
from .context_linker import best_context_for, find_shared_region, in_range
from .option_extractor import extract_options

_Q_RE = re.compile(config.QUESTION_NUMBER_RE)
_DIR_RE = re.compile(config.DIRECTION_RE)

_MATH_FAMILY_PREFIXES = ("timesnewroman", "symbol", "cambria", "math")
_MATH_OPERATORS = set("+\u2212\u00d7\u00f7=<>%\u221a^")
_ARITHMETIC_OPERATORS = set("\u00d7\u00f7\u221a")   # × ÷ √ — unambiguous
_HAS_DIGIT = re.compile(r"\d")


def looks_arithmetic(text: str) -> bool:
    """Heuristic for "this is an equation", font-independent.

    The reference renders some equations (e.g. Q69) in the body font, so font
    detection alone misses them. An expression counts as arithmetic when it
    contains a strong operator (× ÷ √) or an ``=`` together with a digit.
    """
    if not text:
        return False
    if any(c in text for c in _ARITHMETIC_OPERATORS):
        return True
    return "=" in text and bool(_HAS_DIGIT.search(text))


def _family(font: str) -> str:
    return re.split(r"[-+]", font.strip().lower())[0]


def looks_math_line(line: Line) -> bool:
    fams: dict[str, int] = {}
    total = 0
    for s in line.spans:
        if s.text.strip() == "":
            continue
        f = _family(s.font)
        fams[f] = fams.get(f, 0) + len(s.text)
        total += len(s.text)
    if total == 0:
        return False
    math_chars = sum(n for f, n in fams.items() if f.startswith(_MATH_FAMILY_PREFIXES))
    text = line.text()
    has_operator = any(c in _MATH_OPERATORS for c in text)
    return math_chars >= 0.6 * total and has_operator


def _is_question_line(line: Line, left_margin: float) -> Optional[re.Match]:
    if line.x0 > left_margin + 8:
        return None
    return _Q_RE.match(line.text())


def _directs_context(text: str) -> Optional[tuple[int, int]]:
    m = _DIR_RE.match(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    if re.match(r"^\s*direction", text, flags=re.IGNORECASE):
        return None, None
    return None


def _context_type_from_text(text: str) -> str:
    t = text.lower()
    if "graph" in t or "chart" in t:
        return "data_interpretation_graph"
    if "table" in t:
        return "data_interpretation_table"
    if "passage" in t or "read the" in t:
        return "reading_passage"
    if "code language" in t or "coded as" in t:
        return "coding_language"
    if "symbol, letter and digits" in t or "arrangement of symbol" in t:
        return "alphanumeric_sequence"
    if "floor" in t:
        return "floor_puzzle"
    if "height" in t:
        return "height_puzzle"
    if "syllogism" in t or "statements" in t or "conclusions" in t:
        return "logical_statements"
    return "instruction"


@dataclass
class _QAcc:
    number: Optional[int]
    number_raw: str
    page_number: int
    order_index: int
    lines: list[tuple[int, Line]] = field(default_factory=list)
    marker_line_pos: int = 0
    marker_span_bbox: Optional[tuple] = None
    marker_text: str = ""
    context_index: Optional[int] = None
    section_index: Optional[int] = None
    preamble: list[tuple[int, Line]] = field(default_factory=list)


class QuestionSegmenter:
    def __init__(self, layouts: list[PageLayout]):
        self.layouts = layouts
        self.sections: list[ParsedSection] = []
        self.contexts: list[ParsedContext] = []
        self.questions: list[ParsedQuestion] = []
        self.regions_by_page: dict[int, list[Region]] = {l.page_number: l.regions for l in layouts}

    # ------------------------------------------------------------------
    def segment(self) -> tuple[list[ParsedSection], list[ParsedContext], list[ParsedQuestion]]:
        content: list[tuple[int, Line]] = []
        for layout in self.layouts:
            for line in layout.lines:
                if line.kind in ("heading", "direction", "body"):
                    content.append((layout.page_number, line))

        left_margin = self._left_margin()

        # Pre-compute anchor positions (question markers) for lookahead logic.
        anchor_idx: list[int] = []
        for i, (_, line) in enumerate(content):
            if _is_question_line(line, left_margin):
                anchor_idx.append(i)
        anchor_set = set(anchor_idx)

        cur_section: Optional[ParsedSection] = None
        cur_context: Optional[ParsedContext] = None
        ctx_lines: list[tuple[int, Line]] = []
        cur_q: Optional[_QAcc] = None
        pending: list[tuple[int, Line]] = []
        order = 0

        def finalize_context():
            nonlocal cur_context, ctx_lines
            if cur_context is not None and ctx_lines:
                cur_context.text = _join_lines(ctx_lines)
                cur_context.page_start = min(p for p, _ in ctx_lines)
                cur_context.page_end = max(p for p, _ in ctx_lines)
                xs0 = min(l.x0 for _, l in ctx_lines); ys0 = min(l.y0 for _, l in ctx_lines)
                xs1 = max(l.x1 for _, l in ctx_lines); ys1 = max(l.y1 for _, l in ctx_lines)
                cur_context.bbox = (xs0, ys0, xs1, ys1)
                structured = find_shared_region(cur_context, ctx_lines, self.regions_by_page)
                # Preserve exact per-line text (spacing matters for symbol
                # sequences such as questions 24-28).
                structured["exact_lines"] = [_exact_line_text(l) for _, l in ctx_lines]
                if cur_context.context_type == "alphanumeric_sequence":
                    structured["sequence"] = " ".join(
                        _exact_line_text(l) for _, l in ctx_lines[1:]
                    ).strip()
                cur_context.structured = structured
            ctx_lines = []

        def finalize_question():
            nonlocal cur_q, pending
            if cur_q is None:
                return
            q = self._build_question(cur_q)
            if q is not None:
                self.questions.append(q)
            cur_q = None

        for i, (page, line) in enumerate(content):
            text = line.text()

            if line.kind == "heading":
                finalize_context()
                finalize_question()
                cur_section = ParsedSection(index=len(self.sections), name=text, page_number=page,
                                            order_index=len(self.sections))
                self.sections.append(cur_section)
                pending = []
                continue

            if line.kind == "direction":
                finalize_question()
                finalize_context()
                rng = _directs_context(text)
                qs, qe = (rng if rng else (None, None))
                ctx = ParsedContext(
                    index=len(self.contexts),
                    context_type=_context_type_from_text(text),
                    label=_direction_label(text),
                    text="",
                    raw_text=text,
                    page_start=page, page_end=page,
                    q_start=qs, q_end=qe,
                )
                self.contexts.append(ctx)
                cur_context = ctx
                ctx_lines = [(page, line)]
                pending = []
                continue

            # body line
            m = _is_question_line(line, left_margin)
            if m:
                number = int(m.group(1))
                finalize_question()
                order += 1
                cur_q = _QAcc(number=number, number_raw=m.group(0).strip(),
                              page_number=page, order_index=order)
                cur_q.section_index = cur_section.index if cur_section else None
                # preamble lines captured just before this marker belong to it
                cur_q.preamble = pending
                pending = []
                cur_q.lines.append((page, line))
                cur_q.marker_line_pos = 0
                marker_span = self._find_marker_span(line, m)
                if marker_span is not None:
                    cur_q.marker_span_bbox = marker_span.bbox
                    cur_q.marker_text = marker_span.text
                # link to context by range
                if cur_context is not None and in_range(number, cur_context):
                    cur_q.context_index = cur_context.index
                continue

            if cur_q is not None:
                # Preamble for the NEXT question? (math row / superscript above
                # the next marker, outside the current option block)
                nxt = _next_anchor(anchor_set, i)
                if (nxt is not None and nxt - i <= 2 and looks_math_line(line)
                        and _below_current_options(line, cur_q)):
                    pending.append((page, line))
                    continue
                cur_q.lines.append((page, line))
                continue

            if cur_context is not None:
                if looks_math_line(line):
                    # formula rows above an upcoming question number
                    pending.append((page, line))
                else:
                    ctx_lines.append((page, line))
                continue

            pending.append((page, line))

        finalize_question()
        finalize_context()

        self._link_orphan_questions_to_contexts()
        self._assign_section_ranges()
        self._flag_numbering_issues()
        return self.sections, self.contexts, self.questions

    # ------------------------------------------------------------------
    def _left_margin(self) -> float:
        xs = []
        for layout in self.layouts:
            for line in layout.lines:
                if line.kind == "body":
                    xs.append(line.x0)
        return min(xs) if xs else 55.0

    def _find_marker_span(self, line: Line, m: re.Match):
        for s in sorted(line.spans, key=lambda s: s.x0):
            if s.x0 <= line.x0 + 3 and s.text.strip():
                return s
        return None

    def _build_question(self, acc: _QAcc) -> Optional[ParsedQuestion]:
        lines = [l for _, l in acc.lines]
        # find the first option line (options may share a line with the stem)
        options, first_opt = extract_options(lines)
        stem_lines = lines[:first_opt] if first_opt else lines
        stem_parts = [self._line_stem_text(l, acc) for l in stem_lines]
        stem_parts = [p for p in stem_parts if p]
        preamble_text = _join_lines(acc.preamble)

        is_math = any(looks_math_line(l) for l in stem_lines) or any(
            looks_math_line(l) for _, l in acc.preamble)
        if not is_math:
            probe = " ".join([self._line_stem_text(l, acc) for l in stem_lines]
                             + [l.text() for _, l in acc.preamble])
            is_math = looks_arithmetic(probe)

        stem_text = " ".join(stem_parts).strip()
        if preamble_text:
            stem_text = (preamble_text + " " + stem_text).strip()

        quality: list[str] = []
        asset = None
        math_block = None
        math_record: Optional[dict] = None
        if is_math:
            base_font = _dominant_size(stem_lines) or config.DEFAULT_BODY_FONT_SIZE
            all_stem_lines = [l for _, l in acc.preamble] + stem_lines
            drawings = self._drawings_for(acc.page_number)
            box = _union_bbox([l.bbox for l in all_stem_lines])
            math_block = math_layout.reconstruct(all_stem_lines, drawings, base_font, bbox=box)
            quality.append("math_reconstructed")
            if math_block.uncertain:
                quality.append("math_layout_uncertain")
            method = "pymupdf-math-reconstruct"
            math_record = {
                "linear": _strip_leading_number(math_block.linear),
                "visual_lines": math_block.visual_lines,
                "uncertain": math_block.uncertain,
                "has_fractions": math_block.has_fractions,
                "has_radicals": math_block.has_radicals,
                "has_superscripts": math_block.has_superscripts,
                "has_big_parens": math_block.has_big_parens,
                "notes": math_block.notes + [
                    "Reconstruction is heuristic; the source crop is authoritative."],
                "verified": False,
            }
        else:
            method = config.EXTRACTION_METHOD_DIGITAL

        if not options:
            quality.append("no_options_found")
        else:
            idxs = sorted(o.index for o in options)
            if idxs != list(range(1, len(idxs) + 1)):
                quality.append("non_contiguous_options")

        # raw (immutable) extraction of the statement only; options keep their
        # own raw_text. This is what "raw extraction vs corrected text" means.
        stem_line_set = set(id(l) for l in stem_lines)
        raw_stem_lines = list(acc.preamble) + [(p, l) for p, l in acc.lines if id(l) in stem_line_set]
        raw = _join_lines(raw_stem_lines)

        page_end = max(p for p, _ in acc.lines) if acc.lines else acc.page_number
        bbox = _union_bbox([l.bbox for _, l in acc.lines] + [l.bbox for _, l in acc.preamble]) \
            if (acc.lines or acc.preamble) else None

        q = ParsedQuestion(
            number=acc.number,
            number_raw=acc.number_raw,
            page_number=acc.page_number,
            page_end=page_end,
            order_index=acc.order_index,
            stem=stem_text,
            raw_text=raw,
            options=options,
            bbox=bbox,
            context_index=acc.context_index,
            section_index=acc.section_index,
            is_mcq=bool(options),
            is_math=is_math,
            math=math_record,
            quality_flags=quality,
            needs_review=True,
        )
        return q

    def _line_stem_text(self, line: Line, acc: _QAcc) -> str:
        text = line.text()
        # strip the leading question number token if present on this line
        text = re.sub(config.QUESTION_NUMBER_RE, "", text, count=1).strip()
        return text

    def _drawings_for(self, page_number: int):
        for layout in self.layouts:
            if layout.page_number == page_number:
                return layout.drawings
        return []

    # ------------------------------------------------------------------
    def _link_orphan_questions_to_contexts(self) -> None:
        """Give every question its best context, even if not set at anchor time.

        A question that crossed a page boundary or appeared before its range was
        parsed still gets a deterministic, most-specific context link.
        """
        if not self.contexts:
            return
        for q in self.questions:
            if q.context_index is not None or q.number is None:
                continue
            idx = best_context_for(q.number, self.contexts)
            if idx is not None:
                q.context_index = idx

    def _assign_section_ranges(self) -> None:
        if not self.sections:
            return
        # order sections by their first question
        for q in self.questions:
            if q.section_index is not None and 0 <= q.section_index < len(self.sections):
                sec = self.sections[q.section_index]
                nums = [qq.number for qq in self.questions
                        if qq.section_index == q.section_index and qq.number is not None]
                if nums:
                    sec.start_question = min(nums)
                    sec.end_question = max(nums)

    def _flag_numbering_issues(self) -> None:
        nums = [q.number for q in self.questions if q.number is not None]
        if not nums:
            return
        seen: dict[int, int] = {}
        for q in self.questions:
            if q.number is None:
                continue
            seen[q.number] = seen.get(q.number, 0) + 1
        duplicates = {n for n, c in seen.items() if c > 1}
        expected = set(range(min(nums), max(nums) + 1))
        missing = sorted(expected - set(nums))
        for q in self.questions:
            if q.number in duplicates:
                q.quality_flags.append("duplicate_number")
            if q.number is None:
                q.quality_flags.append("unidentified_number")
        self._missing_numbers = missing
        self._duplicate_numbers = sorted(duplicates)


# ---------------------------------------------------------------------------
def _join_lines(lines: list[tuple[int, Line]]) -> str:
    return re.sub(r"\s+", " ", " ".join(l.text() for _, l in lines)).strip()


def _exact_line_text(line: Line) -> str:
    """Line text with internal span spacing preserved (no whitespace collapse)."""
    return line.text().rstrip()


def _union_bbox(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _next_anchor(anchor_set: set[int], i: int) -> Optional[int]:
    for j in range(i + 1, i + 4):
        if j in anchor_set:
            return j
    return None


def _below_current_options(line: Line, acc: _QAcc) -> bool:
    if not acc.lines:
        return True
    last_y = max(l.y1 for _, l in acc.lines)
    return line.y0 > last_y - 2


def _in_range(number: int, ctx: ParsedContext) -> bool:
    return in_range(number, ctx)


def _direction_label(text: str) -> str:
    m = _DIR_RE.match(text)
    if m:
        return f"Direction ({m.group(1)}-{m.group(2)})"
    return "Direction"


def _dominant_size(lines: list[Line]) -> float:
    counts: dict[float, int] = {}
    for line in lines:
        for s in line.spans:
            if s.size >= config.LAYOUT.watermark_min_font_size:
                continue
            key = round(s.size, 1)
            counts[key] = counts.get(key, 0) + len(s.text)
    if not counts:
        return config.DEFAULT_BODY_FONT_SIZE
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _strip_leading_number(text: str) -> str:
    return re.sub(r"^\s*\d{1,3}\s*[\.\)]\s*", "", text or "").strip()
