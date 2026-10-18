# Project Analysis — reference document "Model Test 13.pdf"
(working notes, kept in docs/ANALYSIS.md)

## Goal (from master prompt)
Build a real, working local app: PDF/image exam papers -> faithful question
digitization, shared-context preservation, topic classification, answer-key
extraction, persistent SQLite question bank, Streamlit UI, tests, docs.

Priorities: faithful extraction, source traceability, shared-context
preservation, honest quality reporting, human correction. NOT auto-solving.

## Reference document facts (verified by inspection)
- 8 pages, A4 (595x842), rotation 0, extractable text (digital PDF, producer doPDF).
- Page 1: branding header (logo image tiles + barcode), title box
  "IBPS REGIONAL RURAL BANKS (RRBs) / CLERKS-XV PRELIMS - MODEL TEST - 13",
  section heading "REASONING", Q1-4 syllogism group, Direction(5-9).
- Pages 1-4: Reasoning Q1-40. Pages 5-8: Numerical Ability Q41-80.
  Section heading "NUMERICAL ABILITY" appears mid page 5 (y=418).
- Each question has 5 options (1)..5)) with VARYING layouts:
  * 2-column rows: 1)&2) on one y, 3)&4) on next, 5) on third.
  * single row of five (e.g. Q19, Q23, Q46-50 options).
  * options wrapped across lines (Q53 "33 1/3", Q66 "8 1/2", "16 2/3").
  * options merged in one span: Q7 "4) 13th - March5) 18th - May";
    Q20 "4) 168cm   5) Can't be determined"; Q21 "3) One  4) ... 5) ...".
- Shared-context groups present: Direction (1-4),(5-9),(10-14),(15-18),(20-22),
  (24-28),(30-34),(35-39),(46-50),(52-57),(61-66),(68-80).
- Q5-9 puzzle CONTINUES ACROSS the page1->page2 boundary (clues split).
- Direction text is BOLD "Direction (a-b):"; the "(a-b)" range is the anchor.
- Repeated NOISE per page:
  * header y~58-62: "CCE"(HelvBlack@11), "Sreedhar's"(TimesNewRoman@11),
    "IBPS RRB CLERKS - PRELIMS - XV - MT - 13"(BookmanOldStyle@11).
  * huge diagonal watermark: GillSansMT-Bold@90.9 "Sreedhar's" (y~170) and
    HelvBlack@212.8 " CCE" (y~182). Detect by font size >= 30.
  * page number: Arial-BoldMT@7 digits inside an oval near bottom center y~766.
  * header/footer horizontal rules (drawings) y~74 and y~769.
  * QR code box + "SCAN QR FOR OUR RESULTS" on page 8 (drawings/box).
- Symbol font (SymbolMT) glyphs are emitted as Private-Use-Area code points
  offset by 0xF000 -> real Adobe Symbol codes:
    0xB4 -> multiplication (x)   0xB8 -> division (/)
    0x2B -> +   0x2D -> -   0x3D -> =
    0xA3 -> <= (<=)   0xB3 -> >= (>=)
    0xE6/0xE7/0xE8 -> large left parenthesis pieces "("
    0xF6/0xF7/0xF8 -> large right parenthesis pieces ")"
  (Inequality Q15-18 use 0xA3/0xB3; the loss of these caused blank gaps in raw text.)
- Symbol arrangement Q24-28 (page 4, y110 & y122) is ONE span per line, two
  physical lines, characters separated by multiple spaces. Must preserve
  exactly (identity, order, repeats, symbols, spaces). Visual: "U@ +" etc.
- Line graph (Q52-57, page 6): vector drawing, not an image. Y-axis 0..120
  step 20 ("Number of students who took part in the event" rotated), X axis
  "Schools" + categories A,B,C,D,E. Values visually ~ A80 B~37 C~63 D~48 E100.
  Underlying data NOT machine-readable -> must preserve crop + flag uncertain.
- Table (Q61-66, page 7): vector drawing + Calibri@18 text. Header row
  Months/Shops | January | February | March ; rows A(80,120,91) B(96,104,72)
  C(36,84,75). Structured extraction feasible from coordinates.
- Math (Q68-80, page 8): 2D layout using TimesNewRomanPSMT + SymbolMT.
  Radical signs (sqrt) are FILLED vector paths; fraction bars are STROKE lines.
  Examples (visual): Q68 sqrt(?) + (267-42)/15 = 180/6 ; Q69 7^2 x 3^3 - ? + 50 = 1350
  Q74 sqrt(196) + 8^2 x 3 = ? - 150 ; Q80 (3/8 + 1 3/4) x (5/6 + 1 1/6) x ? = 714.
  Reading order from text extraction is jumbled -> need 2D layout reconstruction
  + always keep the page crop. Never silently assert a wrong interpretation.
- Answer key (page 8, bottom, CourierNewPS-BoldMT@10.1): compact pairs
  "1.1 2.2 3.2 ..." = question.option. 80 entries, 8 lines of 10.
  Some rows split into multiple spans out of x-order (row 41-50) -> sort by x.
  Also "KEY" label + QR code box nearby.

## Design consequences
- Extraction must be coordinate-driven (PyMuPDF dict/rawdict), not text-order.
- Layout analyzer must classify spans into: header, footer, page-number,
  watermark, section-heading, direction, question-body, option, caption,
  table-cell, graph-text, math, key.
- Noise removal = position + font-size + repeat-position evidence; NEVER global
  phrase deletion (prompt requirement).
- Options must be split on "(N)" markers even when multiple share a span/line.
- Shared context = Direction blocks (range anchor) + stimulus that continues
  across pages; questions link to context via their number being inside range.
- Math reconstruction is best-effort + crop image + review flag.
- Graph/table crops stored as assets; table structured data parsed from coords.
- Answer key parsed from pairs, validated against extracted questions.
