"""Embedding service — thin wrapper delegating to tools layer.

Preserves backward compatibility with existing code that imports from
``app.services.embeddings``.  All logic lives in
``app.tools.embedding_tool``.
"""

from __future__ import annotations

from app.tools.embedding_tool import generate_embeddings  # noqa: F401
