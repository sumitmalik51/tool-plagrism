"""Shared test fixtures — sets up a temporary SQLite database for all tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Enable debug mode before any app code is imported so the JWT secret
# auto-generates and the production-secret validator is skipped.
os.environ.setdefault("PG_DEBUG", "true")

import pytest

from app.services.database import SQLiteDatabase, reset_db, get_db

# ---------------------------------------------------------------------------
# Prevent download / loading of the real embedding model in CI.
# Individual tests that need embeddings mock generate_embeddings directly.
# ---------------------------------------------------------------------------
_model_mock = MagicMock()
_model_patcher = patch("app.tools.embedding_tool._load_model", return_value=_model_mock)
_model_patcher.start()

# ---------------------------------------------------------------------------
# Create a single temp DB shared by all test modules.
# This runs once when conftest is loaded (before any tests).
# ---------------------------------------------------------------------------

_tmp = tempfile.NamedTemporaryFile(suffix="_test.db", delete=False)
_tmp.close()
_test_db = SQLiteDatabase(Path(_tmp.name))
_test_db.init_schema()
reset_db(_test_db)


@pytest.fixture(autouse=True)
def _reset_usage_limiter():
    """Clear the usage_logs table before each test to prevent cross-test
    rate-limit interference."""
    from app.services.rate_limiter import limiter
    limiter.reset()
    # Also reset the auth endpoint rate limiter
    from app.routes.auth import _auth_limiter
    with _auth_limiter._lock:
        _auth_limiter._attempts.clear()
    yield
