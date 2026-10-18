/**
 * QBank Web App — Client-Side Decryption & Interactive Exam Portal
 * v2.0 — with Source Paper Viewer, 3-panel layout, and polished UX
 */

// =============================================================================
// GLOBAL STATE
// =============================================================================
let gVaultData       = null;   // decrypted vault JSON
let gFilteredQs      = [];     // current filtered question list
let gCurrentIdx      = 0;      // index within gFilteredQs
let gActiveFilter    = { type: "all", value: null, label: "All Questions" };
let gUserChoices     = {};     // { qId: optionIndex (string) }
let gRevealedAnswers = {};     // { qId: true }
let gActiveMode      = "practice";
let gEncryptedBlob   = null;

// Source paper viewer state
let gSourceDocId     = null;   // currently viewed document
let gSourcePage      = 1;      // currently viewed page number

// =============================================================================
// 1. BOOT — load vault blob on page ready
// =============================================================================
document.addEventListener("DOMContentLoaded", async () => {
  try {
    const res = await fetch("data.enc?t=" + Date.now(), { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    gEncryptedBlob = await res.json();

    // Auto-unlock if session password saved
    const saved = sessionStorage.getItem("qbank_pass");
    if (saved) {
      document.getElementById("masterPasswordInput").value = saved;
      document.getElementById("rememberMeCheckbox").checked = true;
      await unlockVault();
    }
  } catch (err) {
    console.error("Vault load error:", err);
    showLockError("Could not load data.enc — export from Python first.");
  }
});

// =============================================================================
// 2. LOCK / UNLOCK
// =============================================================================
async function unlockVault() {
  const password = document.getElementById("masterPasswordInput").value;
  const remember  = document.getElementById("rememberMeCheckbox").checked;
  const btn        = document.getElementById("unlockButton");

  if (!password || !gEncryptedBlob) return;

  hideLockError();
  btn.disabled = true;
  btn.querySelector(".btn-text").textContent = "Decrypting…";

  try {
    const json    = await decryptData(gEncryptedBlob, password);
    gVaultData    = JSON.parse(json);

    if (remember) {
      sessionStorage.setItem("qbank_pass", password);
    } else {
      sessionStorage.removeItem("qbank_pass");
    }

    document.getElementById("lockScreen").classList.add("hidden");
    document.getElementById("appContainer").classList.remove("hidden");
    initAppUI();
  } catch {
    showLockError("Incorrect password or corrupt vault. Please try again.");
    btn.disabled = false;
    btn.querySelector(".btn-text").textContent = "Unlock Vault";
  }
}

async function decryptData(blob, password) {
  const enc       = new TextEncoder();
  const salt      = b64ToBytes(blob.salt);
  const iv        = b64ToBytes(blob.iv);
  const cipher    = b64ToBytes(blob.ciphertext);
  const baseKey   = await crypto.subtle.importKey(
    "raw", enc.encode(password), { name: "PBKDF2" }, false, ["deriveKey"]
  );
  const aesKey = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: 100000, hash: "SHA-256" },
    baseKey,
    { name: "AES-GCM", length: 256 },
    false, ["decrypt"]
  );
  const buf = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, aesKey, cipher);
  return new TextDecoder().decode(buf);
}

function b64ToBytes(b64) {
  const bin   = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function lockVault() {
  gVaultData = null;
  sessionStorage.removeItem("qbank_pass");
  document.getElementById("masterPasswordInput").value = "";
  document.getElementById("unlockButton").querySelector(".btn-text").textContent = "Unlock Vault";
  document.getElementById("unlockButton").disabled = false;
  document.getElementById("appContainer").classList.add("hidden");
  document.getElementById("lockScreen").classList.remove("hidden");
}

function togglePasswordVisibility() {
  const inp = document.getElementById("masterPasswordInput");
  inp.type  = inp.type === "password" ? "text" : "password";
}

function showLockError(msg) {
  const el = document.getElementById("lockError");
  el.innerHTML = `<span>⚠</span> ${msg}`;
  el.classList.remove("hidden");
}
function hideLockError() {
  document.getElementById("lockError").classList.add("hidden");
}

// =============================================================================
// 3. MAIN UI INITIALISATION
// =============================================================================
function initAppUI() {
  const total = gVaultData.questions.length;
  document.getElementById("totalQuestionsBadge").textContent = total;
  document.getElementById("count-all").textContent = total;

  buildTopicTree();
  buildPapersList();
  selectTopic("all");
}

// =============================================================================
// 4. SIDEBAR — TOPIC TREE & PAPERS LIST
// =============================================================================
function buildTopicTree() {
  const container = document.getElementById("topicTree");
  container.innerHTML = "";

  const tax = gVaultData.taxonomy_index || {};

  // Sort subjects so Reasoning comes before Quant etc.
  const subjects = Object.keys(tax).sort();

  for (const subject of subjects) {
    const topics = tax[subject];
    const totalInSubj = Object.values(topics).reduce((a, b) => a + b, 0);

    const grp = document.createElement("div");
    grp.className = "subject-group";

    const lbl = document.createElement("div");
    lbl.className = "subject-label";
    lbl.textContent = `${subject} · ${totalInSubj}`;
    grp.appendChild(lbl);

    // Sort topics by count descending
    const sortedTopics = Object.entries(topics).sort((a, b) => b[1] - a[1]);
    for (const [topic, count] of sortedTopics) {
      const item = document.createElement("div");
      item.className = "topic-item";
      item.id = `topic-${safeId(topic)}`;
      item.onclick = () => selectTopic("topic", topic, subject);
      item.innerHTML = `
        <span class="topic-emoji">${topicEmoji(topic)}</span>
        <span class="topic-name">${topic}</span>
        <span class="topic-count">${count}</span>
      `;
      grp.appendChild(item);
    }

    container.appendChild(grp);
  }
}

function buildPapersList() {
  const list = document.getElementById("papersList");
  list.innerHTML = "";
  (gVaultData.documents || []).forEach(d => {
    const count = gVaultData.questions.filter(q => q.document_id === d.id).length;
    const item  = document.createElement("div");
    item.className = "topic-item";
    item.id = `paper-${safeId(d.id)}`;
    item.onclick = () => selectTopic("paper", d.id, d.filename);
    item.innerHTML = `
      <span class="topic-emoji">📄</span>
      <span class="topic-name">${d.filename}</span>
      <span class="topic-count">${count}</span>
    `;
    list.appendChild(item);
  });
}

function topicEmoji(topic) {
  const t = topic.toLowerCase();
  if (t.includes("syllog"))                    return "🔄";
  if (t.includes("percent") || t.includes("%")) return "💯";
  if (t.includes("blood"))                     return "🩸";
  if (t.includes("seating") || t.includes("sitting")) return "💺";
  if (t.includes("puzzle"))                    return "🧩";
  if (t.includes("data interpret"))            return "📊";
  if (t.includes("profit") || t.includes("loss")) return "💰";
  if (t.includes("speed") || t.includes("time"))  return "⏱️";
  if (t.includes("number"))                    return "🔢";
  if (t.includes("simplif"))                   return "🧮";
  if (t.includes("inequalit"))                 return "⚖️";
  if (t.includes("direction"))                 return "🧭";
  if (t.includes("coding") || t.includes("decoding")) return "🔐";
  if (t.includes("series"))                    return "📈";
  if (t.includes("analogy"))                   return "🤔";
  if (t.includes("mixture") || t.includes("alligation")) return "🧪";
  if (t.includes("interest"))                  return "💳";
  if (t.includes("geometry") || t.includes("mensur")) return "📐";
  if (t.includes("probability"))               return "🎲";
  return "📌";
}

// =============================================================================
// 5. FILTER & SEARCH
// =============================================================================
function selectTopic(type, value = null, extra = "") {
  document.querySelectorAll(".topic-item").forEach(el => el.classList.remove("active"));

  if (type === "all") {
    document.getElementById("topic-all").classList.add("active");
    gActiveFilter     = { type: "all", value: null, label: "All Questions" };
    gFilteredQs       = [...gVaultData.questions];
  } else if (type === "topic") {
    const el = document.getElementById(`topic-${safeId(value)}`);
    if (el) el.classList.add("active");
    gActiveFilter = { type: "topic", value, label: `${value}` };
    gFilteredQs   = gVaultData.questions.filter(q => q.topic === value);
  } else if (type === "paper") {
    const el = document.getElementById(`paper-${safeId(value)}`);
    if (el) el.classList.add("active");
    gActiveFilter = { type: "paper", value, label: `📄 ${extra}` };
    gFilteredQs   = gVaultData.questions.filter(q => q.document_id === value);
  }

  updateFilterBar();
  gCurrentIdx = 0;
  renderCurrentView();
  closeMobileSidebar();
}

function handleSearch() {
  const q      = document.getElementById("searchInput").value.trim().toLowerCase();
  const clearB = document.getElementById("clearSearchBtn");
  clearB.classList.toggle("hidden", !q);

  if (!q) {
    selectTopic(gActiveFilter.type, gActiveFilter.value, gActiveFilter.label);
    return;
  }

  let pool = gVaultData.questions;
  if (gActiveFilter.type === "topic") pool = pool.filter(x => x.topic === gActiveFilter.value);
  if (gActiveFilter.type === "paper") pool = pool.filter(x => x.document_id === gActiveFilter.value);

  gFilteredQs = pool.filter(x =>
    (x.stem   || "").toLowerCase().includes(q) ||
    (x.topic  || "").toLowerCase().includes(q) ||
    (x.subject|| "").toLowerCase().includes(q) ||
    (x.options|| []).some(o => (o.text || "").toLowerCase().includes(q))
  );

  document.getElementById("activeTopicLabel").textContent  = `Search: "${q}"`;
  document.getElementById("filteredCountLabel").textContent = `(${gFilteredQs.length} results)`;
  document.getElementById("resetFilterBtn").classList.remove("hidden");

  gCurrentIdx = 0;
  renderCurrentView();
}

function clearSearch() {
  document.getElementById("searchInput").value = "";
  handleSearch();
}

function updateFilterBar() {
  document.getElementById("activeTopicLabel").textContent  = gActiveFilter.label;
  document.getElementById("filteredCountLabel").textContent = `(${gFilteredQs.length} questions)`;
  document.getElementById("resetFilterBtn").classList.toggle("hidden", gActiveFilter.type === "all");
}

// =============================================================================
// 6. VIEW MODES
// =============================================================================
function setMode(mode) {
  gActiveMode = mode;
  document.getElementById("modePracticeBtn").classList.toggle("active", mode === "practice");
  document.getElementById("modeFeedBtn").classList.toggle("active", mode === "feed");
  document.getElementById("practiceView").classList.toggle("hidden", mode !== "practice");
  document.getElementById("feedView").classList.toggle("hidden", mode !== "feed");
  renderCurrentView();
}

function renderCurrentView() {
  if (gActiveMode === "practice") renderPracticeMode();
  else                             renderFeedMode();
}

// =============================================================================
// 7. PRACTICE MODE
// =============================================================================
function renderPracticeMode() {
  const total = gFilteredQs.length;

  if (total === 0) {
    document.getElementById("questionStepIndicator").textContent = "No questions match.";
    document.getElementById("practiceStemText").textContent = "Try clearing your search or selecting a different topic.";
    document.getElementById("practiceOptionsList").innerHTML = "";
    document.getElementById("jumpPillRow").innerHTML = "";
    clearSourcePanel();
    return;
  }

  if (gCurrentIdx >= total) gCurrentIdx = 0;
  const q = gFilteredQs[gCurrentIdx];

  // ── Navigator ──
  document.getElementById("questionStepIndicator").textContent = `Question ${gCurrentIdx + 1} of ${total}`;
  document.getElementById("prevQuestionBtn").disabled = gCurrentIdx === 0;
  document.getElementById("nextQuestionBtn").disabled = gCurrentIdx >= total - 1;

  // ── Jump pills ──
  renderJumpPills(total);

  // ── Meta chips ──
  const chips = document.getElementById("practiceMetaChips");
  chips.innerHTML = `
    <span class="chip chip-q">Q${q.number != null ? q.number : gCurrentIdx + 1}</span>
    <span class="chip chip-subj">${esc(q.subject || 'General')}</span>
    <span class="chip chip-topic">${esc(q.topic || 'General')}</span>
    <span class="chip chip-page">Page ${q.page || 1}</span>
    ${q.is_math ? '<span class="chip chip-math">∑ Math</span>' : ''}
  `;

  // ── Stimulus pane ──
  renderStimulusPane(q);

  // ── Question stem ──
  document.getElementById("practiceStemText").textContent = q.stem || "";

  // ── KaTeX math ──
  const mathBox    = document.getElementById("practiceMathBox");
  const katexTgt   = document.getElementById("katexTarget");
  if (q.is_math && q.math && q.math.linear) {
    mathBox.classList.remove("hidden");
    const latex = linearToLatex(q.math.linear);
    if (window.katex) {
      try { window.katex.render(latex, katexTgt, { displayMode: true, throwOnError: false }); }
      catch { katexTgt.textContent = q.math.linear; }
    } else { katexTgt.textContent = q.math.linear; }
  } else {
    mathBox.classList.add("hidden");
  }

  // ── Options ──
  renderOptions(q);

  // ── Feedback & provenance ──
  renderFeedbackAndProvenance(q);

  // ── Source paper ──
  renderSourcePanel(q);
}

function renderStimulusPane(q) {
  const ctx      = q.context;
  const content  = document.getElementById("stimulusContent");
  const empty    = document.getElementById("stimulusEmptyState");
  const cropBox  = document.getElementById("cropPreviewBox");
  const cropImg  = document.getElementById("questionCropImg");

  if (ctx && (ctx.text || ctx.image_b64 || ctx.sequence)) {
    empty.classList.add("hidden");
    content.classList.remove("hidden");

    document.getElementById("stimulusLabel").textContent =
      `${ctx.label || 'Direction'} · Q${ctx.question_start || '?'}–Q${ctx.question_end || '?'}`;
    document.getElementById("stimulusText").textContent = ctx.text || "";

    const seqEl = document.getElementById("stimulusSequence");
    seqEl.classList.toggle("hidden", !ctx.sequence);
    if (ctx.sequence) seqEl.textContent = ctx.sequence;

    const imgWrap = document.getElementById("stimulusImageWrapper");
    const imgEl   = document.getElementById("stimulusImage");
    imgWrap.classList.toggle("hidden", !ctx.image_b64);
    if (ctx.image_b64) imgEl.src = ctx.image_b64;
  } else {
    content.classList.add("hidden");
    empty.classList.remove("hidden");
  }

  // Formula crop
  if (q.crop_b64) {
    cropImg.src = q.crop_b64;
    cropBox.classList.remove("hidden");
  } else {
    cropBox.classList.add("hidden");
  }
}

function renderJumpPills(total) {
  const row = document.getElementById("jumpPillRow");
  row.innerHTML = "";
  for (let i = 0; i < total; i++) {
    const q    = gFilteredQs[i];
    const pill = document.createElement("div");
    pill.className = `jump-pill ${i === gCurrentIdx ? "active" : ""} ${gUserChoices[q.id] ? "answered" : ""}`;
    pill.textContent = q.number != null ? q.number : i + 1;
    pill.title = `Q${q.number != null ? q.number : i + 1} · ${q.topic}`;
    pill.onclick = () => { gCurrentIdx = i; renderPracticeMode(); };
    row.appendChild(pill);
  }
  // Scroll active pill into view
  const active = row.querySelector(".jump-pill.active");
  if (active) active.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
}

function renderOptions(q) {
  const container = document.getElementById("practiceOptionsList");
  container.innerHTML = "";

  const chosen     = gUserChoices[q.id];
  const revealed   = gRevealedAnswers[q.id];
  const correctIdx = q.answer ? String(q.answer.option_index) : null;

  (q.options || []).forEach(opt => {
    const card   = document.createElement("div");
    const optIdx = String(opt.index);
    card.className = "option-card";
    if (chosen === optIdx)   card.classList.add("selected");
    if (revealed && correctIdx) {
      if (optIdx === correctIdx)   card.classList.add("correct");
      else if (chosen === optIdx)  card.classList.add("wrong");
    }

    card.onclick = () => {
      gUserChoices[q.id] = optIdx;
      renderOptions(q);
      renderJumpPills(gFilteredQs.length);
    };
    card.innerHTML = `
      <div class="option-badge">${esc(opt.label || opt.index)}</div>
      <div class="option-text">${esc(opt.text || "")}</div>
    `;
    container.appendChild(card);
  });
}

function checkAnswer() {
  const q = gFilteredQs[gCurrentIdx];
  if (!gUserChoices[q.id]) { alert("Please select an option first!"); return; }
  gRevealedAnswers[q.id] = true;
  renderPracticeMode();
}

function toggleRevealAnswer() {
  const q = gFilteredQs[gCurrentIdx];
  gRevealedAnswers[q.id] = !gRevealedAnswers[q.id];
  renderPracticeMode();
}

function renderFeedbackAndProvenance(q) {
  const banner   = document.getElementById("feedbackBanner");
  const drawer   = document.getElementById("answerProvenanceDrawer");
  const pBody    = document.getElementById("provenanceContent");

  const chosen   = gUserChoices[q.id];
  const revealed = gRevealedAnswers[q.id];
  const correct  = q.answer ? String(q.answer.option_index) : null;

  if (revealed && correct) {
    banner.classList.remove("hidden");
    if (chosen === correct) {
      banner.className = "feedback-banner correct";
      banner.innerHTML = `🎉 Correct! Option <strong>${correct}</strong> is the verified answer.`;
    } else if (chosen) {
      banner.className = "feedback-banner wrong";
      banner.innerHTML = `❌ Wrong. You chose <strong>${chosen}</strong> · Correct is <strong>${correct}</strong>`;
    } else {
      banner.className = "feedback-banner info";
      banner.innerHTML = `ℹ️ Official Answer: Option <strong>${correct}</strong>`;
    }
    drawer.classList.remove("hidden");
    pBody.innerHTML = `
      <strong>Option ${esc(String(q.answer.option_index))}</strong>
      ${q.answer.value ? `&nbsp;—&nbsp;${esc(q.answer.value)}` : ""}
      <br><small style="color:var(--txt-400)">
        Status: <code>${esc(q.answer.status || "verified")}</code> &nbsp;·&nbsp;
        Source: <code>${esc(q.answer.method || "official_key")}</code>
      </small>
    `;
  } else {
    banner.classList.add("hidden");
    drawer.classList.add("hidden");
  }
}

function prevQuestion() { if (gCurrentIdx > 0) { gCurrentIdx--; renderPracticeMode(); } }
function nextQuestion()  { if (gCurrentIdx < gFilteredQs.length - 1) { gCurrentIdx++; renderPracticeMode(); } }
function randomQuestion() {
  if (gFilteredQs.length > 1) {
    gCurrentIdx = Math.floor(Math.random() * gFilteredQs.length);
    renderPracticeMode();
  }
}

// =============================================================================
// 8. SOURCE PAPER VIEWER
// =============================================================================
function renderSourcePanel(q) {
  const docId    = q.document_id;
  const pageNum  = q.page || 1;

  // Find document entry
  const doc = (gVaultData.documents || []).find(d => d.id === docId);
  const renders = doc ? (doc.page_renders || {}) : {};

  gSourceDocId = docId;
  gSourcePage  = pageNum;

  const hasRenders = Object.keys(renders).length > 0;

  const viewer = document.getElementById("sourcePaperViewer");
  const empty  = document.getElementById("sourcePaperEmpty");

  if (!hasRenders) {
    viewer.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }

  viewer.classList.remove("hidden");
  empty.classList.add("hidden");

  showSourcePage(docId, pageNum, doc);
}

function showSourcePage(docId, pageNum, doc) {
  doc = doc || (gVaultData.documents || []).find(d => d.id === docId);
  const renders = doc ? (doc.page_renders || {}) : {};
  const keys    = Object.keys(renders).map(Number).sort((a, b) => a - b);
  const maxPage = keys.length > 0 ? Math.max(...keys) : 1;

  // Clamp page
  pageNum = Math.max(1, Math.min(pageNum, maxPage));
  gSourcePage = pageNum;

  // Update nav controls
  document.getElementById("sourcePageLabel").textContent = `Page ${pageNum} / ${maxPage}`;
  document.getElementById("sourcePrevPageBtn").disabled = pageNum <= 1;
  document.getElementById("sourceNextPageBtn").disabled = pageNum >= maxPage;

  const dataUri = renders[String(pageNum)] || renders[pageNum];
  const img     = document.getElementById("sourcePaperImg");

  if (dataUri) {
    img.src = dataUri;
    img.style.opacity = "0";
    img.onload = () => { img.style.opacity = "1"; };
  } else {
    img.src = "";
  }

  // Labels
  document.getElementById("sourcePaperLabel").textContent =
    doc ? `${doc.filename}` : "";
  document.getElementById("sourcePageHint").textContent =
    `Tap ‹ › to browse pages · Currently viewing page ${pageNum}`;
}

function sourcePageNav(delta) {
  const doc     = (gVaultData.documents || []).find(d => d.id === gSourceDocId);
  const renders = doc ? (doc.page_renders || {}) : {};
  const keys    = Object.keys(renders).map(Number).sort((a, b) => a - b);
  const maxPage = keys.length > 0 ? Math.max(...keys) : 1;

  gSourcePage = Math.max(1, Math.min(gSourcePage + delta, maxPage));
  showSourcePage(gSourceDocId, gSourcePage, doc);
}

function clearSourcePanel() {
  document.getElementById("sourcePaperImg").src = "";
  document.getElementById("sourcePaperLabel").textContent = "";
  document.getElementById("sourcePageHint").textContent = "";
  document.getElementById("sourcePaperEmpty").classList.remove("hidden");
  document.getElementById("sourcePaperViewer").classList.add("hidden");
}

// =============================================================================
// 9. FEED / BROWSE MODE
// =============================================================================
function renderFeedMode() {
  const container = document.getElementById("feedCardsList");
  container.innerHTML = "";

  if (gFilteredQs.length === 0) {
    container.innerHTML = `
      <div style="text-align:center; color:var(--txt-400); padding:3rem;">
        <div style="font-size:2rem; margin-bottom:0.75rem;">🔍</div>
        No questions found. Try a different filter.
      </div>`;
    return;
  }

  gFilteredQs.forEach((q, idx) => {
    const card = document.createElement("div");
    card.className = "feed-card";

    // Context block
    let ctxHtml = "";
    if (q.context && q.context.text) {
      ctxHtml = `
        <div class="feed-context-box">
          <div class="feed-context-label">📌 ${esc(q.context.label || "Direction")} · Q${q.context.question_start}–Q${q.context.question_end}</div>
          <div style="font-size:0.88rem; color:var(--txt-200); line-height:1.65; white-space:pre-wrap">${esc(q.context.text)}</div>
        </div>`;
    }

    // Math block
    let mathHtml = "";
    if (q.is_math && q.math && q.math.linear) {
      mathHtml = `<div class="math-block" style="margin:0.75rem 0; font-size:0.95rem; text-align:left; font-family:var(--font-mono); color:var(--brand-light);">${esc(q.math.linear)}</div>`;
    }

    // Options
    let optsHtml = "";
    (q.options || []).forEach(o => {
      const isCorrect = q.answer && String(q.answer.option_index) === String(o.index);
      optsHtml += `
        <div class="feed-option${isCorrect ? " correct" : ""}">
          <div class="feed-option-badge">${esc(o.label || String(o.index))}</div>
          <div class="feed-option-text">${esc(o.text || "")}${isCorrect ? '<span class="feed-answer-mark">✓ Correct</span>' : ""}</div>
        </div>`;
    });

    card.innerHTML = `
      <div class="question-meta-chips" style="margin-bottom:0.85rem;">
        <span class="chip chip-q">Q${q.number != null ? q.number : idx + 1}</span>
        <span class="chip chip-subj">${esc(q.subject || "")}</span>
        <span class="chip chip-topic">${esc(q.topic || "")}</span>
        <span class="chip chip-page">Page ${q.page || 1}</span>
        ${q.is_math ? '<span class="chip chip-math">∑ Math</span>' : ""}
      </div>
      ${ctxHtml}
      <div class="question-stem" style="font-size:1rem; margin-bottom:0.85rem;">${esc(q.stem || "")}</div>
      ${mathHtml}
      <div style="margin-top:0.5rem;">${optsHtml}</div>
    `;

    // Click to jump to practice mode at this question
    card.addEventListener("dblclick", () => {
      gCurrentIdx = idx;
      setMode("practice");
    });
    card.title = "Double-click to open in Practice Mode";

    container.appendChild(card);
  });
}

// =============================================================================
// 10. MATH HELPERS
// =============================================================================
function linearToLatex(linear) {
  if (!linear) return "";
  let s = String(linear);
  s = s.replace(/√\s*(\d+|\?)/g,     "\\sqrt{$1}");
  s = s.replace(/÷/g,                " \\div ");
  s = s.replace(/−/g,                " - ");
  s = s.replace(/×/g,                " \\times ");
  s = s.replace(/(\d+|\?)\s*x\s*(\d+|\?)/g, "$1 \\times $2");
  s = s.replace(/\(([^)]+)\)\/\(([^)]+)\)/g, "\\frac{$1}{$2}");
  s = s.replace(/(\d+)\/(\d+)/g,    "\\frac{$1}{$2}");
  return s;
}

// =============================================================================
// 11. SIDEBAR MOBILE TOGGLE
// =============================================================================
function toggleSidebar() {
  document.getElementById("sidebar").classList.toggle("open");
  document.getElementById("sidebarBackdrop").classList.toggle("hidden");
}
function closeMobileSidebar() {
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("sidebarBackdrop").classList.add("hidden");
}

// =============================================================================
// 12. UTILITIES
// =============================================================================
function safeId(str) {
  return String(str).replace(/[^a-zA-Z0-9_-]/g, "_");
}

// HTML-escape to prevent XSS / broken layouts from question text
function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
