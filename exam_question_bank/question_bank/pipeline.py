"""End-to-end processing pipeline.

Orchestrates the independently-testable services in the order required by the
master prompt, and is the single entry point both the CLI/scripts and the
Streamlit app call:

    ingest → inspect → extract (digital or OCR) → layout → segment
           → answer key → crops → classify → persist

The pipeline never fabricates content. Every stage records quality warnings and
the raw extraction is kept beside the cleaned text, so a failure is visible and
recoverable rather than silent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pymupdf

from . import config
from .models import (DocumentAnalysis, Line, PageLayout, ParsedAnswerKeyEntry,
                     ParsedContext, ParsedQuestion, Span)
from .repositories import Repository
from .services import document_loader, image_processor, ocr_engine
from .services.answer_key_extractor import extract_answer_key
from .services.classifier import Classifier
from .services.layout_analyzer import LayoutAnalyzer
from .services.page_inspector import PageInspection, inspect_page
from .services.pdf_extractor import extract_raw_page, group_spans_into_lines
from .services.question_segmenter import QuestionSegmenter
from .taxonomy import Taxonomy


@dataclass
class PipelineResult:
    document_id: str
    filename: str
    page_count: int
    analysis: DocumentAnalysis
    stats: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(self, repository: Optional[Repository] = None, *,
                 classifier: Optional[Classifier] = None,
                 taxonomy: Optional[Taxonomy] = None,
                 use_ai: bool = False, render: bool = True,
                 crop_assets: bool = True):
        self.repo = repository or Repository()
        self.taxonomy = taxonomy or Taxonomy(self.repo.db)
        self.use_ai = use_ai
        if classifier is not None:
            self.classifier = classifier
        else:
            self.taxonomy.ensure_seeded()
            self.classifier = Classifier(self.taxonomy, use_ai=use_ai)
        self.render = render
        self.crop_assets = crop_assets

    # ------------------------------------------------------------------
    def process(self, source_path: Path, *, exam: Optional[str] = None,
                year: Optional[int] = None, source_notes: Optional[str] = None) -> PipelineResult:
        loaded = document_loader.store_document(Path(source_path))
        warnings: list[str] = []

        if loaded.doc_format == "pdf":
            analysis, inspections, doc = self._analyse_pdf(loaded)
        else:
            analysis, inspections, doc = self._analyse_image(loaded)

        analysis.metadata["size_bytes"] = loaded.size_bytes

        # ---- page renders + asset crops (needs the open document) --------
        render_paths: dict[int, str] = {}
        if doc is not None and self.render:
            try:
                render_paths = self._render_pages(loaded, analysis, doc)
                if self.crop_assets:
                    self._crop_assets(loaded, analysis, doc)
            finally:
                doc.close()
        elif doc is not None:
            doc.close()

        # ---- attach context text so classification sees the shared stimulus
        ctx_text = {c.index: c.text for c in analysis.contexts}
        for q in analysis.questions:
            if q.context_index is not None:
                setattr(q, "_context_text", ctx_text.get(q.context_index, ""))

        # ---- answer-key validation against the extracted questions --------
        self._validate_answer_key(analysis, warnings)

        # ---- persist ------------------------------------------------------
        doc_id = self.repo.save_analysis(
            analysis, exam=exam, year=year, source_notes=source_notes,
            inspections=inspections, render_paths=render_paths,
            classify=True, classifier=self.classifier)

        stats = self._stats(analysis, render_paths)
        stats["document_id"] = doc_id
        return PipelineResult(document_id=doc_id, filename=analysis.filename,
                              page_count=analysis.page_count, analysis=analysis,
                              stats=stats, warnings=warnings + analysis.warnings)

    # ------------------------------------------------------------------
    def _analyse_pdf(self, loaded):
        doc = pymupdf.open(str(loaded.path))
        raw_pages = []
        inspections: list[PageInspection] = []
        for i in range(doc.page_count):
            page = doc.load_page(i)
            raw = extract_raw_page(page, i + 1)
            raw_pages.append(raw)
            inspections.append(inspect_page(raw))

        # OCR pages that were flagged as needing it (only when OCR is set up).
        for raw, insp, in zip(raw_pages, inspections):
            if insp.needs_ocr and ocr_engine.ocr_available():
                page = doc.load_page(raw.page_number - 1)
                png = image_processor.render_page(loaded.sha256, page, raw.page_number)
                result = ocr_engine.ocr_image(png)
                if result.text:
                    raw.spans = _ocr_text_to_spans(result.text, raw.rotation)
                    raw.raw_text = result.text
                    insp2 = inspect_page(raw)
                    # keep the "text came from OCR" evidence
                    insp2.warnings.append("ocr_extracted")
                    inspections[raw_pages.index(raw)] = insp2

        analyzer = LayoutAnalyzer(raw_pages, inspections)
        layouts = analyzer.analyse()

        analysis = DocumentAnalysis(
            filename=loaded.filename, sha256=loaded.sha256, path=str(loaded.path),
            page_count=doc.page_count, page_layouts=layouts)
        self._segment(analysis)
        analysis.answer_key = extract_answer_key(layouts)
        for insp in inspections:
            if insp.warnings:
                analysis.warnings.extend(f"p{insp.page_number}:{w}" for w in insp.warnings)
        return analysis, inspections, doc

    def _analyse_image(self, loaded):
        from PIL import Image

        width = height = 0.0
        try:
            with Image.open(loaded.path) as img:  # type: ignore
                width, height = float(img.width), float(img.height)
        except Exception:
            pass

        result = ocr_engine.ocr_image(loaded.path)
        warnings: list[str] = []
        if not result.available:
            warnings.append("ocr_unavailable: " + (result.error or "Tesseract not configured"))
        elif not result.text:
            warnings.append("ocr_empty_result")

        spans = _ocr_text_to_spans(result.text, 0, width or 595.0, height or 842.0)
        raw_lines = group_spans_into_lines(spans, 1)
        layout = PageLayout(page_number=1, width=width or 595.0, height=height or 842.0,
                            rotation=0, body_font_size=config.DEFAULT_BODY_FONT_SIZE,
                            lines=raw_lines, raw_text=result.text, page_type="scanned",
                            warnings=list(warnings))
        for line in layout.lines:
            line.kind = "body"

        insp = PageInspection(
            page_number=1, width=layout.width, height=layout.height, rotation=0,
            char_count=len(result.text.strip()), image_count=1, drawing_count=0,
            text_density=0.0, image_area_fraction=1.0, page_type="scanned",
            has_text=bool(result.text.strip()), needs_ocr=not result.available,
            body_font_size=config.DEFAULT_BODY_FONT_SIZE, warnings=list(warnings))

        analysis = DocumentAnalysis(
            filename=loaded.filename, sha256=loaded.sha256, path=str(loaded.path),
            page_count=1, page_layouts=[layout])
        self._segment(analysis)
        analysis.answer_key = extract_answer_key([layout])
        analysis.warnings.extend(warnings)
        return analysis, [insp], None

    def _segment(self, analysis: DocumentAnalysis) -> None:
        seg = QuestionSegmenter(analysis.page_layouts)
        sections, contexts, questions = seg.segment()
        analysis.sections = sections
        analysis.contexts = contexts
        analysis.questions = questions
        # carry numbering diagnostics onto the analysis
        analysis.metadata["missing_numbers"] = getattr(seg, "_missing_numbers", [])
        analysis.metadata["duplicate_numbers"] = getattr(seg, "_duplicate_numbers", [])
        if analysis.metadata["missing_numbers"]:
            analysis.warnings.append(
                "possible_missing_question_numbers:" +
                ",".join(str(n) for n in analysis.metadata["missing_numbers"]))
        if analysis.metadata["duplicate_numbers"]:
            analysis.warnings.append(
                "duplicate_question_numbers:" +
                ",".join(str(n) for n in analysis.metadata["duplicate_numbers"]))

    # ------------------------------------------------------------------
    def _render_pages(self, loaded, analysis: DocumentAnalysis, doc) -> dict[int, str]:
        paths: dict[int, str] = {}
        for layout in analysis.page_layouts:
            page = doc.load_page(layout.page_number - 1)
            p = image_processor.render_page(loaded.sha256, page, layout.page_number)
            paths[layout.page_number] = str(p)
        return paths

    def _crop_assets(self, loaded, analysis: DocumentAnalysis, doc) -> None:
        # Context regions (graph/table) first: one crop per shared region.
        for ctx in analysis.contexts:
            region = (ctx.structured or {}).get("region_bbox")
            page_no = (ctx.structured or {}).get("region_page")
            if region and page_no:
                page = doc.load_page(int(page_no) - 1)
                p = image_processor.crop_asset(
                    loaded.sha256, page, tuple(region), f"ctx_{ctx.index:03d}_region")
                ctx.asset_path = str(p)
                ctx.structured["region_asset"] = str(p)

        # Math questions: crop the exact stem/formula area for verification.
        for q in analysis.questions:
            if not q.is_math or not q.bbox:
                continue
            page = doc.load_page(q.page_number - 1)
            p = image_processor.crop_asset(
                loaded.sha256, page, tuple(q.bbox), f"q{q.number or q.order_index:03d}_math")
            q.asset_path = str(p)

    # ------------------------------------------------------------------
    def _validate_answer_key(self, analysis: DocumentAnalysis, warnings: list[str]) -> None:
        by_number: dict[int, ParsedQuestion] = {
            q.number: q for q in analysis.questions if q.number is not None}
        option_count = {n: len(q.options) for n, q in by_number.items()}

        seen: dict[int, int] = {}
        for e in analysis.answer_key:
            seen[e.question_number] = seen.get(e.question_number, 0) + 1
        duplicates = {n for n, c in seen.items() if c > 1}

        for e in analysis.answer_key:
            q = by_number.get(e.question_number)
            if e.question_number in duplicates:
                e.match_status = "duplicate"
            elif q is None:
                e.match_status = "out_of_range" if analysis.answer_key else "unmatched"
            elif order_out_of_range(e, option_count.get(e.question_number, 0)):
                e.match_status = "invalid"
            else:
                e.match_status = "matched"

        if analysis.answer_key:
            keyed = {e.question_number for e in analysis.answer_key}
            missing = sorted(set(by_number) - keyed)
            if missing:
                warnings.append("answer_key_missing_for:" + ",".join(str(n) for n in missing))
                analysis.metadata["answer_key_missing"] = missing
        else:
            warnings.append("no_answer_key_detected")
        if duplicates:
            warnings.append("answer_key_duplicate_for:" + ",".join(str(n) for n in sorted(duplicates)))

    def _stats(self, analysis: DocumentAnalysis, render_paths: dict) -> dict:
        options_total = sum(len(q.options) for q in analysis.questions)
        mcq = sum(1 for q in analysis.questions if q.options)
        return {
            "pages": analysis.page_count,
            "renders": len(render_paths),
            "sections": len(analysis.sections),
            "contexts": len(analysis.contexts),
            "questions": len(analysis.questions),
            "questions_with_options": mcq,
            "options": options_total,
            "math_questions": sum(1 for q in analysis.questions if q.is_math),
            "answer_keys": len(analysis.answer_key),
            "contexts_with_region": sum(1 for c in analysis.contexts if (c.structured or {}).get("region_bbox")),
            "regions": sum(len(l.regions) for l in analysis.page_layouts),
            "missing_numbers": analysis.metadata.get("missing_numbers", []),
            "duplicate_numbers": analysis.metadata.get("duplicate_numbers", []),
        }


# ---------------------------------------------------------------------------
def order_out_of_range(entry: ParsedAnswerKeyEntry, n_options: int) -> bool:
    if entry.option_index is None:
        return False
    if n_options == 0:
        return False
    return entry.option_index > n_options


def _ocr_text_to_spans(text: str, rotation: int = 0,
                       width: float = 595.0, height: float = 842.0,
                       line_height: float = 14.0, margin: float = 50.0) -> list[Span]:
    """Turn plain OCR text into synthetic, coordinate-bearing spans.

    OCR has no text layer, so lines are laid out top-to-bottom with a fixed
    pitch. This keeps the downstream segmenter (which is coordinate-driven)
    working; OCR text is explicitly flagged as such by the caller.
    """
    spans: list[Span] = []
    y = margin
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            y += line_height
            continue
        spans.append(Span(text=line, font="OCR", size=config.DEFAULT_BODY_FONT_SIZE,
                          bbox=(margin, y, margin + _approx_width(line), y + line_height - 2),
                          raw_text=line))
        y += line_height
    return spans


def _approx_width(text: str) -> float:
    return max(10.0, 6.0 * len(text))
