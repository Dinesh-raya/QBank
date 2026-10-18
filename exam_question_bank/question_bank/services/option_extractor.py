"""Option extraction.

Options in these papers are laid out inconsistently, so we locate every
``N)`` marker by coordinates and attach text to it rather than assuming one
option per line. Supported layouts include:

* five options in a single row;
* two columns (``1)``/``2)`` on one line, ``3)``/``4)`` on the next, ``5)`` last);
* several options merged inside one span (``4) ... 5) ...``);
* an option whose value is a stacked fraction (``33 1/3`` rendered as 33 then
  numerator/denominator) — re-joined as ``33 1/3``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .. import config
from ..models import Line, ParsedOption

_MARKER_RE = config.OPTION_MARKER_RE


@dataclass
class _Frag:
    x: float
    y: float
    x1: float
    text: str
    has_marker: bool = False
    marker_index: Optional[int] = None
    line_i: int = 0


@dataclass
class _Marker:
    index: int
    x: float
    y: float
    line_i: int


def _span_segments(span) -> list[tuple[Optional[int], str, float, float]]:
    """Split a span into (marker_index_or_None, text, x0, x1) pieces."""
    text = span.text
    out: list[tuple[Optional[int], str, float, float]] = []
    if not text:
        return out
    n = max(len(text), 1)
    last = 0
    for m in _iter_markers(text):
        start, end, idx = m
        if start > last:
            piece = text[last:start]
            out.append((None, piece, span.x0 + span.width * last / n,
                        span.x0 + span.width * start / n))
        out.append((idx, text[start:end], span.x0 + span.width * start / n,
                    span.x0 + span.width * end / n))
        last = end
    if last < len(text):
        out.append((None, text[last:], span.x0 + span.width * last / n, span.x1))
    return out


def _iter_markers(text: str):
    import re
    for m in re.finditer(r"(?:^|(?<=\s)|(?<=[a-z\)\]\.]))([1-9])\)\s?", text, flags=re.IGNORECASE):
        yield m.start(), m.end(), int(m.group(1))


def extract_options(lines: list[Line], base_font: float = config.DEFAULT_BODY_FONT_SIZE) -> tuple[list[ParsedOption], int]:
    """Return (options, index of the first option line) for a question's lines.

    Lines before the returned index belong to the question stem.
    """
    markers: list[_Marker] = []
    frags: list[_Frag] = []
    first_opt_line = -1

    for li, line in enumerate(lines):
        spans = sorted(line.spans, key=lambda s: s.x0)
        current: Optional[int] = None
        line_has_marker = False
        for span in spans:
            for idx, text, x0, x1 in _span_segments(span):
                if idx is not None:
                    line_has_marker = True
                    current = idx
                    markers.append(_Marker(index=idx, x=x0, y=span.y0, line_i=li))
                    frags.append(_Frag(x=x0, y=span.y0, x1=span.x0 + span.width,
                                       text=_clean_marker_tail(text), has_marker=True,
                                       marker_index=idx, line_i=li))
                else:
                    frags.append(_Frag(x=x0, y=span.y0, x1=x1, text=text,
                                       has_marker=current is not None, marker_index=current,
                                       line_i=li))
        if line_has_marker and first_opt_line == -1:
            first_opt_line = li

    if first_opt_line == -1 or not markers:
        return [], len(lines)

    # Fragments on stem lines (above the first option line) are never options;
    # including them would let a formula row leak into an answer choice.
    frags = [f for f in frags if f.line_i >= first_opt_line]

    # Assign every fragment to an option index.
    marker_x_by_index = {m.index: [] for m in markers}
    for m in markers:
        marker_x_by_index[m.index].append(m.x)
    # Representative x for each option index = its markers' mean x.
    rep_x = {i: sum(xs) / len(xs) for i, xs in marker_x_by_index.items() if xs}

    grouped: dict[int, list[_Frag]] = {i: [] for i in rep_x}
    for f in frags:
        if f.marker_index is not None:
            grouped.setdefault(f.marker_index, []).append(f)
        elif f.text.strip():
            # orphan fragment (e.g. fraction numerator/denominator): nearest option by x
            idx = min(rep_x, key=lambda i: abs(rep_x[i] - f.x))
            grouped.setdefault(idx, []).append(f)

    options: list[ParsedOption] = []
    for idx in sorted(grouped):
        text = _assemble_option(grouped[idx])
        if not text:
            continue
        row_frags = sorted(grouped[idx], key=lambda f: (f.y, f.x))
        x0 = min(f.x for f in row_frags)
        x1 = max(f.x1 for f in row_frags)
        y0 = min(f.y for f in row_frags)
        y1 = max(f.y for f in row_frags)
        options.append(ParsedOption(
            index=idx,
            label=f"{idx})",
            text=text,
            raw_text=text,
            bbox=(x0, y0, x1, y1),
        ))
    return options, first_opt_line


def _clean_marker_tail(text: str) -> str:
    # text includes the marker, e.g. "3) " or "3)33"; strip the leading marker
    import re
    return re.sub(r"^\s*[1-9]\)\s*", "", text).strip()


def _assemble_option(frags: list[_Frag]) -> str:
    if not frags:
        return ""
    # Determine the marker row (nearest to a has_marker fragment's y).
    marker_ys = [f.y for f in frags if f.has_marker]
    marker_y = min(marker_ys) if marker_ys else min(f.y for f in frags)

    row_frags = sorted([f for f in frags if abs(f.y - marker_y) <= 4 and f.text.strip()],
                       key=lambda f: f.x)
    other = [f for f in frags if not (abs(f.y - marker_y) <= 4 and f.text.strip())]

    row_text = " ".join(f.text.strip() for f in row_frags if f.text.strip()).strip()

    # Stacked-fraction pairs among the remaining fragments.
    stacked = sorted([f for f in other if f.text.strip()], key=lambda f: (f.y, f.x))
    used = [False] * len(stacked)
    extras: list[str] = []
    for i in range(len(stacked)):
        if used[i]:
            continue
        a = stacked[i]
        cx_a = (a.x + a.x1) / 2
        for j in range(i + 1, len(stacked)):
            if used[j]:
                continue
            b = stacked[j]
            if not (6 <= (b.y - a.y) <= 30):
                continue
            cx_b = (b.x + b.x1) / 2
            if abs(cx_a - cx_b) <= 6 and _is_number(a.text) and _is_number(b.text):
                extras.append(f"{a.text.strip()}/{b.text.strip()}")
                used[i] = used[j] = True
                break
    for i, f in enumerate(stacked):
        if not used[i] and f.text.strip():
            extras.append(f.text.strip())

    parts = [p for p in [row_text] + extras if p]
    return " ".join(parts).strip()


def _is_number(t: str) -> bool:
    import re
    return bool(re.fullmatch(r"\d+(\.\d+)?", t.strip()))
