"""Structural / layout analysis.

Turns raw page primitives into classified ``Line``s and detects visual regions
(tables, graphs, answer-key blocks). Noise handling is evidence-based:

* decorative text is identified by font size (watermark) — not by phrase;
* running headers/footers are identified by *repeated position AND repeated
  text across pages*, so a phrase that legitimately appears in many questions is
  never globally deleted;
* page numbers are digits drawn near the bottom centre, often inside an oval.

No line is ever dropped from the page entirely: noise lines are moved to
``PageLayout.noise_lines`` (and the raw text is always kept separately) so a user
can investigate any cleanup decision.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .. import config
from ..models import Line, PageLayout, Region
from .page_inspector import PageInspection
from .pdf_extractor import RawPage

_DIGITS_RE = re.compile(r"^\s*\d{1,3}\s*$")
_SECTION_STOPWORDS = {"A", "I", "II", "III", "IV", "V", "X"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _font_family(font: str) -> str:
    """Reduce a font name to a family key, e.g. 'BookmanOldStyle-Bold' -> 'bookmanoldstyle'."""
    return re.split(r"[-+]", font.strip().lower())[0]


def _sort_numeric(values: list[str]) -> list[str]:
    def key(v: str) -> float:
        try:
            return float(v)
        except ValueError:
            return float("inf")
    return sorted(set(values), key=key)


_MATH_OP_CHARS = "=+\u2212\u00d7\u00f7\u221a^<>%/"
_NUMERIC_ONLY = re.compile(r"^[\d\s\.\,\-\u2212/()]+$")


def _looks_math_shaped(text: str) -> bool:
    """True for numeric/operator lines (equation tokens), not word labels."""
    if not text or not any(c.isdigit() for c in text):
        return False
    if any(c in text for c in _MATH_OP_CHARS):
        return True
    return bool(_NUMERIC_ONLY.match(text.strip()))


def _inside_bbox(line: Line, bbox: tuple[float, float, float, float], pad: float = 2.0) -> bool:
    cx = (line.x0 + line.x1) / 2
    cy = (line.y0 + line.y1) / 2
    return (bbox[0] - pad <= cx <= bbox[2] + pad
            and bbox[1] - pad <= cy <= bbox[3] + pad)


@dataclass
class DocumentNoise:
    header_signatures: set[str] = field(default_factory=set)
    footer_signatures: set[str] = field(default_factory=set)
    watermark_signatures: set[str] = field(default_factory=set)


class LayoutAnalyzer:
    def __init__(self, raw_pages: list[RawPage], inspections: list[PageInspection]):
        self.raw_pages = raw_pages
        self.inspections = inspections
        self.page_count = len(raw_pages)
        self.noise = DocumentNoise()
        self._page_objs: dict[int, RawPage] = {rp.page_number: rp for rp in raw_pages}

    # -- public ---------------------------------------------------------------
    def analyse(self) -> list[PageLayout]:
        layouts: list[PageLayout] = []
        for raw, insp in zip(self.raw_pages, self.inspections):
            layouts.append(self._analyse_page(raw, insp))
        self._detect_document_noise(layouts)
        for layout in layouts:
            self._finalise_noise(layout)
        return layouts

    # -- per page -------------------------------------------------------------
    def _analyse_page(self, raw: RawPage, insp: PageInspection) -> PageLayout:
        layout = PageLayout(
            page_number=raw.page_number,
            width=raw.width,
            height=raw.height,
            rotation=raw.rotation,
            body_font_size=insp.body_font_size,
            raw_text=raw.raw_text,
            page_type=insp.page_type,
            warnings=list(insp.warnings),
            drawings=list(raw.drawings),
        )
        from .pdf_extractor import group_spans_into_lines

        # Split watermark/branding spans out *before* line grouping: a 90–212 pt
        # glyph has a huge bounding box that would otherwise glue every line it
        # overlaps (and corrupt the left margin used for question detection).
        body_spans = [s for s in raw.spans if s.size < config.LAYOUT.watermark_min_font_size]
        big_spans = [s for s in raw.spans if s.size >= config.LAYOUT.watermark_min_font_size]

        lines = group_spans_into_lines(body_spans, raw.page_number)
        watermark_lines = group_spans_into_lines(big_spans, raw.page_number, y_tolerance=40.0)
        for wl in watermark_lines:
            wl.kind = "watermark"

        header_y = raw.height * config.LAYOUT.header_band_fraction
        footer_y = raw.height * (1.0 - config.LAYOUT.footer_band_fraction)
        center_x = raw.width / 2.0

        body_fonts = self._dominant_fonts(raw)
        figure_fonts = self._figure_fonts(raw, body_fonts)
        heading_sizes = self._heading_sizes(raw, insp.body_font_size)

        for line in lines:
            self._classify_line(line, raw, insp, header_y, footer_y, center_x,
                                body_fonts, figure_fonts, heading_sizes)
            layout.lines.append(line)
        layout.lines.extend(watermark_lines)
        layout.lines.sort(key=lambda l: (round(l.y0, 1), l.x0))

        layout.regions = self._detect_regions(raw, layout, figure_fonts)
        self._rescue_math_lines(layout)
        return layout

    def _rescue_math_lines(self, layout: PageLayout) -> None:
        """Reclassify formula lines that font-matching mistook for figure text.

        Table and graph labels share the same fonts as equation tokens in the
        reference paper, so a font-only rule would drop Q68–80 entirely. Any
        math-shaped line *outside* a table/graph region is real question content.
        """
        guard = [r.bbox for r in layout.regions if r.kind in ("table", "graph")]
        for line in layout.lines:
            if line.kind != "figure_text":
                continue
            if any(_inside_bbox(line, b) for b in guard):
                continue
            if _looks_math_shaped(line.text()):
                line.kind = "body"

    # -- helpers --------------------------------------------------------------
    def _dominant_fonts(self, raw: RawPage) -> set[str]:
        counts: Counter[str] = Counter()
        for s in raw.spans:
            if s.size >= config.LAYOUT.watermark_min_font_size:
                continue
            counts[_font_family(s.font)] += len(s.text)
        if not counts:
            return {"bookmanoldstyle"}
        top = counts.most_common(1)[0][1]
        # families with at least 25% of the dominant family's characters
        return {fam for fam, n in counts.items() if n >= 0.25 * top}

    def _figure_fonts(self, raw: RawPage, body_fonts: set[str]) -> set[str]:
        """Font families used by axis/table labels (not body, not noise)."""
        counts: Counter[str] = Counter()
        for s in raw.spans:
            if s.size >= config.LAYOUT.watermark_min_font_size:
                continue
            counts[_font_family(s.font)] += len(s.text)
        return {fam for fam in counts if fam not in body_fonts}

    def _heading_sizes(self, raw: RawPage, body_font: float) -> set[float]:
        sizes = {round(s.size, 1) for s in raw.spans
                 if s.size >= body_font + config.SECTION_FONT_SIZE_MARGIN
                 and s.size < config.LAYOUT.watermark_min_font_size}
        return sizes

    def _classify_line(self, line: Line, raw: RawPage, insp: PageInspection,
                       header_y: float, footer_y: float, center_x: float,
                       body_fonts: set[str], figure_fonts: set[str],
                       heading_sizes: set[float]) -> None:
        text = line.text()
        plain = text.strip()
        if not text:
            line.kind = "noise"
            return

        # 1) watermark: every meaningful span is huge.
        big = [s for s in line.spans if s.size >= config.LAYOUT.watermark_min_font_size]
        if big and sum(len(s.text) for s in big) >= 0.6 * sum(len(s.text) for s in line.spans):
            line.kind = "watermark"
            return

        # 2) header / footer bands
        if line.y0 < header_y:
            line.kind = "header"
            return
        if line.y0 > footer_y:
            if _DIGITS_RE.match(text):
                line.kind = "page_number"
            else:
                line.kind = "footer"
            return

        # 3) answer-key block (monospaced question.option pairs) and decorative labels
        fams = Counter()
        for s in line.spans:
            fams[_font_family(s.font)] += len(s.text)
        # Membership must be a substring test: the actual family key for the
        # reference key font is "couriernewps", not "couriernew".
        has_mono = any("courier" in f for f in fams)
        if has_mono and len(re.findall(r"\d{1,3}\s*[\.\)]\s*[1-9A-Ea-e]\b", text)) >= 3:
            line.kind = "key"
            return
        if plain.upper() == "KEY":
            line.kind = "key"
            return
        if any("arial" in f for f in fams) and not any(fam in body_fonts for fam in fams):
            line.kind = "decorative"   # e.g. "SCAN QR FOR OUR RESULTS"
            return

        # 4) figure text (axis/table labels)
        if fams and all(fam in figure_fonts for fam in fams):
            line.kind = "figure_text"
            return

        # 5) section heading
        letters = [c for c in plain if c.isalpha()]
        is_caps = bool(letters) and all(c.isupper() for c in letters)
        max_size = max((s.size for s in line.spans), default=0.0)
        known = plain.upper() in config.KNOWN_SECTION_NAMES
        if known or (
            is_caps
            and len(plain) <= 45
            and len(plain.split()) <= 6
            and round(max_size, 1) in heading_sizes
            and plain.upper() not in _SECTION_STOPWORDS
        ):
            line.kind = "heading"
            return

        # 6) direction / instruction block
        if re.match(config.DIRECTION_RE, plain) or re.match(r"^direction", plain.lower()):
            line.kind = "direction"
            return

        line.kind = "body"

    # -- regions --------------------------------------------------------------
    def _detect_regions(self, raw: RawPage, layout: PageLayout,
                        figure_fonts: set[str]) -> list[Region]:
        regions: list[Region] = []

        # Collect figure_text lines and cluster vertically adjacent ones.
        fig_lines = [l for l in layout.lines if l.kind == "figure_text"]
        if fig_lines:
            fig_lines.sort(key=lambda l: l.y0)
            cluster: list[Line] = [fig_lines[0]]
            clusters: list[list[Line]] = []
            for l in fig_lines[1:]:
                if l.y0 - cluster[-1].y1 <= 3 * layout.body_font_size:
                    cluster.append(l)
                else:
                    clusters.append(cluster)
                    cluster = [l]
            clusters.append(cluster)

            for cl in clusters:
                x0 = min(l.x0 for l in cl)
                y0 = min(l.y0 for l in cl)
                x1 = max(l.x1 for l in cl)
                y1 = max(l.y1 for l in cl)
                bbox = (x0, y0, x1, y1)
                # extend to include nearby drawings (the graph/table body)
                bbox = self._extend_with_drawings(raw, bbox)
                kind = self._guess_region_kind(layout, cl)
                structured = {}
                if kind == "table":
                    structured = self._parse_table(layout, bbox)
                elif kind == "graph":
                    structured = self._parse_graph_labels(cl)
                regions.append(Region(kind=kind, page_number=raw.page_number,
                                      bbox=bbox, structured=structured))
        return regions

    def _extend_with_drawings(self, raw: RawPage,
                              bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = bbox
        pad = 6.0
        near = [d for d in raw.drawings
                if d.bbox[0] >= x0 - 90 and d.bbox[2] <= x1 + 90
                and d.bbox[1] >= y0 - 60 and d.bbox[3] <= y1 + 60]
        for d in near:
            x0 = min(x0, d.bbox[0]); y0 = min(y0, d.bbox[1])
            x1 = max(x1, d.bbox[2]); y1 = max(y1, d.bbox[3])
        return (x0 - pad, y0 - pad, x1 + pad, y1 + pad)

    def _guess_region_kind(self, layout: PageLayout, cl: list[Line]) -> str:
        # Find the nearest preceding direction text on this page.
        direction_text = ""
        for l in layout.lines:
            if l.y0 >= cl[0].y0:
                break
            if l.kind == "direction":
                direction_text = l.text().lower()
        blob = (" ".join(l.text() for l in cl) + " " + direction_text).lower()
        if any(w in blob for w in ("graph", "chart", "pie", "bar", "line graph")):
            return "graph"
        if any(w in blob for w in ("table", "tabulated")):
            return "table"
        # Fallback: many numeric labels -> table-ish, else figure.
        nums = sum(1 for l in cl for t in l.text().split() if t.replace(".", "").isdigit())
        return "table" if nums >= 6 else "figure"

    def _parse_table(self, layout: PageLayout,
                     bbox: tuple[float, float, float, float]) -> dict:
        """Extract a structured grid from figure/text tokens inside *bbox*."""
        x0, y0, x1, y1 = bbox
        tokens: list[tuple[float, float, str]] = []
        for line in layout.lines:
            if line.kind not in ("figure_text", "body", "table"):
                continue
            if not (y0 <= line.y0 <= y1 and x0 - 2 <= line.x0 <= x1 + 2):
                continue
            for s in line.spans:
                t = s.text.strip()
                if t:
                    tokens.append((s.x0, s.y0, t))
        if not tokens:
            return {}

        # group into rows by y
        tokens.sort(key=lambda t: (round(t[1], 1), t[0]))
        rows: list[list[tuple[float, float, str]]] = []
        for tok in tokens:
            if rows and abs(tok[1] - rows[-1][0][1]) <= 6:
                rows[-1].append(tok)
            else:
                rows.append([tok])
        # group columns by x-centre clustering across all rows
        xs = sorted(t[0] for t in tokens)
        col_centers: list[float] = []
        for x in xs:
            if not col_centers or x - col_centers[-1] > 25:
                col_centers.append(x)
            else:
                col_centers[-1] = (col_centers[-1] + x) / 2

        grid: list[list[str]] = []
        for row in rows:
            row.sort(key=lambda t: t[0])
            cells = ["" for _ in col_centers]
            for x, _, txt in row:
                # nearest column centre
                idx = min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - x))
                cells[idx] = (cells[idx] + " " + txt).strip()
            grid.append(cells)
        return {"columns": len(col_centers), "rows": grid}

    def _parse_graph_labels(self, cl: list[Line]) -> dict:
        labels = [l.text() for l in cl]
        numbers = []
        categories = []
        for l in cl:
            for s in l.spans:
                t = s.text.strip()
                if t.replace(".", "", 1).isdigit():
                    numbers.append(t)
                elif len(t) == 1 and t.isalpha():
                    categories.append(t)
        return {
            "axis_labels": labels,
            "numeric_labels": _sort_numeric(numbers),
            "category_labels": categories,
            "data_values_verified": False,
            "note": "Values are read visually from the graph; underlying data is not machine-readable.",
        }

    # -- document-level noise -------------------------------------------------
    def _detect_document_noise(self, layouts: list[PageLayout]) -> None:
        if self.page_count < 2:
            return
        header_sigs: Counter[str] = Counter()
        footer_sigs: Counter[str] = Counter()
        for layout in layouts:
            for line in layout.lines:
                if line.kind == "header":
                    header_sigs[_norm(line.text())] += 1
                elif line.kind == "footer":
                    footer_sigs[_norm(line.text())] += 1
        threshold = max(2, int(0.6 * self.page_count))
        self.noise.header_signatures = {s for s, n in header_sigs.items() if n >= threshold}
        self.noise.footer_signatures = {s for s, n in footer_sigs.items() if n >= threshold}

    def _finalise_noise(self, layout: PageLayout) -> None:
        """Move confirmed noise lines into ``noise_lines`` and tag the rest.

        A header/footer that is *not* a document-wide repeated signature is not
        noise: e.g. a ``Direction`` block that happens to sit in the top band.
        Those lines are reclassified as body so segmentation still sees them.
        """
        kept: list[Line] = []
        for line in layout.lines:
            if line.kind in ("watermark", "page_number"):
                layout.noise_lines.append(line)
                continue
            if line.kind == "header" and _norm(line.text()) in self.noise.header_signatures:
                layout.noise_lines.append(line)
                continue
            if line.kind == "footer" and _norm(line.text()) in self.noise.footer_signatures:
                layout.noise_lines.append(line)
                continue
            if line.kind in ("header", "footer"):
                line.kind = "body"
            if line.kind == "decorative":
                layout.noise_lines.append(line)
                continue
            kept.append(line)
        layout.lines = kept
