"""Application configuration settings."""

from pathlib import Path

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
    weight_semantic: float = 0.30
    weight_web_search: float = 0.25
    weight_academic: float = 0.25
    weight_ai_detection: float = 0.20

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
    azure_openai_api_version: str = "2024-12-01-preview"
    rewriter_max_tokens: int = 4096
    rewriter_temperature: float = 0.7

    # External API keys
    bing_api_key: str = ""

    model_config = {"env_prefix": "PG_", "env_file": ".env"}


settings = Settings()
