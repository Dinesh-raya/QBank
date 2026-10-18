"""Settings — paths, environment and optional integrations (read-only)."""
from __future__ import annotations

import streamlit as st

from question_bank import config
from question_bank.ui import (ai_status_line, bootstrap, get_repository, human_bytes,
                              ocr_status_line, page_header)

bootstrap()
st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")
page_header("⚙️ Settings", "Local paths, database state and optional integrations.")

repo = get_repository()

st.subheader("Paths")
st.dataframe([
    {"name": "Project root", "path": str(config.PROJECT_ROOT)},
    {"name": "Database", "path": str(config.DB_PATH)},
    {"name": "Uploads", "path": str(config.UPLOADS_DIR)},
    {"name": "Page renders", "path": str(config.RENDERS_DIR)},
    {"name": "Asset crops", "path": str(config.ASSETS_DIR)},
    {"name": "Exports", "path": str(config.EXPORTS_DIR)},
    {"name": "Backups", "path": str(config.BACKUPS_DIR)},
], hide_index=True, width="stretch")

st.subheader("Database")
c1, c2 = st.columns(2)
c1.metric("Schema version", repo.db.schema_version())
c2.metric("File size", human_bytes(config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0))

st.subheader("Optional OCR")
st.write(ocr_status_line())
st.caption(f"Render DPI: {config.LAYOUT.render_dpi}. Configure the Tesseract binary with the "
           "`QB_TESSERACT_CMD` environment variable or by adding it to PATH.")

st.subheader("Optional local AI classifier")
st.write(ai_status_line())
st.json({
    "QB_AI_ENABLED": config.os.environ.get("QB_AI_ENABLED", "0"),
    "QB_AI_PROVIDER": config.AI.provider,
    "QB_AI_BASE_URL": config.AI.base_url,
    "QB_AI_MODEL": config.AI.model,
    "QB_AI_ALLOW_REMOTE": config.os.environ.get("QB_AI_ALLOW_REMOTE", "0"),
})
st.caption("The classifier is disabled unless QB_AI_ENABLED=1. Remote endpoints are blocked unless "
           "QB_AI_ALLOW_REMOTE=1. No document text leaves the machine by default.")

st.subheader("Extraction tuning")
st.json({
    "watermark_min_font_size": config.LAYOUT.watermark_min_font_size,
    "header_band_fraction": config.LAYOUT.header_band_fraction,
    "footer_band_fraction": config.LAYOUT.footer_band_fraction,
    "min_text_chars_for_digital": config.LAYOUT.min_text_chars_for_digital,
})
