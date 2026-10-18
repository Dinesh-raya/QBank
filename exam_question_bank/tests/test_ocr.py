"""Optional OCR path tests.

These exercise the Tesseract integration *when it is configured*, and skip
cleanly when it is not. OCR is optional in this project: the reference paper has
a text layer, so nothing else in the suite depends on it.

Enable the OCR tests by installing the Tesseract binary and pytesseract, then
ensuring either ``tesseract`` is on PATH or ``QB_TESSERACT_CMD`` points at it.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _ocr():
    from question_bank.services import ocr_engine

    return ocr_engine


def test_ocr_availability_is_reported_without_error():
    """ocr_available() must never raise, whether or not OCR is installed."""
    engine = _ocr()
    assert isinstance(engine.ocr_available(), bool)
    assert isinstance(engine.tesseract_path(), (str, type(None)))


def test_ocr_image_returns_structured_result_when_unavailable():
    """When OCR is not configured, ocr_image must fail soft, not raise."""
    engine = _ocr()
    if engine.ocr_available():
        pytest.skip("OCR is configured; unavailable-path behaviour not applicable")
    result = engine.ocr_image(Path("does-not-matter.png"))
    assert result.available is False
    assert result.error


def test_ocr_reads_known_word_from_image(tmp_path):
    """End-to-end OCR: a rendered word should be recovered from the image."""
    engine = _ocr()
    if not engine.ocr_available():
        pytest.skip("Tesseract binary / pytesseract not available")

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (600, 160), "white")
    draw = ImageDraw.Draw(img)
    # A large, plain word keeps OCR unambiguous across Tesseract versions.
    draw.text((40, 50), "QUESTION", fill="black")
    path = tmp_path / "scratch.png"
    img.save(path)

    result = engine.ocr_image(path)
    assert result.available is True
    assert result.error is None
    assert "QUESTION" in (result.text or "").upper()
    assert result.words
