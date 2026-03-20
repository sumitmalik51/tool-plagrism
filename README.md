# PlagiarismGuard

AI-powered multi-agent plagiarism detection system built with FastAPI.

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
├── config.py            # Application settings
├── agents/              # Detection agents
│   ├── base_agent.py
│   ├── semantic_agent.py
│   ├── web_search_agent.py
│   ├── academic_agent.py
│   ├── ai_detection_agent.py
│   ├── aggregation_agent.py
│   └── report_agent.py
├── services/            # Business logic
│   ├── ingestion.py
│   └── text_extractor.py
├── models/              # Pydantic schemas
│   └── schemas.py
├── routes/              # API endpoints
│   └── upload.py
└── utils/               # Helpers & logging
    ├── logger.py
    └── helpers.py
tests/                   # Test suite
```

## API Endpoints

| Method | Path            | Description                       |
|--------|-----------------|-----------------------------------|
| GET    | `/health`       | Health check                      |
| POST   | `/api/v1/upload` | Upload a document for analysis   |
