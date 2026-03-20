"""Tools layer — independent, framework-agnostic service functions.

Each tool module:
  • Is independently callable (no agent framework dependency)
  • Accepts clear inputs, returns structured JSON
  • Can be exposed via its own FastAPI endpoint
  • Is ready for Azure Foundry Agent orchestration
"""

from app.tools.ai_detection_tool import detect_ai_text
from app.tools.content_extractor_tool import chunk_text, extract_text
from app.tools.embedding_tool import generate_embeddings, generate_embeddings_sync
from app.tools.similarity_tool import (
    compute_overall_score,
    cosine_similarity_matrix,
    find_high_similarity_pairs,
    run_similarity_analysis,
)
from app.tools.web_search_tool import search_multiple, search_web

__all__ = [
    "detect_ai_text",
    "chunk_text",
    "extract_text",
    "generate_embeddings",
    "generate_embeddings_sync",
    "compute_overall_score",
    "cosine_similarity_matrix",
    "find_high_similarity_pairs",
    "run_similarity_analysis",
    "search_web",
    "search_multiple",
]
