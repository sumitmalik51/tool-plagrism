# PlagiarismGuard

AI-powered multi-agent plagiarism detection platform with 6 specialized agents, 17+ tools, per-model AI detection, and a Chrome extension. Built with FastAPI and Azure OpenAI.

## Features

- **Multi-Agent Plagiarism Detection** — Semantic, Web Search, Academic, AI Detection, Aggregation, and Report agents working in parallel
- **Per-Model AI Detection** — Identifies whether text was written by ChatGPT, Claude, Gemini, Copilot, or a human (GPT-powered fingerprinting)
- **Text Humanizer** — Rewrite AI-generated text to sound naturally human (7 rewrite modes)
- **Multi-Format Support** — PDF, DOCX, TXT, LaTeX, and **PPTX** (PowerPoint) files
- **Google Docs Import** — Analyze publicly shared Google Docs directly via URL
- **Word-Count Quotas** — Monthly word-based usage limits per subscription tier
- **Chrome Extension** — Right-click scan on any webpage, with popup results
- **Multilingual** — Supports 50+ languages with auto-detection
- **Citation Stripping** — Automatic citation/reference removal for accurate scoring
- **Repository Check** — Compare documents against your own uploaded document library
- **DOCX Export** — Download full plagiarism reports as formatted Word documents
- **Razorpay Payments** — Subscription billing with Pro and Premium tiers

## Quick Start

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload

# Visit API docs
# http://127.0.0.1:8000/docs
```

## Project Structure

```
app/
├── main.py              # FastAPI entry point
├── config.py            # Application settings (tiers, quotas, limits)
├── agents/              # Detection agents
│   ├── base_agent.py         # Abstract base
│   ├── semantic_agent.py     # Internal duplication (embeddings)
│   ├── web_search_agent.py   # Web source matching
│   ├── academic_agent.py     # Academic paper matching (OpenAlex)
│   ├── ai_detection_agent.py # AI-generated text detection + model ID
│   ├── aggregation_agent.py  # Score aggregation & risk
│   └── report_agent.py       # AI-generated report narrative
├── tools/               # Reusable tool functions
│   ├── ai_detection_tool.py       # Heuristic + GPT AI detection + model fingerprinting
│   ├── content_extractor_tool.py  # PDF, DOCX, TXT, LaTeX, PPTX extraction
│   ├── general_rewriter.py        # 7-mode rewriter (humanize, paraphrase, etc.)
│   ├── grammar_tool.py            # Grammar & style checking
│   ├── readability_tool.py        # Readability metrics
│   ├── citation_tool.py           # Citation detection & stripping
│   ├── fingerprint_tool.py        # Document fingerprinting
│   └── ...
├── services/            # Business logic
│   ├── orchestrator.py       # Multi-agent pipeline orchestrator
│   ├── ingestion.py          # File upload & extraction
│   ├── rate_limiter.py       # Daily scan + monthly word-count quotas
│   ├── auth_service.py       # JWT auth, user management
│   ├── database.py           # SQLite / Azure SQL dual-backend
│   └── ...
├── models/              # Pydantic schemas
│   └── schemas.py
├── routes/              # API endpoints
│   ├── upload.py        # File upload & Google Docs import
│   ├── analyze.py       # Full plagiarism analysis pipeline
│   ├── rewrite.py       # AI rewriter (7 modes)
│   ├── writing.py       # Grammar, readability, batch analysis
│   ├── tools.py         # Individual tool endpoints
│   ├── auth.py          # Signup, login, API keys, usage, payments
│   ├── advanced.py      # Reference validation, cross-compare
│   └── admin.py         # Admin dashboard
├── static/              # Frontend (landing page, dashboard, login)
└── utils/               # Helpers & logging
extension/               # Chrome browser extension (beta)
workspace-addon/         # Google Workspace add-on (beta)
word-addin/              # Microsoft Word add-in (beta)
tests/                   # 450+ test suite
```

> **Note:** The `extension/`, `workspace-addon/`, and `word-addin/` folders contain
> scaffolded implementations that are not yet published to their respective stores.
> They connect to the PlagiarismGuard API and are functional for local dev/testing.

## Subscription Tiers

| Feature | Free | Pro | Premium |
|---------|------|-----|---------|
| Scans per day | 3 | Unlimited | Unlimited |
| Word quota / month | 5,000 | 200,000 | 500,000 |
| Max file size | 50 MB | 50 MB | 100 MB |
| Batch analysis | — | 5 files | 10 files |
| API keys | 1 | 5 | 20 |
| Web search queries | 8 | 8 | 15 |
| DOCX export watermark | Yes | No | No |

## Chrome Extension

The `extension/` folder contains a Manifest V3 Chrome extension:

1. Go to `chrome://extensions` → Enable Developer Mode
2. Click **Load unpacked** → Select the `extension/` folder
3. Click the extension icon → Enter your server URL and API key
4. Highlight text on any page → Click **Scan Selected Text** or right-click → **Scan with PlagiarismGuard**

## Environment Variables

All settings use the `PG_` prefix. Key variables:

| Variable | Description |
|----------|-------------|
| `PG_AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL |
| `PG_AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `PG_AZURE_OPENAI_DEPLOYMENT` | Model deployment name (default: `gpt-4o`) |
| `PG_SQL_CONNECTION_STRING` | Azure SQL connection string (empty = SQLite) |
| `PG_JWT_SECRET` | JWT signing secret |
| `PG_BING_API_KEY` | Bing Search API key (optional) |
| `PG_RAZORPAY_KEY_ID` | Razorpay payment key |
| `PG_ACS_CONNECTION_STRING` | Azure Communication Services (emails) |
| `PG_WORD_QUOTA_FREE` | Monthly word limit for free tier (default: 5000) |
| `PG_WORD_QUOTA_PRO` | Monthly word limit for pro tier (default: 200000) |
| `PG_WORD_QUOTA_PREMIUM` | Monthly word limit for premium tier (default: 500000) |

## Testing

```bash
python -m pytest tests/ -x -q --tb=short
```
