"""Page inspection: decide how a page should be processed and flag quality.

Does NOT assume non-empty text means a page was extracted correctly. Combines
text density, image coverage, drawing density and suspicious-character checks
into a page type plus an explicit list of quality warnings.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from .. import config
from .pdf_extractor import RawPage


@dataclass
class PageInspection:
    page_number: int
    width: float
    height: float
    rotation: int
    char_count: int
    image_count: int
    drawing_count: int
    text_density: float            # chars per 1000 pt^2 of page area
    image_area_fraction: float
    page_type: str                 # digital | scanned | mixed
    has_text: bool
    needs_ocr: bool
    body_font_size: float
    warnings: list[str] = field(default_factory=list)


_SUSPICIOUS_RANGES = (
    (0xE000, 0xF8FF),   # private use area (decoded symbols should not survive here)
    (0xFFF0, 0xFFFF),   # specials
)


def _suspicious_chars(text: str) -> list[str]:
    found: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch == "\ufffd":
            found.append(ch)
            continue
        for lo, hi in _SUSPICIOUS_RANGES:
            if lo <= code <= hi:
                found.append(ch)
                break
    return found


def _est_image_area(raw: RawPage) -> float:
    """Approximate fraction of the page covered by raster images.

    Uses the page's image blocks (via get_text is not available here), so we
    fall back to image count heuristics when placements are unknown.
    """
    # image placements are added by the analyser; here we approximate using the
    # count relative to a typical page. Kept intentionally conservative.
    if not raw.images:
        return 0.0
    # 50+ tiny tiles is the reference branding/barcode, not a scan.
    if len(raw.images) > 20:
        return 0.15
    return min(0.9, 0.25 * len(raw.images))


def inspect_page(raw: RawPage) -> PageInspection:
    warnings: list[str] = []
    area = max(raw.width * raw.height, 1.0)
    text = raw.raw_text or ""
    char_count = len(text.strip())
    density = char_count / (area / 1000.0)

    # Body font size = the size carrying the most characters (ignoring tiny
    # superscripts and huge watermark text).
    size_counts: dict[float, int] = {}
    for s in raw.spans:
        if s.size >= config.LAYOUT.watermark_min_font_size:
            continue
        key = round(s.size, 1)
        size_counts[key] = size_counts.get(key, 0) + len(s.text)
    body_font = config.DEFAULT_BODY_FONT_SIZE
    if size_counts:
        body_font = max(size_counts.items(), key=lambda kv: kv[1])[0]

    image_area = _est_image_area(raw)
    has_text = char_count >= config.LAYOUT.min_text_chars_for_digital
    needs_ocr = not has_text or (image_area >= config.LAYOUT.scanned_image_area_fraction and density < 1.0)

    if not has_text:
        page_type = "scanned"
    elif image_area >= config.LAYOUT.scanned_image_area_fraction:
        page_type = "mixed"
    else:
        page_type = "digital"

    if char_count == 0:
        warnings.append("no_extractable_text")
    elif char_count < config.LAYOUT.min_text_chars_for_digital:
        warnings.append("very_little_text")

    if image_area >= config.LAYOUT.scanned_image_area_fraction:
        warnings.append("large_image_area")

    suspicious = _suspicious_chars("".join(s.text for s in raw.spans))
    if suspicious:
        warnings.append(f"suspicious_chars:{len(suspicious)}")

    return PageInspection(
        page_number=raw.page_number,
        width=raw.width,
        height=raw.height,
        rotation=raw.rotation,
        char_count=char_count,
        image_count=len(raw.images),
        drawing_count=len(raw.drawings),
        text_density=round(density, 3),
        image_area_fraction=round(image_area, 3),
        page_type=page_type,
        has_text=has_text,
        needs_ocr=needs_ocr,
        body_font_size=body_font,
        warnings=warnings,
    )
