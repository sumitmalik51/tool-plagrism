"""Embedding tool — generates vector embeddings for text.

Standalone, framework-agnostic tool. Accepts clear inputs, returns structured JSON.
Can be called independently via API or by any orchestrator.
"""

from __future__ import annotations

import asyncio
import time
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from app.config import settings
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    """Load the sentence-transformer model once and cache it."""
    from sentence_transformers import SentenceTransformer as ST

    model_name = settings.embedding_model
    logger.info("loading_embedding_model", model=model_name)
    model = ST(model_name)
    logger.info("embedding_model_loaded", model=model_name)
    return model


def _embed_sync(texts: list[str]) -> NDArray[np.float32]:
    """Generate embeddings synchronously (CPU-bound)."""
    model = _load_model()
    embeddings: NDArray[np.float32] = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embeddings


async def generate_embeddings(texts: list[str]) -> NDArray[np.float32]:
    """Generate normalized embeddings for a list of text strings.

    Runs the model in a thread-pool executor to avoid blocking the event loop.

    Args:
        texts: List of text chunks to embed.

    Returns:
        A 2-D numpy array of shape ``(len(texts), embedding_dim)``
        with L2-normalized vectors.
    """
    if not texts:
        return np.empty((0, 0), dtype=np.float32)

    start = time.perf_counter()
    loop = asyncio.get_running_loop()
    embeddings = await loop.run_in_executor(None, _embed_sync, texts)
    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "embeddings_generated",
        count=len(texts),
        dim=embeddings.shape[1],
        elapsed_s=elapsed,
    )
    return embeddings


def generate_embeddings_sync(texts: list[str]) -> dict:
    """Synchronous wrapper that returns structured JSON output.

    Returns:
        Dict with ``count``, ``dimension``, and ``embeddings`` (as nested lists).
    """
    if not texts:
        return {"count": 0, "dimension": 0, "embeddings": []}

    start = time.perf_counter()
    embeddings = _embed_sync(texts)
    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "embeddings_generated_sync",
        count=len(texts),
        dim=embeddings.shape[1],
        elapsed_s=elapsed,
    )

    return {
        "count": len(texts),
        "dimension": int(embeddings.shape[1]),
        "embeddings": embeddings.tolist(),
        "elapsed_s": elapsed,
    }
