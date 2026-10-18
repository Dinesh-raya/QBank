"""Direct PDF extraction with PyMuPDF.

Produces coordinate-rich primitives (``Span``/``Line``/drawing info) rather than
naive top-to-bottom text, because the reference papers use 2D layouts (stacked
fractions, columned options, side-by-side conclusions) where text-order output
is wrong. Symbol-font glyphs are decoded here so callers never see PUA garbage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pymupdf

from .. import config
from ..models import Line, Span


@dataclass
class DrawingInfo:
    kind: str                          # 'line' | 'fill'
    bbox: tuple[float, float, float, float]
    item_count: int = 0


@dataclass
class RawPage:
    page_number: int
    width: float
    height: float
    rotation: int
    spans: list[Span] = field(default_factory=list)
    drawings: list[DrawingInfo] = field(default_factory=list)
    images: list[tuple] = field(default_factory=list)
    raw_text: str = ""


class PdfExtractionError(RuntimeError):
    pass


def open_pdf(path: Path) -> "pymupdf.Document":
    try:
        return pymupdf.open(str(path))
    except Exception as exc:  # corrupt / encrypted / unsupported
        raise PdfExtractionError(f"Could not open PDF {path.name}: {exc}") from exc


def _span_from_dict(s: dict) -> Span:
    raw = s.get("text", "")
    decoded = config.decode_symbol_text(raw, s.get("font", ""))
    return Span(
        text=decoded,
        font=s.get("font", ""),
        size=float(s.get("size", 0.0)),
        bbox=tuple(float(v) for v in s.get("bbox", (0, 0, 0, 0))),
        raw_text=raw,
        flags=int(s.get("flags", 0)),
    )


def extract_raw_page(page: "pymupdf.Page", page_number: int) -> RawPage:
    """Extract spans, drawings and images from a single page."""
    rect = page.rect
    rp = RawPage(
        page_number=page_number,
        width=float(rect.width),
        height=float(rect.height),
        rotation=int(page.rotation),
        raw_text=page.get_text("text"),
    )

    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:  # not a text block
            continue
        for line in block.get("lines", []):
            for s in line.get("spans", []):
                if s.get("text", "") == "":
                    continue
                rp.spans.append(_span_from_dict(s))

    for d in page.get_drawings():
        try:
            r = d["rect"]
            bbox = (float(r.x0), float(r.y0), float(r.x1), float(r.y1))
        except Exception:
            continue
        kind = "fill" if d.get("type") == "f" else "line"
        rp.drawings.append(DrawingInfo(kind=kind, bbox=bbox, item_count=len(d.get("items", []))))

    for img in page.get_images(full=True):
        rp.images.append(tuple(img))

    return rp


def group_spans_into_lines(
    spans: list[Span], page_number: int, y_tolerance: Optional[float] = None
) -> list[Line]:
    """Group spans that share a baseline into visual ``Line`` objects.

    Lines are returned in reading order (top-to-bottom, then left-to-right).
    Spans whose text is only whitespace are ignored.
    """
    tol = config.LAYOUT.line_y_tolerance if y_tolerance is None else y_tolerance
    # Ignore spans that carry no printable content; keep everything else
    # verbatim (including lone symbols) so nothing is lost.
    usable = [s for s in spans if s.text != "" and s.text.strip() != ""]

    # greedy clustering by vertical overlap of the baseline band
    usable.sort(key=lambda s: (s.y0, s.x0))
    clusters: list[list[Span]] = []
    for s in usable:
        placed = False
        for cluster in clusters:
            ref = cluster[0]
            if abs(s.y0 - ref.y0) <= tol or (s.y0 <= ref.y1 - 1 and s.y1 >= ref.y0 + 1):
                cluster.append(s)
                placed = True
                break
        if not placed:
            clusters.append([s])

    lines: list[Line] = []
    for cluster in clusters:
        cluster.sort(key=lambda s: s.x0)
        x0 = min(s.x0 for s in cluster)
        y0 = min(s.y0 for s in cluster)
        x1 = max(s.x1 for s in cluster)
        y1 = max(s.y1 for s in cluster)
        lines.append(Line(page_number=page_number, bbox=(x0, y0, x1, y1), spans=cluster))
    lines.sort(key=lambda l: (round(l.y0, 1), l.x0))
    return lines


def render_page_png(page: "pymupdf.Page", out_path: Path, dpi: Optional[int] = None) -> Path:
    dpi = dpi or config.LAYOUT.render_dpi
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix = page.get_pixmap(dpi=dpi)
    pix.save(str(out_path))
    return out_path


def render_region_png(
    page: "pymupdf.Page",
    bbox: tuple[float, float, float, float],
    out_path: Path,
    *,
    dpi: Optional[int] = None,
    padding: Optional[float] = None,
) -> Path:
    """Render a cropped region of a page (clamped to the page rectangle)."""
    dpi = dpi or config.LAYOUT.render_dpi
    padding = config.LAYOUT.crop_padding if padding is None else padding
    page_rect = page.rect
    clip = pymupdf.Rect(
        max(bbox[0] - padding, page_rect.x0),
        max(bbox[1] - padding, page_rect.y0),
        min(bbox[2] + padding, page_rect.x1),
        min(bbox[3] + padding, page_rect.y1),
    )
    if clip.is_empty:
        clip = pymupdf.Rect(bbox)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    pix.save(str(out_path))
    return out_path
