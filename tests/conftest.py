"""Shared test fixtures — sets up a temporary SQLite database for all tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.database import SQLiteDatabase, reset_db, get_db

# ---------------------------------------------------------------------------
# Create a single temp DB shared by all test modules.
# This runs once when conftest is loaded (before any tests).
# ---------------------------------------------------------------------------

_tmp = tempfile.NamedTemporaryFile(suffix="_test.db", delete=False)
_tmp.close()
_test_db = SQLiteDatabase(Path(_tmp.name))
_test_db.init_schema()
reset_db(_test_db)
