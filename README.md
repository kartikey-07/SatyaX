<p align="center">
  <img src="static/logo_1.jpg" alt="SatyaX Logo" width="260" />
</p>

# ⚡ SatyaX — AI-Powered Fact Verification & Misinformation Analysis Platform

> **SatyaX** is an AI-powered fact verification and misinformation analysis platform that combines BERT-based linguistic analysis, real-time evidence retrieval, source reliability assessment, and Google Gemini AI reasoning to evaluate the credibility of online content.

---

## ✨ Features

| Feature | Description |
|---|---|
| ✅ URL Analysis | Paste any news article URL — SatyaX auto-extracts the full text via 5-layer scraper |
| ✅ News Verification | Analyze headlines, full articles, or social media claims |
| ✅ Claim Extraction | Gemini AI extracts and individually verifies each factual claim |
| ✅ Evidence Retrieval | Real-time DuckDuckGo web search for corroborating sources |
| ✅ Authentication | Secure user login via **Clerk** (Email, Google, Apple, GitHub) |
| ✅ Dashboard & History | Cloud-saved history, verdict distributions, and shareable reports for users |
| ✅ PDF Verification Reports | Professional 8-section corporate PDF export via ReportLab |
| ✅ Shareable Result Links | Permanent `/report/SX-XXXXXX` URLs for every analysis |
| ✅ Admin Dashboard | Secure `/admin` panel tracking global stats, total analyses, and individual user activity |
| ✅ Comedy Generator | Gemini-powered satirical headlines (The Onion style) with GPT-2 fallback |
| ✅ Live News Feed | NewsAPI-powered news browser with direct fact-check buttons |

---

## 🛠 Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · Flask |
| NLP Classification | BERT (fine-tuned on ISOT + WELFake, 40k+ articles) |
| AI Reasoning | Google Gemini Flash Lite (REST API) |
| Comedy Generator | Gemini (primary) · GPT-2 (fallback) |
| Authentication | Clerk (Frontend JS + Backend JWT Verification) |
| URL Scraping | Trafilatura · newspaper3k · BeautifulSoup · Google Cache · Archive.org |
| Web Search | DuckDuckGo (ddgs) — no API key required |
| Live News | NewsAPI |
| PDF Export | ReportLab |
| Database | SQLite (`satyax.db`) — stores reports & global analysis logs |
| Frontend | Vanilla HTML · CSS · JavaScript · Google Fonts (Inter) |

---

## 📁 Project Structure

```
SatyaX/
│
├── app.py                         ← Flask backend + all routes + AI pipeline
├── auth.py                        ← Clerk JWT verification & Admin route decorators
├── satyax.db                      ← SQLite reports database (auto-created)
├── requirements.txt
├── .env                           ← API keys (not committed to git)
│
├── static/
│   ├── style.css                  ← Dark glassmorphism design system
│   ├── script.js                  ← Main UI logic
│   └── auth.js                    ← Clerk authentication & frontend state
│
├── templates/
│   ├── index.html                 ← Main application (Fact Checker + Comedy + News)
│   ├── dashboard.html             ← Authenticated user dashboard & stats
│   ├── admin.html                 ← Secure admin dashboard & platform analytics
│   ├── report.html                ← Shared verification report view
│   ├── history.html               ← Verifications history page
│   ├── how_it_works.html          ← 9-stage pipeline explainer
│   ├── methodology.html           ← Full methodology documentation
│   ├── faq.html                   ← Frequently asked questions
│   └── 404.html                   ← Missing report error page
│
└── saved_fake_news_model/
    ├── config.json
    ├── model.safetensors          ← Download separately (see below)
    ├── tokenizer_config.json
    ├── vocab.txt
    └── special_tokens_map.json
```

---

## 🚀 Setup Instructions

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/yourusername/satyax.git
cd satyax
```

### 2️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

Core packages:
```bash
pip install flask torch transformers requests trafilatura newspaper3k beautifulsoup4 lxml python-dotenv ddgs reportlab pyjwt
```

### 3️⃣ Download the BERT Model

The `model.safetensors` file is not included due to size limits.

👉 **[Download model.safetensors from Google Drive](https://drive.google.com/uc?export=download&id=1H-PIKN2eV-aHzZQtczQGCddFJjtgKuB-)**

```bash
mkdir saved_fake_news_model
# Move the downloaded file into:
# saved_fake_news_model/model.safetensors
```

### 4️⃣ Configure API Keys

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_google_gemini_api_key
NEWS_API_KEY=your_newsapi_key
CLERK_PUBLISHABLE_KEY=pk_test_xxxxxxxxxx
CLERK_SECRET_KEY=sk_test_xxxxxxxxxx
CLERK_FRONTEND_API=https://your-clerk-instance.clerk.accounts.dev
```

| Key | Where to get it |
|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `NEWS_API_KEY` | [NewsAPI.org](https://newsapi.org/register) |
| `CLERK_*` Keys | [Clerk Dashboard](https://dashboard.clerk.com) |

> DuckDuckGo search does **not** require an API key.

### 5️⃣ Setting up an Admin Account
To access the Admin Dashboard at `/admin`, your user account requires the `admin` role. 
1. Log into your app once to create a user.
2. Go to your [Clerk Dashboard](https://dashboard.clerk.com) → **Users**.
3. Edit your user's **Public Metadata** and add:
   ```json
   { "role": "admin" }
   ```
4. Restart your Flask server and re-login!

### 6️⃣ Run the Application

```bash
python app.py
```

Visit: **[http://localhost:5000](http://localhost:5000)**

---

## 🔗 Key Routes Reference

| Method | Route | Description |
|---|---|---|
| GET | `/` | Main application page |
| GET | `/dashboard` | User's personalized dashboard & history |
| GET | `/admin` | Admin dashboard (Requires `role: admin` metadata) |
| POST | `/analyze` | Main fact-check pipeline |
| POST | `/save-report` | Save analysis to DB, return `SX-XXXXXX` report ID |
| GET | `/report/<id>` | View shared verification report |
| POST | `/export-pdf` | Generate PDF directly from analysis data |
| GET | `/api/admin/stats` | Fetches platform-wide stats for Admin Dashboard |

---

## 🧠 Verification Pipeline

```
User Input (text / URL)
        ↓
5-Layer URL Scraper (if URL)
        ↓
BERT Writing Style Analysis
  · Sensationalism Risk
  · Clickbait Probability
  · Emotional Language Score
        ↓
DuckDuckGo Real-Time Web Search
  · 5 related articles + Source Reliability Scoring
        ↓
Gemini AI Deep Analysis
  · Verdict (6 categories) & Truth Score (0–100)
  · ELI5 Plain-English Summary
  · Key Claims Extraction & Verification
        ↓
Results + Post-Analysis Actions
  · Save to Global Log Database (analysis_logs)
  · Download PDF → SatyaX_Report_SX-XXXXXX.pdf
```

---

## 🏷 Verdict System

| Verdict | Meaning |
|---|---|
| ✅ REAL | Accurate, verifiable, strongly supported by evidence |
| 🚫 FAKE | False, fabricated, or directly contradicted by evidence |
| ⚠️ MISLEADING | Technically true but framed to deceive |
| 🔶 PARTIALLY TRUE | Mix of correct and incorrect claims |
| 💬 CONTEXT NEEDED | Accurate but missing critical background context |
| 🔍 UNVERIFIED | Insufficient evidence to confirm or deny |

---

## ⚠️ Known Limitations

- Major publishers (Reuters, NYT, WSJ) use WAF bot-protection that blocks all scrapers
- Gemini may not know very recent events (knowledge cutoff applies)
- Running on Flask dev server — use Gunicorn + Nginx for production deployments

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

*SatyaX — Smart evidence. Transparent reasoning. Better decisions.*
