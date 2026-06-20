import os
import re
import json
import random
import sqlite3
import string
import requests
import torch
from io import BytesIO
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file, redirect
from transformers import BertTokenizer, BertForSequenceClassification
from transformers import GPT2LMHeadModel, GPT2Tokenizer
from dotenv import load_dotenv

# ── ReportLab (PDF Export) ──
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor, white, black
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table,
        TableStyle, HRFlowable, KeepTogether, Image
    )
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False
    print("[WARN] reportlab not installed — PDF export disabled")

load_dotenv()

app = Flask(__name__)

# ─────────────────────────────────────────────
# Model Loading
# ─────────────────────────────────────────────

print("[*] Loading BERT model...")
BERT_MODEL_PATH = "saved_fake_news_model"
bert_tokenizer = BertTokenizer.from_pretrained(BERT_MODEL_PATH)
bert_model = BertForSequenceClassification.from_pretrained(BERT_MODEL_PATH)
bert_model.eval()
LABELS = ["FAKE", "REAL"]

print("[*] Loading GPT-2 model...")
gpt2_tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
gpt2_model = GPT2LMHeadModel.from_pretrained("gpt2")
gpt2_model.eval()

# ─────────────────────────────────────────────
# API Configuration
# ─────────────────────────────────────────────

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GEMINI_MODEL = "gemini-flash-lite-latest"
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + GEMINI_MODEL + ":generateContent"
)

gemini_client = bool(GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here")
if gemini_client:
    print("[OK] Gemini REST API configured (" + GEMINI_MODEL + ")")
else:
    print("[WARN] No Gemini API key found -- running in BERT-only mode.")

# ─────────────────────────────────────────────
# SQLite — Reports Database
# ─────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "satyax.db")

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id   TEXT UNIQUE NOT NULL,
                input_text  TEXT,
                verdict     TEXT,
                truth_score INTEGER,
                confidence  INTEGER,
                analysis_json TEXT,
                created_at  TEXT DEFAULT (strftime('%Y-%m-%d %H:%M UTC', 'now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT,
                input_text  TEXT,
                verdict     TEXT,
                truth_score INTEGER,
                created_at  TEXT DEFAULT (strftime('%Y-%m-%d %H:%M UTC', 'now'))
            )
        """)
        conn.commit()

init_db()
print("[OK] SQLite reports DB ready:", DB_PATH)

# Add user_id column if it doesn't exist (safe migration)
try:
    with sqlite3.connect(DB_PATH) as _conn:
        _conn.execute("ALTER TABLE reports ADD COLUMN user_id TEXT")
        _conn.commit()
except Exception:
    pass  # Column already exists


def generate_report_id() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "SX-" + "".join(random.choices(chars, k=6))


# ── Import Clerk Auth (after DB init, before routes) ──
from auth import (
    require_auth, require_admin, optional_auth, auth_context,
    get_current_user, get_current_user_full, list_clerk_users, get_clerk_user_count,
    CLERK_PUBLISHABLE_KEY, CLERK_FRONTEND_API
)


# ─────────────────────────────────────────────
# PDF Report Generation
# ─────────────────────────────────────────────

def generate_pdf_report(report: dict) -> bytes:
    """Generate a professional PDF verification report using ReportLab."""
    if not REPORTLAB_OK:
        raise RuntimeError("reportlab not installed")

    buf = BytesIO()

    # Color palette
    C_DARK    = HexColor("#0e1528")
    C_PRIMARY = HexColor("#8b5cf6")
    C_REAL    = HexColor("#10b981")
    C_FAKE    = HexColor("#ef4444")
    C_MISLEAD = HexColor("#f59e0b")
    C_TEXT    = HexColor("#1e293b")
    C_MUTED   = HexColor("#64748b")
    C_LIGHT   = HexColor("#f8fafc")
    C_BORDER  = HexColor("#e2e8f0")

    verdict = (report.get("verdict") or "").upper()
    VERDICT_COLOR = {
        "REAL": C_REAL, "FAKE": C_FAKE,
        "MISLEADING": C_MISLEAD,
        "PARTIALLY_TRUE": HexColor("#f97316"),
        "CONTEXT_NEEDED": C_PRIMARY,
        "UNVERIFIED": HexColor("#94a3b8"),
    }.get(verdict, C_MUTED)

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
        title=f"SatyaX Report {report.get('report_id', '')}",
        author="SatyaX"
    )

    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    H1   = S("H1",   fontSize=20, fontName="Helvetica-Bold",  textColor=C_TEXT,   spaceAfter=4)
    H2   = S("H2",   fontSize=13, fontName="Helvetica-Bold",  textColor=C_TEXT,   spaceBefore=14, spaceAfter=6)
    BODY = S("Body", fontSize=9,  fontName="Helvetica",       textColor=C_TEXT,   leading=14, spaceAfter=4)
    MUTED= S("Mute", fontSize=8,  fontName="Helvetica",       textColor=C_MUTED,  leading=12, spaceAfter=3)
    SUB  = S("Sub",  fontSize=10, fontName="Helvetica",       textColor=C_MUTED,  spaceAfter=16)

    story = []
    analysis  = report.get("analysis", {}) or {}
    gemini    = analysis.get("gemini", {}) or {}
    bert      = analysis.get("bert", {}) or {}
    related   = analysis.get("related_articles", []) or []
    ts        = report.get("truth_score", 0) or 0
    conf      = report.get("confidence", 0) or 0

    verdict_label = {
        "REAL": "✓ REAL", "FAKE": "✗ FAKE",
        "MISLEADING": "⚠ MISLEADING",
        "PARTIALLY_TRUE": "◐ PARTIALLY TRUE",
        "CONTEXT_NEEDED": "? CONTEXT NEEDED",
        "UNVERIFIED": "⬡ UNVERIFIED",
    }.get(verdict, verdict or "—")

    # ── Header ──
    _rid = report.get("report_id", "\u2014")
    _cat = report.get("created_at", "\u2014")
    _logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.jpg")
    _logo_cell = Image(_logo_path, width=1.1*cm, height=1.1*cm) if os.path.exists(_logo_path) else Paragraph('<font size="20" color="#8b5cf6"><b>SX</b></font>', BODY)
    hdr = [[ _logo_cell,
             Paragraph(f'<font size="18" color="#8b5cf6"><b>Satya<font color="#06b6d4">X</font></b></font>', BODY),
             Paragraph(f'<font size="7.5" color="#94a3b8">Report: <b>{_rid}</b><br/>Generated: {_cat}</font>', BODY) ]]
    ht = Table(hdr, colWidths=["8%","52%","40%"])
    ht.setStyle(TableStyle([
        ("ALIGN",(2,0),(2,0),"RIGHT"), ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BOTTOMPADDING",(0,0),(-1,-1),10),
    ]))
    story += [ht, HRFlowable(width="100%", thickness=2, color=C_PRIMARY), Spacer(1,0.2*cm),
              Paragraph("Evidence-Based Verification Report", SUB)]

    # ── Section 1: Executive Summary ──
    story.append(Paragraph("Executive Summary", H2))
    exec_data = [
        ["VERDICT", "TRUTH SCORE", "AI CONFIDENCE"],
        [verdict_label, f"{ts} / 100", f"{conf}%"],
    ]
    et = Table(exec_data, colWidths=["34%","33%","33%"])
    et.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),C_DARK), ("TEXTCOLOR",(0,0),(-1,0),white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"), ("FONTSIZE",(0,0),(-1,0),8),
        ("ALIGN",(0,0),(-1,-1),"CENTER"), ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("BACKGROUND",(0,1),(-1,1),C_LIGHT),
        ("FONTNAME",(0,1),(0,1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,1),(0,1),VERDICT_COLOR),
        ("FONTSIZE",(0,1),(-1,1),11),
        ("GRID",(0,0),(-1,-1),0.5,C_BORDER),
    ]))
    story.append(et)
    eli5 = gemini.get("eli5_verdict","")
    if eli5:
        story += [Spacer(1,0.2*cm), Paragraph(f"<i>{eli5}</i>", MUTED)]

    # ── Section 2: Original Input ──
    story += [HRFlowable(width="100%",thickness=0.5,color=C_BORDER), Paragraph("Original Input", H2)]
    input_text = (report.get("input_text") or "")[:800]
    story.append(Paragraph(input_text or "(No input text provided)", BODY))

    # ── Section 3: Writing Style Analysis ──
    story += [HRFlowable(width="100%",thickness=0.5,color=C_BORDER), Paragraph("Writing Style Analysis (BERT)", H2)]
    story.append(Paragraph("Evaluates linguistic patterns only — not factual accuracy.", MUTED))
    bv   = bert.get("verdict","FAKE")
    bc   = bert.get("confidence_pct", 50)
    fp   = bc if bv == "FAKE" else (100 - bc)
    def lvl(p): return "High" if p>=67 else "Medium" if p>=34 else "Low"
    bd   = [["Metric","Score","Risk Level"],
            ["Sensationalism Risk",  f"{round(fp)}%",              lvl(fp)],
            ["Clickbait Probability",f"{min(100,round(fp*.88+6))}%", lvl(fp)],
            ["Emotional Language",   f"{min(100,round(fp*.82+4))}%", lvl(fp)],
            ["Style Confidence",     f"{bc}%",                     "Model Confidence"]]
    bt = Table(bd, colWidths=["50%","25%","25%"])
    bt.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),C_DARK), ("TEXTCOLOR",(0,0),(-1,0),white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),8.5), ("ALIGN",(1,0),(-1,-1),"CENTER"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[white,C_LIGHT]),
        ("GRID",(0,0),(-1,-1),0.5,C_BORDER),
    ]))
    story.append(bt)

    # ── Section 4: Key Claims ──
    claims = gemini.get("claims", []) or []
    if claims:
        story += [HRFlowable(width="100%",thickness=0.5,color=C_BORDER),
                  Paragraph("Extracted Claims Analysis", H2)]
        for i, cl in enumerate(claims[:5], 1):
            ct = (cl.get("claim","") if isinstance(cl,dict) else str(cl))[:160]
            cs = (cl.get("status","") if isinstance(cl,dict) else "")
            ce = (cl.get("evidence","") if isinstance(cl,dict) else "")[:120]
            rows = [[f"Claim {i}", ct]]
            if cs: rows.append(["Status", cs])
            if ce: rows.append(["Evidence", ce])
            clT = Table(rows, colWidths=["20%","80%"])
            clT.setStyle(TableStyle([
                ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
                ("FONTSIZE",(0,0),(-1,-1),8.5), ("VALIGN",(0,0),(-1,-1),"TOP"),
                ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
                ("LEFTPADDING",(0,0),(-1,-1),6),
                ("BACKGROUND",(0,0),(0,-1),C_LIGHT), ("TEXTCOLOR",(0,0),(0,-1),C_MUTED),
                ("GRID",(0,0),(-1,-1),0.5,C_BORDER),
            ]))
            story += [clT, Spacer(1,0.1*cm)]

    # ── Section 5: Evidence ──
    if related:
        story += [HRFlowable(width="100%",thickness=0.5,color=C_BORDER),
                  Paragraph("Evidence & Related Sources", H2)]
        ed = [["Source","Reliability","Title / Summary"]]
        for art in related[:5]:
            src = (art.get("source") or "Unknown")[:18]
            rel = art.get("reliability", 5)
            tit = (art.get("title") or art.get("snippet") or "")[:75]
            rl  = "Trusted" if rel>=8 else "Moderate" if rel>=5 else "Low"
            ed.append([src, f"{rel}/10 ({rl})", tit])
        eT = Table(ed, colWidths=["22%","22%","56%"])
        eT.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),C_DARK), ("TEXTCOLOR",(0,0),(-1,0),white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),8), ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
            ("LEFTPADDING",(0,0),(-1,-1),5),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[white,C_LIGHT]),
            ("GRID",(0,0),(-1,-1),0.5,C_BORDER),
        ]))
        story.append(eT)

    # ── Section 6: AI Reasoning ──
    summary = gemini.get("summary","")
    if summary:
        story += [HRFlowable(width="100%",thickness=0.5,color=C_BORDER),
                  Paragraph("AI Reasoning Summary", H2),
                  Paragraph(summary[:600], BODY)]

    # ── Section 7: Architecture ──
    story += [HRFlowable(width="100%",thickness=0.5,color=C_BORDER),
              Paragraph("Analysis Pipeline", H2)]
    _drep  = report.get('report_id', '\u2014')
    _dtime = report.get('created_at', '\u2014')
    pipeline = [
        "User Input", "Content Extraction (Trafilatura / BeautifulSoup)",
        "Writing Style Analysis (BERT)", "Claim Extraction (Gemini AI)",
        "Real-Time Evidence Retrieval (Web Search)", "Source Reliability Assessment",
        "AI Fact Verification Engine (Gemini Flash)",
        f"Truth Score Generated: {ts}/100", f"Final Verdict: {verdict_label}",
    ]
    aD = [[ Paragraph(f'<font color="#6366f1">{"↓ " if i>0 else ""}Step {i+1}</font>  —  {s}', BODY) ]
          for i,s in enumerate(pipeline)]
    aT = Table(aD, colWidths=["100%"])
    aT.setStyle(TableStyle([
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),10),
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[C_LIGHT,white]),
    ]))
    story.append(aT)

    # ── Section 8: Disclaimer ──
    story += [Spacer(1,0.5*cm), HRFlowable(width="100%",thickness=1.5,color=C_PRIMARY), Spacer(1,0.2*cm),
              Paragraph(
                  f"DISCLAIMER: This report was generated by PramanaAI, an AI-assisted evidence-based "
                  f"verification platform. Results reflect publicly available information and real-time web "
                  f"search at the time of analysis. This is not a substitute for expert judgment. "
                  f"Report ID: {report.get('report_id','—')} | {report.get('created_at','—')}",
                  MUTED)]

    doc.build(story)
    buf.seek(0)
    return buf.read()

# ─────────────────────────────────────────────
# Helper: BERT Classification
# ─────────────────────────────────────────────

def bert_classify(text: str):
    """Returns (label, confidence_pct) using BERT."""
    inputs = bert_tokenizer(
        text[:512], return_tensors="pt",
        padding=True, truncation=True
    )
    with torch.no_grad():
        logits = bert_model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0]
        pred_id = torch.argmax(probs).item()
    return LABELS[pred_id], round(probs[pred_id].item() * 100, 1)


# ─────────────────────────────────────────────
# Helper: DuckDuckGo News Search
# ─────────────────────────────────────────────

def search_related_news(query: str, max_results: int = 5):
    """Search DuckDuckGo for related news. No API key needed."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.news(query[:200], max_results=max_results))
        return results
    except Exception as e:
        print(f"DDG search error: {e}")
        return []


# ─────────────────────────────────────────────
# Helper: URL Article Scraper (multi-layer fallback)
# ─────────────────────────────────────────────

SCRAPER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def _scrape_trafilatura(url: str):
    """Layer 1: Trafilatura — best quality extraction."""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
                favor_recall=True,
            )
            if text and len(text.strip()) > 100:
                return text.strip()
    except Exception as e:
        print(f"[Trafilatura] {e}")
    return None


def _scrape_newspaper(url: str):
    """Layer 2: newspaper3k — good for news sites."""
    try:
        from newspaper import Article
        article = Article(url)
        article.download()
        article.parse()
        text = article.text.strip()
        if text and len(text) > 100:
            return text
    except Exception as e:
        print(f"[newspaper3k] {e}")
    return None


def _scrape_beautifulsoup(url: str):
    """Layer 3: requests + BeautifulSoup — raw fallback."""
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, headers=SCRAPER_HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "aside", "form", "iframe", "noscript", "ads"]):
            tag.decompose()

        # Try common article containers first
        article_body = None
        for selector in ["article", "[class*='article-body']", "[class*='story-body']",
                         "[class*='post-content']", "[class*='entry-content']",
                         "main", ".content", "#content"]:
            article_body = soup.select_one(selector)
            if article_body:
                break

        if article_body:
            paragraphs = article_body.find_all("p")
        else:
            paragraphs = soup.find_all("p")

        text = "\n\n".join(
            p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 40
        )
        if text and len(text) > 100:
            return text.strip()
    except Exception as e:
        print(f"[BeautifulSoup] {e}")
    return None


def _scrape_google_cache(url: str):
    """Layer 4: Google Cache — works for many bot-protected news sites."""
    try:
        cache_url = "https://webcache.googleusercontent.com/search?q=cache:" + url
        resp = requests.get(cache_url, headers=SCRAPER_HEADERS, timeout=15)
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        paragraphs = soup.find_all("p")
        text = "\n\n".join(
            p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 40
        )
        if text and len(text) > 100:
            return text.strip()
    except Exception as e:
        print(f"[GoogleCache] {e}")
    return None


def _scrape_archive_org(url: str):
    """Layer 5: Archive.org Wayback Machine — fallback for paywalled/protected sites."""
    try:
        # Check if a recent snapshot exists
        api_url = f"https://archive.org/wayback/available?url={url}"
        check = requests.get(api_url, timeout=10)
        check.raise_for_status()
        data = check.json()
        snapshot = data.get("archived_snapshots", {}).get("closest", {})
        if not snapshot.get("available"):
            return None
        archive_url = snapshot.get("url", "")
        if not archive_url:
            return None
        resp = requests.get(archive_url, headers=SCRAPER_HEADERS, timeout=20)
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        article_body = None
        for selector in ["article", "[class*='article-body']", "[class*='story-body']",
                         "[class*='post-content']", "main"]:
            article_body = soup.select_one(selector)
            if article_body:
                break
        paragraphs = (article_body or soup).find_all("p")
        text = "\n\n".join(
            p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 40
        )
        if text and len(text) > 100:
            return text.strip()
    except Exception as e:
        print(f"[Archive.org] {e}")
    return None



def scrape_article_from_url(url: str):
    """
    Multi-layer article scraper. Returns (text, layer_name) or (None, None).
    Layer 1: Trafilatura    → "primary"
    Layer 2: newspaper3k   → "fallback"
    Layer 3: BeautifulSoup → "beautifulsoup"
    Layer 4: Google Cache  → "cache"
    Layer 5: Archive.org   → "archive"
    """
    text = _scrape_trafilatura(url)
    if text:
        print(f"[Scraper] Trafilatura OK ({len(text)} chars)")
        return text, "primary"

    text = _scrape_newspaper(url)
    if text:
        print(f"[Scraper] newspaper3k OK ({len(text)} chars)")
        return text, "fallback"

    text = _scrape_beautifulsoup(url)
    if text:
        print(f"[Scraper] BeautifulSoup OK ({len(text)} chars)")
        return text, "beautifulsoup"

    text = _scrape_google_cache(url)
    if text:
        print(f"[Scraper] Google Cache OK ({len(text)} chars)")
        return text, "cache"

    text = _scrape_archive_org(url)
    if text:
        print(f"[Scraper] Archive.org OK ({len(text)} chars)")
        return text, "archive"

    print("[Scraper] All 5 layers failed for:", url)
    return None, None


# Trusted source reliability map (domain → score out of 10)
SOURCE_RELIABILITY = {
    "bbc": 9, "reuters": 10, "apnews": 10, "bloomberg": 9, "nytimes": 9,
    "theguardian": 9, "wsj": 9, "washingtonpost": 9, "ndtv": 8, "thehindu": 8,
    "hindustantimes": 8, "timesofindia": 7, "indianexpress": 8, "aljazeera": 8,
    "cnn": 8, "foxnews": 6, "breitbart": 3, "theonion": 1, "fifa": 10,
    "who": 10, "un": 10, "gov": 9, "edu": 8, "wikipedia": 6,
}

def get_source_reliability(url: str) -> int:
    """Return reliability score 1-10 based on source domain."""
    if not url:
        return 5
    url_lower = url.lower()
    for domain, score in SOURCE_RELIABILITY.items():
        if domain in url_lower:
            return score
    return 5  # Unknown source default


def gemini_analyze(text: str, search_results: list):
    """Use Gemini Flash Lite via REST API for deep, nuanced fact-checking."""
    if not gemini_client:
        return None

    snippets = "\n".join([
        "- [" + r.get("source", "Source") + "] " + r.get("title", "") + ": " + r.get("body", "")[:180]
        for r in search_results[:5]
    ])

    prompt = (
        "You are an expert, evidence-based fact-checker. Analyze the following news content with precision.\n\n"
        "NEWS CONTENT:\n" + text[:3000] + "\n\n"
        "RELATED NEWS FROM WEB:\n" + (snippets if snippets else "No related articles found.") + "\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. If the text is a factually ACCURATE informational statement, label it REAL — do NOT call it MISLEADING.\n"
        "2. Use MISLEADING only if the text contains a claim that is technically true but intentionally distorts or omits crucial context to deceive.\n"
        "3. Use CONTEXT_NEEDED if the statement is accurate but lacks background context a reader would need to fully understand it.\n"
        "4. Use UNVERIFIED if there is insufficient evidence to confirm or deny the claims.\n"
        "5. Use PARTIALLY_TRUE only if some specific claims are true and others are false.\n"
        "6. Extract INDIVIDUAL verifiable claims — not vague summaries.\n"
        "7. truth_score (0-100): 100 = fully verified accurate, 0 = completely false.\n"
        "8. eli5_verdict: explain the verdict in one simple sentence a 10-year-old would understand.\n\n"
        "Respond ONLY with a valid JSON object (no markdown, no extra text):\n"
        '{"verdict":"REAL"|"FAKE"|"MISLEADING"|"PARTIALLY_TRUE"|"CONTEXT_NEEDED"|"UNVERIFIED",'
        '"confidence_pct":<0-100>,'
        '"truth_score":<0-100>,'
        '"eli5_verdict":"<one simple sentence verdict for a general audience>",'
        '"summary":"<2-3 sentence evidence-based assessment>",'
        '"evidence_found":[{"fact":"<specific verified fact>","source":"<source name>"}],'
        '"paragraph_analysis":[{"text":"<first 60 chars>","verdict":"REAL"|"FAKE"|"MISLEADING"|"CONTEXT_NEEDED","explanation":"<one specific sentence>"}],'
        '"key_claims":[{"claim":"<specific verifiable claim>","verdict":"TRUE"|"FALSE"|"UNVERIFIED","note":"<brief evidence-based note>"}],'
        '"confusion_clarification":"<Explain precisely: what is accurate, what is missing context, and what readers should know. Be specific, not generic.",'
        '"real_sources":[{"title":"<title>","url":"<url>"}]}'
    )

    try:
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY
        }
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(GEMINI_API_URL, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError as e:
        print("Gemini JSON parse error:", e)
    except Exception as e:
        print("Gemini error:", e)
    return None


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("index.html", **auth_context())


@app.route("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html", **auth_context())


@app.route("/methodology")
def methodology():
    return render_template("methodology.html", **auth_context())


@app.route("/faq")
def faq():
    return render_template("faq.html", **auth_context())


def generate_with_gemini(topic: str):
    """Use Gemini to generate a high-quality satirical comedy news article."""
    prompt = (
        "You are a professional satirical comedy writer in the style of The Onion. "
        "Generate a short, funny fake news article about the topic below.\n\n"
        "TOPIC: " + topic + "\n\n"
        "Rules:\n"
        "- The headline must be absurd, ironic, or unexpectedly funny\n"
        "- Write exactly 3 short paragraphs (2-3 sentences each)\n"
        "- Use a confident, serious news-report tone (the humor comes from the absurdity of the content, not the writing style)\n"
        "- Include a clear punchline or twist in the last paragraph\n"
        "- Avoid offensive, political hate, or harmful content\n"
        "- Keep it family-friendly and clever\n\n"
        "Respond ONLY with valid JSON (no markdown):\n"
        '{"headline":"<satirical headline>","paragraphs":["<para 1>","<para 2>","<para 3 with punchline>"]}'
    )
    try:
        headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(GEMINI_API_URL, headers=headers, json=body, timeout=20)
        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        data = json.loads(raw)
        return data.get("headline", ""), data.get("paragraphs", [])
    except Exception as e:
        print("Gemini comedy generation error:", e)
        return None, None


def generate_with_gpt2(topic: str):
    """Fallback: use GPT-2 to generate a comedy headline + article (lower quality)."""
    COMEDY_PREFIXES = [
        "In a shocking turn of events that surprised absolutely nobody,",
        "Local scientists confirm that",
        "Breaking comedy news: experts agree that",
        "Sources close to the situation reveal that",
        "Government officials are baffled as",
    ]
    ARTICLE_SEEDS = [
        "According to a totally reliable anonymous source, {topic} has been",
        "Eyewitnesses at the scene reported that {topic} was",
        "Meanwhile, in a related development, {topic} continues to",
    ]
    prefix = random.choice(COMEDY_PREFIXES)
    seed = prefix + " " + topic
    headline_ids = gpt2_tokenizer.encode(seed, return_tensors="pt", max_length=50, truncation=True)
    with torch.no_grad():
        headline_out = gpt2_model.generate(
            headline_ids, max_length=45, num_return_sequences=1,
            no_repeat_ngram_size=2, top_p=0.95, top_k=60,
            temperature=1.1, do_sample=True,
            pad_token_id=gpt2_tokenizer.eos_token_id
        )
    headline = gpt2_tokenizer.decode(headline_out[0], skip_special_tokens=True)
    paragraphs = []
    for seed_tmpl in random.sample(ARTICLE_SEEDS, 3):
        para_seed = seed_tmpl.format(topic=topic)
        para_ids = gpt2_tokenizer.encode(para_seed, return_tensors="pt", max_length=35, truncation=True)
        with torch.no_grad():
            para_out = gpt2_model.generate(
                para_ids, max_length=70, num_return_sequences=1,
                no_repeat_ngram_size=2, top_p=0.9, top_k=50,
                temperature=1.2, do_sample=True,
                pad_token_id=gpt2_tokenizer.eos_token_id
            )
        paragraphs.append(gpt2_tokenizer.decode(para_out[0], skip_special_tokens=True))
    return headline, paragraphs


@app.route("/generate", methods=["POST"])
def generate():
    """Generate a comedy fake news headline + short satirical article."""
    data = request.get_json()
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "No topic provided"}), 400

    # Use Gemini if available (much better quality), else fall back to GPT-2
    if gemini_client:
        headline, paragraphs = generate_with_gemini(topic)
        engine = "gemini"
    else:
        headline, paragraphs = None, None
        engine = "gpt2"

    if not headline:
        headline, paragraphs = generate_with_gpt2(topic)
        engine = "gpt2"

    return jsonify({
        "headline": headline,
        "article": paragraphs,
        "engine": engine,
        "disclaimer": "This is AI-generated satirical comedy content for entertainment only. Not real news!"
    })



@app.route("/analyze", methods=["POST"])
@optional_auth
def analyze(current_user=None):
    """
    Full pipeline:
    1. Accept text (headline / full article) OR URL
    2. If URL → scrape full article with trafilatura
    3. BERT fast classification → verdict + confidence
    4. DuckDuckGo → top 5 related real news
    5. Gemini Flash → paragraph-level analysis, key claims, clarification
    """
    data = request.get_json()
    url = data.get("url", "").strip()
    text = data.get("text", "").strip()
    scraped_from_url = False
    scrape_layer = None

    # Step 1: Extract text if URL provided
    if url and not text:
        scraped_text, scrape_layer = scrape_article_from_url(url)
        if not scraped_text:
            from urllib.parse import quote_plus
            return jsonify({
                "error": "Could not extract the article from this URL.",
                "scrape_failed_url": url,
                "google_cache_url": "https://webcache.googleusercontent.com/search?q=cache:" + url,
                "archive_url": "https://web.archive.org/web/*/" + url,
            }), 400
        text = scraped_text
        scraped_from_url = True

    if not text:
        return jsonify({"error": "Please provide article text or a URL to analyze."}), 400

    # Step 2: BERT classification
    bert_verdict, bert_conf = bert_classify(text)

    # Step 3: Search for related real news
    search_query = " ".join(text.split()[:30])  # First 30 words as search query
    related_articles = search_related_news(search_query, max_results=6)

    # Step 4: Gemini deep analysis
    gemini_result = gemini_analyze(text, related_articles)

    # Build final response — enrich related articles with reliability scores
    enriched_articles = []
    for r in related_articles[:5]:
        enriched_articles.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "source": r.get("source", ""),
            "date": r.get("date", ""),
            "snippet": r.get("body", "")[:220],
            "reliability": get_source_reliability(r.get("url", ""))
        })

    # Log the analysis request globally
    try:
        user_id = current_user.get("user_id") if current_user else None
        truth_score = gemini_result.get("truth_score") if gemini_result else 0
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO analysis_logs (user_id, input_text, verdict, truth_score) VALUES (?, ?, ?, ?)",
                (user_id, text[:500], bert_verdict, truth_score)
            )
            conn.commit()
    except Exception as e:
        print(f"[ERROR] Failed to log analysis: {e}")

    return jsonify({
        "bert": {
            "verdict": bert_verdict,
            "confidence_pct": bert_conf
        },
        "related_articles": enriched_articles,
        "gemini": gemini_result,
        "scraped_from_url": scraped_from_url,
        "scrape_layer": scrape_layer,
        "gemini_available": gemini_client
    })


@app.route("/fetch_news", methods=["GET"])
def fetch_news():
    """Fetch live news from NewsAPI with pagination."""
    query    = request.args.get("q", "technology")
    page     = max(1, int(request.args.get("page", 1)))
    pageSize = min(20, max(1, int(request.args.get("pageSize", 6))))

    url = (
        f"https://newsapi.org/v2/everything?q={query}"
        f"&language=en&pageSize={pageSize}&page={page}&sortBy=publishedAt&apiKey={NEWS_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        articles = []
        for a in data.get("articles", []):
            articles.append({
                "title":       a.get("title", ""),
                "content":     a.get("content") or a.get("description", ""),
                "url":         a.get("url", ""),
                "source":      a["source"]["name"],
                "publishedAt": a.get("publishedAt", ""),
                "urlToImage":  a.get("urlToImage", "")
            })
        return jsonify({
            "articles":      articles,
            "total_results": data.get("totalResults", 0),
            "page":          page,
            "pageSize":      pageSize
        })
    except Exception as e:
        print("News fetch error:", e)
        return jsonify({"error": "Failed to fetch news. Check your NewsAPI key."}), 500


# ─────────────────────────────────────────────
# Feature: Save & Share Report
# ─────────────────────────────────────────────

@app.route("/save-report", methods=["POST"])
def save_report():
    """Save analysis result to DB and return shareable report ID."""
    data = request.get_json()

    # Optionally link to authenticated user
    current_user = get_current_user()
    user_id = current_user["user_id"] if current_user else None

    report_id = generate_report_id()
    with sqlite3.connect(DB_PATH) as conn:
        for _ in range(10):
            if not conn.execute("SELECT 1 FROM reports WHERE report_id=?", (report_id,)).fetchone():
                break
            report_id = generate_report_id()

        analysis_payload = data.get("analysis", {})
        conn.execute("""
            INSERT INTO reports (report_id, input_text, verdict, truth_score, confidence, analysis_json, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id,
            (data.get("input_text") or "")[:5000],
            data.get("verdict", ""),
            int(data.get("truth_score") or 0),
            int(data.get("confidence") or 0),
            json.dumps(analysis_payload),
            user_id,
        ))
        conn.commit()

    report_url = request.host_url.rstrip("/") + f"/report/{report_id}"
    return jsonify({"report_id": report_id, "url": report_url})


@app.route("/report/<report_id>")
def view_report(report_id):
    """View a shared analysis report."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM reports WHERE report_id=?", (report_id,)).fetchone()

    if not row:
        return render_template("404.html"), 404

    report = {
        "report_id": row["report_id"],
        "input_text": row["input_text"],
        "verdict": row["verdict"],
        "truth_score": row["truth_score"],
        "confidence": row["confidence"],
        "analysis": json.loads(row["analysis_json"] or "{}"),
        "created_at": row["created_at"],
    }
    return render_template("report.html", report=report, **auth_context())


# ─────────────────────────────────────────────
# Feature: PDF Export
# ─────────────────────────────────────────────

@app.route("/export-pdf", methods=["POST"])
def export_pdf_direct():
    """Generate and download PDF directly from analysis data (no DB required)."""
    if not REPORTLAB_OK:
        return jsonify({"error": "PDF export not available — reportlab not installed"}), 503
    data = request.get_json()
    analysis = data.get("analysis", {})
    gemini_d = analysis.get("gemini") or {}

    report = {
        "report_id": generate_report_id(),
        "input_text": (data.get("input_text") or "")[:5000],
        "verdict": data.get("verdict", ""),
        "truth_score": int(data.get("truth_score") or 0),
        "confidence": int(data.get("confidence") or 0),
        "analysis": analysis,
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    try:
        pdf_bytes = generate_pdf_report(report)
    except Exception as e:
        print("PDF error:", e)
        return jsonify({"error": f"PDF generation failed: {e}"}), 500

    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"SatyaX_Report_{report['report_id']}.pdf"
    )


@app.route("/export-pdf/<report_id>")
def export_pdf_by_id(report_id):
    """Download PDF for a saved report."""
    if not REPORTLAB_OK:
        return jsonify({"error": "PDF export not available"}), 503
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM reports WHERE report_id=?", (report_id,)).fetchone()
    if not row:
        return "Report not found", 404
    report = {
        "report_id": row["report_id"],
        "input_text": row["input_text"],
        "verdict": row["verdict"],
        "truth_score": row["truth_score"],
        "confidence": row["confidence"],
        "analysis": json.loads(row["analysis_json"] or "{}"),
        "created_at": row["created_at"],
    }
    try:
        pdf_bytes = generate_pdf_report(report)
    except Exception as e:
        return f"PDF error: {e}", 500
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"SatyaX_Report_{report_id}.pdf"
    )


# ─────────────────────────────────────────────
# Feature: History Page
# ─────────────────────────────────────────────

@app.route("/history")
@require_auth
def history_page(current_user=None):
    return render_template("history.html", **auth_context())


# ─────────────────────────────────────────────
# Auth Pages (Clerk)
# ─────────────────────────────────────────────

@app.route("/sign-in")
def sign_in_page():
    user = get_current_user()
    if user:
        return redirect("/dashboard")
    return render_template("sign_in.html",
        clerk_pk=CLERK_PUBLISHABLE_KEY,
        clerk_frontend=CLERK_FRONTEND_API)


@app.route("/sign-up")
def sign_up_page():
    user = get_current_user()
    if user:
        return redirect("/dashboard")
    return render_template("sign_up.html",
        clerk_pk=CLERK_PUBLISHABLE_KEY,
        clerk_frontend=CLERK_FRONTEND_API)


@app.route("/dashboard")
@require_auth
def dashboard_page(current_user=None):
    return render_template("dashboard.html", **auth_context())


@app.route("/profile")
@require_auth
def profile_page(current_user=None):
    return render_template("profile.html", **auth_context())


@app.route("/saved-reports")
@require_auth
def saved_reports_page(current_user=None):
    return redirect("/dashboard")


@app.route("/admin")
@require_admin
def admin_page(current_user=None):
    return render_template("admin.html", **auth_context())


# ─────────────────────────────────────────────
# Auth APIs
# ─────────────────────────────────────────────

@app.route("/api/my-reports")
@require_auth
def api_my_reports(current_user=None):
    """Return reports saved by the current user."""
    user_id = current_user["user_id"]
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT report_id, input_text, verdict, truth_score, created_at FROM reports "
            "WHERE user_id=? ORDER BY id DESC LIMIT 50",
            (user_id,)
        ).fetchall()
    reports = [{
        "report_id":   r["report_id"],
        "input_text":  r["input_text"],
        "verdict":     r["verdict"],
        "truth_score": r["truth_score"],
        "created_at":  r["created_at"],
        "shared":      True,
    } for r in rows]
    return jsonify({"reports": reports})


@app.route("/api/admin/stats")
@require_admin
def api_admin_stats(current_user=None):
    """Admin stats: users, reports, verdicts, recent reports."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        total_reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        shared_reports = conn.execute("SELECT COUNT(*) FROM reports WHERE user_id IS NOT NULL").fetchone()[0]
        avg_row = conn.execute("SELECT AVG(truth_score) FROM reports WHERE truth_score IS NOT NULL").fetchone()
        avg_score = avg_row[0] if avg_row else None
        recent = conn.execute(
            "SELECT report_id, input_text, verdict, truth_score, created_at FROM reports ORDER BY id DESC LIMIT 20"
        ).fetchall()
        verdict_rows = conn.execute(
            "SELECT verdict, COUNT(*) as cnt FROM reports WHERE verdict IS NOT NULL GROUP BY verdict"
        ).fetchall()

        # New queries for analysis tracking
        total_analyses = 0
        analysis_counts = {}
        try:
            total_analyses = conn.execute("SELECT COUNT(*) FROM analysis_logs").fetchone()[0]
            analysis_counts_rows = conn.execute("SELECT user_id, COUNT(*) as cnt FROM analysis_logs WHERE user_id IS NOT NULL GROUP BY user_id").fetchall()
            analysis_counts = {r["user_id"]: r["cnt"] for r in analysis_counts_rows}
        except Exception:
            pass

    users = list_clerk_users(limit=50)
    for u in users:
        u["analysis_count"] = analysis_counts.get(u["user_id"], 0)

    total_users = get_clerk_user_count()
    verdict_dist = {r["verdict"]: r["cnt"] for r in verdict_rows}
    recent_reports = [{
        "report_id":  r["report_id"],
        "input_text": r["input_text"],
        "verdict":    r["verdict"],
        "truth_score":r["truth_score"],
        "created_at": r["created_at"],
    } for r in recent]

    return jsonify({
        "total_users":          total_users,
        "total_reports":        total_reports,
        "shared_reports":       shared_reports,
        "total_analyses":       total_analyses,
        "avg_score":            avg_score,
        "users":                users,
        "recent_reports":       recent_reports,
        "verdict_distribution": verdict_dist,
    })


@app.route("/api/admin/user_activity/<user_id>")
@require_admin
def api_admin_user_activity(user_id, current_user=None):
    """Fetch analysis history for a specific user."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT input_text, verdict, truth_score, created_at FROM analysis_logs "
                "WHERE user_id=? ORDER BY id DESC LIMIT 100",
                (user_id,)
            ).fetchall()
            history = [{
                "input_text":  r["input_text"],
                "verdict":     r["verdict"],
                "truth_score": r["truth_score"],
                "created_at":  r["created_at"],
            } for r in rows]
        except Exception:
            history = []
    return jsonify({"history": history})


@app.route("/api/admin/health")
@require_admin
def api_admin_health(current_user=None):
    """System health check for admin dashboard."""
    return jsonify({
        "flask":  True,
        "bert":   True,   # loaded at startup
        "gemini": gemini_client,
        "clerk":  bool(CLERK_PUBLISHABLE_KEY and CLERK_FRONTEND_API),
    })


if __name__ == "__main__":
    print("\n[*] Starting SatyaX...")
    print("   BERT model: [OK] loaded")
    print("   GPT-2 model: [OK] loaded")
    print("   Gemini AI: " + ('[OK] active (' + GEMINI_MODEL + ')' if gemini_client else '[WARN] not configured (BERT-only mode)'))
    print(f"   NewsAPI: {'[OK] configured' if NEWS_API_KEY else '[WARN] not configured'}")
    print(f"   Clerk Auth: {'[OK] configured' if CLERK_PUBLISHABLE_KEY else '[WARN] not configured (set CLERK_PUBLISHABLE_KEY)'}")
    print("\n   Visit: http://localhost:5000\n")
    app.run(debug=True)
