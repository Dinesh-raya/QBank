# QBank — Exam Paper Digitizer & Encrypted Question Bank

An offline-first, coordinate-driven document analysis and question bank digitizer for competitive exam papers, paired with a client-side AES-256-GCM encrypted web portal.

---

## 🌟 Key Features

1. **Precision Coordinate-Driven Extraction:**
   - Extracts questions, multi-column options, and shared stimulus paragraphs from exam PDFs.
   - PUA symbol font decoding (Adobe Symbol `0xF000` base) for clean Greek letters and mathematical operators.
   - Preserves 2-D mathematical formulas and graphical stimulus regions (data interpretation charts & tables) as high-resolution coordinate crops.

2. **Automated Topic Classification:**
   - Hierarchical rule-based taxonomy classifier.
   - Sub-topic tagging for Reasoning Ability, Quantitative Aptitude, and Data Interpretation.

3. **Streamlit Multi-Page Studio (`exam_question_bank/`):**
   - **Dashboard**: Corpus analytics and extraction health metrics.
   - **Import**: Document ingestion pipeline with auto-OCR fallback.
   - **Review Extraction**: Interactive per-page question inspector and classifier override.
   - **Question Bank**: Split-screen study station with KaTeX mathematical rendering and stimulus drawer.
   - **Answer Key Review**: Automatic key grid extraction and provenance verification.
   - **Taxonomy Manager**: Hierarchical topic editor.
   - **Export & Backup**: JSON, CSV, encrypted backup, and one-click Web Vault exporter.

4. **Zero-Knowledge Encrypted Web Vault (`web_app/`):**
   - Standalone, zero-dependency browser portal.
   - Client-side Web Crypto AES-256-GCM decryption with PBKDF2 (100,000 iterations).
   - Can be served locally or hosted entirely on free GitHub Pages with complete privacy.

---

## 🚀 Quick Start

### 1. Python Streamlit Application

```bash
# Navigate to the Streamlit app
cd exam_question_bank

# Install dependencies
pip install -r requirements.txt

# Run the test suite (55 tests)
python -m pytest

# Launch the Streamlit application
streamlit run app.py
```

### 2. Encrypted Web Portal

```bash
# Navigate to web_app
cd web_app

# Start a local HTTP server
python -m http.server 8080

# Open in browser: http://localhost:8080
```

---

## 🔒 Security & Privacy

- All document processing, classification, and OCR runs strictly offline on your local machine.
- No cloud APIs, paid services, or telemetry.
- Encrypted export files use authenticated AES-256-GCM encryption with SHA-256 HMAC verification.

---

## 📂 Repository Structure

```
├── exam_question_bank/     # Python Streamlit core application & pipeline
│   ├── app.py              # Main Streamlit entrypoint
│   ├── pages/              # 8 workflow pages
│   ├── question_bank/      # Modular extraction, classification, and DB services
│   ├── scripts/            # CLI import and export utilities
│   └── tests/              # Pytest test suite
├── web_app/                # Client-side encrypted web portal
│   ├── index.html          # Web UI layout
│   ├── style.css           # Glassmorphism dark theme
│   ├── app.js              # Web Crypto decryption & interactive study view
│   └── data.enc            # Encrypted question vault
├── docs/                   # Analysis & architectural specifications
└── STATE.md                # Session state & implementation log
```
