"""Linking questions to their shared context (passage / puzzle / table / graph).

Shared material is stored *once* as a context record; every question that
depends on it stores only a reference. The linking rules are deliberately
small and pure so they can be unit-tested without a PDF:

1. A ``Direction (a-b)`` block opens a context with an explicit question range.
   A question links to the context whose range contains its number. When ranges
   overlap, the *narrowest* containing range wins (most specific stimulus).
2. A question that has no explicit range link, but sits physically after a
   context on the same page and before the next context, links to that nearest
   preceding context (best-effort, always flagged for review elsewhere).
3. Region linkage attaches the first visual region (table / graph) found at or
   below the direction line to the context, so a graph referenced by six
   questions is stored once and referenced by all six.
"""
from __future__ import annotations

from typing import Iterable, Optional

from ..models import Line, ParsedContext, Region


def in_range(number: int, ctx: ParsedContext) -> bool:
    """True when *number* falls inside the context's declared range.

    A context without a range (a bare ``Direction``) accepts any number, which
    keeps open-ended instruction blocks attached to the questions that follow.
    """
    if ctx.q_start is None or ctx.q_end is None:
        return True
    return ctx.q_start <= number <= ctx.q_end


def range_span(ctx: ParsedContext) -> Optional[int]:
    if ctx.q_start is None or ctx.q_end is None:
        return None
    return ctx.q_end - ctx.q_start


def best_context_for(number: int, contexts: Iterable[ParsedContext]) -> Optional[int]:
    """Return the index of the most specific context containing *number*.

    Prefers the narrowest explicit range; falls back to the last open-ended
    context only when no ranged context matches.
    """
    matches = [c for c in contexts if in_range(number, c)]
    if not matches:
        return None
    ranged = [c for c in matches if range_span(c) is not None]
    if ranged:
        return min(ranged, key=lambda c: range_span(c)).index  # type: ignore[arg-type]
    return matches[-1].index


def find_shared_region(ctx: ParsedContext,
                       ctx_lines: list[tuple[int, Line]],
                       regions_by_page: dict[int, list[Region]],
                       kinds: tuple[str, ...] = ("table", "graph")) -> dict:
    """Return a structured descriptor of the region belonging to *ctx*.

    Searches the context's pages for the first *meaningful* region (table or
    graph) whose top is at or below the direction line, so a table/graph printed
    under the instruction block is attached to the context (and therefore to
    every linked question). Formula/figure fragments are not treated as shared
    stimuli — each formula keeps its own per-question crop instead.
    """
    if not ctx_lines:
        return {}
    direction_y = ctx_lines[0][1].y0
    pages = range(ctx.page_start, ctx.page_end + 1)
    for p in pages:
        for region in regions_by_page.get(p, []):
            if region.kind not in kinds:
                continue
            if region.bbox[1] >= direction_y - 5:
                return {
                    "region_kind": region.kind,
                    "region_page": region.page_number,
                    "region_bbox": list(region.bbox),
                    "structured": region.structured,
                }
    return {}
