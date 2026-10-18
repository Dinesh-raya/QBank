# Exam Paper Digitizer & Question Bank

A **local-only** application that turns competitive-exam question papers (digital
PDFs or scanned images) into a searchable, editable and classifiable question
bank stored in SQLite.

It prioritises **faithful extraction, source traceability, shared-context
preservation, topic classification and human correction** over automation. It is
deliberately *not* an answer-solving or mock-test engine.

---

## 1. Project overview

Pipeline (every stage is an independently testable module):

```
ingest → inspect page → extract (digital text | OCR) → layout analysis
      → question segmentation → answer-key extraction → asset crops
      → topic classification → persist (SQLite) → duplicate detection
```

Key design decisions:

- **Coordinate-driven extraction.** Questions are located by PDF coordinates
  (`PyMuPDF` "dict" mode), not by the text layer's reading order, because the
  reference papers use 2-D layouts (stacked fractions, columns, side-by-side
  conclusions).
- **Nothing is fabricated.** A missing question number, answer or value stays
  missing and is flagged. Heuristic 2-D formula reconstruction is stored
  *separately* and marked `uncertain`; the raw text and a source crop stay
  canonical.
- **Evidence-based noise removal.** Watermarks are found by font size; running
  headers/footers by *repeated position **and** repeated text across pages*; page
  numbers as digits in the bottom band. A header/footer that is not a
  document-wide repeated signature is kept as body text.
- **Shared material is stored once.** A `Direction (a-b)` block becomes a single
  *context* record; each of its questions stores only a reference. Contexts are
  linked by the narrowest matching `(a-b)` range.
- **Immutable raw text, editable copy.** `questions.raw_text` is never modified;
  edits go to `questions.text`. Every edit is written to `review_history`.
- **Idempotent import.** A document's id is its SHA-256; re-importing replaces
  its derived rows in one transaction.

---

## 2. Tested Python version

**Python 3.13.14** (CPython) on **Windows 11**. The code targets Python 3.10+.

Verified with: `pymupdf 1.28.2`, `Pillow 12.2.0`, `streamlit 1.58.0`,
`pandas 3.0.3`, `numpy 2.5.0`, `pytest 9.1.1`.

---

## 3. Install

### Windows PowerShell

```powershell
cd C:\Users\dines\Downloads\QBank\exam_question_bank

# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope Process RemoteSigned

# Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` separates **core** (pymupdf, Pillow), **UI** (streamlit,
pandas), **testing** (pytest) and **optional OCR** (pytesseract, numpy). OCR is
optional: the app runs fully without it and simply flags scanned pages.

---

## 4. Launch

```powershell
# From exam_question_bank/
streamlit run app.py
```

The app opens on `http://localhost:8501`. Use the sidebar to move between
Dashboard, Import Documents, Review Extraction, Question Bank, Answer-Key
Review, Taxonomy Manager, Settings and Export & Backup.

### Headless import (no browser)

```powershell
python scripts\import_document.py "..\Model Test 13.pdf" --exam "IBPS RRB Clerk"
python scripts\import_document.py paper.pdf --no-render   # skip image rendering
```

---

## 5. Optional OCR (Tesseract)

Digital PDFs need no OCR. For scanned papers:

1. Install the Tesseract binary (e.g. the UB-Mannheim Windows build).
2. Point the app at it. The app already auto-detects the usual Windows install
   directory (`C:\Program Files\Tesseract-OCR\tesseract.exe`), so this is only
   needed for non-standard locations:

```powershell
$env:QB_TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
# persistent:
setx QB_TESSERACT_CMD "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Pages with little/no extractable text are auto-flagged `needs_ocr`. When
Tesseract is unavailable, those pages are still imported and clearly flagged —
nothing is silently dropped.

The OCR path is exercised by `tests/test_ocr.py` (it skips cleanly when
Tesseract/pytesseract are absent).

---

## 6. Optional local AI classifier

Rule-based classification always runs and is the default. An **optional** local
model (Ollama / any OpenAI-compatible chat endpoint) can be used for questions
the rules cannot place. Nothing is sent anywhere unless you explicitly opt in.

```powershell
$env:QB_AI_ENABLED = "1"
$env:QB_AI_BASE_URL = "http://localhost:11434"     # Ollama default
$env:QB_AI_MODEL    = "qwen2.5:3b-instruct"
# Only needed for a NON-local endpoint:
$env:QB_AI_ALLOW_REMOTE = "1"
```

Enable "Use the optional local AI classifier" on the Import page (or
`--use-ai` on the CLI) to let it suggest topics for unmatched questions. If the
service is unreachable, the rule-based result stands and the app keeps working.

---

## 7. Import & review workflow

1. **Import Documents** — upload one or more PDFs/images, set exam/year (stored,
   never invented), and process. Warnings and per-document stats show what was
   found. Re-processing the same file is safe.
2. **Review Extraction** — pick a page, compare the rendered page + raw text with
   the extracted questions. Edit question text and options, correct the number,
   set the review status, link/unlink the shared context, edit the classification,
   exclude a non-question, split a combined record, merge fragments, or create a
   question manually. Every change is recorded in the History table.
3. **Question Bank** — full-text search and filters (subject, topic, subtopic,
   exam, year, document, review status, missing answer, duplicate candidate).
   Open any question for its options, context, answer, classification and history.
4. **Answer-Key Review** — see missing/out-of-range/invalid/duplicate entries and
   manually set or correct an answer (which marks the question verified).
5. **Taxonomy Manager** — add/rename/deactivate/delete subjects, topics and
   subtopics; invalid parent-child links are rejected.
6. **Export & Backup** — see below.

---

## 8. Data & database locations

All local data lives under `exam_question_bank/data/` (git-ignored):

| Path | Contents |
|------|----------|
| `data/question_bank.db` | SQLite database (WAL) |
| `data/uploads/<sha256>/original.*` | Immutable copies of uploaded originals |
| `data/renders/<sha256>/page_*.png` | Rendered page previews |
| `data/assets/<sha256>/*.png` | Context-region and math-question crops |
| `data/exports/` | JSON/CSV exports |
| `data/backups/` | ZIP backups |

The database persists across restarts. Uploaded originals are never modified.

---

## 9. Export formats

- **JSON** (`schema: exam-question-bank/1`) — structured questions with ordered
  options, shared contexts, primary/secondary classifications, answer-key
  provenance, math reconstruction and source metadata.
- **CSV** (UTF-8 with BOM) — spreadsheet-friendly rows: question text, joined
  options, subject/topic/subtopic, tags, answer, verification and review status,
  source page, quality flags.

Both can be produced for the whole bank or a single document from the
**Export & Backup** page.

---

## 10. Backup & restoration

CSV is **not** a backup. A backup is a single ZIP containing a consistent SQLite
snapshot (via SQLite's online-backup API) plus every local asset file, with a
`backup_manifest.json`.

- **Create:** Export & Backup → *Create backup now* (or `list_backups()` /
  `create_backup()` in code).
- **Restore:** upload the ZIP on the same page. Existing files are moved aside
  (`*.replaced`) before being overwritten, so a failed restore never destroys the
  current bank.

---

## 11. Automated tests

```powershell
pytest                       # runs tests/ (see pytest.ini)
pytest tests\test_answer_key.py -q
pytest tests\test_ocr.py -q  # OCR path (skips if Tesseract is absent)
```

The regression suite runs the real pipeline once against
`tests/fixtures/Model Test 13.pdf`. That fixture is **git-ignored**
(copyrighted). If it is absent, the PDF-dependent tests **skip gracefully**
instead of failing. Unit tests (classification, database, context-linking logic)
run without any fixture.

See **section 14** for current results.

---

## 12. Troubleshooting

| Symptom | Fix |
|---|---|
| `streamlit` not found | Activate the venv, `python -m pip install -r requirements.txt`, run via `python -m streamlit run app.py`. |
| `.\.venv\Scripts\Activate.ps1` blocked | `Set-ExecutionPolicy -Scope Process RemoteSigned` then retry. |
| Page flagged `needs_ocr` | It has little/no text. Install Tesseract and set `QB_TESSERACT_CMD`. |
| Formula text "jumbled" (Q68-80) | Expected: 2-D layout. The crop image is authoritative; the heuristic linear form is flagged `math_layout_uncertain`. |
| AI suggestions never appear | `QB_AI_ENABLED=1` and a reachable endpoint are required; rules still classify without it. |
| DB locked | Close other app instances; SQLite is opened in WAL mode with a 30 s timeout. |
| Need to reset everything | Stop the app, delete `data/question_bank.db*` (and `data/renders`, `data/assets` if desired), relaunch. |

---

## 13. Known limitations

- **Not every layout.** The extractor is designed to generalise (per-document
  section/option/answer detection) but is only *verified* on the reference paper.
  Other layouts may need tuning of `config.LayoutConfig`.
- **OCR is verified on rendered text, not on a scanned paper.** Tesseract 5.5.3
  is detected, and `tests/test_ocr.py` OCRs a rendered image end-to-end (known
  word recovered; a real paper page also reads cleanly). A true low-quality scan
  has not been exercised.
- **2-D formula reconstruction is heuristic.** It is never presented as verified;
  the source crop is the source of truth.
- **Graph data is not machine-readable.** Axis/category labels are captured and
  the region is cropped; numeric series are read visually, so question *values*
  are not auto-extracted (by design — the prompt forbids inventing values).
- **Classification is heuristic.** It is a *suggestion* with a recorded method;
  a human confirms or corrects it.
- Handwriting, rotated pages and multi-column body text are not specially
  handled beyond the general heuristics.

---

## 14. Reference-paper results (verified)

`Model Test 13.pdf` (8 pages), as produced by the pipeline and asserted by the
test suite:

| Check | Result |
|---|---|
| Pages | 8 |
| Sections | 2 (`REASONING` q1-40, `NUMERICAL ABILITY` q41-80) |
| Questions | 80, numbers 1-80, **no gaps or duplicates** |
| Options | 400 (exactly 5 per question) |
| Shared contexts | 12 (graph q52-57, table q61-66, symbol arrangement q24-28, …) |
| Contexts with a graph/table region | 2 (both cropped) |
| Math questions | 13 (q68-80), all with a source crop |
| Answer keys | 80, all matched, **0 missing/invalid/duplicate** |
| Extraction warnings | none |
| Classification | Reasoning 40 / Quantitative Aptitude 40, 0 unclassified |

Run `pytest` to reproduce. The suite contains **55 tests** (one additional OCR
test skips when Tesseract is not installed).

---

## 15. Project structure

```
exam_question_bank/
├── app.py                      # Streamlit entry point
├── pages/                      # Dashboard, Import, Review, Bank, Answer Key,
│                               #   Taxonomy, Settings, Export & Backup
├── question_bank/
│   ├── config.py  database.py  models.py  repositories.py  taxonomy.py
│   ├── pipeline.py             # end-to-end orchestrator
│   └── services/               # document_loader, page_inspector, pdf_extractor,
│                               #   ocr_engine, image_processor, layout_analyzer,
│                               #   question_segmenter, option_extractor,
│                               #   context_linker, answer_key_extractor,
│                               #   math_layout, classifier, local_model_adapter,
│                               #   duplicate_detector, export_service, backup_service
├── config/default_taxonomy.json
├── scripts/import_document.py  # headless CLI
├── tests/                      # pytest suite (+ git-ignored fixture PDF)
├── data/                       # local data (git-ignored)
├── requirements.txt  pytest.ini  .gitignore  README.md
```

---

## 16. Privacy

Everything runs and stays on this machine. No document content is sent anywhere
unless you explicitly enable the optional local model *and* point it at a remote
endpoint with `QB_AI_ALLOW_REMOTE=1`. There is no telemetry.
