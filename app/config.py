"""Application configuration settings."""

from pathlib import Path
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration loaded from environment variables."""

    app_name: str = "PlagiarismGuard"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # File upload
    max_upload_size_mb: int = 50
    allowed_extensions: list[str] = [".pdf", ".docx", ".txt"]
    upload_dir: Path = Path("uploads")

    # Agent weights (used by aggregation_agent)
    # Semantic agent detects internal duplication (self-similarity), which
    # is not plagiarism, so its weight is 0.  The remaining agents share
    # the full weight budget.
    weight_semantic: float = 0.0
    weight_web_search: float = 0.35
    weight_academic: float = 0.35
    weight_ai_detection: float = 0.30

    # Semantic agent
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size: int = 800
    chunk_overlap: int = 150
    semantic_similarity_threshold: float = 0.80

    # Risk classification thresholds (plagiarism_score 0-100)
    risk_threshold_high: float = 60.0
    risk_threshold_medium: float = 30.0

    # Web search limits
    web_search_max_queries: int = 8
    web_search_results_per_query: int = 5
    web_search_similarity_threshold: float = 0.50

    # Academic / Scholar search limits
    scholar_max_queries: int = 8
    scholar_results_per_query: int = 5

    # Azure OpenAI (for AI rewriter)
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2025-01-01-preview"
    rewriter_max_tokens: int = 4096
    rewriter_temperature: float = 0.7

    # External API keys
    bing_api_key: str = ""

    # Authentication — comma-separated list of valid API keys.
    # When empty, auth is disabled (dev mode). Set PG_API_KEYS_RAW in prod.
    api_keys_raw: str = ""
    api_keys: list[str] = []

    # JWT settings (for user login/signup flow)
    jwt_secret: str = ""         # Set PG_JWT_SECRET in prod; auto-generated in dev
    jwt_expiry_seconds: int = 86400  # 24 hours

    # Scan rate limits (per day)
    scan_limit_anonymous: int = 3   # max scans/day for anonymous (by IP)
    scan_limit_free: int = 3        # max scans/day for free registered users

    # Razorpay payment gateway
    razorpay_key_id: str = ""       # Set PG_RAZORPAY_KEY_ID
    razorpay_key_secret: str = ""   # Set PG_RAZORPAY_KEY_SECRET

    # Database — Azure SQL connection string.
    # When empty, falls back to SQLite for local dev.
    # Set PG_SQL_CONNECTION_STRING in production.
    sql_connection_string: str = ""

    # Azure Communication Services (ACS) — for transactional emails.
    # Set PG_ACS_CONNECTION_STRING and PG_ACS_SENDER_EMAIL in production.
    acs_connection_string: str = ""
    acs_sender_email: str = "DoNotReply@plagiarismguard.com"

    # Public base URL (used in email links).
    # Set PG_APP_BASE_URL in production.
    app_base_url: str = "https://plagiarismguard-jl6yu5wij5mu4.azurewebsites.net"

    # Admin panel — comma-separated list of admin email addresses.
    # Set PG_ADMIN_EMAILS in production.
    admin_emails: str = "sumitmalik51@gmail.com"

    @model_validator(mode="after")
    def _parse_api_keys(self) -> "Settings":
        """Split ``api_keys_raw`` into a list."""
        if self.api_keys_raw and not self.api_keys:
            self.api_keys = [
                k.strip() for k in self.api_keys_raw.split(",") if k.strip()
            ]
        return self

    model_config = {"env_prefix": "PG_", "env_file": ".env"}


settings = Settings()
