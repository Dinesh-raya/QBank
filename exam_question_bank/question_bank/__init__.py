"""Exam Question Bank — faithful exam-paper digitization and classification.

The package is intentionally import-light: importing ``question_bank`` must not
import Streamlit or any optional dependency, so that core processing functions
stay testable and usable head-less (``pytest`` runs without a browser).
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
