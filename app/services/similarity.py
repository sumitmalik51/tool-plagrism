"""Similarity service — thin wrapper delegating to tools layer.

Preserves backward compatibility with existing code that imports from
``app.services.similarity``.  All logic lives in
``app.tools.similarity_tool``.
"""

from app.tools.similarity_tool import (  # noqa: F401
    compute_overall_score,
    cosine_similarity_matrix,
    find_high_similarity_pairs,
)
