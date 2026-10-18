"""Answer-key extraction.

Handles the common compact forms:
* ``question.option`` pairs (``1.1 2.2 3.2 ...``) — the reference format;
* ``question) A`` / ``question. A`` letter keys;
* the same patterns spread across a line's spans (sorted by x first).

A missing answer stays missing: nothing is inferred just because one is
expected. Validation against extracted questions happens in the pipeline.
"""
from __future__ import annotations

import re

from .. import config
from ..models import Line, PageLayout, ParsedAnswerKeyEntry

_PAIR = re.compile(config.ANSWER_KEY_PAIR_RE)
_LETTER = re.compile(config.ANSWER_KEY_LETTER_RE)
_LETTER_TO_INDEX = {c: i + 1 for i, c in enumerate("ABCDE")}


def _key_line_text(line: Line) -> str:
    # join spans strictly by x to defeat any out-of-order span splitting
    return " ".join(s.text for s in sorted(line.spans, key=lambda s: s.x0))


def extract_answer_key(layouts: list[PageLayout]) -> list[ParsedAnswerKeyEntry]:
    entries: list[ParsedAnswerKeyEntry] = []
    seen: set[int] = set()
    for layout in layouts:
        for line in layout.lines:
            if line.kind != "key":
                continue
            text = _key_line_text(line)
            if re.fullmatch(r"\s*key\s*", text, flags=re.IGNORECASE):
                continue
            # letter form first (rare, but explicit)
            letter_hits = list(_LETTER.finditer(text))
            pair_hits = list(_PAIR.finditer(text))
            hits = pair_hits if len(pair_hits) >= len(letter_hits) else letter_hits
            for m in hits:
                q = int(m.group(1))
                if q in seen or not (1 <= q <= 500):
                    continue
                if m.re is _LETTER:
                    opt_idx = _LETTER_TO_INDEX.get(m.group(2).upper())
                    value = m.group(2).upper()
                else:
                    opt_idx = int(m.group(2))
                    value = m.group(2)
                seen.add(q)
                entries.append(ParsedAnswerKeyEntry(
                    question_number=q,
                    option_index=opt_idx,
                    answer_value=value,
                    page_number=layout.page_number,
                    extraction_method="pymupdf-key-parse",
                    raw_text=m.group(0),
                ))
    entries.sort(key=lambda e: e.question_number)
    return entries
