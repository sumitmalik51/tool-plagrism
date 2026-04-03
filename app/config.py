"""Application configuration settings."""

import warnings
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
    allowed_extensions: list[str] = [".pdf", ".docx", ".txt", ".tex", ".pptx"]
    upload_dir: Path = Path("uploads")

    # Agent weights (used by aggregation_agent)
    # Semantic agent detects internal duplication (self-similarity), which
    # is not plagiarism, so its weight is 0.  The remaining agents share
    # the full weight budget.
    weight_semantic: float = 0.0
    weight_web_search: float = 0.35
    weight_academic: float = 0.35
    weight_ai_detection: float = 0.30

    # Semantic agent (multilingual model — supports 50+ languages)
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_executor_workers: int = 3  # Concurrent embedding requests
    chunk_size: int = 800
    chunk_overlap: int = 150
    semantic_similarity_threshold: float = 0.80

    # Text processing limits (magic numbers extracted for tuning)
    max_query_length: int = 150  # Max chars for academic search queries
    web_query_max_length: int = 200  # Max chars for web search queries
    passage_display_length: int = 500  # Chars to display in flagged passages
    flagged_passages_limit: int = 50  # Max passages to return in response
    page_content_length: int = 2000  # Max chars of fetched page to analyze

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
    jwt_expiry_seconds: int = 7200   # 2 hours (short-lived access tokens)
    jwt_refresh_expiry_seconds: int = 604800  # 7 days (refresh token)

    # Scan rate limits (per day)
    scan_limit_anonymous: int = 3   # max scans/day for anonymous (by IP)
    scan_limit_free: int = 3        # max scans/day for free registered users

    # Word-count quotas (per month, 0 = unlimited)
    word_quota_free: int = 5000           # Free users: 5K words/month
    word_quota_pro: int = 200000          # Pro users: 200K words/month
    word_quota_premium: int = 500000      # Premium users: 500K words/month

    # Tier-based feature limits
    max_upload_size_mb_pro: int = 50       # Pro file size limit
    max_upload_size_mb_premium: int = 100  # Premium file size limit
    batch_max_files_pro: int = 5           # Pro batch analysis limit
    batch_max_files_premium: int = 10      # Premium batch analysis limit
    api_keys_limit_pro: int = 5            # Pro API key limit
    api_keys_limit_premium: int = 20       # Premium API key limit
    web_search_max_queries_premium: int = 15  # Premium gets more web search queries

    # Razorpay payment gateway
    razorpay_key_id: str = ""       # Set PG_RAZORPAY_KEY_ID
    razorpay_key_secret: str = ""   # Set PG_RAZORPAY_KEY_SECRET
    razorpay_webhook_secret: str = ""  # Set PG_RAZORPAY_WEBHOOK_SECRET (optional, falls back to key_secret)

    # Database — Azure SQL connection string.
    # When empty, falls back to SQLite for local dev.
    # Set PG_SQL_CONNECTION_STRING in production.
    sql_connection_string: str = ""

    # Azure Communication Services (ACS) — for transactional emails.
    # Set PG_ACS_CONNECTION_STRING and PG_ACS_SENDER_EMAIL in production.
    acs_connection_string: str = ""
    acs_sender_email: str = "DoNotReply@05cf42e5-2365-4546-aa1d-1c54ce6cbbc8.azurecomm.net"

    # Public base URL (used in email links).
    # Set PG_APP_BASE_URL in production.
    app_base_url: str = "https://plagiarismguard-jl6yu5wij5mu4.azurewebsites.net"

    # Admin panel — comma-separated list of admin email addresses.
    # Set PG_ADMIN_EMAILS in production.
    admin_emails: str = ""

    @model_validator(mode="after")
    def _parse_api_keys(self) -> "Settings":
        """Split ``api_keys_raw`` into a list."""
        if self.api_keys_raw and not self.api_keys:
            self.api_keys = [
                k.strip() for k in self.api_keys_raw.split(",") if k.strip()
            ]
        return self

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """Ensure critical secrets are set when not in debug mode."""
        if self.debug:
            return self
        missing: list[str] = []
        if not self.jwt_secret:
            missing.append("PG_JWT_SECRET")
        if not self.sql_connection_string:
            missing.append("PG_SQL_CONNECTION_STRING")
        if not self.azure_openai_api_key:
            missing.append("PG_AZURE_OPENAI_API_KEY")
        if missing:
            msg = (
                f"Production mode requires these environment variables: "
                f"{', '.join(missing)}. Set PG_DEBUG=true to bypass."
            )
            warnings.warn(msg, stacklevel=2)
        return self

    model_config = {"env_prefix": "PG_", "env_file": ".env"}


settings = Settings()
