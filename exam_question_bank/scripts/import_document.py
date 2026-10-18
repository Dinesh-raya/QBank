"""Headless import CLI for the Exam Question Bank.

Runs the same pipeline the Streamlit app uses, so a paper can be imported on a
server or in CI without a browser:

    python scripts/import_document.py "Model Test 13.pdf" --exam "IBPS RRB Clerk"
    python scripts/import_document.py paper.pdf --no-render
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the project root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

from question_bank.pipeline import Pipeline  # noqa: E402
from question_bank.repositories import Repository  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a PDF/image into the question bank.")
    parser.add_argument("source", type=Path, help="Path to the PDF or image file")
    parser.add_argument("--exam", default=None, help="Exam name (e.g. 'IBPS RRB Clerk')")
    parser.add_argument("--year", type=int, default=None, help="Exam year")
    parser.add_argument("--notes", default=None, help="Free-text source notes")
    parser.add_argument("--use-ai", action="store_true",
                        help="Allow the optional local AI classifier")
    parser.add_argument("--no-render", action="store_true",
                        help="Skip page renders and asset crops (faster, no images)")
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(f"error: file not found: {args.source}", file=sys.stderr)
        return 2

    repo = Repository()
    pipeline = Pipeline(repository=repo, use_ai=args.use_ai, render=not args.no_render,
                        crop_assets=not args.no_render)
    result = pipeline.process(args.source, exam=args.exam, year=args.year,
                              source_notes=args.notes)

    print(f"document_id: {result.document_id}")
    for key, value in result.stats.items():
        if key == "document_id":
            continue
        print(f"  {key}: {value}")
    if result.warnings:
        print("warnings:")
        for w in result.warnings:
            print(f"  - {w}")
    else:
        print("warnings: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
