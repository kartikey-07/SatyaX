/* ============================================================
   SatyaX — Frontend Logic
   ============================================================ */

"use strict";

// ── Tab Navigation ────────────────────────────────────────

let _newsLoaded = false;
let currentNewsPage = 1;
let currentNewsQuery = "";
const newsPageSize = 6;

function switchTab(name) {
  document.querySelectorAll(".tab-btn").forEach(b => {
    b.classList.remove("active");
    b.setAttribute("aria-selected", "false");
  });
  document.querySelectorAll(".tab-content").forEach(p => p.classList.remove("active"));

  document.getElementById(`tab-${name}`).classList.add("active");
  document.getElementById(`tab-${name}`).setAttribute("aria-selected", "true");
  document.getElementById(`panel-${name}`).classList.add("active");

  // Auto-load top headlines the first time news tab opens
  if (name === "news" && !_newsLoaded) {
    _newsLoaded = true;
    document.getElementById("newsQuery").value = "top headlines";
    fetchNews();
  }
}

// ── News Category Chip Selection ─────────────────────────

function selectNewsCategory(el, query) {
  // Update active chip
  document.querySelectorAll("#newsCategories .news-chip").forEach(c => c.classList.remove("active"));
  el.classList.add("active");
  // Set query and fetch
  document.getElementById("newsQuery").value = query;
  fetchNews();
}

// ── Fact Checker — Input Mode ─────────────────────────────

let inputMode = "text";

function setInputMode(mode) {
  inputMode = mode;
  document.getElementById("toggle-text").classList.toggle("active", mode === "text");
  document.getElementById("toggle-url").classList.toggle("active", mode === "url");
  document.getElementById("text-input-area").style.display = mode === "text" ? "block" : "none";
  document.getElementById("url-input-area").style.display = mode === "url" ? "block" : "none";
}

// ── Fact Checker — Analyze ────────────────────────────────

async function analyzeContent() {
  const text = document.getElementById("articleText").value.trim();
  const url  = document.getElementById("articleUrl").value.trim();

  if (!text && !url) {
    alert("⚠️ Please paste article text or enter a URL first.");
    return;
  }

  const btn = document.getElementById("analyzeBtn");
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-icon">⏳</span><span>Analyzing…</span>';

  // Show loader, hide old results
  document.getElementById("analyzeLoader").style.display = "block";
  document.getElementById("analysisResults").style.display = "none";
  animateSteps();

  let _errData = {};
  try {
    const resp = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, url })
    });

    const data = await resp.json();
    if (!resp.ok) {
      _errData = data;
      throw new Error(data.error || "Analysis failed");
    }

    document.getElementById("analyzeLoader").style.display = "none";
    renderAnalysis(data);
    document.getElementById("analysisResults").style.display = "flex";
    document.getElementById("analysisResults").scrollIntoView({ behavior: "smooth", block: "start" });

    // ── Show post-analysis action bar ──
    const bar = document.getElementById("postAnalysisBar");
    bar.style.display = "block";

    // ── Fallback scraper notice ──
    const layerNotice = document.getElementById("scrapeLayerNotice");
    const layerMsg    = document.getElementById("scrapeLayerMsg");
    if (data.scrape_layer && data.scrape_layer !== "primary") {
      const layerNames = {
        fallback: "newspaper3k fallback",
        beautifulsoup: "BeautifulSoup fallback",
        cache:   "Google Cache fallback",
        archive: "Archive.org fallback",
      };
      layerMsg.textContent = `Primary extraction failed. ${layerNames[data.scrape_layer] || "Fallback"} extraction used successfully.`;
      layerNotice.style.display = "flex";
    } else {
      layerNotice.style.display = "none";
    }

    // ── Save to localStorage history ──
    const inputText = text || url || "";
    saveToHistory(data, inputText);

    // Store current analysis data for Share/PDF
    window._lastAnalysisData = data;
    window._lastInputText    = inputText;

    // Reset share panel for new analysis
    document.getElementById("sharePanelInline").style.display = "none";
    const shareBtn = document.getElementById("shareBtn");
    shareBtn.disabled = false;
    shareBtn.innerHTML = "<span>🔗</span> Share Result";

  } catch (err) {
    document.getElementById("analyzeLoader").style.display = "none";
    console.error(err);
    showScrapeError(
      _errData.error || err.message,
      url,
      _errData.google_cache_url || null,
      _errData.archive_url || null
    );
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">⚡</span><span>Analyze Now</span>';
  }
}

// ── Scrape Error Panel ─────────────────────────────────────

function showScrapeError(message, origUrl, cacheUrl, archiveUrl) {
  // Remove old error panel if present
  const existing = document.getElementById("scrapeErrorPanel");
  if (existing) existing.remove();

  const isUrlError = cacheUrl || archiveUrl;
  const panel = document.createElement("div");
  panel.id = "scrapeErrorPanel";
  panel.className = "scrape-error-panel";
  panel.innerHTML = `
    <div class="sep-icon">🚫</div>
    <div class="sep-title">Could Not Extract Article</div>
    <div class="sep-msg">
      ${isUrlError
        ? `This site uses bot protection, a paywall, or restricts automated access.<br>
           <strong>Reuters, NYT, WSJ</strong> and similar sites block all scrapers.`
        : (message || "Analysis failed. Please try again.")}
    </div>
    ${isUrlError ? `
    <div class="sep-hint">Try one of these options to get the article text:</div>
    <div class="sep-actions">
      ${cacheUrl ? `<a href="${cacheUrl}" target="_blank" class="sep-btn sep-btn-cache">
        📋 Open Google Cache → Copy Text
      </a>` : ""}
      ${archiveUrl ? `<a href="${archiveUrl}" target="_blank" class="sep-btn sep-btn-archive">
        🗄️ Open Archive.org
      </a>` : ""}
      ${origUrl ? `<a href="${origUrl}" target="_blank" class="sep-btn sep-btn-orig">
        🔗 Open Original Article
      </a>` : ""}
    </div>
    <div class="sep-hint" style="margin-top:0.75rem;">
      Then paste the article text into the <strong>Text</strong> input and analyze.
    </div>` : ""}
    <button class="sep-close" onclick="document.getElementById('scrapeErrorPanel').remove()">✕ Dismiss</button>
  `;

  // Insert below the analyze button
  const btn = document.getElementById("analyzeBtn");
  btn.parentNode.insertBefore(panel, btn.nextSibling);
  panel.scrollIntoView({ behavior: "smooth", block: "center" });
}


// ── History (localStorage) ────────────────────────────────

const HISTORY_KEY = "pramanaai_history";

function saveToHistory(data, inputText) {
  try {
    const gemini  = data.gemini || {};
    const bert    = data.bert   || {};
    const verdict = gemini.verdict || bert.verdict || "UNVERIFIED";
    const ts      = typeof gemini.truth_score === "number" ? gemini.truth_score : null;

    const entry = {
      id:          Date.now(),
      title:       (inputText || "").substring(0, 80) || "(No input)",
      verdict:     verdict.toUpperCase(),
      truth_score: ts,
      timestamp:   new Date().toISOString(),
      inputText:   (inputText || "").substring(0, 500),
      analysis:    data,
      report_id:   null,   // filled in after share
    };

    const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    history.unshift(entry);
    if (history.length > 20) history.splice(20);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history));

    // Keep a reference to update with report_id later
    window._lastHistoryId = entry.id;
  } catch(e) {
    console.warn("History save failed:", e);
  }
}

function updateHistoryReportId(id, reportId) {
  try {
    const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    const entry   = history.find(e => e.id === id);
    if (entry) {
      entry.report_id = reportId;
      localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    }
  } catch(e) {}
}


// ── Share Result ──────────────────────────────────────────

async function shareResult() {
  const btn = document.getElementById("shareBtn");
  if (!window._lastAnalysisData) return;

  btn.disabled = true;
  btn.innerHTML = "<span>⏳</span> Saving…";

  try {
    const d    = window._lastAnalysisData;
    const gem  = d.gemini || {};
    const bert = d.bert   || {};

    const payload = {
      input_text:  window._lastInputText || "",
      verdict:     gem.verdict || bert.verdict || "UNVERIFIED",
      truth_score: gem.truth_score ?? 0,
      confidence:  gem.confidence_pct ?? bert.confidence_pct ?? 0,
      analysis:    d,
    };

    const resp = await fetch("/save-report", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
    });
    const result = await resp.json();

    if (!resp.ok) throw new Error(result.error || "Save failed");

    // Show inline share panel
    const panel = document.getElementById("sharePanelInline");
    document.getElementById("shareUrlInput").value = result.url;
    panel.style.display = "block";
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });

    btn.innerHTML = "<span>✓</span> Shared";
    btn.style.background = "rgba(16,185,129,0.15)";
    btn.style.color = "var(--real)";
    btn.style.borderColor = "var(--real-border)";
    btn.disabled = false;

    // Update PDF button to use the saved report
    const pdfBtn = document.getElementById("pdfBtn");
    pdfBtn.onclick = () => { window.location.href = `/export-pdf/${result.report_id}`; };

    // Update history entry
    if (window._lastHistoryId) {
      updateHistoryReportId(window._lastHistoryId, result.report_id);
    }
  } catch(e) {
    console.error("Share failed:", e);
    btn.disabled = false;
    btn.innerHTML = "<span>🔗</span> Share Result";
    alert("Share failed: " + e.message);
  }
}


// ── Download PDF (direct, no save required) ──────────────

async function downloadPDF() {
  const btn = document.getElementById("pdfBtn");
  if (!window._lastAnalysisData) return;

  btn.disabled = true;
  btn.innerHTML = "<span>⏳</span> Generating…";

  try {
    const d    = window._lastAnalysisData;
    const gem  = d.gemini || {};
    const bert = d.bert   || {};

    const payload = {
      input_text:  window._lastInputText || "",
      verdict:     gem.verdict || bert.verdict || "UNVERIFIED",
      truth_score: gem.truth_score ?? 0,
      confidence:  gem.confidence_pct ?? bert.confidence_pct ?? 0,
      analysis:    d,
    };

    const resp = await fetch("/export-pdf", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || "PDF generation failed");
    }

    // Trigger download
    const blob     = await resp.blob();
    const blobUrl  = URL.createObjectURL(blob);
    const a        = document.createElement("a");
    const filename = resp.headers.get("Content-Disposition")?.match(/filename="(.+)"/)?.[1]
                     || "PramanaAI_Report.pdf";
    a.href     = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);

    btn.innerHTML = "<span>✓</span> Downloaded";
    btn.style.background = "rgba(16,185,129,0.1)";
    btn.style.color = "var(--real)";
    setTimeout(() => {
      btn.disabled  = false;
      btn.innerHTML = "<span>⬇</span> Download PDF";
      btn.style.background = "";
      btn.style.color = "";
    }, 3000);
  } catch(e) {
    console.error("PDF failed:", e);
    btn.disabled  = false;
    btn.innerHTML = "<span>⬇</span> Download PDF";
    alert("PDF error: " + e.message);
  }
}


// ── Copy share URL ────────────────────────────────────────

function copyShareUrl() {
  const input   = document.getElementById("shareUrlInput");
  const copiedEl= document.getElementById("spiCopied");
  navigator.clipboard.writeText(input.value).then(() => {
    copiedEl.style.display = "block";
    setTimeout(() => { copiedEl.style.display = "none"; }, 2500);
  });
}


// ── Step Animator ─────────────────────────────────────────

function animateSteps() {
  const steps = ["step1", "step2", "step3", "step4"];
  steps.forEach(s => {
    document.getElementById(s).className = "loader-step";
  });
  let i = 0;
  const iv = setInterval(() => {
    if (i > 0) document.getElementById(steps[i - 1]).className = "loader-step done";
    if (i < steps.length) {
      document.getElementById(steps[i]).className = "loader-step active";
      i++;
    } else {
      clearInterval(iv);
    }
  }, 1800);
  window._stepInterval = iv;
}

const VERDICT_ICONS = {
  REAL:           "✅",
  FAKE:           "🚫",
  MISLEADING:     "⚠️",
  PARTIALLY_TRUE: "🔶",
  CONTEXT_NEEDED: "💬",
  UNVERIFIED:     "🔍"
};

const VERDICT_LABELS = {
  REAL:           "REAL NEWS",
  FAKE:           "FAKE NEWS",
  MISLEADING:     "MISLEADING",
  PARTIALLY_TRUE: "PARTIALLY TRUE",
  CONTEXT_NEEDED: "CONTEXT NEEDED",
  UNVERIFIED:     "UNVERIFIED"
};

const PARA_ICONS = {
  REAL:           "✅",
  FAKE:           "❌",
  MISLEADING:     "⚠️",
  CONTEXT_NEEDED: "💬"
};

function getTruthScoreHint(score) {
  if (score >= 90) return "Highly accurate — strongly supported by evidence.";
  if (score >= 70) return "Mostly accurate — minor gaps or unverified details.";
  if (score >= 50) return "Mixed accuracy — some claims verified, others not.";
  if (score >= 30) return "Low accuracy — significant false or misleading claims.";
  return "Very low accuracy — content appears largely false.";
}

function getReliabilityClass(score) {
  if (score >= 8) return "reliability-high";
  if (score >= 5) return "reliability-medium";
  return "reliability-low";
}

function getReliabilityLabel(score) {
  if (score >= 8) return "✓ Trusted";
  if (score >= 5) return "~ Moderate";
  return "⚠ Low";
}

function renderAnalysis(data) {
  // ── Primary verdict: prefer Gemini, fallback to BERT ──
  const gemini  = data.gemini;
  const bert    = data.bert;
  const hasGemini = !!gemini;

  const verdict    = hasGemini ? gemini.verdict        : bert.verdict;
  const confPct    = hasGemini ? gemini.confidence_pct : bert.confidence_pct;
  const verdictKey = (verdict || "FAKE").toUpperCase().replace(/ /g, "_");
  const cssClass   = verdictKey.toLowerCase();

  // Verdict banner
  const banner = document.getElementById("verdictBanner");
  banner.className = "verdict-banner " + cssClass;
  document.getElementById("verdictBadge").textContent  = VERDICT_ICONS[verdictKey]  || "❓";
  document.getElementById("verdictLabel").textContent  = VERDICT_LABELS[verdictKey] || verdict;
  document.getElementById("verdictSub").textContent    =
    data.scraped_from_url ? "Article extracted from URL and analyzed" : "Based on provided text";

  // Confidence bar
  document.getElementById("confidencePct").textContent = confPct + "%";
  requestAnimationFrame(() => {
    document.getElementById("confidenceBar").style.width = Math.min(confPct, 100) + "%";
  });

  // ── BERT Writing Style Analysis ──
  // Derive 4 style metrics from BERT's underlying fake/real probability
  const fakeProb = bert.verdict === 'FAKE'
    ? bert.confidence_pct
    : (100 - bert.confidence_pct);

  // Each metric is a deterministic function of the sensationalism signal
  const sensationalism  = Math.round(fakeProb);
  const clickbait       = Math.min(100, Math.round(fakeProb * 0.88 + 6));
  const emotionalLang   = Math.min(100, Math.round(fakeProb * 0.82 + 4));
  const styleConf       = bert.confidence_pct;

  function setMetricBar(barId, valId, pct) {
    const bar = document.getElementById(barId);
    const val = document.getElementById(valId);
    if (!bar || !val) return;
    val.textContent = pct + "%";
    // Color: low=green, medium=amber, high=red
    const color = pct >= 67 ? 'var(--fake)'
                : pct >= 34 ? 'var(--misleading)'
                :              'var(--real)';
    bar.style.background = color;
    requestAnimationFrame(() => { bar.style.width = pct + "%"; });
  }

  setMetricBar("bertSensBar",  "bertSensVal",  sensationalism);
  setMetricBar("bertClickBar", "bertClickVal", clickbait);
  setMetricBar("bertEmoBar",   "bertEmoVal",   emotionalLang);

  // Style confidence bar uses neutral purple color
  const confBar = document.getElementById("bertConfBar");
  document.getElementById("bertConfVal").textContent = styleConf + "%";
  requestAnimationFrame(() => {
    confBar.style.width = styleConf + "%";
  });

  // Overall style tag
  const styleTag = document.getElementById("bertStyleTag");
  if (styleTag) {
    let label, tagClass;
    if (sensationalism >= 67) {
      label = "⚠️ Sensational / Alarmist writing style detected";
      tagClass = "bert-tag-high";
    } else if (sensationalism >= 34) {
      label = "⚡ Moderately informal or emotive writing style";
      tagClass = "bert-tag-medium";
    } else {
      label = "✓ Formal / Journalistic writing style";
      tagClass = "bert-tag-low";
    }
    styleTag.textContent = label;
    styleTag.className = "bert-style-tag " + tagClass;
  }

  if (hasGemini) {
    // ── ELI5 Verdict ──
    if (gemini.eli5_verdict) {
      document.getElementById("eli5Box").textContent = gemini.eli5_verdict;
      document.getElementById("eli5Section").style.display = "block";
    }

    // ── Truth Score ──
    if (typeof gemini.truth_score === "number") {
      const ts = gemini.truth_score;
      document.getElementById("truthScoreNum").textContent = ts + "/100";
      document.getElementById("truthScoreHint").textContent = getTruthScoreHint(ts);
      // Color the bar: 0→red, 50→orange, 100→green via background-position
      const barPos = (100 - ts) + "%";
      const bar = document.getElementById("truthScoreBar");
      requestAnimationFrame(() => {
        bar.style.setProperty("--bar-pos", barPos);
        bar.style.width = ts + "%";
      });
      document.getElementById("truthScoreSection").style.display = "block";
    }

    // ── Summary ──
    if (gemini.summary) {
      document.getElementById("summaryBox").textContent = gemini.summary;
      document.getElementById("geminiSummarySection").style.display = "block";
    }

    // ── Evidence Found ──
    if (gemini.evidence_found && gemini.evidence_found.length > 0) {
      const list = document.getElementById("evidenceList");
      list.innerHTML = "";
      gemini.evidence_found.forEach(e => {
        const item = document.createElement("div");
        item.className = "evidence-item";
        item.innerHTML = `
          <span class="evidence-icon">✓</span>
          <span class="evidence-fact">${escHtml(e.fact || "")}</span>
          <span class="evidence-source">${escHtml(e.source || "")}</span>`;
        list.appendChild(item);
      });
      document.getElementById("evidenceSection").style.display = "block";
    }

    // ── Paragraph Breakdown ──
    if (gemini.paragraph_analysis && gemini.paragraph_analysis.length > 0) {
      const list = document.getElementById("paragraphList");
      list.innerHTML = "";
      gemini.paragraph_analysis.forEach(para => {
        const vk = (para.verdict || "MISLEADING").toUpperCase();
        const item = document.createElement("div");
        item.className = "para-item " + vk;
        item.innerHTML = `
          <div class="para-icon">${PARA_ICONS[vk] || "❓"}</div>
          <div class="para-body">
            <div class="para-quote">"${escHtml(para.text || "")}"</div>
            <span class="para-verdict-tag ${vk}">${vk.replace(/_/g," ")}</span>
            <div class="para-explanation">${escHtml(para.explanation || "")}</div>
          </div>`;
        list.appendChild(item);
      });
      document.getElementById("paragraphSection").style.display = "block";
    }

    // ── Key Claims ──
    if (gemini.key_claims && gemini.key_claims.length > 0) {
      const list = document.getElementById("claimsList");
      list.innerHTML = "";
      gemini.key_claims.forEach(c => {
        const vk = (c.verdict || "UNVERIFIED").toUpperCase();
        const icons = { TRUE: "✅", FALSE: "❌", UNVERIFIED: "🔍" };
        const item = document.createElement("div");
        item.className = "claim-item";
        item.innerHTML = `
          <span class="claim-verdict ${vk}">${icons[vk] || ""} ${vk}</span>
          <div class="claim-body">
            <div class="claim-text">${escHtml(c.claim || "")}</div>
            <div class="claim-note">${escHtml(c.note || "")}</div>
          </div>`;
        list.appendChild(item);
      });
      document.getElementById("claimsSection").style.display = "block";
    }

    // ── Clarification ──
    if (gemini.confusion_clarification) {
      document.getElementById("clarificationBox").textContent = gemini.confusion_clarification;
      document.getElementById("clarificationSection").style.display = "block";
    }

  } else {
    // BERT-only mode
    const summaryBox = document.getElementById("summaryBox");
    summaryBox.textContent =
      "Gemini AI is not configured — showing BERT-only result. Add your GEMINI_API_KEY to .env for full paragraph-level analysis, claim verification, and evidence-based scoring.";
    document.getElementById("geminiSummarySection").style.display = "block";
  }

  // ── Related Articles (with reliability badges) ──
  const relList = document.getElementById("relatedList");
  relList.innerHTML = "";
  const articles = data.related_articles || [];

  if (articles.length === 0) {
    relList.innerHTML = '<p style="color:var(--text-dim);font-size:0.85rem;">No related articles found.</p>';
  } else {
    articles.forEach(a => {
      const rel = typeof a.reliability === "number" ? a.reliability : 5;
      const relClass = getReliabilityClass(rel);
      const relLabel = getReliabilityLabel(rel);
      const card = document.createElement("a");
      card.className = "related-card";
      card.href = a.url || "#";
      card.target = "_blank";
      card.rel = "noopener noreferrer";
      card.innerHTML = `
        <div class="related-source">${escHtml(a.source || "Source")}</div>
        <div class="related-title">${escHtml(a.title || "")}</div>
        <div class="related-snippet">${escHtml(a.snippet || "")}</div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:0.4rem;">
          <div class="related-date">${formatDate(a.date)}</div>
          <span class="reliability-badge ${relClass}" title="Source reliability: ${rel}/10">
            ${relLabel} &nbsp;${rel}/10
          </span>
        </div>`;
      relList.appendChild(card);
    });
  }

  document.getElementById("relatedSection").style.display = "block";
}


// ── Comedy Generator ──────────────────────────────────────

let lastGeneratedHeadline = "";

async function generateComedy() {
  const topic = document.getElementById("seedText").value.trim();
  if (!topic) {
    alert("⚠️ Please enter a topic first.");
    return;
  }

  const btn = document.getElementById("generateBtn");
  btn.disabled = true;
  document.getElementById("comedyLoader").style.display = "flex";
  document.getElementById("comedyResult").style.display = "none";

  try {
    const resp = await fetch("/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic })
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Generation failed");

    lastGeneratedHeadline = data.headline;

    // Show engine badge
    const engineLabel = data.engine === 'gemini' ? '✨ Powered by Gemini AI' : '⚙️ Powered by GPT-2';
    const engineColor = data.engine === 'gemini' ? 'var(--real)' : 'var(--text-muted)';

    // Populate
    document.getElementById("tickerText").textContent = data.headline;
    document.getElementById("comedyHeadline").textContent = data.headline;

    const body = document.getElementById("comedyArticleBody");
    body.innerHTML = '';
    // Engine badge
    const badge = document.createElement('div');
    badge.style.cssText = 'font-size:0.72rem;font-weight:600;color:' + engineColor + ';margin-bottom:0.75rem;letter-spacing:0.04em;';
    badge.textContent = engineLabel;
    body.appendChild(badge);
    (data.article || []).forEach(para => {
      const p = document.createElement("p");
      p.className = "comedy-para";
      p.textContent = para;
      body.appendChild(p);
    });

    document.getElementById("comedyDisclaimer").textContent = data.disclaimer || "";
    document.getElementById("comedyResult").style.display = "block";
  } catch (err) {
    console.error(err);
    alert("❌ Error: " + err.message);
  } finally {
    btn.disabled = false;
    document.getElementById("comedyLoader").style.display = "none";
  }
}

function setTopic(topic) {
  document.getElementById("seedText").value = topic;
  generateComedy();
}

function copyComedy() {
  if (!lastGeneratedHeadline) return;
  navigator.clipboard.writeText(lastGeneratedHeadline).then(() => {
    alert("✅ Headline copied to clipboard!");
  });
}

function factCheckGenerated() {
  if (!lastGeneratedHeadline) return;
  switchTab("checker");
  setInputMode("text");
  document.getElementById("articleText").value = lastGeneratedHeadline;
  document.getElementById("articleText").focus();
}

// ── Live News ─────────────────────────────────────────────

async function fetchNews(isLoadMore = false) {
  const queryInput = document.getElementById("newsQuery").value.trim() || "technology";
  const container = document.getElementById("newsResults");
  const loadMoreContainer = document.getElementById("loadMoreNewsContainer");
  const loadMoreBtn = document.getElementById("loadMoreNewsBtn");

  if (!isLoadMore) {
    currentNewsPage = 1;
    currentNewsQuery = queryInput;
    container.innerHTML = "";
    if (loadMoreContainer) {
      loadMoreContainer.style.display = "none";
    }
  }

  document.getElementById("newsLoader").style.display = "flex";
  if (loadMoreBtn) {
    loadMoreBtn.disabled = true;
    loadMoreBtn.innerHTML = "<span>⏳</span> Loading...";
  }

  try {
    const url = `/fetch_news?q=${encodeURIComponent(currentNewsQuery)}&page=${currentNewsPage}&pageSize=${newsPageSize}`;
    const resp = await fetch(url);
    const data = await resp.json();
    document.getElementById("newsLoader").style.display = "none";
    if (loadMoreBtn) {
      loadMoreBtn.disabled = false;
      loadMoreBtn.innerHTML = "<span>➕</span> Load More";
    }

    if (data.error) {
      if (!isLoadMore) {
        container.innerHTML = `<p style="color:var(--fake);text-align:center;padding:2rem;">${escHtml(data.error)}</p>`;
      } else {
        alert(data.error);
      }
      return;
    }

    const articles = data.articles || [];
    if (articles.length === 0) {
      if (!isLoadMore) {
        container.innerHTML = '<p style="color:var(--text-dim);text-align:center;padding:2rem;">No articles found.</p>';
      } else {
        if (loadMoreContainer) {
          loadMoreContainer.style.display = "none";
        }
      }
      return;
    }

    articles.forEach(article => {
      const card = document.createElement("div");
      card.className = "news-card";

      const imgHtml = article.urlToImage
        ? `<img class="news-card-image" src="${escAttr(article.urlToImage)}" alt="${escAttr(article.title)}" loading="lazy" onerror="this.style.display='none'" />`
        : "";

      card.innerHTML = `
        ${imgHtml}
        <div class="news-card-body">
          <div class="news-card-source">${escHtml(article.source)}</div>
          <div class="news-card-title">${escHtml(article.title)}</div>
          <div class="news-card-content">${escHtml(article.content || "")}</div>
          <div class="news-card-date">${formatDate(article.publishedAt)}</div>
          <div class="news-card-actions">
            <button class="btn-fact-check">🔍 Fact-Check</button>
            <a class="btn-read-more" href="${escAttr(article.url)}" target="_blank" rel="noopener noreferrer">🔗 Read</a>
          </div>
        </div>`;

      // Attach event listener safely — avoids JSON.stringify quote-clash in onclick=""
      card.querySelector(".btn-fact-check").addEventListener("click", () => {
        factCheckArticle(article.title, article.url);
      });

      container.appendChild(card);
    });

    // Show/hide "Load More" button based on whether we have more articles
    const loadedCount = container.children.length;
    const totalResults = data.total_results || 0;
    if (loadMoreContainer) {
      if (loadedCount < totalResults && articles.length === newsPageSize) {
        loadMoreContainer.style.display = "block";
      } else {
        loadMoreContainer.style.display = "none";
      }
    }

  } catch (err) {
    document.getElementById("newsLoader").style.display = "none";
    if (loadMoreBtn) {
      loadMoreBtn.disabled = false;
      loadMoreBtn.innerHTML = "<span>➕</span> Load More";
    }
    console.error(err);
    if (!isLoadMore) {
      container.innerHTML = `<p style="color:var(--fake);text-align:center;padding:2rem;">❌ Failed to fetch news.</p>`;
    } else {
      alert("Failed to load more news.");
    }
  }
}

async function loadMoreNews() {
  currentNewsPage++;
  await fetchNews(true);
}

function factCheckArticle(title, url) {
  switchTab("checker");
  if (url) {
    setInputMode("url");
    document.getElementById("articleUrl").value = url;
  } else {
    setInputMode("text");
    document.getElementById("articleText").value = title;
  }
  // Auto-scroll and trigger analysis
  document.getElementById("panel-checker").scrollIntoView({ behavior: "smooth" });
  setTimeout(() => analyzeContent(), 300);
}

// ── Utilities ─────────────────────────────────────────────

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escAttr(str) {
  return String(str).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  try {
    return new Date(dateStr).toLocaleDateString("en-IN", {
      day: "numeric", month: "short", year: "numeric"
    });
  } catch {
    return dateStr;
  }
}
