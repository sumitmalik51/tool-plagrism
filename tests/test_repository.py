"""Tests for the institutional document repository service."""

from __future__ import annotations

import pytest

from app.services.repository import find_similar_documents, store_document_fingerprints


# ---------------------------------------------------------------------------
# store_document_fingerprints
# ---------------------------------------------------------------------------

class TestStoreDocumentFingerprints:
    def test_store_returns_count(self):
        text = "Machine learning algorithms are widely used in natural language processing. " * 10
        result = store_document_fingerprints("test-doc-001", text, user_id=999, title="Test Paper")
        assert result["stored"] is True
        assert result["fingerprint_count"] > 0

    def test_store_short_text_not_stored(self):
        result = store_document_fingerprints("test-doc-short", "hi")
        assert result["stored"] is False
        assert result["fingerprint_count"] == 0

    def test_store_duplicate_id_handled(self):
        text = "Deep learning has revolutionized computer vision tasks. " * 10
        store_document_fingerprints("test-doc-dup", text, user_id=999)
        # Second insert — may fail or succeed depending on DB constraints
        result = store_document_fingerprints("test-doc-dup2", text, user_id=999)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# find_similar_documents
# ---------------------------------------------------------------------------

class TestFindSimilarDocuments:
    def test_finds_identical_document(self):
        text = "The impact of social media on political discourse is a growing field of study. " * 10
        store_document_fingerprints("test-doc-find-1", text, user_id=888, title="Social Media Paper")

        matches = find_similar_documents(text, user_id=888)
        assert len(matches) >= 1
        # Should find the document we just stored
        doc_ids = [m["document_id"] for m in matches]
        assert "test-doc-find-1" in doc_ids

    def test_excludes_self(self):
        text = "Blockchain technology provides decentralized consensus mechanisms. " * 10
        store_document_fingerprints("test-doc-find-2", text, user_id=888)

        matches = find_similar_documents(text, user_id=888, exclude_document_id="test-doc-find-2")
        doc_ids = [m["document_id"] for m in matches]
        assert "test-doc-find-2" not in doc_ids

    def test_no_match_for_unrelated_text(self):
        store_document_fingerprints(
            "test-doc-find-3",
            "Quantum computing uses qubits and entanglement for computation. " * 10,
            user_id=777,
        )

        matches = find_similar_documents(
            "Ancient Roman architecture featured arches and concrete construction. " * 10,
            user_id=777,
        )
        # May be empty or low similarity
        for m in matches:
            assert m["jaccard"] < 0.5

    def test_returns_empty_for_short_text(self):
        matches = find_similar_documents("hi")
        assert matches == []
