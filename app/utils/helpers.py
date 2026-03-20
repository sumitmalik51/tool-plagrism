"""General-purpose helper utilities."""

from pathlib import Path

from app.config import settings


def validate_file_extension(filename: str) -> bool:
    """Check if the uploaded file has an allowed extension."""
    ext = Path(filename).suffix.lower()
    return ext in settings.allowed_extensions


def validate_file_size(size_bytes: int) -> bool:
    """Check if the uploaded file is within the allowed size limit."""
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    return size_bytes <= max_bytes


def ensure_upload_dir() -> Path:
    """Create the upload directory if it does not exist and return its path."""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings.upload_dir
