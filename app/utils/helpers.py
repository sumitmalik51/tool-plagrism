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


# Magic-byte signatures keyed by extension. The values are tuples of
# acceptable (offset, prefix) pairs. We deliberately keep this short and
# lenient — matching the FIRST chunk of bytes is plenty to reject a .pdf
# whose body is actually a zip archive being fed to PyPDF2 (which has
# historical parser CVEs).
_MAGIC_SIGNATURES: dict[str, tuple[tuple[int, bytes], ...]] = {
    ".pdf":  ((0, b"%PDF-"),),
    # ZIP-based formats (docx/odt) all start with PK\x03\x04 or PK\x05\x06.
    ".docx": ((0, b"PK\x03\x04"), (0, b"PK\x05\x06"), (0, b"PK\x07\x08")),
    ".doc":  ((0, b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"),),  # OLE compound file
    ".odt":  ((0, b"PK\x03\x04"), (0, b"PK\x05\x06"), (0, b"PK\x07\x08")),
    ".rtf":  ((0, b"{\\rtf"),),
}


def validate_file_signature(filename: str, file_bytes: bytes) -> bool:
    """Best-effort magic-byte check that the file content matches its extension.

    Returns True for extensions we don't have a signature for (.txt, .md, etc.)
    so plain-text uploads keep working — the goal is specifically to reject
    binary-format spoofing (a .pdf that's actually a zip), which is the
    real attack against PyPDF2/pdfplumber/python-docx parsers.
    """
    ext = Path(filename).suffix.lower()
    sigs = _MAGIC_SIGNATURES.get(ext)
    if not sigs:
        return True  # No signature configured for this type; trust extension.
    head = file_bytes[:32]
    return any(head[off:off + len(prefix)] == prefix for off, prefix in sigs)


def ensure_upload_dir() -> Path:
    """Create the upload directory if it does not exist and return its path."""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings.upload_dir
