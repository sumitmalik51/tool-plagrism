"""Tests for the .docx export endpoint."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


class TestExportDocx:
    def test_export_basic(self):
        """POST /api/v1/rewrite/export-docx returns a valid .docx file."""
        res = client.post(
            "/api/v1/rewrite/export-docx",
            json={
                "original": "The quick brown fox jumps over the lazy dog.",
                "rewritten": "A swift brown fox leaps over the idle dog.",
                "title": "Test Document",
                "show_changes": False,
            },
        )
        assert res.status_code == 200
        assert "wordprocessingml.document" in res.headers["content-type"]
        assert "attachment" in res.headers.get("content-disposition", "")
        # Verify it's a valid zip file (docx is a ZIP)
        content = res.content
        assert content[:2] == b"PK"

    def test_export_with_track_changes(self):
        """show_changes=True should still produce a valid .docx."""
        res = client.post(
            "/api/v1/rewrite/export-docx",
            json={
                "original": "Original paragraph one.\nOriginal paragraph two.",
                "rewritten": "Rewritten paragraph one.\nRewritten paragraph two.",
                "show_changes": True,
            },
        )
        assert res.status_code == 200
        assert res.content[:2] == b"PK"

    def test_export_default_title(self):
        """Omitting title should default to 'Rewritten Document'."""
        res = client.post(
            "/api/v1/rewrite/export-docx",
            json={
                "original": "Hello world.",
                "rewritten": "Greetings, world.",
            },
        )
        assert res.status_code == 200
        assert "rewritten_document.docx" in res.headers.get("content-disposition", "").lower()

    def test_export_empty_original_rejected(self):
        """Empty original text should be rejected by validation."""
        res = client.post(
            "/api/v1/rewrite/export-docx",
            json={
                "original": "",
                "rewritten": "Some text.",
            },
        )
        assert res.status_code == 422

    def test_export_empty_rewritten_rejected(self):
        """Empty rewritten text should be rejected by validation."""
        res = client.post(
            "/api/v1/rewrite/export-docx",
            json={
                "original": "Some text.",
                "rewritten": "",
            },
        )
        assert res.status_code == 422

    def test_export_docx_contains_text(self):
        """Verify the .docx actually contains the rewritten text."""
        from docx import Document

        res = client.post(
            "/api/v1/rewrite/export-docx",
            json={
                "original": "Alpha bravo charlie.",
                "rewritten": "Delta echo foxtrot.",
                "show_changes": False,
            },
        )
        assert res.status_code == 200
        doc = Document(io.BytesIO(res.content))
        full_text = "\n".join(p.text for p in doc.paragraphs)
        assert "Delta echo foxtrot" in full_text
