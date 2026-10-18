"""Typed intermediate representation used across the extraction pipeline.

These dataclasses are deliberately storage-agnostic: services produce and
consume them, and the repositories layer maps them to/from SQLite. Keeping the
IR explicit makes each pipeline stage independently testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Span:
    """A run of text with a single font/size and a bounding box (PDF points)."""

    text: str
    font: str
    size: float
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    raw_text: str = ""                       # before symbol decoding
    flags: int = 0

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


@dataclass
class Line:
    """A visual text line: one or more spans that share a baseline (y band)."""

    page_number: int
    bbox: tuple[float, float, float, float]
    spans: list[Span] = field(default_factory=list)
    kind: str = "body"          # body|header|footer|page_number|watermark|heading|direction|option|math|table|graph|key|caption|noise
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    def text(self, sep: str = " ") -> str:
        """Reading-order text of the line's spans, loosely joined.

        Adjacent spans that are directly contiguous are joined without an
        inserted separator so that text split mid-word ("18" + "th") reads
        correctly, while a visible horizontal gap inserts ``sep``.
        """
        parts: list[str] = []
        prev_x1: Optional[float] = None
        for s in sorted(self.spans, key=lambda s: s.x0):
            if s.text == "":
                continue
            if prev_x1 is not None:
                gap = s.x0 - prev_x1
                if gap > 1.2 and not parts[-1].endswith(" ") and not s.text.startswith(" "):
                    parts.append(sep)
            parts.append(s.text)
            prev_x1 = s.x1
        return "".join(parts).strip()


@dataclass
class PageLayout:
    """Result of analysing a single page."""

    page_number: int
    width: float
    height: float
    rotation: int
    body_font_size: float
    lines: list[Line] = field(default_factory=list)          # body + structural lines, reading order
    noise_lines: list[Line] = field(default_factory=list)     # header/footer/watermark/page-number
    regions: list["Region"] = field(default_factory=list)     # tables, graphs
    drawings: list[Any] = field(default_factory=list)         # DrawingInfo list (vector paths)
    raw_text: str = ""
    page_type: str = "digital"                                # digital|scanned|mixed
    warnings: list[str] = field(default_factory=list)

    def body_lines(self) -> list[Line]:
        return [l for l in self.lines if l.kind not in ("header", "footer", "page_number", "watermark")]


@dataclass
class Region:
    """A visual region (table / graph / figure) that must be preserved."""

    kind: str                                   # table|graph|figure|qr|formula
    page_number: int
    bbox: tuple[float, float, float, float]
    crop_path: Optional[str] = None
    structured: dict[str, Any] = field(default_factory=dict)
    verified: bool = False
    note: str = ""


@dataclass
class ParsedOption:
    index: int
    label: str
    text: str
    raw_text: str = ""
    bbox: Optional[tuple[float, float, float, float]] = None


@dataclass
class ParsedQuestion:
    number: Optional[int]
    number_raw: str
    page_number: int
    order_index: int
    stem: str
    raw_text: str
    options: list[ParsedOption] = field(default_factory=list)
    bbox: Optional[tuple[float, float, float, float]] = None
    context_index: Optional[int] = None
    section_index: Optional[int] = None
    is_mcq: bool = True
    is_math: bool = False
    asset_path: Optional[str] = None
    math: Optional[dict] = None
    quality_flags: list[str] = field(default_factory=list)
    needs_review: bool = False
    page_end: Optional[int] = None


@dataclass
class ParsedContext:
    index: int
    context_type: str
    label: str
    text: str
    raw_text: str
    page_start: int
    page_end: int
    q_start: Optional[int] = None
    q_end: Optional[int] = None
    bbox: Optional[tuple[float, float, float, float]] = None
    asset_path: Optional[str] = None
    structured: dict[str, Any] = field(default_factory=dict)
    verified: bool = False


@dataclass
class ParsedSection:
    index: int
    name: str
    page_number: int
    order_index: int
    start_question: Optional[int] = None
    end_question: Optional[int] = None


@dataclass
class ParsedAnswerKeyEntry:
    question_number: int
    option_index: Optional[int]
    answer_value: str
    page_number: int
    extraction_method: str
    raw_text: str
    match_status: str = "unmatched"   # matched|unmatched|missing|duplicate|invalid|ambiguous


@dataclass
class DocumentAnalysis:
    """Full result of analysing a document (pre-persistence)."""

    filename: str
    sha256: str
    path: str
    page_count: int
    page_layouts: list[PageLayout] = field(default_factory=list)
    sections: list[ParsedSection] = field(default_factory=list)
    contexts: list[ParsedContext] = field(default_factory=list)
    questions: list[ParsedQuestion] = field(default_factory=list)
    answer_key: list[ParsedAnswerKeyEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
