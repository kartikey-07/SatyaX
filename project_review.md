# SatyaX — Comprehensive Project Review & Pre-Deployment Guide

This document provides a complete overview of the **SatyaX** project (Fake News Generator & Detector) in its current state, highlighting its features, architecture, and a checklist to ensure smooth deployment to a production environment.

---

## 1. Project Overview
**SatyaX** is an advanced, AI-powered platform designed to combat misinformation and educate users on media literacy. It features a dual-engine system:
1. **Fact-Checking Engine:** Evaluates text or URLs to detect fake, real, or misleading news using BERT classification, DuckDuckGo search cross-referencing, and Gemini Flash contextual analysis.
2. **Satire/Fake News Generator:** Uses GPT-2 and Gemini to generate satirical news articles to demonstrate how AI can be weaponized for misinformation, serving as an educational tool.

---

## 2. Core Features & Capabilities
- **Multi-Modal Input:** Users can input direct text or paste URLs (which are scraped via `trafilatura`).
- **Comprehensive Verification:** 
  - Fast baseline classification via custom-trained **BERT**.
  - Live context gathering via **DuckDuckGo** news search.
  - Deep-dive contextual reasoning via **Gemini AI**.
- **User Authentication:** Fully integrated with **Clerk** (supporting Email, Google, Apple, and GitHub logins).
- **History & Saved Reports:**
  - **Local History:** Fast, browser-based history for casual users.
  - **Saved Reports:** Authenticated users can save reports to the database and generate shareable public links.
  - **PDF Export:** Generates professional, downloadable PDF reports of the analysis via `reportlab`.
- **Admin Dashboard:**
  - Secure `/admin` route protected by Clerk role-based metadata.
  - Tracks platform-wide metrics (Total Users, Total Analyses, Saved Reports).
  - Displays verdict distribution.
  - Tracks individual user activity and analysis history.

---

## 3. Technology Stack
### Backend
- **Framework:** Python / Flask
- **Database:** SQLite (Stores `reports` and `analysis_logs`)
- **AI Models:** 
  - **HuggingFace Transformers:** Custom BERT model (`saved_fake_news_model`) and GPT-2.
  - **Google Gemini API:** Paragraph-level reasoning and truth scoring.
- **Data Gathering:** `trafilatura` (Web scraping), `duckduckgo-search` (Live news).
- **PDF Generation:** `reportlab`

### Frontend
- **Structure:** HTML5, CSS3 (Vanilla), JavaScript (Vanilla)
- **Styling:** Custom "glassmorphism" UI with dark mode aesthetics.
- **Authentication:** Clerk JS Frontend SDK integrated natively.

---

## 4. Database Schema
The SQLite database (`pramanaai.db`) consists of two main tables:

1. **`reports`** (For Saved & Shared Reports)
   - `id`, `report_id` (Unique SX- identifier), `user_id` (Clerk ID)
   - `input_text`, `verdict`, `truth_score`, `confidence`
   - `analysis_json` (Full JSON dump of the AI analysis)
   - `created_at`
2. **`analysis_logs`** (For Global Tracking)
   - `id`, `user_id` (Nullable for anonymous)
   - `input_text` (Truncated to 500 chars), `verdict`, `truth_score`
   - `created_at`

---

## 5. Security & Data Privacy
- **Authentication:** Handled entirely by Clerk, ensuring passwords and sensitive PII are never stored on your servers.
- **Authorization:** Admin routes are secured via JWT verification using Clerk's JWKS and backend API validation.
- **Sanitization:** User inputs are escaped in the frontend using custom `escHtml()` functions to prevent Cross-Site Scripting (XSS).
- **Error Handling:** Backend failures gracefully degrade (e.g., falling back to BERT if Gemini hits rate limits).

---

## 6. Pre-Deployment Checklist

Before pushing this project to a production server (like Heroku, Render, AWS, or DigitalOcean), ensure the following are complete:

### Environment Variables
> [!IMPORTANT]
> Ensure these variables are set securely in your production environment. **Never commit your `.env` file to GitHub.**
- [ ] `GEMINI_API_KEY`: Valid Google Gemini API Key.
- [ ] `NEWS_API_KEY`: Valid NewsAPI Key for the Live News feed.
- [ ] `CLERK_PUBLISHABLE_KEY`: From your Clerk Production instance.
- [ ] `CLERK_SECRET_KEY`: From your Clerk Production instance.
- [ ] `CLERK_FRONTEND_API`: E.g., `https://clerk.satyax.com` or your Clerk frontend URL.

### Code & Server Configuration
- [ ] **Debug Mode:** In `app.py`, change `app.run(debug=True)` to `debug=False`.
- [ ] **WSGI Server:** Do not use the built-in Flask server in production. Use **Gunicorn** or **Waitress**. 
  - *Example:* `gunicorn -w 4 -b 0.0.0.0:5000 app:app`
- [ ] **Database Migration:** SQLite is great for lightweight usage, but if you expect high traffic, consider migrating to PostgreSQL using SQLAlchemy. If staying with SQLite, ensure the `pramanaai.db` file is stored in a persistent volume (not ephemeral storage, which resets on deployment platforms like Heroku/Render).
- [ ] **Model Hosting:** The local BERT and GPT-2 models (`saved_fake_news_model`) require significant RAM to load. Ensure your production server has at least **2GB - 4GB of RAM**.
- [ ] **HTTPS / SSL:** Ensure your production domain has an SSL certificate configured so Clerk authentication functions properly.

### Clerk Configuration
- [ ] **Switch to Production:** In the Clerk Dashboard, switch your instance from "Development" to "Production".
- [ ] **Update Redirects:** Update the allowed origins and redirect URLs in the Clerk Dashboard to match your production domain.

### Final Testing
- [ ] Test a full verification flow anonymously.
- [ ] Test logging in via a social provider.
- [ ] Test saving a report and viewing the public share link.
- [ ] Test the `/admin` dashboard to ensure metrics and activity logs load properly.
