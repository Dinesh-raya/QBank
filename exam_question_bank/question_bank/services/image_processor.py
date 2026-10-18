"""Page rendering and asset-crop helpers (paths + naming)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pymupdf

from .. import config
from .pdf_extractor import render_page_png, render_region_png


def document_render_dir(sha256: str) -> Path:
    d = config.RENDERS_DIR / sha256
    d.mkdir(parents=True, exist_ok=True)
    return d


def document_asset_dir(sha256: str) -> Path:
    d = config.ASSETS_DIR / sha256
    d.mkdir(parents=True, exist_ok=True)
    return d


def render_page(sha256: str, page: "pymupdf.Page", page_number: int, dpi: Optional[int] = None) -> Path:
    out = document_render_dir(sha256) / f"page_{page_number:03d}.png"
    return render_page_png(page, out, dpi=dpi)


def crop_asset(sha256: str, page: "pymupdf.Page",
               bbox: tuple[float, float, float, float], name: str,
               dpi: Optional[int] = None) -> Path:
    out = document_asset_dir(sha256) / f"{name}.png"
    return render_region_png(page, bbox, out, dpi=dpi)
