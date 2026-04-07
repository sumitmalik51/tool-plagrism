"""Research Writer routes — graph-to-paragraph generation with plagiarism checking.

Endpoints:
  POST /api/v1/research-writer/generate   — generate paragraph from graph image
  POST /api/v1/research-writer/check      — deep plagiarism check on text
  POST /api/v1/research-writer/expand     — expand paragraph to full section
  POST /api/v1/research-writer/improve    — improve student's explanation
  GET  /api/v1/research-writer/versions/{session_id} — version history
  POST /api/v1/research-writer/caption    — standalone figure caption
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections import defaultdict
from typing import Any, Literal, Optional

import numpy as np
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.dependencies.rate_limit import enforce_rw_limit, record_usage
from app.services.auth_service import verify_access_token
from app.services.persistence import (
    rw_cache_get,
    rw_cache_set,
    rw_get_next_version_number,
    rw_get_user_embeddings,
    rw_get_versions,
    rw_store_embedding,
    rw_store_version,
)
from app.tools.research_writer_tool import (
    expand_section,
    generate_figure_caption,
    generate_paragraph,
    hash_request,
    improve_explanation,
    validate_image,
    fetch_image_from_url,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/research-writer", tags=["research-writer"])

# ═══════════════════════════════════════════════════════════════════════════
# Burst throttle (in-memory, per-user)
# ═══════════════════════════════════════════════════════════════════════════

_burst_log: dict[int, list[float]] = defaultdict(list)
_BURST_WINDOW = 60.0  # seconds
_BURST_LIMIT = 3      # max generates within window


def _check_burst(user_id: int) -> None:
    """Reject if user sent too many generate requests in the burst window."""
    now = time.time()
    timestamps = _burst_log[user_id]
    # Prune old entries
    _burst_log[user_id] = [t for t in timestamps if now - t < _BURST_WINDOW]
    if len(_burst_log[user_id]) >= _BURST_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests — please wait a moment before generating again.",
        )
    _burst_log[user_id].append(now)


# ═══════════════════════════════════════════════════════════════════════════
# Auth helper
# ═══════════════════════════════════════════════════════════════════════════

def _get_user_id(authorization: str) -> int:
    """Extract user_id from Bearer token.  Raises 401 on failure."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.removeprefix("Bearer ").strip()
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return int(payload["sub"])


# ═══════════════════════════════════════════════════════════════════════════
# Search result cache (in-memory, 10-min TTL)
# ═══════════════════════════════════════════════════════════════════════════

_search_cache: dict[str, tuple[list[dict], float]] = {}
_SEARCH_CACHE_TTL = 600.0  # 10 minutes


def _sanitize_text(text: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


# ═══════════════════════════════════════════════════════════════════════════
# Background task helpers (with error handling — no silent data loss)
# ═══════════════════════════════════════════════════════════════════════════

def _bg_store_cache(request_hash: str, user_id: int, response_json: str) -> None:
    try:
        rw_cache_set(request_hash, user_id, response_json)
        logger.debug("rw_cache_stored", hash=request_hash[:12])
    except Exception as e:
        logger.error("rw_cache_store_failed", hash=request_hash[:12], error=str(e))


async def _bg_store_embedding(user_id: int, paragraph: str, text_hash: str) -> None:
    try:
        from app.tools.embedding_tool import generate_embeddings
        embeddings = await generate_embeddings([paragraph])
        blob = embeddings[0].astype(np.float32).tobytes()
        rw_store_embedding(user_id, text_hash, paragraph, blob)
        logger.debug("rw_embedding_stored", user_id=user_id, hash=text_hash[:12])
    except Exception as e:
        logger.error("rw_embedding_store_failed", user_id=user_id, error=str(e))


def _bg_store_version(
    session_id: str, user_id: int, version_num: int,
    paragraph: str, section_type: str, level: str, image_hash: str,
) -> None:
    try:
        rw_store_version(session_id, user_id, version_num, paragraph, section_type, level, image_hash)
        logger.debug("rw_version_stored", session_id=session_id, version=version_num)
    except Exception as e:
        logger.error("rw_version_store_failed", session_id=session_id, error=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Image resolution helper
# ═══════════════════════════════════════════════════════════════════════════

async def _resolve_image(
    image: UploadFile | None,
    image_url: str | None,
    image_base64: str | None,
) -> tuple[str, str, float]:
    """Resolve image from exactly one of three sources → (b64, mime, quality)."""
    sources = sum(1 for s in (image, image_url, image_base64) if s)
    if sources == 0:
        raise HTTPException(status_code=422, detail="Provide an image (file, URL, or base64)")
    if sources > 1:
        raise HTTPException(status_code=422, detail="Provide only ONE image source")

    if image:
        file_bytes = await image.read()
        return validate_image(file_bytes)

    if image_url:
        return await fetch_image_from_url(image_url)

    if image_base64:
        # Handle data URI prefix: data:image/png;base64,...
        raw = image_base64
        if raw.startswith("data:"):
            raw = raw.split(",", 1)[-1]
        import base64 as b64mod
        try:
            file_bytes = b64mod.b64decode(raw)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid base64 image data")
        return validate_image(file_bytes)

    raise HTTPException(status_code=422, detail="No image provided")


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/generate",
    dependencies=[Depends(enforce_rw_limit("rw_generate"))],
)
async def generate_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: str = Header(...),
    image: UploadFile | None = File(None),
    image_url: str | None = Form(None),
    image_base64: str | None = Form(None),
    explanation: str = Form(...),
    section_type: str = Form("results"),
    citation_style: str = Form("apa"),
    tone: str = Form("academic"),
    level: str = Form("undergraduate"),
    session_id: str | None = Form(None),
):
    """Generate an academic paragraph from a graph image + explanation."""
    user_id = _get_user_id(authorization)

    # Abuse protection: explanation quality
    if len(explanation.strip()) < 20:
        raise HTTPException(status_code=422, detail="Explanation too short — describe what the graph shows (min 20 characters)")

    # Burst throttle
    _check_burst(user_id)

    # Resolve image
    try:
        b64, mime, quality = await _resolve_image(image, image_url, image_base64)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Cache check
    req_hash = hash_request(b64, explanation, section_type, level, tone, citation_style)
    cached = rw_cache_get(req_hash)
    if cached:
        logger.info("rw_cache_hit", hash=req_hash[:12])
        record_usage(request, tool_type="rw_generate", word_count=len(cached.get("paragraph", "").split()))
        return cached

    # Generate
    result = await generate_paragraph(
        image_base64=b64,
        mime_type=mime,
        explanation=explanation,
        section_type=section_type,
        citation_style=citation_style,
        tone=tone,
        level=level,
        image_quality_score=quality,
    )

    # Record usage
    word_count = len(result.get("paragraph", "").split())
    record_usage(request, tool_type="rw_generate", word_count=word_count)

    # Version management
    if not session_id:
        session_id = uuid.uuid4().hex
    result["session_id"] = session_id

    version_num = rw_get_next_version_number(session_id, user_id)
    result["version_number"] = version_num

    image_hash = hashlib.sha256(b64[:200].encode()).hexdigest()[:16]
    paragraph_text = result.get("paragraph", "")
    text_hash = hashlib.sha256(paragraph_text.encode()).hexdigest()

    # Background tasks (each independently wrapped — no silent data loss)
    background_tasks.add_task(_bg_store_cache, req_hash, user_id, json.dumps(result))
    background_tasks.add_task(_bg_store_embedding, user_id, paragraph_text, text_hash)
    background_tasks.add_task(
        _bg_store_version, session_id, user_id, version_num,
        paragraph_text, section_type, level, image_hash,
    )

    return result


@router.post(
    "/check",
    dependencies=[Depends(enforce_rw_limit("rw_check"))],
)
async def check_endpoint(
    request: Request,
    authorization: str = Header(...),
    body: dict = ...,
):
    """Deep plagiarism check on generated text."""
    user_id = _get_user_id(authorization)
    text = body.get("text", "")
    if not text or len(text.strip()) < 20:
        raise HTTPException(status_code=422, detail="Text too short for plagiarism check")

    start = time.perf_counter()
    text = _sanitize_text(text)

    # 1. Extract key phrases (2-3 sentence chunks)
    sentences = re.split(r'(?<=[.!?])\s+', text)
    phrases = []
    for i in range(0, len(sentences), 2):
        chunk = " ".join(sentences[i:i + 2]).strip()
        if len(chunk) > 30:
            phrases.append(chunk[:200])  # Cap phrase length
    phrases = phrases[:4]  # Max 4 phrases

    # 2. Web search with caching
    web_results: list[dict] = []
    from app.tools.web_search_tool import search_multiple, fetch_page_text

    uncached_phrases = []
    for phrase in phrases:
        phrase_hash = hashlib.sha256(phrase.encode()).hexdigest()
        now = time.time()
        if phrase_hash in _search_cache:
            cached_results, cached_at = _search_cache[phrase_hash]
            if now - cached_at < _SEARCH_CACHE_TTL:
                web_results.extend(cached_results)
                continue
        uncached_phrases.append((phrase, phrase_hash))

    if uncached_phrases:
        query_list = [p for p, _ in uncached_phrases]
        try:
            search_resp = await search_multiple(query_list, count_per_query=3)
            new_results = search_resp.get("results", [])
            # Cache results per phrase
            per_phrase = len(new_results) // max(len(query_list), 1)
            for idx, (_, ph) in enumerate(uncached_phrases):
                chunk_results = new_results[idx * per_phrase:(idx + 1) * per_phrase]
                _search_cache[ph] = (chunk_results, time.time())
            web_results.extend(new_results)
        except Exception as e:
            logger.warning("rw_check_search_failed", error=str(e))

    # 3. Fetch page content (top 5, limited to 5000 chars each)
    urls = list({r["url"] for r in web_results if r.get("url")})[:5]
    page_texts: dict[str, str] = {}
    if urls:
        try:
            page_texts = await fetch_page_text(urls, timeout=6.0, max_concurrent=5)
            # Truncate to 5000 chars
            page_texts = {u: t[:5000] for u, t in page_texts.items() if t}
        except Exception as e:
            logger.warning("rw_check_fetch_failed", error=str(e))

    # 4. Embed & compare
    max_web_sim = 0.0
    web_matches: list[dict] = []

    if page_texts:
        from app.tools.embedding_tool import generate_embeddings
        from app.tools.similarity_tool import cosine_similarity_matrix

        all_texts = [text] + list(page_texts.values())
        try:
            embeddings = await generate_embeddings(all_texts)
            text_emb = embeddings[:1]
            page_embs = embeddings[1:]
            sim_matrix = cosine_similarity_matrix(text_emb, page_embs)
            page_urls = list(page_texts.keys())
            for j, url in enumerate(page_urls):
                sim = float(sim_matrix[0, j])
                if sim > 0.2:
                    title = next((r.get("title", "") for r in web_results if r.get("url") == url), "")
                    web_matches.append({"url": url, "title": title, "similarity": round(sim, 3)})
                max_web_sim = max(max_web_sim, sim)
        except Exception as e:
            logger.warning("rw_check_embed_failed", error=str(e))

    # 5. Internal embedding store check
    internal_matches = 0
    max_internal_sim = 0.0
    try:
        stored = rw_get_user_embeddings(user_id)
        if stored:
            from app.tools.embedding_tool import generate_embeddings as gen_emb
            text_embedding = await gen_emb([text])
            for row in stored:
                stored_emb = np.frombuffer(row["embedding_blob"], dtype=np.float32)
                sim = float(np.dot(text_embedding[0], stored_emb) / (
                    np.linalg.norm(text_embedding[0]) * np.linalg.norm(stored_emb) + 1e-9
                ))
                if sim > 0.60:
                    internal_matches += 1
                max_internal_sim = max(max_internal_sim, sim)
    except Exception as e:
        logger.warning("rw_check_internal_failed", error=str(e))

    # 6. Final verdict (tiered thresholds)
    similarity_score = max(max_web_sim, max_internal_sim)
    if similarity_score < 0.30:
        verdict = "original"
    elif similarity_score < 0.60:
        verdict = "needs_review"
    else:
        verdict = "likely_plagiarized"

    web_matches.sort(key=lambda m: m["similarity"], reverse=True)
    elapsed = round(time.perf_counter() - start, 2)

    record_usage(request, tool_type="rw_check", word_count=len(text.split()))

    return {
        "is_original": similarity_score < 0.30,
        "similarity_score": round(similarity_score, 3),
        "verdict": verdict,
        "web_matches": web_matches[:5],
        "internal_matches": internal_matches,
        "elapsed_s": elapsed,
    }


@router.post(
    "/expand",
    dependencies=[Depends(enforce_rw_limit("rw_expand"))],
)
async def expand_endpoint(
    request: Request,
    authorization: str = Header(...),
    body: dict = ...,
):
    """Expand a paragraph into a full section."""
    _get_user_id(authorization)

    paragraph = body.get("paragraph", "")
    if len(paragraph.strip()) < 30:
        raise HTTPException(status_code=422, detail="Paragraph too short to expand")

    section_type = body.get("section_type", "results")
    target_length = body.get("target_length", "medium")
    level = body.get("level", "undergraduate")

    result = await expand_section(paragraph, section_type, target_length, level)
    record_usage(request, tool_type="rw_expand", word_count=result.get("word_count", 0))
    return result


@router.post(
    "/improve",
    dependencies=[Depends(enforce_rw_limit("rw_improve"))],
)
async def improve_endpoint(
    request: Request,
    authorization: str = Header(...),
    image: UploadFile | None = File(None),
    image_url: str | None = Form(None),
    image_base64: str | None = Form(None),
    explanation: str = Form(...),
):
    """Improve a student's graph explanation."""
    _get_user_id(authorization)

    try:
        b64, mime, _ = await _resolve_image(image, image_url, image_base64)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    improved = await improve_explanation(explanation, b64, mime)
    record_usage(request, tool_type="rw_improve", word_count=len(improved.split()))
    return {"improved_explanation": improved}


@router.get("/versions/{session_id}")
async def versions_endpoint(
    session_id: str,
    authorization: str = Header(...),
):
    """List version history for a generation session."""
    user_id = _get_user_id(authorization)
    versions = rw_get_versions(session_id, user_id)
    return {"session_id": session_id, "versions": versions}


@router.post(
    "/caption",
    dependencies=[Depends(enforce_rw_limit("rw_generate"))],
)
async def caption_endpoint(
    request: Request,
    authorization: str = Header(...),
    image: UploadFile | None = File(None),
    image_url: str | None = Form(None),
    image_base64: str | None = Form(None),
    explanation: str = Form(""),
):
    """Generate a figure caption from a graph image."""
    _get_user_id(authorization)

    try:
        b64, mime, _ = await _resolve_image(image, image_url, image_base64)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    caption = await generate_figure_caption(b64, mime, explanation)
    record_usage(request, tool_type="rw_generate", word_count=len(caption.split()))
    return {"caption": caption}
