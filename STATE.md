# Session State — QBank (Exam Paper Digitizer)

**Saved:** 2026-10-18
**Status:** DELIVERED, VERIFIED & ENHANCED — Web App v2.0 with Source Paper Viewer.
**Purpose of this file:** resume context for the next session without re-deriving it.
Do not duplicate the spec: read `master-prompt.txt` (spec) and `exam_question_bank/README.md`
(behaviour, install, limitations, verified results) first. This file records only *state,
decisions, and open threads*.

---

## Where things are

| Path | What |
|---|---|
| `C:\Users\dines\Downloads\QBank\master-prompt.txt` | Authoritative spec (892 lines) |
| `C:\Users\dines\Downloads\QBank\Model Test 13.pdf` | Reference benchmark (8 pages) — copyrighted, do NOT commit |
| `C:\Users\dines\Downloads\QBank\docs\ANALYSIS.md` | Verified PDF analysis + design consequences |
| `C:\Users\dines\Downloads\QBank\exam_question_bank\` | **Working source tree (the deliverable)** |
| `C:\Users\dines\Downloads\QBank\web_app\` | **Standalone encrypted web app (v2.0)** |
| `C:\Users\dines\Downloads\QBank\web_app\launch_local.bat` | **Double-click to preview locally** |
| `C:\Users\dines\Downloads\QBank\exam_question_bank\data\question_bank.db` | Populated dev DB with verified reference result |

Env: Windows 11, Python 3.13.14 only. PyMuPDF 1.28.2, Pillow 12.2.0, Streamlit 1.58.0,
pandas 3.0.3, numpy 2.5.0, pytest 9.1.1, pytesseract 0.3.13. Tesseract 5.5.3 installed at
`C:\Program Files\Tesseract-OCR\tesseract.exe` (auto-detected; no env var needed).
Not a git repo — nothing is committed anywhere.

---

## Current verified state (all executed, not estimated)

- `pytest` → **55 passed, 1 skipped** in the working dir.
- Streamlit smoke test: all 9 scripts (`app.py` + `pages/1..8`) run with zero exceptions via `AppTest`.
- Reference result: 8 pages, 2 sections, 12 contexts, 80 questions (1-80, no gaps/dupes),
  400 options (5 each), 13 math (q68-80) all cropped, 80 answer keys all `matched`,
  2 graph/table regions, 0 warnings, classification Reasoning 40 / Quant 40, **0 unclassified**.
- OCR path: verified end-to-end (known word recovered; real page reads at ~91% confidence).

---

## Web App v2.0 Changes (2026-10-18)

### What changed:
1. **Source Paper Viewer** (right panel): Each question now shows the actual exam page
   image (page_NNN.png renders) it was extracted from. Uses ‹ › buttons to browse other pages.
   The correct page auto-loads when you navigate between questions.

2. **3-Panel Layout**:
   - Left: Topic index sidebar (sorted, with emoji icons per topic type)
   - Center: Question & interactive options (practice/check/reveal)
   - Right: Source paper viewer (sticky, shows rendered exam page)

3. **`export_encrypted_web.py` updated** (v1.1):
   - Now embeds all page renders (`data/renders/<doc_id>/page_NNN.png`) as base64 data-URIs
   - Vault is now ~5.9 MB (was 1.2 MB) because page images are included
   - `include_pages=False` flag available if you want a smaller export without page images

4. **Visual redesign** — premium dark theme:
   - Animated lock screen with glowing ring icon and blob background
   - Clean Inter + JetBrains Mono typography
   - Indigo/violet brand palette, glass-morphism panels
   - Emoji per topic type in sidebar tree
   - `sessionStorage` (not localStorage) for session-only password caching

5. **`launch_local.bat`** — double-click to serve from Python's built-in HTTP server and
   open in the default browser automatically.

### Vault password for dev vault:
```
pass123
```

### To regenerate vault after importing new papers:
```powershell
cd C:\Users\dines\Downloads\QBank\exam_question_bank
$env:PYTHONIOENCODING = "utf-8"
python scripts/export_encrypted_web.py --password "YOUR_PASSWORD"
```

---

## Key decisions already locked in

- Extraction is **coordinate-driven** (PyMuPDF `dict`), not text order.
- Raw text is **canonical**; heuristic math reconstruction lives only in `questions.math_json`
  + a per-question source crop. Missing answer stays missing. Never present a heuristic as verified.
- Symbol font PUA decoding: `0xF000` base → Adobe Symbol (`config.decode_symbol_text`).
- Watermark = span size ≥30pt, split out **before** line grouping. Header/footer = repeated
  position+text across pages. Page number = digits in bottom band. **Never** global phrase deletion.
- `header_band_fraction=0.09`, `footer_band_fraction=0.10`.
- Contexts linked by `Direction (a-b)` range (narrowest wins), orphan fallback.
- Document `id` = SHA-256; re-import replaces derived rows atomically (idempotent).
- Classification: non-DI → rules over `question_text + context_text` (most specific by list
  order; method `heuristic_keyword` if matched in question text else `heuristic_context`);
  DI (`data_interpretation_*`) → question text only, then context-type prior
  (`Quantitative Aptitude > Data Interpretation`). Specific operation stays the primary topic;
  `data_interpretation` recorded as a **tag**.
- Not auto-solving answers (out of scope by spec priorities). No paid APIs/cloud/telemetry.
- Web app uses sessionStorage (not localStorage) so password never persists after tab close.

---

## Open threads for the next discussion

1. **2-D formula reading order** (q68-80) can extract jumbled — flagged uncertain, crop is
   authoritative. Idea: column-aware reflow for stacked fractions/radicals.
2. **Graph numeric series** read visually only (deliberate — spec forbids inventing values).
   Optional human-confirmed "trace the series" assist could be discussed.
3. **Low-quality scans**: OCR verified on clean renders, not on a degraded scan. Preprocessing
   (deskew/binarize) before OCR is the likely next step.
4. **Other layouts**: verified only on `Model Test 13.pdf`. Would need `config.LayoutConfig` tuning.
5. **Web app vault size**: 5.9 MB with page renders. Can compress further (JPEG instead of PNG)
   or exclude page renders (`include_pages=False`) for a lightweight 1.2 MB vault.
6. **GitHub Pages deployment**: Push only the `web_app/` folder contents to a GitHub repo and
   enable Pages. The vault is already encrypted — no auth needed on GitHub side.

---

## First commands to re-orient

```powershell
cd C:\Users\dines\Downloads\QBank\exam_question_bank
$env:PYTHONIOENCODING="utf-8"
python -m pytest                       # expect 55 passed, 1 skipped

# Preview web app locally (double-click OR run in terminal):
cd C:\Users\dines\Downloads\QBank\web_app
python -m http.server 8080
# Then open: http://localhost:8080
# Password: pass123
```

> Warning: do NOT re-run the pipeline with `--no-render` against the dev DB — it would wipe
> render/asset paths. The DB is already in the verified state (document id
> `30a974a9b6c395c35d210cde9589d8944c4c709bf88a0f3211b8bfbbd29ca2fc`).
