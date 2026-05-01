"""Embedding tool — generates vector embeddings for text.

Standalone, framework-agnostic tool. Accepts clear inputs, returns structured JSON.
Can be called independently via API or by any orchestrator.
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from app.config import settings
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = get_logger(__name__)

# Single-worker executor so the model lock isn't contended by multiple
# threads spinning on acquire() and starving the event loop of GIL time.
_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    """Get or create the single-worker embedding executor."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="embedding-worker-"
        )
        logger.info("embedding_executor_created", max_workers=1)
    return _executor


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    """Load the sentence-transformer model once and cache it."""
    from sentence_transformers import SentenceTransformer as ST

    model_name = settings.embedding_model
    logger.info("loading_embedding_model", model=model_name)
    model = ST(model_name)
    logger.info("embedding_model_loaded", model=model_name)
    return model


def preload_model() -> None:
    """Eagerly load the embedding model (called at app startup)."""
    try:
        _load_model()
    except Exception as exc:
        logger.error("model_preload_failed", error=str(exc))


_BATCH_SIZE = 32  # Small batches so we release the GIL between them


def _embed_batch_sync(texts: list[str]) -> NDArray[np.float32]:
    """Generate embeddings for a SMALL batch synchronously (≤32 texts)."""
    model = _load_model()
    embeddings: NDArray[np.float32] = model.encode(
        texts,
        batch_size=_BATCH_SIZE,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embeddings


async def generate_embeddings(texts: list[str]) -> NDArray[np.float32]:
    """Generate normalized embeddings for a list of text strings.

    Splits the input into small batches and yields to the event loop
    between batches.  This prevents the GIL from being held for 10+
    seconds during tokenisation of large documents, keeping SSE
    heartbeats and health checks responsive.

    Uses a **single-worker** thread pool so only one batch runs at a
    time (the tokenizer is not thread-safe anyway), and competing
    threads don't spin on a lock starving the event loop.

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
    executor = _get_executor()

    # Split into small batches so the GIL is released between them,
    # allowing the event loop to process SSE keepalives / health checks.
    parts: list[NDArray[np.float32]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        emb = await loop.run_in_executor(executor, _embed_batch_sync, batch)
        parts.append(emb)
        # Yield control so queued coroutines (heartbeat, SSE, HTTP) run.
        await asyncio.sleep(0)

    embeddings = np.vstack(parts) if len(parts) > 1 else parts[0]
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
    embeddings = _embed_batch_sync(texts)
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
