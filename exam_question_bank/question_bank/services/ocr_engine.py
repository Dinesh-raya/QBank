"""Optional OCR via Tesseract.

The application must run without OCR: this module reports availability and is
only called for pages the page inspector marked as needing OCR. Configure the
Tesseract binary with ``QB_TESSERACT_CMD`` or by having ``tesseract`` on PATH.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:  # optional dependency
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore
    _HAVE_PYTESSERACT = True
except Exception:  # pragma: no cover - exercised only when deps absent
    pytesseract = None  # type: ignore
    Image = None  # type: ignore
    _HAVE_PYTESSERACT = False


@dataclass
class OcrResult:
    text: str
    confidence: Optional[float] = None
    available: bool = False
    words: list[dict] = field(default_factory=list)
    error: Optional[str] = None


def _default_candidates() -> list[str]:
    """Well-known default install locations, checked when PATH misses them.

    Windows installers historically do not add ``tesseract`` to PATH, so the
    binary is often present at a fixed location. Unix locations are included
    for completeness. Any of these can be overridden with QB_TESSERACT_CMD.
    """
    if os.name == "nt":
        roots = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        return [str(Path(r) / "Tesseract-OCR" / "tesseract.exe") for r in roots if r]
    return ["/usr/bin/tesseract", "/usr/local/bin/tesseract", "/opt/homebrew/bin/tesseract"]


def tesseract_path() -> Optional[str]:
    env = os.environ.get("QB_TESSERACT_CMD")
    if env and Path(env).exists():
        return env
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in _default_candidates():
        if Path(candidate).exists():
            return candidate
    return None


def ocr_available() -> bool:
    return _HAVE_PYTESSERACT and tesseract_path() is not None


def configure() -> Optional[str]:
    if not _HAVE_PYTESSERACT:
        return None
    cmd = tesseract_path()
    if cmd:
        try:
            pytesseract.pytesseract.tesseract_cmd = cmd  # type: ignore
        except Exception:
            pass
    return cmd


def ocr_image(image_path: Path, lang: str = "eng") -> OcrResult:
    """Run OCR on an image file. Never raises: failures are reported."""
    if not _HAVE_PYTESSERACT:
        return OcrResult(text="", available=False, error="pytesseract not installed")
    if tesseract_path() is None:
        return OcrResult(text="", available=False, error="Tesseract binary not found (set QB_TESSERACT_CMD)")
    configure()
    try:
        with Image.open(image_path) as img:  # type: ignore
            data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)  # type: ignore
        words = []
        confs = []
        # Group words into lines using Tesseract's own block/paragraph/line
        # counters, so multi-line images reconstruct as multiple lines instead
        # of one run-on string.
        lines: dict[tuple, list[str]] = {}
        line_order: list[tuple] = []
        for i in range(len(data.get("text", []))):
            word = (data["text"][i] or "").strip()
            if not word:
                continue
            conf = float(data["conf"][i]) if str(data["conf"][i]).replace(".", "", 1).lstrip("-").isdigit() else -1
            key = (data.get("block_num", [0])[i] if "block_num" in data else 0,
                   data.get("par_num", [0])[i] if "par_num" in data else 0,
                   data.get("line_num", [0])[i] if "line_num" in data else 0)
            lines.setdefault(key, []).append(word)
            if key not in line_order:
                line_order.append(key)
            words.append({
                "text": word,
                "conf": conf,
                "left": data["left"][i], "top": data["top"][i],
                "width": data["width"][i], "height": data["height"][i],
            })
            if conf >= 0:
                confs.append(conf)
        text = "\n".join(" ".join(lines[key]) for key in line_order)
        mean_conf = sum(confs) / len(confs) if confs else None
        return OcrResult(text=text, confidence=mean_conf, available=True, words=words)
    except Exception as exc:  # pragma: no cover
        return OcrResult(text="", available=True, error=str(exc))
