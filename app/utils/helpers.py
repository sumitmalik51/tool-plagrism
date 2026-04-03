"""General-purpose helper utilities."""

from pathlib import Path

from app.config import settings


def validate_file_extension(filename: str) -> bool:
    """Check if the uploaded file has an allowed extension."""
    ext = Path(filename).suffix.lower()
    return ext in settings.allowed_extensions


def validate_file_size(size_bytes: int, plan_type: str = "free") -> bool:
    """Check if the uploaded file is within the allowed size limit.

    Premium users get a higher limit (100 MB by default).
    """
    if plan_type == "premium":
        max_mb = settings.max_upload_size_mb_premium
    elif plan_type == "pro":
        max_mb = settings.max_upload_size_mb_pro
    else:
        max_mb = settings.max_upload_size_mb
    max_bytes = max_mb * 1024 * 1024
    return size_bytes <= max_bytes


def get_upload_limit_mb(plan_type: str = "free") -> int:
    """Return the upload size limit in MB for the given plan."""
    if plan_type == "premium":
        return settings.max_upload_size_mb_premium
    if plan_type == "pro":
        return settings.max_upload_size_mb_pro
    return settings.max_upload_size_mb


def ensure_upload_dir() -> Path:
    """Create the upload directory if it does not exist and return its path."""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings.upload_dir
